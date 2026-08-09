import pytest

from syzygy.cli import main
from syzygy.interpretation.providers import api_keys


def test_knowledge_ingest_without_a_path_ingests_all_three_docs_pdfs(
    isolated_app_paths, tmp_path, monkeypatch, capsys
):
    from syzygy.knowledge.ingest import IngestResult

    docs = tmp_path / "docs"
    docs.mkdir()
    filenames = (
        "book_of_thoth.pdf",
        "understanding_crowley_thoth_tarot.pdf",
        "mirror_of_the_soul.pdf",
    )
    for filename in filenames:
        (docs / filename).write_bytes(b"fixture")
    monkeypatch.chdir(tmp_path)
    calls: list[tuple[str, str | None]] = []

    def fake_ingest(conn, pdf_path, *, now, source_type=None, on_progress=None):
        calls.append((pdf_path.name, source_type))
        return IngestResult(
            source_type=source_type,
            skipped=False,
            chunk_count=2,
            card_count=1,
        )

    monkeypatch.setattr("syzygy.knowledge.ingest.ingest", fake_ingest)

    assert main(["knowledge", "ingest"]) == 0
    assert calls == [
        ("book_of_thoth.pdf", "book_of_thoth"),
        ("understanding_crowley_thoth_tarot.pdf", "duquette_companion"),
        ("mirror_of_the_soul.pdf", "ziegler_mirror_of_soul"),
    ]
    assert capsys.readouterr().out.count("ingested 2 chunks") == 3


def test_knowledge_ingest_without_a_path_reports_every_missing_pdf(
    isolated_app_paths, tmp_path, monkeypatch, capsys
):
    (tmp_path / "docs").mkdir()
    monkeypatch.chdir(tmp_path)

    assert main(["knowledge", "ingest"]) == 1
    error = capsys.readouterr().err
    assert "book_of_thoth.pdf" in error
    assert "mirror_of_the_soul.pdf" in error
    assert "understanding_crowley_thoth_tarot.pdf" in error


