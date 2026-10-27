"""The lesson's load script on its own: steady inserts, updates and reads, one line per second.

python -m locks_lab.interfaces.load_cli --seconds 60
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from collections.abc import Sequence

from ..infrastructure.load_runner import ThreadedLoad
from ..infrastructure.shutdown import ShutdownSignal
from .common import load_settings


def main(argv: Sequence[str] | None = None) -> int:
    """Run the load for `--seconds` (or until SIGINT or SIGTERM), then print the window summary as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=60)
    arguments = parser.parse_args(argv)
    settings = load_settings()
    if settings is None:
        return 2
    shutdown = ShutdownSignal()
    shutdown.install()
    with ThreadedLoad(settings.postgres, settings.load) as load:
        start = load.now()
        deadline = time.monotonic() + arguments.seconds
        while time.monotonic() < deadline and not shutdown.requested:
            time.sleep(1.0)
            window = load.summary(max(start, load.now() - 1.0), load.now())
            print(f"ops={window.ops:4d} errors={window.errors:3d} p99={window.p99_ms:8.1f} ms", flush=True)
        print(json.dumps(dataclasses.asdict(load.summary(start, load.now())), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
