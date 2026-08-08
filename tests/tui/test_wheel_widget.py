"""The Wheel widget's event contract.

The Wheel is a real interaction, not a themed "Randomize" button
(DESIGN.md section 33's UX invariants), and it must remain incapable of
choosing a card on its own (ARCHITECTURE_HANDOFF.md section 31). Both
properties are asserted here rather than left to code review.
"""

from __future__ import annotations

import ast
import inspect

from textual.app import App, ComposeResult
from textual.message import Message

from syzygy.sortes.entropy import EntropyCollector
from syzygy.tui.widgets import wheel as wheel_module
from syzygy.tui.widgets.wheel import (
    WheelDisturbance,
    WheelImpulse,
    WheelNotReady,
    WheelRelease,
    WheelWidget,
)


class WheelHarness(App[None]):
    """A bare app holding one Wheel, recording what it posts."""

    def __init__(self) -> None:
        super().__init__()
        self.collector = EntropyCollector()
        self.messages: list[Message] = []

    def compose(self) -> ComposeResult:
        yield WheelWidget(self.collector, id="wheel")

    def on_wheel_impulse(self, event: WheelImpulse) -> None:
        self.messages.append(event)

    def on_wheel_disturbance(self, event: WheelDisturbance) -> None:
        self.messages.append(event)

    def on_wheel_release(self, event: WheelRelease) -> None:
        self.messages.append(event)

    def on_wheel_not_ready(self, event: WheelNotReady) -> None:
        self.messages.append(event)

    def of_type(self, message_type: type[Message]) -> list[Message]:
        return [m for m in self.messages if isinstance(m, message_type)]


async def test_impulses_record_entropy_and_post_messages():
    app = WheelHarness()
    async with app.run_test() as pilot:
        await pilot.press("space", "space")
        await pilot.pause()

        assert app.collector.event_count == 2
        assert len(app.of_type(WheelImpulse)) == 2
        wheel = app.query_one("#wheel", WheelWidget)
        assert wheel.impulses == 2
        assert wheel.momentum > wheel_module.IDLE_SPEED


async def test_arrow_keys_disturb_phase():
    app = WheelHarness()
    async with app.run_test() as pilot:
        await pilot.press("left", "right")
        await pilot.pause()

        directions = [m.direction for m in app.of_type(WheelDisturbance)]
        assert directions == [-1, 1]
        assert app.collector.event_count == 2


async def test_release_requires_the_wheel_to_be_turning():
    app = WheelHarness()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()

        wheel = app.query_one("#wheel", WheelWidget)
        assert app.of_type(WheelNotReady)
        assert not app.of_type(WheelRelease)
        assert not wheel.released
        # Even a refused release contributed its timing to the pool.
        assert app.collector.event_count == 1


async def test_release_happens_once_and_then_ignores_input():
    app = WheelHarness()
    async with app.run_test() as pilot:
        await pilot.press("space", "space", "space", "enter")
        await pilot.pause()

        wheel = app.query_one("#wheel", WheelWidget)
        assert wheel.released
        assert len(app.of_type(WheelRelease)) == 1

        events_at_release = app.collector.event_count
        await pilot.press("space", "enter", "left")
        await pilot.pause()
        assert len(app.of_type(WheelRelease)) == 1
        assert wheel.impulses == 3
        assert app.collector.event_count == events_at_release


async def test_unbound_printable_keys_also_contribute_entropy():
    app = WheelHarness()
    async with app.run_test() as pilot:
        await pilot.press("k", "x")
        await pilot.pause()
        assert app.collector.event_count == 2
        assert len(app.of_type(WheelImpulse)) == 2


async def test_widget_cannot_select_a_card():
    """The Wheel collects entropy; `syzygy.sortes` decides the card."""
    tree = ast.parse(inspect.getsource(wheel_module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    assert "syzygy.sortes.draw" not in imported  # no card selection
    assert "syzygy.sortes.deck" not in imported  # no knowledge of the deck
    assert "random" not in imported and "secrets" not in imported  # no entropy of its own
    assert "syzygy.sortes.entropy" in imported  # collection only

    # And the release message carries no result of any kind: it adds no
    # constructor and therefore no payload to Textual's base Message.
    assert "__init__" not in vars(WheelRelease)


async def test_renders_at_any_size():
    app = WheelHarness()
    async with app.run_test(size=(60, 18)) as pilot:
        wheel = app.query_one("#wheel", WheelWidget)
        strip = wheel.render_line(5)
        assert strip.cell_length == wheel.size.width

        await pilot.resize_terminal(30, 10)
        await pilot.pause()
        strip = wheel.render_line(2)
        assert strip.cell_length == wheel.size.width
