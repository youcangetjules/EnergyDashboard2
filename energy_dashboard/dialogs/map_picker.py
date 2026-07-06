"""
Energy Dashboard — `dialogs/map_picker.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

import time as _time_mod

from energy_dashboard.common import *
import pwd
class _MapPickerUnavailable(RuntimeError):
    """Raised when QtWebEngine isn't installed."""


def _configure_qt_webengine_chromium():
    """Chromium flags before QApplication (root needs --no-sandbox for QWebEngine)."""
    flags = os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '').strip()
    extra = []
    if '--no-sandbox' not in flags:
        try:
            if hasattr(os, 'geteuid') and os.geteuid() == 0:
                extra.append('--no-sandbox')
        except Exception:
            pass
    # When the user has not set flags, add Linux defaults that reduce KDE/GPU crashes.
    if sys.platform.startswith('linux') and not flags:
        for opt in (
            '--disable-gpu',
            '--disable-gpu-compositing',
            '--disable-dev-shm-usage',
        ):
            if opt not in extra:
                extra.append(opt)
    if extra:
        os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = (
            f"{flags} {' '.join(extra)}".strip()
        )


def _forecast_w3w_api_key():
    try:
        return (
            QSettings('PowerModel', 'EnergyDashboard2')
            .value('params/w3w_api_key', '', type=str) or ''
        ).strip()
    except Exception:
        return ''


def _w3w_lookup_coordinates(words, api_key):
    """Return (lat, lon) or (None, None) and an error/status message."""
    words = (words or '').strip().lstrip('/')
    if not words or words.count('.') != 2:
        return None, None, 'what3words must be three dot-separated words'
    if not (api_key or '').strip():
        return None, None, 'Set a what3words API key in Setup & Info → Solar (if you use w3w)'
    try:
        r = requests.get(
            'https://api.what3words.com/v3/convert-to-coordinates',
            params={'words': words, 'key': api_key.strip()},
            timeout=15,
        )
        if r.status_code != 200:
            return None, None, f'HTTP {r.status_code}'
        j = r.json()
        if 'coordinates' in j:
            return (
                float(j['coordinates']['lat']),
                float(j['coordinates']['lng']),
                '',
            )
        return None, None, j.get('error', {}).get('message', 'unknown w3w response')
    except Exception as e:
        return None, None, str(e)


def _w3w_lookup_words(lat, lon, api_key):
    """Return (words, err) for coordinates → what3words (convert-to-3wa)."""
    if not (api_key or '').strip():
        return None, 'Set a what3words API key in Setup & Info → Solar (if you use w3w)'
    try:
        la = round(float(lat), 8)
        lo = round(float(lon), 8)
    except (TypeError, ValueError):
        return None, 'Invalid coordinates'
    try:
        r = requests.get(
            'https://api.what3words.com/v3/convert-to-3wa',
            params={
                'coordinates': f'{la},{lo}',
                'key': api_key.strip(),
            },
            timeout=15,
        )
        if r.status_code != 200:
            return None, f'HTTP {r.status_code}'
        j = r.json() or {}
        w = (j.get('words') or '').strip().lstrip('/')
        if w and w.count('.') == 2:
            return w, ''
        return None, j.get('error', {}).get('message', 'unknown w3w response')
    except Exception as e:
        return None, str(e)


def _nominatim_lookup_place(query):
    """Geocode a place name via OpenStreetMap Nominatim (no API key)."""
    q = (query or '').strip()
    if not q:
        return None, None, 'Enter a place name or postcode'
    try:
        r = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params={'q': q, 'format': 'json', 'limit': 1},
            headers={'User-Agent': f'PowerModel/{APP_VERSION} (forecast location)'},
            timeout=20,
        )
        if r.status_code != 200:
            return None, None, f'Nominatim HTTP {r.status_code}'
        rows = r.json()
        if not rows:
            return None, None, 'No results — try a more specific place name'
        row = rows[0]
        return float(row['lat']), float(row['lon']), row.get('display_name', '')
    except Exception as e:
        return None, None, str(e)


def _map_picker_webengine_available():
    try:
        import importlib.util
        return importlib.util.find_spec('PySide6.QtWebEngineWidgets') is not None
    except Exception:
        return False


def _embedded_web_ui_enabled():
    """Qt WebEngine for device URLs can segfault on root/KDE — opt-in only."""
    return (
        os.environ.get('POWERMODEL_EMBEDDED_WEB_UI', '').strip() == '1'
        and _map_picker_webengine_available()
    )


