"""Choosing which self is being read for (docs/old/DESIGN.md section 3.1).

Also where a self is *destroyed*: deleting a profile takes every reading
made for it (M11.2), so it is a two-phase action here - select, then
confirm against a panel that names what is about to be lost - rather than
a single keypress.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Label, ListItem, ListView, Static

from syzygy.domain.profile import Profile
from syzygy.storage.profiles import count_readings, delete_profile, list_profiles
from syzygy.tui.screens.base import SyzygyScreen, TitleBar


class ProfileListItem(ListItem):
    def __init__(self, profile: Profile) -> None:
        birth = profile.birth_data
        super().__init__(
            Label(
                f"{profile.display_name:<20} {birth.local_date} {birth.local_time}  "
                f"{birth.place_label}"
            )
        )
        self.profile = profile


class ProfileSelectScreen(SyzygyScreen):
    BINDINGS = [
        ("n", "create_profile", "new profile"),
        ("d", "delete_profile", "delete"),
        ("escape", "back", "back"),
    ]

    #: The profile the confirm panel is currently asking about.
    _pending_delete: Profile | None = None
    _selecting = False

    def compose(self) -> ComposeResult:
        yield TitleBar("PROFILES")
        with Vertical(id="profile-select-body"):
            yield Static("Select a self.", classes="lede")
            yield ListView(id="profile-list")
            yield Static("[ENTER] select   [N] new   [D] delete", classes="keys")
        with Vertical(id="profile-delete-confirm", classes="hidden"):
            yield Static("DELETE PROFILE", classes="section-heading")
            yield Static("", id="delete-body")
            yield Static("", id="delete-error", classes="error")
            with Horizontal(classes="button-row"):
                yield Button("DELETE", id="delete-confirm", variant="error")
                yield Button("CANCEL", id="delete-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self._reload()

    # -- selecting ---------------------------------------------------------

    def _reload(self) -> None:
        """Rebuild the list from storage and focus it."""
        listing = self.query_one("#profile-list", ListView)
        listing.clear()
        profiles = list_profiles(self.syzygy.services.conn)
        for profile in profiles:
            listing.append(ProfileListItem(profile))
        if profiles:
            listing.index = 0
        listing.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ProfileListItem) and not self._selecting:
            self._selecting = True
            self.syzygy.set_profile(item.profile)

            def open_home() -> None:
                self.app.switch_screen("home")

            self.syzygy.animations.self_selected(item, open_home)

    def action_create_profile(self) -> None:
        self.app.push_screen("profile_create")

    # -- deleting ----------------------------------------------------------

    def _highlighted_profile(self) -> Profile | None:
        listing = self.query_one("#profile-list", ListView)
        item = listing.highlighted_child
        return item.profile if isinstance(item, ProfileListItem) else None

    def action_delete_profile(self) -> None:
        """Ask before destroying anything - deletion is irreversible and
        takes the profile's readings with it."""
        if not self.query_one("#profile-delete-confirm").has_class("hidden"):
            return  # already asking
        profile = self._highlighted_profile()
        if profile is None:
            self.app.bell()  # nothing highlighted: say so rather than no-op
            return

        self._pending_delete = profile
        readings = count_readings(self.syzygy.services.conn, profile.id)
        if readings == 0:
            loss = "It has no readings."
        elif readings == 1:
            loss = "Its 1 reading will be deleted with it."
        else:
            loss = f"All {readings} of its readings will be deleted with it."
        active = (
            " This is the profile currently being read for." if self._is_active(profile) else ""
        )
        birth = profile.birth_data
        self.query_one("#delete-body", Static).update(
            f"Delete {profile.display_name}?\n"
            f"  {birth.local_date} {birth.local_time}  {birth.place_label}\n\n"
            f"{loss}{active}\n"
            f"This cannot be undone."
        )
        self.query_one("#delete-error", Static).update("")
        self.query_one("#profile-select-body").add_class("hidden")
        self.query_one("#profile-delete-confirm").remove_class("hidden")
        # CANCEL takes focus, not DELETE: a stray ENTER on a destructive
        # confirmation must not be what destroys the data.
        self.query_one("#delete-cancel", Button).focus()

    def _is_active(self, profile: Profile) -> bool:
        active = self.syzygy.profile
        return active is not None and active.id == profile.id

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "delete-confirm":
            self._confirm_delete()
        elif event.button.id == "delete-cancel":
            self._cancel_delete()

    def _cancel_delete(self) -> None:
        self._pending_delete = None
        self.query_one("#profile-delete-confirm").add_class("hidden")
        self.query_one("#profile-select-body").remove_class("hidden")
        self.query_one("#profile-list", ListView).focus()

    def _confirm_delete(self) -> None:
        profile = self._pending_delete
        if profile is None:
            return
        was_active = self._is_active(profile)
        try:
            delete_profile(self.syzygy.services.conn, profile.id)
        except Exception as exc:  # docs/old/DESIGN.md section 23: never fail silently
            self.query_one("#delete-error", Static).update(
                f"Could not delete {profile.display_name} - {type(exc).__name__}: {exc}"
            )
            return

        self._pending_delete = None
        if was_active:
            # The active profile no longer exists; nothing may keep reading
            # for it (M11.2c).
            self.syzygy.clear_profile()
        self.query_one("#profile-delete-confirm").add_class("hidden")
        self.query_one("#profile-select-body").remove_class("hidden")

        remaining = list_profiles(self.syzygy.services.conn)
        if not remaining:
            self.app.switch_screen("welcome")
            return
        # Deliberately does not auto-select a replacement for a deleted
        # active profile: which self is being read for is the user's
        # choice, never a side effect of a deletion.
        self._reload()

    def action_back(self) -> None:
        if not self.query_one("#profile-delete-confirm").has_class("hidden"):
            self._cancel_delete()
            return
        if self.syzygy.profile is not None and len(self.app.screen_stack) > 1:
            self.app.pop_screen()
