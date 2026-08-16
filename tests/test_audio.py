"""The looping theme (M15).

The thing most worth testing here is what happens when audio *doesn't*
work, because that is the common case: CI has no audio device, the extra
is optional, and a terminal divination app must never fail to start over
a sound card. Every one of those paths has to end at `SilentTheme`.
"""

from __future__ import annotations

import json

import pytest

from syzygy.audio import (
    AUDIO_SECTION,
    DEFAULT_VOLUME,
    LoopingTheme,
    SilentTheme,
    ThemePlayer,
    create_theme_player,
    load_muted,
    save_muted,
)


class FakePlayback:
    """Stands in for `just_playback.Playback`, recording what it was told."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.active = False
        self.volume = 1.0
        self.looping = False

    def load_file(self, path: str) -> None:
        self.calls.append(f"load:{path}")

    def loop_at_end(self, loop: bool) -> None:
        self.looping = loop

    def set_volume(self, volume: float) -> None:
        self.volume = volume

    def play(self) -> None:
        self.calls.append("play")
        self.active = True

    def pause(self) -> None:
        self.calls.append("pause")

    def resume(self) -> None:
        self.calls.append("resume")

    def stop(self) -> None:
        self.calls.append("stop")
        self.active = False


@pytest.fixture
def settings_path(tmp_path):
    return tmp_path / "settings.json"


# -- degrading to silence (M15.1e) ---------------------------------------


def test_the_no_audio_flag_skips_playback_entirely(settings_path):
    player = create_theme_player(settings_path, enabled=False)
    assert isinstance(player, SilentTheme)
    assert player.available is False


def test_a_missing_extra_degrades_to_silence(settings_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_just_playback(name, *args, **kwargs):
        if name == "just_playback":
            raise ImportError("No module named 'just_playback'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_just_playback)

    player = create_theme_player(settings_path)
    assert isinstance(player, SilentTheme)
    assert "audio` extra" in player.reason


def test_a_backend_that_raises_degrades_to_silence(settings_path, monkeypatch):
    """No device, a driver error, an unsupported format - all the same
    answer."""

    class Exploding:
        def __init__(self) -> None:
            raise RuntimeError("no audio device")

    monkeypatch.setattr("just_playback.Playback", Exploding)

    player = create_theme_player(settings_path)
    assert isinstance(player, SilentTheme)
    assert "no audio device" in player.reason


def test_silence_satisfies_the_whole_interface(settings_path):
    """Callers must not need to check which implementation they have."""
    player: ThemePlayer = SilentTheme("testing")
    player.start()
    assert player.toggle_mute() is True
    player.play_notification()
    player.stop()
    assert player.muted is True


# -- the real player, with a fake backend --------------------------------


def _looping(settings_path, *, muted: bool = False) -> tuple[LoopingTheme, FakePlayback]:
    playback = FakePlayback()
    return LoopingTheme(playback, settings_path, muted=muted), playback


def _looping_with_notification(
    settings_path, *, muted: bool = False
) -> tuple[LoopingTheme, FakePlayback, FakePlayback]:
    playback = FakePlayback()
    notification = FakePlayback()
    theme = LoopingTheme(
        playback,
        settings_path,
        muted=muted,
        notification_playback=notification,
    )
    return theme, playback, notification


def test_start_plays_and_is_idempotent(settings_path):
    theme, playback = _looping(settings_path)
    theme.start()
    theme.start()
    assert playback.calls == ["play"]


def test_start_while_muted_plays_nothing(settings_path):
    theme, playback = _looping(settings_path, muted=True)
    theme.start()
    assert playback.calls == []


def test_notification_plays_without_interrupting_the_theme(settings_path):
    theme, playback, notification = _looping_with_notification(settings_path)
    theme.start()
    theme.play_notification()

    assert playback.calls == ["play"]
    assert notification.calls == ["play"]


def test_notification_respects_mute(settings_path):
    theme, _, notification = _looping_with_notification(settings_path)
    theme.toggle_mute()
    theme.play_notification()

    assert notification.calls == ["stop"]


def test_mute_pauses_rather_than_stopping(settings_path):
    """Pause holds the position, so unmuting continues the track instead
    of restarting a 2:47 loop from the top."""
    theme, playback = _looping(settings_path)
    theme.start()

    assert theme.toggle_mute() is True
    assert playback.calls == ["play", "pause"]

    assert theme.toggle_mute() is False
    assert playback.calls == ["play", "pause", "resume"]


def test_unmuting_before_start_does_not_play(settings_path):
    theme, playback = _looping(settings_path, muted=True)
    theme.toggle_mute()
    assert playback.calls == []


def test_unmuting_after_the_track_ended_starts_it_again(settings_path):
    theme, playback = _looping(settings_path)
    theme.start()
    theme.toggle_mute()
    playback.active = False  # backend finished while muted

    theme.toggle_mute()
    assert playback.calls[-1] == "play"


def test_stop_is_idempotent(settings_path):
    theme, playback = _looping(settings_path)
    theme.start()
    theme.stop()
    theme.stop()
    assert playback.calls.count("stop") == 2  # cheap, and safe to repeat
    assert playback.active is False


def test_stop_also_stops_a_notification(settings_path):
    theme, _, notification = _looping_with_notification(settings_path)
    theme.play_notification()
    theme.stop()

    assert notification.calls == ["play", "stop"]


def test_a_backend_that_throws_mid_session_does_not_propagate(settings_path):
    """A headset unplugged, a laptop resumed from suspend."""

    class Breaking(FakePlayback):
        def pause(self) -> None:
            raise OSError("device disappeared")

    theme = LoopingTheme(Breaking(), settings_path, muted=False)
    theme.start()
    assert theme.toggle_mute() is True  # no exception


# -- the persisted preference (M15.1d) -----------------------------------


def test_mute_defaults_to_off(settings_path):
    assert load_muted(settings_path) is False
    assert load_muted(None) is False


def test_mute_round_trips(settings_path):
    save_muted(settings_path, True)
    assert load_muted(settings_path) is True
    save_muted(settings_path, False)
    assert load_muted(settings_path) is False


def test_toggling_persists_the_preference(settings_path):
    theme, _ = _looping(settings_path)
    theme.start()
    theme.toggle_mute()

    assert load_muted(settings_path) is True
    assert json.loads(settings_path.read_text())[AUDIO_SECTION] == {"muted": True}


def test_a_new_player_honours_the_saved_preference(settings_path, monkeypatch):
    save_muted(settings_path, True)
    monkeypatch.setattr("just_playback.Playback", FakePlayback)

    player = create_theme_player(settings_path)
    assert player.muted is True


def test_the_player_sets_a_restrained_volume_and_loops(settings_path, monkeypatch):
    monkeypatch.setattr("just_playback.Playback", FakePlayback)

    player = create_theme_player(settings_path)
    assert isinstance(player, LoopingTheme)
    assert player._playback.volume == DEFAULT_VOLUME
    assert player._playback.looping is True


def test_an_unwritable_settings_file_does_not_break_the_toggle(tmp_path):
    """The toggle still applies for the session; only persistence fails."""
    unwritable = tmp_path / "nope" / "settings.json"
    unwritable.parent.mkdir()
    unwritable.parent.chmod(0o500)
    try:
        theme, _ = _looping(unwritable)
        theme.start()
        assert theme.toggle_mute() is True
    finally:
        unwritable.parent.chmod(0o700)


# -- settings sharing (the reason `syzygy.settings` exists) --------------


def test_audio_and_provider_settings_coexist(settings_path):
    """Before M15 the settings file *was* the provider selection, so a
    second setting would have destroyed it on the next write."""
    from syzygy.interpretation.providers.selection import (
        ProviderSelection,
        load_selection,
        save_selection,
    )

    save_selection(settings_path, ProviderSelection(provider_id="openai", model_id="gpt-4o-mini"))
    save_muted(settings_path, True)

    selection = load_selection(settings_path)
    assert selection is not None
    assert selection.provider_id == "openai"
    assert load_muted(settings_path) is True

    # ...and in the other order.
    save_selection(settings_path, ProviderSelection(provider_id="llama_cpp"))
    assert load_muted(settings_path) is True


def test_a_legacy_flat_settings_file_still_loads(settings_path):
    """Existing installs have the pre-M15 shape on disk."""
    from syzygy.interpretation.providers.selection import load_selection

    settings_path.write_text('{"provider_id": "anthropic", "model_id": "claude-test"}')

    selection = load_selection(settings_path)
    assert selection is not None
    assert selection.provider_id == "anthropic"


def test_a_corrupt_settings_file_reads_as_no_preferences(settings_path):
    settings_path.write_text("{not json at all")
    assert load_muted(settings_path) is False
