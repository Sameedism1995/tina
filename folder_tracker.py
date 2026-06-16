import os
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

PROJECT_MARKERS = {
    'package.json':   'Node.js',
    'requirements.txt': 'Python',
    'pyproject.toml': 'Python',
    'Pipfile':        'Python',
    'Cargo.toml':     'Rust',
    'go.mod':         'Go',
    'pom.xml':        'Java',
    'build.gradle':   'Java',
    'Gemfile':        'Ruby',
    'composer.json':  'PHP',
    'pubspec.yaml':   'Flutter',
    'CMakeLists.txt': 'C/C++',
    'Makefile':       'Make',
    'mix.exs':        'Elixir',
    '.xcode':         'Xcode',
}

SCAN_ROOTS = [
    Path.home() / 'Documents',
    Path.home() / 'Desktop',
    Path.home() / 'Projects',
    Path.home() / 'Developer',
    Path.home() / 'dev',
    Path.home() / 'code',
    Path.home() / 'Code',
    Path.home() / 'workspace',
    Path.home() / 'Sites',
]

SKIP_DIRS = {
    'node_modules', '__pycache__', '.venv', 'venv', '.git',
    'dist', 'build', 'target', '.cache', '.tox', 'coverage',
    '.next', '.nuxt', 'out', '.parcel-cache',
}

MAX_RESULTS = 5
MAX_DEPTH   = 2


@dataclass
class FolderProject:
    name:          str
    path:          str
    project_type:  str
    last_modified: float        # epoch seconds
    is_git:        bool
    git_branch:    Optional[str] = None
    recent_file:   Optional[str] = None

    def idle_since(self) -> str:
        secs = time.time() - self.last_modified
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{int(secs // 60)}m ago"
        if secs < 86400:
            return f"{int(secs // 3600)}h ago"
        return f"{int(secs // 86400)}d ago"


class FolderScanner:
    def scan(self) -> List[FolderProject]:
        results: List[FolderProject] = []
        seen: set = set()

        for root in SCAN_ROOTS:
            if not root.exists():
                continue
            try:
                self._walk(root, 0, results, seen)
            except (PermissionError, OSError):
                continue

        # Sort by most-recently-modified, then cap — do NOT cap during the walk
        # so alphabetically-later folders (e.g. salxir websites) get a fair chance
        results.sort(key=lambda p: p.last_modified, reverse=True)
        return results[:MAX_RESULTS]

    def _walk(self, path: Path, depth: int,
              results: list, seen: set) -> None:
        if depth > MAX_DEPTH:
            return

        # Check if this directory is a project root
        ptype = self._project_type(path)
        if ptype:
            resolved = str(path.resolve())
            if resolved not in seen:
                seen.add(resolved)
                proj = self._build(path, ptype)
                if proj:
                    results.append(proj)
            return  # don't recurse into a project root

        # Otherwise recurse one level deeper
        if depth < MAX_DEPTH:
            try:
                for entry in sorted(path.iterdir(), key=lambda e: e.name):
                    if (entry.is_dir()
                            and not entry.name.startswith('.')
                            and entry.name not in SKIP_DIRS):
                        try:
                            self._walk(entry, depth + 1, results, seen)
                        except (PermissionError, OSError):
                            continue
            except (PermissionError, OSError):
                pass

    def _project_type(self, path: Path) -> Optional[str]:
        for marker, ptype in PROJECT_MARKERS.items():
            if (path / marker).exists():
                return ptype
        return None

    def _build(self, path: Path, ptype: str) -> Optional[FolderProject]:
        try:
            last_mod, recent = self._last_modified(path)
            is_git = (path / '.git').exists()
            branch = self._git_branch(path) if is_git else None
            return FolderProject(
                name=path.name,
                path=str(path),
                project_type=ptype,
                last_modified=last_mod,
                is_git=is_git,
                git_branch=branch,
                recent_file=recent,
            )
        except (PermissionError, OSError):
            return None

    def _last_modified(self, path: Path):
        latest = path.stat().st_mtime
        latest_name = None
        try:
            for entry in path.iterdir():
                if entry.name.startswith('.') or entry.name in SKIP_DIRS:
                    continue
                try:
                    mtime = entry.stat().st_mtime
                    if mtime > latest:
                        latest = mtime
                        latest_name = entry.name
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            pass
        return latest, latest_name

    def _git_branch(self, path: Path) -> Optional[str]:
        try:
            head = path / '.git' / 'HEAD'
            if head.exists():
                content = head.read_text().strip()
                if content.startswith('ref: refs/heads/'):
                    return content[len('ref: refs/heads/'):]
                return content[:8]
        except (OSError, IOError):
            pass
        return None
