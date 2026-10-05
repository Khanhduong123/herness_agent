"""Backward-compatibility shim for harness_agent.models."""

from __future__ import annotations

import sys

import harness_agent.core.models as _impl
from harness_agent.core.models import *  # noqa: F401, F403

sys.modules[__name__] = _impl
