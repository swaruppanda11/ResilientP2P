"""Pytest bootstrap: make `common`, `coordinator`, `peer`, `origin` importable.

Tests target the p2p-coordinator stack (coordinator + coord-peer + origin
images, which share `common.auth` with the DHT peer stack). The DHT peer's
auth module is a byte-for-byte copy of the coordinator's, so coverage here
transfers to that image.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COORD_ROOT = REPO_ROOT / "p2p-coordinator"

# Prepend so the stack's `common`/`coordinator`/`peer` win over any
# same-named packages elsewhere on PYTHONPATH.
sys.path.insert(0, str(COORD_ROOT))

# Reset common env vars so module-load-time settings are deterministic.
for _var in ("AUTH_MODE", "AUTH_TOKEN", "PEER_GROUP"):
    os.environ.pop(_var, None)
