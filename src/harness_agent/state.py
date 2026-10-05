"""Backward-compatibility shim for harness_agent.state."""

from __future__ import annotations

import sys

import harness_agent.core.state as _impl
from harness_agent.core.state import *  # noqa: F401, F403

sys.modules[__name__] = _impl
