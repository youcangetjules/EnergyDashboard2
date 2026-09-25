"""
Energy Dashboard — Roof layout tab (Physical Plant Tools group).

Define roof faces (tilt / azimuth / kWp), pick panel types, outline faces on
an embedded satellite map (or a Google Earth screenshot), then push a
multi-plane plant model into the Forecasts tab.
"""
from __future__ import annotations

import json
import math
import re
import threading
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from xml.etree import ElementTree as ET

from energy_dashboard.common import *
from energy_dashboard.plant.panel_catalog import list_panels, panel_by_id, panel_label

_SETTINGS_KEY = "forecasts/roof_layout"
_SETTINGS_IMAGE_KEY = "forecasts/roof_layout_image"
_SETTINGS_IMAGERY_KEY = "forecasts/roof_layout_imagery"

_COL_NAME, _COL_STRING, _COL_TILT, _COL_AZ, _COL_PANEL, _COL_COUNT, _COL_KWP, _COL_ON, _COL_VIZ = range(9)

# Stack pages: live satellite map vs GE screenshot canvas.
_PAGE_MAP, _PAGE_IMAGE = 0, 1


def _panel_by_id(pid: str) -> dict:
    return panel_by_id(pid)


def _new_plane(name: str = "South roof") -> dict:
    pan = panel_by_id("gen_400")
    count = 8
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "tilt": 35.0,
        "azimuth": 0.0,  # degrees 0…359; 0 = south, 90 = west, 180 = north, 270 = east
        "panel_type": pan["id"],
        "panel_count": count,
        "kwp": round(count * pan["wp"] / 1000.0, 3),
        "pv_string": 1,  # inverter MPPT / DC string number (1, 2, …)
        "enabled": True,
        "viz": True,  # show geo_ring / KML outline on the map
        "polygon": [],  # [x, y] scene coords on GE screenshot
        "geo_ring": [],  # [[lon, lat], ...] on satellite map / KML
        # Orientation: top → bottom defines facing azimuth
        "top_edge": [],
        "bottom_edge": [],
    }


_TILE_UA = {
    "User-Agent": "PowerModel-EnergyDashboard/2.9 (roof clearest-image scan)",
}
_WAYBACK_CATALOG = (
    "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
    "World_Imagery/MapServer?f=pjson"
)


def _latlon_to_tile(lat: float, lon: float, z: int) -> tuple[int, int]:
    n = 2.0 ** int(z)
    x = int((float(lon) + 180.0) / 360.0 * n)
    lat_r = math.radians(float(lat))
    y = int(
        (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi)
        / 2.0 * n
    )
    n_i = int(n)
    return x % n_i, max(0, min(n_i - 1, y))


def _sharpness_from_bytes(data: bytes) -> float:
    """Laplacian variance of a greyscale tile (higher = clearer edges)."""
    if not data or len(data) < 200:
        return 0.0
    from PySide6.QtGui import QImage

    img = QImage()
    if not img.loadFromData(data):
        return 0.0
    img = img.convertToFormat(QImage.Format.Format_Grayscale8)
    w, h = img.width(), img.height()
    if w < 8 or h < 8:
        return 0.0
    bpl = img.bytesPerLine()
    buf = bytes(img.constBits())
    g = np.frombuffer(buf, dtype=np.uint8).reshape((h, bpl))[:, :w].astype(np.float32)
    if float(g.std()) < 4.0:
        return 0.0
    c = g[1:-1, 1:-1]
    lap = (
        -4.0 * c
        + g[:-2, 1:-1] + g[2:, 1:-1]
        + g[1:-1, :-2] + g[1:-1, 2:]
    )
    score = float(np.var(lap))
    mean = float(g.mean())
    if mean > 230:  # washed-out / cloud
        score *= 0.12
    elif mean < 10:  # almost black / missing
        score *= 0.12
    return score


def _tile_url(kind: str, z: int, x: int, y: int, *, m: str = "", year: str = "") -> str:
    if kind == "esri_live":
        return (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            f"World_Imagery/MapServer/tile/{z}/{y}/{x}"
        )
    if kind == "google":
        return f"https://mt0.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
    if kind == "google_hyb":
        return f"https://mt0.google.com/vt/lyrs=y&x={x}&y={y}&z={z}"
    if kind == "wayback":
        return (
            "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
            f"World_Imagery/WMTS/1.0.0/default028mm/MapServer/tile/{m}/{z}/{y}/{x}"
        )
    if kind.startswith("s2_") or year:
        yr = year or kind.replace("s2_", "")
        return (
            "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-"
            f"{yr}_3857/default/GoogleMapsCompatible/{z}/{y}/{x}.jpg"
        )
    return ""


def _fetch_tile_score(url: str) -> float:
    try:
        r = requests.get(url, timeout=8, headers=_TILE_UA)
        if r.status_code != 200 or not r.content:
            return 0.0
        return _sharpness_from_bytes(r.content)
    except Exception:
        return 0.0


def _candidate_score(kind: str, lat: float, lon: float, z: int, **kw) -> float:
    native = {
        "esri_live": 19, "wayback": 19, "google": 21, "google_hyb": 21,
        "s2_2024": 16, "s2_2021": 16, "s2_2018": 16,
    }
    zz = min(int(z), native.get(kind, 19))
    x0, y0 = _latlon_to_tile(lat, lon, zz)
    scores = []
    for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        url = _tile_url(kind, zz, x0 + dx, y0 + dy, **kw)
        if not url:
            continue
        scores.append(_fetch_tile_score(url))
    good = [s for s in scores if s > 0]
    return float(sum(good) / len(good)) if good else 0.0


def _wayback_catalog() -> list[dict]:
    """Newest-first [{date, m}] from Esri Wayback Selection."""
    try:
        r = requests.get(_WAYBACK_CATALOG, timeout=20, headers=_TILE_UA)
        data = r.json()
    except Exception:
        return []
    out = []
    for s in data.get("Selection") or []:
        m = s.get("M")
        if not m:
            continue
        name = s.get("Name") or ""
        match = re.search(r"Wayback\s+(\d{4}-\d{2}-\d{2})", name)
        date = match.group(1) if match else "unknown"
        out.append({"date": date, "m": str(m)})
    return out


