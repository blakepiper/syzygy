"""Choosing which self is being read for (DESIGN.md section 3.1)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Footer, Label, ListItem, ListView, Static

from syzygy.domain.profile import Profile
from syzygy.storage.profiles import list_profiles
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
        ("escape", "back", "back"),
        ("q", "quit", "quit"),
    ]

    def compose(self) -> ComposeResult:
        yield TitleBar("PROFILES")
        yield Static("Select a self.", classes="lede")
        yield ListView(id="profile-list")
        yield Footer()

    def on_mount(self) -> None:
        listing = self.query_one("#profile-list", ListView)
        profiles = list_profiles(self.syzygy.services.conn)
        for profile in profiles:
            listing.append(ProfileListItem(profile))
        if profiles:
            listing.index = 0
        listing.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ProfileListItem):
            self.syzygy.set_profile(item.profile)
            self.app.switch_screen("home")

    def action_create_profile(self) -> None:
        self.app.push_screen("profile_create")

    def action_back(self) -> None:
        if self.syzygy.profile is not None and len(self.app.screen_stack) > 1:
            self.app.pop_screen()
