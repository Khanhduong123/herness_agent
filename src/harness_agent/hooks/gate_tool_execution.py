"""PreToolUse enforcement hook for Antigravity.

Enforces RULE 0 (Zero-Tolerance Code-Writing Lock for Orchestrator)
and tool gating constraints by intercepting tool calls before execution.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

RULE_0_TOOL_DENIAL_REASON = (
    "RULE 0 HARD-GATE: Hidden background subagents are strictly prohibited. "
    "Dispatch workers interactively in Herdr panes."
)

RULE_0_CODE_MUTATION_REASON = (
    "RULE 0 HARD-GATE: Central Orchestrator is strictly forbidden from "
    "directly writing or modifying application source code (src/, tests/). "
    "Launch a Coder Agent via Herdr in an isolated worktree."
)

CONTRACT_FREEZE_PATH = ".ai/context/contract_freeze.json"

FORBIDDEN_SUBAGENT_TOOLS = frozenset({"invoke_subagent", "define_subagent"})

MUTATION_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "write_to_file",
        "replace_file_content",
        "apply_patch",
        "multi_replace_file_content",
    }
)

ALLOWED_PATH_PREFIXES = (
    ".ai/plans/",
    ".ai/status/",
    ".ai/context/",
    ".runs/",
    ".agents/skills/",
)

FORBIDDEN_PATH_PREFIXES = (
    "src/",
    "tests/",
    "examples/",
    "scripts/",
)

FORBIDDEN_ROOT_FILES = frozenset(
    {
        "agents.md",
        "setup.py",
        "pyproject.toml",
    }
)


class PreToolUseDecision(BaseModel):
    """Output structure conforming to the PreToolUse hook contract."""

    decision: str = Field(
        ...,
        description="Gate decision: 'allow' or 'deny'.",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Explanation when the tool execution is denied.",
    )


def _configure_utf8_streams() -> None:
    """Configure sys.stdout, sys.stderr, and sys.stdin to use utf-8 encoding."""
    for stream_name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def extract_target_path(args: Dict[str, Any]) -> Optional[str]:
    """Extract file path parameter from various tool call argument aliases."""
    for key in ("Path", "path", "file_path", "target_file", "filePath", "targetFile"):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def is_path_forbidden(
    target_path_str: str,
    workspace_paths: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """Evaluate whether target file path mutates protected application files.

    Returns (is_forbidden, reason).
    """
    normalized = target_path_str.replace("\\", "/").strip()

    # Check if target is inside an artifact directory
    if ".gemini/antigravity-cli/brain" in normalized or "/brain/" in normalized:
        return False, ""

    # Normalize relative to workspaces if provided
    candidate_rel_paths: List[str] = []
    if workspace_paths:
        for ws in workspace_paths:
            ws_norm = ws.replace("\\", "/").rstrip("/")
            if normalized.lower().startswith(ws_norm.lower() + "/"):
                candidate_rel_paths.append(normalized[len(ws_norm) + 1 :])

    if not candidate_rel_paths:
        target_obj = Path(target_path_str)
        if target_obj.is_absolute():
            # If absolute but matches cwd
            try:
                cwd = Path.cwd()
                rel = target_obj.relative_to(cwd)
                candidate_rel_paths.append(str(rel).replace("\\", "/"))
            except ValueError:
                candidate_rel_paths.append(normalized)
        else:
            candidate_rel_paths.append(normalized)

    for rel_path in candidate_rel_paths:
        rel_clean = rel_path
        while rel_clean.startswith("./") or rel_clean.startswith("/"):
            if rel_clean.startswith("./"):
                rel_clean = rel_clean[2:]
            elif rel_clean.startswith("/"):
                rel_clean = rel_clean[1:]
        rel_lower = rel_clean.lower()

        # Check explicitly allowed prefixes
        if any(rel_lower.startswith(prefix.lower()) for prefix in ALLOWED_PATH_PREFIXES):
            return False, ""

        # Check forbidden root files
        if "/" not in rel_clean and rel_lower in FORBIDDEN_ROOT_FILES:
            return True, RULE_0_CODE_MUTATION_REASON

        # Guard legacy harness architectural blueprints
        if rel_lower.startswith(".harness/") and "architecture" in rel_lower:
            return (
                True,
                "RULE 0 HARD-GATE: Orchestrator architecture blueprint must be stored "
                "in .ai/context/ (e.g. .ai/context/architecture.md), not .harness/.",
            )

        # Check forbidden prefixes
        if any(rel_lower.startswith(prefix.lower()) for prefix in FORBIDDEN_PATH_PREFIXES):
            return True, RULE_0_CODE_MUTATION_REASON

    return False, ""


def get_frozen_files(workspace_paths: Optional[List[str]] = None) -> List[str]:
    """Read list of frozen contract files from contract freeze manifest if present."""
    candidate_paths: List[Path] = [Path(CONTRACT_FREEZE_PATH)]

    cwd = Path.cwd()
    candidate_paths.append(cwd / CONTRACT_FREEZE_PATH)

    # If inside worktree or child directory, check parent directories up to git root
    curr = cwd
    for _ in range(5):
        candidate_paths.append(curr / CONTRACT_FREEZE_PATH)
        if (curr / ".git").exists():
            break
        parent = curr.parent
        if parent == curr:
            break
        curr = parent

    if workspace_paths:
        for ws in workspace_paths:
            ws_path = Path(ws)
            candidate_paths.append(ws_path / CONTRACT_FREEZE_PATH)

    for p in candidate_paths:
        try:
            if p.is_file():
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                files = data.get("contract_files") or data.get("frozen_files") or []
                if isinstance(files, list):
                    return [str(item).replace("\\", "/").strip() for item in files if item]
        except Exception:
            continue

    return []


def is_frozen_contract_violation(
    target_path_str: str,
    frozen_files: List[str],
    workspace_paths: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """Check if target file path matches any frozen contract file."""
    if not frozen_files:
        return False, ""

    norm_target = target_path_str.replace("\\", "/").strip()
    norm_target_clean = norm_target
    while norm_target_clean.startswith("./") or norm_target_clean.startswith("/"):
        if norm_target_clean.startswith("./"):
            norm_target_clean = norm_target_clean[2:]
        elif norm_target_clean.startswith("/"):
            norm_target_clean = norm_target_clean[1:]

    # Also resolve target path relative to workspaces or cwd
    candidate_target_rels = [norm_target_clean]
    if workspace_paths:
        for ws in workspace_paths:
            ws_norm = ws.replace("\\", "/").rstrip("/")
            if norm_target.lower().startswith(ws_norm.lower() + "/"):
                candidate_target_rels.append(norm_target[len(ws_norm) + 1 :])

    try:
        target_obj = Path(target_path_str)
        if target_obj.is_absolute():
            try:
                rel = str(target_obj.relative_to(Path.cwd())).replace("\\", "/")
                candidate_target_rels.append(rel)
            except ValueError:
                pass
    except Exception:
        pass

    for frozen in frozen_files:
        norm_frozen = frozen.replace("\\", "/").strip()
        while norm_frozen.startswith("./") or norm_frozen.startswith("/"):
            if norm_frozen.startswith("./"):
                norm_frozen = norm_frozen[2:]
            elif norm_frozen.startswith("/"):
                norm_frozen = norm_frozen[1:]

        for cand in candidate_target_rels:
            cand_clean = cand
            while cand_clean.startswith("./") or cand_clean.startswith("/"):
                if cand_clean.startswith("./"):
                    cand_clean = cand_clean[2:]
                elif cand_clean.startswith("/"):
                    cand_clean = cand_clean[1:]

            if cand_clean.lower() == norm_frozen.lower() or cand_clean.lower().endswith(
                "/" + norm_frozen.lower()
            ):
                reason = (
                    f"FROZEN_CONTRACT_VIOLATION: File '{target_path_str}' is a frozen interface "
                    f"contract. Modifying shared contracts during parallel worker execution "
                    f"is strictly prohibited."
                )
                return True, reason

    return False, ""


def is_in_worker_worktree(workspace_paths: Optional[List[str]] = None) -> bool:
    """Check if the execution environment is inside an isolated agent worktree."""
    cwd_str = str(Path.cwd()).replace("\\", "/").lower()
    if "/.worktrees/agent/" in cwd_str or ".worktrees/agent/" in cwd_str:
        return True
    if workspace_paths:
        for ws in workspace_paths:
            ws_norm = ws.replace("\\", "/").lower()
            if "/.worktrees/agent/" in ws_norm or ".worktrees/agent/" in ws_norm:
                return True
    return False


def evaluate_tool_call(
    tool_name: str,
    tool_args: Dict[str, Any],
    workspace_paths: Optional[List[str]] = None,
) -> PreToolUseDecision:
    """Evaluate a tool execution request against Rule 0, contract freeze, and gating rules."""
    # 1. Deny forbidden background subagent tools
    if tool_name in FORBIDDEN_SUBAGENT_TOOLS:
        return PreToolUseDecision(
            decision="deny",
            reason=RULE_0_TOOL_DENIAL_REASON,
        )

    # 2. Check contract freeze violation for mutation tools (orchestrator and workers)
    if tool_name in MUTATION_TOOLS:
        target_path = extract_target_path(tool_args)
        if target_path:
            frozen_files = get_frozen_files(workspace_paths)
            violation, freeze_reason = is_frozen_contract_violation(
                target_path, frozen_files, workspace_paths
            )
            if violation:
                return PreToolUseDecision(
                    decision="deny",
                    reason=freeze_reason,
                )

    # 3. Allow mutation tools if running inside isolated worktree (not violating freeze)
    if tool_name in MUTATION_TOOLS and is_in_worker_worktree(workspace_paths):
        return PreToolUseDecision(decision="allow")

    # 4. Check Orchestrator code mutation tools (Rule 0)
    if tool_name in MUTATION_TOOLS:
        target_path = extract_target_path(tool_args)
        if target_path:
            forbidden, reason = is_path_forbidden(target_path, workspace_paths)
            if forbidden:
                return PreToolUseDecision(
                    decision="deny",
                    reason=reason,
                )

    return PreToolUseDecision(decision="allow")


def process_hook_payload(payload: Dict[str, Any]) -> PreToolUseDecision:
    """Parse incoming hook payload and evaluate tool use decision."""
    tool_call = payload.get("toolCall", {})
    if not isinstance(tool_call, dict):
        return PreToolUseDecision(decision="allow")

    tool_name = tool_call.get("name", "")
    tool_args = tool_call.get("args", {})
    if not isinstance(tool_args, dict):
        tool_args = {}

    workspace_paths = payload.get("workspacePaths", [])
    if not isinstance(workspace_paths, list):
        workspace_paths = []

    return evaluate_tool_call(
        tool_name=tool_name,
        tool_args=tool_args,
        workspace_paths=[str(p) for p in workspace_paths],
    )


def read_stdin_with_timeout(timeout_sec: float = 0.5) -> str:
    """Read sys.stdin with a timeout to prevent hanging on open interactive pipes."""
    import threading

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


def main() -> None:
    """Entry point for PreToolUse enforcement hook."""
    _configure_utf8_streams()
    payload: Dict[str, Any] = {}
    try:
        raw_input = read_stdin_with_timeout(0.5)
        if raw_input:
            payload = json.loads(raw_input)
    except Exception:
        payload = {}

    decision = process_hook_payload(payload)
    print(decision.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
