"""Birthplace geocoding: a free-text place label -> coordinates + timezone.

Onboarding convenience only (docs/old/DESIGN.md section 6.1, AGENTS.md) - never
part of astrological calculation. `geopy` and `timezonefinder` ship in the
main install but remain lazy imports inside `resolve_birthplace`, so a
damaged dependency cannot prevent the rest of the application from starting.

The resolved timezone is always the **birthplace's** zone - the zone
needed to convert a local birth time to UTC for the natal chart - never a
current-location zone. Mirrors the "no current-location astrology"
invariant in AGENTS.md even though this module only ever looks at a place
the user typed, not wherever the app happens to be running.
"""

from __future__ import annotations

from dataclasses import dataclass


class GeocodingUnavailable(Exception):
    """A required geocoding runtime dependency is unavailable."""


class GeocodingFailed(Exception):
    """Resolution failed: no network, no geocoder match for the place
    label, or no timezone match for the resolved coordinates."""


@dataclass(frozen=True)
class ResolvedPlace:
    latitude: float
    longitude: float
    timezone: str


def resolve_birthplace(place_label: str) -> ResolvedPlace:
    """Resolve a free-text place label to `(latitude, longitude, timezone)`.

    Raises `GeocodingUnavailable` if a runtime dependency cannot be imported,
    or `GeocodingFailed` for any other resolution failure. Callers must
    treat both as non-fatal - manual latitude/longitude/timezone entry is
    always the fallback (docs/old/DESIGN.md section 6.1).
    """
    try:
        from geopy.geocoders import Nominatim
        from timezonefinder import TimezoneFinder
    except ImportError as exc:
        raise GeocodingUnavailable(
            "birthplace geocoding dependencies are unavailable; reinstall syzygy"
        ) from exc

    try:
        location = Nominatim(user_agent="syzygy-tui").geocode(place_label)
    except Exception as exc:  # geopy's service/network failures
        raise GeocodingFailed(f"could not reach the geocoding service ({exc})") from exc

    if location is None:
        raise GeocodingFailed(f"no location found for {place_label!r}")

    timezone = TimezoneFinder().timezone_at(lat=location.latitude, lng=location.longitude)
    if timezone is None:
        raise GeocodingFailed(
            f"resolved coordinates for {place_label!r} but found no timezone there"
        )

    return ResolvedPlace(
        latitude=location.latitude,
        longitude=location.longitude,
        timezone=timezone,
    )
