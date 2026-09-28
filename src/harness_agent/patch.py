"""Patch-only mechanism and tool-locking implementation.

Enforces 'Patch, never regenerate' rule to prevent full-file hallucination rewrites.
"""

from __future__ import annotations

import difflib
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class ToolLockViolationError(Exception):
    """Raised when an agent violates tool-locking policies."""

    pass


class DisallowedFullFileOverwriteError(ToolLockViolationError):
    """Raised when an agent attempts to overwrite or regenerate an entire file."""

    pass


class PatchHunk(BaseModel):
    """Represents a parsed diff hunk."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: List[str] = Field(default_factory=list)


class PatchResult(BaseModel):
    """Result of applying diff patches or chunk replacements."""

    success: bool
    target_file: str
    hunks_applied: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    diff_patch: str = ""
    message: str = ""


_HUNK_HEADER_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")


def parse_unified_diff(diff_text: str) -> List[PatchHunk]:
    """Parse unified diff text into structured PatchHunk objects."""
    hunks: List[PatchHunk] = []
    lines = diff_text.splitlines()
    current_hunk: Optional[PatchHunk] = None

    for line in lines:
        match = _HUNK_HEADER_RE.match(line)
        if match:
            if current_hunk:
                hunks.append(current_hunk)
            old_start = int(match.group(1))
            old_lines = int(match.group(2)) if match.group(2) is not None else 1
            new_start = int(match.group(3))
            new_lines = int(match.group(4)) if match.group(4) is not None else 1
            current_hunk = PatchHunk(
                old_start=old_start,
                old_lines=old_lines,
                new_start=new_start,
                new_lines=new_lines,
                lines=[],
            )
        elif current_hunk is not None:
            if line.startswith(("+", "-", " ", "\\")):
                current_hunk.lines.append(line)
            elif not line.startswith(("---", "+++", "diff ", "index ")):
                # If leading space was stripped, treat as context line
                current_hunk.lines.append(" " + line)

    if current_hunk:
        hunks.append(current_hunk)

    return hunks


def apply_unified_diff(original_text: str, diff_text: str) -> Tuple[str, int, int, int]:
    """Apply unified diff text to original_text.

    Returns (new_text, hunks_applied, lines_added, lines_removed).
    """
    hunks = parse_unified_diff(diff_text)
    if not hunks:
        raise ValueError("No valid diff hunks found in patch content")

    orig_lines = original_text.splitlines(keepends=True)
    new_lines: List[str] = []
    orig_idx = 0
    lines_added = 0
    lines_removed = 0
    hunks_applied = 0

    for hunk in hunks:
        target_idx = max(0, hunk.old_start - 1)

        # Copy unchanged lines before hunk
        while orig_idx < target_idx and orig_idx < len(orig_lines):
            new_lines.append(orig_lines[orig_idx])
            orig_idx += 1

        for hline in hunk.lines:
            if not hline:
                continue
            marker = hline[0]
            content = hline[1:]
            if not content.endswith("\n"):
                content += "\n"

            if marker == " ":
                # Context line
                if orig_idx < len(orig_lines):
                    new_lines.append(orig_lines[orig_idx])
                    orig_idx += 1
                else:
                    new_lines.append(content)
            elif marker == "-":
                # Deletion line
                if orig_idx < len(orig_lines):
                    orig_idx += 1
                lines_removed += 1
            elif marker == "+":
                # Addition line
                new_lines.append(content)
                lines_added += 1

        hunks_applied += 1

    # Copy remaining unchanged lines after last hunk
    while orig_idx < len(orig_lines):
        new_lines.append(orig_lines[orig_idx])
        orig_idx += 1

    return "".join(new_lines), hunks_applied, lines_added, lines_removed


def apply_patch(
    target_file: str,
    patch_content: str,
    workspace_dir: Optional[str] = None,
    dry_run: bool = False,
    enforce_tool_lock: bool = True,
) -> PatchResult:
    """Apply a unified diff patch to a target file, strictly enforcing tool-locking."""
    file_path = (
        os.path.join(workspace_dir, target_file)
        if workspace_dir and not os.path.isabs(target_file)
        else os.path.abspath(target_file)
    )

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Target file not found for patch: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        original_text = f.read()

    orig_lines = original_text.splitlines()

    # Enforce tool-locking: verify the patch is not regenerating the entire file
    hunks = parse_unified_diff(patch_content)
    if enforce_tool_lock and len(orig_lines) > 5 and hunks:
        total_orig_lines = len(orig_lines)
        for hunk in hunks:
            # If a single hunk tries to delete the entire file or rewrite > 90% of lines
            if hunk.old_lines >= total_orig_lines and hunk.old_start <= 1:
                raise DisallowedFullFileOverwriteError(
                    f"Tool-locking violation: Patch attempts to rewrite entire file "
                    f"({hunk.old_lines}/{total_orig_lines} lines). Only minimal diff hunks allowed."
                )

    new_text, hunks_applied, lines_added, lines_removed = apply_unified_diff(
        original_text, patch_content
    )

    diff = "".join(
        difflib.unified_diff(
            original_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{target_file}",
            tofile=f"b/{target_file}",
        )
    )

    if not dry_run:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_text)

    return PatchResult(
        success=True,
        target_file=target_file,
        hunks_applied=hunks_applied,
        lines_added=lines_added,
        lines_removed=lines_removed,
        diff_patch=diff,
        message=f"Applied {hunks_applied} hunk(s) (+{lines_added}/-{lines_removed} lines)",
    )


def multi_replace_file_content(
    target_file: str,
    replacements: List[Dict[str, Any]],
    workspace_dir: Optional[str] = None,
    dry_run: bool = False,
    enforce_tool_lock: bool = True,
) -> PatchResult:
    """Apply one or more targeted search-and-replace hunks to a file."""
    file_path = (
        os.path.join(workspace_dir, target_file)
        if workspace_dir and not os.path.isabs(target_file)
        else os.path.abspath(target_file)
    )

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Target file not found for multi_replace: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        original_text = f.read()

    orig_lines = original_text.splitlines()
    total_lines = len(orig_lines)
    modified_text = original_text
    hunks_applied = 0
    lines_added = 0
    lines_removed = 0

    for rep in replacements:
        target = rep.get("target_content", "")
        replacement = rep.get("replacement_content", "")

        if not target:
            raise ValueError("Replacement must contain non-empty 'target_content'")

        if enforce_tool_lock and total_lines > 5:
            # Check if replacing whole file or almost whole file
            if target.strip() == original_text.strip():
                raise DisallowedFullFileOverwriteError(
                    "Tool-locking violation: Replacing entire file content is disallowed. "
                    "Use atomic replacement hunks targeting only modified lines."
                )

        if target not in modified_text:
            raise ValueError(f"Target content not found in {target_file}: {target!r}")

        allow_multiple = rep.get("allow_multiple", False)
        count = modified_text.count(target)
        if count > 1 and not allow_multiple:
            raise ValueError(
                f"Multiple occurrences ({count}) of target content found and allow_multiple=False"
            )

        target_lines_count = len(target.splitlines())
        replacement_lines_count = len(replacement.splitlines())

        if allow_multiple:
            modified_text = modified_text.replace(target, replacement)
            hunks_applied += count
            lines_removed += target_lines_count * count
            lines_added += replacement_lines_count * count
        else:
            modified_text = modified_text.replace(target, replacement, 1)
            hunks_applied += 1
            lines_removed += target_lines_count
            lines_added += replacement_lines_count

    diff = "".join(
        difflib.unified_diff(
            original_text.splitlines(keepends=True),
            modified_text.splitlines(keepends=True),
            fromfile=f"a/{target_file}",
            tofile=f"b/{target_file}",
        )
    )

    if not dry_run:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(modified_text)

    return PatchResult(
        success=True,
        target_file=target_file,
        hunks_applied=hunks_applied,
        lines_added=lines_added,
        lines_removed=lines_removed,
        diff_patch=diff,
        message=f"Applied {hunks_applied} hunk replacement(s)",
    )


def validate_tool_call(
    tool_name: str,
    args: Dict[str, Any],
    workspace_dir: str,
    allowed_tools: Optional[List[str]] = None,
    disallowed_tools: Optional[List[str]] = None,
    enforce_patch_only: bool = False,
) -> Tuple[bool, str]:
    """Validate a tool call against tool-locking policies and patch-only constraints."""
    disallowed = disallowed_tools or []
    if tool_name in disallowed:
        return (
            False,
            f"Tool-locking violation: Tool '{tool_name}' is forbidden by tool-locking policy.",
        )

    if allowed_tools is not None and tool_name not in allowed_tools:
        return False, (
            f"Tool-locking violation: Tool '{tool_name}' is not permitted. "
            f"Permitted tools: {', '.join(allowed_tools)}"
        )

    if enforce_patch_only:
        # Full-file overwrite via write_to_file on existing files is prohibited
        if tool_name in ("write_to_file", "write_file", "create_file"):
            target_file = (
                args.get("target_file")
                or args.get("TargetFile")
                or args.get("path")
                or args.get("file")
            )
            if target_file:
                target_path = (
                    os.path.join(workspace_dir, target_file)
                    if not os.path.isabs(target_file)
                    else target_file
                )
                if os.path.exists(target_path):
                    # Check if overwrite requested
                    overwrite = args.get("overwrite", args.get("Overwrite", True))
                    if overwrite:
                        return False, (
                            f"Tool-locking violation: Overwriting existing file '{target_file}' "
                            f"using '{tool_name}' is prohibited. "
                            f"You must ONLY use patch tools ('apply_patch', "
                            f"'multi_replace_file_content', 'replace_file_content')."
                        )

        # Full-file replacement via replace_file_content is prohibited
        if tool_name in ("replace_file_content", "multi_replace_file_content"):
            target_content = args.get("target_content") or args.get("TargetContent")
            target_file = args.get("target_file") or args.get("TargetFile")
            if target_file and target_content:
                target_path = (
                    os.path.join(workspace_dir, target_file)
                    if not os.path.isabs(target_file)
                    else target_file
                )
                if os.path.exists(target_path):
                    try:
                        with open(target_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        if (
                            target_content.strip() == content.strip()
                            and len(content.splitlines()) > 5
                        ):
                            return False, (
                                f"Tool-locking violation: Full-file replacement detected on "
                                f"'{target_file}'. You must apply minimal diff hunks instead of "
                                f"rewriting the entire file."
                            )
                    except Exception:
                        pass

    return True, "Tool call validated successfully."