def _map_picker_webengine_enabled():
    """Leaflet map in Set location… — on when WebEngine is installed unless opted out."""
    raw = os.environ.get('POWERMODEL_MAP_WEBENGINE', '').strip().lower()
    if raw in ('0', 'false', 'no', 'off'):
        return False
    if raw in ('1', 'true', 'yes', 'on'):
        return _map_picker_webengine_available()
    return _map_picker_webengine_available()


def _desktop_unix_user():
    """GUI session owner (not root when the dashboard was started with sudo)."""
    try:
        sudo_uid = os.environ.get('SUDO_UID', '').strip()
        if sudo_uid.isdigit() and int(sudo_uid) >= 1000:
            import pwd
            return pwd.getpwuid(int(sudo_uid)).pw_name
    except Exception:
        pass
    override = os.environ.get('POWERMODEL_GUI_USER', '').strip()
    if override and override != 'root':
        return override
    for key in ('LOGNAME', 'USER'):
        name = (os.environ.get(key) or '').strip()
        if name and name != 'root':
            return name
    try:
        import pwd
        for entry in sorted(os.listdir('/run/user'), key=lambda x: int(x) if x.isdigit() else 0):
            if entry.isdigit() and int(entry) >= 1000:
                return pwd.getpwuid(int(entry)).pw_name
    except Exception:
        pass
    return None


def _gui_env_for_user(username):
    """DISPLAY / XDG_RUNTIME_DIR / DBus for launching a browser on the desktop."""
    import pwd
    env = os.environ.copy()
    if not username:
        return env
    try:
        pw = pwd.getpwnam(username)
    except KeyError:
        return env
    uid = pw.pw_uid
    env['HOME'] = pw.pw_dir
    env['USER'] = username
    env['LOGNAME'] = username
    rundir = f'/run/user/{uid}'
    if os.path.isdir(rundir):
        env['XDG_RUNTIME_DIR'] = rundir
        bus = os.path.join(rundir, 'bus')
        if os.path.exists(bus):
            env['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path={bus}'
    if not env.get('DISPLAY'):
        env['DISPLAY'] = ':0'
    xauth = os.path.join(pw.pw_dir, '.Xauthority')
    if os.path.isfile(xauth):
        env['XAUTHORITY'] = xauth
    return env


def _argv_for_gui_session(argv):
    """When running as root, run the browser as the desktop user (snap needs this)."""
    import shutil
    user = _desktop_unix_user()
    env = _gui_env_for_user(user) if user else os.environ.copy()
    try:
        as_root = hasattr(os, 'geteuid') and os.geteuid() == 0
    except Exception:
        as_root = False
    if as_root and user and user != 'root':
        runuser = shutil.which('runuser')
        if runuser:
            return [runuser, '-u', user, '--'] + list(argv), env
    return list(argv), env


def _direct_browser_launch_commands(url):
    """Real browser binaries only — never /usr/bin/firefox (KDE xdg-settings wrapper)."""
    import shutil
    try:
        as_root = hasattr(os, 'geteuid') and os.geteuid() == 0
    except Exception:
        as_root = False
    sandbox = ['--no-sandbox'] if as_root else []
    seen = set()

    def _add(argv):
        key = tuple(argv)
        if key not in seen:
            seen.add(key)
            yield argv

    snap_ff = '/snap/bin/firefox'
    if os.path.isfile(snap_ff) and os.access(snap_ff, os.X_OK):
        yield from _add([snap_ff, '-new-window', url])

    for name in (
        'firefox-esr',
        'google-chrome-stable', 'google-chrome',
        'chromium', 'chromium-browser',
    ):
        path = shutil.which(name)
        if not path:
            continue
        if 'firefox' in name:
            yield from _add([path, '-new-window', url])
        else:
            yield from _add([path] + sandbox + ['--new-window', url])

    # Last resort: plain firefox only if not the /usr/bin snap wrapper script.
    path = shutil.which('firefox')
    if path and path not in ('/usr/bin/firefox', '/bin/firefox'):
        yield from _add([path, '-new-window', url])


def _try_launch_direct_browser(url):
    import subprocess
    last_err = ''
    for argv in _direct_browser_launch_commands(url):
        full_argv, env = _argv_for_gui_session(argv)
        try:
            proc = subprocess.Popen(
                full_argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                start_new_session=True,
            )
            _time_mod.sleep(0.8)
            code = proc.poll()
            if code is not None:
                err = (proc.stderr.read() or b'').decode('utf-8', errors='replace').strip()
                last_err = err or f'process exited with code {code}'
                continue
            return True, os.path.basename(argv[0]), ''
        except OSError as e:
            last_err = str(e)
            continue
    return False, '', last_err


class DeviceWebUiDialog(QDialog):
    """Safe Web UI helper — copy URL or launch Firefox/Chromium directly."""

    def __init__(self, url, parent=None, title=None):
        super().__init__(parent)
        self._url = (url or '').strip()
        self.setWindowTitle(title or 'Web UI')
        self.resize(520, 200)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        hint = QLabel(
            'Opens Firefox/Chromium directly (not the <code>/usr/bin/firefox</code> '
            'wrapper). If the app runs as <b>root</b>, the browser starts as your '
            'desktop user. If no window appears, copy the URL below.'
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.RichText)
        hint.setStyleSheet('color: #a6adc8;')
        lay.addWidget(hint)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel('URL:'))
        self.url_edit = QLineEdit(self._url)
        self.url_edit.setReadOnly(True)
        self.url_edit.selectAll()
        url_row.addWidget(self.url_edit, 1)
        copy_btn = QPushButton('Copy')
        copy_btn.clicked.connect(self._copy_url)
        _apply_primary_button_style(copy_btn)
        url_row.addWidget(copy_btn)
        lay.addLayout(url_row)

        self.status_label = QLabel('')
        self.status_label.setStyleSheet('color: #a6adc8; font-size: 11px;')
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton('Open in browser')
        self.open_btn.clicked.connect(self._launch_browser)
        _apply_primary_button_style(self.open_btn)
        btn_row.addWidget(self.open_btn)
        btn_row.addStretch()
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.accept)
        _apply_primary_button_style(close_btn)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)
        _prepare_dialog_buttons(self)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, '_auto_launched', False):
            self._auto_launched = True
            self._launch_browser(quiet=True)

    def _copy_url(self):
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(self._url)
            self.status_label.setText('URL copied to clipboard.')

    def _launch_browser(self, quiet=False):
        ok, exe, err = _try_launch_direct_browser(self._url)
        if ok:
            gui_user = _desktop_unix_user()
            who = f' as {gui_user}' if gui_user and gui_user != 'root' else ''
            self.status_label.setText(
                f'Launched {exe}{who} — if no window appears, copy the URL.'
            )
            return True
        detail = (err or 'no browser found').replace('\n', ' ')[:240]
        if not quiet:
            self.status_label.setText(
                f'Could not start a browser: {detail}. Copy the URL or install Firefox.'
            )
        elif err:
            self.status_label.setText(f'Browser failed: {detail}')
        return False


