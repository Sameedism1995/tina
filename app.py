#!/usr/bin/env python3
"""
app.py — Tina: Personal Development Secretary
Minimalist Tkinter UI for macOS.
"""
from __future__ import annotations

import os
import sys
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── macOS bundle name ──────────────────────────────────────────────────────────
try:
    from Foundation import NSBundle, NSProcessInfo
    _d = NSBundle.mainBundle().infoDictionary()
    _d["CFBundleName"] = "Tina"
    _d["CFBundleDisplayName"] = "Tina"
    NSProcessInfo.processInfo().setProcessName_("Tina")
except Exception:
    pass

import tkinter as tk

try:
    import psutil
except ImportError:
    print("[Tina] psutil required: pip install psutil")
    sys.exit(1)

from monitor        import ProcessMonitor
from folder_tracker import FolderScanner, FolderProject
from persistence    import load_state, save_state, append_log
from wake_monitor   import WakeMonitor
from ai_monitor     import AIMonitor

# ── Palette ────────────────────────────────────────────────────────────────────
BG    = "#111111"
BG2   = "#191919"
TEXT  = "#e8e8e8"
DIM   = "#666666"
DIM2  = "#333333"
GREEN = "#4ade80"
BLUE  = "#60a5fa"
AMBER = "#fbbf24"
SEP   = "#222222"
LINK  = "#888888"

# ── Fonts ──────────────────────────────────────────────────────────────────────
F_XS   = ("Helvetica Neue", 10)
F_SM   = ("Helvetica Neue", 11)
F_MD   = ("Helvetica Neue", 13)
F_MD_B = ("Helvetica Neue", 13, "bold")
F_LG   = ("Helvetica Neue", 16, "bold")
F_SEC  = ("Helvetica Neue", 10)   # section labels (rendered UPPERCASE)
F_MONO = ("Menlo", 12)
F_MONO_SM = ("Menlo", 10)

REFRESH_S      = 30
FOCUS_DURATION = 25 * 60   # seconds — default; actual duration stored in state prefs

# Port → service name
PORT_NAMES: dict[int, str] = {
    3000: "Dev Server", 3001: "Dev Server", 3002: "Dev Server",
    4000: "Dev Server", 4200: "Angular",    4321: "Astro",
    5000: "Flask",      5001: "Dev Server", 5173: "Vite",
    8000: "Django",     8080: "HTTP",       8443: "HTTPS Dev",
    8888: "Jupyter",    9000: "Dev Server",
    5432: "PostgreSQL", 3306: "MySQL",      27017: "MongoDB",
    6379: "Redis",      5672: "RabbitMQ",   9200: "Elasticsearch",
    1433: "SQL Server", 5984: "CouchDB",    9092: "Kafka",
}


# Known remote services by hostname fragment
KNOWN_APIS: list[tuple[str, str]] = [
    ("openai.com",      "OpenAI"),
    ("anthropic.com",   "Anthropic"),
    ("claude.ai",       "Claude"),
    ("github.com",      "GitHub"),
    ("api.github.com",  "GitHub API"),
    ("githubusercontent","GitHub CDN"),
    ("stripe.com",      "Stripe"),
    ("twilio.com",      "Twilio"),
    ("sendgrid.net",    "SendGrid"),
    ("vercel.com",      "Vercel"),
    ("netlify.com",     "Netlify"),
    ("supabase.co",     "Supabase"),
    ("firebase",        "Firebase"),
    ("amazonaws.com",   "AWS"),
    ("googleapis.com",  "Google API"),
    ("google.com",      "Google"),
    ("cloudflare.com",  "Cloudflare"),
    ("sentry.io",       "Sentry"),
    ("mixpanel.com",    "Mixpanel"),
    ("segment.com",     "Segment"),
    ("huggingface.co",  "HuggingFace"),
    ("replicate.com",   "Replicate"),
]


def _label_host(host: str) -> str:
    """Return a friendly service name for a hostname, or the host itself."""
    h = host.lower()
    for fragment, label in KNOWN_APIS:
        if fragment in h:
            return label
    return host


def _human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ── Timer state ────────────────────────────────────────────────────────────────

class TimerState:
    def __init__(self, remaining: int = FOCUS_DURATION, running: bool = False):
        self.remaining = max(0, remaining)
        self.running   = running
        self.done      = remaining <= 0

    def tick(self) -> bool:
        """Decrement; return True if just hit zero."""
        if self.running and self.remaining > 0:
            self.remaining -= 1
            if self.remaining == 0:
                self.running = False
                self.done    = True
                return True
        return False

    def fmt(self) -> str:
        m, s = divmod(max(0, self.remaining), 60)
        return f"{m:02d}:{s:02d}"


# ── Main application ───────────────────────────────────────────────────────────

