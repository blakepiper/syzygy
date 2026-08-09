"""Shared screen scaffolding.

Screens reach the application's collaborators (database connection, clock,
astrology engine, interpretation provider) through `SyzygyScreen.syzygy`
rather than importing or constructing any of them - the app owns the wiring
so tests can substitute a fixture engine and provider wholesale.

Three cross-cutting behaviours live here rather than in each screen,
because a screen that forgets one of them is a defect nobody notices
until it ships: the layout tiers (M12.5d), directional focus (M17.5), and
the selection marker on a list row (M17.4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, ListView, Static

from syzygy.tui.animation.events import SemanticEvent
from syzygy.tui.widgets.marked_list import MarkedListItem

if TYPE_CHECKING:
    from syzygy.tui.app import SyzygyApp


#: The layout tiers (M12.5d). Three of them, defined here and nowhere
#: else - `syzygy.tcss` styles the `-compact`/`-wide` classes this module
#: sets, and M14's animations and the too-small gate use the same numbers
#: rather than picking their own.
#:
#:   below 80x24          the floor. `syzygy.tui.screens.too_small` takes
#:                        over; no layout is expected to work down there.
#:   80x24 - 99x31        `-compact`. Same content, same shape, trimmed
#:                        padding. Nothing may be hidden that carries
#:                        information (docs/old/DESIGN.md section 18.6).
#:   100x32 - 119 wide    the regular tier, no class. One column.
#:   120 wide and up      `-wide`. Screens go multi-column: the space
#:                        exists, so it gets used rather than padded
#:                        around (M12.5).
#:
#: docs/old/DESIGN.md section 18.6's ideal terminal size. At or above this, a
#: screen renders at full size; below it (but still at or above the
#: compact floor in `syzygy.tui.screens.too_small`), screens get a
#: `-compact` class to trim padding/decoration rather than truncating.
IDEAL_WIDTH = 100
IDEAL_HEIGHT = 32

#: Width at which a screen has room for parallel columns. Chosen from the
#: narrowest thing that has to fit beside another: `HomeScreen`'s SELF
#: column is an anchor line like "☉ Sun    ♍ Virgo      14°22'" at ~36
#: cells, and three of those plus padding need 120. Below it the same
#: content stacks - the wide layouts are a second arrangement of the same
#: widgets, never a second set of them.
WIDE_WIDTH = 120

#: Height at which a screen has rows to spare, as `-tall`. Separate from
#: `-wide` because the two are independent: a 200x30 terminal is wide and
#: not tall, and a 90x60 one is the reverse. Only objects whose size is
#: bounded by rows rather than columns should use it - today that is the
#: reveal's card, which is the whole point of that screen and was sitting
#: at a third of the height of a full-screen terminal.
TALL_HEIGHT = 48


class SyzygyScreen(Screen[None]):
    """A screen with typed access back to the Syzygy application.

    Also owns layout-tier detection (docs/old/DESIGN.md section 18.6, M12.5d) in
    one place, via `on_screen_resume`/`on_resize`, rather than each screen
    measuring itself. A subclass that overrides `on_screen_resume` must
    call `super().on_screen_resume()` to keep this working.
    """

    @property
    def syzygy(self) -> SyzygyApp:
        # `App` is generic over its return type only, so the concrete app
        # type has to be asserted here rather than parameterized.
        return cast("SyzygyApp", self.app)

    #: Whether this screen gets the default entry/exit transition
    #: (M17.2a). Screens that own their own choreography - the reveal's
    #: staged sequence, the Wheel, the opening sequence itself - set this
    #: to False rather than animating twice.
    SCREEN_TRANSITIONS = True

    def on_screen_resume(self) -> None:
        self._update_size_classes()
        self._animate_entry()

    def on_screen_suspend(self) -> None:
        """Leaving reads as a move, not a cut (M17.2b).

        Nothing waits on this. The screen switch has already been asked
        for by the time this runs, and a dropped frame leaves the outgoing
        screen dimmed at worst - never a user stranded on it.
        """
        if self.SCREEN_TRANSITIONS and self.is_mounted:
            self.syzygy.animations.trigger(SemanticEvent.EXIT, self)

    def _animate_entry(self) -> None:
        """Stagger the screen's top-level regions in, and decode its title.

        Here rather than per-screen because before M17.2 exactly one
        screen (`wheel`) animated on mount, so everything else simply
        appeared. The regions are the screen's own children: a screen gets
        the transition by being a screen, and a region added later is
        included without anybody remembering to add it.
        """
        if not self.SCREEN_TRANSITIONS:
            return
        title = next(iter(self.query(TitleBar)), None)
        regions = [
            child
            for child in self.children
            if child.display and not isinstance(child, Footer) and child is not title
        ]
        self.syzygy.animations.enter_screen(
            self, regions, title, "" if title is None else title.title_text
        )

    def on_resize(self) -> None:
        self._update_size_classes()

    # -- directional focus (M17.5) -----------------------------------------

    #: Textual moves focus on `tab`/`shift+tab` only, which left every
    #: button row in the application - the delete confirmation, the eight
    #: buttons of model setup, the three of local setup - reachable by
    #: mouse or by a key nobody thinks to press.
    #:
    #: `up`/`down` walk the screen's whole focus chain in the order it
    #: reads, so every control is reachable from every other. `left`/
    #: `right` cycle within the focused control's own container, so a
    #: horizontal row of buttons behaves the way it looks. The two
    #: together are why a form with a button row at the bottom works
    #: whichever axis the user reaches for.
    #:
    #: **Bindings, not an `on_key` handler.** A screen sees the raw key
    #: event *before* the focused widget does, so intercepting it there
    #: would take `left`/`right` away from an `Input`'s cursor and
    #: `up`/`down` away from a `ListView`'s. Textual resolves a binding
    #: from the focused node outwards instead, so a widget with its own
    #: binding for the key always wins and these only ever run for a key
    #: nothing nearer wanted (M17.5b).
    #:
    #: `enter` and `escape` are deliberately *not* here. `enter` already
    #: means "the primary action of the focused control" everywhere -
    #: `Button`, `ListView` and `Input` each bind it - and `escape` is
    #: bound by every screen that has somewhere to back out to. A global
    #: `escape` would also make the too-small gate dismissable, which is
    #: the one screen that must not be.
    BINDINGS = [
        Binding("up", "focus_previous_control", "previous", show=False),
        Binding("down", "focus_next_control", "next", show=False),
        Binding("left", "focus_previous_in_row", "previous", show=False),
        Binding("right", "focus_next_in_row", "next", show=False),
    ]

    def action_focus_previous_control(self) -> None:
        self._step_focus(-1)

    def action_focus_next_control(self) -> None:
        self._step_focus(1)

    def action_focus_previous_in_row(self) -> None:
        self._cycle_focus_in_row(-1)

    def action_focus_next_in_row(self) -> None:
        self._cycle_focus_in_row(1)

    def _step_focus(self, step: int) -> None:
        """Move along the screen's focus chain, in reading order."""
        if not self.focus_chain:
            return
        if self.focused is None:
            self.focus_chain[0].focus()
        elif step > 0:
            self.focus_next()
        else:
            self.focus_previous()

    def _cycle_focus_in_row(self, step: int) -> None:
        """Move within the focused control's own container.

        Falls back to the whole chain when the container holds only the
        one control, so `left`/`right` is never a key that does nothing.
        """
        focused = self.focused
        if focused is None:
            self._step_focus(step)
            return
        container = focused.parent
        siblings = (
            [child for child in container.children if child.focusable]
            if isinstance(container, Widget)
            else []
        )
        if len(siblings) < 2 or focused not in siblings:
            self._step_focus(step)
            return
        siblings[(siblings.index(focused) + step) % len(siblings)].focus()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Move the selection marker with the highlight (M17.4a).

        Here rather than in each screen so every list in the application
        answers "where am I" the same way, including lists added later. A
        subclass that needs its own handler must call
        `super().on_list_view_highlighted(event)`.
        """
        for item in event.list_view.query(MarkedListItem):
            item.set_marked(item is event.item)

    def _update_size_classes(self) -> None:
        compact = self.size.width < IDEAL_WIDTH or self.size.height < IDEAL_HEIGHT
        self.set_class(compact, "-compact")
        # Width only. A wide layout trades height for width - three
        # columns need *fewer* rows than the same content stacked - so a
        # short terminal is a reason to go multi-column, not to avoid it.
        self.set_class(self.size.width >= WIDE_WIDTH, "-wide")
        self.set_class(self.size.height >= TALL_HEIGHT, "-tall")


class FormScroll(VerticalScroll):
    """A scrollable region whose contents are *controls*, not prose.

    Textual's scrollable containers bind the arrow keys to scrolling, and
    a binding on the focused widget's ancestor beats one on the screen -
    so inside a scrolling form, `up`/`down` moved the view rather than the
    focus, and the fields below the fold could still only be reached with
    Tab (M17.5c).

    Delegating the two vertical keys to the screen's focus movement is the
    better behaviour anyway: Textual scrolls a newly focused widget into
    view, so moving between fields scrolls exactly as far as it has to and
    never past what the user is filling in. Use `VerticalScroll` unchanged
    for a region that holds text to read rather than controls to operate.
    """

    BINDINGS = [
        Binding("up", "screen.focus_previous_control", "previous", show=False),
        Binding("down", "screen.focus_next_control", "next", show=False),
    ]


class TitleBar(Static):
    """`SYZYGY` on the left, context (usually the date) on the right."""

    def __init__(self, right_text: str = "", *, id: str | None = None) -> None:
        super().__init__(id=id, classes="title-bar")
        self.right_text = right_text

    def on_mount(self) -> None:
        self.render_title()

    def set_right_text(self, right_text: str) -> None:
        self.right_text = right_text
        self.render_title()

    def render_title(self) -> None:
        width = max(self.size.width, 30)
        left = "SYZYGY"
        padding = max(1, width - len(left) - len(self.right_text))
        self._title_text = f"{left}{' ' * padding}{self.right_text}"
        self.update(self._title_text)

    @property
    def title_text(self) -> str:
        """The settled bar, as text.

        `SyzygyScreen`'s entry animation decodes *into* this, so it has to
        be readable from outside - and it has to be the value the bar
        would render anyway, or a skipped animation would land on
        something the bar never chose.
        """
        return getattr(self, "_title_text", "")

    def on_resize(self) -> None:
        self.render_title()
