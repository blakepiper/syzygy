"""`syzygy dev animate`, the bench itself (M17.2e).

What a headless test can say about it is narrow and worth saying anyway:
every entry in the catalogue plays without raising, and the catalogue
covers the whole vocabulary. What it cannot say - whether any of it is
*visible* - is the entire reason the bench exists, and is a job for an eye
on a real terminal.
"""

from __future__ import annotations

from textual.widgets import ListView

from syzygy.tui.animation.events import SemanticEvent
from syzygy.tui.animation.motion import MotionLevel
from syzygy.tui.screens.animation_demo import AnimationDemoApp, DemoItem


async def test_every_entry_plays_without_raising():
    app = AnimationDemoApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        listing = app.query_one("#demo-list", ListView)
        assert listing.children

        for index in range(len(listing.children)):
            listing.index = index
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            app.animations.animator.finish_all()
            await pilot.pause()


async def test_the_catalogue_covers_every_semantic_event():
    app = AnimationDemoApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        labels = [
            item.label_text for item in app.query_one("#demo-list", ListView).query(DemoItem)
        ]

    for event in SemanticEvent:
        assert any(event.value in label for label in labels), event
    # And the named choreographies, which are the ones a screen owns.
    for name in ("startup", "enter-screen", "draw-complete", "ritual-reveal"):
        assert any(name in label for label in labels), name


async def test_the_bench_cycles_motion_for_this_process_only(tmp_path, monkeypatch):
    """A bench must not rewrite the settings of the application it is a
    bench for."""
    from syzygy import settings as settings_module

    written: list[object] = []
    monkeypatch.setattr(
        settings_module, "save_section", lambda *args, **kwargs: written.append(args)
    )

    app = AnimationDemoApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.animations.motion.level is MotionLevel.FULL
        await pilot.press("f2")
        await pilot.pause()
        assert app.animations.motion.level is MotionLevel.REDUCED

    assert written == []
