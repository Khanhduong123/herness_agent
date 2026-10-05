"""Backward-compatibility shim for harness_agent.runner."""

from __future__ import annotations

import sys

import harness_agent.core.runner as _impl
from harness_agent.core.runner import *  # noqa: F401, F403

sys.modules[__name__] = _impl
