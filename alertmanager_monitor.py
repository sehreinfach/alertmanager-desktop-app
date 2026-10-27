#!/usr/bin/env python3
"""
AlertManager Monitor — GNOME Desktop App
Shows a persistent indicator button that sits in the panel area (bottom bar),
using a borderless DOCK-type GTK window on X11.  Works on GNOME Shell 40+
without any extra extension.

Panel indicator behaviour:
  • Grey bell     → no alerts
  • Flashing red  → active alerts
  • Grey ⏸       → paused

Left-click        → open/close the alert detail window
Right-click       → context menu  (Pause / Resume, Check now, Quit)
Middle-click/drag → drag the indicator to any desktop position
                    Position is saved to conf.json and restored on restart.
                    Right-click → "Reset to panel" snaps it back to the panel.
"""

import gi
gi.require_version('Gtk',      '3.0')
gi.require_version('GLib',     '2.0')
gi.require_version('Gdk',      '3.0')
gi.require_version('GdkPixbuf','2.0')
gi.require_version('Notify',   '0.7')
gi.require_version('Gst',      '1.0')

from gi.repository import Gtk, GLib, Gdk, GdkPixbuf, Notify, Gst

import json
import os
import threading
import urllib.request
import urllib.error
import base64
import datetime

# ── paths ──────────────────────────────────────────────────────────────────────
APP_DIR     = os.path.dirname(os.path.abspath(__file__))
ICONS_DIR   = os.path.join(APP_DIR, "icons")
CONFIG_FILE = os.path.join(APP_DIR, "conf.json")
APP_NAME    = "AlertManager Monitor"

# ── defaults ───────────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "alertmanager_url": "http://localhost:9093",
    "username":         "",
    "password":         "",
    "check_interval":   30,
    "sound_enabled":    True,
    "sound_file":       "/usr/share/sounds/freedesktop/stereo/dialog-warning.oga",
    # Floating indicator position — None means "auto-place in panel"
    "indicator_x":      None,
    "indicator_y":      None,
}

# Panel geometry (read once at start from dconf; fall back to 48 px at bottom)
PANEL_HEIGHT   = 48
PANEL_POSITION = "BOTTOM"   # "TOP" or "BOTTOM"
INDICATOR_W    = 120        # width of the indicator button in the panel


# ══════════════════════════════════════════════════════════════════════════════
#  Panel geometry helpers
# ══════════════════════════════════════════════════════════════════════════════
def _read_panel_geometry():
    """Read dash-to-panel (or fall back to GNOME Shell defaults)."""
    global PANEL_HEIGHT, PANEL_POSITION
    try:
        import subprocess, json as _json

        out = subprocess.check_output(
            ["dconf", "read",
             "/org/gnome/shell/extensions/dash-to-panel/panel-sizes"],
            stderr=subprocess.DEVNULL
        ).decode().strip().strip("'")
        if out:
            sizes = _json.loads(out)
            PANEL_HEIGHT = list(sizes.values())[0]

        out = subprocess.check_output(
            ["dconf", "read",
             "/org/gnome/shell/extensions/dash-to-panel/panel-positions"],
            stderr=subprocess.DEVNULL
        ).decode().strip().strip("'")
        if out:
            positions = _json.loads(out)
            PANEL_POSITION = list(positions.values())[0]   # "TOP" or "BOTTOM"
    except Exception:
        pass   # use defaults