def _open_http_url(url_str, parent=None, title='Web UI', modal=False):
    """Open device web UI without Qt WebEngine (segfault-safe)."""
    raw = (url_str or '').strip()
    if not raw:
        return False
    if not raw.startswith(('http://', 'https://')):
        raw = f'http://{raw.lstrip("/")}'
    qurl = QUrl(raw)
    if not qurl.isValid():
        QMessageBox.warning(parent, title, f'Invalid URL:\n{raw}')
        return False

    if _embedded_web_ui_enabled():
        try:
            dlg = EmbeddedBrowserDialog(raw, parent=parent, title=title)
            dlg.setAttribute(Qt.WA_DeleteOnClose, True)
            if modal:
                dlg.exec()
            else:
                dlg.show()
            return True
        except Exception as e:
            try:
                _log.warn('Web UI', f'Embedded browser failed: {e}')
            except Exception:
                pass

    dlg = DeviceWebUiDialog(raw, parent=parent, title=title)
    if modal:
        dlg.exec()
    else:
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.setWindowFlag(Qt.Window, True)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
    return True


class EmbeddedBrowserDialog(QDialog):
    """In-app HTTP(S) viewer when the OS browser cannot be launched."""

    def __init__(self, url, parent=None, title=None):
        super().__init__(parent)
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self._url = (url or '').strip()
        self.setWindowTitle(title or 'Web UI')
        self.resize(960, 720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        row = QHBoxLayout()
        row.addWidget(QLabel('URL:'))
        self.url_label = QLabel(self._url)
        self.url_label.setStyleSheet('color: #a6adc8; font-size: 11px;')
        self.url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.url_label, 1)
        ext_btn = QPushButton('External browser')
        ext_btn.setToolTip(
            'Try the system default browser (may fail on KDE/root; '
            'use this window if so)'
        )
        ext_btn.clicked.connect(self._open_external)
        _apply_primary_button_style(ext_btn)
        row.addWidget(ext_btn)
        lay.addLayout(row)

        self.web = QWebEngineView()
        self.web.setUrl(QUrl(self._url))
        lay.addWidget(self.web, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.close)
        lay.addWidget(btns)
        _prepare_dialog_buttons(self)

    def _open_external(self):
        qurl = QUrl(self._url)
        try:
            if QDesktopServices.openUrl(qurl):
                return
        except Exception:
            pass
        QMessageBox.information(
            self,
            'External browser',
            'Could not launch the system browser (KDE portal / xdg-open may '
            'be misconfigured on this machine).\n\n'
            f'Use this window, or copy the URL:\n{self._url}',
        )


