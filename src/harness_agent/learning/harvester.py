"""Telemetry harvester for self-improving cognitive loop.

Consolidates session execution events, critic issues, and error logs into normalized
IncidentTrajectories using a 3-tier credit optimization gate (Heuristic Gate, Deterministic
Python Regex Matcher, and Deduplication Gate).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from harness_agent.core.state import WALEvent
from harness_agent.learning.models import IncidentTrajectory, IncidentType, LearnedRule

# Deterministic patterns matching known tool errors (0 tokens)
KNOWN_TOOL_PATTERNS = [
    {
        "pattern": re.compile(r"\\ufeff|utf-8-sig|BOM", re.IGNORECASE),
        "failing_tool": "read_file",
        "recovery_tool": "read_file",
        "root_cause": "UTF-8 BOM encoding issue in source file reading",
        "resolution": "Use encoding='utf-8-sig' or strip leading BOM character byte",
        "incident_type": IncidentType.TOOL_ERROR_RECOVERY,
    },
    {
        "pattern": re.compile(r"unknown flag|unrecognized argument|no such option", re.IGNORECASE),
        "failing_tool": "run_command",
        "recovery_tool": "run_command",
        "root_cause": "Invoked command or CLI tool with unknown or unsupported argument",
        "resolution": "Check CLI documentation / --help and remove unsupported options",
        "incident_type": IncidentType.TOOL_ERROR_RECOVERY,
    },
    {
        "pattern": re.compile(
            r"is already checked out at|already locked|index\.lock|worktree.*exists",
            re.IGNORECASE,
        ),
        "failing_tool": "git_worktree",
        "recovery_tool": "git_worktree",
        "root_cause": "Git worktree lock or duplicate branch worktree conflict",
        "resolution": "Prune or unlock worktree or use isolated unique worktree path",
        "incident_type": IncidentType.TOOL_ERROR_RECOVERY,
    },
    {
        "pattern": re.compile(r"ModuleNotFoundError|No module named", re.IGNORECASE),
        "failing_tool": "run_command",
        "recovery_tool": "run_command",
        "root_cause": "Missing dependency import in runtime python environment",
        "resolution": "Verify conda/virtual environment or install missing requirement",
        "incident_type": IncidentType.TOOL_ERROR_RECOVERY,
    },
    {
        "pattern": re.compile(r"FileNotFoundError|No such file or directory", re.IGNORECASE),
        "failing_tool": "run_command",
        "recovery_tool": "write_file",
        "root_cause": "Attempted to access non-existent file or directory path",
        "resolution": "Ensure directory exists or create parent path before accessing file",
        "incident_type": IncidentType.TOOL_ERROR_RECOVERY,
    },
]


class TelemetryHarvester:
    """Harvester that scans session telemetry and produces incident trajectories."""

    def __init__(self, existing_rules: Optional[List[LearnedRule]] = None) -> None:
        self.existing_rules = existing_rules or []
        self._existing_rule_triggers: Set[str] = {
            r.trigger_context.strip().lower() for r in self.existing_rules
        }

    def harvest(
        self,
        session_id: str,
        wal_events: Optional[List[WALEvent]] = None,
        critic_issues: Optional[List[Dict[str, Any]]] = None,
    ) -> List[IncidentTrajectory]:
        """Harvest incident trajectories using the multi-tier cost conservation gate.

        Tier 1: Heuristic Gate (0 tokens if no errors / issues).
        Tier 2: Deterministic Python Regex Matcher (0 tokens if matched).
        Tier 3: Deduplication check against existing rules.
        """
        wal_events = wal_events or []
        critic_issues = critic_issues or []

        # Tier 1 (Heuristic Gate)
        # Check if wal_events contains any status_code != 0 or if critic_issues is non-empty.
        has_wal_errors = any(getattr(e, "status_code", 0) != 0 for e in wal_events)
        if not has_wal_errors and not critic_issues:
            return []

        trajectories: List[IncidentTrajectory] = []

        # Process WAL error events
        error_events = [e for e in wal_events if getattr(e, "status_code", 0) != 0]
        for event in error_events:
            error_msg = getattr(event, "error_message", "") or ""
            tool_name = getattr(event, "tool_name", "") or ""

            # Check if this error is already covered by existing rules (Tier 3)
            if self._is_deduplicated(error_msg):
                continue

            # Tier 2: Deterministic Python Regex Matcher (0 Tokens)
            matched_traj = self._match_deterministic_pattern(
                session_id=session_id,
                error_msg=error_msg,
                failing_tool=tool_name,
                step_index=getattr(event, "step_index", 0),
            )
            if matched_traj:
                trajectories.append(matched_traj)
            else:
                # Fallback to non-deterministic trajectory requiring micro-reflection
                trajectories.append(
                    IncidentTrajectory(
                        session_id=session_id,
                        incident_type=IncidentType.TOOL_ERROR_RECOVERY,
                        trigger_error=error_msg,
                        failing_tool=tool_name,
                        recovery_tool="",
                        steps_taken=[
                            {
                                "step_index": getattr(event, "step_index", 0),
                                "event_type": getattr(event, "event_type", ""),
                                "tool_name": tool_name,
                                "status_code": getattr(event, "status_code", 1),
                                "error_message": error_msg,
                            }
                        ],
                        root_cause_hypothesis="",
                        resolution="",
                        is_deterministic=False,
                    )
                )

        # Process Critic Rejection Issues
        for issue in critic_issues:
            critic_name = issue.get("critic_name", "critic")
            issue_desc = issue.get("description", "") or issue.get("error", "") or str(issue)

            if self._is_deduplicated(issue_desc):
                continue

            trajectories.append(
                IncidentTrajectory(
                    session_id=session_id,
                    incident_type=IncidentType.CRITIC_REJECTION_FIX,
                    trigger_error=issue_desc,
                    failing_tool=critic_name,
                    recovery_tool="",
                    steps_taken=[{"issue": issue}],
                    root_cause_hypothesis=issue.get("reason", ""),
                    resolution=issue.get("alternative", ""),
                    is_deterministic=False,
                )
            )

        return trajectories

    def _match_deterministic_pattern(
        self, session_id: str, error_msg: str, failing_tool: str, step_index: int
    ) -> Optional[IncidentTrajectory]:
        """Match against known deterministic tool patterns."""
        for entry in KNOWN_TOOL_PATTERNS:
            pattern: re.Pattern = entry["pattern"]
            if pattern.search(error_msg):
                return IncidentTrajectory(
                    session_id=session_id,
                    incident_type=entry["incident_type"],
                    trigger_error=error_msg,
                    failing_tool=failing_tool or entry["failing_tool"],
                    recovery_tool=entry["recovery_tool"],
                    steps_taken=[
                        {
                            "step_index": step_index,
                            "error": error_msg,
                            "failing_tool": failing_tool,
                        }
                    ],
                    root_cause_hypothesis=entry["root_cause"],
                    resolution=entry["resolution"],
                    is_deterministic=True,
                )
        return None

    def _is_deduplicated(self, text: str) -> bool:
        """Check if error/issue matches an existing rule's trigger context."""
        cleaned = text.strip().lower()
        if not cleaned:
            return False
        for trigger in self._existing_rule_triggers:
            if trigger in cleaned or cleaned in trigger:
                return True
        return False
