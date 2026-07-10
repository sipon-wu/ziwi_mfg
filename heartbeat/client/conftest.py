"""Pytest configuration: make the ``client`` package importable in tests.

Tests import the SDK as ``client.heartbeat_client`` etc. We add this package's
parent directory (``code/heartbeat/``) to ``sys.path`` so ``import client``
resolves regardless of the current working directory.
"""

import os
import sys

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)
