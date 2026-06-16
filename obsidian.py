from pathlib import Path
from datetime import datetime
from typing import List, Optional


class ObsidianExporter:
    def __init__(self, vault_path: Optional[str] = None):
        if vault_path:
            self.vault_path = Path(vault_path)
        else:
            default = Path.home() / "Documents" / "ObsidianVault" / "Tina"
            self.vault_path = default

    def export(self, projects, blockers, system_info: dict) -> str:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        content = self._build_markdown(projects, blockers, date_str, time_str)
        self._save(content, date_str)
        return content

    def _build_markdown(self, projects, blockers, date_str: str, time_str: str) -> str:
        lines: List[str] = []

        if not projects:
            lines.append("# Tina Monitor Snapshot")
            lines.append(f"_Scanned: {date_str} {time_str}_")
            lines.append("")
            lines.append("No active development processes detected.")
            return "\n".join(lines)

        for project in projects:
            proj_blockers = [b for b in blockers if b.affected == project.name]

            lines.append(f"# Project: {project.name}")
            lines.append(f"_Last updated: {date_str} {time_str}_")
            lines.append("")

            lines.append("## State")
            lines.append(f"- **Status:** `{project.state}`")
            lines.append(f"- **Active modules:** {', '.join(project.services) or 'None'}")
            lines.append(f"- **Current task:** {project.current_task}")
            if project.ports:
                lines.append(f"- **Active ports:** {', '.join(str(p) for p in project.ports)}")
            lines.append("")

            lines.append("## Events")
            lines.append(f"- Scanned at `{time_str}`")
            lines.append(f"- {len(project.processes)} process(es) detected")
            for proc in project.processes:
                lines.append(
                    f"  - PID {proc.pid} — `{proc.display_name}` "
                    f"({proc.cpu_percent:.1f}% CPU, {proc.memory_mb:.1f} MB)"
                )
            lines.append("")

            lines.append("## Issues")
            if proj_blockers:
                for b in proj_blockers:
                    lines.append(f"- **[{b.severity}]** {b.description}")
                    lines.append(f"  - Fix: `{b.fix}`")
            else:
                lines.append("- None detected")
            lines.append("")

            lines.append("## Relationships")
            lines.append(f"- Project → {', '.join(project.services) or 'unknown'}")
            if project.cwd:
                lines.append(f"- Working directory: `{project.cwd}`")
            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def _save(self, content: str, date_str: str) -> None:
        try:
            self.vault_path.mkdir(parents=True, exist_ok=True)
            filepath = self.vault_path / f"tina-{date_str}.md"
            with open(filepath, 'w') as fh:
                fh.write(content)
        except (IOError, OSError, PermissionError):
            pass
