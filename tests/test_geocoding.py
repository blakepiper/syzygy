"""`syzygy.geocoding`: fakes only, no real network calls (M10.1e)."""

from __future__ import annotations

import sys

import pytest

from syzygy import geocoding


class _FakeLocation:
    def __init__(self, latitude: float, longitude: float) -> None:
        self.latitude = latitude
        self.longitude = longitude


class _FakeNominatim:
    def __init__(self, *, user_agent: str) -> None:
        self.user_agent = user_agent

    def geocode(self, place_label: str):
        if place_label == "Nowhereville":
            return None
        if place_label == "Unreachable":
            raise RuntimeError("connection refused")
        return _FakeLocation(38.8048, -77.0469)


class _FakeTimezoneFinder:
    def timezone_at(self, *, lat: float, lng: float):
        if (lat, lng) == (0.0, 0.0):
            return None
        return "America/New_York"


@pytest.fixture
def fake_geopy(monkeypatch):
    monkeypatch.setattr("geopy.geocoders.Nominatim", _FakeNominatim)
    monkeypatch.setattr("timezonefinder.TimezoneFinder", _FakeTimezoneFinder)


def test_resolve_birthplace_returns_coordinates_and_timezone(fake_geopy):
    resolved = geocoding.resolve_birthplace("Alexandria, Virginia, USA")
    assert resolved.latitude == 38.8048
    assert resolved.longitude == -77.0469
    assert resolved.timezone == "America/New_York"


def test_resolve_birthplace_raises_when_no_match(fake_geopy):
    with pytest.raises(geocoding.GeocodingFailed, match="no location found"):
        geocoding.resolve_birthplace("Nowhereville")


def test_resolve_birthplace_raises_on_service_failure(fake_geopy):
    with pytest.raises(geocoding.GeocodingFailed, match="could not reach"):
        geocoding.resolve_birthplace("Unreachable")


def test_resolve_birthplace_raises_when_extra_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "geopy", None)
    monkeypatch.setitem(sys.modules, "geopy.geocoders", None)
    with pytest.raises(geocoding.GeocodingUnavailable):
        geocoding.resolve_birthplace("Alexandria, Virginia, USA")
