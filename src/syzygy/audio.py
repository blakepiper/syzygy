"""The theme and result-ready cue, looping under the whole application (M15).

## Why this library

Playback needs an MP3 decoder and an audio device, neither of which the
standard library has. Two shapes were considered:

- **Shell out to a system player** (`ffplay`, `mpv`, `afplay`, …). No
  dependency at all, and killing a subprocess is a very clean "stop". But
  no player is guaranteed present, the flags differ per player, Windows
  has no standard one, and muting means killing the process and losing
  the playback position - restarting a 2:47 track from the top every time
  someone toggles the key.
- **A small audio library.** `just_playback`
  (MIT, so AGPL-compatible) wraps miniaudio and ships prebuilt wheels for
  glibc and musl Linux, macOS on both architectures, and Windows, so it
  needs no compiler on any mainstream target. It decodes MP3 itself, and
  gives real `pause`/`resume` that hold position - which is what makes the
  mute key feel like a mute key.

The second is bundled in the main install so the shipped theme works without
a second installation step.

## Nothing here is allowed to matter

A terminal divination app must not fail to start because it cannot open
an audio device. Every failure - damaged dependency, no device, headless
CI, a corrupt file, a backend that raises on some platform we have never
seen - resolves to `SilentTheme`, which satisfies the same interface and
does nothing. `start()` never raises, and neither does anything else here.

Playback runs on the library's own thread, so it never blocks the event
loop; `syzygy.tui` only ever calls `toggle_mute()`/`play_notification()`/`stop()`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from syzygy.settings import AUDIO_SECTION, load_section, save_section

__all__ = [
    "AUDIO_SECTION",
    "DEFAULT_VOLUME",
    "LoopingTheme",
    "NOTIFICATION_RESOURCE",
    "SilentTheme",
    "ThemePlayer",
    "create_theme_player",
    "load_muted",
    "save_muted",
]

RESOURCE_PACKAGE: Final = "syzygy.resources"
THEME_RESOURCE: Final = "audio/theme.mp3"
NOTIFICATION_RESOURCE: Final = "audio/notification.wav"

#: Background music under a text interface should sit well under speech
#: level. Not user-configurable yet: the mute key is the control that was
#: asked for, and a volume slider is a preference surface nobody requested.
DEFAULT_VOLUME: Final = 0.35


@runtime_checkable
class ThemePlayer(Protocol):
    """What the application needs of the theme. Deliberately tiny."""

    @property
    def available(self) -> bool:
        """Whether sound can actually be produced. `False` means every
        other method is a no-op and the UI should say nothing about
        audio."""

    @property
    def muted(self) -> bool: ...

    def start(self) -> None:
        """Begin looping. Idempotent."""

    def toggle_mute(self) -> bool:
        """Flip mute, persist it, and return the new muted state."""

    def stop(self) -> None:
        """Stop and release the device. Idempotent."""

    def play_notification(self) -> None:
        """Play the short cue used when an interpretation is ready."""


class SilentTheme:
    """The no-audio implementation, and the fallback for every failure.

    Reports `available = False` so callers can hide the mute key rather
    than offer one that does nothing.
    """

    available = False

    def __init__(self, reason: str = "") -> None:
        self.reason = reason
        self._muted = True

    @property
    def muted(self) -> bool:
        return self._muted

    def start(self) -> None:
        return None

    def toggle_mute(self) -> bool:
        return True

    def stop(self) -> None:
        return None

    def play_notification(self) -> None:
        return None


class LoopingTheme:
    """`just_playback` behind the `ThemePlayer` interface.

    Mute is `pause`, not `stop`: the position is held, so unmuting
    continues the track rather than restarting it. The device stays open
    while muted, which is the trade that makes the toggle instant.
    """

    available = True

    def __init__(
        self,
        playback: object,
        settings_path: Path | None,
        *,
        muted: bool,
        notification_playback: object | None = None,
    ) -> None:
        # Typed as `object` because `just_playback` has no stubs and must
        # not be imported at module load - see `create_theme_player`.
        self._playback = playback
        self._settings_path = settings_path
        self._muted = muted
        self._started = False
        self._notification_playback = notification_playback

    @property
    def muted(self) -> bool:
        return self._muted

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self._muted:
            # Nothing to hear yet, but the file is loaded and the first
            # unmute is immediate.
            return
        self._safely(lambda: self._playback.play())  # type: ignore[attr-defined]

    def toggle_mute(self) -> bool:
        self._muted = not self._muted
        if self._muted:
            self._safely(lambda: self._playback.pause())  # type: ignore[attr-defined]
            if self._notification_playback is not None:
                self._safely(lambda: self._notification_playback.stop())  # type: ignore[attr-defined]
        elif self._started:
            self._resume_or_play()
        self._persist()
        return self._muted

    def _resume_or_play(self) -> None:
        def resume() -> None:
            if self._playback.active:  # type: ignore[attr-defined]
                self._playback.resume()  # type: ignore[attr-defined]
            else:
                self._playback.play()  # type: ignore[attr-defined]

        self._safely(resume)

    def stop(self) -> None:
        self._started = False
        self._safely(lambda: self._playback.stop())  # type: ignore[attr-defined]
        if self._notification_playback is not None:
            self._safely(lambda: self._notification_playback.stop())  # type: ignore[attr-defined]

    def play_notification(self) -> None:
        """Play the one-shot result-ready cue without interrupting the theme."""
        if self._muted or self._notification_playback is None:
            return
        self._safely(lambda: self._notification_playback.play())  # type: ignore[attr-defined]

    def _persist(self) -> None:
        if self._settings_path is None:
            return
        try:
            save_section(self._settings_path, AUDIO_SECTION, {"muted": self._muted})
        except OSError:
            # An unwritable settings file is not worth interrupting a
            # reading over; the toggle still applied for this session.
            pass

    @staticmethod
    def _safely(action) -> None:
        """Run `action`, swallowing anything the backend throws.

        A device that disappears mid-session (a headset unplugged, a
        suspended laptop) must not take the interface down with it.
        """
        try:
            action()
        except Exception:
            pass


def load_muted(settings_path: Path | None) -> bool:
    """The persisted mute preference. Defaults to **unmuted**: the theme
    is an explicit part of the product, and the mute key is advertised on
    the welcome screen for anyone who disagrees."""
    if settings_path is None:
        return False
    return bool(load_section(settings_path, AUDIO_SECTION).get("muted", False))


def save_muted(settings_path: Path, muted: bool) -> None:
    save_section(settings_path, AUDIO_SECTION, {"muted": muted})


def _resource_path(resource_name: str) -> Path | None:
    """A real filesystem path to a bundled audio resource.

    `just_playback` opens a file by name, so unlike every other bundled
    resource these cannot be read straight out of a zipped wheel. The
    common case (a normal install, or an editable checkout) is a real
    file on disk and this returns it directly; for a zip import it returns
    `None` and the app runs silent rather than unpacking megabytes to a
    temporary directory at startup.
    """
    from importlib import resources

    try:
        resource = resources.files(RESOURCE_PACKAGE).joinpath(resource_name)
        path = Path(str(resource))
    except (ModuleNotFoundError, TypeError, OSError):
        return None
    return path if path.is_file() else None


def _theme_path() -> Path | None:
    """A real filesystem path to the bundled looping theme."""
    return _resource_path(THEME_RESOURCE)


def _notification_playback(playback_type: type, path: Path | None) -> object | None:
    """Best-effort construction of the independent result-ready player.

    The cue is a convenience layered on top of the theme. A bad or missing
    cue must leave the main theme usable, so this failure is intentionally
    isolated from `create_theme_player`'s main playback construction.
    """
    if path is None:
        return None
    try:
        playback = playback_type()
        playback.load_file(str(path))
        playback.loop_at_end(False)
        playback.set_volume(DEFAULT_VOLUME)
        return playback
    except Exception:
        return None


def create_theme_player(
    settings_path: Path | None = None, *, enabled: bool = True
) -> ThemePlayer:
    """The theme player for this machine, or `SilentTheme` if it cannot
    have one. Never raises.

    `enabled=False` (the `--no-audio` flag) skips even trying, which is
    also what a test or a CI run wants.
    """
    if not enabled:
        return SilentTheme("audio disabled")

    try:
        from just_playback import Playback
    except ImportError:
        return SilentTheme("the `audio` extra is not installed")

    # `just_playback` calls `logging.basicConfig(level=INFO)` at import
    # time, which hands the root logger a stderr handler and turns every
    # dependency's INFO chatter into text painted over the interface. The
    # entry points configure logging before this is ever reached; this is
    # the belt to that braces, next to the import that causes it.
    from syzygy.logs import quiet_library_logging

    quiet_library_logging()

    path = _theme_path()
    if path is None:
        return SilentTheme("the bundled theme is not readable as a file")

    try:
        playback = Playback()
        playback.load_file(str(path))
        playback.loop_at_end(True)
        playback.set_volume(DEFAULT_VOLUME)
    except Exception as exc:  # no device, unsupported format, driver error
        return SilentTheme(f"{type(exc).__name__}: {exc}")

    notification = _notification_playback(Playback, _resource_path(NOTIFICATION_RESOURCE))
    return LoopingTheme(
        playback,
        settings_path,
        muted=load_muted(settings_path),
        notification_playback=notification,
    )
