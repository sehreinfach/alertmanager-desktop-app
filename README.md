# AlertManager Monitor

A lightweight GNOME desktop application that monitors **Prometheus Alertmanager**
for active alerts and shows a **flashing panel icon** + desktop notification
when alerts fire.

---

## Features

| Feature | Detail |
|---|---|
| 🔔 Panel icon | Lives in the system tray / GNOME top-bar |
| ⚠ Flashing icon | Alternates between normal and red bell when alerts are active |
| 🔕 Pause / Resume | Right-click tray icon or use the window toolbar |
| 💬 Desktop notification | Shown once when new alerts appear (libnotify) |
| 🔊 Sound | Plays an OGG/WAV file via GStreamer when new alerts fire |
| 📋 Alert table | Click tray icon to open a window with alert details |
| ⚙ Settings dialog | URL, credentials, interval, sound — all configurable in the UI |
| 💾 Config file | `conf.json` in the app directory |

---

## Requirements

```bash
# Debian / Ubuntu / Raspberry Pi OS
sudo apt install python3-gi python3-gi-cairo \
                 gir1.2-gtk-3.0 gir1.2-glib-2.0 \
                 gir1.2-notify-0.7 gir1.2-gst-plugins-base-1.0 \
                 gstreamer1.0-plugins-good gstreamer1.0-plugins-base \
                 gstreamer1.0-alsa
```

All dependencies listed above come pre-installed on most GNOME desktops running
Debian 11/12, Ubuntu 22.04+.

---

## Configuration (`conf.json`)

```json
{
    "alertmanager_url": "http://localhost:9093",
    "username": "",
    "password": "",
    "check_interval": 30,
    "sound_enabled": true,
    "sound_file": "/usr/share/sounds/freedesktop/stereo/dialog-warning.oga"
}
```

| Key | Default | Description |
|---|---|---|
| `alertmanager_url` | `http://localhost:9093` | Full URL to Alertmanager |
| `username` | `""` | HTTP Basic Auth user (leave empty for none) |
| `password` | `""` | HTTP Basic Auth password |
| `check_interval` | `30` | Seconds between polls |
| `sound_enabled` | `true` | Play sound on new alerts |
| `sound_file` | freedesktop warning sound | Path to any `.oga`, `.ogg`, or `.wav` |

---

## Usage

### Run directly

```bash
python3 alertmanager_monitor.py
```

### Install as GNOME application (optional)

```bash
chmod +x install.sh
./install.sh
```

This installs a `.desktop` file so the app appears in your application
launcher. You can optionally add it to autostart (runs on login).

---

## Tray icon states

| Icon | Meaning |
|---|---|
| Grey circle | No active alerts |
| 🔴 Flashing red ↔ grey | **Active alerts!** |
| Grey with ⏸ bars | Monitoring paused |

### Right-click menu

- **Pause / Resume** monitoring
- **Show / Hide** the alert window
- **Check now** — trigger an immediate fetch
- Status label (alert count or error)
- **Quit**

---

## Alert window

Left-click the tray icon to open/close the main window.

Columns: **Severity · Alert · Instance · Summary · Started**

---

## Sound

The app uses **GStreamer** (always available on GNOME) to play the configured
sound file.  The default file is the freedesktop `dialog-warning.oga` which
is present on all standard GNOME installations.

A sound plays **once** when new alerts first appear; it will not repeat until
the alerts clear and new ones arrive.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Icon not visible | Check `~/.config/autostart` or re-run the app |
| No sound | Install `gstreamer1.0-plugins-good` and check the sound file path |
| Connection error | Verify URL in `conf.json`; check firewall / VPN |
| HTTP 401 | Set correct username/password in Settings or `conf.json` |
