"""Syzygy command-line entry point.

The TUI (`syzygy.tui`) is the primary interface, but every non-visual
capability should be reachable and scriptable from here too (docs/old/DESIGN.md
section 20). This module only parses arguments and dispatches; it must not
contain domain logic itself.

Commands implemented so far:

- `syzygy` (no arguments) or `syzygy tui` - launch the terminal interface
  (docs/old/DESIGN.md section 20's first listed command). `--no-audio` starts it
  without the looping theme (M15); `[S]` toggles it in-app.
- `syzygy dev deck` - enumerate the canonical 78-card deck (Milestone 1
  acceptance criterion).
- `syzygy dev astrology` - compute a natal chart and current transits for
  manually-supplied birth data (Milestone 2 acceptance criterion,
  docs/old/DESIGN.md section 20). Takes birth data directly via flags rather than
  a saved profile - it does not touch storage at all.
- `syzygy dev reroll` - discard today's reading so the ritual can be
  walked again (M11.6). Destructive, and refuses to run unless
  `SYZYGY_DEV` is set; see `syzygy.dev` for why this is a delete rather
  than anything that touches a committed card.
- `syzygy dev animate` - the animation bench (M17.2e): every semantic
  event and every named choreography, on demand, at the current motion
  level. `SYZYGY_DEV` only. It is the manual check that motion is
  actually visible on a real terminal, which no headless test can make.
- `syzygy profile create` / `syzygy profile list` / `syzygy profile
  delete` - save/list/delete profiles (Milestone 4; delete is M11.2 and
  takes the profile's readings with it). Storage lives at
  `syzygy.config.default_app_paths()`.
- `syzygy chart` - print a saved profile's natal chart.
- `syzygy knowledge ingest <pdf>` / `status` / `search` / `build-artifact`
  - ingest a Book of Thoth / companion-source PDF, inspect what is
  present, search the index, and (development-only) regenerate the
  committed citations+vectors artifact. Source PDFs live outside the
  repository (`docs/*.pdf` is gitignored); every install ships citations
  and vectors for all three sources but no passages (M13.3) - see
  docs/KNOWLEDGE_SOURCES.md and
  docs/adr/0003-ship-derived-knowledge-index-without-source-text.md.
- `syzygy model status` / `syzygy model configure <provider>` / `syzygy
  model use <provider>` - inspect, set up, and select the four
  `InterpretationProvider`s (Milestone 7.10 + the provider-selection
  wiring after it). Nothing reachable here writes to the readings
  database: hosted-provider API keys live in the OS keyring
  (`syzygy.interpretation.providers.api_keys`, docs/old/DESIGN.md section 13.3),
  and the active selection lives in a small local settings file
  (`syzygy.interpretation.providers.selection`) - `default_services`
  reads that selection to decide what `reading_service` actually calls.
- `syzygy model setup-local` / `syzygy model local status|doctor|list|
  start|stop|remove` - the guided local-model flow (M16) and the commands
  that inspect and manage what it installed. `setup-local` drives the same
  `syzygy.local_models.orchestrator.LocalSetupSession` the TUI wizard
  does, printed: it asks before downloading anything, and without a
  terminal it degrades to a read-only inventory and plan rather than
  prompting where nobody can answer. `status`/`doctor`/`list` are
  read-only and scriptable; `remove` refuses anything Syzygy cannot prove
  it downloaded. See docs/LOCAL_MODELS.md.
- `syzygy dev evaluate-local` - the maintainer evaluation harness
  (M16.3b), gated on `SYZYGY_DEV`. Needs a running model and minutes of
  compute, which is exactly why it is not a test.
- `syzygy doctor` - environment/health check: deck validation, the data
  directory, knowledge-base ingestion status per source, provider
  configuration (the same report `model status` gives), and the local
  model's health. Knowledge base, provider config, and local model are
  informational only - an empty knowledge base
  or an unconfigured provider are both supported states (the ritual falls
  back to `FixtureProvider` and to no source passages), so neither can
  fail `doctor`'s exit code.

Everything else in docs/old/DESIGN.md section 20's command list is a later
milestone's job; add subcommands there as their underlying features land,
rather than stubbing them here with a "not implemented" message.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syzygy import __version__
from syzygy.sortes.deck import DeckValidationError, load_deck

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from syzygy.domain.astrology import NatalChart


def _cmd_tui(args: argparse.Namespace) -> int:
    from syzygy.tui.app import run

    # `getattr`: `syzygy` with no arguments dispatches here too, and that
    # namespace has no flags of its own.
    run(audio=not getattr(args, "no_audio", False))
    return 0


def _cmd_dev_deck(_args: argparse.Namespace) -> int:
    try:
        deck = load_deck()
    except DeckValidationError as exc:
        print(f"deck validation failed: {exc}", file=sys.stderr)
        return 1

    for card in deck:
        suit_or_arcana = card.suit.value if card.suit else "major"
        print(f"{card.id:24s} {suit_or_arcana:8s} {card.full_name}")
    print(f"\n{len(deck)} cards total.")
    return 0


def _print_natal_chart(natal: NatalChart, *, label: str) -> None:
    print(label)
    print(f"engine: {natal.astrology_engine} {natal.astrology_engine_version}")
    print(
        f"Ascendant {natal.ascendant_longitude % 30:5.2f} deg  "
        f"Midheaven {natal.midheaven_longitude % 30:5.2f} deg"
    )
    print()
    for placement in natal.placements:
        retro = "R" if placement.retrograde else " "
        print(
            f"  {placement.body:8s} {placement.sign:12s} {placement.longitude % 30:5.2f} deg "
            f"house {placement.house:>2} {retro}"
        )
    print(f"\n{len(natal.aspects)} natal aspects.")


def _cmd_dev_astrology(args: argparse.Namespace) -> int:
    from syzygy.astrology.kerykeion_backend import KerykeionAstrologyEngine
    from syzygy.astrology.policy import TransitAspectPolicy
    from syzygy.astrology.ranking import TransitRanker
    from syzygy.domain.astrology import BirthData

    birth = BirthData(
        local_date=args.local_date,
        local_time=args.local_time,
        place_label=args.place_label,
        latitude=args.latitude,
        longitude=args.longitude,
        timezone=args.timezone,
        house_system=args.house_system,
    )
    instant = (
        datetime.fromisoformat(args.at).astimezone(UTC)
        if args.at
        else datetime.now(UTC)
    )

    engine = KerykeionAstrologyEngine()
    natal = engine.calculate_natal(birth)

    _print_natal_chart(
        natal,
        label=(
            f"Natal chart - {birth.place_label} "
            f"({birth.local_date} {birth.local_time} {birth.timezone})"
        ),
    )

    print(f"\nTransits at {instant.isoformat()}")
    snapshot = engine.calculate_transits(natal, instant)
    filtered = TransitAspectPolicy().filter(snapshot.raw_aspects)
    ranked = TransitRanker().rank(filtered)
    print(
        f"{len(snapshot.raw_aspects)} raw aspects, {len(filtered)} pass policy, "
        f"top {len(ranked)} ranked:"
    )
    for r in ranked:
        a = r.aspect
        print(
            f"  #{r.rank} {a.transiting_body:8s} {a.aspect:11s} {a.natal_target:10s} "
            f"orb {a.orb_degrees:4.2f} ({a.movement}) score {r.score:.3f}"
        )
    return 0


def _cmd_dev_reroll(args: argparse.Namespace) -> int:
    """Discard today's reading so the ritual can be walked again (M11.6).

    Destructive and development-only. See `syzygy.dev` for why this is a
    delete-then-redraw rather than anything that touches a committed card.
    """
    from syzygy.clock import SystemClock
    from syzygy.dev import DEV_MODE_ENV_VAR, dev_mode_enabled, discard_todays_reading
    from syzygy.storage.profiles import get_profile, list_profiles

    if not dev_mode_enabled():
        print(
            f"`dev reroll` is a development affordance and is disabled. "
            f"Set {DEV_MODE_ENV_VAR}=1 to enable it.",
            file=sys.stderr,
        )
        return 1

    conn = _open_profile_db()
    try:
        if args.profile_id:
            profile = get_profile(conn, args.profile_id)
            if profile is None:
                print(f"no profile with id {args.profile_id!r}", file=sys.stderr)
                return 1
        else:
            profiles = list_profiles(conn)
            if not profiles:
                print("No profiles yet.", file=sys.stderr)
                return 1
            if len(profiles) > 1:
                print("Multiple profiles exist - specify one with --profile-id:", file=sys.stderr)
                for candidate in profiles:
                    print(f"  {candidate.id}  {candidate.display_name}", file=sys.stderr)
                return 1
            profile = profiles[0]

        local_date = SystemClock().now_utc().astimezone().date().isoformat()
        if not args.yes:
            print(
                f"This discards {profile.display_name}'s reading for {local_date} - "
                f"its card and interpretation are destroyed."
            )
            if input("Type 'reroll' to confirm: ").strip() != "reroll":
                print("Not discarded.", file=sys.stderr)
                return 1

        discarded = discard_todays_reading(conn, profile.id, local_date)
    finally:
        conn.close()

    if not discarded:
        print(f"No reading for {local_date} to discard.")
        return 0
    print(f"Discarded {profile.display_name}'s reading for {local_date}. Draw again with `syzygy`.")
    return 0


def _cmd_dev_animate(_args: argparse.Namespace) -> int:
    """Open the animation bench (M17.2e).

    Development-only. No headless test can say whether a transition is
    actually visible on a real terminal; this is the screen that lets
    somebody look.
    """
    from syzygy.dev import DEV_MODE_ENV_VAR, dev_mode_enabled

    if not dev_mode_enabled():
        print(
            f"`dev animate` is a development affordance and is disabled. "
            f"Set {DEV_MODE_ENV_VAR}=1 to enable it.",
            file=sys.stderr,
        )
        return 1

    from syzygy.tui.screens.animation_demo import AnimationDemoApp

    AnimationDemoApp().run()
    return 0


def _open_profile_db() -> sqlite3.Connection:
    from syzygy.config import default_app_paths
    from syzygy.storage.database import open_database

    paths = default_app_paths()
    paths.ensure_exists()
    return open_database(paths.database_path)


def _cmd_profile_create(args: argparse.Namespace) -> int:
    import uuid

    from syzygy.astrology.kerykeion_backend import KerykeionAstrologyEngine
    from syzygy.clock import SystemClock
    from syzygy.domain.astrology import BirthData
    from syzygy.domain.profile import Profile
    from syzygy.storage.profiles import insert_profile

    birth = BirthData(
        local_date=args.local_date,
        local_time=args.local_time,
        place_label=args.place_label,
        latitude=args.latitude,
        longitude=args.longitude,
        timezone=args.timezone,
        house_system=args.house_system,
    )
    natal = KerykeionAstrologyEngine().calculate_natal(birth)
    now = SystemClock().now_utc()
    profile = Profile(
        id=str(uuid.uuid4()),
        display_name=args.display_name,
        birth_data=birth,
        natal_chart=natal,
        created_at_utc=now,
        updated_at_utc=now,
    )

    conn = _open_profile_db()
    try:
        insert_profile(conn, profile)
    finally:
        conn.close()

    print(f"Created profile {profile.id} ({profile.display_name})")
    return 0


def _cmd_profile_list(_args: argparse.Namespace) -> int:
    from syzygy.storage.profiles import list_profiles

    conn = _open_profile_db()
    try:
        profiles = list_profiles(conn)
    finally:
        conn.close()

    if not profiles:
        print("No profiles yet. Create one with `syzygy profile create`.")
        return 0

    for profile in profiles:
        birth = profile.birth_data
        print(
            f"{profile.id}  {profile.display_name:20s} "
            f"{birth.local_date} {birth.local_time} {birth.place_label}"
        )
    return 0


def _cmd_profile_delete(args: argparse.Namespace) -> int:
    from syzygy.storage.profiles import count_readings, delete_profile, get_profile

    conn = _open_profile_db()
    try:
        profile = get_profile(conn, args.profile_id)
        if profile is None:
            print(f"no profile with id {args.profile_id!r}", file=sys.stderr)
            return 1

        readings = count_readings(conn, profile.id)
        if not args.yes:
            print(
                f"This deletes {profile.display_name} ({profile.id}) and its "
                f"{readings} reading(s). This cannot be undone."
            )
            answer = input("Type the profile's name to confirm: ").strip()
            if answer != profile.display_name:
                print("Not deleted.", file=sys.stderr)
                return 1

        deleted = delete_profile(conn, profile.id)
    finally:
        conn.close()

    print(f"Deleted profile {profile.id} ({profile.display_name}) and {deleted} reading(s)")
    return 0


def _cmd_chart(args: argparse.Namespace) -> int:
    from syzygy.storage.profiles import get_profile, list_profiles

    conn = _open_profile_db()
    try:
        if args.profile_id:
            profile = get_profile(conn, args.profile_id)
            if profile is None:
                print(f"no profile with id {args.profile_id!r}", file=sys.stderr)
                return 1
        else:
            profiles = list_profiles(conn)
            if not profiles:
                print("No profiles yet. Create one with `syzygy profile create`.", file=sys.stderr)
                return 1
            if len(profiles) > 1:
                print(
                    "Multiple profiles exist - specify one with --profile-id:",
                    file=sys.stderr,
                )
                for p in profiles:
                    print(f"  {p.id}  {p.display_name}", file=sys.stderr)
                return 1
            profile = profiles[0]
    finally:
        conn.close()

    _print_natal_chart(profile.natal_chart, label=f"Natal chart - {profile.display_name}")
    return 0


def _cmd_knowledge_ingest(args: argparse.Namespace) -> int:
    from pathlib import Path

    from syzygy.clock import SystemClock
    from syzygy.knowledge.ingest import UnknownSourceTypeError, ingest

    pdf_path = Path(args.pdf_path)
    if not pdf_path.is_file():
        print(f"no such file: {pdf_path}", file=sys.stderr)
        return 1

    conn = _open_profile_db()
    try:
        try:
            result = ingest(
                conn, pdf_path, now=SystemClock().now_utc(), source_type=args.source_type
            )
        except UnknownSourceTypeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    finally:
        conn.close()

    if result.skipped:
        print(f"{result.source_type}: already ingested at the current version, skipped")
    else:
        print(
            f"{result.source_type}: ingested {result.chunk_count} chunks "
            f"across {result.card_count} cards"
        )
    return 0


def _cmd_knowledge_status(_args: argparse.Namespace) -> int:
    from syzygy.knowledge.status import any_full_text, source_statuses

    conn = _open_profile_db()
    try:
        statuses = source_statuses(conn)
    finally:
        conn.close()

    for status in statuses:
        # Citations-only is the normal state for anyone who has not
        # supplied their own PDFs (M13.3), so it is reported as a mode
        # rather than as a shortfall.
        version = f" (version {status.ingestion_version})" if status.ingestion_version else ""
        print(
            f"{status.source_type:26s} {status.chunk_count:4d} chunks  "
            f"{status.state.value:15s}{version}"
        )
        if status.detail:
            print(f"{'':26s}      {status.detail}")

    if not any_full_text(statuses):
        print(
            "\nNo source passages are available, so readings are interpreted without\n"
            "them. Run `syzygy knowledge ingest <pdf>` against your own copies of the\n"
            "books to add them - see docs/KNOWLEDGE_SOURCES.md."
        )
    return 0


def _cmd_knowledge_search(args: argparse.Namespace) -> int:
    from syzygy.knowledge.retrieve import search_vectors

    conn = _open_profile_db()
    try:
        hits = search_vectors(conn, args.query, limit=args.limit)
    finally:
        conn.close()

    if not hits:
        print("No matches.")
        return 0
    for hit in hits:
        chunk = hit.chunk
        card = f"  [{chunk.card_id}]" if chunk.card_id else ""
        print(f"{hit.score:.3f}  {chunk.citation}{card}")
    return 0


def _cmd_knowledge_build_artifact(args: argparse.Namespace) -> int:
    """Regenerate the committed knowledge artifact (M13.3b).

    Development-only, and deliberately separate from `ingest`: it reads an
    ingested database and writes citations plus vectors, never text. See
    `docs/adr/0003-ship-derived-knowledge-index-without-source-text.md`.
    """
    from pathlib import Path

    from syzygy.knowledge.artifact import ArtifactError, build_artifact, write_artifact

    if args.database:
        from syzygy.storage.database import open_database

        conn = open_database(Path(args.database))
    else:
        conn = _open_profile_db()

    try:
        artifact = build_artifact(conn)
    except ArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        conn.close()

    index_path, vectors_path = write_artifact(artifact, Path(args.output))
    print(
        f"Wrote {len(artifact.chunks)} citations from {len(artifact.sources)} sources:\n"
        f"  {index_path} ({index_path.stat().st_size:,} bytes)\n"
        f"  {vectors_path} ({vectors_path.stat().st_size:,} bytes)"
    )
    return 0


#: The two hosted providers that need a stored credential; `llama_cpp`
#: needs none (docs/old/DESIGN.md section 13.2) so it is reported separately in
#: `_cmd_model_status` and left out of `model configure`'s choices.
_HOSTED_PROVIDERS = ("openai", "anthropic")
_HOSTED_PROVIDER_ENV_VARS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}

#: Every id `model use` accepts. Kept as a local literal, not imported from
#: `syzygy.interpretation.providers.selection`, so building the argument
#: parser (and therefore every `syzygy ...` invocation, including
#: `--help`) never requires the `providers` extra (httpx, keyring) to be
#: installed - only actually running a `model` subcommand does, via the
#: lazy imports inside each `_cmd_model_*` function below.
_PROVIDER_IDS = ("fixture", "llama_cpp", "openai", "anthropic")


def _settings_path() -> Path:
    from syzygy.config import default_app_paths

    return default_app_paths().settings_path


def _print_provider_status() -> None:
    """Shared by `model status` and `doctor` - which providers are usable
    right now, and which one a reading would actually use.
    """
    import asyncio
    import os

    from syzygy.interpretation.providers import llama_cpp
    from syzygy.interpretation.providers.api_keys import has_stored_api_key
    from syzygy.interpretation.providers.selection import load_selection, resolve_selected_provider

    reachable = asyncio.run(llama_cpp.probe())
    state = "reachable" if reachable else "not reachable"
    print(f"llama_cpp    {state} at {llama_cpp.DEFAULT_BASE_URL} (no API key needed)")

    for provider_id in _HOSTED_PROVIDERS:
        env_var = _HOSTED_PROVIDER_ENV_VARS[provider_id]
        if has_stored_api_key(provider_id):
            print(f"{provider_id:12s} key stored in keyring")
        elif os.environ.get(env_var):
            print(f"{provider_id:12s} key set via {env_var}")
        else:
            print(
                f"{provider_id:12s} no key configured "
                f"(`syzygy model configure {provider_id}`, or set {env_var})"
            )

    selection = load_selection(_settings_path())
    if selection is None:
        print("\nactive provider: fixture (default - select one with `syzygy model use`)")
        return

    _, fallback_reason = resolve_selected_provider(selection)
    label = selection.provider_id + (f" ({selection.model_id})" if selection.model_id else "")
    if fallback_reason:
        print(f"\nactive provider: {label} - CURRENTLY FALLING BACK TO FIXTURE: {fallback_reason}")
    else:
        print(f"\nactive provider: {label}")


def _cmd_model_status(_args: argparse.Namespace) -> int:
    _print_provider_status()
    return 0


def _cmd_model_configure(args: argparse.Namespace) -> int:
    from syzygy.interpretation.providers.api_keys import delete_api_key, store_api_key

    if args.delete:
        delete_api_key(args.provider)
        print(f"Removed any stored key for {args.provider}.")
        return 0

    import getpass

    # Never accepted as a positional/flag argument - that would land it in
    # shell history and in the process list (docs/old/DESIGN.md section 28: do not
    # expose API keys in diagnostics).
    api_key = getpass.getpass(f"{args.provider} API key (input hidden): ")
    if not api_key:
        print("No key entered, nothing stored.", file=sys.stderr)
        return 1

    store_api_key(args.provider, api_key)
    print(f"Stored a key for {args.provider} in the OS keyring.")
    return 0


def _cmd_model_use(args: argparse.Namespace) -> int:
    from syzygy.interpretation.providers.selection import (
        FIXTURE_PROVIDER_ID,
        HOSTED_PROVIDER_IDS,
        ProviderBuildError,
        ProviderSelection,
        build_provider,
        clear_selection,
        save_selection,
    )

    settings_path = _settings_path()

    if args.provider == FIXTURE_PROVIDER_ID:
        clear_selection(settings_path)
        print("Active provider set to fixture.")
        return 0

    selection = ProviderSelection(
        provider_id=args.provider, model_id=args.model, base_url=args.base_url
    )
    try:
        build_provider(selection)
    except ProviderBuildError as exc:
        # Saved anyway: fixing the underlying problem (adding a key,
        # starting llama-server) shouldn't require re-running `model use`
        # too - `model status`/the next reading will pick it up once fixed.
        print(f"warning: {exc}", file=sys.stderr)
        print("Selection saved, but readings will use fixture until this is fixed.")

    if args.provider in HOSTED_PROVIDER_IDS:
        print(
            f"Selecting {args.provider} sends today's reading context (profile name, "
            "chart placements, the drawn card, ranked transits, source passages) to its "
            "servers on every reading from now on (docs/old/DESIGN.md section 13.3)."
        )

    save_selection(settings_path, selection)
    label = args.provider + (f" ({args.model})" if args.model else "")
    print(f"Active provider set to {label}.")
    return 0


def _cmd_dev_evaluate_local(args: argparse.Namespace) -> int:
    """Run the maintainer evaluation harness (M16.3b).

    Development-only and opt-in: it needs a running model and minutes of
    compute, which is exactly why it is not a test. It never writes to the
    catalog - a passing run produces a results file a maintainer reviews
    and commits, and only then may an artifact claim `supported`.
    """
    import json

    from syzygy.dev import DEV_MODE_ENV_VAR, dev_mode_enabled
    from syzygy.local_models.evaluation.harness import evaluate, release_gate
    from syzygy.local_models.fit import SYZYGY_CONTEXT_TOKENS

    if not dev_mode_enabled():
        print(
            f"`dev evaluate-local` is a maintainer tool and is disabled. "
            f"Set {DEV_MODE_ENV_VAR}=1 to enable it.",
            file=sys.stderr,
        )
        return 1

    print(f"Evaluating {args.artifact} at {args.base_url} on {args.hardware}…\n")
    run = evaluate(
        base_url=args.base_url,
        served_model_id=args.model,
        artifact_id=args.artifact,
        runtime_version=args.runtime_version,
        hardware=args.hardware,
        context_tokens=SYZYGY_CONTEXT_TOKENS,
        on_case=lambda result: print(
            f"  {result.case_id:24s} "
            f"{'ok ' if result.succeeded else 'FAIL'} "
            f"{result.seconds:6.1f}s "
            f"{'repaired ' if result.repaired else ''}"
            f"{'TRUNCATED ' if result.truncated else ''}"
            f"{('missing: ' + ','.join(result.missing_facts)) if result.missing_facts else ''}"
            f"{('LEAKED: ' + ','.join(result.leaked)) if result.leaked else ''}"
        ),
    )
    if args.peak_memory_bytes:
        run.peak_memory_bytes = args.peak_memory_bytes

    print(
        f"\nschema-valid first pass {run.schema_valid_rate:.0%}  "
        f"repair {run.repair_rate:.0%}  success {run.success_rate:.0%}"
    )
    if run.median_tokens_per_second:
        print(f"median {run.median_tokens_per_second:.1f} tokens/second")

    gate = release_gate(run, license_reviewed=args.license_reviewed)
    print(f"\nrelease gate: {'PASS' if gate.passed else 'NOT PASSED'}")
    for reason in gate.reasons:
        print(f"  · {reason}")
    if not gate.passed:
        print("\nRubric scores and peak memory are recorded by hand; see")
        print("docs/LOCAL_MODEL_MAINTENANCE.md before promoting a catalogue entry.")

    if args.out:
        from pathlib import Path as _Path

        target = _Path(args.out)
        target.write_text(json.dumps(run.to_json(), indent=2) + "\n", encoding="utf-8")
        print(f"\nWrote {target}")
    return 0 if gate.passed else 1


# -- local models (M16.10a) ---------------------------------------------------


def _local_paths():
    from syzygy.config import default_app_paths
    from syzygy.local_models.paths import LocalModelPaths

    paths = default_app_paths()
    paths.ensure_exists()
    layout = LocalModelPaths.from_app_paths(paths)
    layout.ensure_exists()
    return layout


def _confirm(question: str, *, assume_yes: bool) -> bool:
    """A yes/no prompt that never hangs a non-interactive run.

    Without a terminal there is nobody to answer, so the answer is no
    unless `--yes` was passed - which is why `--yes` exists at all
    (M16.10a: do not make CI prompts hang).
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print("Not a terminal, and --yes was not given: nothing was done.", file=sys.stderr)
        return False
    try:
        answer = input(f"{question} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


def _cmd_model_setup_local(args: argparse.Namespace) -> int:
    """The same orchestrator the TUI wizard drives, printed.

    Interactive when attached to a terminal. Without one it degrades to a
    read-only inventory and recommendation report and exits 0 - a
    scripted environment gets information, never a download it did not
    ask for and never a prompt nobody can answer.
    """
    from syzygy.local_models.orchestrator import LocalSetupSession, SetupStepError
    from syzygy.local_models.report import machine_lines, setup_plan_lines
    from syzygy.local_models.state import STATE_LABELS

    paths = _local_paths()
    session = LocalSetupSession(paths=paths, settings_path=_settings_path())

    print(STATE_LABELS[session.state])
    assessment = session.run_inventory()
    print(f"\n{assessment.headline}\n{assessment.detail}\n")
    if session.inventory is not None:
        for line in machine_lines(session.inventory):
            print(f"  {line}")

    print("\nLooking for a model runner you already have…")
    report = session.run_discovery()
    for item in (*report.endpoints, *report.binaries):
        print(f"  {item.candidate.locator}: {item.compatibility.value} - {item.next_action}")
    if not report.anything_found:
        print("  nothing found (that's normal)")

    interactive = sys.stdin.isatty() and sys.stdout.isatty()

    endpoint = report.usable_endpoint
    if endpoint is not None:
        print(f"\nA compatible server is already running at {endpoint.candidate.locator}.")
        if not interactive and not args.yes:
            print("Run this in a terminal, or pass --yes, to use it.")
            return 0
        if not _confirm("Use it for readings?", assume_yes=args.yes):
            return 0
        session.use_existing_endpoint(endpoint)
        return _finish_local_setup(session)

    recommendation = session.build_recommendation()
    if recommendation.artifact is None:
        print(f"\n{recommendation.rationale}")
        return 0
    if args.tier:
        from syzygy.local_models.contracts import ModelTier

        chosen = session.catalog.by_tier(ModelTier(args.tier))
        if chosen is None:
            print(f"No model is offered in the {args.tier} tier.", file=sys.stderr)
            return 1
        session.choose(chosen.id)

    artifact = session.chosen or recommendation.artifact
    print(f"\nRecommended: {artifact.display_name}")
    print(recommendation.rationale)

    try:
        receipt = session.prepare_consent()
    except SetupStepError as exc:
        print(f"\n{exc.failure.message}", file=sys.stderr)
        if exc.failure.detail:
            print(exc.failure.detail, file=sys.stderr)
        return 1

    print()
    for line in setup_plan_lines(receipt):
        print(line)

    if not interactive and not args.yes:
        print("\nThis is a read-only report: no terminal to confirm at.")
        print("Re-run in a terminal, or pass --yes to accept the plan above.")
        return 0
    if not _confirm("\nDo this?", assume_yes=args.yes):
        print("Nothing was downloaded.")
        return 0

    session.accept_terms()
    try:
        print("\nGetting the model runner…")
        session.install_runtime(on_progress=_print_progress)
        print("\nDownloading the model…")
        session.fetch_model(on_progress=_print_progress)
        print("\nStarting the model…")
        session.start_server(on_phase=lambda _phase, text: print(f"  {text}"))
    except SetupStepError as exc:
        print(f"\n{exc.failure.message}", file=sys.stderr)
        if exc.failure.detail:
            print(exc.failure.detail, file=sys.stderr)
        return 1
    return _finish_local_setup(session)


_progress_state = {"last": -1}


def _print_progress(done: int, total: int | None) -> None:
    """Whole percentages only. A CLI that reprints a bar for every chunk
    fills a scrollback and a CI log with nothing."""
    if not total:
        return
    percent = int(100 * done / total)
    if percent == _progress_state["last"]:
        return
    _progress_state["last"] = percent
    print(f"\r  {percent:3d}%", end="" if percent < 100 else "\n", flush=True)


def _finish_local_setup(session) -> int:
    print("\nChecking it can write a Syzygy reading…")
    try:
        outcome = session.verify_and_activate()
    finally:
        # Setup started a server to check it; setup is not a reason to
        # leave one running. Syzygy starts it again on demand when a
        # reading needs it (M16.7b) - and a multi-gigabyte process left
        # behind by a command that has finished is exactly what ADR 0005
        # says must not happen.
        if session.supervisor is not None:
            session.supervisor.stop()

    if not outcome.activated:
        failure = outcome.failure
        print(f"\n{failure.message if failure else 'Verification failed.'}", file=sys.stderr)
        if failure and failure.detail:
            print(failure.detail, file=sys.stderr)
        print("Readings are unchanged.", file=sys.stderr)
        return 1
    for capability in outcome.result.capabilities:
        print(f"  {capability.name}: OK ({capability.seconds:.1f}s)")
    print("\nReady. Readings now use the local model.")
    print("Syzygy starts and stops the model itself; nothing is running now.")
    return 0


def _cmd_model_local_status(_args: argparse.Namespace) -> int:
    from syzygy.local_models.report import status_lines

    for line in status_lines(_settings_path(), _local_paths()):
        print(line)
    return 0


def _cmd_model_local_doctor(args: argparse.Namespace) -> int:
    from syzygy.local_models.report import doctor_lines

    lines, ok = doctor_lines(_settings_path(), _local_paths(), deep=args.deep)
    for line in lines:
        print(line)
    return 0 if ok else 1


def _cmd_model_local_start(_args: argparse.Namespace) -> int:
    from syzygy.local_models.managed_provider import ManagedLocalProvider
    from syzygy.local_models.settings import ManagementMode, load_local_model_settings
    from syzygy.local_models.supervisor import ServerStartError

    settings = load_local_model_settings(_settings_path())
    if settings.mode is not ManagementMode.MANAGED:
        print("No managed local model is configured.", file=sys.stderr)
        return 1

    provider = ManagedLocalProvider(_settings_path(), _local_paths())
    try:
        base_url = provider._ensure_running()  # noqa: SLF001 - the CLI is the other front end
    except ServerStartError as exc:
        print(exc.failure.message, file=sys.stderr)
        if exc.failure.detail:
            print(exc.failure.detail, file=sys.stderr)
        return 1

    print(f"Local model server listening at {base_url}")
    print("Leave this running and press Ctrl-C to stop it.")
    print("(The interface starts and stops its own; this is for testing by hand.)")
    try:
        # Stay in the foreground. Returning here would orphan a
        # multi-gigabyte process with nothing left to stop it, and the
        # only honest alternative - a detached daemon - is the
        # cross-platform orphan handling ADR 0005 puts out of scope.
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nStopping…")
    finally:
        provider.stop()
    return 0


def _cmd_model_local_stop(_args: argparse.Namespace) -> int:
    from syzygy.local_models.probe import Probe
    from syzygy.local_models.runtime_state import load_runtime_state
    from syzygy.local_models.supervisor import verify_recorded_process

    paths = _local_paths()
    state = load_runtime_state(paths.state_path)
    if state.process is None:
        print("No local model server is recorded as running.")
        return 0

    verified, reason = verify_recorded_process(state.process, Probe.real())
    if not verified:
        # Never signal something we cannot identify: clear the stale
        # record instead (M16.7d).
        from syzygy.local_models.runtime_state import save_runtime_state

        save_runtime_state(paths.state_path, state.model_copy(update={"process": None}))
        print(f"Stale record cleared: {reason}. Nothing was signalled.")
        return 0

    import os
    import signal

    os.kill(state.process.pid, signal.SIGTERM)
    from syzygy.local_models.runtime_state import save_runtime_state

    save_runtime_state(paths.state_path, state.model_copy(update={"process": None}))
    print(f"Asked pid {state.process.pid} to stop.")
    return 0


def _cmd_model_local_list(_args: argparse.Namespace) -> int:
    from syzygy.local_models.diagnostics import format_bytes
    from syzygy.local_models.model_install import list_local_models

    rows = list_local_models(_local_paths(), _settings_path())
    if not rows:
        print("No local model files.")
        return 0
    for row in rows:
        owner = "managed" if row.syzygy_owned else "external"
        used = " (in use)" if row.in_use else ""
        print(f"{row.path}")
        print(f"    {owner}, {format_bytes(row.size_bytes)}, {row.verification}{used}")
        if not row.removable:
            print("    Syzygy will never delete this file.")
    return 0


def _cmd_model_local_use_file(args: argparse.Namespace) -> int:
    """Point Syzygy at a `.gguf` the user already has (M16.6c).

    An explicit path, always. Syzygy does not crawl the home directory
    looking for models - a background scan of somebody's disk is not
    something an astrology program should do, and the file is referenced
    where it is, never moved, rewritten, or removed.
    """
    from pathlib import Path as _Path

    from syzygy.local_models.inventory import collect_inventory
    from syzygy.local_models.model_install import inspect_external_model, use_external_model
    from syzygy.local_models.settings import (
        ManagementMode,
        RuntimeRecord,
        load_local_model_settings,
        save_local_model_settings,
    )

    paths = _local_paths()
    target = _Path(args.path).expanduser()
    inventory = collect_inventory(model_dir=target.parent)
    report = inspect_external_model(target, inventory)

    print(f"{target}")
    if report.metadata is not None:
        print(
            f"  {report.metadata.architecture}, {report.metadata.block_count} layers, "
            f"trained for {report.metadata.context_length} tokens"
        )
    print(f"  {report.reason}")

    if not report.usable:
        print("\nSyzygy will not use this file.", file=sys.stderr)
        return 1
    if report.fits is False and not args.yes:
        print(
            "\nThis is larger than Syzygy estimates this computer can run. "
            "Pass --yes to use it anyway.",
            file=sys.stderr,
        )
        return 1

    settings = load_local_model_settings(_settings_path())
    if settings.runtime is None or not (settings.runtime.path or settings.runtime.base_url):
        print(
            "\nNo model runner is configured yet. Run `syzygy model setup-local` "
            "first, or start your own server and use `syzygy model use llama_cpp`.",
            file=sys.stderr,
        )
        return 1

    use_external_model(_settings_path(), report, served_model_id=target.stem)
    settings = load_local_model_settings(_settings_path())
    save_local_model_settings(
        _settings_path(),
        settings.model_copy(
            update={
                "mode": ManagementMode.MANAGED,
                # The verification recorded against the previous model no
                # longer covers this one.
                "last_verification": None,
                "runtime": settings.runtime or RuntimeRecord(),
            }
        ),
    )
    print(f"\nSyzygy will use {target} and will never move or delete it.")
    print("It has not been verified yet - the next reading runs the check, or run")
    print("`syzygy model local doctor`.")
    _ = paths
    return 0


def _cmd_model_local_remove(args: argparse.Namespace) -> int:
    from pathlib import Path as _Path

    from syzygy.local_models.model_install import remove_managed_model
    from syzygy.local_models.paths import is_syzygy_owned

    paths = _local_paths()
    target = _Path(args.path).expanduser()

    if not is_syzygy_owned(paths, target):
        print(
            f"{target} is not a file Syzygy downloaded, so it will not be removed.",
            file=sys.stderr,
        )
        return 1
    if not _confirm(f"Delete {target}?", assume_yes=args.yes):
        return 0
    if not remove_managed_model(paths, target, _settings_path()):
        print(f"Could not remove {target}.", file=sys.stderr)
        return 1
    print(f"Removed {target}. `syzygy model setup-local` can download it again.")
    return 0


def _cmd_doctor(_args: argparse.Namespace) -> int:
    ok = True

    print(f"syzygy {__version__}")
    print(f"python  {sys.version.split()[0]}")

    try:
        deck = load_deck()
        print(f"deck    OK ({len(deck)} cards)")
    except DeckValidationError as exc:
        print(f"deck    FAILED: {exc}")
        ok = False

    from syzygy.config import default_app_paths

    paths = default_app_paths()
    try:
        paths.ensure_exists()
        print(f"data dir OK ({paths.data_dir})")
    except OSError as exc:
        print(f"data dir FAILED: {exc}")
        ok = False
        # Nothing below here can be checked without a data directory.
        return 1

    print()
    _doctor_knowledge_base()
    print()
    _doctor_providers()
    print()
    _doctor_local_model()

    return 0 if ok else 1


def _doctor_knowledge_base() -> None:
    """Informational only: an empty knowledge base is a supported state
    (a reading still completes with `knowledge_chunks=[]`), so nothing
    here can fail `doctor`'s exit code - it just tells the user what's
    ingested.

    M18.1d: "citations only" and "ingested but broken" are different
    answers and used to render identically. The first is what every fresh
    install looks like and is labelled as normal; the second names what is
    wrong with it, because it is the only one worth acting on.
    """
    from syzygy.knowledge.status import SourceState, broken, source_statuses

    conn = _open_profile_db()
    try:
        statuses = source_statuses(conn)
    finally:
        conn.close()

    labels = {
        SourceState.ABSENT: "not present",
        SourceState.CITATIONS_ONLY: "citations only (normal)",
        SourceState.FULL_TEXT: "full text",
        SourceState.BROKEN: "NEEDS ATTENTION",
    }
    for status in statuses:
        counts = f"{status.chunk_count:4d} chunks, " if status.chunk_count else ""
        print(f"knowledge {status.source_type:26s} {counts}{labels[status.state]}")
        if status.detail:
            print(f"          {status.detail}")

    if broken(statuses):
        print("(re-ingest the affected source with `syzygy knowledge ingest <pdf>`)")
    elif not any(status.has_text for status in statuses):
        print("(citations only - readings still work, with no source passages;")
        print(" see `syzygy knowledge ingest`, or press [K] in the interface)")


def _doctor_providers() -> None:
    """Informational only, same reasoning as `_doctor_knowledge_base` - an
    unconfigured provider is a supported state (`default_services` falls
    back to `FixtureProvider`), so this cannot fail `doctor`'s exit code.
    """
    try:
        _print_provider_status()
    except ImportError as exc:
        print(f"provider check skipped: {exc} (install the `providers` extra)")


def _doctor_local_model() -> None:
    """Informational, same reasoning as the two above (M16.10b): a missing
    local model is a supported state, not a failing environment
    requirement, so it cannot fail `doctor`'s exit code. A *broken* one is
    reported loudly but still does not - `syzygy model local doctor` is
    the command whose exit code means something."""
    try:
        from syzygy.local_models.report import doctor_lines

        lines, ok = doctor_lines(_settings_path(), _local_paths())
    except Exception as exc:  # noqa: BLE001 - never fail doctor on this
        print(f"local model check skipped: {type(exc).__name__}: {exc}")
        return
    for line in lines:
        print(line)
    if not ok:
        print("(run `syzygy model local doctor` for the exit code, or repair it with [M])")


def _add_birth_data_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--local-date", required=True, help="e.g. 1990-08-07")
    parser.add_argument("--local-time", required=True, help="e.g. 14:22:00")
    parser.add_argument("--place-label", default="")
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--timezone", required=True, help="IANA zone, e.g. America/New_York")
    parser.add_argument("--house-system", default="placidus")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="syzygy", description=__doc__)
    parser.add_argument("--version", action="version", version=f"syzygy {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    tui_parser = subparsers.add_parser("tui", help="launch the terminal interface (default)")
    tui_parser.add_argument(
        "--no-audio",
        action="store_true",
        help="start with no theme music (the [S] key toggles it per session)",
    )
    tui_parser.set_defaults(func=_cmd_tui)

    dev_parser = subparsers.add_parser("dev", help="development/debug utilities")
    dev_subparsers = dev_parser.add_subparsers(dest="dev_command")
    dev_deck_parser = dev_subparsers.add_parser("deck", help="enumerate the canonical deck")
    dev_deck_parser.set_defaults(func=_cmd_dev_deck)

    dev_astrology_parser = dev_subparsers.add_parser(
        "astrology", help="compute a natal chart and current transits for manual birth data"
    )
    _add_birth_data_args(dev_astrology_parser)
    dev_astrology_parser.add_argument(
        "--at", default=None, help="ISO instant for transits (default: now, UTC)"
    )
    dev_astrology_parser.set_defaults(func=_cmd_dev_astrology)

    dev_reroll_parser = dev_subparsers.add_parser(
        "reroll",
        help="discard today's reading so the ritual can be walked again (SYZYGY_DEV only)",
    )
    dev_reroll_parser.add_argument(
        "--profile-id", default=None, help="required if more than one profile is saved"
    )
    dev_reroll_parser.add_argument(
        "--yes", action="store_true", help="skip the interactive confirmation"
    )
    dev_reroll_parser.set_defaults(func=_cmd_dev_reroll)

    dev_animate_parser = dev_subparsers.add_parser(
        "animate",
        help="play every animation on demand, at the current motion level (SYZYGY_DEV only)",
    )
    dev_animate_parser.set_defaults(func=_cmd_dev_animate)

    dev_evaluate_parser = dev_subparsers.add_parser(
        "evaluate-local",
        help="run the maintainer evaluation harness against a running model (M16.3b)",
    )
    dev_evaluate_parser.add_argument("--base-url", required=True, help="e.g. http://127.0.0.1:8080/v1")
    dev_evaluate_parser.add_argument("--model", required=True, help="the id the server serves")
    dev_evaluate_parser.add_argument("--artifact", required=True, help="catalog artifact id")
    dev_evaluate_parser.add_argument("--runtime-version", default="unknown")
    dev_evaluate_parser.add_argument(
        "--hardware", required=True, help='e.g. "MacBook Pro M2, 16 GB, Metal"'
    )
    dev_evaluate_parser.add_argument(
        "--peak-memory-bytes", type=int, default=None, help="measured externally"
    )
    dev_evaluate_parser.add_argument(
        "--license-reviewed", action="store_true", help="record that the licence review passed"
    )
    dev_evaluate_parser.add_argument("--out", default=None, help="write the results JSON here")
    dev_evaluate_parser.set_defaults(func=_cmd_dev_evaluate_local)

    profile_parser = subparsers.add_parser("profile", help="manage saved profiles")
    profile_subparsers = profile_parser.add_subparsers(dest="profile_command")

    profile_create_parser = profile_subparsers.add_parser(
        "create", help="save a new profile and calculate its natal chart"
    )
    profile_create_parser.add_argument("--display-name", required=True)
    _add_birth_data_args(profile_create_parser)
    profile_create_parser.set_defaults(func=_cmd_profile_create)

    profile_list_parser = profile_subparsers.add_parser("list", help="list saved profiles")
    profile_list_parser.set_defaults(func=_cmd_profile_list)

    profile_delete_parser = profile_subparsers.add_parser(
        "delete", help="delete a profile and all of its readings (irreversible)"
    )
    profile_delete_parser.add_argument("profile_id", help="id from `syzygy profile list`")
    profile_delete_parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the interactive confirmation (for non-interactive use)",
    )
    profile_delete_parser.set_defaults(func=_cmd_profile_delete)

    chart_parser = subparsers.add_parser("chart", help="print a saved profile's natal chart")
    chart_parser.add_argument(
        "--profile-id", default=None, help="required if more than one profile is saved"
    )
    chart_parser.set_defaults(func=_cmd_chart)

    knowledge_parser = subparsers.add_parser(
        "knowledge", help="ingest and inspect knowledge sources"
    )
    knowledge_subparsers = knowledge_parser.add_subparsers(dest="knowledge_command")

    knowledge_ingest_parser = knowledge_subparsers.add_parser(
        "ingest", help="ingest a Book of Thoth / companion-source PDF"
    )
    knowledge_ingest_parser.add_argument("pdf_path", help="path to the source PDF")
    knowledge_ingest_parser.add_argument(
        "--source-type",
        default=None,
        choices=("book_of_thoth", "duquette_companion", "ziegler_mirror_of_soul"),
        help="override auto-detection from the filename",
    )
    knowledge_ingest_parser.set_defaults(func=_cmd_knowledge_ingest)

    knowledge_status_parser = knowledge_subparsers.add_parser(
        "status", help="show what has been ingested"
    )
    knowledge_status_parser.set_defaults(func=_cmd_knowledge_status)

    knowledge_search_parser = knowledge_subparsers.add_parser(
        "search", help="vector search over the knowledge index"
    )
    knowledge_search_parser.add_argument("query", help="free text")
    knowledge_search_parser.add_argument("--limit", type=int, default=10)
    knowledge_search_parser.set_defaults(func=_cmd_knowledge_search)

    knowledge_build_parser = knowledge_subparsers.add_parser(
        "build-artifact",
        help="regenerate the committed citations+vectors index from an ingested database",
    )
    knowledge_build_parser.add_argument(
        "--output",
        default="src/syzygy/resources/knowledge",
        help="directory to write index.json and vectors.npy into",
    )
    knowledge_build_parser.add_argument(
        "--database", default=None, help="ingested database to read (default: the app's own)"
    )
    knowledge_build_parser.set_defaults(func=_cmd_knowledge_build_artifact)

    model_parser = subparsers.add_parser(
        "model", help="inspect and configure interpretation providers"
    )
    model_subparsers = model_parser.add_subparsers(dest="model_command")

    model_status_parser = model_subparsers.add_parser(
        "status", help="show which providers are configured"
    )
    model_status_parser.set_defaults(func=_cmd_model_status)

    model_configure_parser = model_subparsers.add_parser(
        "configure", help="store or remove a hosted provider's API key"
    )
    model_configure_parser.add_argument("provider", choices=_HOSTED_PROVIDERS)
    model_configure_parser.add_argument(
        "--delete", action="store_true", help="remove the stored key instead of setting one"
    )
    model_configure_parser.set_defaults(func=_cmd_model_configure)

    model_use_parser = model_subparsers.add_parser(
        "use", help="select which provider readings use"
    )
    model_use_parser.add_argument("provider", choices=_PROVIDER_IDS)
    model_use_parser.add_argument(
        "--model", default=None, help="model id (required for openai/anthropic)"
    )
    model_use_parser.add_argument(
        "--base-url", default=None, help="override the provider's default endpoint"
    )
    model_use_parser.set_defaults(func=_cmd_model_use)

    setup_local_parser = model_subparsers.add_parser(
        "setup-local",
        help="set up a local model, with the same steps as the interface (M16.10a)",
    )
    setup_local_parser.add_argument(
        "--tier",
        choices=("faster", "recommended", "higher_quality"),
        default=None,
        help="pick a tier instead of the recommendation",
    )
    setup_local_parser.add_argument(
        "--yes",
        action="store_true",
        help="accept the plan and the model licence without prompting",
    )
    setup_local_parser.set_defaults(func=_cmd_model_setup_local)

    local_parser = model_subparsers.add_parser(
        "local", help="inspect and manage the local model Syzygy runs"
    )
    local_subparsers = local_parser.add_subparsers(dest="local_command")

    local_status_parser = local_subparsers.add_parser(
        "status", help="print the local model configuration (read-only)"
    )
    local_status_parser.set_defaults(func=_cmd_model_local_status)

    local_doctor_parser = local_subparsers.add_parser(
        "doctor", help="check the local model configuration (read-only)"
    )
    local_doctor_parser.add_argument(
        "--deep",
        action="store_true",
        help="re-hash the model file (minutes of I/O on a large model)",
    )
    local_doctor_parser.set_defaults(func=_cmd_model_local_doctor)

    local_start_parser = local_subparsers.add_parser(
        "start", help="start the configured local model server now"
    )
    local_start_parser.set_defaults(func=_cmd_model_local_start)

    local_stop_parser = local_subparsers.add_parser(
        "stop", help="stop the local model server Syzygy started"
    )
    local_stop_parser.set_defaults(func=_cmd_model_local_stop)

    local_list_parser = local_subparsers.add_parser(
        "list", help="list model files, managed and external"
    )
    local_list_parser.set_defaults(func=_cmd_model_local_list)

    local_use_file_parser = local_subparsers.add_parser(
        "use-file", help="use a .gguf model file you already have"
    )
    local_use_file_parser.add_argument("path", help="the exact .gguf file to use")
    local_use_file_parser.add_argument(
        "--yes", action="store_true", help="use it even if Syzygy thinks it won't fit"
    )
    local_use_file_parser.set_defaults(func=_cmd_model_local_use_file)

    local_remove_parser = local_subparsers.add_parser(
        "remove", help="delete a model file Syzygy downloaded"
    )
    local_remove_parser.add_argument("path", help="the exact file to remove")
    local_remove_parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the confirmation (only ever removes a Syzygy-owned file)",
    )
    local_remove_parser.set_defaults(func=_cmd_model_local_remove)

    doctor_parser = subparsers.add_parser("doctor", help="check the local environment")
    doctor_parser.set_defaults(func=_cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        if args.command is None:
            # `syzygy` with no arguments opens the application, per
            # docs/old/DESIGN.md section 20 - the TUI is the primary interface, not
            # a subcommand of a CLI.
            return _cmd_tui(args)
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