def _forecasts_tab_from_parent(parent):
    return parent if isinstance(parent, ForecastsTab) else None


def _sync_forecasts_tab_latlon(forecasts_tab, lat, lon):
    """Write lat/lon into ForecastsTab fields without editingFinished side-effects."""
    lat_edit = forecasts_tab.solar_edits['lat']
    lon_edit = forecasts_tab.solar_edits['lon']
    lat_edit.blockSignals(True)
    lon_edit.blockSignals(True)
    try:
        lat_edit.setText(f'{float(lat):.5f}')
        lon_edit.setText(f'{float(lon):.5f}')
    finally:
        lat_edit.blockSignals(False)
        lon_edit.blockSignals(False)


def _parse_map_pin_latlon(result):
    """Decode getPinLatLon JSON from the Leaflet map page."""
    if result is None:
        return None, None
    if isinstance(result, str) and result.strip():
        try:
            o = json.loads(result)
            return float(o['lat']), float(o['lng'])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
    try:
        if isinstance(result, str) and ',' in result:
            parts = result.replace('[', '').replace(']', '').split(',')
            if len(parts) >= 2:
                return float(parts[0].strip()), float(parts[1].strip())
        if hasattr(result, '__len__') and len(result) >= 2:
            a0, a1 = result[0], result[1]
            if hasattr(a0, 'toDouble'):
                return float(a0.toDouble()), float(a1.toDouble())
            return float(a0), float(a1)
    except (TypeError, ValueError, IndexError, AttributeError):
        pass
    return None, None


def _open_forecast_location_dialog(lat, lon, parent=None, w3w_api_key=''):
    """Leaflet map when WebEngine is available; text/search fallback otherwise."""
    forecasts_tab = _forecasts_tab_from_parent(parent)
    note = None
    if _map_picker_webengine_enabled():
        try:
            return MapPickerDialog(
                lat, lon, parent=parent, w3w_api_key=w3w_api_key,
                forecasts_tab=forecasts_tab,
            )
        except _MapPickerUnavailable as e:
            note = str(e)
        except Exception as e:
            note = str(e)
            try:
                _log.warn('Map picker', f'WebEngine map failed: {e}')
            except Exception:
                pass
    elif _map_picker_webengine_available():
        note = (
            'Embedded map is off (POWERMODEL_MAP_WEBENGINE=0). Use search or '
            'coordinates below, or unset that variable and restart to use the map.'
        )
    else:
        note = (
            'Qt WebEngine is not installed. Install with: '
            '<code>pip install PySide6-Addons</code> (same Python as this app), '
            'then restart. You can still search or type coordinates below.'
        )
    return SimpleLocationPickerDialog(
        lat, lon, parent=parent, w3w_api_key=w3w_api_key, note=note,
        forecasts_tab=forecasts_tab,
    )


