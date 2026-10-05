"""Backward-compatibility shim for harness_agent.citecheck."""

from __future__ import annotations

import sys

import harness_agent.research.citecheck as _impl
from harness_agent.research.citecheck import *  # noqa: F401, F403

sys.modules[__name__] = _impl