class TinaApp:

    def __init__(self, root: tk.Tk):
        self._root       = root
        self._state      = load_state()
        self._monitor    = ProcessMonitor()
        self._folders    = FolderScanner()
        self._ai_monitor = AIMonitor()

        # Runtime state
        self._projects:        list = []
        self._folder_projects: list[FolderProject] = []
        self._api_ports:       list[tuple[int, str]] = []   # (port, service)
        self._ext_conns:       list[str] = []               # external hosts
        self._net_stats:       tuple[str, str] = ("—", "—") # (recv, sent) human strings
        self._net_prev:        Optional[tuple]  = None      # (recv_bytes, sent_bytes, ts)
        self._ai_events:       list             = []
        self._auto_on          = True
        self._scan_remaining   = REFRESH_S
        self._scanning         = False
        self._notes_open:      set[str] = set()
        self._pending_recovery: Optional[tuple] = None

        # Focus duration — loaded from prefs, in seconds
        self._focus_duration: int = (
            self._state.get("preferences", {}).get("focus_minutes", 25) * 60
        )

        # Focus queue — ordered list of project names waiting to run
        self._focus_queue: list[str] = []

        # History search filter — persists across renders
        self._log_filter: str = ""

        # Timers: in-memory, synced to disk every 5 s
        self._timers:      dict[str, TimerState]  = {}
        self._timer_vars:  dict[str, tk.StringVar] = {}  # live countdown text
        self._timer_labels: dict[str, tk.Label]   = {}   # label refs (for color)

        self._restore_timers()
        self._setup_window()
        self._build_skeleton()

        # Trigger startup logic after window is drawn
        self._root.after(100, self._startup)

        # Background threads
        self._wake_monitor = WakeMonitor(on_wake=self._on_wake)
        self._wake_monitor.start()

        self._root.after(1000,  self._timer_tick)
        self._root.after(5000,  self._save_tick)
        self._root.after(400,   self._initial_scan)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Persistence helpers ────────────────────────────────────────────────────

    def _restore_timers(self) -> None:
        for proj, sess in self._state.get("sessions", {}).items():
            self._timers[proj] = TimerState(
                remaining=sess.get("remaining", self._focus_duration),
                running=False,   # never auto-run on cold load; handled by startup
            )

    def _sync_timer(self, project: str, *, running: Optional[bool] = None) -> None:
        """Write in-memory timer back to state dict + save."""
        sessions = self._state.setdefault("sessions", {})
        sess     = sessions.setdefault(project, {})
        timer    = self._timers.get(project)
        if timer:
            sess["remaining"] = timer.remaining
        if running is not None:
            sess["running"] = running
        sess["last_active"] = datetime.now().isoformat(timespec="seconds")
        save_state(self._state)

    # ── Startup / wake / first-launch logic ───────────────────────────────────

    def _startup(self) -> None:
        prefs = self._state.get("preferences", {})

        if prefs.get("first_launch", True):
            self._show_first_launch()
            return

        # Check for elapsed time since last save (restart or sleep)
        last_save_str  = self._state.get("last_save")
        active_focus   = self._state.get("active_focus")

        if active_focus and last_save_str:
            try:
                last_dt  = datetime.fromisoformat(last_save_str)
                elapsed  = (datetime.now() - last_dt).total_seconds()
                if elapsed > 60:
                    sess         = self._state.get("sessions", {}).get(active_focus, {})
                    was_running  = sess.get("running", False)
                    remaining    = sess.get("remaining", self._focus_duration)
                    if was_running:
                        new_rem   = max(0, remaining - int(elapsed))
                        behavior  = prefs.get("wake_behavior", "ask_after_wake")
                        if behavior == "always_resume":
                            self._do_resume(active_focus, new_rem)
                            self._pending_recovery = (active_focus, new_rem, int(elapsed))
                            append_log(self._state, "Restoring session")
                        elif behavior == "ask_after_wake":
                            self._root.after(
                                300,
                                lambda: self._show_wake_prompt(active_focus, new_rem, int(elapsed)),
                            )
            except Exception as exc:
                print(f"[TINA] startup check error: {exc}")

    def _do_resume(self, project: str, remaining: int) -> None:
        if project not in self._timers:
            self._timers[project] = TimerState()
        t = self._timers[project]
        t.remaining = remaining
        t.running   = True
        t.done      = False
        self._state["active_focus"] = project
        append_log(self._state, f"Focus resumed: {project}")

    # ── Window ─────────────────────────────────────────────────────────────────

    def _setup_window(self) -> None:
        r = self._root
        r.title("Tina")
        r.configure(bg=BG)
        r.geometry("500x720+120+80")
        r.minsize(420, 500)

    # ── Skeleton (static frame structure) ─────────────────────────────────────

    def _build_skeleton(self) -> None:
        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self._root, bg=BG)
        hdr.pack(fill="x", padx=24, pady=(16, 0))

        tk.Label(hdr, text="TINA", bg=BG, fg=TEXT,
                 font=("Helvetica Neue", 15, "bold")).pack(side="left")

        right = tk.Frame(hdr, bg=BG)
        right.pack(side="right")

        self._auto_lbl = tk.Label(
            right, text="auto: on", bg=BG, fg=GREEN, font=F_SM, cursor="hand2"
        )
        self._auto_lbl.pack(side="left")
        self._auto_lbl.bind("<Button-1>", lambda _: self._toggle_auto())
        _hover(self._auto_lbl, TEXT, lambda: GREEN if self._auto_on else DIM)

        tk.Label(right, text="  ·  ", bg=BG, fg=DIM2, font=F_SM).pack(side="left")

        ref = tk.Label(right, text="refresh", bg=BG, fg=LINK, font=F_SM, cursor="hand2")
        ref.pack(side="left")
        ref.bind("<Button-1>", lambda _: self._trigger_scan())
        _hover(ref, TEXT, lambda: LINK)

        # Scan status line
        self._status_var = tk.StringVar(value="")
        tk.Label(self._root, textvariable=self._status_var,
                 bg=BG, fg=DIM, font=F_XS).pack(anchor="w", padx=24, pady=(3, 8))

        # Thin separator
        tk.Frame(self._root, bg=SEP, height=1).pack(fill="x")

        # ── Scrollable body ───────────────────────────────────────────────────
        self._canvas = tk.Canvas(self._root, bg=BG, highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)

        self._body = tk.Frame(self._canvas, bg=BG)
        self._win_id = self._canvas.create_window((0, 0), window=self._body, anchor="nw")

        self._body.bind("<Configure>",
                        lambda _: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(self._win_id, width=e.width))
        self._root.bind_all("<MouseWheel>", self._on_scroll)
        self._root.bind_all("<Button-4>",   self._on_scroll)
        self._root.bind_all("<Button-5>",   self._on_scroll)

    def _on_scroll(self, e: tk.Event) -> None:
        if e.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif e.num == 5:
            self._canvas.yview_scroll(1, "units")
        else:
            d = getattr(e, "delta", 0)
            if abs(d) >= 120:
                # Traditional mouse wheel: 120 units per click
                self._canvas.yview_scroll(-(d // 120), "units")
            elif d > 0:
                self._canvas.yview_scroll(-1, "units")
            elif d < 0:
                self._canvas.yview_scroll(1, "units")

    # ── Widget micro-helpers ───────────────────────────────────────────────────

    def _lbl(self, parent, text="", fg=TEXT, font=F_MD, **kw) -> tk.Label:
        return tk.Label(parent, text=text, bg=BG, fg=fg, font=font, **kw)

    def _link(self, parent, text: str, cmd, fg: str = LINK, font=F_SM) -> tk.Label:
        lbl = tk.Label(parent, text=text, bg=BG, fg=fg, font=font, cursor="hand2")
        lbl.bind("<Button-1>", lambda _: cmd())
        _hover(lbl, TEXT, lambda: fg)
        return lbl

    def _sep(self, parent, vpad=(16, 16)) -> None:
        tk.Frame(parent, bg=BG, height=vpad[0]).pack(fill="x")
        tk.Frame(parent, bg=SEP, height=1).pack(fill="x")
        tk.Frame(parent, bg=BG, height=vpad[1]).pack(fill="x")

    def _section(self, parent, title: str) -> None:
        tk.Label(parent, text=title.upper(), bg=BG, fg=DIM,
                 font=F_SEC).pack(anchor="w", padx=24, pady=(0, 10))

    def _gap(self, parent, h: int) -> None:
        tk.Frame(parent, bg=BG, height=h).pack(fill="x")

    # ── Actions row helper ─────────────────────────────────────────────────────

    def _actions(self, parent, items: list[tuple[str, Optional[callable]]]) -> None:
        """Render action links separated by ·  items = [(label, cmd|None)]."""
        row = tk.Frame(parent, bg=BG)
        row.pack(anchor="w", padx=24, pady=(4, 0))
        first = True
        for text, cmd in items:
            if not first:
                tk.Label(row, text=" · ", bg=BG, fg=DIM2, font=F_SM).pack(side="left")
            if cmd:
                self._link(row, text, cmd, fg=LINK).pack(side="left")
            else:
                tk.Label(row, text=text, bg=BG, fg=DIM2, font=F_SM).pack(side="left")
            first = False

    def _timer_action_items(self, name: str, timer, *, notes: bool = False) -> list:
        """Return action link tuples for the given timer state."""
        if timer and timer.running:
            items: list = [
                ("pause",    lambda n=name: self._pause(n)),
                ("complete", lambda n=name: self._complete(n)),
            ]
        elif timer and not timer.running and timer.remaining < self._focus_duration and not timer.done:
            items = [
                ("resume", lambda n=name: self._start(n)),
                ("reset",  lambda n=name: self._reset(n)),
            ]
        else:
            items = [("focus", lambda n=name: self._start(n))]
        if notes:
            items.append(("notes", lambda n=name: self._toggle_notes(n)))
        return items

    # ── Full body render ───────────────────────────────────────────────────────

    def _render(self) -> None:
        for w in self._body.winfo_children():
            w.destroy()
        self._timer_labels.clear()

        self._gap(self._body, 20)

        if self._pending_recovery:
            self._render_recovery(*self._pending_recovery)
            self._pending_recovery = None
            self._sep(self._body, (16, 16))

        # ── 1. OPEN APPS ──────────────────────────────────────────
        self._section(self._body, "Open Apps")
        if not self._projects:
            self._dim_row("No dev processes detected. Start a project or dev server.")
        else:
            active = self._state.get("active_focus")
            for i, proj in enumerate(self._projects):
                self._render_project_row(proj.name, process_state=proj.state)
                if i < len(self._projects) - 1:
                    self._gap(self._body, 12)

        self._sep(self._body)

        # ── 2. FOCUS TIMERS ───────────────────────────────────────
        # Section header + duration picker on the same row
        hdr_row = tk.Frame(self._body, bg=BG)
        hdr_row.pack(fill="x", padx=24, pady=(0, 10))
        tk.Label(hdr_row, text="FOCUS TIMERS", bg=BG, fg=DIM, font=F_SEC).pack(side="left")

        cur_mins = self._focus_duration // 60
        dur_row = tk.Frame(hdr_row, bg=BG)
        dur_row.pack(side="right")
        for i, mins in enumerate([15, 20, 25, 30, 45, 60]):
            if i:
                tk.Label(dur_row, text=" · ", bg=BG, fg=DIM2, font=F_XS).pack(side="left")
            if mins == cur_mins:
                tk.Label(dur_row, text=f"{mins}m", bg=BG, fg=GREEN,
                         font=("Menlo", 10, "bold")).pack(side="left")
            else:
                lbl = tk.Label(dur_row, text=f"{mins}m", bg=BG, fg=DIM, font=F_MONO_SM,
                               cursor="hand2")
                lbl.bind("<Button-1>", lambda _, m=mins: self._set_duration(m))
                _hover(lbl, TEXT, lambda: DIM)
                lbl.pack(side="left")

        # Queue overview — shown only when there are queued projects
        if self._focus_queue:
            q_row = tk.Frame(self._body, bg=BG)
            q_row.pack(fill="x", padx=24, pady=(0, 10))
            tk.Label(q_row, text="up next: ", bg=BG, fg=DIM2, font=F_XS).pack(side="left")
            for i, qname in enumerate(self._focus_queue):
                if i:
                    tk.Label(q_row, text=" → ", bg=BG, fg=DIM2, font=F_XS).pack(side="left")
                tk.Label(q_row, text=qname, bg=BG, fg=DIM, font=F_XS).pack(side="left")

        timer_projects = self._projects[:]
        # Also include any persisted sessions not currently running
        for name in self._timers:
            if not any(p.name == name for p in timer_projects):
                timer_projects.append(type("_P", (), {"name": name, "state": ""})())
        if not timer_projects:
            self._dim_row("No projects to track yet.")
        else:
            for i, proj in enumerate(timer_projects):
                self._render_timer_row(proj.name)
                if i < len(timer_projects) - 1:
                    self._gap(self._body, 10)

        self._sep(self._body)

        # ── 3. TRACKED FOLDERS ────────────────────────────────────
        self._section(self._body, "Tracked Folders")
        running_names = {p.name for p in self._projects}
        folders = [f for f in self._folder_projects if f.name not in running_names]
        if not folders:
            self._dim_row("No project folders found in ~/Documents, ~/Desktop, ~/Projects.")
        else:
            for i, f in enumerate(folders):
                self._render_folder_row(f)
                if i < len(folders) - 1:
                    self._gap(self._body, 12)

        self._sep(self._body)

        # ── 4. CONNECTED APIs ─────────────────────────────────────
        self._section(self._body, "Connected APIs")
        if not self._api_ports and not self._ext_conns:
            self._dim_row("No active ports or external connections detected.")
        else:
            if self._api_ports:
                for port, svc in self._api_ports[:12]:
                    row = tk.Frame(self._body, bg=BG)
                    row.pack(fill="x", padx=24, pady=1)
                    tk.Label(row, text=f":{port}", bg=BG, fg=BLUE,
                             font=F_MONO_SM).pack(side="left")
                    tk.Label(row, text=f"  {svc}", bg=BG, fg=DIM,
                             font=F_SM).pack(side="left")
            if self._ext_conns:
                self._gap(self._body, 6)
                tk.Label(self._body, text="External connections",
                         bg=BG, fg=DIM2, font=F_XS).pack(anchor="w", padx=24)
                for host in self._ext_conns[:10]:
                    tk.Label(self._body, text=f"  {host}", bg=BG, fg=DIM,
                             font=F_SM).pack(anchor="w", padx=24)

        self._sep(self._body)

        # ── 5. DATA IN / OUT ──────────────────────────────────────
        self._section(self._body, "Data In / Out")
        recv, sent = self._net_stats
        net_row = tk.Frame(self._body, bg=BG)
        net_row.pack(anchor="w", padx=24)
        tk.Label(net_row, text="↓ ", bg=BG, fg=GREEN, font=F_SM).pack(side="left")
        tk.Label(net_row, text=recv, bg=BG, fg=TEXT, font=F_MONO_SM).pack(side="left")
        tk.Label(net_row, text="   ↑ ", bg=BG, fg=AMBER, font=F_SM).pack(side="left")
        tk.Label(net_row, text=sent, bg=BG, fg=TEXT, font=F_MONO_SM).pack(side="left")
        tk.Label(net_row, text="  /s since last scan", bg=BG, fg=DIM2,
                 font=F_XS).pack(side="left")

        # AI / browser activity
        if self._ai_events:
            self._gap(self._body, 10)
            tk.Label(self._body, text="AI ACTIVITY", bg=BG, fg=DIM,
                     font=F_SEC).pack(anchor="w", padx=24, pady=(0, 6))
            for ev in self._ai_events[:8]:
                row = tk.Frame(self._body, bg=BG)
                row.pack(fill="x", padx=24, pady=1)
                clr = AMBER if ev.is_image else BLUE
                tk.Label(row, text=ev.source, bg=BG, fg=clr, font=F_SM).pack(side="left")
                tk.Label(row, text=f"  {ev.event}", bg=BG, fg=DIM, font=F_SM).pack(side="left")
                tk.Label(row, text=f"  {ev.age}", bg=BG, fg=DIM2, font=F_XS).pack(side="left")

        self._sep(self._body)

        # ── 6. HISTORY ────────────────────────────────────────────
        self._render_history_section()

        # Settings link
        self._sep(self._body, (20, 8))
        settings_row = tk.Frame(self._body, bg=BG)
        settings_row.pack(fill="x", padx=24)
        self._link(settings_row, "settings", self._show_settings, fg=DIM2).pack(side="left")

        self._gap(self._body, 28)

    def _dim_row(self, text: str) -> None:
        tk.Label(self._body, text=text, bg=BG, fg=DIM2,
                 font=F_SM).pack(anchor="w", padx=24, pady=(0, 4))

    # ── History / log section ─────────────────────────────────────────────────

    def _render_history_section(self) -> None:
        """Searchable activity log — filters live without re-rendering the full UI."""
        # Header + search box on the same row
        hdr = tk.Frame(self._body, bg=BG)
        hdr.pack(fill="x", padx=24, pady=(0, 8))
        tk.Label(hdr, text="HISTORY", bg=BG, fg=DIM, font=F_SEC).pack(side="left")

        search_var = tk.StringVar(value=self._log_filter)
        entry = tk.Entry(
            hdr,
            textvariable=search_var,
            bg=BG2, fg=TEXT, insertbackground=TEXT,
            bd=0, highlightthickness=1,
            highlightbackground=DIM2, highlightcolor=DIM,
            font=F_SM, relief="flat", width=22,
        )
        entry.pack(side="right")

        # Container rebuilt on each filter change
        log_frame = tk.Frame(self._body, bg=BG)
        log_frame.pack(fill="x")

        def _refresh(*_):
            self._log_filter = search_var.get()
            for w in log_frame.winfo_children():
                w.destroy()
            _populate()

        def _populate():
            entries = self._state.get("log", [])
            filt    = self._log_filter.strip().lower()
            today   = datetime.now().strftime("%Y-%m-%d")
            shown   = 0
            for e in entries:
                ts    = e.get("ts", "")
                event = e.get("event", "")
                if filt and filt not in ts.lower() and filt not in event.lower():
                    continue

                # Format timestamp: "today 14:30" or "Jun 16  14:30"
                if ts.startswith(today):
                    label_ts = "today  " + ts[11:]
                elif len(ts) > 5:
                    try:
                        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
                        label_ts = dt.strftime("%b %d  %H:%M")
                    except ValueError:
                        label_ts = ts
                else:
                    label_ts = ts  # legacy HH:MM only

                row = tk.Frame(log_frame, bg=BG)
                row.pack(fill="x", padx=24, pady=1)
                tk.Label(row, text=label_ts, bg=BG, fg=DIM2,
                         font=F_MONO_SM, width=14, anchor="w").pack(side="left")
                tk.Label(row, text=event, bg=BG, fg=DIM,
                         font=F_SM, anchor="w").pack(side="left")
                shown += 1
                if shown >= 50:
                    break

            if shown == 0:
                tk.Label(log_frame,
                         text="No matching entries." if filt else "No activity yet.",
                         bg=BG, fg=DIM2, font=F_SM).pack(anchor="w", padx=24)

        _populate()
        search_var.trace_add("write", _refresh)

    # ── Timer row (Focus Timers section) ──────────────────────────────────────

    def _render_timer_row(self, name: str) -> None:
        timer = self._timers.get(name)
        if not timer:
            timer = TimerState()
            self._timers[name] = timer

        queue_pos = self._focus_queue.index(name) if name in self._focus_queue else -1

        if name not in self._timer_vars:
            self._timer_vars[name] = tk.StringVar()
        var = self._timer_vars[name]
        var.set(timer.fmt())

        frame = tk.Frame(self._body, bg=BG)
        frame.pack(fill="x")

        top = tk.Frame(frame, bg=BG)
        top.pack(fill="x", padx=24)

        # Name + queue position badge
        tk.Label(top, text=name, bg=BG, fg=TEXT, font=F_MD_B).pack(side="left")
        if queue_pos == 0 and not timer.running:
            tk.Label(top, text="  next up", bg=BG, fg=GREEN, font=F_XS).pack(side="left")
        elif queue_pos > 0:
            tk.Label(top, text=f"  #{queue_pos + 1} in queue", bg=BG, fg=DIM, font=F_XS).pack(side="left")

        if timer.running:
            clr = GREEN
        elif timer.remaining < self._focus_duration and not timer.done:
            clr = AMBER
        else:
            clr = DIM

        countdown = tk.Label(top, textvariable=var, bg=BG, fg=clr, font=F_MONO)
        countdown.pack(side="right")
        self._timer_labels[name] = countdown

        # Queue-aware actions
        if timer.running:
            actions: list = [
                ("pause",    lambda n=name: self._pause(n)),
                ("complete", lambda n=name: self._complete(n)),
            ]
        elif timer.remaining < self._focus_duration and not timer.done:
            actions = [
                ("resume", lambda n=name: self._start(n)),
                ("reset",  lambda n=name: self._reset(n)),
            ]
        elif queue_pos >= 0:
            actions = [
                ("focus",  lambda n=name: self._start(n)),
                ("remove from queue", lambda n=name: self._dequeue(n)),
            ]
        else:
            actions = [
                ("focus",   lambda n=name: self._start(n)),
                ("+ queue", lambda n=name: self._enqueue(n)),
            ]
        self._actions(frame, actions)

    # ── Recovery banner ────────────────────────────────────────────────────────

    def _render_recovery(self, project: str, remaining: int, elapsed: int) -> None:
        pad = tk.Frame(self._body, bg=BG)
        pad.pack(fill="x", padx=24)
        tk.Label(pad, text="Welcome back.", bg=BG, fg=TEXT,
                 font=("Helvetica Neue", 15, "bold"), anchor="w").pack(anchor="w")
        self._gap(pad, 4)
        tk.Label(pad, text=f"Last active project:", bg=BG, fg=DIM, font=F_SM).pack(anchor="w")
        tk.Label(pad, text=project, bg=BG, fg=TEXT, font=F_MD_B).pack(anchor="w", pady=(2, 0))
        if remaining > 0:
            m, s = divmod(remaining, 60)
            tk.Label(pad, text=f"{m:02d}:{s:02d} remaining.",
                     bg=BG, fg=DIM, font=F_MONO).pack(anchor="w", pady=(2, 0))

    # ── Project row ────────────────────────────────────────────────────────────

    def _render_project_row(self, name: str, *,
                            process_state: str = "",
                            pinned: bool = False) -> None:
        timer = self._timers.get(name)

        frame = tk.Frame(self._body, bg=BG)
        frame.pack(fill="x")

        # Find the scanned project object for extra metadata
        proj_obj = next((p for p in self._projects if p.name == name), None)

        # Status dot — timer state takes priority over CPU state
        if timer and timer.running:
            dot, dot_fg = "● focusing", GREEN
        elif timer and not timer.running and timer.remaining < self._focus_duration:
            dot, dot_fg = "● paused", AMBER
        elif process_state == "ACTIVE":
            dot, dot_fg = "● active", GREEN
        elif process_state == "RUNNING":
            dot, dot_fg = "● running", BLUE
        else:
            dot, dot_fg = "· idle", DIM2

        # Status line: dot + editor badge(s)
        status_row = tk.Frame(frame, bg=BG)
        status_row.pack(anchor="w", padx=24)
        tk.Label(status_row, text=dot, bg=BG, fg=dot_fg, font=F_XS).pack(side="left")
        if proj_obj and proj_obj.editors:
            for ed in proj_obj.editors:
                tk.Label(status_row, text=f"  · {ed}", bg=BG, fg=BLUE, font=F_XS).pack(side="left")

        # Project name
        tk.Label(frame, text=name, bg=BG, fg=TEXT,
                 font=F_MD_B).pack(anchor="w", padx=24, pady=(2, 0))

        # Services + task description
        if proj_obj:
            if proj_obj.services:
                svc_text = "  ·  ".join(proj_obj.services)
                tk.Label(frame, text=svc_text, bg=BG, fg=DIM, font=F_SM).pack(
                    anchor="w", padx=24)
            if proj_obj.current_task and proj_obj.current_task != "Development service running":
                tk.Label(frame, text=proj_obj.current_task, bg=BG, fg=DIM2, font=F_XS).pack(
                    anchor="w", padx=24)
            if proj_obj.ports:
                ports_text = "  ".join(f":{p}" for p in proj_obj.ports[:6])
                tk.Label(frame, text=ports_text, bg=BG, fg=BLUE, font=F_MONO_SM).pack(
                    anchor="w", padx=24, pady=(1, 0))

        # Timer countdown (static display — Focus Timers section handles live updates)
        if timer:
            timer_lbl = tk.Label(frame, text=timer.fmt() + " remaining",
                                 bg=BG, fg=DIM, font=F_MONO)
            timer_lbl.pack(anchor="w", padx=24, pady=(2, 0))

        self._actions(frame, self._timer_action_items(name, timer))

    # ── Folder row ─────────────────────────────────────────────────────────────

    def _render_folder_row(self, f: FolderProject) -> None:
        name  = f.name
        timer = self._timers.get(name)
        frame = tk.Frame(self._body, bg=BG)
        frame.pack(fill="x")

        tk.Label(frame, text="· idle", bg=BG, fg=DIM2,
                 font=F_XS).pack(anchor="w", padx=24)

        # Name + branch
        name_row = tk.Frame(frame, bg=BG)
        name_row.pack(anchor="w", padx=24, pady=(2, 0))
        tk.Label(name_row, text=name, bg=BG, fg=TEXT,
                 font=F_MD_B).pack(side="left")
        if f.git_branch:
            tk.Label(name_row, text=f"  {f.git_branch}",
                     bg=BG, fg=DIM, font=F_SM).pack(side="left")

        tk.Label(frame, text=f.project_type, bg=BG, fg=DIM2,
                 font=F_XS).pack(anchor="w", padx=24)

        if timer and timer.remaining < self._focus_duration:
            tk.Label(frame, text=timer.fmt() + " remaining",
                     bg=BG, fg=DIM, font=F_MONO).pack(anchor="w", padx=24, pady=(2, 0))

        self._actions(frame, self._timer_action_items(name, timer))

    # ── Inline notes ───────────────────────────────────────────────────────────

    def _render_notes(self, parent: tk.Frame, project: str) -> None:
        content = (self._state.get("sessions", {})
                   .get(project, {})
                   .get("notes", ""))
        txt = tk.Text(
            parent,
            bg=BG2, fg=TEXT, insertbackground=TEXT,
            bd=0, highlightthickness=1,
            highlightbackground=DIM2, highlightcolor=DIM,
            relief="flat", font=F_SM,
            wrap="word", height=4,
            padx=12, pady=10, spacing1=2, spacing3=2,
        )
        txt.pack(fill="x", padx=24, pady=(6, 0))
        txt.insert("1.0", content or "")

        def _save(_event=None):
            val = txt.get("1.0", "end-1c")
            (self._state
             .setdefault("sessions", {})
             .setdefault(project, {})
             )["notes"] = val
            save_state(self._state)

        txt.bind("<KeyRelease>", _save)

    # ── Timer actions ──────────────────────────────────────────────────────────

    def _start(self, project: str) -> None:
        # Pause any other running focus
        current = self._state.get("active_focus")
        if current and current != project and current in self._timers:
            self._timers[current].running = False
            self._sync_timer(current, running=False)

        if project not in self._timers:
            self._timers[project] = TimerState()
        t = self._timers[project]
        if t.done or t.remaining <= 0:
            t.remaining = self._focus_duration
        t.done = False   # always clear so pause→resume works after a completed session
        t.running = True
        self._state["active_focus"] = project
        self._sync_timer(project, running=True)
        append_log(self._state, f"Focus started: {project}")
        self._render()

    def _pause(self, project: str) -> None:
        if project in self._timers:
            self._timers[project].running = False
        self._state["active_focus"] = None
        self._sync_timer(project, running=False)
        append_log(self._state, f"Focus paused: {project}")
        self._render()

    def _complete(self, project: str) -> None:
        if project in self._timers:
            t = self._timers[project]
            t.running   = False
            t.remaining = self._focus_duration
            t.done      = True
        self._state["active_focus"] = None
        self._sync_timer(project, running=False)
        append_log(self._state, f"Focus complete: {project}")
        self._render()
        self._notify(project, "Focus session complete")
        # Advance queue 1.5 s later — gives the notification time to register
        self._root.after(1500, self._advance_queue)

    def _reset(self, project: str) -> None:
        if project in self._timers:
            t = self._timers[project]
            t.remaining = self._focus_duration
            t.running   = False
            t.done      = False
        if self._state.get("active_focus") == project:
            self._state["active_focus"] = None
        self._sync_timer(project, running=False)
        self._render()

    def _set_duration(self, minutes: int) -> None:
        new_secs = minutes * 60
        old_secs = self._focus_duration
        self._focus_duration = new_secs
        self._state.setdefault("preferences", {})["focus_minutes"] = minutes
        # Reset any idle (untouched) timers to the new duration
        for t in self._timers.values():
            if not t.running and not t.done and t.remaining == old_secs:
                t.remaining = new_secs
        save_state(self._state)
        self._render()

    def _toggle_notes(self, project: str) -> None:
        if project in self._notes_open:
            self._notes_open.discard(project)
        else:
            self._notes_open.add(project)
        self._render()

    # ── Focus queue ────────────────────────────────────────────────────────────

    def _enqueue(self, name: str) -> None:
        if name not in self._focus_queue:
            self._focus_queue.append(name)
        self._render()

    def _dequeue(self, name: str) -> None:
        if name in self._focus_queue:
            self._focus_queue.remove(name)
        self._render()

    def _advance_queue(self) -> None:
        """After a session completes: minimise Tina, then pop and start the next project."""
        if not self._focus_queue:
            return
        next_project = self._focus_queue.pop(0)
        self._root.iconify()
        self._root.after(2000, lambda: self._launch_next(next_project))

    def _launch_next(self, project: str) -> None:
        self._start(project)
        self._root.deiconify()
        self._root.lift()
        try:
            self._root.focus_force()
        except Exception:
            pass
        self._notify(project, "Next focus session starting")

    # ── Timer tick — 1 Hz, in-place label updates ──────────────────────────────

    def _timer_tick(self) -> None:
        for name, timer in list(self._timers.items()):
            if timer.tick():
                self._root.after(0, lambda n=name: self._complete(n))
            elif timer.running:
                var = self._timer_vars.get(name)
                if var:
                    try:
                        var.set(timer.fmt())
                    except tk.TclError:
                        pass

        # Update scan countdown
        if self._auto_on and not self._scanning:
            self._scan_remaining -= 1
            if self._scan_remaining <= 0:
                self._trigger_scan()
            else:
                self._status_var.set(f"next scan: {self._scan_remaining}s")

        self._root.after(1000, self._timer_tick)

    # ── State save tick — every 5 s ────────────────────────────────────────────

    def _save_tick(self) -> None:
        for name, timer in self._timers.items():
            self._sync_timer(name, running=timer.running)
        self._root.after(5000, self._save_tick)

    # ── Scanning ───────────────────────────────────────────────────────────────

    def _initial_scan(self) -> None:
        self._trigger_scan()

    def _do_scan(self) -> None:
        try:
            procs    = self._monitor.scan()
            projects = self._monitor.group_into_projects(procs)
            projects = [
                p for p in projects
                if p.name
                and p.cwd != "/"
                and "Tina.app" not in (p.cwd or "")
            ]
        except Exception as exc:
            print(f"[TINA] scan error: {exc}")
            projects = []

        try:
            folders = self._folders.scan()
        except Exception as exc:
            print(f"[TINA] folder scan error: {exc}")
            folders = []

        # Network connections — try psutil first, fall back to lsof
        api_ports: list[tuple[int, str]] = []
        ext_conns: list[str] = []           # friendly-labelled external hosts
        try:
            conns = psutil.net_connections(kind="tcp")
            seen_ports: set[int] = set()
            seen_hosts: set[str] = set()
            for c in conns:
                if c.status == "LISTEN" and c.laddr:
                    port = c.laddr.port
                    if port not in seen_ports:
                        seen_ports.add(port)
                        api_ports.append((port, PORT_NAMES.get(port, "Service")))
                elif c.status == "ESTABLISHED" and c.raddr:
                    ip = c.raddr.ip
                    if not ip.startswith(("127.", "::1", "10.", "192.168.", "172.")):
                        if ip not in seen_hosts:
                            seen_hosts.add(ip)
                            ext_conns.append(ip)
        except Exception:
            # lsof fallback — parses LISTEN and ESTABLISHED lines
            try:
                r = subprocess.run(
                    ["lsof", "-i", "TCP", "-n", "-P"],
                    capture_output=True, text=True, timeout=5,
                )
                seen_ports = set()
                seen_hosts = set()
                for line in r.stdout.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) < 9:
                        continue
                    state = parts[-1].strip("()")
                    addr  = parts[8]
                    if state == "LISTEN":
                        try:
                            port = int(addr.rsplit(":", 1)[-1])
                            if port not in seen_ports:
                                seen_ports.add(port)
                                api_ports.append((port, PORT_NAMES.get(port, "Service")))
                        except ValueError:
                            pass
                    elif state == "ESTABLISHED" and "->" in addr:
                        remote = addr.split("->")[1]
                        ip = remote.rsplit(":", 1)[0].strip("[]")
                        if not ip.startswith(("127.", "::1", "10.", "192.168.", "172.", "fe80", "fd")):
                            if ip not in seen_hosts:
                                seen_hosts.add(ip)
                                ext_conns.append(ip)
            except Exception:
                pass
        api_ports.sort(key=lambda x: x[0])

        # Try hostname resolution for external IPs (non-blocking best-effort)
        import socket
        labelled_conns: list[str] = []
        for ip in ext_conns[:12]:
            try:
                host = socket.gethostbyaddr(ip)[0]
                labelled_conns.append(_label_host(host))
            except Exception:
                labelled_conns.append(ip)
        ext_conns = list(dict.fromkeys(labelled_conns))  # deduplicate preserving order

        # Network I/O rate
        net_stats = ("—", "—")
        try:
            net = psutil.net_io_counters()
            now = datetime.now().timestamp()
            if self._net_prev:
                prev_r, prev_s, prev_t = self._net_prev
                dt = max(1.0, now - prev_t)
                recv_rate = (net.bytes_recv - prev_r) / dt
                sent_rate = (net.bytes_sent - prev_s) / dt
                net_stats = (_human_bytes(recv_rate) + "/s", _human_bytes(sent_rate) + "/s")
            self._net_prev = (net.bytes_recv, net.bytes_sent, now)
        except Exception:
            pass

        # AI / browser activity
        try:
            ai_events = self._ai_monitor.scan()
        except Exception:
            ai_events = []

        self._root.after(0, lambda: self._on_scan_done(
            projects, folders, api_ports, ext_conns, net_stats, ai_events))

    def _on_scan_done(self, projects: list, folders: list,
                       api_ports: list, ext_conns: list,
                       net_stats: tuple, ai_events: list) -> None:
        self._projects        = projects
        self._folder_projects = folders
        self._api_ports       = api_ports
        self._ext_conns       = ext_conns
        self._net_stats       = net_stats
        self._ai_events       = ai_events
        self._scanning        = False

        project_names = {p.name for p in self._projects}
        for p in self._projects:
            if p.name not in self._timers:
                self._timers[p.name] = TimerState()

        active = self._state.get("active_focus")
        if active and active not in project_names:
            self._state["active_focus"] = None

        ts = datetime.now().strftime("%H:%M:%S")
        self._status_var.set(f"last scan: {ts}")
        self._render()

    def _trigger_scan(self) -> None:
        if self._scanning:
            return
        self._scanning       = True
        self._scan_remaining = REFRESH_S
        self._status_var.set("scanning…")
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _toggle_auto(self) -> None:
        self._auto_on = not self._auto_on
        if self._auto_on:
            self._auto_lbl.config(text="auto: on",  fg=GREEN)
            self._scan_remaining = REFRESH_S
        else:
            self._auto_lbl.config(text="auto: off", fg=DIM)

    # ── Wake handling ──────────────────────────────────────────────────────────

    def _on_wake(self, sleep_secs: float) -> None:
        """Called on wake-monitor thread — dispatch to main thread."""
        self._root.after(0, lambda: self._handle_wake(sleep_secs))

    def _handle_wake(self, sleep_secs: float) -> None:
        mins = int(sleep_secs / 60)
        append_log(self._state, f"System awake (slept ~{mins}m)")

        active   = self._state.get("active_focus")
        behavior = self._state.get("preferences", {}).get("wake_behavior", "ask_after_wake")
        timer    = self._timers.get(active) if active else None

        if active and timer and timer.running:
            elapsed  = int(sleep_secs)
            new_rem  = max(0, timer.remaining - elapsed)
            if behavior == "always_resume":
                timer.remaining = new_rem
                append_log(self._state, "Restoring session")
                self._trigger_scan()
            elif behavior == "ask_after_wake":
                timer.running = False
                self._show_wake_prompt(active, new_rem, elapsed)
        else:
            if behavior != "manual_only":
                self._trigger_scan()

    # ── macOS notification ─────────────────────────────────────────────────────

    def _notify(self, subtitle: str, message: str) -> None:
        try:
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{message}" with title "Tina" subtitle "{subtitle}"'],
                check=False, capture_output=True,
            )
        except Exception:
            pass

    # ── Dialogs ────────────────────────────────────────────────────────────────

    def _build_radio_group(self, pad, options: list, choice: tk.StringVar) -> None:
        """Render a list of (value, title, desc) radio options bound to choice."""
        current = choice.get()
        dots: dict[str, tk.Label] = {}

        def select(val: str) -> None:
            choice.set(val)
            for v, dot in dots.items():
                dot.config(text="●" if v == val else "○",
                           fg=GREEN if v == val else DIM)

        for value, title, desc in options:
            row = tk.Frame(pad, bg=BG)
            row.pack(anchor="w", pady=3, fill="x")
            dot = tk.Label(row, text="●" if value == current else "○",
                           bg=BG, fg=GREEN if value == current else DIM,
                           font=F_MD, cursor="hand2")
            dot.pack(side="left", padx=(0, 10))
            dots[value] = dot
            col = tk.Frame(row, bg=BG)
            col.pack(side="left")
            tk.Label(col, text=title, bg=BG, fg=TEXT, font=F_MD_B, anchor="w").pack(anchor="w")
            tk.Label(col, text=desc,  bg=BG, fg=DIM,  font=F_XS,  anchor="w").pack(anchor="w")
            for w in (dot, row, col):
                w.bind("<Button-1>", lambda _, v=value: select(v))

    def _show_first_launch(self) -> None:
        dlg = _Dialog(self._root, "480x400", "Welcome to Tina")
        pad = dlg.pad

        tk.Label(pad, text="Welcome to Tina", bg=BG, fg=TEXT,
                 font=("Helvetica Neue", 20, "bold")).pack(anchor="w")
        self._gap(pad, 6)
        tk.Label(pad, text="Your personal development secretary.",
                 bg=BG, fg=DIM, font=F_MD).pack(anchor="w")
        self._gap(pad, 24)
        tk.Label(pad, text="How would you like Tina to behave?",
                 bg=BG, fg=TEXT, font=F_MD).pack(anchor="w")
        self._gap(pad, 14)

        choice = tk.StringVar(value="always_resume")
        self._build_radio_group(pad, [
            ("always_resume",  "Always Resume Tina",
             "Start automatically · resume after sleep/wake"),
            ("ask_after_wake", "Ask Me After Wake",
             "Show a prompt when system wakes"),
            ("manual_only",    "Only Run When Opened",
             "Never launch or resume automatically"),
        ], choice)
        self._gap(pad, 24)

        def on_continue():
            self._state["preferences"]["wake_behavior"] = choice.get()
            self._state["preferences"]["first_launch"]  = False
            save_state(self._state)
            append_log(self._state, f"Setup: {choice.get()}")
            dlg.destroy()
            self._trigger_scan()

        cont = tk.Label(pad, text="Continue  →", bg=BG, fg=TEXT,
                        font=F_MD_B, cursor="hand2")
        cont.pack(anchor="w")
        cont.bind("<Button-1>", lambda _: on_continue())
        _hover(cont, GREEN, lambda: TEXT)

    def _show_wake_prompt(self, project: str, remaining: int, elapsed: int) -> None:
        dlg = _Dialog(self._root, "400x260", "Resume monitoring?")
        pad = dlg.pad

        tk.Label(pad, text="Resume Tina monitoring?", bg=BG, fg=TEXT,
                 font=("Helvetica Neue", 15, "bold")).pack(anchor="w")
        self._gap(pad, 8)
        tk.Label(pad, text=f"Last active: {project}",
                 bg=BG, fg=DIM, font=F_MD).pack(anchor="w")
        if remaining > 0:
            m, s = divmod(remaining, 60)
            tk.Label(pad, text=f"{m:02d}:{s:02d} remaining",
                     bg=BG, fg=DIM, font=F_MONO).pack(anchor="w", pady=(2, 0))

        self._gap(pad, 24)
        row = tk.Frame(pad, bg=BG)
        row.pack(anchor="w")

        def do_resume():
            self._do_resume(project, remaining)
            dlg.destroy()
            self._trigger_scan()

        def do_dismiss():
            append_log(self._state, "Wake prompt dismissed")
            dlg.destroy()
            self._trigger_scan()

        res = tk.Label(row, text="Resume", bg=BG, fg=GREEN, font=F_MD_B, cursor="hand2")
        res.pack(side="left")
        res.bind("<Button-1>", lambda _: do_resume())
        _hover(res, TEXT, lambda: GREEN)

        tk.Label(row, text="   ", bg=BG).pack(side="left")

        dis = tk.Label(row, text="Not Now", bg=BG, fg=DIM, font=F_MD, cursor="hand2")
        dis.pack(side="left")
        dis.bind("<Button-1>", lambda _: do_dismiss())
        _hover(dis, TEXT, lambda: DIM)

    def _show_settings(self) -> None:
        dlg = _Dialog(self._root, "420x340", "Settings")
        pad = dlg.pad

        tk.Label(pad, text="Keep Tina Running",
                 bg=BG, fg=TEXT, font=F_MD_B).pack(anchor="w")
        self._gap(pad, 14)

        choice = tk.StringVar(
            value=self._state.get("preferences", {}).get("wake_behavior", "ask_after_wake")
        )
        self._build_radio_group(pad, [
            ("always_resume",  "Always Resume Tina",
             "Restore automatically after sleep/wake"),
            ("ask_after_wake", "Ask Me After Wake",
             "Prompt on wake"),
            ("manual_only",    "Only Run When Opened",
             "Never auto-resume"),
        ], choice)
        self._gap(pad, 20)

        def do_save():
            self._state.setdefault("preferences", {})["wake_behavior"] = choice.get()
            save_state(self._state)
            dlg.destroy()

        sv = tk.Label(pad, text="Save", bg=BG, fg=TEXT, font=F_MD_B, cursor="hand2")
        sv.pack(anchor="w")
        sv.bind("<Button-1>", lambda _: do_save())
        _hover(sv, GREEN, lambda: TEXT)

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        append_log(self._state, "Tina closed")
        for name, timer in self._timers.items():
            self._sync_timer(name, running=timer.running)
        self._wake_monitor.stop()
        self._root.destroy()


# ── Utility: dialog window ─────────────────────────────────────────────────────

class _Dialog:
    def __init__(self, root: tk.Tk, geometry: str, title: str):
        self._win = tk.Toplevel(root)
        self._win.title("")
        self._win.configure(bg=BG)
        self._win.geometry(geometry)
        self._win.resizable(False, False)
        self._win.grab_set()
        self._win.lift()
        self.pad = tk.Frame(self._win, bg=BG)
        self.pad.pack(fill="both", expand=True, padx=36, pady=36)

    def destroy(self):
        self._win.destroy()


# ── Utility: hover effect ──────────────────────────────────────────────────────

def _hover(lbl: tk.Label, enter_fg: str, leave_fg_fn) -> None:
    lbl.bind("<Enter>", lambda _: lbl.config(fg=enter_fg))
    lbl.bind("<Leave>", lambda _: lbl.config(fg=leave_fg_fn()))


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    TinaApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
