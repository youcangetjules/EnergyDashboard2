# MOTIFS.md — UI design motifs

Part of the **basic instructions for the development environment** (see `AGENTS.md`).

Living design system for the Energy Dashboard. Prefer these motifs over inventing new chrome. When you change a motif in code, **update this file** so agents and humans stay aligned.

**Source of truth in code** (apply helpers — do not copy QSS by hand into tabs unless necessary):

| Concern | Primary modules |
|---------|-----------------|
| Palette / spin footprint | `energy_dashboard/ui/palette.py` |
| Primary green buttons | `energy_dashboard/ui/theme_constants.py`, `ui/buttons.py` |
| Spin / line-field motif, app QSS | `energy_dashboard/ui/styles.py` |
| Setup & Info field grids | `energy_dashboard/tabs/parameters.py` |
| Charts / dark axes | `energy_dashboard/ui/chart_utils.py`, `ui/palette.py` |

Dark theme base is Catppuccin-inspired (`#1e1e2e` background, `#cdd6f4` text). Motifs sit on top of that.

---

## 1. Buttons

### Primary action (default)

Every ordinary `QPushButton` uses the **muted green** motif (same as “Refresh All”).

| Token | Value |
|-------|--------|
| Background | `#354a3f` (hover `#3f5649`, press `#4a6352`) |
| Text | `#e8f5e9` |
| Border | `1px solid rgba(166, 227, 161, 175)` |
| Radius | `3px` |
| Padding | `4px 14px` |

**How it is applied**

- App-wide: `_REFRESH_ALL_BTN_QSS` / `_APP_GLOBAL_WIDGET_QSS`.
- After building UI: `_style_all_primary_buttons(root)` / `_apply_primary_button_style(btn)`.
- Before showing a dialog: `_prepare_dialog_buttons(dialog)`.
- Alias used in many tabs: `_SUBTLE_BTN_QSS` (identical to primary green — name is historical).

**Do**

- Use primary green for Save, Fetch, Test, Apply, Refresh, Close on action rows.
- Keep button width fixed when aligning under a spin (often `130` or `110` px) so a row of Save + Test looks even.

**Do not**

- Invent a second “loud” green or blue action style for normal buttons.
- Rely on Fusion defaults — always go through the motif helpers.

### One-shot result (after the click)

A button that runs a job (Run Advisor, and the same helper elsewhere) keeps the muted green **until that job finishes**. Then:

| Last result | Fill | Text |
|-------------|------|------|
| Worked | `#5daf6e` — same pale green as a page tab that has just refreshed | Black |
| Failed | `#1e1e2e` — same black as a tab that has not updated | White |

Helper: `_apply_action_outcome_style(btn, ok)` in `ui/buttons.py`. It marks the button exempt so a later primary-style walk does not paint the muted green back over the result.

### Exemptions (not green)

| Control | Motif | Notes |
|---------|--------|--------|
| Main tab **group** strip (`objectName == "mainTabGroupBtn"`) | Amber Catppuccin peach | `_MAIN_TAB_GROUP_BTN_QSS` — must stay amber |
| Tasmota **Toggle** | Property `primary_button_exempt` + dedicated ON/OFF QSS | Never force green |
| Bottom bar **Alarms** | Red fill `#8b3a44`, light text `#ffe8ea` (`_ALARMS_BTN_QSS`) | Sits 30px to the left of Refresh Page. Exempt from the green walk. |
| Alarm defs blocks | Signal `#89b4fa`, Comparison `#94e2d5`, Threshold `#f9e2af`, For how long `#cba6f7`, While `#fab387`, Outcome `#f38ba8`, text `#1e1e2e` | One colour per kind of block; a block drops only into a well of its own colour. Filled wells take the block colour, empty wells are a dashed outline in it. Not the green button motif. |
| Retention **Activate** | Electric-blue when active, muted grey when off | `_retention_activate_btn_qss` |
| Chart **QToolButton** | Transparent + blue hover wash | Part of `_APP_GLOBAL_WIDGET_QSS` |

To exempt a button: `btn.setProperty(PRIMARY_BUTTON_EXEMPT, True)` then apply its own stylesheet.

### Retention dialog actions

- **Save / Prune** on a row → primary green (`_retention_row_action_btn_qss`).
- **Activate / Active** → electric-blue toggle (see spin motif colour `#00a8ff`).

---

## 2. Spin boxes (and matching numeric fields)

### Electric-blue field motif (canonical)

Reference look: Setup & Info **Export (p/kWh)** and every app `QSpinBox` / `QDoubleSpinBox`.

