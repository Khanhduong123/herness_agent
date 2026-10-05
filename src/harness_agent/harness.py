"""Backward-compatibility shim for harness_agent.harness."""

from __future__ import annotations

import sys

import harness_agent.core.harness as _impl
from harness_agent.core.harness import *  # noqa: F401, F403

sys.modules[__name__] = _impl
