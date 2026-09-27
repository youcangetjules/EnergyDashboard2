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


def _span_words(seconds: float) -> str:
    """A short length of time for the Inspect window."""
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        n = int(round(seconds))
        return "1 second" if n == 1 else f"{n} seconds"
    minutes = seconds / 60.0
    n = int(round(minutes))
    if abs(minutes - n) < 0.05:
        return "1 minute" if n == 1 else f"{n} minutes"
    return f"{minutes:.0f} minutes"


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
    """One alarm the monitor can raise. The Alarm defs tab lists these."""

    key: str
    name: str
    level: str
    fires_after: str
    meaning: str


# The smallest pieces an alarm is made of. One palette column each.
ALARM_PIECE_KINDS: tuple[str, ...] = (
    "signal",
    "comparison",
    "threshold",
    "duration",
    "context",
    "outcome",
)
# A sentence needs these four. Threshold and context are optional: "the
# inverter is reported offline" has no limit to compare against.
ALARM_PIECE_REQUIRED: tuple[str, ...] = ("signal", "comparison", "duration", "outcome")


@dataclass(frozen=True)
class AlarmBlocks:
    """One built-in alarm broken into its constituent blocks.

    Dragging those blocks on Alarm defs rebuilds the same sentence. A
    sentence that does not match one of these is a draft: it does not fire.
    """

    key: str
    signal: str
    comparison: str
    threshold: str
    duration: str
    context: str
    outcome: str

    def pieces(self) -> dict[str, str]:
        return {kind: getattr(self, kind) for kind in ALARM_PIECE_KINDS}


def alarm_rule_syntax(pieces: dict[str, str]) -> str:
    """Plain-English syntax built from the blocks in one row.

    ``WHEN signal comparison [threshold] FOR duration [WITH context]
    THEN outcome``. Empty until every required block is in place.
    """
    p = {k: str((pieces or {}).get(k) or "").strip() for k in ALARM_PIECE_KINDS}
    if not all(p[k] for k in ALARM_PIECE_REQUIRED):
        return ""
    head = f"WHEN {p['signal']} {p['comparison']}"
    if p["threshold"]:
        head += f" {p['threshold']}"
    head += f" FOR {p['duration']}"
    if p["context"]:
        head += f" WITH {p['context']}"
    return f"{head} THEN {p['outcome']}"


def alarm_piece_accepted(well_kind: str, piece_kind: str) -> bool:
    """A drop lands only in the well of the same kind."""
    return well_kind in ALARM_PIECE_KINDS and well_kind == piece_kind


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


# Same order as ALARM_CATALOGUE, one row per built-in alarm, each split into
# its smallest pieces. The palette on Alarm defs is built from these columns,
# so a block used by two alarms appears once.
ALARM_BLOCKS: tuple[AlarmBlocks, ...] = (
    AlarmBlocks(
        "low_soc",
        signal="Battery state of charge",
        comparison="stays below",
        threshold="the low-battery line",
        duration="the hold time",
        context="",
        outcome="Warning, or critical if the pack is very low",
    ),
    AlarmBlocks(
        "sun_wasted",
        signal="Spare solar",
        comparison="is at least",
        threshold="the spare-solar minimum",
        duration="the hold time",
        context="the battery is low and barely charging",
        outcome="Critical",
    ),
    AlarmBlocks(
        "load_eats_pv",
        signal="House load",
        comparison="uses almost all of",
        threshold="the solar coming in",
        duration="the hold time",
        context="the battery is barely charging",
        outcome="Warning",
    ),
    AlarmBlocks(
        "grott_lost",
        signal="Grott feed",
        comparison="stops arriving",
        threshold="",
        duration="about 20 seconds",
        context="",
        outcome="Critical",
    ),
    AlarmBlocks(
        "db_disconnected",
        signal="Logging database",
        comparison="cannot be reached",
        threshold="",
        duration="about 60 seconds",
        context="logging is switched on",
        outcome="Critical",
    ),
    AlarmBlocks(
        "db_ingest_stale",
        signal="Database writing",
        comparison="stops",
        threshold="",
        duration="15 minutes",
        context="Growatt or Tasmota looks live",
        outcome="Critical",
    ),
    AlarmBlocks(
        "inverter_comms_lost",
        signal="Inverter",
        comparison="is reported offline",
        threshold="",
        duration="about 2 minutes",
        context="",
        outcome="Critical",
    ),
    AlarmBlocks(
        "tasmota_mqtt_lost",
        signal="Tasmota MQTT",
        comparison="drops",
        threshold="",
        duration="about 30 seconds",
        context="",
        outcome="Critical",
    ),
    AlarmBlocks(
        "tasmota_offline",
        signal="Tasmota device",
        comparison="goes silent",
        threshold="",
        duration="about 8 minutes",
        context="MQTT is still up",
        outcome="Warning, or critical if three or more",
    ),
)

# Blocks worth offering that no built-in alarm uses on its own. They let a
# householder write a sentence of their own; it stays a draft either way.
ALARM_EXTRA_PIECES: dict[str, tuple[str, ...]] = {
    "signal": (
        "string A voltage",
        "string B voltage",
        "PV forecast",
        "PVOutput.org",
        "Wonderwatt",
        "Octopus",
    ),
    "comparison": ("has a differential of", "stays above", "stops"),
    "threshold": ("Volts",),
    "duration": (),
    "context": (
        "it is daytime",
        "it is night-time",
        "the battery is charging",
        "the battery is discharging",
        "the grid is importing",
        "the inverter is online",
        "Agile is in a cheap slot",
    ),
    "outcome": ("send SMS", "create a desktop alert", "Warning", "Critical"),
}

# What kind of thing each signal is about. Shown in faint grey under the
# signal on the palette, and used to judge whether an extra condition has any
# bearing on the signal.
SIGNAL_ALARM_TYPE: dict[str, str] = {
    "Inverter": "Hardware",
    "Tasmota device": "Hardware",
    "string A voltage": "Hardware",
    "string B voltage": "Hardware",
    "Grott feed": "Data flow",
    "Tasmota MQTT": "Data flow",
    "Logging database": "Data ingestion",
    "Database writing": "Data ingestion",
    "Battery state of charge": "Energy",
    "Spare solar": "Energy",
    "House load": "Energy",
    "PV forecast": "Forecast",
    "Wonderwatt": "Forecast",
    "PVOutput.org": "External service",
    "Octopus": "External service",
}