class SimpleLocationPickerDialog(QDialog):
    """Set forecast location without Qt WebEngine (lat/lon, place search, w3w)."""

    def __init__(
        self, init_lat, init_lon, parent=None, w3w_api_key='',
        note=None, forecasts_tab=None,
    ):
        super().__init__(parent)
        self._inv = Invoker(self)
        self._w3w_api_key = (w3w_api_key or '').strip()
        self._forecasts_tab = forecasts_tab or _forecasts_tab_from_parent(parent)
        self._chosen_lat = None
        self._chosen_lon = None
        self.setWindowTitle('Set forecast location')
        self.resize(520, 320)
        lay = QVBoxLayout(self)
        if note:
            hint = QLabel(
                f"<p style='color:#fab387;'>{note}</p>"
                "<p style='color:#a6adc8;'>Use the fields below — coordinates are "
                "WGS84 (EPSG:4326), same as the Lat/Lon boxes on the Forecasts tab.</p>"
            )
            hint.setWordWrap(True)
            hint.setTextFormat(Qt.RichText)
            lay.addWidget(hint)
        form = QGridLayout()
        form.addWidget(QLabel('Latitude:'), 0, 0)
        self.lat_edit = QLineEdit(f'{float(init_lat):.5f}')
        self.lat_edit.setFixedWidth(120)
        form.addWidget(self.lat_edit, 0, 1)
        form.addWidget(QLabel('Longitude:'), 1, 0)
        self.lon_edit = QLineEdit(f'{float(init_lon):.5f}')
        self.lon_edit.setFixedWidth(120)
        form.addWidget(self.lon_edit, 1, 1)
        lay.addLayout(form)
        place_row = QHBoxLayout()
        place_row.addWidget(QLabel('Search place:'))
        self.place_edit = QLineEdit()
        self.place_edit.setPlaceholderText('e.g. Oakley, UK or postcode')
        place_row.addWidget(self.place_edit, 1)
        self.place_btn = QPushButton('Search')
        self.place_btn.clicked.connect(self._search_place)
        place_row.addWidget(self.place_btn)
        lay.addLayout(place_row)
        w3w_row = QHBoxLayout()
        w3w_row.addWidget(QLabel('what3words:'))
        self.w3w_edit = QLineEdit()
        self.w3w_edit.setPlaceholderText('filled.count.soap')
        w3w_row.addWidget(self.w3w_edit, 1)
        self.w3w_btn = QPushButton('Look up')
        self.w3w_btn.clicked.connect(self._lookup_w3w)
        w3w_row.addWidget(self.w3w_btn)
        lay.addLayout(w3w_row)
        self.status_label = QLabel('')
        self.status_label.setStyleSheet('color: #a6adc8; font-size: 11px;')
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)
        btn_row = QHBoxLayout()
        if self._forecasts_tab is not None:
            save_btn = QPushButton('Save parameters')
            save_btn.setStyleSheet(_SUBTLE_BTN_QSS)
            save_btn.setToolTip(
                'Write Lat/Lon/Tilt/Azimuth/kWp to saved settings (shared with '
                'Setup && Info) using coordinates from this dialog and the '
                'Forecasts tab row, then refresh the locale label.'
            )
            save_btn.clicked.connect(self._on_save_parameters)
            btn_row.addWidget(save_btn)
        btn_row.addStretch()
        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self,
        )
        btns.accepted.connect(self._accept_coords)
        btns.rejected.connect(self.reject)
        btn_row.addWidget(btns)
        lay.addLayout(btn_row)
        _prepare_dialog_buttons(self)

    def _read_latlon_fields(self):
        try:
            return float(self.lat_edit.text()), float(self.lon_edit.text())
        except (ValueError, TypeError):
            return None, None

    def _on_save_parameters(self):
        if self._forecasts_tab is None:
            return
        la, lo = self._read_latlon_fields()
        if la is None:
            QMessageBox.warning(
                self, 'Invalid coordinates',
                'Latitude and longitude must be numbers.',
            )
            return
        if not (-90 <= la <= 90 and -180 <= lo <= 180):
            QMessageBox.warning(
                self, 'Out of range',
                'Latitude must be −90…90 and longitude −180…180.',
            )
            return
        _sync_forecasts_tab_latlon(self._forecasts_tab, la, lo)
        self._forecasts_tab._save_forecast_parameters_clicked()
        self.status_label.setText(
            f'Saved solar parameters ({la:.5f}, {lo:.5f}).'
        )

    def _set_coords(self, la, lo, status=''):
        self.lat_edit.setText(f'{la:.5f}')
        self.lon_edit.setText(f'{lo:.5f}')
        if status:
            self.status_label.setText(status)

    def _search_place(self):
        q = self.place_edit.text().strip()
        self.status_label.setText('Searching…')
        self.place_btn.setEnabled(False)
        threading.Thread(
            target=self._place_thread, args=(q,), daemon=True,
        ).start()

    def _place_thread(self, query):
        la, lo, msg = _nominatim_lookup_place(query)
        self._inv.invoke(lambda: self._place_done(la, lo, msg))

    def _place_done(self, la, lo, msg):
        self.place_btn.setEnabled(True)
        if la is None:
            self.status_label.setText(f'Search failed: {msg}')
            return
        self._set_coords(la, lo, msg or f'Found: {la:.5f}, {lo:.5f}')

    def _lookup_w3w(self):
        self.w3w_btn.setEnabled(False)
        self.status_label.setText('Looking up what3words…')
        words = self.w3w_edit.text()
        threading.Thread(
            target=self._w3w_thread, args=(words,), daemon=True,
        ).start()

    def _w3w_thread(self, words):
        la, lo, err = _w3w_lookup_coordinates(words, self._w3w_api_key)
        self._inv.invoke(lambda: self._w3w_done(la, lo, err))

    def _w3w_done(self, la, lo, err):
        self.w3w_btn.setEnabled(True)
        if la is None:
            self.status_label.setText(f'what3words: {err}')
            return
        self._set_coords(la, lo, f'what3words → {la:.5f}, {lo:.5f}')

    def _accept_coords(self):
        la, lo = self._read_latlon_fields()
        if la is None:
            QMessageBox.warning(
                self, 'Invalid coordinates',
                'Latitude and longitude must be numbers.',
            )
            return
        if not (-90 <= la <= 90 and -180 <= lo <= 180):
            QMessageBox.warning(
                self, 'Out of range',
                'Latitude must be −90…90 and longitude −180…180.',
            )
            return
        self._chosen_lat = la
        self._chosen_lon = lo
        self.accept()

    def chosen_latlon(self):
        return self._chosen_lat, self._chosen_lon


