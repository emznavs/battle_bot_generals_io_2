import argparse
import asyncio
import os
import pathlib

from .client import main as run_bot


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
    try:
        asyncio.run(run_bot(args.games))
    except KeyboardInterrupt:
        pass
