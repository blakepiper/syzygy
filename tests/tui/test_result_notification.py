"""The result-ready cue for the two slow interpretation paths."""

from __future__ import annotations

from syzygy.tui.app import SyzygyApp

from .test_oracle import complete_oracle
from .test_ritual_flow import FailingProvider, settle, turn_the_wheel


class RecordingTheme:
    available = True

    def __init__(self) -> None:
        self._muted = False
        self.calls: list[str] = []

    @property
    def muted(self) -> bool:
        return self._muted

    def start(self) -> None:
        self.calls.append("start")

    def toggle_mute(self) -> bool:
        self._muted = not self._muted
        return self._muted

    def play_notification(self) -> None:
        self.calls.append("notification")

    def stop(self) -> None:
        self.calls.append("stop")


async def test_daily_reading_cues_when_interpretation_is_complete(services, profile) -> None:
    theme = RecordingTheme()
    app = SyzygyApp(services, theme_player=theme)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)

        assert theme.calls.count("notification") == 1


async def test_oracle_cues_when_interpretation_is_complete(services, profile) -> None:
    theme = RecordingTheme()
    app = SyzygyApp(services, theme_player=theme)
    async with app.run_test() as pilot:
        await settle(pilot)
        await complete_oracle(pilot)

        assert theme.calls.count("notification") == 1


async def test_an_interpretation_failure_does_not_cue(services, profile) -> None:
    services.provider = FailingProvider()
    theme = RecordingTheme()
    app = SyzygyApp(services, theme_player=theme)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)

        assert "notification" not in theme.calls
