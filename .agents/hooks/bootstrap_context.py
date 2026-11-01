"""SessionStart lifecycle hook for hydrating Antigravity session context.

Reads project state and active WAL milestones from .ai/context, applies token budgeting,
and emits injectSteps conforming to the Antigravity SessionStart hook contract.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

COLD_START_MESSAGE = "Workspace initialized. Ready for initial task planning."
TRUNCATION_MARKER = "[Full plan details in .ai/plans/main/]"

MAX_LINES = 40
MAX_MILESTONES = 3
MAX_MODIFIED_FILES = 5
MAX_ESTIMATED_TOKENS = 800
MAX_LEARNED_TOKENS = 200
MAX_LEARNED_RULES = 3


def select_relevant_rules(
    rules: List[Any],
    context_keywords: List[str],
    max_rules: int = 3,
) -> List[Any]:
    """Select Top-1 anchor rule and Top-(max_rules-1) contextually matched rules.

    Selection strategy:
    1. Top-1 Anchor: Highest priority rule by calculate_priority_score().
    2. Contextual Matches: Scored by keyword/tag overlap against context_keywords
       (e.g., file extensions, goal words). Pick top matches to fill up to max_rules.
    """
    if not rules:
        return []

    # Sort all rules descending by priority score
    scored_rules = sorted(
        rules,
        key=lambda r: (
            r.calculate_priority_score()
            if hasattr(r, "calculate_priority_score")
            else (r.get("hit_count", 1) if isinstance(r, dict) else getattr(r, "hit_count", 1))
        ),
        reverse=True,
    )

    if max_rules <= 0:
        return []

    selected: List[Any] = [scored_rules[0]]
    if len(selected) >= max_rules or len(scored_rules) == 1:
        return selected

    remaining = scored_rules[1:]
    clean_keywords = {kw.lower().strip() for kw in context_keywords if kw and kw.strip()}

    def _match_score(rule: Any) -> float:
        score = 0.0
        rule_tags = rule.get("tags", []) if isinstance(rule, dict) else getattr(rule, "tags", [])
        rule_tags_clean = [str(t).lower().strip() for t in rule_tags]

        rule_trigger = str(
            rule.get("trigger_context", "")
            if isinstance(rule, dict)
            else getattr(rule, "trigger_context", "")
        ).lower()
        rule_title = str(
            rule.get("title", "") if isinstance(rule, dict) else getattr(rule, "title", "")
        ).lower()
        rule_directive = str(
            rule.get("directive", "") if isinstance(rule, dict) else getattr(rule, "directive", "")
        ).lower()

        for kw in clean_keywords:
            if not kw:
                continue
            # Exact tag match gets highest boost
            if kw in rule_tags_clean:
                score += 3.0
            # Extension or word match in trigger context
            if kw in rule_trigger:
                score += 2.0
            # Word match in title or directive
            if kw in rule_title or kw in rule_directive:
                score += 1.0

        # Tie-breaker with decayed priority score
        p_score = (
            rule.calculate_priority_score()
            if hasattr(rule, "calculate_priority_score")
            else (
                rule.get("hit_count", 1)
                if isinstance(rule, dict)
                else getattr(rule, "hit_count", 1)
            )
        )
        return score * 100.0 + float(p_score)

    remaining_sorted = sorted(remaining, key=_match_score, reverse=True)
    needed = max_rules - len(selected)
    selected.extend(remaining_sorted[:needed])
    return selected


def _load_learned_rules_pure_python(base_dir: Path) -> List[Dict[str, Any]]:
    """Pure-Python loader for .ai/learned/rules.json."""
    rules_json_path = base_dir / ".ai" / "learned" / "rules.json"
    if not rules_json_path.is_file():
        return []
    try:
        data = json.loads(rules_json_path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _format_learned_directives_section(
    rules: List[Any], max_tokens: int = MAX_LEARNED_TOKENS
) -> List[str]:
    """Format selected learned rules under '#### Learned Project Directives' with token cap."""
    if not rules:
        return []

    header = ["", "#### Learned Project Directives"]
    body_lines: List[str] = []

    for r in rules:
        title = getattr(r, "title", None) or (r.get("title") if isinstance(r, dict) else "Rule")
        directive = getattr(r, "directive", None) or (
            r.get("directive") if isinstance(r, dict) else ""
        )
        line = f"- **{title}**: {directive.strip()}"
        candidate = header + body_lines + [line]
        if estimate_tokens("\n".join(candidate)) > max_tokens:
            break
        body_lines.append(line)

    if not body_lines:
        return []

    return header + body_lines


def _configure_utf8_streams() -> None:
    """Configure stdout, stderr, and stdin to use UTF-8 encoding."""
    for stream_name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def read_stdin_with_timeout(timeout_sec: float = 0.5) -> str:
    """Read sys.stdin with a timeout to prevent hanging on open interactive pipes."""
    result = [""]

    def _reader() -> None:
        try:
            stdin_stream = getattr(sys, "stdin", None)
            if stdin_stream:
                result[0] = stdin_stream.read()
        except Exception:
            pass

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)
    return result[0].strip()


def parse_stdin_safely(timeout_sec: float = 0.5) -> Dict[str, Any]:
    """Parse JSON payload from stdin with timeout protection."""
    raw = read_stdin_with_timeout(timeout_sec)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def format_session_start_payload(markdown_text: str) -> Dict[str, Any]:
    """Format markdown text into Antigravity SessionStart output contract."""
    return {
        "injectSteps": [
            {
                "systemMessage": {
                    "systemMessage": markdown_text,
                }
            }
        ]
    }


def estimate_tokens(text: str) -> int:
    """Estimate token count using word/character heuristic (~4 chars/token or 1 token/word)."""
    if not text:
        return 0
    words = len(text.split())
    chars = len(text)
    return max(int(words * 1.3), int(chars / 4))


def apply_budget(markdown_lines: List[str]) -> str:
    """Enforce token and line constraints on compiled markdown."""
    if len(markdown_lines) > MAX_LINES:
        markdown_lines = markdown_lines[:MAX_LINES]
        if not any(TRUNCATION_MARKER in line for line in markdown_lines):
            markdown_lines.append(TRUNCATION_MARKER)

    joined = "\n".join(markdown_lines).strip()
    if estimate_tokens(joined) > MAX_ESTIMATED_TOKENS:
        while (
            markdown_lines
            and estimate_tokens("\n".join(markdown_lines + [TRUNCATION_MARKER]))
            > MAX_ESTIMATED_TOKENS
        ):
            markdown_lines.pop()
        if not any(TRUNCATION_MARKER in line for line in markdown_lines):
            markdown_lines.append(TRUNCATION_MARKER)
        joined = "\n".join(markdown_lines).strip()

    return joined


def _read_recent_wal_events(
    wal_file: Path, max_events: int = MAX_MILESTONES
) -> List[Dict[str, Any]]:
    """Pure-Python parser for reading recent WAL milestones without external dependencies."""
    if not wal_file.is_file():
        return []
    events: List[Dict[str, Any]] = []
    try:
        with open(wal_file, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return []
            for row in reader:
                if len(row) >= 5:
                    try:
                        events.append(
                            {
                                "session_id": row[0],
                                "step_index": int(row[1]) if row[1].isdigit() else 0,
                                "event_type": row[2],
                                "tool_name": row[3],
                                "status_code": (
                                    int(row[4])
                                    if row[4].isdigit()
                                    or (row[4].startswith("-") and row[4][1:].isdigit())
                                    else 0
                                ),
                                "latency_ms": (float(row[5]) if len(row) > 5 and row[5] else 0.0),
                                "error_message": row[6] if len(row) > 6 else "",
                            }
                        )
                    except Exception:
                        continue
    except Exception:
        return []
    return events[-max_events:] if events else []


def build_context_from_pure_python(base_dir: Path) -> str:
    """Fallback reader when harness_agent cannot be imported."""
    context_dir = base_dir / ".ai" / "context"
    state_file = context_dir / "state.json"
    wal_file = context_dir / "wal_actions.log"
    context_md = context_dir / "context.md"

    if not context_dir.is_dir() or (
        not state_file.is_file() and not wal_file.is_file() and not context_md.is_file()
    ):
        return COLD_START_MESSAGE

    task_id = "unknown"
    session_id = "default"
    status = "pending"
    goal = "No active goal specified."
    active_step = 0
    modified_files: List[str] = []

    if state_file.is_file():
        try:
            content = state_file.read_text(encoding="utf-8").strip()
            if content:
                data = json.loads(content)
                if isinstance(data, dict):
                    task_id = str(data.get("task_id") or task_id)
                    session_id = str(data.get("session_id") or session_id)
                    status = str(data.get("status") or status)
                    goal = str(data.get("goal") or goal)
                    active_step = int(data.get("active_step") or 0)
                    mf = data.get("modified_files")
                    if isinstance(mf, list):
                        modified_files = [str(item) for item in mf if item]
        except Exception:
            pass

    wal_events = _read_recent_wal_events(wal_file, max_events=MAX_MILESTONES)
    if wal_events:
        last_event = wal_events[-1]
        if last_event.get("event_type") in ("action_start", "tool_call", "action_in_progress"):
            status = "recovering"
            active_step = last_event.get("step_index", active_step)
        elif last_event.get("status_code", 0) != 0:
            status = "error"
            active_step = last_event.get("step_index", active_step)
        elif last_event.get("step_index", 0) > active_step:
            active_step = last_event.get("step_index", active_step)

    lines = [
        "### Active Project Context",
        f"> Task: `{task_id}` | Session: `{session_id}` | Status: `{status.upper()}`",
        f"- **Goal**: {goal.strip()}",
        f"- **Active Step**: {active_step}",
    ]

    if wal_events:
        lines.append("")
        lines.append("#### Recent Milestones")
        for ev in wal_events[-MAX_MILESTONES:]:
            st = "SUCCESS" if ev.get("status_code", 0) == 0 else f"FAILED({ev.get('status_code')})"
            tool = ev.get("tool_name") or ev.get("event_type") or "unknown"
            step_idx = ev.get("step_index", 0)
            lines.append(f"- Step {step_idx}: `{tool}` -> {st}")

    if modified_files:
        lines.append("")
        lines.append("#### Modified Files")
        for mf in modified_files[:MAX_MODIFIED_FILES]:
            lines.append(f"- `{mf}`")

    # Dynamic learned rules matching (<200 tokens budget)
    raw_rules = _load_learned_rules_pure_python(base_dir)
    if raw_rules:
        # Extract keywords from goal and file extensions from modified_files
        keywords = set(re.findall(r"[a-zA-Z0-9_-]+", goal.lower()))
        for mf in modified_files:
            suffix = Path(mf).suffix.lower()
            if suffix:
                keywords.add(suffix)
                keywords.add(suffix.lstrip("."))
        selected = select_relevant_rules(raw_rules, list(keywords), max_rules=MAX_LEARNED_RULES)
        directives_lines = _format_learned_directives_section(
            selected, max_tokens=MAX_LEARNED_TOKENS
        )
        if directives_lines:
            lines.extend(directives_lines)

    return apply_budget(lines)


def get_hydrated_context(workspace_root: Optional[Path] = None) -> str:
    """Build hydrated context markdown via StateCoordinator or pure-Python fallback."""
    root = (workspace_root or Path.cwd()).resolve()

    try:
        from harness_agent.core.state import StateCoordinator

        context_dir = root / ".ai" / "context"
        state_file = context_dir / "state.json"
        wal_file = context_dir / "wal_actions.log"

        if not context_dir.is_dir() and not state_file.is_file() and not wal_file.is_file():
            return COLD_START_MESSAGE

        coordinator = StateCoordinator(
            session_path=state_file,
            wal_path=wal_file,
            context_md_path=context_dir / "context.md",
        )
        recon = coordinator.reconcile_on_startup()
        state = recon.reconciled_state

        if state is None:
            if not wal_file.is_file() and not state_file.is_file():
                return COLD_START_MESSAGE
            return build_context_from_pure_python(root)

        status = state.status
        if recon.recovery_action == "interrupted_action_detected":
            status = "recovering"
        elif recon.recovery_action == "error_detected":
            status = "error"

        meta_line = (
            f"> Task: `{state.task_id}` | Session: `{state.session_id}` "
            f"| Status: `{status.upper()}`"
        )
        lines = [
            "### Active Project Context",
            meta_line,
            f"- **Goal**: {state.goal.strip()}",
            f"- **Active Step**: {state.active_step}",
        ]

        all_events = coordinator.wal.read_all_events() if wal_file.is_file() else []
        if all_events:
            lines.append("")
            lines.append("#### Recent Milestones")
            for ev in all_events[-MAX_MILESTONES:]:
                st = "SUCCESS" if ev.status_code == 0 else f"FAILED({ev.status_code})"
                tool = ev.tool_name or ev.event_type or "unknown"
                lines.append(f"- Step {ev.step_index}: `{tool}` -> {st}")

        if state.modified_files:
            lines.append("")
            lines.append("#### Modified Files")
            for mf in state.modified_files[:MAX_MODIFIED_FILES]:
                lines.append(f"- `{mf}`")

        # Dynamic learned rules matching (<200 tokens budget)
        try:
            from harness_agent.learning.reflector import KnowledgeReflector

            reflector = KnowledgeReflector(output_dir=root / ".ai" / "learned")
            rules = reflector.load_rules()
        except Exception:
            raw_rules = _load_learned_rules_pure_python(root)
            rules = raw_rules

        if rules:
            keywords = set(re.findall(r"[a-zA-Z0-9_-]+", state.goal.lower()))
            for mf in state.modified_files:
                suffix = Path(mf).suffix.lower()
                if suffix:
                    keywords.add(suffix)
                    keywords.add(suffix.lstrip("."))
            selected = select_relevant_rules(rules, list(keywords), max_rules=MAX_LEARNED_RULES)
            directives_lines = _format_learned_directives_section(
                selected, max_tokens=MAX_LEARNED_TOKENS
            )
            if directives_lines:
                lines.extend(directives_lines)

        return apply_budget(lines)

    except Exception:
        return build_context_from_pure_python(root)


def build_bootstrap_payload(workspace_root: Optional[Path] = None) -> Dict[str, Any]:
    """Build SessionStart payload for given workspace root."""
    root = Path(workspace_root).resolve() if workspace_root is not None else None
    context_md = get_hydrated_context(root)
    return format_session_start_payload(context_md)


def main() -> None:
    """Entry point for SessionStart hook."""
    _configure_utf8_streams()

    input_data = parse_stdin_safely(timeout_sec=0.2)

    workspace_root: Optional[Path] = None
    workspace_paths = input_data.get("workspacePaths")
    if isinstance(workspace_paths, list) and workspace_paths:
        first_path = workspace_paths[0]
        if isinstance(first_path, str) and first_path.strip():
            p = Path(first_path.strip())
            if p.is_dir():
                workspace_root = p

    try:
        context_md = get_hydrated_context(workspace_root)
    except Exception:
        context_md = COLD_START_MESSAGE

    payload = format_session_start_payload(context_md)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