| Token | Value |
|-------|--------|
| Fill | Panel surface lifted 15% toward white (`_SPIN_FIELD_BG`) |
| Border | `#00a8ff` (`_ELECTRIC_BLUE`) — 1px |
| Focus border | Same electric blue |
| Text | `#cdd6f4`, weight ~490 |
| Radius | `4px` |
| Default size | **98 × 20** px (`_SPIN_FIELD_MOTIF_W` × `_SPIN_FIELD_MOTIF_H`) |
| Wide / DB port | **128 × 20** (`_SPIN_FIELD_MOTIF_DB_W`) |
| Stepper strip | 18px; SVG chevrons; hover wash on up/down buttons |
| Value alignment | Left + vertical centre |

**How it is applied**

```python
apply_spin_field_motif(spin)                    # 98×20
apply_spin_field_motif(spin, width=140)         # custom width
spin.setProperty("_pm_spin_motif_w", 140)       # respected by tree walk
spin.setProperty("_params_db_field", True)      # → DB width
apply_spin_field_motif_tree(root)               # main window does this once
apply_combo_field_motif(combo, width=320)       # same grey + electric-blue border
apply_date_picker_motif(button, width=168)      # dropdown calendar, not a stepper
```

A day picker is a dropdown that opens a calendar (PV String Charge **Day**). Same fill and electric-blue border as a combo, one chevron, exempt from the green button motif. Do not offer a future day. Do not use spin up/down chevrons for a date.

Setup & Info line edits that should *look* like spins (host, user, API key slices, etc.):

```python
apply_setup_info_line_field_motif(edit)         # objectName paramsDbField
```

**Aliases** (same QSS): `_spin_field_motif_qss()`, `_setup_info_spin_qss()`, `_flat_tariff_spin_qss()`, `_combo_field_motif_qss()`.

### Neutral inputs (same grey fill)

Ordinary `QLineEdit` / `QComboBox` / `QTimeEdit` use the **same slight grey fill** as spin fields (`_SPIN_FIELD_BG`, aliased as `_DARK_INPUT_BG`) with a soft border — not electric blue — unless explicitly promoted via `apply_setup_info_line_field_motif`.

App start also runs `apply_input_field_fill_tree(root)` so Fusion paints that grey even when stylesheet Base is ignored.

**Rule of thumb:** editable numbers and Setup credential *fields that sit in the spin grid* → electric blue. Long free-text (API keys on Octopus Live, share URLs) may stay soft-bordered or use the blue motif when they sit in a Setup pair grid. Every text entry and spin shares the lifted grey fill.

### Special spin chrome

| Context | Style |
|---------|--------|
| Tasmota pin-chart overlay spin | Frosted white on chart (`_TASMOTA_PIN_CHART_CB_QSS`) — local exception |

---

## 3. Alignment styles

These are layout rules, not colours. Misaligned spins/buttons are a recurring UX bug — follow these.

### A. Label column → field column (Setup & Info)

Setup uses a **pair grid**: title | gap | field | gap-to-next (up to 3 pairs per row).

| Constant | Role |
|----------|------|
| `_SETUP_INFO_LABEL_WIDTH` (200) / pair widths | Title columns sized to the **widest title** so every field shares one left edge |
| `_PARAMS_LABEL_SPIN_GAP` (12) | Space between title and field |
| `_PARAMS_SPIN_NEXT_GAP` (24) | Space before the next pair’s title |
| `_SETUP_INFO_SPIN_BTN_GAP` (20) | Horizontal gap when a button sits **on the same row** after a spin |

Helpers: `_params_make_field_grid()`, `_params_grid_add_pairs()`, `_params_apply_grid_columns()`, `_align_setup_info_spins()`.

**Rule:** Title columns are anchored to the widest title in that grid — never leave each row with a different label width, or fields zigzag.

### B. Save / Test under a field (own row)

When Save (and optional Test) sit **below** a spin or URL field:

1. Put them in the **field column** of the grid (`_params_field_col(0)`), not under the label.
2. Left-align the button row with the spin/field above.
3. Test sits **to the right** of Save (same height, equal fixed widths when practical).
4. Do **not** insert `_SETUP_INFO_SPIN_BTN_GAP` as leading indent on that row — that pushes Save past the spin’s left edge.

Canonical examples: PVOutput, Wonderwatt, auto-refresh interval on Setup & Info.

### C. Stacked credential rows (Octopus)

For Import / Export MPAN (and Account No on Live):

1. Give labels a **shared fixed width** = `max(QFontMetrics advance of each label) + pad`.
2. Stack Import above Export so fields share one left edge (Export MPAN is the visual reference).
3. Do not park Import MPAN mid-row after Granularity — that breaks vertical alignment with Export.
4. On Octopus Live, Hours and View are split by a vertical rule. **Save** sits immediately to the right of View, and **Test** sits to the right of Save (equal fixed widths). Do not put Save back beside Account No.