_ENERGY = ("Battery state of charge", "Spare solar", "House load")
_STRINGS = ("string A voltage", "string B voltage")
# Signals each extra condition can sensibly qualify. "MQTT is still up" says
# something about a feed or a plug; it says nothing about a string voltage.
CONTEXT_SIGNALS: dict[str, tuple[str, ...]] = {
    "the battery is low and barely charging": _ENERGY,
    "the battery is barely charging": _ENERGY,
    "logging is switched on": ("Logging database", "Database writing"),
    "Growatt or Tasmota looks live": ("Logging database", "Database writing"),
    "MQTT is still up": ("Grott feed", "Tasmota MQTT", "Tasmota device"),
    "it is daytime": _ENERGY + _STRINGS + ("PV forecast", "Wonderwatt", "PVOutput.org"),
    "it is night-time": ("Battery state of charge", "House load", "Octopus"),
    "the battery is charging": _ENERGY + _STRINGS,
    "the battery is discharging": ("Battery state of charge", "House load"),
    "the grid is importing": _ENERGY + ("Octopus",),
    "the inverter is online": _ENERGY + _STRINGS + ("Grott feed", "Database writing"),
    "Agile is in a cheap slot": ("Battery state of charge", "House load", "Octopus"),
}


def signal_alarm_type(text: str) -> str:
    return SIGNAL_ALARM_TYPE.get(str(text or "").strip(), "")


def alarm_logic_note(pieces: dict[str, str]) -> str:
    """Why a complete, unit-correct sentence still looks like odd logic.

    Empty when the extra condition bears on at least one of the signals, or
    there is no extra condition. A built-in rule never gets a note.
    """
    if alarm_blocks_key(pieces):
        return ""
    context = str((pieces or {}).get("context") or "").strip()
    if not context:
        return ""
    allowed = CONTEXT_SIGNALS.get(context)
    if allowed is None:
        return ""
    signals, _join = split_joined_pieces(
        str((pieces or {}).get("signal") or ""), set(alarm_palette("signal")),
    )
    signals = [s for s in signals if s]
    if not signals or any(s in allowed for s in signals):
        return ""
    if len(signals) == 1:
        about = signals[0]
    else:
        about = ", ".join(signals[:-1]) + " or " + signals[-1]
    return (
        f"“{context}” has no bearing on {about}, so that condition adds "
        "nothing to the alarm. Please check the logic."
    )

# These choose how a rule tells you. They are not a severity, so a built-in
# rule can keep its warning or critical wording and still name a channel.
ACTION_OUTCOMES = ("send SMS", "create a desktop alert")


# Comparisons are listed by family, not by which alarm used them first.
# "stays below" and "stays above" sit together; the rest follow the same idea.
_COMPARISON_ORDER = (
    "stays below",
    "stays above",
    "is at least",
    "has a differential of",
    "uses almost all of",
    "stops arriving",
    "stops",
    "drops",
    "goes silent",
    "cannot be reached",
    "is reported offline",
)


# How long a condition must stay true. The palette offers these, in this order.
# "is seen" means no wait. "custom value" is the list entry; a typed time is
# stored as "45 seconds" or "7 minutes". "is flapping" is the list entry; the
# rule stores the sentence from the dialogue (see FlapSpec).
DURATION_CHOICES: tuple[str, ...] = (
    "is seen",
    "10 seconds",
    "30 seconds",
    "1 minute",
    "2 minutes",
    "5 minutes",
    "10 minutes",
    "30 minutes",
    "custom value",
    "is flapping",
)
FLAP_CHOICE = "is flapping"


@dataclass(frozen=True)
class FlapSpec:
    """How often a line must be crossed before the alarm sounds.

    ``times`` crossings inside ``window_min`` minutes. A crossing counts only
    after the condition has stayed true for ``dwell_s`` seconds.
    """

    times: int
    window_min: int
    dwell_s: int

    def phrase(self) -> str:
        return (
            f"Seen {_count_word(self.times, 'time', 'times')} in "
            f"{_count_word(self.window_min, 'minute', 'minutes')} where the "
            "trigger threshold is exceeded for "
            f"{_count_word(self.dwell_s, 'second', 'seconds')}"
        )
_DURATION_SECONDS = {
    "is seen": 0.0,
    "10 seconds": 10.0,
    "30 seconds": 30.0,
    "1 minute": 60.0,
    "2 minutes": 120.0,
    "5 minutes": 300.0,
    "10 minutes": 600.0,
    "30 minutes": 1800.0,
}


def duration_seconds(text: str) -> float | None:
    """Seconds a How long block stands for, or None if it is not a length of time.

    The old catalogue phrases ("the hold time", "about 20 seconds") are not
    lengths here — those alarms keep the wait set in Setup.
    """
    raw = (text or "").strip().lower()
    if raw in _DURATION_SECONDS:
        return _DURATION_SECONDS[raw]
    import re
    seconds = re.fullmatch(r"(\d+)\s+seconds?", raw)
    if seconds:
        return float(seconds.group(1))
    minutes = re.fullmatch(r"(\d+)\s+minutes?", raw)
    if minutes:
        return float(minutes.group(1)) * 60.0
    return None


def _count_word(n: int, one: str, many: str) -> str:
    return f"{int(n)} {one if int(n) == 1 else many}"