def _sample_wayback(releases: list[dict], *, cap: int = 22) -> list[dict]:
    """One (sometimes two) snapshots per year so the scan stays quick."""
    by_year: dict[str, list[dict]] = {}
    for rel in releases:
        by_year.setdefault((rel.get("date") or "0000")[:4], []).append(rel)
    picked: list[dict] = []
    seen: set[str] = set()
    for year in sorted(by_year.keys(), reverse=True):
        lst = by_year[year]
        for rel in (lst[0], lst[len(lst) // 2] if len(lst) >= 4 else None):
            if not rel or rel["m"] in seen:
                continue
            seen.add(rel["m"])
            picked.append(rel)
            if len(picked) >= cap:
                return picked
    return picked


def _scan_clearest_imagery(lat: float, lon: float, zoom: int) -> dict | None:
    """Return the sharpest {key, m, label, score} at this roof location."""
    z = max(16, min(int(zoom or 20), 21))
    jobs: list[tuple] = []
    jobs.append(("esri_live", "Esri Live (current mosaic)", "", None))
    jobs.append(("google", "Google Satellite (current)", "", None))
    jobs.append(("google_hyb", "Google Hybrid (current)", "", None))
    for yr in ("2024", "2021", "2018"):
        jobs.append((f"s2_{yr}", f"Sentinel-2 cloudless {yr}", "", yr))
    for rel in _sample_wayback(_wayback_catalog()):
        jobs.append((
            "wayback",
            f"Esri Wayback {rel['date']}",
            rel["m"],
            None,
        ))

    best = None
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {}
        for kind, label, m, year in jobs:
            kw = {}
            if m:
                kw["m"] = m
            if year:
                kw["year"] = year
            futs[pool.submit(_candidate_score, kind, lat, lon, z, **kw)] = (
                kind, label, m,
            )
        for fut in as_completed(futs):
            kind, label, m = futs[fut]
            try:
                score = float(fut.result() or 0.0)
            except Exception:
                score = 0.0
            if score <= 0:
                continue
            if best is None or score > best["score"]:
                best = {
                    "key": kind,
                    "m": m or "",
                    "label": label,
                    "score": score,
                }
    return best


def _kwp_from_panels(panel_type: str, count: int) -> float:
    pan = _panel_by_id(panel_type)
    try:
        n = max(0, int(count))
    except (TypeError, ValueError):
        n = 0
    try:
        wp = float(pan.get("wp") or 0)
    except (TypeError, ValueError):
        wp = 0.0
    return round(n * wp / 1000.0, 3)


def _parse_kml_polygons(path: str) -> list[list[tuple[float, float]]]:
    """Return list of polygons as [(lon, lat), ...] from a KML/KMZ-ish XML file."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    text = text.replace("xmlns=", "xmlns_omit=")
    root = ET.fromstring(text)
    polys: list[list[tuple[float, float]]] = []
    for coords_el in root.iter():
        if not str(coords_el.tag).endswith("coordinates"):
            continue
        raw = (coords_el.text or "").strip()
        if not raw:
            continue
        ring: list[tuple[float, float]] = []
        for token in raw.replace("\n", " ").split():
            parts = token.split(",")
            if len(parts) < 2:
                continue
            try:
                lon, lat = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            ring.append((lon, lat))
        if len(ring) >= 3:
            polys.append(ring)
    return polys


def _bearing_deg(lon1, lat1, lon2, lat2) -> float:
    """Initial compass bearing degrees (0=N, 90=E) between two WGS84 points."""
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δλ = math.radians(lon2 - lon1)
    y = math.sin(Δλ) * math.cos(φ2)
    x = math.cos(φ1) * math.sin(φ2) - math.sin(φ1) * math.cos(φ2) * math.cos(Δλ)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _norm_az_0_359(az: float) -> float:
    """Clamp azimuth to [0, 359.9…] — UI uses degrees 0…359 only (0 = south)."""
    try:
        a = float(az)
    except (TypeError, ValueError):
        a = 0.0
    a = a % 360.0
    if a < 0:
        a += 360.0
    if a >= 360.0:
        a = 0.0
    return round(a, 1)


def _ui_az_to_forecast_solar(az: float) -> float:
    """UI 0…359 (0=south, 90=west, 180=north, 270=east) → Forecast.Solar ±180."""
    a = _norm_az_0_359(az)
    if a > 180.0:
        return round(a - 360.0, 1)
    return a


def _forecast_solar_to_ui_az(az: float) -> float:
    """Forecast.Solar ±180 → UI 0…359."""
    try:
        a = float(az)
    except (TypeError, ValueError):
        a = 0.0
    if a < 0:
        a += 360.0
    return _norm_az_0_359(a)


def _forecast_az_to_compass(az: float) -> float:
    """UI / facing azimuth (0=south) → compass bearing (0=N, 90=E)."""
    return _norm_az_0_359(float(az) + 180.0)


def _offset_lonlat(lon: float, lat: float, bearing_deg: float, dist_m: float) -> tuple[float, float]:
    br = math.radians(bearing_deg)
    dlat = (dist_m * math.cos(br)) / 110540.0
    cos_lat = math.cos(math.radians(lat))
    dlon = (dist_m * math.sin(br)) / (111320.0 * max(abs(cos_lat), 1e-6))
    return lon + dlon, lat + dlat


def _lonlat_to_local_m(lon, lat, lon0, lat0) -> tuple[float, float]:
    x = (lon - lon0) * 111320.0 * math.cos(math.radians(lat0))
    y = (lat - lat0) * 110540.0
    return x, y


def _azimuth_guide_for_plane(plane: dict, extend_m: float = 10.0) -> dict | None:
    """Dashed azimuth guide: line along facing dir, ±extend_m past outline vertices.

    Returns ``{top:[lon,lat], bottom:[lon,lat], tilt, azimuth}`` or None.
    """
    ring = _normalize_geo_ring(plane.get("geo_ring") or [])
    top_e = _normalize_edge(_plane_top_edge(plane))
    bot_e = _normalize_edge(_plane_bottom_edge(plane))
    try:
        az = _norm_az_0_359(plane.get("azimuth") or 0)
        tilt = float(plane.get("tilt") or 0)
    except (TypeError, ValueError):
        az, tilt = 0.0, 0.0

    pts: list[list[float]] = []
    if len(ring) >= 2:
        pts = ring
    elif top_e and bot_e:
        pts = top_e + bot_e
    else:
        return None

    lon0 = sum(p[0] for p in pts) / len(pts)
    lat0 = sum(p[1] for p in pts) / len(pts)
    bearing = _forecast_az_to_compass(az)
    br = math.radians(bearing)
    ux, uy = math.sin(br), math.cos(br)

    projs = []
    for lon, lat in pts:
        x, y = _lonlat_to_local_m(lon, lat, lon0, lat0)
        projs.append(x * ux + y * uy)
    pmin, pmax = min(projs), max(projs)
    p_top = pmin - float(extend_m)
    p_bot = pmax + float(extend_m)
    top_lon, top_lat = _offset_lonlat(lon0, lat0, bearing, p_top)
    bot_lon, bot_lat = _offset_lonlat(lon0, lat0, bearing, p_bot)
    return {
        "top": [top_lon, top_lat],
        "bottom": [bot_lon, bot_lat],
        "tilt": round(tilt, 1),
        "azimuth": az,
    }


def _compass_to_forecast_azimuth(bearing_n: float) -> float:
    """Compass bearing (0=N) → UI azimuth 0…359 (0=south)."""
    return _norm_az_0_359(float(bearing_n) - 180.0)


def _flip_forecast_azimuth(az: float) -> float:
    """Reverse facing: +180°, stay in 0…359."""
    return _norm_az_0_359(float(az) + 180.0)


def _normalize_edge(edge) -> list[list[float]]:
    """Return [[lon,lat],[lon,lat]] or []."""
    pts = _normalize_geo_ring(edge)
    if len(pts) < 2:
        return []
    return [pts[0], pts[1]]


def _azimuth_from_top_bottom_edges(top_edge, bottom_edge) -> float | None:
    """Facing azimuth from top edge → bottom edge (downslope).

    UI degrees 0…359: 0 = south, 90 = west, 180 = north, 270 = east.
    """
    top = _normalize_edge(top_edge)
    bottom = _normalize_edge(bottom_edge)
    if len(top) < 2 or len(bottom) < 2:
        return None
    t_mid = ((top[0][0] + top[1][0]) / 2.0, (top[0][1] + top[1][1]) / 2.0)
    b_mid = ((bottom[0][0] + bottom[1][0]) / 2.0, (bottom[0][1] + bottom[1][1]) / 2.0)
    bearing = _bearing_deg(t_mid[0], t_mid[1], b_mid[0], b_mid[1])
    mid_lat = (t_mid[1] + b_mid[1]) / 2.0
    dx = (b_mid[0] - t_mid[0]) * 111_320.0 * math.cos(math.radians(mid_lat))
    dy = (b_mid[1] - t_mid[1]) * 110_540.0
    if math.hypot(dx, dy) < 0.3:
        eb = _bearing_deg(top[0][0], top[0][1], top[1][0], top[1][1])
        cand = (eb + 90.0) % 360.0
        tlon = t_mid[0] + 0.0001 * math.sin(math.radians(cand))
        tlat = t_mid[1] + 0.0001 * math.cos(math.radians(cand))
        d1 = (tlon - b_mid[0]) ** 2 + (tlat - b_mid[1]) ** 2
        cand2 = (eb - 90.0) % 360.0
        tlon2 = t_mid[0] + 0.0001 * math.sin(math.radians(cand2))
        tlat2 = t_mid[1] + 0.0001 * math.cos(math.radians(cand2))
        d2 = (tlon2 - b_mid[0]) ** 2 + (tlat2 - b_mid[1]) ** 2
        bearing = cand if d1 <= d2 else cand2
    return _compass_to_forecast_azimuth(bearing)


# Back-compat alias
_azimuth_from_high_low_edges = _azimuth_from_top_bottom_edges


def _plane_top_edge(plane: dict) -> list:
    return plane.get("top_edge") or plane.get("high_edge") or []


def _plane_bottom_edge(plane: dict) -> list:
    return plane.get("bottom_edge") or plane.get("low_edge") or []


def _longest_edge_facing_azimuth(ring: list[tuple[float, float]]) -> float | None:
    """Suggest plane azimuth from the longest polygon edge (outward ≈ perpendicular)."""
    if len(ring) < 2:
        return None
    best_len = -1.0
    best_bearing = None
    n = len(ring)
    pts = ring[:-1] if ring[0] == ring[-1] and n > 3 else ring
    for i in range(len(pts)):
        lon1, lat1 = pts[i]
        lon2, lat2 = pts[(i + 1) % len(pts)]
        mid_lat = (lat1 + lat2) / 2.0
        dx = (lon2 - lon1) * 111_320.0 * math.cos(math.radians(mid_lat))
        dy = (lat2 - lat1) * 110_540.0
        length = math.hypot(dx, dy)
        if length <= best_len:
            continue
        best_len = length
        edge_bearing = _bearing_deg(lon1, lat1, lon2, lat2)
        best_bearing = (edge_bearing + 90.0) % 360.0
    if best_bearing is None:
        return None
    return _compass_to_forecast_azimuth(best_bearing)


def _normalize_geo_ring(ring) -> list[list[float]]:
    out: list[list[float]] = []
    for p in ring or []:
        try:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                out.append([float(p[0]), float(p[1])])
        except (TypeError, ValueError):
            continue
    return out


class _RoofCanvas(QGraphicsView):
    """Background image + click-to-draw roof polygon for the selected plane."""

    polygonChanged = Signal()
    drawFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setBackgroundBrush(QColor("#11111b"))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._bg_item: QGraphicsPixmapItem | None = None
        self._poly_item: QGraphicsPolygonItem | None = None
        self._draw_mode = False
        self._points: list[QPointF] = []
        self._draft_item: QGraphicsPathItem | None = None

    def set_background_image(self, path: str | None):
        if self._bg_item is not None:
            self._scene.removeItem(self._bg_item)
            self._bg_item = None
        if not path or not Path(path).is_file():
            return
        pix = QPixmap(path)
        if pix.isNull():
            return
        self._bg_item = self._scene.addPixmap(pix)
        self._bg_item.setZValue(-10)
        self._scene.setSceneRect(QRectF(pix.rect()))
        self.fitInView(self._bg_item, Qt.AspectRatioMode.KeepAspectRatio)

    def set_draw_mode(self, on: bool):
        self._draw_mode = bool(on)
        self.setDragMode(
            QGraphicsView.DragMode.NoDrag if on else QGraphicsView.DragMode.ScrollHandDrag
        )
        self.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)

    def clear_polygon(self):
        self._points = []
        if self._poly_item is not None:
            self._scene.removeItem(self._poly_item)
            self._poly_item = None
        if self._draft_item is not None:
            self._scene.removeItem(self._draft_item)
            self._draft_item = None
        self.polygonChanged.emit()

    def set_polygon_points(self, pts: list):
        self._points = [QPointF(float(p[0]), float(p[1])) for p in (pts or [])]
        self._redraw_polygon()

    def polygon_points(self) -> list[list[float]]:
        return [[p.x(), p.y()] for p in self._points]

    def _redraw_polygon(self):
        if self._poly_item is not None:
            self._scene.removeItem(self._poly_item)
            self._poly_item = None
        if self._draft_item is not None:
            self._scene.removeItem(self._draft_item)
            self._draft_item = None
        if len(self._points) < 2:
            return
        poly = QPolygonF(self._points)
        pen = QPen(QColor("#89b4fa"), 2.0)
        brush = QBrush(QColor(137, 180, 250, 50))
        self._poly_item = self._scene.addPolygon(poly, pen, brush)
        self._poly_item.setZValue(5)

    def mousePressEvent(self, event):
        if self._draw_mode and event.button() == Qt.MouseButton.LeftButton:
            pt = self.mapToScene(event.position().toPoint())
            self._points.append(pt)
            self._redraw_polygon()
            self.polygonChanged.emit()
            event.accept()
            return
        if self._draw_mode and event.button() == Qt.MouseButton.RightButton:
            if self._points:
                self._points.pop()
                self._redraw_polygon()
                self.polygonChanged.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self._draw_mode and event.button() == Qt.MouseButton.LeftButton:
            self.set_draw_mode(False)
            self.drawFinished.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _SatelliteRoofMap(QWidget):
    """Embedded Leaflet + Esri World Imagery for outlining roof faces."""

    polygonChanged = Signal()
    drawFinished = Signal()
    edgePicked = Signal(str, object)  # kind 'top'|'bottom', [[lon,lat],[lon,lat]]

    _HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Roof satellite</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html, body, #map { margin:0; padding:0; height:100%; width:100%; background:#11111b; }
  .hint {
    position:absolute; left:8px; bottom:10px; z-index:1000;
    background:rgba(17,17,27,0.9); color:#cdd6f4;
    padding:4px 8px; border-radius:4px; font:11px/1.3 Helvetica,sans-serif;
    border:1px solid #45475a; max-width:42%;
  }
  .meta {
    position:absolute; left:50%; bottom:10px; z-index:900;
    transform:translateX(-50%);
    background:rgba(17,17,27,0.92); color:#cdd6f4;
    padding:6px 10px; border-radius:4px; font:11px/1.35 Helvetica,sans-serif;
    border:1px solid #45475a; max-width:48%; text-align:center;
    pointer-events:none;
  }
  .meta b { color: #f9e2af; }
  /* Leaflet attribution / scale sit on the same baseline as hint + meta. */
  .leaflet-bottom {
    bottom: 10px !important;
  }
  .leaflet-control-attribution {
    margin: 0 8px 0 0 !important;
    background: rgba(17,17,27,0.9) !important;
    color: #a6adc8 !important;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 2px 6px !important;
  }
  .az-tilt-label {
    background: transparent !important;
    border: none !important;
  }
  .az-tilt-label div {
    background: rgba(17,17,27,0.92);
    color: #f9e2af;
    border: 1px solid #f9e2af;
    border-radius: 4px;
    padding: 2px 8px;
    font: 11px/1.3 Helvetica,sans-serif;
    white-space: nowrap;
    text-align: center;
  }
  .ibar {
    position:absolute; left:52px; top:8px; right:8px; z-index:1000;
    display:flex; flex-wrap:wrap; gap:6px; align-items:center;
    background:rgba(17,17,27,0.94); color:#cdd6f4;
    padding:6px 8px; border-radius:6px; border:1px solid #45475a;
    font:11px/1.3 Helvetica,sans-serif;
  }
  .ibar label { display:flex; align-items:center; gap:4px; white-space:nowrap; }
  .ibar select, .ibar button {
    background:#313244; color:#cdd6f4; border:1px solid #585b70;
    border-radius:4px; padding:2px 6px; font:11px Helvetica,sans-serif;
  }
  .ibar button { cursor:pointer; min-width:28px; }
  .ibar button:disabled { opacity:0.4; cursor:default; }
  #wbBox { display:none; align-items:center; gap:4px; flex-wrap:wrap; }
  #wbBox.on { display:flex; }
</style>
</head>
<body>
  <div id="map"></div>
  <div class="ibar" id="ibar">
    <label>Imagery
      <select id="srcSel">
        <option value="esri_live" selected>Esri Live (current mosaic)</option>
        <option value="wayback">Esri Wayback (dated archive)</option>
        <option value="google">Google Satellite (current)</option>
        <option value="google_hyb">Google Hybrid (current)</option>
        <option value="s2_2024">Sentinel-2 cloudless 2024</option>
        <option value="s2_2021">Sentinel-2 cloudless 2021</option>
        <option value="s2_2018">Sentinel-2 cloudless 2018</option>
      </select>
    </label>
    <div id="wbBox">
      <label>Year <select id="wbYear"></select></label>
      <button id="wbPrev" title="Older release">◀</button>
      <label>Release <select id="wbRelease"></select></label>
      <button id="wbNext" title="Newer release">▶</button>
    </div>
  </div>
  <div id="meta" class="meta">Imagery date: …</div>
  <div id="hint" class="hint">Satellite view — pan/zoom; Draw outline to trace a roof face</div>
<script>
  var lat = __INIT_LAT__, lon = __INIT_LON__;
  var map = L.map('map', {
    zoomControl: true,
    doubleClickZoom: false,
    maxZoom: 22
  }).setView([lat, lon], 20);

  var esriImagery = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    { maxZoom: 22, maxNativeZoom: 19, attribution: 'Tiles &copy; Esri' }
  );
  var esriLabels = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
    { maxZoom: 22, maxNativeZoom: 19, opacity: 0.65 }
  );
  var googleSat = L.tileLayer(
    'https://mt{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
    { maxZoom: 22, maxNativeZoom: 21, subdomains: ['0','1','2','3'], attribution: '&copy; Google' }
  );
  var googleHybrid = L.tileLayer(
    'https://mt{s}.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
    { maxZoom: 22, maxNativeZoom: 21, subdomains: ['0','1','2','3'], attribution: '&copy; Google' }
  );
  var waybackLayer = L.tileLayer(
    'https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/MapServer/tile/32246/{z}/{y}/{x}',
    { maxZoom: 22, maxNativeZoom: 19, attribution: 'Esri World Imagery Wayback' }
  );
  function s2Layer(year) {
    return L.tileLayer(
      'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-' + year + '_3857/default/GoogleMapsCompatible/{z}/{y}/{x}.jpg',
      { maxZoom: 18, maxNativeZoom: 16, attribution: 'Sentinel-2 cloudless &copy; EOX / ESA' }
    );
  }
  var s2_2024 = s2Layer('2024');
  var s2_2021 = s2Layer('2021');
  var s2_2018 = s2Layer('2018');

  var layersByKey = {
    google: googleSat,
    google_hyb: googleHybrid,
    esri_live: L.layerGroup([esriImagery, esriLabels]),
    wayback: waybackLayer,
    s2_2024: s2_2024,
    s2_2021: s2_2021,
    s2_2018: s2_2018
  };
  /* Default Esri Live — Google tiles often stay blank in Qt WebEngine. */
  var activeBase = 'esri_live';
  var activeLayer = layersByKey.esri_live;
  activeLayer.addTo(map);
  var googleTileErrors = 0;

  function bindGoogleTileFallback(layer, key) {
    layer.on('tileerror', function() {
      if (activeBase !== key) return;
      googleTileErrors += 1;
      if (googleTileErrors < 3) return;
      googleTileErrors = 0;
      var sel = document.getElementById('srcSel');
      if (sel) sel.value = 'esri_live';
      setActiveLayer('esri_live');
      setHint('Google tiles failed in this view — switched to Esri Live');
    });
    layer.on('tileload', function() { googleTileErrors = 0; });
  }
  bindGoogleTileFallback(googleSat, 'google');
  bindGoogleTileFallback(googleHybrid, 'google_hyb');

  /* Wayback releases: newest → oldest [{date, m, id}] */
  var wbReleases = [];
  var wbByYear = {};
  var wbIdx = 0;

  function setActiveLayer(key) {
    if (activeLayer) map.removeLayer(activeLayer);
    activeBase = key;
    activeLayer = layersByKey[key] || layersByKey.esri_live;
    if (key === 'google' || key === 'google_hyb') googleTileErrors = 0;
    activeLayer.addTo(map);
    var wb = document.getElementById('wbBox');
    if (wb) {
      if (key === 'wayback') wb.classList.add('on');
      else wb.classList.remove('on');
    }
    scheduleImageryMeta();
  }

  function waybackUrl(m) {
    return 'https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/MapServer/tile/' +
      m + '/{z}/{y}/{x}';
  }

  function applyWaybackIndex(idx) {
    if (!wbReleases.length) return;
    wbIdx = Math.max(0, Math.min(wbReleases.length - 1, idx));
    var rel = wbReleases[wbIdx];
    waybackLayer.setUrl(waybackUrl(rel.m));
    var ySel = document.getElementById('wbYear');
    var rSel = document.getElementById('wbRelease');
    if (ySel) ySel.value = rel.date.slice(0, 4);
    fillReleaseSelect(rel.date.slice(0, 4), rel.m);
    document.getElementById('wbPrev').disabled = (wbIdx >= wbReleases.length - 1);
    document.getElementById('wbNext').disabled = (wbIdx <= 0);
    scheduleImageryMeta();
  }

  function fillReleaseSelect(year, selectM) {
    var rSel = document.getElementById('wbRelease');
    if (!rSel) return;
    var list = wbByYear[year] || [];
    rSel.innerHTML = '';
    list.forEach(function(rel) {
      var opt = document.createElement('option');
      opt.value = String(rel.m);
      opt.textContent = rel.date + (rel.id ? ' (' + rel.id + ')' : '');
      rSel.appendChild(opt);
    });
    if (selectM) rSel.value = String(selectM);
    else if (list.length) rSel.value = String(list[0].m);
  }

  function loadWaybackCatalog() {
    fetch('https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer?f=pjson')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var sel = data.Selection || [];
        wbReleases = [];
        wbByYear = {};
        sel.forEach(function(s) {
          var name = s.Name || '';
          var m = s.M;
          if (!m) return;
          var date = '';
          var parts = name.match(/Wayback\\s+(\\d{4}-\\d{2}-\\d{2})/);
          if (parts) date = parts[1];
          else date = 'unknown';
          var rel = { date: date, m: String(m), id: s.ID || '' };
          wbReleases.push(rel);
          var y = date.slice(0, 4);
          if (!wbByYear[y]) wbByYear[y] = [];
          wbByYear[y].push(rel);
        });
        var ySel = document.getElementById('wbYear');
        ySel.innerHTML = '';
        Object.keys(wbByYear).sort().reverse().forEach(function(y) {
          var opt = document.createElement('option');
          opt.value = y;
          opt.textContent = y + ' (' + wbByYear[y].length + ' releases)';
          ySel.appendChild(opt);
        });
        applyWaybackIndex(0);
      })
      .catch(function() {
        setMeta('Wayback catalog failed to load');
      });
  }

  document.getElementById('srcSel').addEventListener('change', function() {
    setActiveLayer(this.value);
  });
  document.getElementById('wbYear').addEventListener('change', function() {
    var list = wbByYear[this.value] || [];
    if (!list.length) return;
    /* Jump to newest release in that year (first in year list from Selection order). */
    var m = list[0].m;
    var idx = wbReleases.findIndex(function(r) { return r.m === m; });
    applyWaybackIndex(idx >= 0 ? idx : 0);
  });
  document.getElementById('wbRelease').addEventListener('change', function() {
    var m = this.value;
    var idx = wbReleases.findIndex(function(r) { return r.m === m; });
    applyWaybackIndex(idx >= 0 ? idx : wbIdx);
  });
  document.getElementById('wbPrev').addEventListener('click', function() {
    applyWaybackIndex(wbIdx + 1);  /* older */
  });
  document.getElementById('wbNext').addEventListener('click', function() {
    applyWaybackIndex(wbIdx - 1);  /* newer */
  });
  loadWaybackCatalog();

  window.applyImagery = function(key, waybackM) {
    var sel = document.getElementById('srcSel');
    if (sel) sel.value = key;
    setActiveLayer(key);
    if (key === 'wayback' && waybackM != null && String(waybackM) !== '') {
      var idx = wbReleases.findIndex(function(r) {
        return String(r.m) === String(waybackM);
      });
      if (idx >= 0) applyWaybackIndex(idx);
    }
  };
  window.getMapView = function() {
    var c = map.getCenter();
    return JSON.stringify({ lat: c.lat, lon: c.lng, z: map.getZoom() });
  };

  var drawMode = false;
  var pts = [];  // [{lat,lng}, ...]
  var layer = null;
  var markers = [];
  var vizLayerGroup = L.layerGroup().addTo(map);
  var VIZ_COLORS = ['#89b4fa', '#a6e3a1', '#f9e2af', '#cba6f7', '#fab387', '#94e2d5', '#f38ba8'];
  var _metaTimer = null;
  var _metaReq = 0;

  function setHint(t) {
    var el = document.getElementById('hint');
    if (el) el.innerText = t;
  }

  function setMeta(t) {
    var el = document.getElementById('meta');
    if (el) el.innerHTML = t;
  }

  function _attr(a, key, alias) {
    if (!a) return null;
    if (a[key] != null && a[key] !== 'Null' && a[key] !== '') return a[key];
    if (alias && a[alias] != null && a[alias] !== 'Null' && a[alias] !== '') return a[alias];
    return null;
  }

  function _fmtDate(yyyyMmDd, pretty) {
    var s = String(yyyyMmDd || '').replace(/\\D/g, '');
    if (s.length === 8) {
      var y = s.slice(0,4), m = parseInt(s.slice(4,6),10), d = parseInt(s.slice(6,8),10);
      var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      if (m >= 1 && m <= 12) return d + ' ' + months[m-1] + ' ' + y;
    }
    if (pretty && pretty !== 'Null') return String(pretty);
    return null;
  }

  function refreshImageryMeta() {
    var c = map.getCenter();
    var z = Math.round(map.getZoom());
    if (activeBase === 'google' || activeBase === 'google_hyb') {
      setMeta(
        'Imagery: <b>Google ' + (activeBase === 'google_hyb' ? 'Hybrid' : 'Satellite') + '</b> · current · z' + z +
        '<br><span style="color:#a6adc8">Scene date not in tiles — use Esri Live/Wayback for dated capture</span>'
      );
      return;
    }
    if (activeBase.indexOf('s2_') === 0) {
      var yr = activeBase.slice(3);
      setMeta(
        'Imagery: <b>Sentinel-2 cloudless ' + yr + '</b> · annual mosaic · z' + z +
        '<br><span style="color:#a6adc8">~10 m/pixel — good for timeline, not panel edges</span>'
      );
      return;
    }
    if (activeBase === 'wayback') {
      var rel = wbReleases[wbIdx];
      if (!rel) {
        setMeta('Imagery: <b>Esri Wayback</b> · loading catalog…');
        return;
      }
      setMeta(
        'Imagery: <b>Esri Wayback</b> · basemap as of <b>' + rel.date + '</b>' +
        (rel.id ? ' · ' + rel.id : '') + ' · z' + z +
        '<br><span style="color:#a6adc8">Archive snapshot date (local scene may be older)</span>'
      );
      return;
    }
    /* Esri Live — query citation metadata at map centre */
    var lon = c.lng, la = c.lat;
    var pad = Math.max(0.0003, 0.02 / Math.pow(2, Math.max(0, z - 12)));
    var req = ++_metaReq;
    setMeta('Imagery date: looking up…');
    var qs = new URLSearchParams({
      f: 'json',
      geometry: lon + ',' + la,
      geometryType: 'esriGeometryPoint',
      sr: '4326',
      layers: 'all:4',
      tolerance: '3',
      mapExtent: (lon-pad)+','+(la-pad)+','+(lon+pad)+','+(la+pad),
      imageDisplay: '800,600,96',
      returnGeometry: 'false'
    });
    fetch('https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/identify?' + qs.toString())
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (req !== _metaReq) return;
        var results = data.results || [];
        var best = null, fallback = null;
        var nativeHi = 19;
        for (var i = 0; i < results.length; i++) {
          var a = results[i].attributes || {};
          var lo = parseInt(_attr(a, 'MinMapLevel', 'FROM_CACHE_LEVEL') || '0', 10);
          var hi = parseInt(_attr(a, 'MaxMapLevel', 'TO_CACHE_LEVEL') || '23', 10);
          if (isNaN(lo)) lo = 0;
          if (isNaN(hi)) hi = 23;
          if (z >= lo && z <= hi) { best = a; nativeHi = hi; break; }
          fallback = a;
          if (hi > 0 && hi < 30) nativeHi = Math.max(nativeHi, hi);
        }
        try {
          esriImagery.options.maxNativeZoom = Math.min(19, Math.max(15, nativeHi));
          esriLabels.options.maxNativeZoom = esriImagery.options.maxNativeZoom;
        } catch (e1) {}
        var a2 = best || fallback;
        if (!a2) {
          setMeta('Imagery date: unavailable — try Google or Wayback');
          return;
        }
        var dateStr = _fmtDate(_attr(a2, 'SRC_DATE', 'DATE (YYYYMMDD)'), _attr(a2, 'SRC_DATE2', 'DATE'));
        var res = _attr(a2, 'SRC_RES', 'RESOLUTION (M)');
        var src = _attr(a2, 'NICE_DESC', 'SOURCE') || _attr(a2, 'NICE_NAME', 'SOURCE_INFO') || '';
        var desc = _attr(a2, 'SRC_DESC', 'DESCRIPTION') || '';
        var bits = [];
        bits.push('<b>' + (dateStr || 'date unknown') + '</b>');
        if (res != null && res !== '') bits.push(Number(res).toFixed(res < 1 ? 2 : 1) + ' m');
        if (src) bits.push(src);
        if (desc && desc !== src) bits.push(desc);
        bits.push('z' + z + (z > esriImagery.options.maxNativeZoom ? ' (overzoom)' : ''));
        setMeta('Imagery (Esri Live): ' + bits.join(' · '));
      })
      .catch(function() {
        if (req !== _metaReq) return;
        setMeta('Imagery date: lookup failed');
      });
  }

  function scheduleImageryMeta() {
    if (_metaTimer) clearTimeout(_metaTimer);
    _metaTimer = setTimeout(refreshImageryMeta, 450);
  }
  map.on('moveend', scheduleImageryMeta);
  map.on('zoomend', scheduleImageryMeta);
  setTimeout(refreshImageryMeta, 600);

  function redraw() {
    if (layer) { map.removeLayer(layer); layer = null; }
    markers.forEach(function(m) { map.removeLayer(m); });
    markers = [];
    if (pts.length === 0) return;
    pts.forEach(function(p) {
      markers.push(L.circleMarker([p.lat, p.lng], {
        radius: 4, color: '#89b4fa', fillColor: '#89b4fa', fillOpacity: 1, weight: 1,
        interactive: false
      }).addTo(map));
    });
    if (pts.length >= 2) {
      var latlngs = pts.map(function(p) { return [p.lat, p.lng]; });
      if (pts.length >= 3) {
        layer = L.polygon(latlngs, {
          color: '#89b4fa', weight: 2, fillColor: '#89b4fa', fillOpacity: 0.25,
          interactive: false
        }).addTo(map);
      } else {
        layer = L.polyline(latlngs, {
          color: '#89b4fa', weight: 2, interactive: false
        }).addTo(map);
      }
    }
  }

  function notifyChange() {
    document.title = 'POLYCHG ' + Date.now();
  }

  function finishDraw() {
    drawMode = false;
    map.dragging.enable();
    setHint('Outline saved — adjust tilt/panels, or Draw outline for another face');
    document.title = 'DRAWOFF ' + Date.now();
    notifyChange();
  }

  map.on('contextmenu', function(e) {
    if (edgeMode && edgeDraft.length) {
      L.DomEvent.preventDefault(e);
      edgeDraft.pop();
      redrawOrientation();
      return;
    }
    if (!drawMode) return;
    L.DomEvent.preventDefault(e);
    if (pts.length) { pts.pop(); redraw(); notifyChange(); }
  });
  map.on('dblclick', function(e) {
    if (!drawMode) return;
    L.DomEvent.stop(e);
    if (pts.length && pts.length < 3) {
      /* need at least a triangle */
    }
    finishDraw();
  });

  window.setCenter = function(la, lo, z) {
    map.setView([la, lo], z || Math.max(map.getZoom(), 18));
    scheduleImageryMeta();
  };
  window.setDrawMode = function(on) {
    drawMode = !!on;
    if (on) { edgeMode = null; edgeDraft = []; }
    if (drawMode) {
      map.dragging.disable();
      setHint('Click vertices · right-click undo · double-click finish');
    } else {
      map.dragging.enable();
      setHint('Satellite view — pan/zoom; Draw outline to trace a roof face');
    }
  };
  window.clearPolygon = function() {
    pts = [];
    redraw();
    notifyChange();
  };
  /* ring: [[lon,lat], ...] */
  window.setGeoRing = function(jsonStr) {
    pts = [];
    try {
      var ring = JSON.parse(jsonStr || '[]') || [];
      ring.forEach(function(p) {
        if (p && p.length >= 2) pts.push({ lat: +p[1], lng: +p[0] });
      });
    } catch (err) {}
    redraw();
    if (pts.length) {
      try { map.fitBounds(L.latLngBounds(pts.map(function(p){return [p.lat,p.lng];})).pad(0.3)); }
      catch (e2) {}
    }
  };
  window.getGeoRing = function() {
    return JSON.stringify(pts.map(function(p) { return [p.lng, p.lat]; }));
  };
  /* faces: [{name, ring:[[lon,lat],...]}, ...] — all Viz-checked outlines */
  window.setVizRings = function(jsonStr) {
    vizLayerGroup.clearLayers();
    var faces = [];
    try { faces = JSON.parse(jsonStr || '[]') || []; } catch (e0) { faces = []; }
    faces.forEach(function(f, i) {
      var ring = f.ring || [];
      if (ring.length < 3) return;
      var latlngs = [];
      for (var j = 0; j < ring.length; j++) {
        if (ring[j] && ring[j].length >= 2)
          latlngs.push([+ring[j][1], +ring[j][0]]);
      }
      if (latlngs.length < 3) return;
      var col = VIZ_COLORS[i % VIZ_COLORS.length];
      var poly = L.polygon(latlngs, {
        color: col, weight: 2, fillColor: col, fillOpacity: 0.2,
        /* Must stay non-interactive or edge/outline clicks never reach the map. */
        interactive: false
      });
      if (f.name) poly.bindTooltip(String(f.name), { sticky: true, interactive: false });
      vizLayerGroup.addLayer(poly);
    });
  };

  /* ── Top / bottom edge picking for azimuth (top → bottom) ───────── */
  var edgeMode = null;       // 'top' | 'bottom' | null
  var edgeDraft = [];        // [{lat,lng}, ...]
  var lastPickedEdge = null; // [[lon,lat],[lon,lat]]
  var topEdgeLL = null;
  var bottomEdgeLL = null;
  var topEdgeLayer = null;
  var bottomEdgeLayer = null;
  var edgeDraftLayer = null;
  var faceArrowLayer = null;

  function _clearLayer(refName) {
    if (refName === 'top' && topEdgeLayer) { map.removeLayer(topEdgeLayer); topEdgeLayer = null; }
    if (refName === 'bottom' && bottomEdgeLayer) { map.removeLayer(bottomEdgeLayer); bottomEdgeLayer = null; }
    if (refName === 'draft' && edgeDraftLayer) { map.removeLayer(edgeDraftLayer); edgeDraftLayer = null; }
    if (refName === 'arrow' && faceArrowLayer) { map.removeLayer(faceArrowLayer); faceArrowLayer = null; }
  }

  function redrawOrientation() {
    _clearLayer('top'); _clearLayer('bottom'); _clearLayer('draft'); _clearLayer('arrow');
    if (topEdgeLL && topEdgeLL.length >= 2) {
      topEdgeLayer = L.polyline(topEdgeLL, {
        color: '#f38ba8', weight: 5, opacity: 0.95, interactive: false
      }).addTo(map);
    }
    if (bottomEdgeLL && bottomEdgeLL.length >= 2) {
      bottomEdgeLayer = L.polyline(bottomEdgeLL, {
        color: '#94e2d5', weight: 5, opacity: 0.95, interactive: false
      }).addTo(map);
    }
    if (topEdgeLL && topEdgeLL.length >= 2 && bottomEdgeLL && bottomEdgeLL.length >= 2) {
      var hm = L.latLng(
        (topEdgeLL[0].lat + topEdgeLL[1].lat) / 2,
        (topEdgeLL[0].lng + topEdgeLL[1].lng) / 2
      );
      var lm = L.latLng(
        (bottomEdgeLL[0].lat + bottomEdgeLL[1].lat) / 2,
        (bottomEdgeLL[0].lng + bottomEdgeLL[1].lng) / 2
      );
      faceArrowLayer = L.layerGroup([
        L.polyline([hm, lm], {
          color: '#f9e2af', weight: 3, dashArray: '6 4', interactive: false
        }),
        L.circleMarker(lm, {
          radius: 5, color: '#f9e2af', fillColor: '#f9e2af', fillOpacity: 1,
          interactive: false
        })
      ]).addTo(map);
    }
    if (edgeDraft.length) {
      var draftItems = [
        L.polyline(edgeDraft, {
          color: '#cba6f7', weight: 3, dashArray: '4 4', interactive: false
        })
      ];
      edgeDraft.forEach(function(p) {
        draftItems.push(L.circleMarker(p, {
          radius: 4, color: '#cba6f7', fillOpacity: 1, interactive: false
        }));
      });
      edgeDraftLayer = L.layerGroup(draftItems).addTo(map);
    }
  }

  function finishEdgePick() {
    if (edgeDraft.length < 2 || !edgeMode) return;
    lastPickedEdge = [
      [edgeDraft[0].lng, edgeDraft[0].lat],
      [edgeDraft[1].lng, edgeDraft[1].lat]
    ];
    if (edgeMode === 'top') {
      topEdgeLL = [edgeDraft[0], edgeDraft[1]];
    } else {
      bottomEdgeLL = [edgeDraft[0], edgeDraft[1]];
    }
    var kind = edgeMode;
    edgeMode = null;
    edgeDraft = [];
    map.dragging.enable();
    map.getContainer().style.cursor = '';
    redrawOrientation();
    setHint('Edge saved — pick the other edge (azimuth = top → bottom)');
    document.title = 'EDGEPICK ' + kind + ' ' + Date.now() + ' ' + Math.random();
  }

  function _addEdgePoint(ll) {
    if (!edgeMode || !ll) return;
    edgeDraft.push(ll);
    redrawOrientation();
    if (edgeDraft.length >= 2) finishEdgePick();
    else setHint('Click the other end of the ' + (edgeMode === 'top' ? 'top' : 'bottom') + ' edge');
  }

  map.on('click', function(e) {
    if (drawMode) {
      pts.push({ lat: e.latlng.lat, lng: e.latlng.lng });
      redraw();
      notifyChange();
      return;
    }
    /* Edge pick is handled in capture-phase listener below. */
  });

  /* Capture-phase: works even when polygons/tiles would steal Leaflet clicks. */
  map.getContainer().addEventListener('click', function(domEvent) {
    if (!edgeMode || drawMode) return;
    if (domEvent.target && domEvent.target.closest) {
      if (domEvent.target.closest('.ibar, .meta, .hint, .leaflet-control, button, select, label'))
        return;
    }
    domEvent.preventDefault();
    domEvent.stopPropagation();
    var ll = map.mouseEventToLatLng(domEvent);
    _addEdgePoint(ll);
  }, true);

  window.setEdgePickMode = function(mode) {
    edgeMode = (mode === 'top' || mode === 'bottom') ? mode : null;
    edgeDraft = [];
    drawMode = false;
    if (edgeMode) {
      map.dragging.disable();
      map.boxZoom.disable();
      map.getContainer().style.cursor = 'crosshair';
      setHint('Click two ends of the ' + (edgeMode === 'top' ? 'TOP' : 'BOTTOM') + ' edge');
    } else {
      map.dragging.enable();
      try { map.boxZoom.enable(); } catch (e0) {}
      map.getContainer().style.cursor = '';
      setHint('Satellite view — pan/zoom; Draw outline to trace a roof face');
    }
    redrawOrientation();
  };
  window.getLastPickedEdge = function() {
    return JSON.stringify(lastPickedEdge || []);
  };
  window.setOrientationEdges = function(topJson, bottomJson) {
    topEdgeLL = null; bottomEdgeLL = null;
    try {
      var h = JSON.parse(topJson || '[]') || [];
      if (h.length >= 2) topEdgeLL = [{ lat: +h[0][1], lng: +h[0][0] }, { lat: +h[1][1], lng: +h[1][0] }];
    } catch (e1) {}
    try {
      var l = JSON.parse(bottomJson || '[]') || [];
      if (l.length >= 2) bottomEdgeLL = [{ lat: +l[0][1], lng: +l[0][0] }, { lat: +l[1][1], lng: +l[1][0] }];
    } catch (e2) {}
    redrawOrientation();
  };
  window.clearOrientationEdges = function() {
    topEdgeLL = null; bottomEdgeLL = null; edgeDraft = []; edgeMode = null;
    map.getContainer().style.cursor = '';
    redrawOrientation();
  };

  var azGuideLayer = null;
  window.setAzimuthGuide = function(jsonStr) {
    if (azGuideLayer) { map.removeLayer(azGuideLayer); azGuideLayer = null; }
    if (!jsonStr) return;
    var g = null;
    try { g = JSON.parse(jsonStr); } catch (e0) { return; }
    if (!g || !g.top || !g.bottom) return;
    var top = L.latLng(+g.top[1], +g.top[0]);
    var bot = L.latLng(+g.bottom[1], +g.bottom[0]);
    var line = L.polyline([top, bot], {
      color: '#f9e2af', weight: 3, dashArray: '10 6', interactive: false
    });
    var tip = L.circleMarker(bot, {
      radius: 5, color: '#f9e2af', fillColor: '#f9e2af', fillOpacity: 1,
      interactive: false
    });
    var tiltTxt = (g.tilt != null) ? Number(g.tilt).toFixed(1) : '?';
    var azTxt = (g.azimuth != null) ? Number(g.azimuth).toFixed(1) : '?';
    var label = L.marker(bot, {
      interactive: false,
      keyboard: false,
      icon: L.divIcon({
        className: 'az-tilt-label',
        html: '<div>tilt ' + tiltTxt + '° · az ' + azTxt + '°</div>',
        iconSize: [160, 22],
        iconAnchor: [80, -6]
      })
    });
    azGuideLayer = L.layerGroup([line, tip, label]).addTo(map);
  };
  window.clearAzimuthGuide = function() {
    if (azGuideLayer) { map.removeLayer(azGuideLayer); azGuideLayer = null; }
  };
</script>
</body>
</html>
"""

    def __init__(self, init_lat: float, init_lon: float, parent=None):
        super().__init__(parent)
        self._ring: list[list[float]] = []
        self._ready = False
        self._pending_ring: list | None = None
        self._pending_viz: list | None = None
        self._pending_center: tuple[float, float, int] | None = None
        self._pending_edge_mode: str | None = None
        self._pending_az_guide: dict | None = None
        self._pending_imagery: tuple | None = None
        self._draw_mode = False
        self._web = None
        self._init_lat = float(init_lat)
        self._init_lon = float(init_lon)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)

        try:
            from energy_dashboard.dialogs.map_picker import (
                _map_picker_webengine_available,
                _map_picker_webengine_enabled,
            )
            ok = _map_picker_webengine_enabled() and _map_picker_webengine_available()
        except Exception:
            ok = False
            try:
                import importlib.util
                ok = importlib.util.find_spec("PySide6.QtWebEngineWidgets") is not None
            except Exception:
                ok = False
        self._web_ok = bool(ok)

        if not ok:
            msg = QLabel(
                "Satellite map needs PySide6 WebEngine "
                "(pip install PySide6-WebEngine).\n"
                "Use Load GE image… for a screenshot instead."
            )
            msg.setWordWrap(True)
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setStyleSheet("color: #a6adc8; padding: 24px;")
            self._lay.addWidget(msg, 1)
        # Chromium is NOT started here. Constructing the QWebEngineView at
        # tab-build time kept a full browser process alive from app startup —
        # one segfaulted inside libQt6WebEngineCore after two idle days
        # (22 Aug). ensure_started() creates it on first actual view.

    def ensure_started(self):
        """Create the Chromium-backed map view on first show (lazy)."""
        if not self._web_ok or self._web is not None:
            return
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self._web = QWebEngineView()
        html = (
            self._HTML
            .replace("__INIT_LAT__", f"{self._init_lat:.6f}")
            .replace("__INIT_LON__", f"{self._init_lon:.6f}")
        )
        self._web.setHtml(html, QUrl("https://localhost/"))
        self._web.loadFinished.connect(self._on_load_finished)
        self._web.page().titleChanged.connect(self._on_title)
        self._lay.addWidget(self._web, 1)

    @property
    def available(self) -> bool:
        return self._web_ok

    def _on_load_finished(self, ok: bool):
        self._ready = bool(ok)
        if not self._ready:
            return
        if self._pending_center is not None:
            la, lo, z = self._pending_center
            self._pending_center = None
            self.set_center(la, lo, z)
        if self._pending_ring is not None:
            ring = self._pending_ring
            self._pending_ring = None
            self.set_geo_ring(ring)
        if self._pending_viz is not None:
            viz = self._pending_viz
            self._pending_viz = None
            self.set_viz_rings(viz)
        if self._pending_edge_mode:
            mode = self._pending_edge_mode
            self._pending_edge_mode = None
            self.set_edge_pick_mode(mode)
        if self._pending_az_guide is not None:
            g = self._pending_az_guide
            self._pending_az_guide = None
            self.set_azimuth_guide(g)
        if self._draw_mode:
            self.set_draw_mode(True)
        if self._pending_imagery is not None:
            key, m = self._pending_imagery
            self._pending_imagery = None
            self.apply_imagery(key, m)

    def _on_title(self, title: str):
        t = title or ""
        if t.startswith("DRAWOFF"):
            self._draw_mode = False
            self.drawFinished.emit()
            self._fetch_ring()
        elif t.startswith("POLYCHG"):
            self._fetch_ring()
        elif t.startswith("EDGEPICK"):
            parts = t.split()
            kind = parts[1] if len(parts) > 1 else ""
            if kind in ("top", "bottom", "high", "low") and self._web is not None:
                # Map legacy high/low titles if an old page is somehow still loaded
                kind_n = {"high": "top", "low": "bottom"}.get(kind, kind)
                self._web.page().runJavaScript(
                    "window.getLastPickedEdge();",
                    lambda result, k=kind_n: self._got_edge(k, result),
                )

    def _fetch_ring(self):
        if self._web is None or not self._ready:
            return
        self._web.page().runJavaScript("window.getGeoRing();", self._got_ring)

    def _got_ring(self, result):
        ring: list[list[float]] = []
        try:
            if isinstance(result, str):
                data = json.loads(result or "[]")
            elif isinstance(result, list):
                data = result
            else:
                data = []
            ring = _normalize_geo_ring(data)
        except (TypeError, ValueError, json.JSONDecodeError):
            ring = []
        self._ring = ring
        self.polygonChanged.emit()

    def _got_edge(self, kind: str, result):
        edge: list[list[float]] = []
        try:
            if isinstance(result, str):
                data = json.loads(result or "[]")
            elif isinstance(result, list):
                data = result
            else:
                data = []
            edge = _normalize_edge(data)
        except (TypeError, ValueError, json.JSONDecodeError):
            edge = []
        if edge:
            self.edgePicked.emit(kind, edge)

    def set_center(self, lat: float, lon: float, zoom: int = 20):
        if not self._web_ok:
            return
        if not self._ready:
            self._pending_center = (float(lat), float(lon), int(zoom))
            return
        self._web.page().runJavaScript(
            f"window.setCenter({float(lat)}, {float(lon)}, {int(zoom)});"
        )

    def apply_imagery(self, key: str, wayback_m: str | None = None):
        """Switch the Leaflet basemap (and Wayback release if given)."""
        if not self._web_ok:
            return
        k = str(key or "esri_live")
        m = str(wayback_m or "")
        if not self._ready:
            self._pending_imagery = (k, m)
            return
        self._pending_imagery = None
        self._web.page().runJavaScript(
            f"window.applyImagery({json.dumps(k)}, {json.dumps(m)});"
        )

    def get_map_view(self, callback):
        """callback(dict with lat, lon, z) — or empty dict if the map is not ready."""
        if not self._web_ok or not self._ready or self._web is None:
            callback({})
            return
        def _done(raw):
            try:
                callback(json.loads(raw) if isinstance(raw, str) else {})
            except (TypeError, json.JSONDecodeError):
                callback({})
        self._web.page().runJavaScript("window.getMapView();", _done)

    def set_draw_mode(self, on: bool):
        self._draw_mode = bool(on)
        if not self._web_ok:
            return
        if not self._ready:
            return
        self._web.page().runJavaScript(
            f"window.setDrawMode({str(bool(on)).lower()});"
        )

    def set_edge_pick_mode(self, mode: str | None):
        """mode: 'top', 'bottom', or None/'' to cancel."""
        if not self._web_ok:
            return
        m = mode if mode in ("top", "bottom") else ""
        if not self._ready:
            self._pending_edge_mode = m or None
            return
        self._pending_edge_mode = None
        self._web.page().runJavaScript(f"window.setEdgePickMode('{m}');")

    def set_orientation_edges(self, top_edge, bottom_edge):
        if not self._web_ok:
            return
        hj = json.dumps(_normalize_edge(top_edge))
        lj = json.dumps(_normalize_edge(bottom_edge))
        if not self._ready:
            return
        he = hj.replace("\\", "\\\\").replace("'", "\\'")
        le = lj.replace("\\", "\\\\").replace("'", "\\'")
        self._web.page().runJavaScript(
            f"window.setOrientationEdges('{he}', '{le}');"
        )

    def clear_orientation_edges(self):
        if self._web is None or not self._ready:
            return
        self._web.page().runJavaScript("window.clearOrientationEdges();")

    def set_azimuth_guide(self, guide: dict | None):
        """Show dashed facing line + tilt label at the bottom end."""
        if not self._web_ok:
            return
        if not self._ready:
            self._pending_az_guide = guide
            return
        if not guide:
            self._web.page().runJavaScript("window.clearAzimuthGuide();")
            return
        esc = json.dumps(guide).replace("\\", "\\\\").replace("'", "\\'")
        self._web.page().runJavaScript(f"window.setAzimuthGuide('{esc}');")

    def clear_azimuth_guide(self):
        self.set_azimuth_guide(None)

    def clear_polygon(self):
        self._ring = []
        if not self._web_ok:
            return
        if not self._ready:
            self._pending_ring = []
            return
        self._web.page().runJavaScript("window.clearPolygon();")

    def set_geo_ring(self, ring):
        ring = _normalize_geo_ring(ring)
        self._ring = ring
        if not self._web_ok:
            return
        payload = json.dumps(ring)
        if not self._ready:
            self._pending_ring = ring
            return
        # Escape for JS string literal
        esc = payload.replace("\\", "\\\\").replace("'", "\\'")
        self._web.page().runJavaScript(f"window.setGeoRing('{esc}');")

    def set_viz_rings(self, faces: list[dict]):
        """Overlay all Viz-checked face rings. ``faces``: name + ring [[lon,lat],...]."""
        if not self._web_ok:
            return
        payload = []
        for f in faces or []:
            ring = _normalize_geo_ring(f.get("ring") or [])
            if len(ring) < 3:
                continue
            payload.append({
                "name": f.get("name") or "",
                "ring": ring,
            })
        if not self._ready:
            self._pending_viz = payload
            return
        esc = json.dumps(payload).replace("\\", "\\\\").replace("'", "\\'")
        self._web.page().runJavaScript(f"window.setVizRings('{esc}');")

    def geo_ring(self) -> list[list[float]]:
        return list(self._ring)


class RoofLayoutTab(QWidget):
    """Roof faces + panel placement → multi-plane solar forecast inputs."""

    def __init__(self, forecasts_tab, status_callback, dash=None):
        super().__init__()
        self.forecasts_tab = forecasts_tab
        self.set_status = status_callback
        self.dash = dash
        self.on_data_updated = None
        self._planes: list[dict] = []
        self._image_path = ""
        self._suppress = False
        self._sharp_busy = False
        self._inv = Invoker(self)
        self.build_ui()
        self._load()
        QTimer.singleShot(0, self._center_map_on_forecasts)

    # ── UI ──────────────────────────────────────────────────────────────

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        hint = QLabel(
            "Trace each panel array as its own <b>roof face</b>. "
            "Use <b>Select top edge</b> / <b>Select bottom edge</b> to set facing "
            "(azimuth = top → bottom), then <b>Set tilt</b>. "
            "Multiple faces ⇒ multiple azimuths. Azimuth: <b>0…359°</b> "
            "(0 = south, 90 = west, 180 = north, 270 = east)."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        root.addWidget(hint)

        toolbar = QHBoxLayout()

        self.btn_sat = QPushButton("Satellite map")
        self.btn_sat.setToolTip("Show live aerial imagery at the Forecasts location.")
        self.btn_sat.clicked.connect(self._show_satellite)
        toolbar.addWidget(self.btn_sat)

        self.btn_center = QPushButton("Center on location")
        self.btn_center.setToolTip("Recenter the satellite map on Forecasts lat/lon.")
        self.btn_center.clicked.connect(self._center_map_on_forecasts)
        toolbar.addWidget(self.btn_center)

        self.btn_clearest = QPushButton("Use clearest image")
        self.btn_clearest.setToolTip(
            "Scan Google, Esri Live, Esri Wayback (dated archives), and Sentinel-2 "
            "at this roof and switch to the sharpest tile (clearest panel edges)."
        )
        self.btn_clearest.clicked.connect(self._use_clearest_image)
        toolbar.addWidget(self.btn_clearest)

        self.btn_load_image = QPushButton("Load GE image…")
        self.btn_load_image.setToolTip(
            "Load a Google Earth (or Maps) screenshot as an alternate canvas."
        )
        self.btn_load_image.clicked.connect(self._load_image)
        toolbar.addWidget(self.btn_load_image)

        self.btn_import_kml = QPushButton("Import KML…")
        self.btn_import_kml.setToolTip(
            "Import a polygon from Google Earth (File → Save → KML)."
        )
        self.btn_import_kml.clicked.connect(self._import_kml)
        toolbar.addWidget(self.btn_import_kml)

        self.btn_open_ge = QPushButton("Open Google Earth")
        self.btn_open_ge.setToolTip("Open Google Earth Web in your browser.")
        self.btn_open_ge.clicked.connect(self._open_google_earth)
        toolbar.addWidget(self.btn_open_ge)

        self.btn_draw = QPushButton("Draw outline")
        self.btn_draw.setCheckable(True)
        self.btn_draw.setToolTip(
            "Click to add polygon vertices. Right-click undoes. Double-click finishes."
        )
        self.btn_draw.toggled.connect(self._on_draw_toggled)
        toolbar.addWidget(self.btn_draw)

        self.btn_clear_outline = QPushButton("Clear outline")
        self.btn_clear_outline.clicked.connect(self._clear_outline)
        toolbar.addWidget(self.btn_clear_outline)

        toolbar.addStretch(1)

        self.btn_add_plane = QPushButton("Add roof face")
        self.btn_add_plane.clicked.connect(self._add_plane)
        toolbar.addWidget(self.btn_add_plane)

        self.btn_remove_plane = QPushButton("Remove face")
        self.btn_remove_plane.clicked.connect(self._remove_plane)
        toolbar.addWidget(self.btn_remove_plane)

        self.btn_save = QPushButton("Save")
        self.btn_save.clicked.connect(lambda: self._save(announce=True))
        toolbar.addWidget(self.btn_save)

        self.btn_apply = QPushButton("Apply to Forecasts")
        self.btn_apply.setToolTip(
            "Enable multi-plane fetch from these faces and refresh Forecasts. "
            "Each face keeps its own tilt/azimuth; Forecasts fields get total kWp."
        )
        self.btn_apply.clicked.connect(self._apply_to_forecasts)
        toolbar.addWidget(self.btn_apply)

        self.btn_single = QPushButton("Use single-plane")
        self.btn_single.setToolTip(
            "Stop multi-plane fetch; Forecasts will use its Lat/Lon/Tilt/Azimuth/kWp "
            "fields only (your roof faces stay saved)."
        )
        self.btn_single.clicked.connect(self._use_single_plane)
        toolbar.addWidget(self.btn_single)
        root.addLayout(toolbar)

        # Orientation: top → bottom edges define azimuth; tilt spin per face
        orient = QHBoxLayout()
        orient.addWidget(QLabel("Orientation:"))
        self.btn_top = QPushButton("Select top edge")
        self.btn_top.setCheckable(True)
        self.btn_top.setToolTip(
            "Top / ridge side of this roof face. Click two ends of the edge on the map. "
            "Azimuth is measured from the top edge pointing toward the bottom edge."
        )
        self.btn_top.toggled.connect(lambda on: self._on_edge_pick_toggled("top", on))
        orient.addWidget(self.btn_top)

        self.btn_bottom = QPushButton("Select bottom edge")
        self.btn_bottom.setCheckable(True)
        self.btn_bottom.setToolTip(
            "Bottom / eaves side of this roof face. Click two ends on the map."
        )
        self.btn_bottom.toggled.connect(lambda on: self._on_edge_pick_toggled("bottom", on))
        orient.addWidget(self.btn_bottom)

        orient.addWidget(QLabel("Tilt °"))
        self.tilt_spin = QDoubleSpinBox()
        self.tilt_spin.setRange(0.0, 90.0)
        self.tilt_spin.setDecimals(1)
        self.tilt_spin.setSingleStep(1.0)
        self.tilt_spin.setValue(35.0)
        self.tilt_spin.setFixedWidth(70)
        self.tilt_spin.setToolTip("Roof / panel tilt for the selected face (degrees from horizontal).")
        orient.addWidget(self.tilt_spin)

        self.btn_apply_tilt = QPushButton("Set tilt")
        self.btn_apply_tilt.setToolTip("Apply the tilt value to the selected roof face.")
        self.btn_apply_tilt.clicked.connect(self._apply_tilt_to_face)
        orient.addWidget(self.btn_apply_tilt)

        self.btn_flip_az = QPushButton("Flip azimuth")
        self.btn_flip_az.setToolTip(
            "Reverse facing of the selected face: add 180° (0…359). "
            "Also swaps top/bottom edge labels."
        )
        self.btn_flip_az.clicked.connect(self._flip_face_azimuth)
        orient.addWidget(self.btn_flip_az)

        self.btn_flip_all_az = QPushButton("Flip all")
        self.btn_flip_all_az.setToolTip(
            "Reverse facing on every enabled roof face (+180°). "
            "Use when KML/import got top↔bottom backwards (NE/NW shown instead of SE/SW)."
        )
        self.btn_flip_all_az.clicked.connect(self._flip_all_azimuths)
        orient.addWidget(self.btn_flip_all_az)

        self.btn_clear_orient = QPushButton("Clear edges")
        self.btn_clear_orient.clicked.connect(self._clear_face_edges)
        orient.addWidget(self.btn_clear_orient)

        orient.addStretch(1)
        self.orient_status = QLabel("Select a face, then top edge → bottom edge → set tilt.")
        self.orient_status.setStyleSheet("color: #a6adc8; font-size: 11px;")
        orient.addWidget(self.orient_status)
        root.addLayout(orient)

        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Face", "String", "Tilt °", "Azimuth °", "Panel", "Count", "kWp", "On", "Viz",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 9):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
        left_lay.addWidget(self.table, 1)

        self.summary = QLabel("No roof faces yet.")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color: #cdd6f4; font-size: 11px;")
        left_lay.addWidget(self.summary)
        split.addWidget(left)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        lat0, lon0 = self._forecast_latlon()
        self.view_stack = QStackedWidget()
        self.sat_map = _SatelliteRoofMap(lat0, lon0)
        self.sat_map.polygonChanged.connect(self._on_map_polygon_changed)
        self.sat_map.drawFinished.connect(self._on_draw_finished)
        self.sat_map.edgePicked.connect(self._on_edge_picked)
        self.view_stack.addWidget(self.sat_map)

        self.canvas = _RoofCanvas()
        self.canvas.polygonChanged.connect(self._on_canvas_polygon_changed)
        self.canvas.drawFinished.connect(self._on_draw_finished)
        self.view_stack.addWidget(self.canvas)

        if self.sat_map.available:
            self.view_stack.setCurrentIndex(_PAGE_MAP)
        else:
            self.view_stack.setCurrentIndex(_PAGE_IMAGE)

        right_lay.addWidget(self.view_stack, 1)
        self.canvas_hint = QLabel(
            "Satellite map: pan/zoom to your roof, select a face, then Draw outline."
        )
        self.canvas_hint.setStyleSheet("color: #6c7086; font-size: 10px;")
        right_lay.addWidget(self.canvas_hint)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)

    # ── Persistence / model ─────────────────────────────────────────────

    def _forecast_latlon(self) -> tuple[float, float]:
        lat, lon = 51.5, -0.1
        se = getattr(self.forecasts_tab, "solar_edits", None) or {}
        try:
            if "lat" in se and se["lat"].text().strip():
                lat = float(se["lat"].text().strip())
            if "lon" in se and se["lon"].text().strip():
                lon = float(se["lon"].text().strip())
        except (TypeError, ValueError):
            pass
        return lat, lon

    def _load(self):
        s = QSettings("PowerModel", "EnergyDashboard2")
        raw = s.value(_SETTINGS_KEY, "", type=str) or ""
        self._image_path = s.value(_SETTINGS_IMAGE_KEY, "", type=str) or ""
        planes = []
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    planes = list(data.get("planes") or [])
                elif isinstance(data, list):
                    planes = data
            except json.JSONDecodeError:
                planes = []
        if not planes:
            planes = [_new_plane("South roof")]
        for p in planes:
            p.setdefault("geo_ring", [])
            p.setdefault("polygon", [])
            p.setdefault("viz", True)
            p.setdefault("pv_string", 1)
            p.setdefault("top_edge", p.get("high_edge") or [])
            p.setdefault("bottom_edge", p.get("low_edge") or [])
            # Migrate legacy keys into top/bottom
            if not p.get("top_edge") and p.get("high_edge"):
                p["top_edge"] = p["high_edge"]
            if not p.get("bottom_edge") and p.get("low_edge"):
                p["bottom_edge"] = p["low_edge"]
            try:
                p["pv_string"] = max(1, int(p.get("pv_string") or 1))
            except (TypeError, ValueError):
                p["pv_string"] = 1
            # Migrate legacy ±180 Forecast.Solar values → 0…359
            try:
                p["azimuth"] = _forecast_solar_to_ui_az(p.get("azimuth") or 0)
            except (TypeError, ValueError):
                p["azimuth"] = 0.0
        self._planes = planes
        if self._image_path:
            self.canvas.set_background_image(self._image_path)
        self._rebuild_table()
        if self.table.rowCount():
            self.table.selectRow(0)
        self._update_summary()

    def _save(self, *, announce=False):
        self._sync_table_into_planes()
        s = QSettings("PowerModel", "EnergyDashboard2")
        s.setValue(_SETTINGS_KEY, json.dumps({"planes": self._planes}))
        s.setValue(_SETTINGS_IMAGE_KEY, self._image_path or "")
        s.sync()
        self._update_summary()
        if announce:
            self.set_status(
                f"Roof layout saved — {len(self._planes)} face(s), "
                f"{self._total_kwp():.2f} kWp total."
            )
            if self.on_data_updated:
                try:
                    self.on_data_updated()
                except Exception:
                    pass

    def _rebuild_table(self):
        self._suppress = True
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for plane in self._planes:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._set_row(row, plane)
        self.table.blockSignals(False)
        self._suppress = False

    def _set_row(self, row: int, plane: dict):
        def _item(text, editable=True):
            it = QTableWidgetItem(str(text))
            if not editable:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return it

        self.table.setItem(row, _COL_NAME, _item(plane.get("name") or f"Face {row + 1}"))
        try:
            str_n = max(1, int(plane.get("pv_string") or 1))
        except (TypeError, ValueError):
            str_n = 1
        str_it = _item(str_n)
        str_it.setToolTip(
            "Inverter DC string / MPPT input this face is wired into "
            "(1, 2, …). Several faces may share one string."
        )
        self.table.setItem(row, _COL_STRING, str_it)
        self.table.setItem(row, _COL_TILT, _item(f"{float(plane.get('tilt') or 0):.1f}"))
        self.table.setItem(row, _COL_AZ, _item(f"{_norm_az_0_359(plane.get('azimuth') or 0):.1f}"))

        combo = QComboBox()
        self._fill_panel_combo(combo, plane.get("panel_type") or "gen_400")
        idx = combo.findData(plane.get("panel_type") or "gen_400")
        combo.setCurrentIndex(max(0, idx))
        combo.currentIndexChanged.connect(
            lambda _i, r=row: self._on_panel_combo(r)
        )
        self.table.setCellWidget(row, _COL_PANEL, combo)

        self.table.setItem(row, _COL_COUNT, _item(int(plane.get("panel_count") or 0)))
        self.table.setItem(row, _COL_KWP, _item(f"{float(plane.get('kwp') or 0):.3f}"))

        on = QTableWidgetItem("")
        on.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )
        on.setCheckState(
            Qt.CheckState.Checked if plane.get("enabled", True) else Qt.CheckState.Unchecked
        )
        on.setToolTip("Include this face in the multi-plane forecast")
        self.table.setItem(row, _COL_ON, on)

        viz = QTableWidgetItem("")
        viz.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )
        viz.setCheckState(
            Qt.CheckState.Checked if plane.get("viz", True) else Qt.CheckState.Unchecked
        )
        viz.setToolTip("Show this face’s outline / KML on the satellite map")
        self.table.setItem(row, _COL_VIZ, viz)

    def _sync_table_into_planes(self):
        if not self._planes:
            return
        for row, plane in enumerate(self._planes):
            if row >= self.table.rowCount():
                break
            name_it = self.table.item(row, _COL_NAME)
            str_it = self.table.item(row, _COL_STRING)
            tilt_it = self.table.item(row, _COL_TILT)
            az_it = self.table.item(row, _COL_AZ)
            count_it = self.table.item(row, _COL_COUNT)
            on_it = self.table.item(row, _COL_ON)
            viz_it = self.table.item(row, _COL_VIZ)
            combo = self.table.cellWidget(row, _COL_PANEL)
            if name_it:
                plane["name"] = name_it.text().strip() or plane.get("name") or f"Face {row + 1}"
            try:
                plane["pv_string"] = max(1, int((str_it.text() if str_it else "1") or 1))
            except ValueError:
                plane["pv_string"] = int(plane.get("pv_string") or 1)
            try:
                plane["tilt"] = float((tilt_it.text() if tilt_it else "0") or 0)
            except ValueError:
                pass
            try:
                plane["azimuth"] = _norm_az_0_359((az_it.text() if az_it else "0") or 0)
            except ValueError:
                pass
            if combo is not None:
                plane["panel_type"] = combo.currentData() or plane.get("panel_type")
            try:
                count = int((count_it.text() if count_it else "0") or 0)
            except ValueError:
                count = int(plane.get("panel_count") or 0)
            plane["panel_count"] = count
            plane["kwp"] = _kwp_from_panels(plane.get("panel_type") or "gen_400", count)
            if on_it is not None:
                plane["enabled"] = on_it.checkState() == Qt.CheckState.Checked
            if viz_it is not None:
                plane["viz"] = viz_it.checkState() == Qt.CheckState.Checked
            # Keep String cell normalised (integer ≥ 1).
            if str_it is not None:
                self._suppress = True
                str_it.setText(str(int(plane["pv_string"])))
                self._suppress = False
            kwp_it = self.table.item(row, _COL_KWP)
            if kwp_it:
                self._suppress = True
                kwp_it.setText(f"{plane['kwp']:.3f}")
                self._suppress = False

    def _selected_index(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _total_kwp(self) -> float:
        self._sync_table_into_planes()
        total = 0.0
        for p in self._planes:
            if not p.get("enabled", True):
                continue
            try:
                total += float(p.get("kwp") or 0)
            except (TypeError, ValueError):
                pass
        return total

    def _weighted_tilt_azimuth(self) -> tuple[float, float]:
        self._sync_table_into_planes()
        tw = 0.0
        t_sum = 0.0
        a_sum = 0.0
        for p in self._planes:
            if not p.get("enabled", True):
                continue
            w = float(p.get("kwp") or 0)
            if w <= 0:
                continue
            tw += w
            t_sum += w * float(p.get("tilt") or 0)
            a_sum += w * _norm_az_0_359(p.get("azimuth") or 0)
        if tw <= 0:
            return 35.0, 0.0
        return round(t_sum / tw, 1), _norm_az_0_359(a_sum / tw)

    def _update_summary(self):
        self._sync_table_into_planes()
        n = sum(1 for p in self._planes if p.get("enabled", True))
        kwp = self._total_kwp()
        mode = "satellite" if self.view_stack.currentIndex() == _PAGE_MAP else "GE image"
        self.summary.setText(
            f"<b>{n}</b> enabled face(s) · <b>{kwp:.2f} kWp</b> total · view: {mode}"
        )

    def active_planes_for_forecast(self) -> list[dict]:
        """Planes with positive kWp for multi-plane solar fetch."""
        self._sync_table_into_planes()
        out = []
        for p in self._planes:
            if not p.get("enabled", True):
                continue
            try:
                kwp = float(p.get("kwp") or 0)
                tilt = float(p.get("tilt") or 0)
                az = _norm_az_0_359(p.get("azimuth") or 0)
            except (TypeError, ValueError):
                continue
            if kwp <= 0:
                continue
            out.append({
                "name": p.get("name") or "face",
                "tilt": tilt,
                # Forecast.Solar / Open-Meteo expect ±180 (0=south)
                "azimuth": _ui_az_to_forecast_solar(az),
                "kwp": kwp,
                "pv_string": int(p.get("pv_string") or 1),
            })
        return out

    # ── Slots ───────────────────────────────────────────────────────────

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._suppress or item is None:
            return
        row = item.row()
        if row < 0 or row >= len(self._planes):
            return
        if item.column() in (_COL_COUNT, _COL_PANEL):
            self._recompute_kwp_cell(row)
        if item.column() == _COL_VIZ:
            self._sync_table_into_planes()
            self._refresh_viz_on_map()
            self._save(announce=False)
        self._update_summary()

    def _refresh_viz_on_map(self):
        """Push Viz-checked face outlines onto the satellite map."""
        faces = []
        for i, p in enumerate(self._planes):
            if not p.get("viz", True):
                continue
            ring = _normalize_geo_ring(p.get("geo_ring") or [])
            if len(ring) < 3:
                continue
            faces.append({
                "name": p.get("name") or f"Face {i + 1}",
                "ring": ring,
            })
        self.sat_map.set_viz_rings(faces)

    def _on_panel_combo(self, row: int):
        if self._suppress:
            return
        self._recompute_kwp_cell(row)
        self._update_summary()

    def _recompute_kwp_cell(self, row: int):
        if row < 0 or row >= len(self._planes):
            return
        combo = self.table.cellWidget(row, _COL_PANEL)
        count_it = self.table.item(row, _COL_COUNT)
        pid = combo.currentData() if combo else "gen_400"
        try:
            count = int((count_it.text() if count_it else "0") or 0)
        except ValueError:
            count = 0
        kwp = _kwp_from_panels(pid, count)
        self._suppress = True
        kwp_it = self.table.item(row, _COL_KWP)
        if kwp_it:
            kwp_it.setText(f"{kwp:.3f}")
        self._planes[row]["panel_type"] = pid
        self._planes[row]["panel_count"] = count
        self._planes[row]["kwp"] = kwp
        self._suppress = False

    def _push_outline_to_views(self, plane: dict):
        geo = _normalize_geo_ring(plane.get("geo_ring") or [])
        self.sat_map.set_geo_ring(geo)
        self.canvas.set_polygon_points(plane.get("polygon") or [])
        self.sat_map.set_orientation_edges(
            _plane_top_edge(plane),
            _plane_bottom_edge(plane),
        )
        self._refresh_viz_on_map()
        self._refresh_azimuth_guide(plane)
        try:
            self.tilt_spin.setValue(float(plane.get("tilt") or 35.0))
        except (TypeError, ValueError):
            self.tilt_spin.setValue(35.0)
        self._refresh_orient_status(plane)

    def _refresh_azimuth_guide(self, plane: dict | None = None):
        if plane is None:
            idx = self._selected_index()
            plane = self._planes[idx] if 0 <= idx < len(self._planes) else None
        if not plane:
            self.sat_map.clear_azimuth_guide()
            return
        guide = _azimuth_guide_for_plane(plane, extend_m=10.0)
        self.sat_map.set_azimuth_guide(guide)

    def _refresh_orient_status(self, plane: dict | None = None):
        if plane is None:
            idx = self._selected_index()
            plane = self._planes[idx] if 0 <= idx < len(self._planes) else None
        if not plane:
            self.orient_status.setText(
                "Select a face, then top edge → bottom edge → set tilt."
            )
            return
        has_t = bool(_normalize_edge(_plane_top_edge(plane)))
        has_b = bool(_normalize_edge(_plane_bottom_edge(plane)))
        try:
            az = _norm_az_0_359(plane.get("azimuth") or 0)
            tilt = float(plane.get("tilt") or 0)
        except (TypeError, ValueError):
            az, tilt = 0.0, 0.0
        bits = []
        bits.append("top ✓" if has_t else "top —")
        bits.append("bottom ✓" if has_b else "bottom —")
        bits.append(f"tilt {tilt:.1f}°")
        bits.append(f"az {az:.1f}° (0–359, top→bottom)")
        self.orient_status.setText(" · ".join(bits))

    def _on_row_selected(self):
        idx = self._selected_index()
        if idx < 0 or idx >= len(self._planes):
            return
        # Cancel edge pick when switching faces
        self._cancel_edge_pick_buttons()
        plane = self._planes[idx]
        self._push_outline_to_views(plane)
        name = plane.get("name") or f"Face {idx + 1}"
        if self.view_stack.currentIndex() == _PAGE_MAP:
            self.canvas_hint.setText(
                f"Editing “{name}” — Draw outline, then Select top/bottom edges and Set tilt."
            )
        else:
            self.canvas_hint.setText(
                f"Editing outline for “{name}” on the GE image."
            )

    def _on_map_polygon_changed(self):
        idx = self._selected_index()
        if idx < 0 or idx >= len(self._planes):
            return
        ring = self.sat_map.geo_ring()
        self._planes[idx]["geo_ring"] = ring
        self._refresh_viz_on_map()
        self._refresh_azimuth_guide(self._planes[idx])
        # Only auto-guess azimuth when the user hasn't set top/bottom edges yet.
        if (
            len(ring) >= 3
            and not _normalize_edge(_plane_top_edge(self._planes[idx]))
            and not _normalize_edge(_plane_bottom_edge(self._planes[idx]))
        ):
            az = _longest_edge_facing_azimuth([(p[0], p[1]) for p in ring])
            if az is not None:
                self._set_face_azimuth(idx, az)
        self._refresh_orient_status(self._planes[idx])

    def _set_face_azimuth(self, idx: int, az: float):
        self._planes[idx]["azimuth"] = _norm_az_0_359(az)
        self._suppress = True
        az_it = self.table.item(idx, _COL_AZ)
        if az_it:
            az_it.setText(f"{_norm_az_0_359(az):.1f}")
        self._suppress = False
        if idx == self._selected_index():
            self._refresh_azimuth_guide(self._planes[idx])

    def _set_face_tilt(self, idx: int, tilt: float):
        self._planes[idx]["tilt"] = float(tilt)
        self._suppress = True
        tilt_it = self.table.item(idx, _COL_TILT)
        if tilt_it:
            tilt_it.setText(f"{float(tilt):.1f}")
        self._suppress = False
        if idx == self._selected_index():
            self._refresh_azimuth_guide(self._planes[idx])

    def _recompute_azimuth_from_edges(self, idx: int):
        if idx < 0 or idx >= len(self._planes):
            return
        plane = self._planes[idx]
        az = _azimuth_from_top_bottom_edges(
            _plane_top_edge(plane), _plane_bottom_edge(plane),
        )
        if az is None:
            return
        self._set_face_azimuth(idx, az)
        self._refresh_orient_status(plane)
        self.set_status(
            f"Roof layout: azimuth {az:.1f}° from top→bottom "
            f"(face “{plane.get('name') or idx + 1}”)."
        )

    def _cancel_edge_pick_buttons(self):
        for btn in (self.btn_top, self.btn_bottom):
            btn.blockSignals(True)
            btn.setChecked(False)
            btn.blockSignals(False)
        self.sat_map.set_edge_pick_mode(None)

    def _on_edge_pick_toggled(self, kind: str, on: bool):
        idx = self._selected_index()
        if on and idx < 0:
            self._cancel_edge_pick_buttons()
            QMessageBox.information(self, "Roof layout", "Select a roof face first.")
            return
        if on:
            if self.btn_draw.isChecked():
                self.btn_draw.blockSignals(True)
                self.btn_draw.setChecked(False)
                self.btn_draw.blockSignals(False)
                self.sat_map.set_draw_mode(False)
                self.canvas.set_draw_mode(False)
            other = self.btn_bottom if kind == "top" else self.btn_top
            other.blockSignals(True)
            other.setChecked(False)
            other.blockSignals(False)
            self.sat_map.ensure_started()
            self.view_stack.setCurrentIndex(_PAGE_MAP)
            self.sat_map.set_edge_pick_mode(kind)
            label = "TOP" if kind == "top" else "BOTTOM"
            self.canvas_hint.setText(
                f"Click two ends of the {label} edge (azimuth = top → bottom)."
            )
            self.set_status(
                f"Roof layout: pick {label} edge — click two ends on the map "
                "(cursor should be a crosshair)."
            )
        else:
            self.sat_map.set_edge_pick_mode(None)

    def _on_edge_picked(self, kind: str, edge):
        idx = self._selected_index()
        if idx < 0 or idx >= len(self._planes):
            return
        edge = _normalize_edge(edge)
        if not edge:
            return
        key = "top_edge" if kind == "top" else "bottom_edge"
        self._planes[idx][key] = edge
        # Keep legacy keys in sync for older saves
        legacy = "high_edge" if kind == "top" else "low_edge"
        self._planes[idx][legacy] = edge
        btn = self.btn_top if kind == "top" else self.btn_bottom
        btn.blockSignals(True)
        btn.setChecked(False)
        btn.blockSignals(False)
        self.sat_map.set_edge_pick_mode(None)
        self.sat_map.set_orientation_edges(
            _plane_top_edge(self._planes[idx]),
            _plane_bottom_edge(self._planes[idx]),
        )
        self._recompute_azimuth_from_edges(idx)
        self._save(announce=False)

    def _apply_tilt_to_face(self):
        idx = self._selected_index()
        if idx < 0:
            QMessageBox.information(self, "Roof layout", "Select a roof face first.")
            return
        tilt = float(self.tilt_spin.value())
        self._set_face_tilt(idx, tilt)
        self._refresh_orient_status(self._planes[idx])
        self._save(announce=False)
        self.set_status(
            f"Roof layout: tilt {tilt:.1f}° on “{self._planes[idx].get('name') or idx + 1}”."
        )

    def _flip_face_azimuth(self):
        idx = self._selected_index()
        if idx < 0:
            return
        try:
            az = float(self._planes[idx].get("azimuth") or 0)
        except (TypeError, ValueError):
            az = 0.0
        plane = self._planes[idx]
        # Swap top/bottom for display only — facing reverses by exactly 180°.
        # Do not recompute from edge midpoints (that can jump by ~90° if edges
        # are short/skewed relative to the array).
        top = list(_plane_top_edge(plane))
        bottom = list(_plane_bottom_edge(plane))
        if top or bottom:
            plane["top_edge"], plane["bottom_edge"] = bottom, top
            plane["high_edge"], plane["low_edge"] = bottom, top
            self.sat_map.set_orientation_edges(
                plane.get("top_edge"), plane.get("bottom_edge"),
            )
        new_az = _flip_forecast_azimuth(az)
        self._set_face_azimuth(idx, new_az)
        self._refresh_orient_status(plane)
        self._save(announce=False)
        self.set_status(
            f"Roof layout: flipped azimuth {az:.1f}° → {new_az:.1f}° (180°)."
        )

    def _flip_all_azimuths(self):
        """Reverse facing on every enabled face (KML top/bottom often inverted)."""
        self._sync_table_into_planes()
        n = 0
        for i, plane in enumerate(self._planes):
            if not plane.get("enabled", True):
                continue
            try:
                az = float(plane.get("azimuth") or 0)
            except (TypeError, ValueError):
                az = 0.0
            top = list(_plane_top_edge(plane))
            bottom = list(_plane_bottom_edge(plane))
            if top or bottom:
                plane["top_edge"], plane["bottom_edge"] = bottom, top
                plane["high_edge"], plane["low_edge"] = bottom, top
            new_az = _flip_forecast_azimuth(az)
            plane["azimuth"] = new_az
            n += 1
            # Keep table cell in sync without full rebuild side-effects.
            item = self.table.item(i, 2)
            if item is not None:
                item.setText(f"{new_az:.1f}")
            else:
                self._set_face_azimuth(i, new_az)
        if n <= 0:
            self.set_status("Roof layout: no enabled faces to flip.")
            return
        idx = self._selected_index()
        if idx >= 0:
            plane = self._planes[idx]
            self.sat_map.set_orientation_edges(
                plane.get("top_edge"), plane.get("bottom_edge"),
            )
            self._refresh_orient_status(plane)
            self._refresh_azimuth_guide(plane)
        self._save(announce=False)
        self.set_status(
            f"Roof layout: flipped azimuth on {n} face(s) (+180°). "
            "Click Apply to Forecasts to refresh the solar curve."
        )

    def _clear_face_edges(self):
        idx = self._selected_index()
        if idx < 0:
            return
        for k in ("top_edge", "bottom_edge", "high_edge", "low_edge"):
            self._planes[idx][k] = []
        self.sat_map.clear_orientation_edges()
        self._refresh_orient_status(self._planes[idx])
        self._save(announce=False)

    def _on_canvas_polygon_changed(self):
        idx = self._selected_index()
        if idx < 0 or idx >= len(self._planes):
            return
        self._planes[idx]["polygon"] = self.canvas.polygon_points()

    def _on_draw_finished(self):
        if self.btn_draw.isChecked():
            self.btn_draw.blockSignals(True)
            self.btn_draw.setChecked(False)
            self.btn_draw.blockSignals(False)
        self.sat_map.set_draw_mode(False)
        self.canvas.set_draw_mode(False)

    def _on_draw_toggled(self, on: bool):
        idx = self._selected_index()
        if on and idx < 0:
            self.btn_draw.blockSignals(True)
            self.btn_draw.setChecked(False)
            self.btn_draw.blockSignals(False)
            QMessageBox.information(self, "Roof layout", "Select a roof face first.")
            return
        if on:
            self._cancel_edge_pick_buttons()
        if self.view_stack.currentIndex() == _PAGE_MAP:
            self.sat_map.set_draw_mode(on)
            self.canvas.set_draw_mode(False)
        else:
            self.canvas.set_draw_mode(on)
            self.sat_map.set_draw_mode(False)

    def _clear_outline(self):
        if self.view_stack.currentIndex() == _PAGE_MAP:
            self.sat_map.clear_polygon()
        else:
            self.canvas.clear_polygon()
        idx = self._selected_index()
        if 0 <= idx < len(self._planes):
            if self.view_stack.currentIndex() == _PAGE_MAP:
                self._planes[idx]["geo_ring"] = []
            else:
                self._planes[idx]["polygon"] = []

    def reload_panel_choices(self):
        """Rebuild each face’s panel menu from the Panel database."""
        self._suppress = True
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, _COL_PANEL)
            if combo is None:
                continue
            self._fill_panel_combo(combo, combo.currentData())
        self._suppress = False
        for row in range(self.table.rowCount()):
            self._recompute_kwp_cell(row)
        self._update_summary()

    def _fill_panel_combo(self, combo, current_id):
        combo.blockSignals(True)
        combo.clear()
        for pan in list_panels():
            combo.addItem(panel_label(pan), pan["id"])
        idx = combo.findData(current_id or "gen_400")
        if idx < 0 and combo.count():
            idx = 0
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def showEvent(self, event):
        super().showEvent(event)
        self.reload_panel_choices()
        # Chromium starts on first view of the map page, not at app startup.
        if self.view_stack.currentIndex() == _PAGE_MAP:
            self.sat_map.ensure_started()
            self._restore_saved_imagery()

    def _show_satellite(self):
        self.sat_map.ensure_started()
        self.view_stack.setCurrentIndex(_PAGE_MAP)
        self._center_map_on_forecasts()
        self.canvas_hint.setText(
            "Satellite map: pan/zoom to your roof, select a face, then Draw outline."
        )
        self._update_summary()
        idx = self._selected_index()
        if 0 <= idx < len(self._planes):
            self._push_outline_to_views(self._planes[idx])
        self._restore_saved_imagery()

    def _center_map_on_forecasts(self):
        lat, lon = self._forecast_latlon()
        self.sat_map.set_center(lat, lon, 20)
        self.set_status(f"Roof layout map centered on {lat:.5f}, {lon:.5f}")

    def _saved_imagery(self) -> dict:
        s = QSettings("PowerModel", "EnergyDashboard2")
        raw = s.value(_SETTINGS_IMAGERY_KEY, "", type=str) or ""
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _store_imagery(self, choice: dict):
        s = QSettings("PowerModel", "EnergyDashboard2")
        s.setValue(_SETTINGS_IMAGERY_KEY, json.dumps({
            "key": choice.get("key") or "esri_live",
            "m": choice.get("m") or "",
            "label": choice.get("label") or "",
        }))

    def _restore_saved_imagery(self):
        choice = self._saved_imagery()
        key = choice.get("key")
        if not key:
            return
        self.sat_map.apply_imagery(key, choice.get("m") or "")

    def _use_clearest_image(self):
        if self._sharp_busy:
            return
        self.sat_map.ensure_started()
        self.view_stack.setCurrentIndex(_PAGE_MAP)
        self.btn_clearest.setEnabled(False)
        self._sharp_busy = True
        self.set_status("Roof layout: scanning satellite/aerial layers for the clearest image…")
        self.canvas_hint.setText("Scanning imagery for the sharpest roof view…")

        def _got_view(view: dict):
            lat, lon = self._forecast_latlon()
            try:
                if view.get("lat") is not None:
                    lat = float(view["lat"])
                if view.get("lon") is not None:
                    lon = float(view["lon"])
            except (TypeError, ValueError):
                pass
            try:
                zoom = int(view.get("z") or 20)
            except (TypeError, ValueError):
                zoom = 20
            threading.Thread(
                target=self._scan_clearest_thread,
                args=(lat, lon, zoom),
                daemon=True,
            ).start()

        self.sat_map.get_map_view(_got_view)

    def _scan_clearest_thread(self, lat: float, lon: float, zoom: int):
        try:
            winner = _scan_clearest_imagery(lat, lon, zoom)
        except Exception:
            winner = None

        def _apply():
            self._sharp_busy = False
            self.btn_clearest.setEnabled(True)
            if not winner:
                self.set_status(
                    "Roof layout: could not score imagery (network?). Try again, "
                    "or pick Esri Wayback by year."
                )
                self.canvas_hint.setText(
                    "Clearest-image scan found nothing usable. Check the network "
                    "or pick a Wayback release by hand."
                )
                return
            self.sat_map.apply_imagery(winner["key"], winner.get("m") or "")
            self._store_imagery(winner)
            label = winner.get("label") or winner["key"]
            self.set_status(f"Roof layout: using clearest image — {label}")
            self.canvas_hint.setText(
                f"Using clearest image: {label}. Trace faces on this background."
            )

        self._inv.invoke(_apply)

    def _add_plane(self):
        self._sync_table_into_planes()
        n = len(self._planes) + 1
        plane = _new_plane(f"Roof face {n}")
        try:
            used = [int(p.get("pv_string") or 1) for p in self._planes]
            plane["pv_string"] = (max(used) + 1) if used else 1
        except (TypeError, ValueError):
            plane["pv_string"] = n
        self._planes.append(plane)
        self._rebuild_table()
        self.table.selectRow(self.table.rowCount() - 1)
        self._update_summary()

    def _remove_plane(self):
        idx = self._selected_index()
        if idx < 0:
            return
        if len(self._planes) <= 1:
            QMessageBox.information(self, "Roof layout", "Keep at least one roof face.")
            return
        del self._planes[idx]
        self._rebuild_table()
        self.table.selectRow(min(idx, self.table.rowCount() - 1))
        self._update_summary()
        self._save(announce=False)

    def _on_table_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        row = idx.row() if idx.isValid() else self._selected_index()
        if row < 0 or row >= len(self._planes):
            return
        self.table.selectRow(row)
        name = self._planes[row].get("name") or f"Face {row + 1}"
        menu = QMenu(self)
        act_remove = menu.addAction(f"Remove “{name}”")
        act_remove.setEnabled(len(self._planes) > 1)
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_remove:
            self._remove_plane()

    def _load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Google Earth screenshot",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)",
        )
        if not path:
            return
        self._image_path = path
        self.canvas.set_background_image(path)
        self.view_stack.setCurrentIndex(_PAGE_IMAGE)
        self._save(announce=False)
        self.set_status(f"Roof layout: loaded background {Path(path).name}")
        self.canvas_hint.setText(
            "GE image loaded — select a face, then Draw outline on the screenshot."
        )
        self._update_summary()

    def _import_kml(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Google Earth KML",
            str(Path.home()),
            "KML (*.kml *.xml);;All files (*)",
        )
        if not path:
            return
        try:
            polys = _parse_kml_polygons(path)
        except Exception as e:
            QMessageBox.warning(self, "Roof layout", f"Could not read KML:\n{e}")
            return
        if not polys:
            QMessageBox.information(
                self, "Roof layout",
                "No polygons found in that KML. In Google Earth, draw a polygon "
                "and File → Save Place As → KML.",
            )
            return
        self._sync_table_into_planes()
        created = 0
        for i, ring in enumerate(polys):
            lons = [p[0] for p in ring]
            lats = [p[1] for p in ring]
            lat_c = sum(lats) / len(lats)
            lon_c = sum(lons) / len(lons)
            az = _longest_edge_facing_azimuth(ring)
            plane = _new_plane(f"KML face {i + 1}")
            plane["pv_string"] = i + 1
            if az is not None:
                plane["azimuth"] = az
            plane["geo_ring"] = [[lon, lat] for lon, lat in ring]
            self._planes.append(plane)
            created += 1
            if i == 0 and self.forecasts_tab is not None:
                try:
                    from energy_dashboard.dialogs.map_picker import _sync_forecasts_tab_latlon
                    _sync_forecasts_tab_latlon(self.forecasts_tab, lat_c, lon_c)
                except Exception:
                    se = getattr(self.forecasts_tab, "solar_edits", None) or {}
                    if "lat" in se:
                        se["lat"].setText(f"{lat_c:.5f}")
                    if "lon" in se:
                        se["lon"].setText(f"{lon_c:.5f}")
        self._rebuild_table()
        self.table.selectRow(self.table.rowCount() - created)
        self.sat_map.ensure_started()
        self.view_stack.setCurrentIndex(_PAGE_MAP)
        self._center_map_on_forecasts()
        self._save(announce=False)
        self.set_status(
            f"Roof layout: imported {created} KML polygon(s). "
            "Adjust tilt/panel count, then Apply to Forecasts."
        )
        self._update_summary()

    def _open_google_earth(self):
        lat, lon = self._forecast_latlon()
        url = f"https://earth.google.com/web/@{lat},{lon},120a,400d,35y,0h,0t,0r"
        opened = False
        try:
            from energy_dashboard.dialogs.map_picker import _try_launch_direct_browser
            opened = bool(_try_launch_direct_browser(url))
        except Exception:
            opened = False
        if not opened:
            try:
                opened = bool(QDesktopServices.openUrl(QUrl(url)))
            except Exception:
                opened = False
        if not opened:
            try:
                opened = bool(webbrowser.open(url))
            except Exception:
                opened = False
        if opened:
            self.set_status(
                "Opened Google Earth Web — or use the in-tab Satellite map to outline."
            )
        else:
            QMessageBox.information(
                self,
                "Google Earth",
                "Could not launch a browser.\n\n"
                f"Open this URL manually:\n{url}\n\n"
                "Or use the in-tab Satellite map / Load GE image…",
            )

    def _apply_to_forecasts(self):
        self._sync_table_into_planes()
        planes = self.active_planes_for_forecast()
        if not planes:
            QMessageBox.information(
                self, "Roof layout",
                "Enable at least one roof face with panel count / kWp > 0.",
            )
            return
        self._save(announce=False)
        ft = self.forecasts_tab
        if ft is None:
            return
        total_kwp = sum(p["kwp"] for p in planes)
        tilt, az_ui = self._weighted_tilt_azimuth()
        az_api = _ui_az_to_forecast_solar(az_ui)
        se = ft.solar_edits
        se["kwp"].setText(f"{total_kwp:.3f}".rstrip("0").rstrip("."))
        se["tilt"].setText(f"{tilt:.1f}".rstrip("0").rstrip("."))
        se["azimuth"].setText(f"{az_api:.1f}".rstrip("0").rstrip("."))
        if hasattr(ft, "_save_forecast_parameters_clicked"):
            try:
                ft._save_forecast_parameters_clicked()
            except Exception:
                pass
        s = QSettings("PowerModel", "EnergyDashboard2")
        s.setValue("forecasts/use_roof_layout", True)
        s.sync()
        self.set_status(
            f"Roof layout applied — {len(planes)} face(s), {total_kwp:.2f} kWp. "
            "Fetching multi-plane solar forecast…"
        )
        if hasattr(ft, "fetch_forecasts"):
            ft.fetch_forecasts()
        if self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception:
                pass

    def _use_single_plane(self):
        s = QSettings("PowerModel", "EnergyDashboard2")
        s.setValue("forecasts/use_roof_layout", False)
        s.sync()
        self.set_status(
            "Roof layout: multi-plane off — Forecasts will use single tilt/azimuth/kWp."
        )
        ft = self.forecasts_tab
        if ft is not None and hasattr(ft, "fetch_forecasts"):
            ft.fetch_forecasts()


def active_roof_planes_from_settings() -> list[dict]:
    """Read enabled planes from QSettings (for Forecasts fetch without tab)."""
    s = QSettings("PowerModel", "EnergyDashboard2")
    if not s.value("forecasts/use_roof_layout", False, type=bool):
        return []
    raw = s.value(_SETTINGS_KEY, "", type=str) or ""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        planes = data.get("planes") if isinstance(data, dict) else data
    except json.JSONDecodeError:
        return []
    out = []
    for p in planes or []:
        if not p.get("enabled", True):
            continue
        try:
            kwp = float(p.get("kwp") or 0)
            tilt = float(p.get("tilt") or 0)
            az = _norm_az_0_359(p.get("azimuth") or 0)
        except (TypeError, ValueError):
            continue
        if kwp <= 0:
            continue
        out.append({
            "name": p.get("name") or "face",
            "tilt": tilt,
            "azimuth": _ui_az_to_forecast_solar(az),
            "kwp": kwp,
        })
    return out


__all__ = ["RoofLayoutTab", "active_roof_planes_from_settings"]
