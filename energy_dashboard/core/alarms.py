"""
Live battery / PV / Grott-feed alarms for the Energy Dashboard.

Evaluated on each Growatt live update and on a 15 s watchdog (so a dead
Grott feed still fires when the UI is not getting new snapshots). Pure
logic — no Qt widgets here so workers and tests can call it without a GUI.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


# Defaults (also used when QSettings keys are missing).
DEFAULT_HOLD_MINUTES = 10.0
DEFAULT_PV_MIN_KW = 1.0
DEFAULT_CHARGE_IDLE_KW = 0.15
# Legacy fixed cooldown (kept for QSettings / configure compat; tray uses backoff).
DEFAULT_NOTIFY_COOLDOWN_S = 30 * 60
DEFAULT_GROTT_LOST_HOLD_S = 20.0
DEFAULT_DB_DISCONNECT_HOLD_S = 60.0
DEFAULT_DB_INGEST_HOLD_S = 90.0
DEFAULT_INGEST_STARTUP_GRACE_S = 16 * 60
DEFAULT_INVERTER_LOST_HOLD_S = 120.0
DEFAULT_TASMOTA_MQTT_HOLD_S = 30.0
DEFAULT_TASMOTA_STALE_S = 8 * 60

# System-tray re-notify while an alarm stays active:
# 4× every 5 min, 4× every 10 min, 4× every 30 min, then hourly.
# First notify is immediate (interval 0); stages apply to subsequent gaps.
NOTIFY_BACKOFF_STAGES: tuple[tuple[int, float], ...] = (
    (4, 5 * 60),
    (4, 10 * 60),
    (4, 30 * 60),
)
NOTIFY_BACKOFF_FINAL_S = 60 * 60


def notify_backoff_interval_s(notifies_already_sent: int) -> float:
    """Seconds to wait before the next tray notify given how many were already sent."""
    sent = max(0, int(notifies_already_sent))
    if sent <= 0:
        return 0.0
    consumed = 0
    for count, interval in NOTIFY_BACKOFF_STAGES:
        if sent < consumed + count:
            return float(interval)
        consumed += count
    return float(NOTIFY_BACKOFF_FINAL_S)


@dataclass(frozen=True)
class AlarmSpec:
    """One alarm the monitor can raise. The Enumerated Alarms tab lists these."""

    key: str
    name: str
    level: str
    fires_after: str
    meaning: str


# Standing catalogue. Live titles and details still come from AlarmMonitor.
ALARM_CATALOGUE: tuple[AlarmSpec, ...] = (
    AlarmSpec(
        "low_soc",
        "Low state of charge",
        "Warning, or critical if very low",
        "Setup hold time (default 10 min)",
        "The pack stays below the low-SOC threshold in Setup. "
        "It is critical if the charge falls under half that threshold, or under 5%.",
    ),
    AlarmSpec(
        "sun_wasted",
        "Spare solar not charging",
        "Critical",
        "Setup hold time (default 10 min)",
        "State of charge is below the threshold, spare solar is at least the "
        "sun-waste minimum (default 1 kW), and the battery is barely charging. "
        "The house is not using that spare — the inverter or BMS is not taking it.",
    ),
    AlarmSpec(
        "load_eats_pv",
        "House using all the solar",
        "Warning",
        "Setup hold time (default 10 min)",
        "The array is producing at least the sun-waste minimum, but the house "
        "is using almost all of it, so nothing is left to charge the battery.",
    ),
    AlarmSpec(
        "grott_lost",
        "Grott feed lost",
        "Critical",
        "About 20 seconds if MQTT drops; the Grott fresh window if frames stop",
        "The local Grott feed is down, or MQTT is up but no live inverter frame "
        "has arrived. A quiet stretch of about 11 minutes after the Shine stick "
        "reconnects is the stick talking to Growatt’s servers, not a broker drop.",
    ),
    AlarmSpec(
        "db_disconnected",
        "Logging database unreachable",
        "Critical",
        "About 60 seconds",
        "Logging is turned on, but the database cannot be reached, so live "
        "readings are not being stored.",
    ),
    AlarmSpec(
        "db_ingest_stale",
        "Nothing written to the database",
        "Critical",
        "About 90 seconds, after 15 minutes with no new rows",
        "The database is connected and Growatt or Tasmota looks live, but "
        "growatt_readings / tasmota_readings have had no new rows. Startup is "
        "given about 16 minutes before this can fire.",
    ),
    AlarmSpec(
        "inverter_comms_lost",
        "Inverter not talking",
        "Critical",
        "About 2 minutes",
        "Growatt’s cloud says the inverter is offline. That is the kit itself "
        "(Shine stick, display, LAN), not a chart in this app.",
    ),
    AlarmSpec(
        "tasmota_mqtt_lost",
        "Tasmota MQTT disconnected",
        "Critical",
        "About 30 seconds",
        "The Tasmota page is in MQTT mode and the broker connection has dropped, "
        "so plug and CT readings will freeze.",
    ),
    AlarmSpec(
        "tasmota_offline",
        "Tasmota device silent",
        "Warning, or critical if three or more",
        "About 8 minutes",
        "Named plugs or CTs have stopped reporting while MQTT itself is still up. "
        "Usual causes are Wi-Fi, a plug that is off, or stuck firmware.",
    ),
)


@dataclass
class AlarmHit:
    key: str
    severity: str  # "warn" | "critical"
    title: str
    detail: str
    since_wall: float
    just_triggered: bool = False
    should_notify: bool = False


@dataclass
class AlarmMonitor:
    """Track rising/falling edges for low-SOC and sun-wasted conditions."""

    hold_minutes: float = DEFAULT_HOLD_MINUTES
    pv_min_kw: float = DEFAULT_PV_MIN_KW
    charge_idle_kw: float = DEFAULT_CHARGE_IDLE_KW
    notify_cooldown_s: float = DEFAULT_NOTIFY_COOLDOWN_S
    enabled: bool = True
    desktop_enabled: bool = True

    _below_since: float | None = field(default=None, init=False)
    _sun_waste_since: float | None = field(default=None, init=False)
    _load_eats_pv_since: float | None = field(default=None, init=False)
    _grott_lost_since: float | None = field(default=None, init=False)
    _db_disc_since: float | None = field(default=None, init=False)
    _db_ingest_since: float | None = field(default=None, init=False)
    _inv_lost_since: float | None = field(default=None, init=False)
    _tasmota_mqtt_since: float | None = field(default=None, init=False)
    _tasmota_off_since: float | None = field(default=None, init=False)
    _ingest_seen_ok: bool = field(default=False, init=False)
    _tasmota_offline_labels: tuple[str, ...] = field(default=(), init=False)
    _started_wall: float = field(default_factory=time.time, init=False)
    _active: dict[str, AlarmHit] = field(default_factory=dict, init=False)
    _last_notify_wall: dict[str, float] = field(default_factory=dict, init=False)
    _notify_count: dict[str, int] = field(default_factory=dict, init=False)
    history: list[dict[str, Any]] = field(default_factory=list, init=False)
    _history_cap: int = field(default=40, init=False)

    def configure(
        self,
        *,
        enabled: bool | None = None,
        desktop_enabled: bool | None = None,
        hold_minutes: float | None = None,
        pv_min_kw: float | None = None,
        charge_idle_kw: float | None = None,
        notify_cooldown_s: float | None = None,
    ) -> None:
        if enabled is not None:
            self.enabled = bool(enabled)
        if desktop_enabled is not None:
            self.desktop_enabled = bool(desktop_enabled)
        if hold_minutes is not None:
            self.hold_minutes = max(1.0, float(hold_minutes))
        if pv_min_kw is not None:
            self.pv_min_kw = max(0.1, float(pv_min_kw))
        if charge_idle_kw is not None:
            self.charge_idle_kw = max(0.0, float(charge_idle_kw))
        if notify_cooldown_s is not None:
            # Retained for settings compat; desktop repeats use notify_backoff_interval_s.
            self.notify_cooldown_s = max(60.0, float(notify_cooldown_s))

    def clear(self) -> None:
        self._below_since = None
        self._sun_waste_since = None
        self._load_eats_pv_since = None
        self._grott_lost_since = None
        self._db_disc_since = None
        self._db_ingest_since = None
        self._inv_lost_since = None
        self._tasmota_mqtt_since = None
        self._tasmota_off_since = None
        self._ingest_seen_ok = False
        self._tasmota_offline_labels = ()
        self._active.clear()
        self._last_notify_wall.clear()
        self._notify_count.clear()

    def _drop_alarm(self, key: str) -> None:
        self._active.pop(key, None)
        self._last_notify_wall.pop(key, None)
        self._notify_count.pop(key, None)

    def evaluate(
        self,
        *,
        soc_pct: float | None,
        pv_kw: float | None,
        charge_kw: float | None,
        discharge_kw: float | None,
        load_kw: float | None,
        grid_import_kw: float | None,
        soc_threshold_pct: float,
        grott_expected: bool = False,
        grott_connected: bool = False,
        grott_fresh: bool = False,
        grott_age_s: float | None = None,
        grott_fresh_s: float = 120.0,
        now_wall: float | None = None,
        db_logging_enabled: bool = False,
        db_connected: bool | None = None,
        db_error: str = "",
        db_engine: str = "",
        db_rows_15m: int | None = None,
        growatt_writing: bool = False,
        tasmota_writing: bool = False,
        inverter_comms_lost: bool = False,
        inverter_comms_reason: str = "",
        tasmota_mqtt_expected: bool = False,
        tasmota_mqtt_connected: bool = False,
        tasmota_offline: list[str] | tuple[str, ...] | None = None,
    ) -> list[AlarmHit]:
        """Return currently active alarms (empty when healthy or disabled)."""
        if not self.enabled:
            self.clear()
            return []

        now = float(now_wall if now_wall is not None else time.time())
        hold_s = self.hold_minutes * 60.0
        thr = float(soc_threshold_pct)

        try:
            soc = float(soc_pct) if soc_pct is not None else None
        except (TypeError, ValueError):
            soc = None
        try:
            pv = float(pv_kw or 0.0)
        except (TypeError, ValueError):
            pv = 0.0
        try:
            chg = float(charge_kw or 0.0)
        except (TypeError, ValueError):
            chg = 0.0
        try:
            dsch = float(discharge_kw or 0.0)
        except (TypeError, ValueError):
            dsch = 0.0
        try:
            load = float(load_kw or 0.0)
        except (TypeError, ValueError):
            load = 0.0
        try:
            gimp = float(grid_import_kw or 0.0)
        except (TypeError, ValueError):
            gimp = 0.0

        # Grott is a continuous local feed. Lost MQTT or a stale snapshot is an
        # alarm even when the last SOC reading is still on screen.
        grott_ok = (not grott_expected) or (bool(grott_connected) and bool(grott_fresh))
        if grott_ok:
            self._grott_lost_since = None
            self._drop_alarm("grott_lost")
        elif self._grott_lost_since is None:
            self._grott_lost_since = now

        if soc is None:
            hits: list[AlarmHit] = []
            grott_hit = self._grott_lost_hit(
                now, grott_connected, grott_age_s, grott_fresh_s,
            )
            if grott_hit is not None:
                hits.append(grott_hit)
            hits.extend(self._pipeline_hits(
                now,
                db_logging_enabled=db_logging_enabled,
                db_connected=db_connected,
                db_error=db_error,
                db_engine=db_engine,
                db_rows_15m=db_rows_15m,
                growatt_writing=growatt_writing,
                tasmota_writing=tasmota_writing,
                inverter_comms_lost=inverter_comms_lost,
                inverter_comms_reason=inverter_comms_reason,
                tasmota_mqtt_expected=tasmota_mqtt_expected,
                tasmota_mqtt_connected=tasmota_mqtt_connected,
                tasmota_offline=tasmota_offline,
            ))
            keep = {h.key for h in hits}
            for k in list(self._active.keys()):
                if k not in keep:
                    self._drop_alarm(k)
            return hits

        # ── Low SOC timer ──────────────────────────────────────────────
        if soc < thr:
            if self._below_since is None:
                self._below_since = now
        else:
            self._below_since = None
            self._drop_alarm("low_soc")

        # ── Sun wasted: real PV *surplus* exists but nothing is charging ──
        # Surplus (PV minus house load) is what can actually reach the
        # battery; PV alone is not enough to call this a fault.
        surplus = pv - load
        sun_waste_cond = (
            soc < thr
            and surplus >= self.pv_min_kw
            and chg < self.charge_idle_kw
        )
        if sun_waste_cond:
            if self._sun_waste_since is None:
                self._sun_waste_since = now
        else:
            self._sun_waste_since = None
            self._drop_alarm("sun_wasted")

        # ── Load is eating all the PV: nothing left to charge with ───────
        # Distinct from the above — here the inverter is behaving, the house
        # is simply consuming everything the array makes.
        load_eats_cond = (
            pv >= self.pv_min_kw
            and surplus < 0.2
            and chg < self.charge_idle_kw
        )
        if load_eats_cond:
            if self._load_eats_pv_since is None:
                self._load_eats_pv_since = now
        else:
            self._load_eats_pv_since = None
            self._drop_alarm("load_eats_pv")

        hits: list[AlarmHit] = []

        if self._below_since is not None and (now - self._below_since) >= hold_s:
            dur_m = (now - self._below_since) / 60.0
            why = _why_low_with_context(soc, thr, pv, chg, dsch, load, gimp, self.pv_min_kw)
            hit = self._raise(
                key="low_soc",
                severity="critical" if soc < max(5.0, thr * 0.5) else "warn",
                title=f"SOC {soc:.0f}% below {thr:.0f}% for {dur_m:.0f} min",
                detail=why,
                since_wall=self._below_since,
                now_wall=now,
            )
            hits.append(hit)

        if self._sun_waste_since is not None and (now - self._sun_waste_since) >= hold_s:
            dur_m = (now - self._sun_waste_since) / 60.0
            detail = (
                f"SOC {soc:.0f}% for {dur_m:.0f} min with ~{surplus:.1f} kW spare PV "
                f"(PV {pv:.2f} kW, load {load:.2f} kW) but charge only {chg:.2f} kW. "
                "Genuine surplus is not reaching the battery — check the inverter "
                "charge/export schedule, forced discharge, and BMS charge limits."
            )
            hit = self._raise(
                key="sun_wasted",
                severity="critical",
                title=f"Spare PV {surplus:.1f} kW not charging (SOC {soc:.0f}%)",
                detail=detail,
                since_wall=self._sun_waste_since,
                now_wall=now,
            )
            hits.append(hit)

        if self._load_eats_pv_since is not None and (now - self._load_eats_pv_since) >= hold_s:
            dur_m = (now - self._load_eats_pv_since) / 60.0
            detail = (
                f"PV {pv:.2f} kW but house load {load:.2f} kW for {dur_m:.0f} min — "
                f"no surplus left to charge (grid import {gimp:.2f} kW, SOC {soc:.0f}%). "
                "The inverter is fine; the house is consuming everything the array "
                "makes. Find and shift the big draw, or the battery cannot refill "
                "from solar today."
            )
            hit = self._raise(
                key="load_eats_pv",
                severity="warn",
                title=f"Load {load:.1f} kW consuming all PV {pv:.1f} kW",
                detail=detail,
                since_wall=self._load_eats_pv_since,
                now_wall=now,
            )
            hits.append(hit)

        grott_hit = self._grott_lost_hit(
            now, grott_connected, grott_age_s, grott_fresh_s,
        )
        if grott_hit is not None:
            hits.append(grott_hit)

        hits.extend(self._pipeline_hits(
            now,
            db_logging_enabled=db_logging_enabled,
            db_connected=db_connected,
            db_error=db_error,
            db_engine=db_engine,
            db_rows_15m=db_rows_15m,
            growatt_writing=growatt_writing,
            tasmota_writing=tasmota_writing,
            inverter_comms_lost=inverter_comms_lost,
            inverter_comms_reason=inverter_comms_reason,
            tasmota_mqtt_expected=tasmota_mqtt_expected,
            tasmota_mqtt_connected=tasmota_mqtt_connected,
            tasmota_offline=tasmota_offline,
        ))

        # Keep only currently active keys in _active
        keep = {h.key for h in hits}
        for k in list(self._active.keys()):
            if k not in keep:
                self._drop_alarm(k)

        return hits

    def _grott_lost_hit(
        self,
        now: float,
        connected: bool,
        age_s: float | None,
        fresh_s: float,
    ) -> AlarmHit | None:
        if self._grott_lost_since is None:
            return None
        # MQTT drop: fire quickly. Never-received payload: wait the Grott
        # fresh window so startup / first heartbeat is not a false alarm.
        # Already-stale snapshot: age has already exceeded fresh_s.
        if not connected:
            hold_s = DEFAULT_GROTT_LOST_HOLD_S
        elif age_s is None:
            hold_s = max(DEFAULT_GROTT_LOST_HOLD_S, float(fresh_s))
        else:
            hold_s = DEFAULT_GROTT_LOST_HOLD_S
        if (now - self._grott_lost_since) < hold_s:
            return None
        dur_s = now - self._grott_lost_since
        if not connected:
            title = "Grott feed lost — MQTT disconnected"
            detail = (
                f"No Grott MQTT connection for {dur_s:.0f}s. "
                "The inverter feed should be continuous — check Grott, EMQX, "
                "and the Shine datalogger."
            )
        else:
            age = float(age_s) if age_s is not None else dur_s
            title = f"Grott feed lost — no telemetry for {age:.0f}s"
            detail = (
                f"MQTT is still connected, but Grott has not published a live "
                f"inverter frame for {age:.0f}s (stale after {float(fresh_s):.0f}s). "
                "The Shine stick often reconnects around the hour and goes quiet "
                "for about 11 minutes while it announces itself to Growatt's "
                "servers — Grott has nothing to republish until the next "
                "status/heartbeat. Hybrid will use the cloud API in that window. "
                "This is not an MQTT broker drop."
            )
        return self._raise(
            key="grott_lost",
            severity="critical",
            title=title,
            detail=detail,
            since_wall=self._grott_lost_since,
            now_wall=now,
        )

    def _pipeline_hits(
        self,
        now: float,
        *,
        db_logging_enabled: bool,
        db_connected: bool | None,
        db_error: str,
        db_engine: str,
        db_rows_15m: int | None,
        growatt_writing: bool,
        tasmota_writing: bool,
        inverter_comms_lost: bool,
        inverter_comms_reason: str,
        tasmota_mqtt_expected: bool,
        tasmota_mqtt_connected: bool,
        tasmota_offline: list[str] | tuple[str, ...] | None,
    ) -> list[AlarmHit]:
        """Database ingest and device-health alarms (independent of SOC)."""
        hits: list[AlarmHit] = []
        eng = (db_engine or "database").strip() or "database"

        # ── Logging enabled but we cannot reach the database ────────────
        if db_logging_enabled and db_connected is False:
            if self._db_disc_since is None:
                self._db_disc_since = now
        else:
            self._db_disc_since = None
            self._drop_alarm("db_disconnected")
        if (
            self._db_disc_since is not None
            and (now - self._db_disc_since) >= DEFAULT_DB_DISCONNECT_HOLD_S
        ):
            dur_s = now - self._db_disc_since
            err = (db_error or "connection failed").strip()
            hits.append(self._raise(
                key="db_disconnected",
                severity="critical",
                title=f"{eng} disconnected — not logging",
                detail=(
                    f"The logging database has been unreachable for {dur_s:.0f}s "
                    f"({err}). Live readings are not being stored. Check host, "
                    "credentials, and that the database is ticked in Setup & Info."
                ),
                since_wall=self._db_disc_since,
                now_wall=now,
            ))

        # ── Connected, but no Growatt/Tasmota rows landing ──────────────
        expect_write = bool(growatt_writing or tasmota_writing)
        if db_connected and db_rows_15m is not None and int(db_rows_15m) > 0:
            self._ingest_seen_ok = True
        ingest_dry = (
            bool(db_logging_enabled)
            and db_connected is True
            and expect_write
            and db_rows_15m is not None
            and int(db_rows_15m) <= 0
        )
        uptime = now - float(self._started_wall or now)
        past_grace = self._ingest_seen_ok or uptime >= DEFAULT_INGEST_STARTUP_GRACE_S
        if ingest_dry and past_grace:
            if self._db_ingest_since is None:
                self._db_ingest_since = now
        else:
            self._db_ingest_since = None
            self._drop_alarm("db_ingest_stale")
        if (
            self._db_ingest_since is not None
            and (now - self._db_ingest_since) >= DEFAULT_DB_INGEST_HOLD_S
        ):
            who = []
            if growatt_writing:
                who.append("Growatt")
            if tasmota_writing:
                who.append("Tasmota")
            src = " and ".join(who) or "live devices"
            hits.append(self._raise(
                key="db_ingest_stale",
                severity="critical",
                title="No data written to the database",
                detail=(
                    (
                        f"{db_error} {src} are live and {eng} is connected, "
                        "so ingest stays at zero until this login can write "
                        "growatt_readings / tasmota_readings."
                    )
                    if db_error
                    else (
                        f"{src} are live, {eng} is connected, but growatt_readings / "
                        f"tasmota_readings have had no new rows in the last 15 minutes. "
                        "The logger may be skipping writes (stale Grott snapshot, "
                        "backoff, or a table error). Check Setup → Database Export "
                        "and the Console for write errors."
                    )
                ),
                since_wall=self._db_ingest_since,
                now_wall=now,
            ))

        # ── Inverter reported offline by Growatt cloud ──────────────────
        if inverter_comms_lost:
            if self._inv_lost_since is None:
                self._inv_lost_since = now
        else:
            self._inv_lost_since = None
            self._drop_alarm("inverter_comms_lost")
        if (
            self._inv_lost_since is not None
            and (now - self._inv_lost_since) >= DEFAULT_INVERTER_LOST_HOLD_S
        ):
            reason = (inverter_comms_reason or "offline").strip()
            dur_m = (now - self._inv_lost_since) / 60.0
            hits.append(self._raise(
                key="inverter_comms_lost",
                severity="critical",
                title=f"Inverter not talking ({reason})",
                detail=(
                    f"Growatt has reported the inverter as {reason} for "
                    f"{dur_m:.0f} min. That is the kit on the roof/in the garage, "
                    "not this app. Check the Shine stick, inverter display, and "
                    "LAN. Grott will also go quiet until the stick publishes again."
                ),
                since_wall=self._inv_lost_since,
                now_wall=now,
            ))

        # ── Tasmota MQTT broker down ────────────────────────────────────
        if tasmota_mqtt_expected and not tasmota_mqtt_connected:
            if self._tasmota_mqtt_since is None:
                self._tasmota_mqtt_since = now
        else:
            self._tasmota_mqtt_since = None
            self._drop_alarm("tasmota_mqtt_lost")
        if (
            self._tasmota_mqtt_since is not None
            and (now - self._tasmota_mqtt_since) >= DEFAULT_TASMOTA_MQTT_HOLD_S
        ):
            dur_s = now - self._tasmota_mqtt_since
            hits.append(self._raise(
                key="tasmota_mqtt_lost",
                severity="critical",
                title="Tasmota MQTT disconnected",
                detail=(
                    f"The Tasmota tab is in MQTT mode but has had no broker "
                    f"connection for {dur_s:.0f}s. Plug / CT readings will freeze. "
                    "Check EMQX host, credentials, and that the devices still "
                    "publish tele/."
                ),
                since_wall=self._tasmota_mqtt_since,
                now_wall=now,
            ))

        # ── Named Tasmota devices gone silent ───────────────────────────
        offline = [str(x).strip() for x in (tasmota_offline or []) if str(x).strip()]
        # If the whole MQTT pipe is down, don't also list every plug.
        if tasmota_mqtt_expected and not tasmota_mqtt_connected:
            offline = []
        if offline:
            self._tasmota_offline_labels = tuple(offline)
            if self._tasmota_off_since is None:
                self._tasmota_off_since = now
        else:
            self._tasmota_off_since = None
            self._tasmota_offline_labels = ()
            self._drop_alarm("tasmota_offline")
        if (
            self._tasmota_off_since is not None
            and (now - self._tasmota_off_since) >= DEFAULT_TASMOTA_STALE_S
        ):
            labels = ", ".join(self._tasmota_offline_labels[:6])
            extra = (
                f" (+{len(self._tasmota_offline_labels) - 6} more)"
                if len(self._tasmota_offline_labels) > 6
                else ""
            )
            n = len(self._tasmota_offline_labels)
            hits.append(self._raise(
                key="tasmota_offline",
                severity="warn" if n < 3 else "critical",
                title=(
                    f"{n} Tasmota device{'s' if n != 1 else ''} not reporting"
                ),
                detail=(
                    f"No telemetry for at least {DEFAULT_TASMOTA_STALE_S / 60.0:.0f} "
                    f"min from: {labels}{extra}. "
                    "Wi-Fi drop, a powered-off plug, or a stuck Tasmota firmware "
                    "are the usual causes — not a chart bug."
                ),
                since_wall=self._tasmota_off_since,
                now_wall=now,
            ))

        return hits

    def _raise(
        self,
        *,
        key: str,
        severity: str,
        title: str,
        detail: str,
        since_wall: float,
        now_wall: float,
    ) -> AlarmHit:
        prev = self._active.get(key)
        just = prev is None
        should_notify = False
        if self.desktop_enabled:
            sent = int(self._notify_count.get(key, 0))
            interval = notify_backoff_interval_s(sent)
            last = self._last_notify_wall.get(key, 0.0)
            due = sent <= 0 or (now_wall - last) >= interval
            if due:
                should_notify = True
                self._last_notify_wall[key] = now_wall
                self._notify_count[key] = sent + 1
        hit = AlarmHit(
            key=key,
            severity=severity,
            title=title,
            detail=detail,
            since_wall=since_wall,
            just_triggered=just,
            should_notify=should_notify,
        )
        self._active[key] = hit
        if just:
            self.history.insert(0, {
                "wall": now_wall,
                "key": key,
                "severity": severity,
                "title": title,
                "detail": detail,
            })
            del self.history[self._history_cap:]
        return hit

    def banner_summary(self, hits: list[AlarmHit] | None = None) -> str:
        active = hits if hits is not None else list(self._active.values())
        if not active:
            return ""
        # Prefer the most severe / most specific first.
        order = {"critical": 0, "warn": 1}
        active = sorted(active, key=lambda h: order.get(h.severity, 9))
        return "  ·  ".join(h.title for h in active)


def _why_low_with_context(soc, thr, pv, chg, dsch, load, gimp, pv_min) -> str:
    parts = [f"Battery at {soc:.0f}% (threshold {thr:.0f}%)."]
    if pv >= pv_min and chg < 0.2:
        parts.append(
            f"PV {pv:.2f} kW is available but charge is {chg:.2f} kW — "
            "sun is not refilling the pack."
        )
    elif pv < pv_min and load > 0.5:
        parts.append(
            f"PV only {pv:.2f} kW vs load {load:.2f} kW — evening/overnight drain."
        )
    if dsch > 0.2:
        parts.append(f"Still discharging at {dsch:.2f} kW.")
    if gimp > 0.2:
        parts.append(f"Grid import {gimp:.2f} kW while SOC is low.")
    if chg > 0.3:
        parts.append(f"Charging at {chg:.2f} kW — recovery in progress.")
    return " ".join(parts)


def scan_history_sun_waste(
    df,
    *,
    pv_min_kw: float = DEFAULT_PV_MIN_KW,
    charge_idle_kw: float = DEFAULT_CHARGE_IDLE_KW,
    min_minutes: float = 30.0,
) -> list[dict[str, Any]]:
    """Windows where real PV *surplus* existed but the battery did not charge.

    Deliberately SOC-free: stored MIX-chart history carries no measured SOC, so
    any SOC-based rule here would test a reconstructed number. Surplus
    (PV − load) and charge power are measured, so they can be trusted.
    """
    if df is None or len(df) < 2:
        return []
    events: list[dict[str, Any]] = []
    in_evt = False
    start = None
    rows: list = []
    for _, row in df.iterrows():
        try:
            pv = float(row.get("pv_kW", 0) or 0)
            chg = float(row.get("charge_kW", 0) or 0)
            load = float(row.get("load_kW", 0) or 0)
        except (TypeError, ValueError, KeyError):
            continue
        cond = (pv - load) >= pv_min_kw and chg < charge_idle_kw
        if cond:
            if not in_evt:
                in_evt = True
                start = row["timestamp"]
                rows = []
            rows.append(row)
        elif in_evt:
            _close_hist_event(events, start, rows, min_minutes)
            in_evt = False
            rows = []
    if in_evt and rows:
        _close_hist_event(events, start, rows, min_minutes)
    return events


def summarise_solar_utilisation(df, *, slot_hours: float = 5.0 / 60.0) -> dict[str, Any]:
    """Per-day PV / load / surplus / charge energy from measured chart rows.

    Answers "was there ever spare sun to charge with, and did it charge?"
    without relying on any SOC value.
    """
    out: dict[str, Any] = {"days": [], "surplus_kwh": 0.0, "charged_kwh": 0.0}
    if df is None or len(df) == 0:
        return out
    try:
        import pandas as _pd
        ts = _pd.to_datetime(df["timestamp"])
    except Exception:
        return out
    pv = df.get("pv_kW")
    load = df.get("load_kW")
    chg = df.get("charge_kW")
    if pv is None or load is None or chg is None:
        return out
    frame = _pd.DataFrame({
        "date": ts.dt.date,
        "pv": _pd.to_numeric(pv, errors="coerce").fillna(0.0),
        "load": _pd.to_numeric(load, errors="coerce").fillna(0.0),
        "chg": _pd.to_numeric(chg, errors="coerce").fillna(0.0),
    })
    frame["surplus"] = (frame["pv"] - frame["load"]).clip(lower=0.0)
    for day, g in frame.groupby("date"):
        night = g  # base load uses the whole day's minimum band
        row = {
            "date": day,
            "pv_kwh": float((g["pv"] * slot_hours).sum()),
            "load_kwh": float((g["load"] * slot_hours).sum()),
            "surplus_kwh": float((g["surplus"] * slot_hours).sum()),
            "charged_kwh": float((g["chg"] * slot_hours).sum()),
            "base_load_kw": float(night["load"].quantile(0.05)),
            "median_load_kw": float(g["load"].median()),
            "peak_load_kw": float(g["load"].max()),
        }
        out["days"].append(row)
        out["surplus_kwh"] += row["surplus_kwh"]
        out["charged_kwh"] += row["charged_kwh"]
    return out


def _close_hist_event(events, start, rows, min_minutes: float) -> None:
    if not rows or start is None:
        return
    end = rows[-1]["timestamp"]
    try:
        dur_min = (end - start).total_seconds() / 60.0
    except Exception:
        return
    if dur_min < min_minutes:
        return
    avg_pv = float(sum(float(r.get("pv_kW", 0) or 0) for r in rows) / len(rows))
    avg_chg = float(sum(float(r.get("charge_kW", 0) or 0) for r in rows) / len(rows))
    avg_load = float(sum(float(r.get("load_kW", 0) or 0) for r in rows) / len(rows))
    min_soc = float(min(float(r["soc_pct"]) for r in rows))
    events.append({
        "start": start,
        "end": end,
        "duration_min": dur_min,
        "min_soc": min_soc,
        "avg_pv_kW": avg_pv,
        "avg_charge_kW": avg_chg,
        "avg_load_kW": avg_load,
    })


__all__ = [
    "AlarmHit",
    "AlarmMonitor",
    "AlarmSpec",
    "ALARM_CATALOGUE",
    "notify_backoff_interval_s",
    "NOTIFY_BACKOFF_STAGES",
    "NOTIFY_BACKOFF_FINAL_S",
    "DEFAULT_HOLD_MINUTES",
    "DEFAULT_PV_MIN_KW",
    "DEFAULT_CHARGE_IDLE_KW",
    "DEFAULT_NOTIFY_COOLDOWN_S",
    "DEFAULT_GROTT_LOST_HOLD_S",
    "scan_history_sun_waste",
    "summarise_solar_utilisation",
]
