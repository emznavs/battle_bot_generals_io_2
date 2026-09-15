import argparse
import asyncio
import os
import pathlib
import subprocess

from . import config
from .client import log
from .client import main as run_bot


def version_banner():
    """Stamp the running code into the log: edits only apply after a restart."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha, dirty = "", ""
    stamp = sha or "unknown"
    if dirty:
        stamp += "+local-edits"
    log(f"code {stamp}")
    log(
        f"tuning queue={config.QUEUE_TARGET} run_min={config.GENERAL_RUN_MIN} "
        f"garrison={config.GARRISON_SHARE}/cap{config.GARRISON_CAP_OF_MINE} "
        f"press@{config.PRESS_MIN_TICK}"
    )


def load_env(path=".env"):
    """Read the gitignored .env so `python -m bot.main` works without sourcing."""
    env_file = pathlib.Path(path)
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export ") :]
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generals Arena bot")
    parser.add_argument("--games", type=int, default=0, help="stop after N games")
    args = parser.parse_args()
    load_env()
    version_banner()
    try:
        asyncio.run(run_bot(args.games))
    except KeyboardInterrupt:
        pass
