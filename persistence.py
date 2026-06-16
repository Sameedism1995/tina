"""persistence.py — Tina state store (JSON, ~/.tina/state.json)"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

TINA_DIR   = Path.home() / ".tina"
STATE_FILE = TINA_DIR / "state.json"

_DEFAULT: dict = {
    "preferences": {
        # None = first-launch not yet completed
        "wake_behavior": None,   # "always_resume" | "ask_after_wake" | "manual_only"
        "first_launch":  True,
    },
    # { project_name: { remaining, running, notes, last_active } }
    "sessions":    {},
    "active_focus": None,   # project name or None
    "last_save":    None,   # ISO timestamp string
    "log":          [],     # [{ ts, event }, ...]  — most-recent first
}


def load_state() -> dict:
    TINA_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            raw = json.loads(STATE_FILE.read_text())
            merged = {**_DEFAULT, **raw}
            merged["preferences"] = {**_DEFAULT["preferences"],
                                     **raw.get("preferences", {})}
            return merged
        except Exception as exc:
            print(f"[TINA] state load error: {exc}")
    # Return a fresh deep copy so callers can mutate freely
    return {
        "preferences": dict(_DEFAULT["preferences"]),
        "sessions":    {},
        "active_focus": None,
        "last_save":    None,
        "log":          [],
    }


def save_state(state: dict) -> None:
    TINA_DIR.mkdir(parents=True, exist_ok=True)
    state["last_save"] = datetime.now().isoformat(timespec="seconds")
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    except Exception as exc:
        print(f"[TINA] state save error: {exc}")


def append_log(state: dict, event: str) -> None:
    entry = {"ts": datetime.now().strftime("%H:%M"), "event": event}
    state["log"] = [entry, *state["log"]][:60]
    save_state(state)
