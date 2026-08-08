"""Birthplace geocoding: a free-text place label -> coordinates + timezone.

Onboarding convenience only (DESIGN.md section 6.1, AGENTS.md) - never
part of astrological calculation, and the rest of the application must
keep working without the `geocoding` extra installed. `geopy` and
`timezonefinder` are therefore imported lazily inside `resolve_birthplace`,
never at module load.

The resolved timezone is always the **birthplace's** zone - the zone
needed to convert a local birth time to UTC for the natal chart - never a
current-location zone. Mirrors the "no current-location astrology"
invariant in AGENTS.md even though this module only ever looks at a place
the user typed, not wherever the app happens to be running.
"""

from __future__ import annotations

from dataclasses import dataclass


class GeocodingUnavailable(Exception):
    """The `geocoding` extra (`geopy`, `timezonefinder`) isn't installed."""


class GeocodingFailed(Exception):
    """The extra is installed, but resolution failed: no network, no
    geocoder match for the place label, or no timezone match for the
    resolved coordinates."""


@dataclass(frozen=True)
class ResolvedPlace:
    latitude: float
    longitude: float
    timezone: str


def resolve_birthplace(place_label: str) -> ResolvedPlace:
    """Resolve a free-text place label to `(latitude, longitude, timezone)`.

    Raises `GeocodingUnavailable` if the `geocoding` extra isn't installed,
    or `GeocodingFailed` for any other resolution failure. Callers must
    treat both as non-fatal - manual latitude/longitude/timezone entry is
    always the fallback (DESIGN.md section 6.1).
    """
    try:
        from geopy.geocoders import Nominatim
        from timezonefinder import TimezoneFinder
    except ImportError as exc:
        raise GeocodingUnavailable(
            "birthplace geocoding requires the 'geocoding' extra "
            '(pip install "syzygy[geocoding]")'
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
