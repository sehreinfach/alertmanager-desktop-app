#!/bin/bash
# Uninstall AlertManager Monitor
# Removes desktop entry, autostart entry, and kills any running instance.
# Does NOT delete the application source directory.

set -euo pipefail

DESKTOP_INSTALL="$HOME/.local/share/applications/alertmanager-monitor.desktop"
AUTOSTART_FILE="$HOME/.config/autostart/alertmanager-monitor.desktop"
APP_NAME="AlertManager Monitor"

echo "╔══════════════════════════════════════╗"
echo "║   AlertManager Monitor — Uninstall   ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. Kill any running instance ───────────────────────────────────────────────
PIDS=$(pgrep -f "alertmanager_monitor.py" 2>/dev/null || true)
if [[ -n "$PIDS" ]]; then
    echo "⏹  Stopping running instance(s): PID $PIDS"
    kill $PIDS 2>/dev/null || true
    sleep 1
    # Force-kill if still alive
    PIDS=$(pgrep -f "alertmanager_monitor.py" 2>/dev/null || true)
    if [[ -n "$PIDS" ]]; then
        kill -9 $PIDS 2>/dev/null || true
        echo "   (force-killed)"
    fi
    echo "   ✔ Process stopped"
else
    echo "ℹ  No running instance found"
fi
echo ""

# ── 2. Remove autostart entry ──────────────────────────────────────────────────
if [[ -f "$AUTOSTART_FILE" ]]; then
    rm -f "$AUTOSTART_FILE"
    echo "✔  Removed autostart entry: $AUTOSTART_FILE"
else
    echo "ℹ  No autostart entry found (skipped)"
fi

# ── 3. Remove desktop entry ────────────────────────────────────────────────────
if [[ -f "$DESKTOP_INSTALL" ]]; then
    rm -f "$DESKTOP_INSTALL"
    echo "✔  Removed desktop entry:   $DESKTOP_INSTALL"
else
    echo "ℹ  No desktop entry found (skipped)"
fi

# ── 4. Refresh the application database ───────────────────────────────────────
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "✔  Application database refreshed"
echo ""

# ── 5. Summary ─────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Uninstall complete.                                     ║"
echo "║                                                          ║"
echo "║  The source directory was NOT deleted.                   ║"
echo "║  To also remove the source files run:                    ║"
echo "║    rm -rf \"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)\"  ║"
echo "╚══════════════════════════════════════════════════════════╝"
