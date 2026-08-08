"""Syzygy command-line entry point.

The TUI (`syzygy.tui`) is the primary interface, but every non-visual
capability should be reachable and scriptable from here too (DESIGN.md
section 20). This module only parses arguments and dispatches; it must not
contain domain logic itself.

Commands implemented so far:

- `syzygy` (no arguments) or `syzygy tui` - launch the terminal interface
  (DESIGN.md section 20's first listed command).
- `syzygy dev deck` - enumerate the canonical 78-card deck (Milestone 1
  acceptance criterion).
- `syzygy dev astrology` - compute a natal chart and current transits for
  manually-supplied birth data (Milestone 2 acceptance criterion,
  DESIGN.md section 20). Takes birth data directly via flags rather than
  a saved profile - it does not touch storage at all.
- `syzygy profile create` / `syzygy profile list` - save/list profiles
  (Milestone 4). Storage lives at `syzygy.config.default_app_paths()`.
- `syzygy chart` - print a saved profile's natal chart.
- `syzygy knowledge ingest <pdf>` / `syzygy knowledge status` - ingest a
  Book of Thoth / companion-source PDF and inspect what has been ingested
  (Milestone 6). Source PDFs live outside the repository (`docs/*.pdf` is
  gitignored) - see docs/KNOWLEDGE_SOURCES.md.
- `syzygy doctor` - basic environment/health check.

Everything else in DESIGN.md section 20's command list is a later
milestone's job; add subcommands there as their underlying features land,
rather than stubbing them here with a "not implemented" message.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syzygy import __version__
from syzygy.sortes.deck import DeckValidationError, load_deck

if TYPE_CHECKING:
    import sqlite3

    from syzygy.domain.astrology import NatalChart


def _cmd_tui(_args: argparse.Namespace) -> int:
    from syzygy.tui.app import run

    run()
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
    from syzygy.knowledge.ingest import SOURCE_TYPES
    from syzygy.knowledge.store import count_chunks, get_source_by_type

    conn = _open_profile_db()
    try:
        for source_type in SOURCE_TYPES:
            source = get_source_by_type(conn, source_type)
            if source is None:
                print(f"{source_type:26s} not ingested")
                continue
            chunk_count = count_chunks(conn, source.id)
            print(
                f"{source_type:26s} {chunk_count:4d} chunks  "
                f"(version {source.ingestion_version}, hash {source.file_hash[:12]})"
            )
    finally:
        conn.close()
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

    return 0 if ok else 1


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

    doctor_parser = subparsers.add_parser("doctor", help="check the local environment")
    doctor_parser.set_defaults(func=_cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        if args.command is None:
            # `syzygy` with no arguments opens the application, per
            # DESIGN.md section 20 - the TUI is the primary interface, not
            # a subcommand of a CLI.
            return _cmd_tui(args)
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