def parse_flap(text: str) -> FlapSpec | None:
    """The Is flapping sentence, or None when this How long is a plain wait."""
    import re
    match = re.fullmatch(
        r"seen (\d+) times? in (\d+) minutes? where the trigger threshold "
        r"is exceeded for (\d+) seconds?",
        (text or "").strip(),
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    times, window, dwell = (int(match.group(i)) for i in (1, 2, 3))
    if times < 1 or window < 1 or dwell < 0:
        return None
    return FlapSpec(times=times, window_min=window, dwell_s=dwell)


def format_duration(seconds: float) -> str:
    """Chip text for a typed length of time. Zero is "is seen"."""
    try:
        whole = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "is seen"
    if whole <= 0:
        return "is seen"
    if whole % 60 == 0:
        minutes = whole // 60
        return "1 minute" if minutes == 1 else f"{minutes} minutes"
    return "1 second" if whole == 1 else f"{whole} seconds"


def alarm_palette(kind: str) -> tuple[str, ...]:
    """Every block of one kind, without repeats.

    Comparisons use ``_COMPARISON_ORDER``. Anything else stays in first-used
    order, then the extra pieces.
    """
    if kind not in ALARM_PIECE_KINDS:
        return ()
    if kind == "duration":
        return DURATION_CHOICES
    out: list[str] = []
    for row in ALARM_BLOCKS:
        text = getattr(row, kind)
        if text and text not in out:
            out.append(text)
    for text in ALARM_EXTRA_PIECES.get(kind, ()):
        if text not in out:
            out.append(text)
    if kind != "comparison":
        return tuple(out)
    rank = {text: index for index, text in enumerate(_COMPARISON_ORDER)}
    tail = len(_COMPARISON_ORDER)
    return tuple(sorted(out, key=lambda text: (rank.get(text, tail), out.index(text))))


def split_joined_pieces(text: str, known: set[str]) -> tuple[list[str], str]:
    """Split 'A and B' or 'A or B' when every part is a real block.

    A single known phrase stays whole, including ones that happen to contain
    the word "or" (such as "Warning, or critical if the pack is very low").
    """
    text = (text or "").strip()
    if not text:
        return [], "and"
    if text in known:
        return [text], "and"
    for op in (" or ", " and "):
        parts = [part.strip() for part in text.split(op) if part.strip()]
        if len(parts) > 1 and all(part in known for part in parts):
            return parts, op.strip()
    return [text], "and"


def severity_outcome(text: str) -> str:
    """Outcome wording used to match a built-in rule, without the channels."""
    parts, _join = split_joined_pieces(text, set(alarm_palette("outcome")))
    kept = [part for part in parts if part not in ACTION_OUTCOMES]
    if len(kept) == 1:
        return kept[0]
    if len(kept) > 1:
        return " and ".join(kept)
    if text and text not in ACTION_OUTCOMES:
        return text
    return ""


def outcome_channels(text: str) -> set[str] | None:
    """Channels named on a rule, or None when the rule leaves that to Setup.

    ``sms`` and ``desktop`` are the only names. None means both Setup
    choices still apply.
    """
    parts, _join = split_joined_pieces(text, set(alarm_palette("outcome")))
    chosen: set[str] = set()
    if "send SMS" in parts:
        chosen.add("sms")
    if "create a desktop alert" in parts:
        chosen.add("desktop")
    return chosen or None


def rule_channel_overrides(rows: Any) -> dict[str, set[str]]:
    """Per-alarm channels taken from saved Alarm defs rows.

    Only a row that still matches a built-in alarm counts, and only when it
    names a channel. Anything else leaves the Setup choices alone.
    """
    out: dict[str, set[str]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        pieces = {k: str(row.get(k) or "") for k in ALARM_PIECE_KINDS}
        key = alarm_blocks_key(pieces)
        if not key:
            continue
        channels = outcome_channels(pieces["outcome"])
        if channels:
            out[key] = channels
    return out


def signal_builtin_keys(signal: str) -> tuple[str, ...]:
    """Built-in alarm keys that watch this signal, if any."""
    return tuple(row.key for row in ALARM_BLOCKS if row.signal == signal)


def signal_combo(text: str) -> tuple[list[str], str] | None:
    """Two or more real signals, and whether they combine with and or or."""
    parts, join = split_joined_pieces(text, set(alarm_palette("signal")))
    if len(parts) < 2:
        return None
    return parts, join


def combo_matches(text: str, active_keys: set[str]) -> bool:
    """True when this signal phrase's AND/OR is met by alarms already sounding.

    A signal with no built-in alarm (string voltage, for example) is never
    sounding. AND needs every signal's alarm. OR needs any one of them.
    """
    combo = signal_combo(text)
    if combo is None:
        return False
    parts, join = combo
    flags = []
    for part in parts:
        keys = signal_builtin_keys(part)
        flags.append(bool(keys) and any(key in active_keys for key in keys))
    if join == "or":
        return any(flags)
    return all(flags)


# What each block is measured in. A rule can only compare like with like:
# a percentage with a percentage, power with power, volts with volts.
# "status" is a feed or a device, not a number.
_SIGNAL_UNIT = {
    "Battery state of charge": "percent",
    "Spare solar": "power",
    "House load": "power",
    "string A voltage": "volts",
    "string B voltage": "volts",
    "PV forecast": "power",
    "PVOutput.org": "power",
    "Wonderwatt": "power",
    "Octopus": "energy",
    "Grott feed": "status",
    "Logging database": "status",
    "Database writing": "status",
    "Inverter": "status",
    "Tasmota MQTT": "status",
    "Tasmota device": "status",
}
_THRESHOLD_UNIT = {
    "the low-battery line": "percent",
    "the spare-solar minimum": "power",
    "the solar coming in": "power",
    "Volts": "volts",
}
_UNIT_WORDS = {
    "percent": "a percentage",
    "power": "power, in kW",
    "volts": "volts",
    "status": "a feed, not a number",
    "energy": "energy, in kWh",
}
_MEASURED_COMPARISONS = frozenset({
    "stays below",
    "stays above",
    "is at least",
    "has a differential of",
    "uses almost all of",
})
_STATUS_COMPARISONS = frozenset({
    "stops arriving",
    "stops",
    "drops",
    "goes silent",
    "cannot be reached",
    "is reported offline",
})


def _unit_list(pairs: list[tuple[str, str]]) -> str:
    bits = [f"{name} is {_UNIT_WORDS[unit]}" for name, unit in pairs]
    if len(bits) == 1:
        return bits[0]
    if len(bits) == 2:
        return f"{bits[0]}, and {bits[1]}"
    return ", ".join(bits[:-1]) + f", and {bits[-1]}"


def alarm_unit_problem(pieces: dict[str, str]) -> str:
    """Why this sentence mixes units, or "" when the units agree.

    Battery state of charge is a percentage. Spare solar is power in kW.
    Putting both on one comparison, or comparing either to a limit in the
    other unit, is not a valid rule.
    """
    p = {k: str((pieces or {}).get(k) or "").strip() for k in ALARM_PIECE_KINDS}
    if not all(p[k] for k in ALARM_PIECE_REQUIRED):
        return ""
    parts, _join = split_joined_pieces(p["signal"], set(alarm_palette("signal")))
    if not parts:
        return ""
    paired: list[tuple[str, str]] = []
    for part in parts:
        unit = _SIGNAL_UNIT.get(part)
        if not unit:
            return ""
        paired.append((part, unit))
    units = {unit for _name, unit in paired}
    if len(units) > 1:
        return (
            f"{_unit_list(paired)}. Those units don't match, "
            "so they cannot share one comparison."
        )
    signal_unit = paired[0][1]
    comparison = p["comparison"]
    threshold = p["threshold"]
    threshold_unit = _THRESHOLD_UNIT.get(threshold, "") if threshold else ""
    if comparison in _MEASURED_COMPARISONS:
        if signal_unit == "status":
            return (
                f"{comparison.capitalize()} compares a measurement, "
                f"but {paired[0][0]} is a feed, not a number."
            )
        if not threshold:
            return (
                f"{comparison.capitalize()} needs a limit in the same unit "
                f"({_UNIT_WORDS[signal_unit]})."
            )
        if threshold_unit and threshold_unit != signal_unit:
            return (
                f"{_unit_list(paired)}, but {threshold} is {_UNIT_WORDS[threshold_unit]}. "
                "The limit has to be in the same unit as the signal."
            )
        return ""
    if comparison in _STATUS_COMPARISONS:
        if signal_unit != "status":
            return (
                f"{comparison.capitalize()} is about a feed going quiet, "
                f"but {paired[0][0]} is {_UNIT_WORDS[signal_unit]}."
            )
        if threshold_unit:
            return (
                f"{comparison.capitalize()} does not take "
                f"a limit that is {_UNIT_WORDS[threshold_unit]}."
            )
    return ""


def alarm_blocks_key(pieces: dict[str, str]) -> str | None:
    """Key of the built-in alarm these blocks match, or None for a draft.

    How long may be the original phrase, or one of the duration choices
    (including a typed time). The rest of the sentence still has to match.
    """
    p = {k: str((pieces or {}).get(k) or "").strip() for k in ALARM_PIECE_KINDS}
    p["outcome"] = severity_outcome(p["outcome"])
    for row in ALARM_BLOCKS:
        canon = row.pieces()
        if any(
            p[k] != canon[k]
            for k in ALARM_PIECE_KINDS
            if k not in ("duration", "outcome")
        ):
            continue
        if severity_outcome(canon["outcome"]) != p["outcome"]:
            continue
        if (
            p["duration"] == canon["duration"]
            or duration_seconds(p["duration"]) is not None
            or parse_flap(p["duration"]) is not None
        ):
            return row.key
    return None


def alarm_band(key: str, severity: str) -> str:
    """Tray band for an alarm that is already sounding.

    Critical is the monitor's critical grade: the pack is very low, the
    inverter is offline, a feed has died, or three or more plugs are silent.
    Major is a warning that still needs a look (the pack is under the low
    line, or one or two plugs have gone quiet). Minor is the house using
    almost all the solar — the inverter is behaving, so it is a note.
    """
    if str(severity or "").strip() == "critical":
        return "critical"
    if str(key or "").strip() == "load_eats_pv":
        return "minor"
    return "major"


@dataclass
class AlarmHit:
    key: str
    severity: str  # "warn" | "critical"
    title: str
    detail: str
    since_wall: float
    just_triggered: bool = False
    should_notify: bool = False


@dataclass(frozen=True)
class AlarmPart:
    """One clause of a built-in alarm, as the last live check saw it.

    ``on`` is whether that clause is true. ``result`` marks the whole alarm
    (sounding or not) rather than a single clause.
    """

    label: str
    on: bool
    detail: str
    result: bool = False


@dataclass
class AlarmMonitor:
    """Track rising/falling edges for low-SOC and sun-wasted conditions."""

    hold_minutes: float = DEFAULT_HOLD_MINUTES
    pv_min_kw: float = DEFAULT_PV_MIN_KW
    charge_idle_kw: float = DEFAULT_CHARGE_IDLE_KW
    notify_cooldown_s: float = DEFAULT_NOTIFY_COOLDOWN_S
    enabled: bool = True
    desktop_enabled: bool = True
    # Per-alarm waits. Alarm defs edits these; the catalogue phrase stays put
    # so a built-in rule still matches after the number changes.
    grott_lost_hold_s: float = DEFAULT_GROTT_LOST_HOLD_S
    db_disconnect_hold_s: float = DEFAULT_DB_DISCONNECT_HOLD_S
    db_ingest_hold_s: float = DEFAULT_DB_INGEST_HOLD_S
    inverter_lost_hold_s: float = DEFAULT_INVERTER_LOST_HOLD_S
    tasmota_mqtt_hold_s: float = DEFAULT_TASMOTA_MQTT_HOLD_S
    tasmota_stale_s: float = DEFAULT_TASMOTA_STALE_S

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
    _rule_hold_s: dict[str, float] = field(default_factory=dict, init=False)
    _rule_flap: dict[str, FlapSpec] = field(default_factory=dict, init=False)
    _flap_on: dict[str, float] = field(default_factory=dict, init=False)
    _flap_counted: dict[str, bool] = field(default_factory=dict, init=False)
    _flap_hits: dict[str, list[float]] = field(default_factory=dict, init=False)
    _inspection: dict[str, tuple[AlarmPart, ...]] = field(default_factory=dict, init=False)
    _inspection_at: float | None = field(default=None, init=False)

    def set_rule_holds(self, holds: dict[str, float] | None) -> None:
        """Waits chosen on Alarm defs. Missing keys keep the Setup wait."""
        cleaned: dict[str, float] = {}
        for key, seconds in (holds or {}).items():
            try:
                cleaned[str(key)] = max(0.0, float(seconds))
            except (TypeError, ValueError):
                continue
        self._rule_hold_s = cleaned

    def set_rule_flaps(self, flaps: dict[str, FlapSpec] | None) -> None:
        """Is flapping on a built-in rule replaces that alarm's plain wait."""
        cleaned: dict[str, FlapSpec] = {}
        for key, spec in (flaps or {}).items():
            if isinstance(spec, FlapSpec):
                cleaned[str(key)] = spec
        removed = set(self._rule_flap) - set(cleaned)
        self._rule_flap = cleaned
        for key in removed:
            self._flap_on.pop(key, None)
            self._flap_counted.pop(key, None)
            self._flap_hits.pop(key, None)

    def _end_stretch(self, key: str) -> None:
        """The condition just went false. A flap keeps its recent crossings."""
        if key not in self._rule_flap:
            self._drop_alarm(key)

    def _note_flap(self, key: str, cond: bool, now: float) -> None:
        """Count one crossing once it has stayed over the line long enough."""
        spec = self._rule_flap.get(key)
        if spec is None:
            self._flap_on.pop(key, None)
            self._flap_counted.pop(key, None)
            self._flap_hits.pop(key, None)
            return
        if cond:
            started = self._flap_on.get(key)
            if started is None:
                self._flap_on[key] = now
                self._flap_counted[key] = False
                started = now
            if (
                not self._flap_counted.get(key)
                and (now - started) >= float(spec.dwell_s)
            ):
                self._flap_hits.setdefault(key, []).append(now)
                self._flap_counted[key] = True
        else:
            self._flap_on.pop(key, None)
            self._flap_counted[key] = False
        window = float(spec.window_min) * 60.0
        hits = [t for t in self._flap_hits.get(key, []) if (now - t) <= window]
        if hits:
            self._flap_hits[key] = hits
        else:
            self._flap_hits.pop(key, None)

    def _fires(self, key: str, since: float | None, now: float, hold_s: float) -> bool:
        spec = self._rule_flap.get(key)
        if spec is not None:
            return len(self._flap_hits.get(key, ())) >= spec.times
        return since is not None and (now - float(since)) >= float(hold_s)

    def _mark_since(self, key: str, since: float | None) -> float:
        if key in self._rule_flap:
            hits = self._flap_hits.get(key) or []
            if hits:
                return float(hits[0])
        return float(since if since is not None else 0.0)

    def _wait_s(self, key: str, default: float) -> float:
        if key in self._rule_hold_s:
            return self._rule_hold_s[key]
        return float(default)

    def configure(
        self,
        *,
        enabled: bool | None = None,
        desktop_enabled: bool | None = None,
        hold_minutes: float | None = None,
        pv_min_kw: float | None = None,
        charge_idle_kw: float | None = None,
        notify_cooldown_s: float | None = None,
        grott_lost_hold_s: float | None = None,
        db_disconnect_hold_s: float | None = None,
        db_ingest_hold_s: float | None = None,
        inverter_lost_hold_s: float | None = None,
        tasmota_mqtt_hold_s: float | None = None,
        tasmota_stale_s: float | None = None,
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
        if grott_lost_hold_s is not None:
            self.grott_lost_hold_s = min(600.0, max(5.0, float(grott_lost_hold_s)))
        if db_disconnect_hold_s is not None:
            self.db_disconnect_hold_s = min(600.0, max(10.0, float(db_disconnect_hold_s)))
        if db_ingest_hold_s is not None:
            self.db_ingest_hold_s = min(1800.0, max(30.0, float(db_ingest_hold_s)))
        if inverter_lost_hold_s is not None:
            self.inverter_lost_hold_s = min(1800.0, max(60.0, float(inverter_lost_hold_s)))
        if tasmota_mqtt_hold_s is not None:
            self.tasmota_mqtt_hold_s = min(600.0, max(5.0, float(tasmota_mqtt_hold_s)))
        if tasmota_stale_s is not None:
            self.tasmota_stale_s = min(3600.0, max(60.0, float(tasmota_stale_s)))

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
        self._flap_on.clear()
        self._flap_counted.clear()
        self._flap_hits.clear()
        self._inspection = {}
        self._inspection_at = None
        self._active.clear()
        self._last_notify_wall.clear()
        self._notify_count.clear()

    def _drop_alarm(self, key: str) -> None:
        self._active.pop(key, None)
        self._last_notify_wall.pop(key, None)
        self._notify_count.pop(key, None)

    def custom_notify_due(self, key: str, now_wall: float) -> bool:
        """Same repeat spacing as a built-in alarm, for a combined rule."""
        sent = int(self._notify_count.get(key, 0))
        interval = notify_backoff_interval_s(sent)
        last = float(self._last_notify_wall.get(key, 0.0))
        if sent > 0 and (float(now_wall) - last) < interval:
            return False
        self._last_notify_wall[key] = float(now_wall)
        self._notify_count[key] = sent + 1
        return True

    def custom_notify_clear(self, key: str) -> None:
        """Forget a combined rule once it is no longer true, so the next time is fresh."""
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
        low_hold = self._wait_s("low_soc", self.hold_minutes * 60.0)
        sun_hold = self._wait_s("sun_wasted", self.hold_minutes * 60.0)
        load_hold = self._wait_s("load_eats_pv", self.hold_minutes * 60.0)
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
            self._end_stretch("grott_lost")
        elif self._grott_lost_since is None:
            self._grott_lost_since = now
        self._note_flap("grott_lost", not grott_ok, now)

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
            self._remember_inspection(
                now, soc=soc, thr=thr, pv=pv, chg=chg, load=load, gimp=gimp,
                grott_expected=grott_expected, grott_ok=grott_ok,
                grott_connected=grott_connected, grott_age_s=grott_age_s,
                grott_fresh_s=grott_fresh_s,
                db_logging_enabled=db_logging_enabled, db_connected=db_connected,
                db_rows_15m=db_rows_15m, growatt_writing=growatt_writing,
                tasmota_writing=tasmota_writing,
                inverter_comms_lost=inverter_comms_lost,
                inverter_comms_reason=inverter_comms_reason,
                tasmota_mqtt_expected=tasmota_mqtt_expected,
                tasmota_mqtt_connected=tasmota_mqtt_connected,
                tasmota_offline=tasmota_offline,
            )
            return hits

        # ── Low SOC timer ──────────────────────────────────────────────
        low = soc < thr
        if low:
            if self._below_since is None:
                self._below_since = now
        else:
            self._below_since = None
            self._end_stretch("low_soc")
        self._note_flap("low_soc", low, now)

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
            self._end_stretch("sun_wasted")
        self._note_flap("sun_wasted", sun_waste_cond, now)

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
            self._end_stretch("load_eats_pv")
        self._note_flap("load_eats_pv", load_eats_cond, now)

        hits: list[AlarmHit] = []

        if self._fires("low_soc", self._below_since, now, low_hold):
            dur_m = (now - self._mark_since("low_soc", self._below_since)) / 60.0
            why = _why_low_with_context(soc, thr, pv, chg, dsch, load, gimp, self.pv_min_kw)
            hit = self._raise(
                key="low_soc",
                severity="critical" if soc < max(5.0, thr * 0.5) else "warn",
                title=f"SOC {soc:.0f}% below {thr:.0f}% for {dur_m:.0f} min",
                detail=why,
                since_wall=self._mark_since("low_soc", self._below_since),
                now_wall=now,
            )
            hits.append(hit)

        if self._fires("sun_wasted", self._sun_waste_since, now, sun_hold):
            dur_m = (now - self._mark_since("sun_wasted", self._sun_waste_since)) / 60.0
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
                since_wall=self._mark_since("sun_wasted", self._sun_waste_since),
                now_wall=now,
            )
            hits.append(hit)

        if self._fires("load_eats_pv", self._load_eats_pv_since, now, load_hold):
            dur_m = (now - self._mark_since("load_eats_pv", self._load_eats_pv_since)) / 60.0
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
                since_wall=self._mark_since("load_eats_pv", self._load_eats_pv_since),
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
        self._remember_inspection(
            now, soc=soc, thr=thr, pv=pv, chg=chg, load=load, gimp=gimp,
            grott_expected=grott_expected, grott_ok=grott_ok,
            grott_connected=grott_connected, grott_age_s=grott_age_s,
            grott_fresh_s=grott_fresh_s,
            db_logging_enabled=db_logging_enabled, db_connected=db_connected,
            db_rows_15m=db_rows_15m, growatt_writing=growatt_writing,
            tasmota_writing=tasmota_writing,
            inverter_comms_lost=inverter_comms_lost,
            inverter_comms_reason=inverter_comms_reason,
            tasmota_mqtt_expected=tasmota_mqtt_expected,
            tasmota_mqtt_connected=tasmota_mqtt_connected,
            tasmota_offline=tasmota_offline,
        )
        return hits

    def rule_inspection(self, key: str) -> tuple[AlarmPart, ...] | None:
        """Clauses from the last live check.

        None until ``evaluate`` has run. An empty tuple means that check did
        not cover this alarm.
        """
        if self._inspection_at is None:
            return None
        return self._inspection.get(str(key), ())

    def inspection_at(self) -> float | None:
        """Wall clock of the last live check, or None if it has not run."""
        return self._inspection_at

    def _grott_hold_s(self, connected: bool, age_s: float | None, fresh_s: float) -> float:
        chosen = self._rule_hold_s.get("grott_lost")
        if chosen is not None:
            return chosen
        if not connected:
            return self.grott_lost_hold_s
        if age_s is None:
            return max(self.grott_lost_hold_s, float(fresh_s))
        return self.grott_lost_hold_s

    def _duration_part(
        self,
        key: str,
        cond: bool,
        since: float | None,
        now: float,
        hold_s: float,
    ) -> AlarmPart:
        """Whether the wait, or the flapping count, has been met."""
        spec = self._rule_flap.get(key)
        if spec is not None:
            n = len(self._flap_hits.get(key, ()))
            detail = (
                f"{n} of {spec.times} crossings in the last "
                f"{spec.window_min:g} minutes. A crossing counts after "
                f"{spec.dwell_s:g} seconds."
            )
            started = self._flap_on.get(key)
            if cond and started is not None and not self._flap_counted.get(key):
                detail += f" The latest one has lasted {_span_words(now - started)}."
            return AlarmPart("How long", n >= int(spec.times), detail)
        if not cond or since is None:
            return AlarmPart(
                "How long",
                False,
                "Not every condition is true, so the wait has not started.",
            )
        held = max(0.0, now - float(since))
        need = max(0.0, float(hold_s))
        if need <= 0:
            return AlarmPart("How long", True, "No wait. It counts as soon as it is seen.")
        if held >= need:
            detail = f"True for {_span_words(held)}. The wait is {_span_words(need)}."
        else:
            detail = f"True for {_span_words(held)} of {_span_words(need)}."
        return AlarmPart("How long", held >= need, detail)

    def _remember_inspection(self, now: float, **fact: Any) -> None:
        """Store each built-in alarm's clauses from the check that just ran.

        The comparisons are the same ones ``evaluate`` uses to start a wait
        and to sound the alarm. Inspect reads this; it does not guess.
        """
        soc = fact["soc"]
        thr = float(fact["thr"])
        pv = float(fact["pv"])
        chg = float(fact["chg"])
        load = float(fact["load"])
        surplus = pv - load
        idle = float(self.charge_idle_kw)
        pv_min = float(self.pv_min_kw)
        known = soc is not None
        low = bool(known and float(soc) < thr)
        low_hold = self._wait_s("low_soc", self.hold_minutes * 60.0)
        sun = bool(known and low and surplus >= pv_min and chg < idle)
        sun_hold = self._wait_s("sun_wasted", self.hold_minutes * 60.0)
        eats = bool(known and pv >= pv_min and surplus < 0.2 and chg < idle)
        load_hold = self._wait_s("load_eats_pv", self.hold_minutes * 60.0)

        def result(key: str, on: bool) -> AlarmPart:
            if on:
                return AlarmPart("The alarm", True, "It is sounding.", result=True)
            return AlarmPart("The alarm", False, "It is not sounding.", result=True)

        parts: dict[str, tuple[AlarmPart, ...]] = {}
        if not known:
            quiet = "No state of charge on the last check, so this is not being judged."
            for key, label in (
                ("low_soc", "Battery state of charge stays below the low-battery line"),
                ("sun_wasted", "Spare solar is at least the spare-solar minimum"),
                ("load_eats_pv", "House load uses almost all of the solar coming in"),
            ):
                parts[key] = (
                    AlarmPart(label, False, quiet),
                    AlarmPart("How long", False, quiet),
                    result(key, False),
                )
        else:
            soc_f = float(soc)
            parts["low_soc"] = (
                AlarmPart(
                    "Battery state of charge stays below the low-battery line",
                    low,
                    f"State of charge is {soc_f:.0f}%. The line is {thr:.0f}%.",
                ),
                self._duration_part("low_soc", low, self._below_since, now, low_hold),
                result("low_soc", self._fires("low_soc", self._below_since, now, low_hold)),
            )
            spare_on = surplus >= pv_min
            battery_low = soc_f < thr
            barely = chg < idle
            parts["sun_wasted"] = (
                AlarmPart(
                    "Spare solar is at least the spare-solar minimum",
                    spare_on,
                    (
                        f"Spare solar is {surplus:.2f} kW "
                        f"(solar {pv:.2f} kW, house {load:.2f} kW). "
                        f"The minimum is {pv_min:.2f} kW."
                    ),
                ),
                AlarmPart(
                    "The battery is low",
                    battery_low,
                    f"State of charge is {soc_f:.0f}%. The line is {thr:.0f}%.",
                ),
                AlarmPart(
                    "The battery is barely charging",
                    barely,
                    f"Charge is {chg:.2f} kW. Barely charging means under {idle:.2f} kW.",
                ),
                self._duration_part("sun_wasted", sun, self._sun_waste_since, now, sun_hold),
                result("sun_wasted", self._fires("sun_wasted", self._sun_waste_since, now, sun_hold)),
            )
            house_on = pv >= pv_min and surplus < 0.2
            parts["load_eats_pv"] = (
                AlarmPart(
                    "House load uses almost all of the solar coming in",
                    house_on,
                    (
                        f"Solar is {pv:.2f} kW and the house is {load:.2f} kW, "
                        f"leaving {surplus:.2f} kW. Almost all means under 0.2 kW left, "
                        f"with solar at least {pv_min:.2f} kW."
                    ),
                ),
                AlarmPart(
                    "The battery is barely charging",
                    barely,
                    f"Charge is {chg:.2f} kW. Barely charging means under {idle:.2f} kW.",
                ),
                self._duration_part(
                    "load_eats_pv", eats, self._load_eats_pv_since, now, load_hold,
                ),
                result(
                    "load_eats_pv",
                    self._fires("load_eats_pv", self._load_eats_pv_since, now, load_hold),
                ),
            )

        grott_expected = bool(fact["grott_expected"])
        grott_bad = bool(grott_expected and not fact["grott_ok"])
        if not grott_expected:
            grott_detail = "Grott is not in the telemetry priority, so this feed is not being watched."
        elif fact["grott_connected"] and fact["grott_ok"]:
            grott_detail = "The Grott feed is connected and fresh."
        elif not fact["grott_connected"]:
            grott_detail = "MQTT to Grott is not connected."
        else:
            age = fact["grott_age_s"]
            age_bit = f"{float(age):.0f} seconds" if age is not None else "an unknown time"
            grott_detail = (
                f"MQTT is up, but the last inverter frame was {age_bit} ago. "
                f"Fresh means within {float(fact['grott_fresh_s']):.0f} seconds."
            )
        grott_hold = self._grott_hold_s(
            bool(fact["grott_connected"]), fact["grott_age_s"], float(fact["grott_fresh_s"]),
        )
        parts["grott_lost"] = (
            AlarmPart("Grott feed stops arriving", grott_bad, grott_detail),
            self._duration_part(
                "grott_lost", grott_bad, self._grott_lost_since, now, grott_hold,
            ),
            result(
                "grott_lost",
                self._fires("grott_lost", self._grott_lost_since, now, grott_hold),
            ),
        )

        logging_on = bool(fact["db_logging_enabled"])
        connected = fact["db_connected"]
        db_down = bool(logging_on and connected is False)
        if not logging_on:
            reach = "Logging is switched off, so a closed database is not an alarm."
        elif connected is True:
            reach = "The database can be reached."
        elif connected is False:
            reach = "The database cannot be reached."
        else:
            reach = "The database has not reported on the last check."
        disc_hold = self._wait_s("db_disconnected", self.db_disconnect_hold_s)
        parts["db_disconnected"] = (
            AlarmPart(
                "Logging is switched on",
                logging_on,
                "Logging is on." if logging_on else "Logging is switched off.",
            ),
            AlarmPart("Logging database cannot be reached", db_down, reach),
            self._duration_part(
                "db_disconnected", db_down, self._db_disc_since, now, disc_hold,
            ),
            result(
                "db_disconnected",
                self._fires("db_disconnected", self._db_disc_since, now, disc_hold),
            ),
        )

        expect_write = bool(fact["growatt_writing"] or fact["tasmota_writing"])
        who = []
        if fact["growatt_writing"]:
            who.append("Growatt")
        if fact["tasmota_writing"]:
            who.append("Tasmota")
        live_detail = (
            f"{' and '.join(who)} look live."
            if who
            else "Neither Growatt nor Tasmota is set to write."
        )
        rows = fact["db_rows_15m"]
        uptime = now - float(self._started_wall or now)
        past_grace = self._ingest_seen_ok or uptime >= DEFAULT_INGEST_STARTUP_GRACE_S
        ingest_dry = (
            logging_on
            and connected is True
            and expect_write
            and rows is not None
            and int(rows) <= 0
        )
        ingest_bad = bool(ingest_dry and past_grace)
        if not logging_on:
            write_detail = "Logging is switched off."
        elif connected is not True:
            write_detail = "The database is not connected. That is the other alarm."
        elif not expect_write:
            write_detail = "Nothing is set to write, so a quiet table is not this alarm."
        elif rows is None:
            write_detail = "No row count on the last check."
        elif int(rows) > 0:
            write_detail = f"{int(rows)} new rows in the last 15 minutes."
        elif not past_grace:
            write_detail = (
                "No new rows yet. The logger is still inside its startup grace "
                "of about 16 minutes, or it has not seen a successful write."
            )
        else:
            write_detail = "No new rows in growatt_readings or tasmota_readings for 15 minutes."
        ingest_hold = self._wait_s("db_ingest_stale", self.db_ingest_hold_s)
        parts["db_ingest_stale"] = (
            AlarmPart("Growatt or Tasmota looks live", expect_write, live_detail),
            AlarmPart("Database writing stops", ingest_bad, write_detail),
            self._duration_part(
                "db_ingest_stale", ingest_bad, self._db_ingest_since, now, ingest_hold,
            ),
            result(
                "db_ingest_stale",
                self._fires("db_ingest_stale", self._db_ingest_since, now, ingest_hold),
            ),
        )

        inv_bad = bool(fact["inverter_comms_lost"])
        reason = str(fact["inverter_comms_reason"] or "").strip()
        if inv_bad:
            inv_detail = f"Growatt reports the inverter as {reason or 'offline'}."
        else:
            inv_detail = "Growatt has not reported the inverter offline."
        inv_hold = self._wait_s("inverter_comms_lost", self.inverter_lost_hold_s)
        parts["inverter_comms_lost"] = (
            AlarmPart("Inverter is reported offline", inv_bad, inv_detail),
            self._duration_part(
                "inverter_comms_lost", inv_bad, self._inv_lost_since, now, inv_hold,
            ),
            result(
                "inverter_comms_lost",
                self._fires("inverter_comms_lost", self._inv_lost_since, now, inv_hold),
            ),
        )

        mqtt_expected = bool(fact["tasmota_mqtt_expected"])
        mqtt_up = bool(fact["tasmota_mqtt_connected"])
        mqtt_bad = bool(mqtt_expected and not mqtt_up)
        if not mqtt_expected:
            mqtt_detail = "The Tasmota page is not in MQTT mode, so this is not being watched."
        elif mqtt_up:
            mqtt_detail = "The Tasmota MQTT connection is up."
        else:
            mqtt_detail = "The Tasmota page is in MQTT mode and the broker connection is down."
        mqtt_hold = self._wait_s("tasmota_mqtt_lost", self.tasmota_mqtt_hold_s)
        parts["tasmota_mqtt_lost"] = (
            AlarmPart("Tasmota MQTT drops", mqtt_bad, mqtt_detail),
            self._duration_part(
                "tasmota_mqtt_lost", mqtt_bad, self._tasmota_mqtt_since, now, mqtt_hold,
            ),
            result(
                "tasmota_mqtt_lost",
                self._fires("tasmota_mqtt_lost", self._tasmota_mqtt_since, now, mqtt_hold),
            ),
        )

        offline = [str(x).strip() for x in (fact["tasmota_offline"] or []) if str(x).strip()]
        if mqtt_expected and not mqtt_up:
            offline = []
        plugs_bad = bool(offline)
        if not mqtt_expected:
            mqtt_ctx = "Tasmota is not using MQTT, so this condition is not being watched."
            mqtt_ctx_on = False
        elif not mqtt_up:
            mqtt_ctx = "MQTT is down, so silent plugs are not listed on their own."
            mqtt_ctx_on = False
        else:
            mqtt_ctx = "MQTT is connected."
            mqtt_ctx_on = True
        if plugs_bad:
            plug_detail = "Silent: " + ", ".join(offline[:6])
            if len(offline) > 6:
                plug_detail += f" (+{len(offline) - 6} more)"
            plug_detail += "."
        elif mqtt_expected and not mqtt_up:
            plug_detail = "Not judged while MQTT itself is down."
        else:
            plug_detail = "Every named device is reporting."
        plug_hold = self._wait_s("tasmota_offline", self.tasmota_stale_s)
        parts["tasmota_offline"] = (
            AlarmPart("MQTT is still up", mqtt_ctx_on, mqtt_ctx),
            AlarmPart("Tasmota device goes silent", plugs_bad, plug_detail),
            self._duration_part(
                "tasmota_offline", plugs_bad, self._tasmota_off_since, now, plug_hold,
            ),
            result(
                "tasmota_offline",
                self._fires("tasmota_offline", self._tasmota_off_since, now, plug_hold),
            ),
        )

        self._inspection = parts
        self._inspection_at = float(now)

    def _grott_lost_hit(
        self,
        now: float,
        connected: bool,
        age_s: float | None,
        fresh_s: float,
    ) -> AlarmHit | None:
        # A duration chosen on Alarm defs replaces the usual Grott wait.
        # Is flapping replaces that wait with a count of crossings.
        hold_s = self._grott_hold_s(connected, age_s, fresh_s)
        if not self._fires("grott_lost", self._grott_lost_since, now, hold_s):
            return None
        dur_s = now - self._mark_since("grott_lost", self._grott_lost_since)
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
            since_wall=self._mark_since("grott_lost", self._grott_lost_since),
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
        db_down = bool(db_logging_enabled and db_connected is False)
        if db_down:
            if self._db_disc_since is None:
                self._db_disc_since = now
        else:
            self._db_disc_since = None
            self._end_stretch("db_disconnected")
        self._note_flap("db_disconnected", db_down, now)
        if self._fires(
            "db_disconnected",
            self._db_disc_since,
            now,
            self._wait_s("db_disconnected", self.db_disconnect_hold_s),
        ):
            dur_s = now - self._mark_since("db_disconnected", self._db_disc_since)
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
                since_wall=self._mark_since("db_disconnected", self._db_disc_since),
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
        ingest_bad = bool(ingest_dry and past_grace)
        if ingest_bad:
            if self._db_ingest_since is None:
                self._db_ingest_since = now
        else:
            self._db_ingest_since = None
            self._end_stretch("db_ingest_stale")
        self._note_flap("db_ingest_stale", ingest_bad, now)
        if self._fires(
            "db_ingest_stale",
            self._db_ingest_since,
            now,
            self._wait_s("db_ingest_stale", self.db_ingest_hold_s),
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
                since_wall=self._mark_since("db_ingest_stale", self._db_ingest_since),
                now_wall=now,
            ))

        # ── Inverter reported offline by Growatt cloud ──────────────────
        inv_bad = bool(inverter_comms_lost)
        if inv_bad:
            if self._inv_lost_since is None:
                self._inv_lost_since = now
        else:
            self._inv_lost_since = None
            self._end_stretch("inverter_comms_lost")
        self._note_flap("inverter_comms_lost", inv_bad, now)
        if self._fires(
            "inverter_comms_lost",
            self._inv_lost_since,
            now,
            self._wait_s("inverter_comms_lost", self.inverter_lost_hold_s),
        ):
            reason = (inverter_comms_reason or "offline").strip()
            dur_m = (now - self._mark_since("inverter_comms_lost", self._inv_lost_since)) / 60.0
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
                since_wall=self._mark_since("inverter_comms_lost", self._inv_lost_since),
                now_wall=now,
            ))

        # ── Tasmota MQTT broker down ────────────────────────────────────
        mqtt_bad = bool(tasmota_mqtt_expected and not tasmota_mqtt_connected)
        if mqtt_bad:
            if self._tasmota_mqtt_since is None:
                self._tasmota_mqtt_since = now
        else:
            self._tasmota_mqtt_since = None
            self._end_stretch("tasmota_mqtt_lost")
        self._note_flap("tasmota_mqtt_lost", mqtt_bad, now)
        if self._fires(
            "tasmota_mqtt_lost",
            self._tasmota_mqtt_since,
            now,
            self._wait_s("tasmota_mqtt_lost", self.tasmota_mqtt_hold_s),
        ):
            dur_s = now - self._mark_since("tasmota_mqtt_lost", self._tasmota_mqtt_since)
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
                since_wall=self._mark_since("tasmota_mqtt_lost", self._tasmota_mqtt_since),
                now_wall=now,
            ))

        # ── Named Tasmota devices gone silent ───────────────────────────
        offline = [str(x).strip() for x in (tasmota_offline or []) if str(x).strip()]
        # If the whole MQTT pipe is down, don't also list every plug.
        if tasmota_mqtt_expected and not tasmota_mqtt_connected:
            offline = []
        plugs_bad = bool(offline)
        if plugs_bad:
            self._tasmota_offline_labels = tuple(offline)
            if self._tasmota_off_since is None:
                self._tasmota_off_since = now
        else:
            self._tasmota_off_since = None
            if "tasmota_offline" not in self._rule_flap:
                self._tasmota_offline_labels = ()
            self._end_stretch("tasmota_offline")
        self._note_flap("tasmota_offline", plugs_bad, now)
        if self._fires(
            "tasmota_offline",
            self._tasmota_off_since,
            now,
            self._wait_s("tasmota_offline", self.tasmota_stale_s),
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
                    f"No telemetry for at least {self.tasmota_stale_s / 60.0:.0f} "
                    f"min from: {labels}{extra}. "
                    "Wi-Fi drop, a powered-off plug, or a stuck Tasmota firmware "
                    "are the usual causes — not a chart bug."
                ),
                since_wall=self._mark_since("tasmota_offline", self._tasmota_off_since),
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
        spec = self._rule_flap.get(key)
        if spec is not None:
            n = len(self._flap_hits.get(key, ()))
            detail = f"{spec.phrase()} — {n} in the window so far. " + detail
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
    "AlarmPart",
    "AlarmMonitor",
    "AlarmSpec",
    "AlarmBlocks",
    "ALARM_CATALOGUE",
    "ALARM_BLOCKS",
    "ALARM_EXTRA_PIECES",
    "ALARM_PIECE_KINDS",
    "ALARM_PIECE_REQUIRED",
    "alarm_palette",
    "alarm_rule_syntax",
    "alarm_piece_accepted",
    "alarm_band",
    "duration_seconds",
    "format_duration",
    "parse_flap",
    "FlapSpec",
    "FLAP_CHOICE",
    "DURATION_CHOICES",
    "SIGNAL_ALARM_TYPE",
    "CONTEXT_SIGNALS",
    "signal_alarm_type",
    "alarm_logic_note",
    "alarm_blocks_key",
    "alarm_unit_problem",
    "split_joined_pieces",
    "severity_outcome",
    "outcome_channels",
    "rule_channel_overrides",
    "signal_builtin_keys",
    "signal_combo",
    "combo_matches",
    "ACTION_OUTCOMES",
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
