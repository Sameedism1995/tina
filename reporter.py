from datetime import datetime
from typing import List


class Reporter:
    WIDTH = 62

    def format(self, projects, blockers, system_info: dict) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines: List[str] = []

        lines.append("=" * self.WIDTH)
        lines.append(f"  TINA — Development Monitor    {ts}")
        lines.append("=" * self.WIDTH)

        # ── PROJECT STATUS ────────────────────────────────────────
        if not projects:
            lines.append("\nPROJECT STATUS:")
            lines.append("  No active development processes detected.")
        else:
            for project in projects:
                lines.append("\nPROJECT STATUS:")
                lines.append(f"  Project:      {project.name}")
                lines.append(f"  State:        {project.state}")
                lines.append(f"  Current Task: {project.current_task}")

        # ── SYSTEM ACTIVITY ───────────────────────────────────────
        lines.append("\n" + "-" * self.WIDTH)
        lines.append("SYSTEM ACTIVITY:")

        all_services = sorted({s for p in projects for s in p.services})
        all_ports = sorted({port for p in projects for port in p.ports})

        lines.append(f"  Running Services: {', '.join(all_services) if all_services else 'None'}")
        if all_ports:
            lines.append(f"  Active Ports:    {', '.join(str(p) for p in all_ports)}")
        lines.append(f"  API Activity:    {system_info.get('api_activity', 'None detected')}")
        lines.append(f"  File/Build:      {system_info.get('build_activity', 'Monitoring...')}")

        # ── BLOCKERS ──────────────────────────────────────────────
        lines.append("\n" + "-" * self.WIDTH)
        lines.append("BLOCKERS:")
        if not blockers:
            lines.append("  None")
        else:
            for b in blockers:
                lines.append(f"  [{b.severity}] {b.description}")
                lines.append(f"         Fix: {b.fix}")

        # ── IMPACT ────────────────────────────────────────────────
        lines.append("\n" + "-" * self.WIDTH)
        lines.append("IMPACT:")
        high = [b for b in blockers if b.severity == 'HIGH']
        medium = [b for b in blockers if b.severity == 'MEDIUM']
        if high:
            affected = ', '.join(sorted({b.affected for b in high}))
            lines.append(f"  CRITICAL — {affected} may be unable to start or function")
        elif medium:
            lines.append("  Services may be degraded — review MEDIUM blockers")
        elif blockers:
            lines.append("  Minor issues present — services should still run")
        else:
            lines.append("  None — environment looks healthy")

        # ── NEXT STEP ─────────────────────────────────────────────
        lines.append("\n" + "-" * self.WIDTH)
        lines.append("NEXT STEP:")
        if blockers:
            top = blockers[0]
            lines.append(f"  {top.fix}")
        elif not projects:
            lines.append("  Navigate to your project folder and start your dev server.")
        else:
            running = [p for p in projects if p.state in ('ACTIVE', 'RUNNING')]
            if running:
                lines.append(f"  Continue working — {running[0].name} is running normally.")
            else:
                lines.append("  Services are idle. Start your dev server if needed.")

        lines.append("\n" + "=" * self.WIDTH)
        return "\n".join(lines)
