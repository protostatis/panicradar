"""
Task Manager for monitoring and controlling crawlers.

Provides a central dashboard for:
- Viewing running tasks (crawlers, backfills, signals)
- Starting/stopping tasks
- Viewing logs and progress
- Health monitoring
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .logging_config import logger
from .storage.db import Database


@dataclass
class TaskInfo:
    """Information about a managed task."""

    name: str
    pid: Optional[int]
    status: str  # "running", "stopped", "error", "unknown"
    started_at: Optional[datetime]
    log_file: Optional[str]
    command: str
    description: str
    last_activity: Optional[datetime] = None
    error: Optional[str] = None


class TaskManager:
    """Manages and monitors crawler tasks."""

    STATE_FILE = "data/task_manager_state.json"

    # Task definitions
    TASK_DEFINITIONS = {
        "crawler": {
            "command": "uv run python -m crypto_sentiment_crawler.main",
            "description": "Live Reddit sentiment crawler",
            "log_prefix": "crawler",
        },
        "backfill": {
            "command": "uv run python -m crypto_sentiment_crawler.backfill",
            "description": "Historical Reddit backfill",
            "log_prefix": "backfill",
        },
        "twitter_backfill": {
            "command": "uv run python -m crypto_sentiment_crawler.twitter_backfill",
            "description": "Twitter/X sentiment backfill",
            "log_prefix": "twitter_backfill",
        },
        "biz_backfill": {
            "command": "uv run python -m crypto_sentiment_crawler.biz_backfill",
            "description": "4chan /biz/ sentiment backfill",
            "log_prefix": "biz_backfill",
        },
        "cryptopanic_backfill": {
            "command": "uv run python -m crypto_sentiment_crawler.cryptopanic_backfill",
            "description": "CryptoPanic news sentiment backfill",
            "log_prefix": "cryptopanic_backfill",
        },
        "bitcointalk_backfill": {
            "command": "uv run python -m crypto_sentiment_crawler.bitcointalk_backfill",
            "description": "Bitcointalk forum backfill",
            "log_prefix": "bitcointalk_backfill",
        },
        "stocktwits_backfill": {
            "command": "uv run python -m crypto_sentiment_crawler.stocktwits_backfill",
            "description": "Stocktwits crypto sentiment backfill",
            "log_prefix": "stocktwits_backfill",
        },
        "collector": {
            "command": "uv run python -m crypto_sentiment_crawler.scheduled_collector",
            "description": "Scheduled multi-source collector",
            "log_prefix": "collector",
        },
        "backtest": {
            "command": "uv run python -m crypto_sentiment_crawler.analysis.backtest_analysis",
            "description": "Run backtest analysis",
            "log_prefix": "backtest",
        },
        "price_backfill": {
            "command": "uv run python -m crypto_sentiment_crawler.price_backfill",
            "description": "Historical price data backfill",
            "log_prefix": "price_backfill",
        },
        "signals": {
            "command": "uv run signals run",
            "description": "Contrarian signal detector",
            "log_prefix": "signals",
        },
    }

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path.cwd()
        self.logs_dir = self.project_root / "logs"
        self.data_dir = self.project_root / "data"
        self.tasks: dict[str, TaskInfo] = {}

        # Ensure directories exist
        self.logs_dir.mkdir(exist_ok=True)
        self.data_dir.mkdir(exist_ok=True)

        # Load saved state
        self._load_state()

    def _load_state(self) -> None:
        """Load task state from file."""
        state_path = self.project_root / self.STATE_FILE
        if state_path.exists():
            try:
                with open(state_path) as f:
                    data = json.load(f)
                for name, info in data.get("tasks", {}).items():
                    self.tasks[name] = TaskInfo(
                        name=name,
                        pid=info.get("pid"),
                        status="unknown",
                        started_at=datetime.fromisoformat(info["started_at"]) if info.get("started_at") else None,
                        log_file=info.get("log_file"),
                        command=info.get("command", ""),
                        description=info.get("description", ""),
                    )
            except Exception as e:
                logger.warning(f"Failed to load task state: {e}")

    def _save_state(self) -> None:
        """Save task state to file."""
        state_path = self.project_root / self.STATE_FILE
        data = {
            "tasks": {
                name: {
                    "pid": task.pid,
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "log_file": task.log_file,
                    "command": task.command,
                    "description": task.description,
                }
                for name, task in self.tasks.items()
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(state_path, "w") as f:
            json.dump(data, f, indent=2)

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is running."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _get_log_file(self, prefix: str) -> str:
        """Generate a log file path."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(self.logs_dir / f"{prefix}_{timestamp}.log")

    def _find_running_by_command(self, command_pattern: str) -> Optional[int]:
        """Find a running process by command pattern."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", command_pattern],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                pids = result.stdout.strip().split("\n")
                if pids and pids[0]:
                    return int(pids[0])
        except Exception:
            pass
        return None

    def update_status(self) -> None:
        """Update status of all tasks."""
        for name, task in self.tasks.items():
            if task.pid:
                if self._is_process_running(task.pid):
                    task.status = "running"
                    # Check log file for activity
                    if task.log_file and Path(task.log_file).exists():
                        mtime = Path(task.log_file).stat().st_mtime
                        task.last_activity = datetime.fromtimestamp(mtime)
                else:
                    task.status = "stopped"
                    task.pid = None
            else:
                # Try to find by command
                if name in self.TASK_DEFINITIONS:
                    cmd = self.TASK_DEFINITIONS[name]["command"]
                    pid = self._find_running_by_command(cmd)
                    if pid:
                        task.pid = pid
                        task.status = "running"
                    else:
                        task.status = "stopped"

    def start_task(self, name: str) -> TaskInfo:
        """Start a task by name."""
        if name not in self.TASK_DEFINITIONS:
            raise ValueError(f"Unknown task: {name}")

        # Check if already running
        self.update_status()
        if name in self.tasks and self.tasks[name].status == "running":
            return self.tasks[name]

        definition = self.TASK_DEFINITIONS[name]
        log_file = self._get_log_file(definition["log_prefix"])

        # Start the process
        with open(log_file, "w") as log:
            process = subprocess.Popen(
                definition["command"],
                shell=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=self.project_root,
                start_new_session=True,
            )

        task = TaskInfo(
            name=name,
            pid=process.pid,
            status="running",
            started_at=datetime.now(timezone.utc),
            log_file=log_file,
            command=definition["command"],
            description=definition["description"],
        )
        self.tasks[name] = task
        self._save_state()

        logger.info(f"Started task '{name}' with PID {process.pid}")
        return task

    def stop_task(self, name: str, force: bool = False) -> bool:
        """Stop a task by name."""
        if name not in self.tasks:
            return False

        task = self.tasks[name]
        if not task.pid:
            return False

        try:
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.kill(task.pid, sig)
            task.status = "stopped"
            task.pid = None
            self._save_state()
            logger.info(f"Stopped task '{name}'")
            return True
        except (OSError, ProcessLookupError):
            task.status = "stopped"
            task.pid = None
            self._save_state()
            return True

    def get_task(self, name: str) -> Optional[TaskInfo]:
        """Get task info by name."""
        self.update_status()
        return self.tasks.get(name)

    def list_tasks(self) -> list[TaskInfo]:
        """List all tasks with updated status."""
        self.update_status()
        return list(self.tasks.values())

    def get_log_tail(self, name: str, lines: int = 50) -> str:
        """Get the last N lines of a task's log."""
        task = self.tasks.get(name)
        if not task or not task.log_file:
            return ""

        log_path = Path(task.log_file)
        if not log_path.exists():
            return ""

        try:
            result = subprocess.run(
                ["tail", "-n", str(lines), str(log_path)],
                capture_output=True,
                text=True,
            )
            return result.stdout
        except Exception:
            return ""

    def register_running(self, name: str, pid: int, log_file: Optional[str] = None) -> TaskInfo:
        """Manually register an already-running process."""
        if name not in self.TASK_DEFINITIONS:
            raise ValueError(f"Unknown task: {name}")

        if not self._is_process_running(pid):
            raise ValueError(f"PID {pid} is not running")

        definition = self.TASK_DEFINITIONS[name]

        task = TaskInfo(
            name=name,
            pid=pid,
            status="running",
            started_at=datetime.now(timezone.utc),  # Approximate
            log_file=log_file,
            command=definition["command"],
            description=definition["description"],
        )
        self.tasks[name] = task
        self._save_state()

        logger.info(f"Registered existing task '{name}' with PID {pid}")
        return task

    def auto_discover(self) -> list[TaskInfo]:
        """Auto-discover running tasks by searching for known processes."""
        discovered = []

        # Patterns to search for
        patterns = {
            "crawler": ["crypto_sentiment_crawler.main", "crypto_sentiment_crawler.scheduler"],
            "backfill": ["crypto_sentiment_crawler.backfill"],
            "price_backfill": ["crypto_sentiment_crawler.price_backfill"],
            "signals": ["signals run", "signals.service"],
        }

        for name, search_patterns in patterns.items():
            if name in self.tasks and self.tasks[name].status == "running":
                continue  # Already tracked

            for pattern in search_patterns:
                pid = self._find_running_by_command(pattern)
                if pid:
                    # Find the most recent log file
                    log_prefix = self.TASK_DEFINITIONS[name]["log_prefix"]
                    log_files = sorted(
                        self.logs_dir.glob(f"{log_prefix}_*.log"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                    log_file = str(log_files[0]) if log_files else None

                    task = TaskInfo(
                        name=name,
                        pid=pid,
                        status="running",
                        started_at=datetime.now(timezone.utc),
                        log_file=log_file,
                        command=self.TASK_DEFINITIONS[name]["command"],
                        description=self.TASK_DEFINITIONS[name]["description"],
                    )
                    self.tasks[name] = task
                    discovered.append(task)
                    break

        if discovered:
            self._save_state()

        return discovered

    def get_stats(self) -> dict:
        """Get overall task statistics."""
        self.update_status()
        stats = {
            "total": len(self.tasks),
            "running": sum(1 for t in self.tasks.values() if t.status == "running"),
            "stopped": sum(1 for t in self.tasks.values() if t.status == "stopped"),
            "tasks": {},
        }
        for name, task in self.tasks.items():
            stats["tasks"][name] = {
                "status": task.status,
                "pid": task.pid,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "description": task.description,
            }
        return stats


def print_status(manager: TaskManager) -> None:
    """Print formatted status of all tasks."""
    print("\n" + "=" * 70)
    print("TASK MANAGER STATUS")
    print("=" * 70)

    tasks = manager.list_tasks()

    if not tasks:
        print("\nNo tasks registered.")
        print("\nAvailable tasks to start:")
        for name, defn in manager.TASK_DEFINITIONS.items():
            print(f"  - {name}: {defn['description']}")
    else:
        print(f"\n{'Task':<20} {'Status':<10} {'PID':<8} {'Started':<20} {'Description'}")
        print("-" * 70)

        for task in tasks:
            status_icon = "🟢" if task.status == "running" else "🔴"
            started = task.started_at.strftime("%Y-%m-%d %H:%M") if task.started_at else "-"
            pid = str(task.pid) if task.pid else "-"
            print(f"{task.name:<20} {status_icon} {task.status:<7} {pid:<8} {started:<20} {task.description[:25]}")

    # Show available tasks not yet started
    registered_names = {t.name for t in tasks}
    available = [n for n in manager.TASK_DEFINITIONS if n not in registered_names]
    if available:
        print(f"\nAvailable: {', '.join(available)}")

    print("=" * 70)


def interactive_menu(manager: TaskManager) -> None:
    """Run interactive menu for task management."""
    while True:
        print_status(manager)
        print("\nCommands:")
        print("  start <task>  - Start a task")
        print("  stop <task>   - Stop a task")
        print("  logs <task>   - View task logs")
        print("  refresh       - Refresh status")
        print("  quit          - Exit")
        print()

        try:
            cmd = input(">>> ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break

        if not cmd:
            continue

        parts = cmd.split()
        action = parts[0]

        if action == "quit" or action == "q":
            break
        elif action == "refresh" or action == "r":
            continue
        elif action == "start" and len(parts) > 1:
            task_name = parts[1]
            try:
                task = manager.start_task(task_name)
                print(f"✅ Started {task_name} (PID: {task.pid})")
            except ValueError as e:
                print(f"❌ Error: {e}")
        elif action == "stop" and len(parts) > 1:
            task_name = parts[1]
            if manager.stop_task(task_name):
                print(f"✅ Stopped {task_name}")
            else:
                print(f"❌ Could not stop {task_name}")
        elif action == "logs" and len(parts) > 1:
            task_name = parts[1]
            logs = manager.get_log_tail(task_name, 30)
            if logs:
                print(f"\n--- Last 30 lines of {task_name} ---")
                print(logs)
                print("--- End of logs ---\n")
            else:
                print(f"No logs found for {task_name}")
        else:
            print("Unknown command. Try: start, stop, logs, refresh, quit")


async def get_db_stats() -> dict:
    """Get database statistics."""
    db = Database()
    await db.connect()

    stats = {}

    # Sentiment records
    cursor = await db.conn.execute("SELECT COUNT(*) FROM sentiment_raw")
    row = await cursor.fetchone()
    stats["sentiment_raw"] = row[0] if row else 0

    cursor = await db.conn.execute("SELECT COUNT(*) FROM sentiment_scores")
    row = await cursor.fetchone()
    stats["sentiment_scores"] = row[0] if row else 0

    # Price records
    cursor = await db.conn.execute("SELECT COUNT(*) FROM price_data")
    row = await cursor.fetchone()
    stats["price_data"] = row[0] if row else 0

    # Date range
    cursor = await db.conn.execute(
        "SELECT MIN(timestamp), MAX(timestamp) FROM sentiment_scores"
    )
    row = await cursor.fetchone()
    if row and row[0]:
        stats["date_range"] = {"min": row[0], "max": row[1]}

    await db.close()
    return stats


def main():
    """Main entry point for task manager CLI."""
    import argparse

    parser = argparse.ArgumentParser(description="Crypto Sentiment Crawler Task Manager")
    parser.add_argument("command", nargs="?", default="status",
                        choices=["status", "start", "stop", "logs", "stats", "interactive", "discover"],
                        help="Command to run")
    parser.add_argument("task", nargs="?", help="Task name for start/stop/logs")
    parser.add_argument("-n", "--lines", type=int, default=50, help="Number of log lines")

    args = parser.parse_args()

    manager = TaskManager()

    if args.command == "status":
        print_status(manager)

    elif args.command == "start":
        if not args.task:
            print("Usage: taskmanager start <task>")
            print(f"Available: {', '.join(manager.TASK_DEFINITIONS.keys())}")
            sys.exit(1)
        try:
            task = manager.start_task(args.task)
            print(f"✅ Started {args.task} (PID: {task.pid})")
            print(f"   Log: {task.log_file}")
        except ValueError as e:
            print(f"❌ Error: {e}")
            sys.exit(1)

    elif args.command == "stop":
        if not args.task:
            print("Usage: taskmanager stop <task>")
            sys.exit(1)
        if manager.stop_task(args.task):
            print(f"✅ Stopped {args.task}")
        else:
            print(f"❌ Could not stop {args.task}")

    elif args.command == "logs":
        if not args.task:
            print("Usage: taskmanager logs <task>")
            sys.exit(1)
        logs = manager.get_log_tail(args.task, args.lines)
        if logs:
            print(logs)
        else:
            print(f"No logs found for {args.task}")

    elif args.command == "stats":
        print_status(manager)
        print("\n📊 DATABASE STATS")
        print("-" * 40)
        stats = asyncio.run(get_db_stats())
        print(f"  Sentiment raw: {stats.get('sentiment_raw', 0):,}")
        print(f"  Sentiment scores: {stats.get('sentiment_scores', 0):,}")
        print(f"  Price data: {stats.get('price_data', 0):,}")
        if "date_range" in stats:
            print(f"  Date range: {stats['date_range']['min']} to {stats['date_range']['max']}")

    elif args.command == "discover":
        print("🔍 Discovering running tasks...")
        discovered = manager.auto_discover()
        if discovered:
            for task in discovered:
                print(f"  ✅ Found {task.name} (PID: {task.pid})")
            print(f"\nDiscovered {len(discovered)} task(s)")
        else:
            print("  No new running tasks found")
        print_status(manager)

    elif args.command == "interactive":
        interactive_menu(manager)


if __name__ == "__main__":
    main()
