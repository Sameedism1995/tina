"""
Monitors AI tool usage via:
  1. Chrome open tabs (AppleScript)
  2. Downloaded images with macOS metadata (mdls kMDItemWhereFroms)
"""
import subprocess
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List

AI_DOMAINS = {
    'chat.openai.com':     'ChatGPT',
    'chatgpt.com':         'ChatGPT',
    'gemini.google.com':   'Gemini',
    'aistudio.google.com': 'Gemini',
    'claude.ai':           'Claude',
    'midjourney.com':      'Midjourney',
    'ideogram.ai':         'Ideogram',
    'leonardo.ai':         'Leonardo',
    'bing.com/images':     'Bing Image Creator',
    'stability.ai':        'Stability AI',
    'runwayml.com':        'Runway',
}

IMAGE_EXTS   = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif'}
LOOKBACK_SEC = 6 * 3600   # show downloads from last 6 hours


@dataclass
class AIEvent:
    source:   str
    event:    str
    detail:   str
    age:      str
    is_image: bool = False


def _age(mtime: float) -> str:
    secs = time.time() - mtime
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


def _match(url: str) -> str:
    url = url.lower()
    for domain, name in AI_DOMAINS.items():
        if domain in url:
            return name
    return ""


class AIMonitor:
    def scan(self) -> List[AIEvent]:
        events: List[AIEvent] = []
        events.extend(self._chrome_tabs())
        events.extend(self._downloaded_images())
        return events

    # ── Chrome open tabs via AppleScript ──────────────────────────
    def _chrome_tabs(self) -> List[AIEvent]:
        script = '''
tell application "System Events"
    if not (exists process "Google Chrome") then return ""
end tell
tell application "Google Chrome"
    set out to ""
    repeat with w in windows
        repeat with t in tabs of w
            set out to out & (URL of t) & "|" & (title of t) & "\n"
        end repeat
    end repeat
    return out
end tell
'''
        try:
            r = subprocess.run(['osascript', '-e', script],
                               capture_output=True, text=True, timeout=7)
            if r.returncode != 0 or not r.stdout.strip():
                return []

            seen: set = set()
            events: List[AIEvent] = []
            for line in r.stdout.strip().splitlines():
                if '|' not in line:
                    continue
                url, _, title = line.partition('|')
                name = _match(url)
                if name and name not in seen:
                    seen.add(name)
                    events.append(AIEvent(
                        source=name,
                        event="Chrome tab open",
                        detail=(title.strip() or url.strip())[:80],
                        age="active",
                    ))
            return events
        except Exception:
            return []

    # ── Downloads folder — check macOS source metadata ─────────────
    def _downloaded_images(self) -> List[AIEvent]:
        downloads = Path.home() / 'Downloads'
        if not downloads.exists():
            return []

        cutoff = time.time() - LOOKBACK_SEC
        events: List[AIEvent] = []

        try:
            candidates = sorted(
                (f for f in downloads.iterdir()
                 if f.suffix.lower() in IMAGE_EXTS and not f.name.startswith('.')),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )[:30]
        except OSError:
            return []

        for f in candidates:
            try:
                mtime = f.stat().st_mtime
                if mtime < cutoff:
                    continue

                # macOS records download source in extended attribute
                r = subprocess.run(
                    ['mdls', '-name', 'kMDItemWhereFroms', '-raw', str(f)],
                    capture_output=True, text=True, timeout=3,
                )
                name = _match(r.stdout)
                if not name:
                    continue

                events.append(AIEvent(
                    source=name,
                    event="Image downloaded",
                    detail=f.name,
                    age=_age(mtime),
                    is_image=True,
                ))
            except Exception:
                continue

        return events