# ══════════════════════════════════════════════════════════════════════════════
#  Config
# ══════════════════════════════════════════════════════════════════════════════
def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as f:
                cfg.update(json.load(f))
    except Exception as e:
        print(f"[WARN] Could not load config: {e}")
    return cfg


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        print(f"[WARN] Could not save config: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  Alertmanager API
# ══════════════════════════════════════════════════════════════════════════════
def fetch_alerts(cfg: dict):
    """Returns (alerts_list, error_string|None)."""
    url = cfg["alertmanager_url"].rstrip("/") + \
          "/api/v2/alerts?active=true&silenced=false&inhibited=false"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    user, pwd = cfg.get("username", ""), cfg.get("password", "")
    if user:
        tok = base64.b64encode(f"{user}:{pwd}".encode()).decode()
        req.add_header("Authorization", f"Basic {tok}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            return (data, None) if isinstance(data, list) else ([], "Unexpected format")
    except urllib.error.HTTPError as e:
        return [], f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return [], f"Connection error: {e.reason}"
    except Exception as e:
        return [], str(e)


# ══════════════════════════════════════════════════════════════════════════════
#  Sound
# ══════════════════════════════════════════════════════════════════════════════
class SoundPlayer:
    def __init__(self):
        Gst.init(None)
        self._pipeline = None

    def play(self, path: str):
        if not path or not os.path.exists(path):
            print(f"[WARN] Sound not found: {path}")
            return
        try:
            if self._pipeline:
                self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = Gst.parse_launch(
                f'filesrc location="{path}" ! decodebin '
                f'! audioconvert ! audioresample ! autoaudiosink'
            )
            self._pipeline.set_state(Gst.State.PLAYING)
        except Exception as e:
            print(f"[WARN] Sound failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  Panel Indicator window  (now freely draggable)
# ══════════════════════════════════════════════════════════════════════════════
class PanelIndicator:
    """
    A small borderless DOCK window that sits in the panel by default.

    Dragging:
      Hold left button and move the mouse to reposition the indicator anywhere
      on the desktop.  The position is saved to conf.json and restored on the
      next start.  The indicator must be moved more than DRAG_THRESHOLD pixels
      before it is considered a drag (so short clicks still open the window).

    Reset:
      "Reset to panel position" in the right-click context menu snaps the
      indicator back to its default panel corner and clears the saved position.

    On X11 / GNOME Shell (both vanilla and dash-to-panel) a DOCK-type window
    is always on top and not included in the window list.
    """

    _FLASH_MS       = 600
    _MARGIN_R       = 4     # px gap from right screen edge (default position)
    _DRAG_THRESHOLD = 5     # pixels of movement before drag mode activates

    # colours
    _COL_NORMAL = "#3d3d3d"
    _COL_ALERT  = "#cc0000"
    _COL_PAUSED = "#5a5a5a"
    _COL_TEXT   = "#ffffff"

    def __init__(self, app: "AlertMonitorApp"):
        self.app = app

        self._state       = "normal"   # "normal" | "alert" | "paused"
        self._flash_on    = True
        self._flash_timer = None
        self._alert_count = 0
        self._tooltip_txt = APP_NAME

        # ── drag state ─────────────────────────────────────────────────────────
        self._drag_active      = False   # True once threshold exceeded
        self._drag_btn_held    = False   # True while button 1 is held
        self._drag_start_x     = 0       # pointer X at button-press (screen)
        self._drag_start_y     = 0       # pointer Y at button-press (screen)
        self._drag_win_start_x = 0       # window X at button-press
        self._drag_win_start_y = 0       # window Y at button-press

        # ── window ─────────────────────────────────────────────────────────────
        self._win = Gtk.Window(type=Gtk.WindowType.POPUP)
        self._win.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self._win.set_decorated(False)
        self._win.set_resizable(False)
        self._win.set_keep_above(True)
        self._win.set_skip_taskbar_hint(True)
        self._win.set_skip_pager_hint(True)
        self._win.set_app_paintable(True)
        self._win.set_default_size(INDICATOR_W, PANEL_HEIGHT)

        # CSS for rounded pill appearance
        ctx = self._win.get_style_context()
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            window {
                background: transparent;
                border-radius: 0;
            }
        """)
        ctx.add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # ── event box (catches clicks & motion) ────────────────────────────────
        self._ebox = Gtk.EventBox()
        self._ebox.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK   |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK
        )
        self._ebox.connect("button-press-event",   self._on_button_press)
        self._ebox.connect("button-release-event", self._on_button_release)
        self._ebox.connect("motion-notify-event",  self._on_motion)
        self._win.add(self._ebox)

        # ── drawing area ───────────────────────────────────────────────────────
        self._da = Gtk.DrawingArea()
        self._da.connect("draw", self._on_draw)
        self._ebox.add(self._da)

        # load icon pixbufs
        self._pb: dict[str, GdkPixbuf.Pixbuf | None] = {
            "normal": self._load_pb("alert-normal.svg"),
            "alert":  self._load_pb("alert-active.svg"),
            "paused": self._load_pb("alert-paused.svg"),
        }

        self._position()
        self._win.show_all()

    # ── positioning ────────────────────────────────────────────────────────────
    def _default_panel_xy(self):
        """Return (x, y) for the default panel-corner position."""
        display = Gdk.Display.get_default()
        monitor = display.get_monitor(0)
        geo     = monitor.get_geometry()
        sw, sh  = geo.width, geo.height
        x = sw - INDICATOR_W - self._MARGIN_R
        y = sh - PANEL_HEIGHT if PANEL_POSITION == "BOTTOM" else 0
        return x, y

    def _position(self):
        """Place the window: use saved position if available, else panel corner."""
        cfg = self.app.config
        sx = cfg.get("indicator_x")
        sy = cfg.get("indicator_y")
        if sx is not None and sy is not None:
            x, y = int(sx), int(sy)
        else:
            x, y = self._default_panel_xy()
        self._win.move(x, y)
        self._win.resize(INDICATOR_W, PANEL_HEIGHT)

    def reset_to_panel(self):
        """Snap the indicator back to the default panel position and clear the saved pos."""
        x, y = self._default_panel_xy()
        self._win.move(x, y)
        self.app.config["indicator_x"] = None
        self.app.config["indicator_y"] = None
        save_config(self.app.config)

    # ── icon loading ───────────────────────────────────────────────────────────
    def _load_pb(self, name: str):
        path = os.path.join(ICONS_DIR, name)
        size = max(PANEL_HEIGHT - 12, 16)
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size)
        except Exception:
            return None

    # ── drawing ────────────────────────────────────────────────────────────────
    def _on_draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()

        # background pill
        if self._state == "alert" and self._flash_on:
            r, g, b = 0.80, 0.05, 0.05
        elif self._state == "paused":
            r, g, b = 0.35, 0.35, 0.35
        else:
            r, g, b = 0.24, 0.24, 0.24

        radius = h * 0.3
        cr.new_sub_path()
        cr.arc(radius,     radius,     radius, 3.14159, 1.5*3.14159)
        cr.arc(w - radius, radius,     radius, 1.5*3.14159, 0)
        cr.arc(w - radius, h - radius, radius, 0, 0.5*3.14159)
        cr.arc(radius,     h - radius, radius, 0.5*3.14159, 3.14159)
        cr.close_path()
        cr.set_source_rgba(r, g, b, 0.92)
        cr.fill()

        # drag-handle grip dots (three vertical pairs on the left edge)
        grip_alpha = 0.55 if self._drag_active else 0.30
        cr.set_source_rgba(1, 1, 1, grip_alpha)
        dot_r  = 1.5
        gx     = 5.5          # horizontal centre of grip dots
        for col in range(2):
            cx = gx + col * 5
            for row in range(3):
                cy = h * 0.25 + row * (h * 0.25)
                cr.arc(cx, cy, dot_r, 0, 6.28318)
                cr.fill()

        # icon
        icon_key = "paused" if self._state == "paused" else \
                   ("alert" if (self._state == "alert" and self._flash_on)
                    else "normal")
        pb = self._pb.get(icon_key)
        icon_w = 0
        if pb:
            icon_w = pb.get_width()
            icon_h = pb.get_height()
            ix = 20           # shifted right a bit to leave room for grip dots
            iy = (h - icon_h) / 2
            import gi as _gi
            from gi.repository import Gdk as _Gdk
            _Gdk.cairo_set_source_pixbuf(cr, pb, ix, iy)
            cr.paint()

        # label text
        if self._state == "alert" and self._alert_count > 0:
            label = f"  ⚠ {self._alert_count}"
        elif self._state == "paused":
            label = "  Paused"
        else:
            label = "  OK"

        cr.set_source_rgba(1, 1, 1, 0.95)
        cr.select_font_face("Sans", 0, 1)   # bold
        font_size = max(h * 0.32, 11)
        cr.set_font_size(font_size)
        tx = icon_w + 24      # account for grip dots + icon offset
        ty = h * 0.65
        cr.move_to(tx, ty)
        cr.show_text(label)

        return False

    # ── drag logic ─────────────────────────────────────────────────────────────
    def _on_button_press(self, widget, event):
        if event.button == 1:
            self._drag_btn_held    = True
            self._drag_active      = False
            self._drag_start_x     = event.x_root
            self._drag_start_y     = event.y_root
            wx, wy = self._win.get_position()
            self._drag_win_start_x = wx
            self._drag_win_start_y = wy
        elif event.button == 3:
            # Right-click: handled on release to avoid conflict with drag
            pass
        return True

    def _on_button_release(self, widget, event):
        if event.button == 1:
            was_drag = self._drag_active
            self._drag_btn_held = False
            self._drag_active   = False
            self._redraw()      # clear drag highlight

            if was_drag:
                # Save the new position to config
                x, y = self._win.get_position()
                self.app.config["indicator_x"] = x
                self.app.config["indicator_y"] = y
                save_config(self.app.config)
            else:
                # Short click → toggle main window
                self.app.toggle_main_window()

        elif event.button == 3:
            self.app.show_tray_menu(int(event.x_root), int(event.y_root))

        return True

    def _on_motion(self, widget, event):
        if not self._drag_btn_held:
            return False

        dx = event.x_root - self._drag_start_x
        dy = event.y_root - self._drag_start_y

        if not self._drag_active:
            if (dx * dx + dy * dy) >= self._DRAG_THRESHOLD ** 2:
                self._drag_active = True
                self._redraw()   # brighten grip dots while dragging

        if self._drag_active:
            nx = int(self._drag_win_start_x + dx)
            ny = int(self._drag_win_start_y + dy)
            self._win.move(nx, ny)

        return True

    # ── public state API ───────────────────────────────────────────────────────
    def set_normal(self, tip: str = "No active alerts"):
        self._stop_flash()
        self._state       = "normal"
        self._alert_count = 0
        self._tooltip_txt = f"{APP_NAME} — {tip}"
        self._win.set_tooltip_text(self._tooltip_txt)
        self._redraw()

    def set_alert(self, count: int, summary: str = ""):
        self._alert_count = count
        tip = f"{APP_NAME} — ⚠ {count} active alert(s)"
        if summary:
            tip += f"\n{summary}"
        self._tooltip_txt = tip
        self._win.set_tooltip_text(tip)
        self._start_flash()

    def set_paused(self):
        self._stop_flash()
        self._state       = "paused"
        self._alert_count = 0
        self._tooltip_txt = f"{APP_NAME} — Paused"
        self._win.set_tooltip_text(self._tooltip_txt)
        self._redraw()

    # ── flash ──────────────────────────────────────────────────────────────────
    def _start_flash(self):
        self._state = "alert"
        if self._flash_timer is None:
            self._flash_on    = True
            self._flash_timer = GLib.timeout_add(self._FLASH_MS, self._flash_tick)
        self._redraw()

    def _stop_flash(self):
        if self._flash_timer is not None:
            GLib.source_remove(self._flash_timer)
            self._flash_timer = None

    def _flash_tick(self) -> bool:
        self._flash_on = not self._flash_on
        self._redraw()
        return True

    def _redraw(self):
        self._da.queue_draw()


# ══════════════════════════════════════════════════════════════════════════════
#  Settings Dialog
# ══════════════════════════════════════════════════════════════════════════════
class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, cfg: dict):
        super().__init__(title="Settings", transient_for=parent, modal=True)
        self.set_default_size(480, 360)
        self.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                         Gtk.STOCK_SAVE,   Gtk.ResponseType.OK)

        grid = Gtk.Grid(column_spacing=12, row_spacing=10,
                        margin_start=18, margin_end=18,
                        margin_top=18, margin_bottom=18)
        self.get_content_area().pack_start(grid, True, True, 0)

        def lbl(t):
            return Gtk.Label(label=t, xalign=1.0)

        grid.attach(lbl("Alertmanager URL:"), 0, 0, 1, 1)
        self._url = Gtk.Entry(text=cfg.get("alertmanager_url", ""), hexpand=True)
        grid.attach(self._url, 1, 0, 2, 1)

        grid.attach(lbl("Username:"), 0, 1, 1, 1)
        self._user = Gtk.Entry(text=cfg.get("username", ""), hexpand=True)
        grid.attach(self._user, 1, 1, 2, 1)

        grid.attach(lbl("Password:"), 0, 2, 1, 1)
        self._pwd = Gtk.Entry(text=cfg.get("password", ""),
                              visibility=False, hexpand=True)
        grid.attach(self._pwd, 1, 2, 2, 1)

        grid.attach(lbl("Check interval (s):"), 0, 3, 1, 1)
        adj = Gtk.Adjustment(value=cfg.get("check_interval", 30),
                             lower=5, upper=3600, step_increment=5)
        self._interval = Gtk.SpinButton(adjustment=adj, digits=0)
        grid.attach(self._interval, 1, 3, 1, 1)

        grid.attach(lbl("Sound enabled:"), 0, 4, 1, 1)
        self._sound_en = Gtk.CheckButton(active=cfg.get("sound_enabled", True))
        grid.attach(self._sound_en, 1, 4, 1, 1)

        grid.attach(lbl("Sound file:"), 0, 5, 1, 1)
        self._sound_f = Gtk.Entry(text=cfg.get("sound_file", ""), hexpand=True)
        grid.attach(self._sound_f, 1, 5, 1, 1)
        btn = Gtk.Button(label="…")
        btn.connect("clicked", self._browse)
        grid.attach(btn, 2, 5, 1, 1)

        self.show_all()

    def _browse(self, _):
        dlg = Gtk.FileChooserDialog(title="Select sound file", parent=self,
                                    action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN,   Gtk.ResponseType.OK)
        ff = Gtk.FileFilter()
        ff.set_name("Audio files")
        for p in ("*.oga","*.ogg","*.wav","*.mp3"):
            ff.add_pattern(p)
        dlg.add_filter(ff)
        if dlg.run() == Gtk.ResponseType.OK:
            self._sound_f.set_text(dlg.get_filename())
        dlg.destroy()

    def get_config(self) -> dict:
        return {
            "alertmanager_url": self._url.get_text().strip(),
            "username":         self._user.get_text(),
            "password":         self._pwd.get_text(),
            "check_interval":   int(self._interval.get_value()),
            "sound_enabled":    self._sound_en.get_active(),
            "sound_file":       self._sound_f.get_text().strip(),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  Main Window
# ══════════════════════════════════════════════════════════════════════════════
class MainWindow(Gtk.Window):
    def __init__(self, app: "AlertMonitorApp"):
        super().__init__(title=APP_NAME)
        self.app = app
        self.set_default_size(720, 500)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", lambda *_: self.hide() or True)

        hb = Gtk.HeaderBar(title=APP_NAME, show_close_button=True)
        self.set_titlebar(hb)

        self._btn_pause = Gtk.Button()
        self._btn_pause.connect("clicked", lambda _: app.toggle_pause())
        hb.pack_start(self._btn_pause)

        btn_ref = Gtk.Button(label="↻ Refresh now")
        btn_ref.set_tooltip_text("Fetch alerts immediately")
        btn_ref.connect("clicked", lambda _: app.trigger_check())
        hb.pack_start(btn_ref)

        btn_cfg = Gtk.Button(label="⚙ Settings")
        btn_cfg.connect("clicked", self._open_settings)
        hb.pack_end(btn_cfg)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(vbox)

        self._status = Gtk.Label(xalign=0,
                                 margin_start=12, margin_end=12,
                                 margin_top=6,    margin_bottom=6)
        vbox.pack_start(self._status, False, False, 0)
        vbox.pack_start(Gtk.Separator(), False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        vbox.pack_start(scroll, True, True, 0)

        self._store = Gtk.ListStore(str, str, str, str, str)
        tv = Gtk.TreeView(model=self._store)
        tv.set_headers_visible(True)
        tv.set_grid_lines(Gtk.TreeViewGridLines.HORIZONTAL)

        for i, (title, w) in enumerate([
            ("Severity", 90), ("Alert", 180),
            ("Instance", 150), ("Summary", 240), ("Started", 155),
        ]):
            r = Gtk.CellRendererText(ellipsize=3)
            c = Gtk.TreeViewColumn(title, r, text=i)
            c.set_resizable(True)
            c.set_min_width(w)
            c.set_sort_column_id(i)
            tv.append_column(c)

        scroll.add(tv)
        self._sync_pause_btn()
        self._set_status("Initialising…")

    def _sync_pause_btn(self):
        if self.app.paused:
            self._btn_pause.set_label("▶ Resume")
            self._btn_pause.set_tooltip_text("Resume monitoring")
        else:
            self._btn_pause.set_label("⏸ Pause")
            self._btn_pause.set_tooltip_text("Pause monitoring")

    def _set_status(self, txt: str):
        self._status.set_markup(f"<small>{GLib.markup_escape_text(txt)}</small>")

    def _open_settings(self, _):
        dlg = SettingsDialog(self, self.app.config)
        if dlg.run() == Gtk.ResponseType.OK:
            self.app.apply_config(dlg.get_config())
        dlg.destroy()

    def refresh(self, alerts, error, paused, last_check):
        GLib.idle_add(self._do_refresh, alerts, error, paused, last_check)

    def _do_refresh(self, alerts, error, paused, last_check):
        self._store.clear()
        self._sync_pause_btn()
        if paused:
            self._set_status("⏸ Monitoring paused")
        elif error:
            self._set_status(f"⚠ Error: {error}  (last check: {last_check})")
        else:
            self._set_status(
                f"✔ Last check: {last_check} — {len(alerts)} active alert(s)"
            )
            for a in alerts:
                lb  = a.get("labels", {})
                ann = a.get("annotations", {})
                self._store.append([
                    lb.get("severity", "—"),
                    lb.get("alertname", "—"),
                    lb.get("instance", lb.get("job", "—")),
                    ann.get("summary", ann.get("description", "—")),
                    a.get("startsAt", "")[:19].replace("T", " "),
                ])
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Application
# ══════════════════════════════════════════════════════════════════════════════
class AlertMonitorApp:
    def __init__(self):
        _read_panel_geometry()

        self.config      = load_config()
        self.paused      = False
        self._alerts     : list = []
        self._last_error        = None
        self._last_check : str  = "never"
        self._had_alerts : bool = False
        self._timer_id          = None

        Notify.init(APP_NAME)
        self._sound     = SoundPlayer()
        self._indicator = PanelIndicator(self)
        self._window    = MainWindow(self)

        self._schedule(delay_ms=500)

    # ── scheduling ─────────────────────────────────────────────────────────────
    def _schedule(self, delay_ms=None):
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
        ms = delay_ms if delay_ms is not None \
             else self.config["check_interval"] * 1000
        self._timer_id = GLib.timeout_add(ms, self._on_timer)

    def _on_timer(self) -> bool:
        if not self.paused:
            threading.Thread(target=self._fetch, daemon=True).start()
        self._schedule()
        return False

    def trigger_check(self):
        if not self.paused:
            threading.Thread(target=self._fetch, daemon=True).start()

    # ── fetch ──────────────────────────────────────────────────────────────────
    def _fetch(self):
        alerts, error = fetch_alerts(self.config)
        GLib.idle_add(self._apply, alerts, error)

    def _apply(self, alerts, error):
        self._alerts     = alerts
        self._last_error = error
        self._last_check = datetime.datetime.now().strftime("%H:%M:%S")
        has = bool(alerts) and error is None

        if has:
            names   = [a.get("labels", {}).get("alertname", "?") for a in alerts[:3]]
            summary = ", ".join(names) + ("…" if len(alerts) > 3 else "")
            self._indicator.set_alert(len(alerts), summary)
            if not self._had_alerts:
                self._notify(len(alerts), summary)
                if self.config.get("sound_enabled"):
                    self._sound.play(self.config.get("sound_file", ""))
        elif error:
            self._indicator.set_normal(f"Error: {error}")
        else:
            self._indicator.set_normal("No active alerts")

        self._had_alerts = has
        self._window.refresh(alerts, error, self.paused, self._last_check)
        return False

    # ── notification ───────────────────────────────────────────────────────────
    def _notify(self, count: int, summary: str):
        try:
            n = Notify.Notification.new(
                f"⚠ {count} Active Alert(s)", summary, "dialog-warning")
            n.set_urgency(Notify.Urgency.CRITICAL)
            n.show()
        except Exception as e:
            print(f"[WARN] Notification: {e}")

    # ── pause / resume ─────────────────────────────────────────────────────────
    def toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self._indicator.set_paused()
        else:
            self._had_alerts = False
            self._indicator.set_normal("Resuming…")
            self.trigger_check()
        self._window.refresh(self._alerts, self._last_error,
                             self.paused, self._last_check)

    # ── window & menu ──────────────────────────────────────────────────────────
    def toggle_main_window(self):
        if self._window.get_visible():
            self._window.hide()
        else:
            self._window.show_all()
            self._window.present()

    def show_tray_menu(self, x: int = 0, y: int = 0):
        menu = Gtk.Menu()

        lbl_p = "▶ Resume monitoring" if self.paused else "⏸ Pause monitoring"
        ip = Gtk.MenuItem(label=lbl_p)
        ip.connect("activate", lambda _: self.toggle_pause())
        menu.append(ip)

        iw = Gtk.MenuItem(label="📋 Show / Hide window")
        iw.connect("activate", lambda _: self.toggle_main_window())
        menu.append(iw)

        ir = Gtk.MenuItem(label="↻ Check now")
        ir.connect("activate", lambda _: self.trigger_check())
        menu.append(ir)

        menu.append(Gtk.SeparatorMenuItem())

        # ── indicator position sub-section ─────────────────────────────────────
        i_reset = Gtk.MenuItem(label="⊹ Reset indicator to panel position")
        i_reset.connect("activate", lambda _: self._indicator.reset_to_panel())
        menu.append(i_reset)

        menu.append(Gtk.SeparatorMenuItem())

        if self._last_error:
            lbl_s = f"Error: {self._last_error[:50]}"
        else:
            lbl_s = (f"⚠ {len(self._alerts)} alert(s) active"
                     if self._alerts else "✔ No active alerts")
        is_ = Gtk.MenuItem(label=lbl_s)
        is_.set_sensitive(False)
        menu.append(is_)

        menu.append(Gtk.SeparatorMenuItem())

        iq = Gtk.MenuItem(label="✕ Quit")
        iq.connect("activate", self._quit)
        menu.append(iq)

        menu.show_all()
        menu.popup_at_pointer(None)

    # ── config ─────────────────────────────────────────────────────────────────
    def apply_config(self, cfg: dict):
        # Preserve indicator position when saving from Settings dialog
        cfg.setdefault("indicator_x", self.config.get("indicator_x"))
        cfg.setdefault("indicator_y", self.config.get("indicator_y"))
        self.config = cfg
        save_config(cfg)
        self._schedule(delay_ms=500)

    # ── quit ───────────────────────────────────────────────────────────────────
    def _quit(self, *_):
        Notify.uninit()
        Gtk.main_quit()

    def run(self):
        Gtk.main()


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = AlertMonitorApp()
    app.run()
