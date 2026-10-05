"""Backward-compatibility shim for harness_agent.security."""

from __future__ import annotations

import sys

import harness_agent.core.security as _impl
from harness_agent.core.security import *  # noqa: F401, F403

sys.modules[__name__] = _impl