### D. Physical / info grids (Growatt)

- Labels in column 0 (often right-aligned titles).
- Values / controls in column 1 — spins and buttons in that cell must start at the **same left edge** as other values.
- Widest title sets the label column; keep that intentional.

### D2. Command Sim (Controls)

- Server and client forms use **label | field | stretch** so fields sit left and stop around mid-window (not full bleed).
- Bind address / profile / operation use electric-blue motif (`apply_setup_info_line_field_motif` / `apply_combo_field_motif`); port / unit / address spins use `apply_spin_field_motif`.

### E. Dialogs

- Content left-aligned inside the dialog margins (Connectivity detail / Wonderwatt share).
- Dialog action buttons get primary green via `_prepare_dialog_buttons`.
- Retention spins already share a grid column — keep labels in col 0, widgets in col 1.
- A dialog that blocks the rest of the app (OK / Cancel / Close via `exec`) stays above every other window until it is answered. That pin is a timer in `ui/modal_ontop.py` — do not rely on each call site, and do not install a Python event filter on the application.
- The main window fills the usable screen and must not extend under the taskbar (`ui/work_area.py`). Do not `showMaximized()` it onto the full monitor.

### F. Database Export status + SQL (Setup & Info)

- **DB seen / Database connected / Tables connected** (or Disabled) sit **immediately after** the host/file fields, **left-aligned** (not centred in leftover width).
- The remaining row width on the **right** is the create-all SQL pane (table list + script + Copy SQL).
- Do not put a stretch *before* the status panel — that parks Disabled on the far right.

- **Copy CREATE SQL** / **Copy SQL** put the full create-all script on the clipboard.
- **Show missing** (each engine row) lists logger tables that are not present yet and shows CREATE SQL for those tables only (PostgreSQL includes GRANT lines for the User field).

### G. General checklist

Before shipping a form row:

- [ ] Do all related fields share one vertical left edge?
- [ ] Does Save under a field line up with that field (not the label)?
- [ ] Is Test to the right of Save, not under it?
- [ ] Are spins 20px tall and motif-coloured (unless exempt)?
- [ ] Are action buttons primary green (unless exempt)?

---

## 4. Related chrome (brief)

Not full motifs, but keep consistent:

| Element | Motif note |
|---------|------------|
| Checkboxes | White halo square; solid green fill when checked (no tick glyph) — `_checkbox_indicator_qss` |
| Status / hint text | `_UI_BLUE` / `_UI_BLUE_MUTED` on dark chrome |
| Footer system strip (`QFrame#systemStatusBar`) | Two lines above the QStatusBar: DB green `#a6e3a1` / red `#f38ba8`; CPU/RAM and ingest in `_DARK_SUBTEXT` 11px on `_DARK_MANTLE` |
| Live banner refresh pill | Same green as primary buttons — `_BANNER_REFRESH_CYCLE_QSS` |
| Main page tabs | Freshness green / static blue / stale black — `ui/tab_bar.py`, palette tab tokens. An **unselected** tab that has **not updated** uses a 10% white fill (`_TAB_PAGE_NOT_UPDATED_IDLE`) and a light outline (`_TAB_OUTLINE_STALE`) drawn **inside** that same silhouette, so the header stays the same size as the green and blue tabs. A **2px** line in 70% grey (`_TAB_BAR_RULE`, `#b3b3b3`) runs under the whole tab bar. |
| Group boxes | Dark surface lift (`_DARK_SURFACE_BG`), light border `#313244` / `#45475a`. **Octopus Live Monitor** title chip (`QGroupBox#octopusLiveMonitor::title`): opaque frosted-glass gradient (highlight → `#585b70` → `#313244`) + `1px solid` `_DARK_OVERLAY` (`#6c7086`), 4px radius — in `ui/styles.py` |
| Alarms / bad state | Peach / red text (`#fab387`, `#f38ba8`) — meaning first, colour second |
| Login-panel test line | Same row as Save / Test, right-hand end (`_TestStatement`). Green `#a6e3a1` “Connectivity — OK”, red `#f38ba8` “Connectivity — failed”, amber `#fab387` “Connectivity - last OK (Stale >1hr since last test)” once a pass is older than an hour. A short note (“Saved…”) stays on the row underneath. |

---

## 5. When adding UI

1. Read this file + `skills.md` (UI/UX hat).
2. Reuse `apply_spin_field_motif` / primary button helpers / Setup grid helpers.
3. Match neighbouring rows on the same screen — local consistency beats a new “clever” layout.
4. If you introduce a **new** recurring control look, add a section here and point at the implementing symbol.

Do not fudge telemetry to make a layout look nicer (`AGENTS.md` telemetry integrity).
