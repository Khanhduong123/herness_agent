"""Backward-compatibility shim for harness_agent.evaluator."""

from __future__ import annotations

import sys

import harness_agent.evaluation.evaluator as _impl
from harness_agent.evaluation.evaluator import *  # noqa: F401, F403

sys.modules[__name__] = _impl
