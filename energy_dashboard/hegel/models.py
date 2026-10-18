"""Inventory records for one Hegel pod.

Missing numbers stay missing. A blank capacity is not zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Chinnor village centre, used as the circle's configured origin.
# OX39 names the postcode district. It is not a rooftop coordinate.
CHINNOR_LAT = 51.701
CHINNOR_LON = -0.901
CHINNOR_RADIUS_KM = 5.0
CHINNOR_POD_ID = "chinnor"
CHINNOR_LOCALITY = "OX39"

VERIFICATION_STATUSES = ("confirmed", "observed", "inferred", "statistical")
LOCATION_ACCURACIES = (
    "site",
    "reported",
    "postcode_centroid",
    "area",
    "unknown",
)
RESOURCE_TYPES = ("pv", "storage", "other")

_VERIFICATION_RANK = {name: i for i, name in enumerate(VERIFICATION_STATUSES)}


@dataclass(frozen=True)
class Pod:
    pod_id: str
    name: str
    centre_lat: float
    centre_lon: float
    radius_km: float
    locality_label: str = ""

    def __post_init__(self) -> None:
        if self.radius_km <= 0:
            raise ValueError("Pod radius must be greater than zero")
        if not (-90.0 <= self.centre_lat <= 90.0 and -180.0 <= self.centre_lon <= 180.0):
            raise ValueError("Pod centre is not a latitude and longitude")


def chinnor_pod() -> Pod:
    return Pod(
        pod_id=CHINNOR_POD_ID,
        name="Chinnor",
        centre_lat=CHINNOR_LAT,
        centre_lon=CHINNOR_LON,
        radius_km=CHINNOR_RADIUS_KM,
        locality_label=CHINNOR_LOCALITY,
    )


@dataclass
class Observation:
    """One row as a source published it, before deduplication."""

    source: str
    source_record_id: str
    resource_type: str
    location_accuracy: str
    verification_status: str
    latitude: float | None = None
    longitude: float | None = None
    installed_capacity_kwp: float | None = None
    storage_capacity_kwh: float | None = None
    equipment_metadata: dict = field(default_factory=dict)
    observation_timestamp: datetime | None = None
    confidence: float | None = None
    pod_id: str = CHINNOR_POD_ID

    def __post_init__(self) -> None:
        if self.resource_type not in RESOURCE_TYPES:
            raise ValueError(f"Unknown resource type: {self.resource_type}")
        if self.location_accuracy not in LOCATION_ACCURACIES:
            raise ValueError(f"Unknown location accuracy: {self.location_accuracy}")
        if self.verification_status not in VERIFICATION_STATUSES:
            raise ValueError(f"Unknown verification status: {self.verification_status}")
        if not self.source or not self.source_record_id:
            raise ValueError("A source row needs a source and a source record id")
        _check_optional_number(self.installed_capacity_kwp, "installed capacity")
        _check_optional_number(self.storage_capacity_kwh, "storage capacity")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("Confidence must be between 0 and 1, or left blank")


@dataclass
class Resource:
    """One physical resource after source rows that are the same site are linked."""

    resource_id: str
    pod_id: str
    resource_type: str
    location_accuracy: str
    verification_status: str
    latitude: float | None
    longitude: float | None
    installed_capacity_kwp: float | None
    storage_capacity_kwh: float | None
    equipment_metadata: dict
    confidence: float | None
    members: tuple[tuple[str, str], ...]


def _check_optional_number(value: float | None, label: str) -> None:
    if value is None:
        return
    if value < 0:
        raise ValueError(f"{label} cannot be negative")


def optional_float(value) -> float | None:
    """Blank, missing, and NaN stay None. A written zero stays zero."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"nan", "none", "null", "unknown", "n/a", "-"}:
            return None
        value = text
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def verification_rank(status: str) -> int:
    return _VERIFICATION_RANK.get(status, len(_VERIFICATION_RANK))
