"""Backward-compatibility shim for harness_agent.patch."""

from __future__ import annotations

import sys

import harness_agent.evaluation.patch as _impl
from harness_agent.evaluation.patch import *  # noqa: F401, F403

sys.modules[__name__] = _impl
