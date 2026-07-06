"""
Energy Dashboard — `config.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.secrets import load_secrets, secret

load_secrets()

# ==================== CREDENTIALS (from .env / environment) ====================

DEFAULT_GROWATT_USER = secret("GROWATT_USER")
DEFAULT_GROWATT_PASS = secret("GROWATT_PASSWORD")
DEFAULT_GROWATT_TOKEN = secret("GROWATT_API_TOKEN")

DEFAULT_OCTOPUS_KEY = secret("OCTOPUS_API_KEY")
DEFAULT_IMPORT_MPAN = secret("OCTOPUS_IMPORT_MPAN")
DEFAULT_IMPORT_SERIAL = secret("OCTOPUS_IMPORT_SERIAL")
DEFAULT_EXPORT_MPAN = secret("OCTOPUS_EXPORT_MPAN")
DEFAULT_EXPORT_SERIAL = secret("OCTOPUS_EXPORT_SERIAL")
DEFAULT_OCTOPUS_ACCOUNT = secret("OCTOPUS_ACCOUNT")

DEFAULT_FORECAST_LAT = secret("FORECAST_LAT", "51.5")
DEFAULT_FORECAST_LON = secret("FORECAST_LON", "-0.1")
DEFAULT_FORECAST_DECLINATION = secret("FORECAST_TILT", "35")
DEFAULT_FORECAST_AZIMUTH = secret("FORECAST_AZIMUTH", "0")
DEFAULT_FORECAST_KWP = secret("FORECAST_KWP", "6.0")
DEFAULT_AGILE_PRODUCT = "AGILE-24-10-01"
DEFAULT_AGILE_TARIFF = "E-1R-AGILE-24-10-01-H"
DEFAULT_AGILE_EXPORT_TARIFF = "E-1R-AGILE-OUTGOING-19-05-13-H"

TASMOTA_IP_START = secret("TASMOTA_IP_START", "222.20.20.101")


class AppParameters:
    """Central tweakable values; the Parameters tab edits these and pushes to other tabs."""

    def __init__(self):
        self.import_flat_pence = 24.5
        self.export_flat_pence = 15.0
        self.analytics_efficiency_pct = 90.0
        self.analytics_max_charge_kw = 3.3
        self.analytics_battery_cost_gbp = 2500.0
        self.agile_product = DEFAULT_AGILE_PRODUCT
        self.agile_tariff = DEFAULT_AGILE_TARIFF
        self.agile_export_tariff = DEFAULT_AGILE_EXPORT_TARIFF
        self.battery_capacity_kwh = 13.0
        self.battery_low_soc_threshold_pct = 10
        self.auto_refresh_seconds = 30
        self.auto_refresh_enabled = True
        self.solar_lat = DEFAULT_FORECAST_LAT
        self.solar_lon = DEFAULT_FORECAST_LON
        self.solar_tilt = DEFAULT_FORECAST_DECLINATION
        self.solar_azimuth = DEFAULT_FORECAST_AZIMUTH
        self.solar_kwp = DEFAULT_FORECAST_KWP
        self.base_load_kw = 0.4
        self.scheduled_loads = []  # list of {'hour': int, 'kw': float, 'duration_min': int}
        self.growatt_local_ip = ""
        self.growatt_local_port = 80
        self.growatt_lan_ip = ""
        self.growatt_wifi_ip = ""
        self.growatt_lan_user = ""
        self.growatt_lan_password = ""
        self.growatt_wifi_user = ""
        self.growatt_wifi_password = ""
        self.grott_mqtt_enabled = False
        self.growatt_telemetry_source = "api"  # api | grott | hybrid
        self.grott_fill_missing_api = False
        self.grott_mqtt_host = ""
        self.grott_mqtt_port = 1883
        self.grott_mqtt_user = ""
        self.grott_mqtt_password = ""
        self.grott_mqtt_topic = "energy/growatt"
        self.grott_mqtt_fresh_s = 120
        # Local Modbus connectivity probe (Setup & Info — optional; requires pymodbus)
        self.growatt_modbus_mode = "off"  # off | tcp | serial
        self.growatt_modbus_tcp_port = 502
        self.growatt_modbus_serial_path = "/dev/ttyUSB0"
        self.growatt_modbus_baud = 9600
        self.growatt_modbus_unit = 1


TASMOTA_IP_END = secret("TASMOTA_IP_END", "222.20.20.112")

# Tasmota device tables: IPs are split evenly between left/right columns
# (first column gets the extra row when the count is odd).
# Power History chart Y-axis presets (right-click menu and pin-500).
TASMOTA_HIST_Y_PRESETS = (0, 200, 300, 400, 500, 750, 1000, 1500, 2000)


def growatt_lan_host(params) -> str:
    """Ethernet/LAN IP for Modbus TCP and optional web UI."""
    return (
        (getattr(params, "growatt_lan_ip", "") or getattr(params, "growatt_local_ip", "") or "")
        .strip()
    )


def growatt_wifi_host(params) -> str:
    """Wi‑Fi dongle / wireless IP for the inverter web UI."""
    return (getattr(params, "growatt_wifi_ip", "") or "").strip()


def growatt_modbus_tcp_host(params) -> str:
    """Host for Modbus TCP — prefer LAN, fall back to Wi‑Fi."""
    return growatt_lan_host(params) or growatt_wifi_host(params)


def growatt_http_host(params) -> str:
    """Host for local web UI reachability — prefer Wi‑Fi, fall back to LAN."""
    return growatt_wifi_host(params) or growatt_lan_host(params)


GROWATT_TELEMETRY_API = "api"
GROWATT_TELEMETRY_GROTT = "grott"
GROWATT_TELEMETRY_HYBRID = "hybrid"
GROWATT_TELEMETRY_SOURCES = (
    GROWATT_TELEMETRY_API,
    GROWATT_TELEMETRY_GROTT,
    GROWATT_TELEMETRY_HYBRID,
)


def growatt_uses_grott(source: str) -> bool:
    return source in (GROWATT_TELEMETRY_GROTT, GROWATT_TELEMETRY_HYBRID)


def read_growatt_telemetry_source(settings, params=None) -> str:
    """Read persisted Growatt live source, migrating legacy grott_mqtt_enabled."""
    key = "params/growatt_telemetry_source"
    if settings is not None and settings.contains(key):
        raw = str(settings.value(key, GROWATT_TELEMETRY_API) or "").strip().lower()
        if raw in GROWATT_TELEMETRY_SOURCES:
            return raw
    if params is not None:
        src = getattr(params, "growatt_telemetry_source", None)
        if src in GROWATT_TELEMETRY_SOURCES:
            return src
    grott = False
    if settings is not None and settings.contains("params/grott_mqtt_enabled"):
        grott = bool(settings.value("params/grott_mqtt_enabled", False, type=bool))
    elif params is not None:
        grott = bool(getattr(params, "grott_mqtt_enabled", False))
    return GROWATT_TELEMETRY_GROTT if grott else GROWATT_TELEMETRY_API


def read_grott_fill_missing_api(settings, params=None) -> bool:
    key = "params/grott_fill_missing_api"
    if settings is not None and settings.contains(key):
        return bool(settings.value(key, False, type=bool))
    if params is not None:
        return bool(getattr(params, "grott_fill_missing_api", False))
    return False


def write_growatt_telemetry_settings(settings, source: str, *, fill_missing_api: bool) -> None:
    """Persist telemetry source and keep legacy grott_mqtt_enabled in sync."""
    if source not in GROWATT_TELEMETRY_SOURCES:
        source = GROWATT_TELEMETRY_API
    settings.setValue("params/growatt_telemetry_source", source)
    settings.setValue("params/grott_mqtt_enabled", growatt_uses_grott(source))
    settings.setValue("params/grott_fill_missing_api", bool(fill_missing_api))


__all__ = [n for n in globals() if not n.startswith('__')]