class MapPickerDialog(QDialog):
    """Modal dialog with an OpenStreetMap (Leaflet) view and a draggable pin.

    The map is rendered inside a QWebEngineView; the user clicks (or drags)
    to position the marker, or types a what3words address to jump to it.
    The chosen lat/lon are read back via runJavaScript when the user clicks
    'Use this location'.
    """

    _LEAFLET_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Pick location</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html, body, #map { margin:0; padding:0; height:100%; width:100%; background:#1e1e2e; }
  .pin-readout {
    position: absolute; top: 8px; right: 8px; z-index: 1000;
    background: rgba(30,30,46,0.92); color: #cdd6f4;
    padding: 4px 8px; border-radius: 4px;
    font: 12px/1.3 'Helvetica',sans-serif;
    border: 1px solid #45475a;
  }
</style>
</head>
<body>
  <div id="map"></div>
  <div id="readout" class="pin-readout">--</div>
<script>
  var lat = __INIT_LAT__, lon = __INIT_LON__;
  var map = L.map('map').setView([lat, lon], 15);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);
  var marker = L.marker([lat, lon], {draggable: true}).addTo(map);

  function _update(latlng) {
    window.__lat = latlng.lat;
    window.__lon = latlng.lng;
    document.getElementById('readout').innerText =
      'Pin: ' + latlng.lat.toFixed(5) + ', ' + latlng.lng.toFixed(5);
    document.title = 'PIN ' + latlng.lat.toFixed(5) + ',' + latlng.lng.toFixed(5);
  }
  _update(marker.getLatLng());
  map.on('click', function(e) { marker.setLatLng(e.latlng); _update(e.latlng); });
  marker.on('dragend', function() { _update(marker.getLatLng()); });

  /* Return JSON — Qt WebEngine may deserialize JS arrays into types that do not
     slice/index like Python lists, which broke reading [lat, lon] in PySide. */
  window.getPinLatLon = function() {
    var ll = marker.getLatLng();
    return JSON.stringify({ lat: ll.lat, lng: ll.lng });
  };
  window.setPinLatLon = function(la, lo) {
    var ll = L.latLng(la, lo);
    marker.setLatLng(ll);
    map.setView(ll, Math.max(map.getZoom(), 16));
    _update(ll);
  };
