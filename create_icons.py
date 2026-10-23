#!/usr/bin/env python3
"""Generate SVG icons for the AlertManager Monitor app."""

import os

icons_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
os.makedirs(icons_dir, exist_ok=True)

# Normal state icon - grey bell
normal_svg = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 22" width="22" height="22">
  <circle cx="11" cy="11" r="10" fill="#555555" opacity="0.85"/>
  <text x="11" y="16" text-anchor="middle" font-size="14" font-family="sans-serif" fill="white">🔔</text>
</svg>'''

# Alert state icon - red bell
alert_svg = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 22" width="22" height="22">
  <circle cx="11" cy="11" r="10" fill="#cc0000" opacity="0.95"/>
  <text x="11" y="16" text-anchor="middle" font-size="14" font-family="sans-serif" fill="white">🔔</text>
</svg>'''

# Paused state icon - grey with pause symbol
paused_svg = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 22" width="22" height="22">
  <circle cx="11" cy="11" r="10" fill="#888888" opacity="0.85"/>
  <rect x="7" y="6" width="3" height="10" fill="white" rx="1"/>
  <rect x="12" y="6" width="3" height="10" fill="white" rx="1"/>
</svg>'''

with open(os.path.join(icons_dir, "alert-normal.svg"), "w") as f:
    f.write(normal_svg)

with open(os.path.join(icons_dir, "alert-active.svg"), "w") as f:
    f.write(alert_svg)

with open(os.path.join(icons_dir, "alert-paused.svg"), "w") as f:
    f.write(paused_svg)

print("Icons created successfully in:", icons_dir)
