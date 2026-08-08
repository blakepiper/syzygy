"""`default_services` reads the provider selection wired up alongside it
(`syzygy.interpretation.providers.selection`) rather than always defaulting
to `FixtureProvider`.

Uses an explicit `database_path` so it never touches the real machine's
`platformdirs` data directory - `default_services` derives the settings
file's path from that same tmp directory (see its docstring/comment).
Never touches the real OS keyring: the fallback case here is an
unrecognized provider id, which fails identically to a missing API key
(`ProviderBuildError`) without needing a keyring fake.
"""

from __future__ import annotations

import json

from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.interpretation.providers.llama_cpp import LlamaCppProvider
from syzygy.tui.app import default_services


def test_default_services_uses_fixture_with_no_settings_file(tmp_path, capsys):
    services = default_services(tmp_path / "syzygy.db")
    try:
        assert isinstance(services.provider, FixtureProvider)
        assert capsys.readouterr().err == ""
    finally:
        services.conn.close()


def test_default_services_honors_a_saved_selection(tmp_path):
    (tmp_path / "settings.json").write_text(
        json.dumps({"provider_id": "llama_cpp", "model_id": "local-test", "base_url": None})
    )

    services = default_services(tmp_path / "syzygy.db")
    try:
        assert isinstance(services.provider, LlamaCppProvider)
        assert services.provider.model_id == "local-test"
    finally:
        services.conn.close()


def test_default_services_falls_back_and_warns_on_a_bad_selection(tmp_path, capsys):
    (tmp_path / "settings.json").write_text(json.dumps({"provider_id": "bogus"}))

    services = default_services(tmp_path / "syzygy.db")
    try:
        assert isinstance(services.provider, FixtureProvider)
        err = capsys.readouterr().err
        assert "bogus" in err
        assert "fixture" in err
    finally:
        services.conn.close()
