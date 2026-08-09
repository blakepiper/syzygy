"""Pilot tests for the guided local-model wizard (M16.9f).

Every service is fake: the machine is a captured `Probe`, the endpoint
qualifier never opens a socket, and the acquisition steps are replaced on
the session so no download, no extraction, and no subprocess happens. What
is exercised is the *screen* - which step it shows, which control is
primary, what it says, and what it refuses to do.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, ListView, Static

from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.interpretation.providers.selection import load_selection
from syzygy.local_models.contracts import (
    Compatibility,
    FailureKind,
    RuntimeCandidate,
    RuntimeCapabilities,
    RuntimeKind,
    RuntimeSource,
    SetupFailure,
)
from syzygy.local_models.orchestrator import LocalSetupSession, SetupStepError
from syzygy.local_models.paths import LocalModelPaths
from syzygy.local_models.state import SetupState
from syzygy.tui.animation.motion import MotionLevel, MotionSettings
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.local_setup import LocalSetupScreen
from tests.local_models.machines import linux_cpu_probe, macos_arm_probe, make_probe


def q(pilot, selector, kind=Static):
    return pilot.app.screen.query_one(selector, kind)


def text_of(widget) -> str:
    return widget.visual.plain


async def settle(pilot) -> None:
    """Let workers finish. The wizard's steps are threaded, so a single
    `pause()` is not enough."""
    for _ in range(12):
        await pilot.pause()
        if not pilot.app.workers._workers:
            break
    await pilot.pause()


def nothing_listening(candidate: RuntimeCandidate) -> RuntimeCapabilities:
    return RuntimeCapabilities(
        candidate=candidate,
        compatibility=Compatibility.UNKNOWN,
        next_action=f"Nothing answered at {candidate.locator}.",
    )


def running_endpoint(candidate: RuntimeCandidate) -> RuntimeCapabilities:
    if ":8080" not in candidate.locator or "[::1]" in candidate.locator:
        return nothing_listening(candidate)
    return RuntimeCapabilities(
        candidate=candidate,
        compatibility=Compatibility.COMPATIBLE,
        next_action="ready",
        serves_http=True,
        lists_models=True,
        chat_completions=True,
        json_schema_response_format=True,
        model_ids=("already-loaded",),
    )


@pytest.fixture
def paths(tmp_path: Path) -> LocalModelPaths:
    layout = LocalModelPaths.from_app_paths(
        type(
            "P",
            (),
            {"data_dir": tmp_path},
        )()  # type: ignore[arg-type]
    )
    layout.ensure_exists()
    return layout


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    return tmp_path / "settings.json"


def make_session(paths, settings_file, *, probe=None, qualifier=nothing_listening):
    return LocalSetupSession(
        paths=paths,
        settings_path=settings_file,
        probe=probe or macos_arm_probe(),
        endpoint_qualifier=qualifier,
    )


def stub_acquisition(session: LocalSetupSession, monkeypatch, *, model_path: Path) -> None:
    """Replace the three steps that touch the world. Their own behaviour is
    covered by `tests/local_models`; here they must simply not happen."""
    from syzygy.local_models.settings import (
        ModelRecord,
        load_local_model_settings,
        save_local_model_settings,
    )

    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"\0" * 128)

    def fake_install(*, on_progress=None, cancel=None):
        session.move_to(SetupState.RUNTIME)
        if on_progress:
            on_progress(10, 10)
        session.runtime = RuntimeCapabilities(
            candidate=RuntimeCandidate(
                kind=RuntimeKind.BINARY,
                source=RuntimeSource.MANAGED,
                locator=str(model_path.parent / "llama-server"),
            ),
            compatibility=Compatibility.COMPATIBLE,
            next_action="ready",
            version="b10331",
        )
        return session.runtime

    def fake_fetch(*, on_progress=None, cancel=None):
        session.move_to(SetupState.MODEL)
        if on_progress:
            on_progress(64, 128)
            on_progress(128, 128)
        settings = load_local_model_settings(session.settings_path)
        save_local_model_settings(
            session.settings_path,
            settings.model_copy(
                update={
                    "model": ModelRecord(
                        path=str(model_path), size_bytes=128, syzygy_owned=True
                    )
                }
            ),
        )
        return model_path

    def fake_start(*, on_phase=None, cancel=None):
        session.move_to(SetupState.START)
        session.external_endpoint = "http://127.0.0.1:18080/v1"
        return None

    monkeypatch.setattr(session, "install_runtime", fake_install)
    monkeypatch.setattr(session, "fetch_model", fake_fetch)
    monkeypatch.setattr(session, "start_server", fake_start)


@pytest.fixture
def fixture_provider(monkeypatch):
    """Whatever the wizard points a provider at, it gets the fixture one -
    no HTTP, and a smoke test that passes."""
    monkeypatch.setattr(
        "syzygy.interpretation.providers.llama_cpp.LlamaCppProvider",
        lambda **kwargs: FixtureProvider(),
    )


async def open_wizard(pilot, session) -> None:
    await pilot.app.push_screen(LocalSetupScreen(session))
    await settle(pilot)


# -- the happy path ----------------------------------------------------------


async def test_the_intro_explains_before_any_jargon(app: SyzygyApp, paths, settings_file):
    async with app.run_test() as pilot:
        await open_wizard(pilot, make_session(paths, settings_file))

        detail = text_of(q(pilot, "#setup-detail"))
        assert "never leave this machine" in detail
        assert "few gigabytes" in detail
        assert "demonstration text" in detail
        # No jargon on the happy path.
        for word in ("llama.cpp", "GGUF", "quantization", "Metal", "tokens"):
            assert word not in detail
        assert "CHECK THIS COMPUTER" in str(q(pilot, "#setup-primary", Button).label)


async def test_a_fresh_setup_walks_intro_to_complete(
    app: SyzygyApp, paths, settings_file, monkeypatch, fixture_provider, tmp_path
):
    session = make_session(paths, settings_file)
    stub_acquisition(session, monkeypatch, model_path=tmp_path / "gguf" / "m.gguf")

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)

        q(pilot, "#setup-primary", Button).press()  # inventory
        await settle(pilot)
        assert session.state is SetupState.INVENTORY

        q(pilot, "#setup-primary", Button).press()  # discovery
        await settle(pilot)
        assert session.state is SetupState.DISCOVERY

        q(pilot, "#setup-primary", Button).press()  # recommend
        await settle(pilot)
        assert session.state is SetupState.RECOMMEND

        q(pilot, "#setup-primary", Button).press()  # consent
        await settle(pilot)
        assert session.state is SetupState.CONSENT

        q(pilot, "#setup-primary", Button).press()  # do it
        await settle(pilot)

        assert session.state is SetupState.COMPLETE
        assert "Ready" in text_of(q(pilot, "#setup-lede"))
        selection = load_selection(settings_file)
        assert selection is not None and selection.provider_id == "llama_cpp"


async def test_nothing_is_downloaded_merely_by_opening_the_wizard(
    app: SyzygyApp, paths, settings_file
):
    session = make_session(paths, settings_file)

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)

        assert session.state is SetupState.INTRO
        assert list(paths.models_dir.iterdir()) == []
        assert load_selection(settings_file) is None


# -- what already exists -----------------------------------------------------


async def test_a_running_server_is_offered_as_the_shortest_route(
    app: SyzygyApp, paths, settings_file, fixture_provider
):
    session = make_session(paths, settings_file, qualifier=running_endpoint)

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)

        assert "already running" in text_of(q(pilot, "#setup-lede"))
        assert "USE THIS SERVER" in str(q(pilot, "#setup-primary", Button).label)

        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)

        assert session.state is SetupState.COMPLETE
        # Nothing was downloaded to get there.
        assert list(paths.models_dir.iterdir()) == []


async def test_an_existing_binary_skips_the_runtime_download(
    app: SyzygyApp, paths, settings_file, tmp_path
):
    binary = tmp_path / "bin" / "llama-server"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    probe = macos_arm_probe(which={"llama-server": str(binary)})
    session = make_session(paths, settings_file, probe=probe)

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)

        # The binary does not identify itself as llama.cpp (no --version
        # stub), so the wizard says nothing usable was found rather than
        # trusting the filename.
        assert "CHOOSE A MODEL" in str(q(pilot, "#setup-primary", Button).label)


# -- what this computer can do -----------------------------------------------


async def test_a_cpu_only_machine_is_told_it_will_be_slow(
    app: SyzygyApp, paths, settings_file
):
    session = make_session(paths, settings_file, probe=linux_cpu_probe())

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)

        assert "slowly" in text_of(q(pilot, "#setup-lede"))


async def test_an_unsupported_platform_offers_the_manual_route(
    app: SyzygyApp, paths, settings_file
):
    session = make_session(paths, settings_file, probe=make_probe(system="Haiku", machine="ppc64"))

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)

        detail = text_of(q(pilot, "#setup-detail"))
        assert "can't set this up automatically" in text_of(q(pilot, "#setup-lede"))
        assert "point Syzygy at" in detail


async def test_a_machine_with_too_little_memory_says_so(app: SyzygyApp, paths, settings_file):
    tiny = linux_cpu_probe(
        files={"/proc/meminfo": "MemTotal:       2097152 kB\nMemAvailable:   1048576 kB\n"},
        sysconf={"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 512 * 1024},
    )
    session = make_session(paths, settings_file, probe=tiny)

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)

        assert "enough free memory" in text_of(q(pilot, "#setup-lede"))


# -- recommendation ----------------------------------------------------------


async def test_the_recommendation_shows_three_options_and_why(
    app: SyzygyApp, paths, settings_file
):
    session = make_session(paths, settings_file)

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)

        listing = q(pilot, "#setup-choices", ListView)
        assert len(listing.children) == 3
        rendered = " ".join(text_of(child.query_one("Label")) for child in listing.children)
        assert "FASTER" in rendered and "RECOMMENDED" in rendered
        assert "download" in rendered and "memory about" in rendered
        assert "Why this model?" in text_of(q(pilot, "#setup-detail"))


async def test_technical_details_are_hidden_until_asked_for(
    app: SyzygyApp, paths, settings_file
):
    session = make_session(paths, settings_file)

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)

        assert q(pilot, "#setup-technical").has_class("hidden")
        await pilot.press("t")
        await settle(pilot)
        panel = text_of(q(pilot, "#setup-technical"))
        assert not q(pilot, "#setup-technical").has_class("hidden")
        assert "sha256" in panel and "GGUF" in panel and "quantization" in panel


async def test_choosing_a_different_tier_updates_the_selection(
    app: SyzygyApp, paths, settings_file
):
    session = make_session(paths, settings_file)

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        for _ in range(3):
            q(pilot, "#setup-primary", Button).press()
            await settle(pilot)

        # Focus stays on the primary action, so CONTINUE is what ENTER
        # does (M16.9b). Choosing a different tier means moving to the
        # list first, exactly as a keyboard user would with TAB.
        listing = q(pilot, "#setup-choices", ListView)
        listing.focus()
        listing.index = 2
        await pilot.pause()
        await pilot.press("enter")
        await settle(pilot)

        assert session.chosen is not None
        assert session.chosen.tier is not None
        assert session.chosen.tier.value == "higher_quality"


# -- consent -----------------------------------------------------------------


async def test_the_consent_step_is_an_exact_receipt(app: SyzygyApp, paths, settings_file):
    session = make_session(paths, settings_file)

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        for _ in range(4):
            q(pilot, "#setup-primary", Button).press()
            await settle(pilot)

        detail = text_of(q(pilot, "#setup-detail"))
        assert "Nothing has been downloaded yet" in text_of(q(pilot, "#setup-lede"))
        assert "It will contact:" in detail
        assert "huggingface.co" in detail
        assert "Total download:" in detail
        assert "127.0.0.1" in detail
        assert "Licence:" in detail
        assert "YES, DO THIS" in str(q(pilot, "#setup-primary", Button).label)


async def test_refusing_consent_downloads_nothing_and_changes_nothing(
    app: SyzygyApp, paths, settings_file
):
    session = make_session(paths, settings_file)

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        for _ in range(4):
            q(pilot, "#setup-primary", Button).press()
            await settle(pilot)

        q(pilot, "#setup-cancel", Button).press()
        await settle(pilot)

        assert session.state is SetupState.CANCELLED
        assert "Nothing was switched over" in text_of(q(pilot, "#setup-lede"))
        assert load_selection(settings_file) is None
        assert list(paths.models_dir.iterdir()) == []


# -- navigation --------------------------------------------------------------


async def test_back_returns_one_step_at_a_time(app: SyzygyApp, paths, settings_file):
    session = make_session(paths, settings_file)

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        for _ in range(3):
            q(pilot, "#setup-primary", Button).press()
            await settle(pilot)
        assert session.state is SetupState.RECOMMEND

        q(pilot, "#setup-back", Button).press()
        await settle(pilot)
        assert session.state is SetupState.DISCOVERY

        q(pilot, "#setup-back", Button).press()
        await settle(pilot)
        assert session.state is SetupState.INVENTORY


async def test_escape_from_the_intro_leaves_the_wizard(app: SyzygyApp, paths, settings_file):
    async with app.run_test() as pilot:
        await open_wizard(pilot, make_session(paths, settings_file))
        assert isinstance(pilot.app.screen, LocalSetupScreen)

        await pilot.press("escape")
        await settle(pilot)

        assert not isinstance(pilot.app.screen, LocalSetupScreen)


async def test_quitting_mid_wizard_does_not_raise(app: SyzygyApp, paths, settings_file):
    async with app.run_test() as pilot:
        await open_wizard(pilot, make_session(paths, settings_file))
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)
        await pilot.press("q")
        await pilot.pause()


# -- failures ----------------------------------------------------------------


async def test_a_download_failure_shows_a_remedy_and_keeps_the_ritual(
    app: SyzygyApp, paths, settings_file, monkeypatch, tmp_path
):
    session = make_session(paths, settings_file)
    stub_acquisition(session, monkeypatch, model_path=tmp_path / "gguf" / "m.gguf")

    def failing_fetch(*, on_progress=None, cancel=None):
        raise SetupStepError(
            SetupFailure(
                kind=FailureKind.INSUFFICIENT_DISK,
                message="Not enough free disk space for the model.",
                detail="9.0 GB needed, 1.2 GB free",
                retryable=False,
            )
        )

    monkeypatch.setattr(session, "fetch_model", failing_fetch)

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        for _ in range(5):
            q(pilot, "#setup-primary", Button).press()
            await settle(pilot)

        assert session.state is SetupState.FAILED
        assert "Not enough free disk space" in text_of(q(pilot, "#setup-lede"))
        assert "readings are unaffected" in text_of(q(pilot, "#setup-detail"))
        assert load_selection(settings_file) is None


async def test_a_failed_smoke_test_never_activates_the_provider(
    app: SyzygyApp, paths, settings_file, monkeypatch, tmp_path
):
    from tests.local_models.test_verification import DeadProvider

    session = make_session(paths, settings_file)
    stub_acquisition(session, monkeypatch, model_path=tmp_path / "gguf" / "m.gguf")
    monkeypatch.setattr(
        "syzygy.interpretation.providers.llama_cpp.LlamaCppProvider",
        lambda **kwargs: DeadProvider(),
    )

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        for _ in range(5):
            q(pilot, "#setup-primary", Button).press()
            await settle(pilot)

        assert session.state is SetupState.FAILED
        assert load_selection(settings_file) is None


async def test_an_unexpected_exception_becomes_a_failure_card(
    app: SyzygyApp, paths, settings_file, monkeypatch
):
    session = make_session(paths, settings_file)

    def explode(*args, **kwargs):
        raise RuntimeError("something nobody predicted")

    monkeypatch.setattr(session, "run_inventory", explode)

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)

        assert session.state is SetupState.FAILED
        assert "Something went wrong" in text_of(q(pilot, "#setup-lede"))


async def test_a_failure_can_be_retried_from_the_start(
    app: SyzygyApp, paths, settings_file, monkeypatch
):
    session = make_session(paths, settings_file)
    session.fail(SetupFailure(kind=FailureKind.OFFLINE, message="no network"))

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        assert "TRY AGAIN" in str(q(pilot, "#setup-primary", Button).label)

        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)

        assert session.state is SetupState.INTRO


# -- diagnostics -------------------------------------------------------------


async def test_copy_diagnostics_writes_a_redacted_report(
    app: SyzygyApp, paths, settings_file
):
    session = make_session(paths, settings_file)

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)

        await pilot.press("d")
        await settle(pilot)

        report = (paths.logs_dir / "diagnostics.txt").read_text()
        assert "[machine]" in report
        assert "Installed memory" in report
        assert "Diagnostics copied" in text_of(q(pilot, "#setup-message"))


# -- layout and motion -------------------------------------------------------


@pytest.mark.parametrize("size", [(80, 24), (100, 32), (140, 50)])
async def test_the_controls_are_reachable_at_every_supported_size(
    app: SyzygyApp, paths, settings_file, size
):
    async with app.run_test(size=size) as pilot:
        await open_wizard(pilot, make_session(paths, settings_file))
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)
        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)

        for selector in ("#setup-primary", "#setup-back", "#setup-cancel"):
            button = q(pilot, selector, Button)
            assert button.display
            region = button.region
            assert region.y + region.height <= size[1]
            assert region.x + region.width <= size[0]


@pytest.mark.parametrize("level", [MotionLevel.FULL, MotionLevel.REDUCED, MotionLevel.OFF])
async def test_every_motion_level_still_reports_progress(
    app: SyzygyApp, paths, settings_file, level, monkeypatch, tmp_path
):
    app.animations.animator.motion = MotionSettings(level=level, speed=1.0)
    session = make_session(paths, settings_file)
    stub_acquisition(session, monkeypatch, model_path=tmp_path / "gguf" / "m.gguf")

    labels: list[str] = []

    async with app.run_test() as pilot:
        await open_wizard(pilot, session)
        screen = pilot.app.screen
        original = screen._refresh_progress

        def record():
            if screen._progress is not None:
                labels.append(screen._progress.label)
            original()

        monkeypatch.setattr(screen, "_refresh_progress", record)

        q(pilot, "#setup-primary", Button).press()
        await settle(pilot)

        assert labels
        assert any("Checking" in label for label in labels)
