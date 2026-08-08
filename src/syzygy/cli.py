"""Syzygy command-line entry point.

The TUI (`syzygy.tui`, not yet implemented - see IMPLEMENTATION_PLAN.md
Milestone 5) is the primary interface, but every non-visual capability
should be reachable and scriptable from here too (DESIGN.md section 20).
This module only parses arguments and dispatches; it must not contain
domain logic itself.

Commands implemented in this architecture-session bootstrap:

- `syzygy dev deck` - enumerate the canonical 78-card deck (Milestone 1
  acceptance criterion).
- `syzygy dev astrology` - compute a natal chart and current transits for
  manually-supplied birth data (Milestone 2 acceptance criterion,
  DESIGN.md section 20). Takes birth data directly via flags rather than
  a saved profile - `syzygy profile create`/`syzygy chart` are Milestone 4
  (profile storage), not yet implemented.
- `syzygy doctor` - basic environment/health check.

Everything else in DESIGN.md section 20's command list is a later
milestone's job; add subcommands there as their underlying features land,
rather than stubbing them here with a "not implemented" message.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from syzygy import __version__
from syzygy.sortes.deck import DeckValidationError, load_deck


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

    print(
        f"Natal chart - {birth.place_label} "
        f"({birth.local_date} {birth.local_time} {birth.timezone})"
    )
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="syzygy", description=__doc__)
    parser.add_argument("--version", action="version", version=f"syzygy {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    dev_parser = subparsers.add_parser("dev", help="development/debug utilities")
    dev_subparsers = dev_parser.add_subparsers(dest="dev_command")
    dev_deck_parser = dev_subparsers.add_parser("deck", help="enumerate the canonical deck")
    dev_deck_parser.set_defaults(func=_cmd_dev_deck)

    dev_astrology_parser = dev_subparsers.add_parser(
        "astrology", help="compute a natal chart and current transits for manual birth data"
    )
    dev_astrology_parser.add_argument("--local-date", required=True, help="e.g. 1990-08-07")
    dev_astrology_parser.add_argument("--local-time", required=True, help="e.g. 14:22:00")
    dev_astrology_parser.add_argument("--place-label", default="")
    dev_astrology_parser.add_argument("--latitude", type=float, required=True)
    dev_astrology_parser.add_argument("--longitude", type=float, required=True)
    dev_astrology_parser.add_argument(
        "--timezone", required=True, help="IANA zone, e.g. America/New_York"
    )
    dev_astrology_parser.add_argument("--house-system", default="placidus")
    dev_astrology_parser.add_argument(
        "--at", default=None, help="ISO instant for transits (default: now, UTC)"
    )
    dev_astrology_parser.set_defaults(func=_cmd_dev_astrology)

    doctor_parser = subparsers.add_parser("doctor", help="check the local environment")
    doctor_parser.set_defaults(func=_cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
