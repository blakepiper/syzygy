"""Screens, one per step of the ritual (docs/old/DESIGN.md section 19).

Screens orchestrate; they do not calculate. Anything a screen shows comes
from `syzygy.storage`, `syzygy.astrology`, `syzygy.sortes`, or
`syzygy.interpretation` - never from arithmetic performed here.
"""
