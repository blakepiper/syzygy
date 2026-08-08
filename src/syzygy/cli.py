"""Syzygy command-line entry point.

The TUI (`syzygy.tui`, not yet implemented - see IMPLEMENTATION_PLAN.md
Milestone 5) is the primary interface, but every non-visual capability
should be reachable and scriptable from here too (DESIGN.md section 20).
This module only parses arguments and dispatches; it must not contain
domain logic itself.

Commands implemented in this architecture-session bootstrap:

- `syzygy dev deck` - enumerate the canonical 78-card deck (Milestone 1
  acceptance criterion).
- `syzygy doctor` - basic environment/health check.

Everything else in DESIGN.md section 20's command list is a later
milestone's job; add subcommands there as their underlying features land,
rather than stubbing them here with a "not implemented" message.
"""

from __future__ import annotations

import argparse
import sys

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
