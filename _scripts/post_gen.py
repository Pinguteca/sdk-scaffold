#!/usr/bin/env python3
"""Flatten overlay directories into the destination root.

The template source organises files under per-overlay subdirectories
(`_common`, `_go`, `_dotnet`, future `_dart`, `_kotlin`, ...) so that
the source tree stays readable as more language overlays are added.
Consumers expect a flat repo layout, so this script runs as a copier
`_tasks` step after rendering: it moves every file under each overlay
to the destination root (preserving sub-paths inside the overlay) and
removes the now-empty overlay directories.

Overlays not selected by the user are excluded by `copier.yml`'s
`_exclude` patterns, so they never appear in the destination tree.
This script just sees the overlays that were rendered and flattens
them unconditionally.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

OVERLAY_PREFIX = "_"


def main() -> int:
    dest = Path.cwd()
    for overlay in sorted(dest.iterdir()):
        if not overlay.is_dir():
            continue
        if not overlay.name.startswith(OVERLAY_PREFIX):
            continue
        for src in sorted(overlay.rglob("*")):
            if src.is_dir():
                continue
            rel = src.relative_to(overlay)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(target))
        shutil.rmtree(overlay)
    return 0


if __name__ == "__main__":
    sys.exit(main())
