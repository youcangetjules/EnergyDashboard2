"""Link source rows that are the same site. Keep every source row's identity.

A postcode centroid is not a rooftop. A district total is not a rooftop.
A battery is not inferred from solar kilowatts.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace

from energy_dashboard.hegel.geo import coord_key, distance_m
from energy_dashboard.hegel.models import Observation, Resource, verification_rank

# Two site pins closer than this, of the same kind and similar size, are one site.
MATCH_METRES = 150.0
# 4 kW and 50 kW are not the same machine. Missing capacity is not a disagreement.
MAX_CAPACITY_RATIO = 4.0

_POINT_ACCURACY = frozenset({"site", "reported"})


def prepare_observations(rows: list[Observation]) -> list[Observation]:
    """When several 'reported' pins share one coordinate, call that a postcode centroid.

    A source that already said the pin is a surveyed site is left as a site.
    """
    counts: dict[tuple[float, float], int] = {}
    for row in rows:
        if row.latitude is None or row.longitude is None:
            continue
        if row.location_accuracy != "reported":
            continue
        key = coord_key(row.latitude, row.longitude)
        counts[key] = counts.get(key, 0) + 1
    shared = {key for key, n in counts.items() if n >= 2}
    prepared: list[Observation] = []
    for row in rows:
        if (
            row.latitude is not None
            and row.longitude is not None
            and row.location_accuracy == "reported"
            and coord_key(row.latitude, row.longitude) in shared
        ):
            prepared.append(replace(row, location_accuracy="postcode_centroid"))
        else:
            prepared.append(row)
    return prepared


def deduplicate(rows: list[Observation]) -> list[Resource]:
    """One resource per site. Statistical rows and postcode centroids stay separate."""
    rows = prepare_observations(rows)
    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if _can_link(rows[i], rows[j]):
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(len(rows)):
        groups.setdefault(find(i), []).append(i)

    resources: list[Resource] = []
    for indexes in groups.values():
        members = [rows[i] for i in indexes]
        resources.append(_resource_from(members))
    resources.sort(key=lambda r: r.resource_id)
    return resources


def _can_link(a: Observation, b: Observation) -> bool:
    if a.pod_id != b.pod_id:
        return False
    if a.verification_status == "statistical" or b.verification_status == "statistical":
        return False
    if a.resource_type != b.resource_type:
        return False
    if a.location_accuracy not in _POINT_ACCURACY or b.location_accuracy not in _POINT_ACCURACY:
        return False
    if None in (a.latitude, a.longitude, b.latitude, b.longitude):
        return False
    if distance_m(a.latitude, a.longitude, b.latitude, b.longitude) > MATCH_METRES:
        return False
    return _capacities_agree(a, b)


def _capacities_agree(a: Observation, b: Observation) -> bool:
    if a.resource_type == "storage":
        left, right = a.storage_capacity_kwh, b.storage_capacity_kwh
    else:
        left, right = a.installed_capacity_kwp, b.installed_capacity_kwp
    if left is None or right is None:
        return True
    if left == 0 or right == 0:
        return left == right
    ratio = max(left, right) / min(left, right)
    return ratio <= MAX_CAPACITY_RATIO


def _resource_from(members: list[Observation]) -> Resource:
    lead = min(
        members,
        key=lambda row: (
            verification_rank(row.verification_status),
            0 if _lead_capacity(row) is not None else 1,
            row.source,
            row.source_record_id,
        ),
    )
    keys = tuple(sorted({(row.source, row.source_record_id) for row in members}))
    return Resource(
        resource_id=_resource_id(lead, keys),
        pod_id=lead.pod_id,
        resource_type=lead.resource_type,
        location_accuracy=lead.location_accuracy,
        verification_status=lead.verification_status,
        latitude=lead.latitude,
        longitude=lead.longitude,
        installed_capacity_kwp=lead.installed_capacity_kwp,
        storage_capacity_kwh=lead.storage_capacity_kwh,
        equipment_metadata=dict(lead.equipment_metadata),
        confidence=lead.confidence,
        members=keys,
    )


def _lead_capacity(row: Observation) -> float | None:
    if row.resource_type == "storage":
        return row.storage_capacity_kwh
    return row.installed_capacity_kwp


def _resource_id(lead: Observation, keys: tuple[tuple[str, str], ...]) -> str:
    if len(keys) == 1:
        source, record_id = keys[0]
        return f"{source}:{record_id}"
    digest = hashlib.sha256(
        "\n".join(f"{source}\t{record_id}" for source, record_id in keys).encode("utf-8")
    ).hexdigest()[:16]
    return f"{lead.pod_id}:{digest}"