</script>
</body>
</html>
"""

    def __init__(
        self, init_lat, init_lon, parent=None, w3w_api_key="",
        forecasts_tab=None,
    ):
        super().__init__(parent)
        # Probe for QtWebEngine without keeping an unused symbol around;
        # the real import happens in `_build_ui` where we actually use it.
        import importlib.util
        if importlib.util.find_spec("PySide6.QtWebEngineWidgets") is None:
            raise _MapPickerUnavailable("PySide6.QtWebEngineWidgets is not installed")

        self.setWindowTitle("Pick location on map")
        self.resize(900, 700)
        self._init_lat = float(init_lat)
        self._init_lon = float(init_lon)
        self._chosen_lat = None
        self._chosen_lon = None
        self._w3w_api_key = (w3w_api_key or "").strip()
        self._forecasts_tab = forecasts_tab or _forecasts_tab_from_parent(parent)
        self._inv = Invoker(self)
        self._w3w_forward_in_flight = False
        self._w3w_reverse_key = None
        self._w3w_reverse_timer = QTimer(self)
        self._w3w_reverse_timer.setSingleShot(True)
        self._w3w_reverse_timer.setInterval(450)
        self._w3w_reverse_timer.timeout.connect(self._run_w3w_reverse_lookup)
        self._build_ui()

    def _build_ui(self):
        from PySide6.QtWebEngineWidgets import QWebEngineView
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # ── what3words / direct lat-lon row ───────────────────────────────
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("what3words:"))
        self.w3w_edit = QLineEdit()
        self.w3w_edit.setPlaceholderText("e.g. filled.count.soap")
        self.w3w_edit.setFixedWidth(220)
        top_row.addWidget(self.w3w_edit)
        self.w3w_btn = QPushButton("Look up")
        self.w3w_btn.clicked.connect(self._lookup_w3w_async)
        top_row.addWidget(self.w3w_btn)

        top_row.addSpacing(20)
        top_row.addWidget(QLabel("or jump to:"))
        self.jump_lat = QLineEdit(f"{self._init_lat:.5f}")
        self.jump_lat.setFixedWidth(90)
        self.jump_lon = QLineEdit(f"{self._init_lon:.5f}")
        self.jump_lon.setFixedWidth(90)
        top_row.addWidget(self.jump_lat)
        top_row.addWidget(QLabel(","))
        top_row.addWidget(self.jump_lon)
        self.jump_btn = QPushButton("Go")
        self.jump_btn.clicked.connect(self._jump_to_coords)
        top_row.addWidget(self.jump_btn)

        top_row.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        top_row.addWidget(self.status_label)
        lay.addLayout(top_row)

        # ── Map view ──────────────────────────────────────────────────────
        self.web = QWebEngineView()
        html = (self._LEAFLET_HTML
                .replace("__INIT_LAT__", f"{self._init_lat:.6f}")
                .replace("__INIT_LON__", f"{self._init_lon:.6f}"))
        # baseUrl set to https so OSM tile + leaflet CDN load over TLS
        from PySide6.QtCore import QUrl
        self.web.setHtml(html, QUrl("https://localhost/"))
        self.web.loadFinished.connect(self._on_map_load_finished)
        self.web.page().titleChanged.connect(self._on_map_pin_title_changed)
        lay.addWidget(self.web, 1)

        crs = QLabel("CRS: WGS84 (EPSG:4326) · tiles © OpenStreetMap contributors")
        crs.setStyleSheet("color: #6c7086; font-size: 10px;")
        lay.addWidget(crs)

        # ── Buttons ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        if self._forecasts_tab is not None:
            save_btn = QPushButton("Save parameters")
            save_btn.setStyleSheet(_SUBTLE_BTN_QSS)
            save_btn.setToolTip(
                "Persist Lat/Lon from the map (or jump fields) plus Tilt/Azimuth/kWp "
                "from the Forecasts tab."
            )
            save_btn.clicked.connect(self._on_save_parameters)
            btn_row.addWidget(save_btn)
        btn_row.addStretch()
        btns = QDialogButtonBox()
        ok = btns.addButton("Use this location", QDialogButtonBox.AcceptRole)
        cancel = btns.addButton(QDialogButtonBox.Cancel)
        ok.clicked.connect(self._accept_with_pin)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(btns)
        lay.addLayout(btn_row)
        _prepare_dialog_buttons(self)

    def _jump_to_coords(self):
        try:
            la = float(self.jump_lat.text())
            lo = float(self.jump_lon.text())
        except ValueError:
            self.status_label.setText("Invalid lat/lon")
            return
        self.web.page().runJavaScript(
            f"window.setPinLatLon({la}, {lo});"
        )
        self.status_label.setText(f"Jumped to {la:.5f}, {lo:.5f}")

    def _on_map_load_finished(self, ok):
        if not ok:
            return
        self.web.page().runJavaScript(
            "window.getPinLatLon();",
            lambda r: self._apply_pin_from_js(r, refresh_w3w=True),
        )

    def _on_map_pin_title_changed(self, title):
        """Leaflet sets document.title to PIN lat,lon on click/drag."""
        if not (title or "").startswith("PIN "):
            return
        body = title[4:].strip()
        if "," not in body:
            return
        lat_s, lon_s = body.split(",", 1)
        try:
            la = float(lat_s.strip())
            lo = float(lon_s.strip())
        except ValueError:
            return
        self._sync_jump_fields(la, lo)
        self._schedule_w3w_reverse(la, lo)

    def _parse_pin_js_result(self, result):
        return _parse_map_pin_latlon(result)

    def _sync_jump_fields(self, la, lo):
        self.jump_lat.setText(f"{la:.5f}")
        self.jump_lon.setText(f"{lo:.5f}")

    def _apply_pin_from_js(self, result, refresh_w3w=False):
        la, lo = self._parse_pin_js_result(result)
        if la is None:
            return
        self._sync_jump_fields(la, lo)
        if refresh_w3w:
            self._schedule_w3w_reverse(la, lo)

    def _schedule_w3w_reverse(self, lat, lon):
        if not self._w3w_api_key or self._w3w_forward_in_flight:
            return
        self._w3w_reverse_key = (
            round(float(lat), 5),
            round(float(lon), 5),
        )
        self._w3w_reverse_timer.start()

    def _run_w3w_reverse_lookup(self):
        key = self._w3w_reverse_key
        if key is None or not self._w3w_api_key:
            return
        la, lo = key
        self.status_label.setText("Looking up what3words for pin…")

        def _thread():
            words, err = _w3w_lookup_words(la, lo, self._w3w_api_key)
            self._inv.invoke(
                lambda w=words, e=err, k=key: self._w3w_reverse_done(k, w, e)
            )

        threading.Thread(target=_thread, daemon=True).start()

    def _w3w_reverse_done(self, key, words, err):
        if key != self._w3w_reverse_key:
            return
        if words:
            self.w3w_edit.blockSignals(True)
            self.w3w_edit.setText(words)
            self.w3w_edit.blockSignals(False)
            self.status_label.setText(f"Pin → ///{words}")
        elif err:
            self.status_label.setText(f"what3words (pin): {err}")

    def _lookup_w3w_async(self):
        """Words → coordinates: move the map pin."""
        words = self.w3w_edit.text().strip().lstrip('/')
        if not words:
            self.status_label.setText(
                "Enter three words separated by dots (e.g. filled.count.soap)"
            )
            return
        self._w3w_forward_in_flight = True
        self._w3w_reverse_timer.stop()
        self.status_label.setText('Looking up what3words…')
        self.w3w_btn.setEnabled(False)
        threading.Thread(
            target=self._w3w_thread, args=(words,), daemon=True,
        ).start()

    def _w3w_thread(self, words):
        la, lo, err = _w3w_lookup_coordinates(words, self._w3w_api_key)
        self._inv.invoke(lambda: self._w3w_done(la, lo, err, words))

    def _w3w_done(self, la, lo, err, words=''):
        self.w3w_btn.setEnabled(True)
        self._w3w_forward_in_flight = False
        if la is None:
            self.status_label.setText(f'what3words lookup failed: {err}')
            return
        self._w3w_reverse_key = (round(la, 5), round(lo, 5))
        self.jump_lat.setText(f'{la:.5f}')
        self.jump_lon.setText(f'{lo:.5f}')
        w = (words or self.w3w_edit.text()).strip().lstrip('/')
        if w:
            self.w3w_edit.blockSignals(True)
            self.w3w_edit.setText(w)
            self.w3w_edit.blockSignals(False)
        self.web.page().runJavaScript(f'window.setPinLatLon({la}, {lo});')
        self.status_label.setText(f'what3words → {la:.5f}, {lo:.5f}')

    def _read_jump_latlon(self):
        try:
            return float(self.jump_lat.text()), float(self.jump_lon.text())
        except (ValueError, TypeError):
            return None, None

    def _apply_save_to_forecasts_tab(self, la, lo):
        if self._forecasts_tab is None or la is None:
            return False
        _sync_forecasts_tab_latlon(self._forecasts_tab, la, lo)
        self._forecasts_tab._save_forecast_parameters_clicked()
        self.status_label.setText(f'Saved solar parameters ({la:.5f}, {lo:.5f}).')
        return True

    def _on_save_parameters(self):
        if self._forecasts_tab is None:
            return

        def _cb(result):
            la, lo = _parse_map_pin_latlon(result)
            if la is None:
                la, lo = self._read_jump_latlon()
            if la is None:
                self.status_label.setText("Couldn't read pin from map")
                return
            if not (-90 <= la <= 90 and -180 <= lo <= 180):
                self.status_label.setText('Lat/lon out of range')
                return
            self._apply_save_to_forecasts_tab(la, lo)

        self.web.page().runJavaScript("window.getPinLatLon();", _cb)

    def _accept_with_pin(self):
        def _cb(result):
            la, lo = _parse_map_pin_latlon(result)
            if la is None or lo is None:
                self.status_label.setText("Couldn't read pin from map")
                return
            self._chosen_lat = la
            self._chosen_lon = lo
            self.accept()

        self.web.page().runJavaScript("window.getPinLatLon();", _cb)

    def chosen_latlon(self):
        return self._chosen_lat, self._chosen_lon


__all__ = [n for n in globals() if not n.startswith('__')]
