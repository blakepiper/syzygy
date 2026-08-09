"""Archive deletion is explicit, confirmed, and cannot become a reroll."""

from textual.widgets import Button, ListView, Static

from syzygy.storage import consultations, iching, oracle, readings
from syzygy.storage.consultation_service import ask_question
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.archive import ArchiveScreen
from syzygy.tui.screens.home import HomeScreen

from .test_ritual_flow import q, settle, text_of, turn_the_wheel


def _confirm_hidden(pilot) -> bool:
    return q(pilot, "#archive-delete-confirm").has_class("hidden")


async def _open_archive(pilot) -> ArchiveScreen:
    await settle(pilot)
    await pilot.press("a")
    await settle(pilot)
    screen = pilot.app.screen
    assert isinstance(screen, ArchiveScreen)
    return screen


async def test_daily_delete_requires_confirmation_and_cannot_enable_a_redraw(
    services, profile, conn
):
    async with SyzygyApp(services).run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        reading = pilot.app.screen.reading
        await pilot.press("escape")
        await settle(pilot)
        await _open_archive(pilot)

        await pilot.press("d")
        await pilot.pause()
        assert not _confirm_hidden(pilot)
        assert readings.get_by_id(conn, reading.id) is not None
        assert "does not permit another draw" in text_of(
            q(pilot, "#archive-delete-body", Static)
        )
        assert pilot.app.focused is q(pilot, "#archive-delete-cancel", Button)

        # A reflexive Enter chooses the safe default.
        await pilot.press("enter")
        await pilot.pause()
        assert _confirm_hidden(pilot)
        assert readings.get_by_id(conn, reading.id) is not None

        await pilot.press("d")
        await pilot.pause()
        q(pilot, "#archive-delete-confirm-button", Button).press()
        await settle(pilot)
        assert readings.get_by_id(conn, reading.id) is None
        assert readings.date_was_deleted(
            conn, profile.id, reading.consultation_local_date
        )
        assert len(q(pilot, "#archive-list", ListView).children) == 0

        await pilot.press("escape")
        await settle(pilot)
        assert isinstance(pilot.app.screen, HomeScreen)
        primary = q(pilot, "#primary-action", Button)
        assert primary.disabled
        assert "READING WAS DELETED" in str(primary.label)


async def test_archive_deletes_an_oracle_consultation(services, profile, conn):
    consultation = ask_question(conn, profile, services.clock, "What should be released?")
    async with SyzygyApp(services).run_test() as pilot:
        await _open_archive(pilot)
        await pilot.press("d")
        await pilot.pause()
        assert "Oracle question" in text_of(q(pilot, "#archive-delete-body", Static))
        q(pilot, "#archive-delete-confirm-button", Button).press()
        await settle(pilot)

        assert consultations.get_by_id(conn, consultation.id) is None
        assert len(q(pilot, "#archive-list", ListView).children) == 0


async def test_archive_still_deletes_the_two_legacy_kinds(services, profile, conn):
    """`[D]` behaviour is unchanged for the superseded rites (M22.4e)."""
    from tests.storage.test_legacy_consultations import (
        insert_legacy_iching_row,
        insert_legacy_oracle_row,
    )

    insert_legacy_oracle_row(conn, profile.id)
    insert_legacy_iching_row(conn, profile.id)

    async with SyzygyApp(services).run_test() as pilot:
        await _open_archive(pilot)
        for _ in range(2):
            await pilot.press("d")
            await pilot.pause()
            assert "earlier" in text_of(q(pilot, "#archive-delete-body", Static))
            q(pilot, "#archive-delete-confirm-button", Button).press()
            await settle(pilot)

        assert oracle.get_by_id(conn, "legacy-thoth") is None
        assert iching.get_by_id(conn, "legacy-iching") is None
        assert len(q(pilot, "#archive-list", ListView).children) == 0
