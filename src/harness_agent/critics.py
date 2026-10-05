"""Backward-compatibility shim for harness_agent.critics."""

from __future__ import annotations

import sys

import harness_agent.evaluation.critics as _impl
from harness_agent.evaluation.critics import *  # noqa: F401, F403

sys.modules[__name__] = _impl
