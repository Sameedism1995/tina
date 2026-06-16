import re
from pathlib import Path
from dataclasses import dataclass
from typing import List


SEVERITY_ORDER = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}

ERROR_PATTERNS = [
    (r'EADDRINUSE',                                     'HIGH',   "Port already in use",
     "Find the process: `lsof -i :<port>` then kill it"),
    (r'ECONNREFUSED',                                   'HIGH',   "Connection refused — dependent service may be down",
     "Ensure the required service (DB, cache, API) is running"),
    (r'Cannot find module',                             'HIGH',   "Missing Node.js module",
     "Run `npm install` or `yarn install`"),
    (r'ModuleNotFoundError|ImportError',                'HIGH',   "Missing Python module",
     "Run `pip install -r requirements.txt` or install the missing package"),
    (r'Error: listen EACCES',                           'HIGH',   "Permission denied on port",
     "Use a port above 1024 or run with elevated permissions"),
    (r'DATABASE_URL.*not.*set|missing.*DATABASE_URL',   'HIGH',   "Missing DATABASE_URL env variable",
     "Set DATABASE_URL in your .env file"),
    (r'ENOMEM|out of memory|Killed',                    'HIGH',   "Out of memory",
     "Free system memory or increase container limits"),
    (r'webpack.*[Ee]rror|Build failed|ERROR in ',       'HIGH',   "Build failure",
     "Check build output for the specific module or syntax error"),
    (r'npm ERR!',                                       'HIGH',   "npm error",
     "Run `npm cache clean --force` then `npm install`"),
    (r'yarn error',                                     'HIGH',   "Yarn error",
     "Run `yarn cache clean` then `yarn install`"),
    (r'SyntaxError',                                    'MEDIUM', "Syntax error in source code",
     "Fix the syntax error reported above the traceback"),
    (r'TypeError',                                      'MEDIUM', "Type error at runtime",
     "Review the traceback — a value is likely None or the wrong type"),
    (r'401 Unauthorized',                               'MEDIUM', "API authentication failure (401)",
     "Check your API key or authentication token"),
    (r'403 Forbidden',                                  'MEDIUM', "API authorization failure (403)",
     "Verify API permissions and credentials"),
    (r'timeout|ETIMEDOUT',                              'MEDIUM', "Connection timeout",
     "Check network connectivity and service availability"),
    (r'ENOENT.*\.env',                                  'MEDIUM', "Missing .env file referenced in code",
     "Create the .env file from .env.example and fill in values"),
]


@dataclass
class Blocker:
    severity: str
    description: str
    affected: str
    fix: str


class BlockerDetector:
    def detect(self, projects) -> List[Blocker]:
        blockers: List[Blocker] = []
        seen: set = set()

        for project in projects:
            if project.cwd:
                for b in self._check_missing_files(project):
                    key = (b.severity, b.description)
                    if key not in seen:
                        seen.add(key)
                        blockers.append(b)
                for b in self._check_log_files(project):
                    key = (b.severity, b.description)
                    if key not in seen:
                        seen.add(key)
                        blockers.append(b)

        blockers.sort(key=lambda b: SEVERITY_ORDER.get(b.severity, 9))
        return blockers

    def _check_missing_files(self, project) -> List[Blocker]:
        blockers: List[Blocker] = []
        cwd = Path(project.cwd)

        if (cwd / 'package.json').exists() and not (cwd / 'node_modules').exists():
            blockers.append(Blocker(
                severity='HIGH',
                description=f"node_modules missing in '{project.name}'",
                affected=project.name,
                fix="Run `npm install` or `yarn install`",
            ))

        if (cwd / '.env.example').exists() and not (cwd / '.env').exists():
            blockers.append(Blocker(
                severity='MEDIUM',
                description=f".env file missing in '{project.name}'",
                affected=project.name,
                fix="Copy `.env.example` to `.env` and fill in the values",
            ))

        if (cwd / 'requirements.txt').exists():
            has_venv = (cwd / 'venv').exists() or (cwd / '.venv').exists()
            if not has_venv:
                blockers.append(Blocker(
                    severity='LOW',
                    description=f"No virtual environment found in '{project.name}'",
                    affected=project.name,
                    fix="Run `python -m venv venv && source venv/bin/activate && pip install -r requirements.txt`",
                ))

        if (cwd / 'go.mod').exists() and not (cwd / 'go.sum').exists():
            blockers.append(Blocker(
                severity='MEDIUM',
                description=f"go.sum missing in '{project.name}'",
                affected=project.name,
                fix="Run `go mod tidy`",
            ))

        return blockers

    def _check_log_files(self, project) -> List[Blocker]:
        blockers: List[Blocker] = []
        cwd = Path(project.cwd)
        log_candidates = (
            list(cwd.glob('*.log'))
            + list(cwd.glob('logs/*.log'))
            + list(cwd.glob('log/*.log'))
        )

        for log_file in log_candidates[:5]:
            try:
                with open(log_file, 'r', errors='ignore') as fh:
                    fh.seek(0, 2)
                    size = fh.tell()
                    fh.seek(max(0, size - 8192))
                    tail = fh.read()

                for pattern, severity, description, fix in ERROR_PATTERNS:
                    if re.search(pattern, tail, re.IGNORECASE):
                        blockers.append(Blocker(
                            severity=severity,
                            description=f"{description} (detected in {log_file.name})",
                            affected=project.name,
                            fix=fix,
                        ))
                        break
            except (IOError, OSError, PermissionError):
                continue

        return blockers
