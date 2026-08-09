"""The Self: a saved user profile and its natal chart."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from syzygy.domain.astrology import BirthData, NatalChart


class Profile(BaseModel):
    """A person Syzygy can read for. Multiple profiles are supported
    (docs/old/DESIGN.md section 3.1). The natal chart is calculated once and
    stored alongside the birth inputs that produced it - never
    recalculated silently on startup.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    birth_data: BirthData
    natal_chart: NatalChart
    created_at_utc: datetime
    updated_at_utc: datetime
