"""Backward-compatibility shim for harness_agent.researcher."""

from __future__ import annotations

import sys

import harness_agent.research.researcher as _impl
from harness_agent.research.researcher import *  # noqa: F401, F403

sys.modules[__name__] = _impl
