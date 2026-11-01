"""Learning and self-improving cognitive loop models."""

from __future__ import annotations

import math
import time
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class IncidentType(str, Enum):
    """Categorization of failure and success incidents observed during agent execution."""

    TOOL_ERROR_RECOVERY = "tool_error_recovery"
    CRITIC_REJECTION_FIX = "critic_rejection_fix"
    REPEATED_ACTION_LOOP = "repeated_action_loop"
    GOLDEN_WORKFLOW = "golden_workflow"


class IncidentTrajectory(BaseModel):
    """Normalized incident trajectory extracted from session telemetry."""

    session_id: str
    incident_type: IncidentType
    trigger_error: str = ""
    failing_tool: str = ""
    recovery_tool: str = ""
    steps_taken: List[Dict[str, Any]] = Field(default_factory=list)
    root_cause_hypothesis: str = ""
    resolution: str = ""
    is_deterministic: bool = False  # Pure python matches (0 tokens)


class LearnedRule(BaseModel):
    """Learned cognitive rule persisted to semantic memory."""

    id: str
    title: str
    trigger_context: str
    directive: str
    tags: List[str] = Field(default_factory=list)
    hit_count: int = 1
    created_at: float = Field(default_factory=time.time)
    last_hit_at: float = Field(default_factory=time.time)
    source_sessions: List[str] = Field(default_factory=list)

    def calculate_priority_score(
        self, half_life_days: float = 14.0, now: Optional[float] = None
    ) -> float:
        """Decayed score: hit_count * exp(-decay_lambda * delta_days)."""
        current_time = now if now is not None else time.time()
        delta_days = max(0.0, (current_time - self.last_hit_at) / 86400.0)
        decay_lambda = math.log(2) / max(1.0, half_life_days)
        return self.hit_count * math.exp(-decay_lambda * delta_days)

    def is_in_grace_period(
        self, grace_period_days: float = 7.0, now: Optional[float] = None
    ) -> bool:
        """New rules within grace period (7 days) are immune from LFU eviction."""
        current_time = now if now is not None else time.time()
        return (current_time - self.created_at) < (grace_period_days * 86400.0)


class AntiPattern(BaseModel):
    """Known harmful pattern or anti-pattern to avoid."""

    id: str
    pattern_name: str
    forbidden_behavior: str
    reason: str
    alternative: str
    tags: List[str] = Field(default_factory=list)
    hit_count: int = 1
    created_at: float = Field(default_factory=time.time)
    last_hit_at: float = Field(default_factory=time.time)

    def calculate_priority_score(
        self, half_life_days: float = 14.0, now: Optional[float] = None
    ) -> float:
        """Decayed score: hit_count * exp(-decay_lambda * delta_days)."""
        current_time = now if now is not None else time.time()
        delta_days = max(0.0, (current_time - self.last_hit_at) / 86400.0)
        decay_lambda = math.log(2) / max(1.0, half_life_days)
        return self.hit_count * math.exp(-decay_lambda * delta_days)

    def is_in_grace_period(
        self, grace_period_days: float = 7.0, now: Optional[float] = None
    ) -> bool:
        """New anti-patterns within grace period (7 days) are immune from LFU eviction."""
        current_time = now if now is not None else time.time()
        return (current_time - self.created_at) < (grace_period_days * 86400.0)
