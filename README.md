# Tina — Personal Dev Secretary

A minimal macOS desktop app that monitors your active dev projects, tracks focus sessions, and shows what's running on your machine.

![Platform](https://img.shields.io/badge/platform-macOS-black) ![Python](https://img.shields.io/badge/python-3.9%2B-blue)

---

## Features

- **Open Apps** — detects running dev processes (Node, Python, Go, etc.), shows which editor has each project open (Cursor, VS Code), active ports, and CPU state
- **Focus Timers** — 25-min Pomodoro sessions per project; configurable duration (15 / 20 / 25 / 30 / 45 / 60 min); pause, resume, complete
- **Focus Queue** — line up multiple projects; when one session ends Tina minimises and automatically starts the next
- **Tracked Folders** — finds your 5 most recently modified project folders in ~/Documents and ~/Desktop
- **Connected APIs** — shows listening ports and external connections with resolved service names (GitHub, OpenAI, Vercel, etc.)
- **Data In / Out** — live network rate + AI activity (Chrome tabs on ChatGPT, Claude, Gemini, downloaded AI images)

---

## Download (macOS)

1. Go to [**Releases**](../../releases) and download **Tina.zip**
2. Unzip and drag **Tina.app** to your Applications folder
3. **First launch:** right-click Tina.app → **Open** → click Open in the dialog
   *(macOS Gatekeeper requires this once for unsigned apps)*
4. On subsequent launches, open normally from Applications or Spotlight

---

## Run from source

```bash
pip install psutil Pillow
python3 app.py
```

Requirements: macOS 10.13+, Python 3.9+

---

## Build the .app bundle yourself

```bash
pip install psutil Pillow
python3 build_app.py
open Tina.app
```
