#!/bin/bash
# Install AlertManager Monitor as a GNOME autostart / application

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SCRIPT="$SCRIPT_DIR/alertmanager_monitor.py"
ICON_PATH="$SCRIPT_DIR/icons/alert-normal.svg"
DESKTOP_FILE="$SCRIPT_DIR/alertmanager-monitor.desktop"
DESKTOP_INSTALL="$HOME/.local/share/applications/alertmanager-monitor.desktop"
AUTOSTART_DIR="$HOME/.config/autostart"
AUTOSTART_FILE="$AUTOSTART_DIR/alertmanager-monitor.desktop"

# Make scripts executable
chmod +x "$APP_SCRIPT"

# Write the .desktop file with real paths
cat > "$DESKTOP_INSTALL" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=AlertManager Monitor
Comment=Monitor Prometheus Alertmanager for active alerts
Exec=python3 $APP_SCRIPT
Icon=$ICON_PATH
Terminal=false
Categories=System;Monitor;
Keywords=prometheus;alertmanager;monitoring;alerts;
StartupNotify=false
EOF

echo "✔ Installed desktop entry: $DESKTOP_INSTALL"

# Ask about autostart
read -p "Add to GNOME autostart (start on login)? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    mkdir -p "$AUTOSTART_DIR"
    cp "$DESKTOP_INSTALL" "$AUTOSTART_FILE"
    echo "✔ Installed autostart entry: $AUTOSTART_FILE"
fi

# Update desktop DB
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo ""
echo "✔ Installation complete!"
echo "  You can now:"
echo "    • Run it directly:  python3 $APP_SCRIPT"
echo "    • Find it in your application launcher as 'AlertManager Monitor'"
echo "    • Edit settings in: $SCRIPT_DIR/conf.json"
