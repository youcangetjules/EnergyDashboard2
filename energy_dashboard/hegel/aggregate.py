"""Pod totals. Unknown capacity is counted as unknown, not added as zero.

District statistics stay out of the rooftop sum.
"""
from __future__ import annotations

from dataclasses import dataclass

from energy_dashboard.hegel.models import Resource


@dataclass(frozen=True)
class CapacityTotals:
    installed_kwp: float | None
    installed_known: int
    installed_unknown: int
    storage_kwh: float | None
    storage_known: int
    storage_unknown: int
    statistical_installed_kwp: float | None
    statistical_known: int
    resource_count: int
    statistical_count: int


def aggregate(resources: list[Resource]) -> CapacityTotals:
    points = [r for r in resources if r.verification_status != "statistical"]
    stats = [r for r in resources if r.verification_status == "statistical"]
    installed, installed_known, installed_unknown = _sum_field(
        points, "installed_capacity_kwp", pv_only=True,
    )
    storage, storage_known, storage_unknown = _sum_field(
        points, "storage_capacity_kwh", storage_only=True,
    )
    statistical, statistical_known, _unknown = _sum_field(
        stats, "installed_capacity_kwp", pv_only=True,
    )
    return CapacityTotals(
        installed_kwp=installed,
        installed_known=installed_known,
        installed_unknown=installed_unknown,
        storage_kwh=storage,
        storage_known=storage_known,
        storage_unknown=storage_unknown,
        statistical_installed_kwp=statistical,
        statistical_known=statistical_known,
        resource_count=len(points),
        statistical_count=len(stats),
    )


def _sum_field(rows: list[Resource], field: str, *, pv_only: bool = False, storage_only: bool = False):
    chosen = []
    for row in rows:
        if pv_only and row.resource_type == "storage":
            continue
        if storage_only and row.resource_type != "storage":
            continue
        chosen.append(row)
    known = [getattr(row, field) for row in chosen if getattr(row, field) is not None]
    unknown = len(chosen) - len(known)
    if not known:
        return None, 0, unknown
    return float(sum(known)), len(known), unknown
