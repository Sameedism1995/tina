#!/usr/bin/env python3
"""
Tina — Local Development Monitoring and Project Awareness Agent

Usage:
  python main.py                         Single scan, print report
  python main.py --watch                 Watch mode (refresh every 30s)
  python main.py --watch --interval 60   Watch every 60 seconds
  python main.py --obsidian ~/Vault      Export Obsidian markdown to a custom vault path
  python main.py --no-obsidian           Skip the Obsidian memory block
"""

import argparse
import os
import sys
import time

try:
    import psutil  # noqa: F401 — imported here to give a friendly error early
except ImportError:
    print("[TINA] psutil is required. Install it with: pip install psutil")
    sys.exit(1)

from monitor import ProcessMonitor
from detector import BlockerDetector
from reporter import Reporter
from obsidian import ObsidianExporter


def _system_info() -> dict:
    return {
        'api_activity': 'No recent API calls detected',
        'build_activity': 'Monitoring file changes...',
    }


def run_scan(
    monitor: ProcessMonitor,
    detector: BlockerDetector,
    reporter: Reporter,
    exporter: ObsidianExporter,
    show_obsidian: bool = True,
) -> None:
    processes = monitor.scan()
    projects = monitor.group_into_projects(processes)
    blockers = detector.detect(projects)
    info = _system_info()

    print(reporter.format(projects, blockers, info))

    if show_obsidian:
        print("\nOBSIDIAN MEMORY:")
        print("```md")
        print(exporter.export(projects, blockers, info))
        print("```")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tina",
        description="Tina — Local Development Monitoring Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        '--watch', '-w',
        action='store_true',
        help='Run continuously in watch mode',
    )
    parser.add_argument(
        '--interval', '-i',
        type=int,
        default=30,
        metavar='SECONDS',
        help='Refresh interval for watch mode (default: 30)',
    )
    parser.add_argument(
        '--obsidian', '-o',
        type=str,
        default=None,
        metavar='PATH',
        help='Obsidian vault path for markdown export',
    )
    parser.add_argument(
        '--no-obsidian',
        action='store_true',
        help='Suppress the Obsidian memory block in output',
    )
    args = parser.parse_args()

    monitor = ProcessMonitor()
    detector = BlockerDetector()
    reporter = Reporter()
    exporter = ObsidianExporter(vault_path=args.obsidian)
    show_obsidian = not args.no_obsidian

    if args.watch:
        print(f"[TINA] Watch mode — refreshing every {args.interval}s. Ctrl-C to stop.\n")
        try:
            while True:
                os.system('clear' if os.name == 'posix' else 'cls')
                run_scan(monitor, detector, reporter, exporter, show_obsidian)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[TINA] Monitoring stopped.")
    else:
        run_scan(monitor, detector, reporter, exporter, show_obsidian)


if __name__ == '__main__':
    main()
