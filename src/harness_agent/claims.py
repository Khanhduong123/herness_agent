"""Backward-compatibility shim for harness_agent.claims."""

from __future__ import annotations

import sys

import harness_agent.research.claims as _impl
from harness_agent.research.claims import *  # noqa: F401, F403

sys.modules[__name__] = _impl