def test_dev_deck_lists_78_cards(capsys):
    exit_code = main(["dev", "deck"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "the_fool" in out
    assert "78 cards total." in out


def test_doctor_exits_zero(isolated_app_paths, capsys):
    exit_code = main(["doctor"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "deck    OK" in out
    # Knowledge base and provider config are informational (docs/old/DESIGN.md
    # section 15/13.3's "no model configured" and "no source passages"
    # are both supported states) - doctor reports them, but neither can
    # fail its exit code.
    #
    # "citations only" is the default state since M13.3: every install
    # ships the citation index, and full text needs the user's own PDFs.
    assert "citations only" in out
    assert "llama_cpp" in out
    assert "active provider: fixture" in out


def test_help_flag_prints_usage(capsys):
    # `syzygy` with no arguments launches the TUI (docs/old/DESIGN.md section 20),
    # so usage is reached through --help rather than through no arguments.
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()
    assert "tui" in out


def test_unknown_subcommand_group_prints_help(capsys):
    exit_code = main(["dev"])
    assert exit_code == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch):
    """None of the `model` command tests below should touch a real OS
    keyring - a tiny in-memory fake keeps them deterministic on any
    machine, same as `tests/interpretation/providers/test_api_keys.py`."""
    store: dict[tuple[str, str], str] = {}

    def fake_get_password(service: str, username: str) -> str | None:
        return store.get((service, username))

    def fake_set_password(service: str, username: str, password: str) -> None:
        store[(service, username)] = password

    def fake_delete_password(service: str, username: str) -> None:
        import keyring.errors

        if (service, username) not in store:
            raise keyring.errors.PasswordDeleteError("not found")
        del store[(service, username)]

    monkeypatch.setattr(api_keys.keyring, "get_password", fake_get_password)
    monkeypatch.setattr(api_keys.keyring, "set_password", fake_set_password)
    monkeypatch.setattr(api_keys.keyring, "delete_password", fake_delete_password)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_model_status_reports_unconfigured_providers(capsys):
    exit_code = main(["model", "status"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "llama_cpp" in out
    assert "not reachable" in out
    assert "openai" in out and "no key configured" in out
    assert "anthropic" in out and "no key configured" in out


def test_model_status_reports_an_env_var_key(capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    exit_code = main(["model", "status"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "openai" in out and "OPENAI_API_KEY" in out


def test_model_configure_stores_a_key(capsys, monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "secret-key")

    exit_code = main(["model", "configure", "openai"])
    assert exit_code == 0
    assert "secret-key" not in capsys.readouterr().out
    assert api_keys.has_stored_api_key("openai") is True
    assert api_keys.resolve_api_key("openai", "OPENAI_API_KEY") == "secret-key"


def test_model_configure_rejects_an_empty_key(capsys, monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "")

    exit_code = main(["model", "configure", "openai"])
    assert exit_code == 1
    assert api_keys.has_stored_api_key("openai") is False


def test_model_configure_delete_removes_a_stored_key(capsys):
    api_keys.store_api_key("anthropic", "secret-key")

    exit_code = main(["model", "configure", "anthropic", "--delete"])
    assert exit_code == 0
    assert api_keys.has_stored_api_key("anthropic") is False


def test_model_configure_rejects_llama_cpp(capsys):
    with pytest.raises(SystemExit):
        main(["model", "configure", "llama_cpp"])


@pytest.fixture
def isolated_app_paths(tmp_path, monkeypatch):
    """`model use` writes to `AppPaths.settings_path` - point that at a
    tmp directory instead of the real machine's `platformdirs` data dir,
    the same way `fake_keyring` isolates the OS keyring above."""
    from syzygy.config import AppPaths

    paths = AppPaths(
        data_dir=tmp_path,
        database_path=tmp_path / "syzygy.db",
        settings_path=tmp_path / "settings.json",
        knowledge_dir=tmp_path / "knowledge",
        models_dir=tmp_path / "models",
        logs_dir=tmp_path / "logs",
    )
    monkeypatch.setattr("syzygy.config.default_app_paths", lambda: paths)
    return paths


def test_model_use_fixture_clears_any_saved_selection(isolated_app_paths, capsys):
    """The legacy flat settings shape, which existing installs still have
    on disk (M15: the file is namespaced now, but must keep loading)."""
    from syzygy.interpretation.providers.selection import load_selection

    isolated_app_paths.settings_path.write_text('{"provider_id": "openai", "model_id": "x"}')

    exit_code = main(["model", "use", "fixture"])
    assert exit_code == 0
    # The file survives - other subsystems keep preferences there now -
    # but it no longer names a provider.
    assert load_selection(isolated_app_paths.settings_path) is None


def test_model_use_llama_cpp_saves_a_selection(isolated_app_paths, capsys):
    exit_code = main(["model", "use", "llama_cpp", "--model", "local-test"])
    assert exit_code == 0

    import json

    saved = json.loads(isolated_app_paths.settings_path.read_text())
    assert saved["provider"] == {
        "provider_id": "llama_cpp",
        "model_id": "local-test",
        "base_url": None,
    }


def test_model_use_openai_without_a_model_id_warns_but_still_saves(isolated_app_paths, capsys):
    exit_code = main(["model", "use", "openai"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "model id" in captured.err.lower()
    assert isolated_app_paths.settings_path.exists()


def test_model_use_openai_discloses_leaving_the_local_machine(isolated_app_paths, capsys):
    main(["model", "use", "openai", "--model", "gpt-4o-mini"])
    out = capsys.readouterr().out
    assert "sends" in out.lower() and "servers" in out.lower()


def test_model_use_llama_cpp_does_not_disclose_leaving_the_machine(isolated_app_paths, capsys):
    main(["model", "use", "llama_cpp"])
    out = capsys.readouterr().out
    assert "servers" not in out.lower()


def test_model_status_reflects_the_active_selection(isolated_app_paths, capsys):
    main(["model", "use", "llama_cpp", "--model", "local-test"])
    capsys.readouterr()  # discard `use`'s own output

    exit_code = main(["model", "status"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "active provider: llama_cpp (local-test)" in out


# -- `syzygy profile delete` (M11.2d) ------------------------------------


def _seed_profile(paths, profile_id: str = "p1", display_name: str = "Blake") -> None:
    """Write a profile straight to the isolated database. Goes through the
    storage layer rather than `profile create`, which would need Kerykeion
    to calculate a real chart."""
    import uuid
    from datetime import UTC, datetime

    from syzygy.domain.astrology import BirthData, NatalChart, NatalPlacement
    from syzygy.domain.profile import Profile
    from syzygy.storage.database import open_database
    from syzygy.storage.profiles import insert_profile

    birth = BirthData(
        local_date="1990-08-07",
        local_time="14:22:00",
        place_label="Alexandria, Virginia, USA",
        latitude=38.8048,
        longitude=-77.0469,
        timezone="America/New_York",
    )
    chart = NatalChart(
        birth_data=birth,
        placements=[
            NatalPlacement(body="Sun", sign="Leo", longitude=135.0, house=10),
            NatalPlacement(body="Moon", sign="Pisces", longitude=338.0, house=4),
        ],
        aspects=[],
        ascendant_longitude=210.0,
        midheaven_longitude=120.0,
        astrology_engine="fixture",
        astrology_engine_version="0",
        chart_schema_version="natal-v1",
    )
    now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    conn = open_database(paths.database_path)
    try:
        insert_profile(
            conn,
            Profile(
                id=profile_id or str(uuid.uuid4()),
                display_name=display_name,
                birth_data=birth,
                natal_chart=chart,
                created_at_utc=now,
                updated_at_utc=now,
            ),
        )
    finally:
        conn.close()


def _saved_profile_ids(paths) -> list[str]:
    from syzygy.storage.database import open_database
    from syzygy.storage.profiles import list_profiles

    conn = open_database(paths.database_path)
    try:
        return [profile.id for profile in list_profiles(conn)]
    finally:
        conn.close()


def test_profile_delete_with_yes_deletes_without_prompting(isolated_app_paths, capsys):
    _seed_profile(isolated_app_paths)

    exit_code = main(["profile", "delete", "p1", "--yes"])

    assert exit_code == 0
    assert "Deleted profile p1" in capsys.readouterr().out
    assert _saved_profile_ids(isolated_app_paths) == []


def test_profile_delete_requires_the_name_to_confirm(isolated_app_paths, capsys, monkeypatch):
    _seed_profile(isolated_app_paths)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "Blake")

    exit_code = main(["profile", "delete", "p1"])

    assert exit_code == 0
    assert _saved_profile_ids(isolated_app_paths) == []


def test_profile_delete_aborts_on_a_wrong_confirmation(isolated_app_paths, capsys, monkeypatch):
    _seed_profile(isolated_app_paths)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")

    exit_code = main(["profile", "delete", "p1"])

    assert exit_code == 1
    assert "Not deleted." in capsys.readouterr().err
    assert _saved_profile_ids(isolated_app_paths) == ["p1"]


def test_profile_delete_reports_an_unknown_id(isolated_app_paths, capsys):
    exit_code = main(["profile", "delete", "no-such-profile", "--yes"])

    assert exit_code == 1
    assert "no profile with id" in capsys.readouterr().err


# -- `syzygy oracle` (M19.5a) --------------------------------------------


def test_oracle_list_and_show_reopen_local_question_data(isolated_app_paths, capsys):
    from datetime import UTC, datetime

    from syzygy.clock import FixedClock
    from syzygy.storage.consultation_service import ask_question
    from syzygy.storage.database import open_database
    from syzygy.storage.profiles import get_profile

    _seed_profile(isolated_app_paths)
    conn = open_database(isolated_app_paths.database_path)
    try:
        profile = get_profile(conn, "p1")
        assert profile is not None
        consultation = ask_question(
            conn,
            profile,
            FixedClock(datetime(2026, 8, 9, 12, tzinfo=UTC)),
            "What remains mine to choose?",
        )
    finally:
        conn.close()

    assert main(["oracle", "list"]) == 0
    listing = capsys.readouterr().out
    assert consultation.id in listing
    assert "What remains mine to choose?" in listing

    assert main(["oracle", "show", consultation.id]) == 0
    shown = capsys.readouterr().out
    assert f"Oracle {consultation.id}" in shown
    assert "Question: What remains mine to choose?" in shown
    assert "Status: asked" in shown


def test_oracle_show_reports_an_unknown_id(isolated_app_paths, capsys):
    assert main(["oracle", "show", "missing"]) == 1
    assert "no Oracle consultation" in capsys.readouterr().err


def test_oracle_ask_draws_and_interprets_without_a_configured_model(
    isolated_app_paths, capsys, monkeypatch
):
    from datetime import UTC, datetime

    from syzygy.astrology.policy import POLICY_VERSION
    from syzygy.clock import FixedClock
    from syzygy.domain.astrology import TransitSnapshot
    from syzygy.interpretation.providers.fixture import FixtureProvider
    from syzygy.storage.database import open_database
    from syzygy.tui.app import SyzygyServices

    class QuietSky:
        def calculate_transits(self, natal, instant):
            return TransitSnapshot(
                instant_utc=instant,
                transiting_positions=[],
                raw_aspects=[],
                astrology_policy_version=POLICY_VERSION,
            )

    _seed_profile(isolated_app_paths)

    class FixedEntropyCollector:
        """Select The Fool so this CLI contract never depends on OS entropy."""

        def record(self, _kind: str) -> None:
            pass

        def digest(self) -> bytes:
            return bytes(32)

    def services():
        return SyzygyServices(
            conn=open_database(isolated_app_paths.database_path),
            clock=FixedClock(datetime(2026, 8, 9, 12, tzinfo=UTC)),
            astrology=QuietSky(),
            provider=FixtureProvider(),
            settings_path=isolated_app_paths.settings_path,
        )

    monkeypatch.setattr("syzygy.tui.app.default_services", services)
    monkeypatch.setattr("syzygy.sortes.entropy.EntropyCollector", FixedEntropyCollector)

    assert main(["oracle", "ask", "What now?"]) == 0
    output = capsys.readouterr().out
    assert "Question: What now?" in output
    assert "Status: complete" in output
    assert "Response" in output

    assert "Esoteric" in output
    assert "Conventional" in output


def test_oracle_ask_casts_both_objects_and_ignores_the_retired_mode_flag(
    isolated_app_paths, capsys, monkeypatch
):
    """M22.5a: `--mode` is accepted for one release with a notice, not a failure."""
    from datetime import UTC, datetime

    from syzygy.clock import FixedClock
    from syzygy.interpretation.providers.fixture import FixtureProvider
    from syzygy.storage.database import open_database
    from syzygy.tui.app import SyzygyServices

    class NoSky:
        def calculate_transits(self, natal, instant):
            raise AssertionError("the Oracle must not read the day's transits")

    class FixedEntropyCollector:
        def record(self, _kind: str) -> None:
            pass

        def digest(self) -> bytes:
            return bytes(32)

    _seed_profile(isolated_app_paths)

    def services():
        return SyzygyServices(
            conn=open_database(isolated_app_paths.database_path),
            clock=FixedClock(datetime(2026, 8, 9, 12, tzinfo=UTC)),
            astrology=NoSky(),
            provider=FixtureProvider(),
            settings_path=isolated_app_paths.settings_path,
        )

    monkeypatch.setattr("syzygy.tui.app.default_services", services)
    monkeypatch.setattr("syzygy.sortes.entropy.EntropyCollector", FixedEntropyCollector)

    assert main(["oracle", "ask", "What now?", "--mode", "iching"]) == 0
    captured = capsys.readouterr()
    assert "no longer a choice" in captured.err
    output = captured.out
    assert "The figure: " in output
    assert "The ground: " in output
    assert "Lines (bottom first):" in output
    assert "Movement: " in output
    assert "Status: complete" in output
    assert "Response" in output

    conn = open_database(isolated_app_paths.database_path)
    try:
        from syzygy.storage.consultations import list_consultations

        consultation = list_consultations(conn, "p1")[0]
    finally:
        conn.close()
    assert consultation.card_draw is not None
    assert consultation.cast is not None

    assert main(["oracle", "list"]) == 0
    listing = capsys.readouterr().out
    assert "ORACLE" in listing
    assert " in " in listing
    assert main(["oracle", "show", consultation.id]) == 0
    assert "Lines (bottom first):" in capsys.readouterr().out


def test_oracle_show_marks_a_legacy_record_as_the_rite_it_was(isolated_app_paths, capsys):
    from syzygy.storage.database import open_database

    _seed_profile(isolated_app_paths)
    conn = open_database(isolated_app_paths.database_path)
    try:
        from tests.storage.test_legacy_consultations import insert_legacy_iching_row

        insert_legacy_iching_row(conn, "p1")
    finally:
        conn.close()

    assert main(["oracle", "show", "legacy-iching"]) == 0
    shown = capsys.readouterr().out
    assert "Historical rite: an I Ching cast alone, with no card" in shown
    assert "The ground: " in shown

    assert main(["oracle", "list"]) == 0
    assert "was: I CHING" in capsys.readouterr().out


# -- `syzygy dev animate` (M17.2e) ---------------------------------------


def test_dev_animate_refuses_without_the_dev_switch(capsys, monkeypatch):
    """A bench, not a feature: it must not be one command away for
    somebody who only installed the application."""
    from syzygy.dev import DEV_MODE_ENV_VAR

    monkeypatch.delenv(DEV_MODE_ENV_VAR, raising=False)

    exit_code = main(["dev", "animate"])

    assert exit_code == 1
    assert "SYZYGY_DEV" in capsys.readouterr().err


def test_dev_animate_opens_the_bench_when_enabled(monkeypatch):
    from syzygy.dev import DEV_MODE_ENV_VAR
    from syzygy.tui.screens import animation_demo

    monkeypatch.setenv(DEV_MODE_ENV_VAR, "1")
    launched: list[str] = []
    monkeypatch.setattr(
        animation_demo.AnimationDemoApp, "run", lambda self: launched.append("run")
    )

    assert main(["dev", "animate"]) == 0
    assert launched == ["run"]


# -- `syzygy dev reroll` (M11.6) -----------------------------------------


def test_dev_reroll_refuses_without_the_dev_switch(isolated_app_paths, capsys, monkeypatch):
    from syzygy.dev import DEV_MODE_ENV_VAR

    monkeypatch.delenv(DEV_MODE_ENV_VAR, raising=False)
    _seed_profile(isolated_app_paths)

    exit_code = main(["dev", "reroll", "--yes"])

    assert exit_code == 1
    assert "SYZYGY_DEV" in capsys.readouterr().err


def test_dev_reroll_reports_when_there_is_nothing_to_discard(
    isolated_app_paths, capsys, monkeypatch
):
    from syzygy.dev import DEV_MODE_ENV_VAR

    monkeypatch.setenv(DEV_MODE_ENV_VAR, "1")
    _seed_profile(isolated_app_paths)

    exit_code = main(["dev", "reroll", "--yes"])

    assert exit_code == 0
    assert "No reading" in capsys.readouterr().out


def test_dev_reroll_aborts_on_a_wrong_confirmation(isolated_app_paths, capsys, monkeypatch):
    from syzygy.dev import DEV_MODE_ENV_VAR

    monkeypatch.setenv(DEV_MODE_ENV_VAR, "1")
    monkeypatch.setattr("builtins.input", lambda *a, **k: "yes")
    _seed_profile(isolated_app_paths)

    exit_code = main(["dev", "reroll"])

    assert exit_code == 1
    assert "Not discarded." in capsys.readouterr().err
