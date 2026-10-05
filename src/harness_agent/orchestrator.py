"""Backward-compatibility shim for harness_agent.orchestrator."""

from __future__ import annotations

import sys

import harness_agent.core.orchestrator as _impl
from harness_agent.core.orchestrator import *  # noqa: F401, F403

sys.modules[__name__] = _impl
