import os
import time
import psutil
from dataclasses import dataclass, field
from typing import List, Optional, Dict

DEV_PROCESS_NAMES: Dict[str, str] = {
    'node': 'Node.js',
    'npm': 'npm',
    'yarn': 'Yarn',
    'pnpm': 'pnpm',
    'python': 'Python',
    'python3': 'Python',
    'uvicorn': 'Uvicorn',
    'gunicorn': 'Gunicorn',
    'fastapi': 'FastAPI',
    'cargo': 'Rust/Cargo',
    'go': 'Go',
    'java': 'Java',
    'gradle': 'Gradle',
    'mvn': 'Maven',
    'ruby': 'Ruby',
    'rails': 'Rails',
    'php': 'PHP',
    'webpack': 'Webpack',
    'vite': 'Vite',
    'next': 'Next.js',
    'nuxt': 'Nuxt.js',
    'gatsby': 'Gatsby',
    'docker': 'Docker',
    'docker-compose': 'Docker Compose',
    'redis-server': 'Redis',
    'postgres': 'PostgreSQL',
    'mongod': 'MongoDB',
    'mysql': 'MySQL',
    'sqlite': 'SQLite',
    'deno': 'Deno',
    'bun': 'Bun',
}


@dataclass
class DevProcess:
    pid: int
    name: str
    display_name: str
    cmdline: List[str]
    cwd: Optional[str]
    cpu_percent: float
    memory_mb: float
    ports: List[int]
    status: str
    create_time: float


@dataclass
class Project:
    name: str
    state: str
    cwd: Optional[str] = None
    processes: List[DevProcess] = field(default_factory=list)
    ports: List[int] = field(default_factory=list)
    services: List[str] = field(default_factory=list)
    current_task: str = ""


class ProcessMonitor:
    def scan(self) -> List[DevProcess]:
        proc_ports = self._get_process_ports()
        procs_raw: Dict[int, psutil.Process] = {}

        # First pass: start CPU measurement (non-blocking)
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd', 'status', 'create_time']):
            try:
                if self._is_dev_process(proc.info):
                    proc.cpu_percent()
                    procs_raw[proc.pid] = proc
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        time.sleep(0.5)

        dev_processes: List[DevProcess] = []
        for pid, proc in procs_raw.items():
            try:
                info = proc.info
                display_name = self._resolve_display_name(info)
                if not display_name:
                    continue

                try:
                    cpu = proc.cpu_percent()
                    mem = proc.memory_info().rss / 1024 / 1024
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    cpu, mem = 0.0, 0.0

                dev_processes.append(DevProcess(
                    pid=pid,
                    name=(info['name'] or '').lower(),
                    display_name=display_name,
                    cmdline=info.get('cmdline') or [],
                    cwd=info.get('cwd'),
                    cpu_percent=cpu,
                    memory_mb=mem,
                    ports=proc_ports.get(pid, []),
                    status=info.get('status', 'unknown'),
                    create_time=info.get('create_time', 0.0),
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        return dev_processes

    def _is_dev_process(self, info: dict) -> bool:
        name = (info.get('name') or '').lower()
        if any(name.startswith(k) for k in DEV_PROCESS_NAMES):
            return True
        for arg in (info.get('cmdline') or []):
            base = os.path.basename(str(arg)).lower()
            if any(base.startswith(k) for k in DEV_PROCESS_NAMES):
                return True
        return False

    def _resolve_display_name(self, info: dict) -> Optional[str]:
        name = (info.get('name') or '').lower()
        for key, val in DEV_PROCESS_NAMES.items():
            if name.startswith(key):
                return val

        for arg in (info.get('cmdline') or []):
            base = os.path.basename(str(arg)).lower()
            for key, val in DEV_PROCESS_NAMES.items():
                if base.startswith(key):
                    return val
        return None

    def _get_process_ports(self) -> Dict[int, List[int]]:
        ports_by_pid: Dict[int, List[int]] = {}
        try:
            for conn in psutil.net_connections(kind='tcp'):
                if conn.status == 'LISTEN' and conn.laddr and conn.pid:
                    ports_by_pid.setdefault(conn.pid, []).append(conn.laddr.port)
        except (psutil.AccessDenied, PermissionError):
            pass
        return ports_by_pid

    def group_into_projects(self, processes: List[DevProcess]) -> List[Project]:
        groups: Dict[str, Project] = {}

        for proc in processes:
            key = proc.cwd or f"proc_{proc.pid}"
            if key not in groups:
                name = os.path.basename(proc.cwd) if proc.cwd else proc.display_name
                groups[key] = Project(name=name, state='IDLE', cwd=proc.cwd)

            groups[key].processes.append(proc)
            groups[key].ports.extend(proc.ports)
            groups[key].services.append(proc.display_name)

        for project in groups.values():
            project.services = sorted(set(project.services))
            project.ports = sorted(set(project.ports))
            project.state = self._determine_state(project)
            project.current_task = self._infer_task(project)

        return list(groups.values())

    def _determine_state(self, project: Project) -> str:
        if not project.processes:
            return 'IDLE'
        total_cpu = sum(p.cpu_percent for p in project.processes)
        if total_cpu > 50:
            return 'ACTIVE'
        if total_cpu > 5:
            return 'RUNNING'
        return 'IDLE'

    def _infer_task(self, project: Project) -> str:
        services = {s.lower() for s in project.services}
        ports = project.ports

        task_map = [
            ({'webpack'}, "Building/bundling frontend assets"),
            ({'vite'}, "Running Vite dev server"),
            ({'next.js'}, "Running Next.js dev server"),
            ({'nuxt.js'}, "Running Nuxt.js dev server"),
            ({'gatsby'}, "Running Gatsby dev server"),
            ({'uvicorn', 'gunicorn', 'fastapi'}, "Serving Python API"),
            ({'rust/cargo'}, "Rust build or cargo run"),
            ({'redis'}, "Redis cache running"),
            ({'postgresql', 'mysql', 'mongodb', 'sqlite'}, "Database service running"),
            ({'docker', 'docker compose'}, "Docker containers running"),
        ]

        for match_set, label in task_map:
            if services & match_set:
                return label

        if 'node.js' in services and ports:
            return f"Node.js server on port {ports[0]}"
        if 'python' in services:
            return "Running Python script or server"
        if ports:
            return f"Service listening on port {ports[0]}"

        return "Development service running"
