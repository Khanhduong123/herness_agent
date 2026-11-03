"""Integration tests for autonomous learning workflow.

Layer 2 Integration Test verifying the end-to-end autonomous learning lifecycle:
1. Stop Event triggers background reflection and deterministic regex synthesizes
   rules.json and rules.md (0 LLM tokens).
2. SessionStart context bootstrapper injects learned directives within token budget
   and handles corrupt/empty files gracefully.
3. Cross-project sync propagates synthesized skills and configuration to target projects.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness_agent.cli import _get_registered_projects, _sync_single_project
from harness_agent.core.dispatch import HerdrDispatcher
from harness_agent.core.state import EventWAL, WALEvent
from harness_agent.hooks.bootstrap_context import (
    MAX_LEARNED_RULES,
    MAX_LEARNED_TOKENS,
    _format_learned_directives_section,
    _load_learned_rules_pure_python,
    estimate_tokens,
    select_relevant_rules,
)
from harness_agent.learning.models import LearnedRule


def test_e2e_stop_event_triggers_background_reflection(tmp_path: Path) -> None:
    """Verify invoking a Stop Event triggers background reflection pipeline producing rules."""
    context_dir = tmp_path / ".ai" / "context"
    learned_dir = tmp_path / ".ai" / "learned"
    skills_dir = tmp_path / ".agents" / "skills"

    context_dir.mkdir(parents=True, exist_ok=True)
    learned_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)

    # 1. Write real incident event matching KNOWN_TOOL_PATTERNS tool-locking regex
    wal_file = context_dir / "wal_actions.log"
    wal = EventWAL(wal_file)
    wal.append_event(
        WALEvent(
            session_id="session_e2e_stop",
            step_index=1,
            event_type="action_error",
            tool_name="write_to_file",
            status_code=1,
            latency_ms=12.5,
            error_message=(
                "Tool-locking violation: Tool 'write_to_file' is not permitted. "
                "Permitted tools: apply_patch, replace_file_content"
            ),
        )
    )

    # 2. Invoke Stop Event via HerdrDispatcher.abort_task with repo_root pointing to tmp_path
    # Mock subprocess.run for herdr/git cleanup commands so abort_task executes cleanly on tmp_path
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ok, msg = HerdrDispatcher.abort_task(
            task_id="test_subtask",
            reason="Tool violation",
            repo_root=tmp_path,
        )
        assert ok is True

    # 3. Deterministic wait loop polling for rules.json (Timeout 10s)
    rules_file = learned_dir / "rules.json"
    start_time = time.time()
    while not rules_file.exists() and (time.time() - start_time) < 10.0:
        time.sleep(0.2)

    assert rules_file.exists(), "Timed out waiting for background reflection to write rules.json"

    # 4. Assertions on rules.json and rules.md
    rules_content = rules_file.read_text(encoding="utf-8")
    rules_data = json.loads(rules_content)
    assert isinstance(rules_data, list)
    assert len(rules_data) >= 1

    first_rule = rules_data[0]
    assert "apply_patch" in first_rule.get("directive", "")
    assert "write_to_file" in first_rule.get("title", "") or "write_to_file" in first_rule.get(
        "trigger_context", ""
    )

    rules_md = learned_dir / "rules.md"
    assert rules_md.exists()
    md_content = rules_md.read_text(encoding="utf-8")
    assert "Learned Rules" in md_content
    assert "apply_patch" in md_content


def test_e2e_session_start_directive_injection_and_budget(tmp_path: Path) -> None:
    """Verify SessionStart hook selects directives, enforces budget, and resists corruption."""
    learned_dir = tmp_path / ".ai" / "learned"
    learned_dir.mkdir(parents=True, exist_ok=True)
    rules_file = learned_dir / "rules.json"

    # 1. Relevance Selection & Budget Enforcement with 5 rules
    rules_data = [
        {
            "id": "rule_01_tool_lock",
            "title": "Use Patch Tools",
            "trigger_context": "write_to_file, tool_locking, patch",
            "directive": (
                "Always use apply_patch or replace_file_content when modifying existing files."
            ),
            "tags": ["patch", "tools", "python"],
            "hit_count": 10,
            "created_at": time.time(),
            "last_hit_at": time.time(),
        },
        {
            "id": "rule_02_utf8_bom",
            "title": "Strip UTF-8 BOM",
            "trigger_context": "read_file, bom, utf-8-sig",
            "directive": (
                "Ensure UTF-8 BOM files are opened with encoding utf-8-sig to prevent SyntaxError."
            ),
            "tags": ["encoding", "bom"],
            "hit_count": 8,
            "created_at": time.time(),
            "last_hit_at": time.time(),
        },
        {
            "id": "rule_03_worktree_lock",
            "title": "Clean Git Worktree Locks",
            "trigger_context": "git, worktree, lock",
            "directive": "Remove stale worktree references and index.lock before spawning worker.",
            "tags": ["git", "worktree"],
            "hit_count": 6,
            "created_at": time.time(),
            "last_hit_at": time.time(),
        },
        {
            "id": "rule_04_irrelevant_latex",
            "title": "LaTeX Font Cache",
            "trigger_context": "latex, pdflatex, font",
            "directive": (
                "Rebuild font cache using luaotfload-tool before compiling heavy documents."
            ),
            "tags": ["latex", "fonts"],
            "hit_count": 2,
            "created_at": time.time(),
            "last_hit_at": time.time(),
        },
        {
            "id": "rule_05_irrelevant_crawler",
            "title": "Respect Crawler Politeness",
            "trigger_context": "crawl, web, rate_limit",
            "directive": "Apply exponential backoff when crawling scholarly endpoints.",
            "tags": ["crawler", "rate_limit"],
            "hit_count": 1,
            "created_at": time.time(),
            "last_hit_at": time.time(),
        },
    ]
    rules_file.write_text(json.dumps(rules_data, indent=2), encoding="utf-8")

    loaded_raw = _load_learned_rules_pure_python(tmp_path)
    assert len(loaded_raw) == 5

    learned_rules = [LearnedRule(**r) for r in loaded_raw]
    context_keywords = ["write_to_file", "patch", "git", "python"]
    selected = select_relevant_rules(
        learned_rules, context_keywords=context_keywords, max_rules=MAX_LEARNED_RULES
    )

    assert len(selected) <= MAX_LEARNED_RULES
    selected_ids = {r.id for r in selected}
    assert "rule_01_tool_lock" in selected_ids

    formatted_lines = _format_learned_directives_section(selected, max_tokens=MAX_LEARNED_TOKENS)
    formatted_text = "\n".join(formatted_lines)

    assert "#### Learned Project Directives" in formatted_text
    assert estimate_tokens(formatted_text) <= MAX_LEARNED_TOKENS

    # 2. Corruption & Empty File Resilience
    rules_file.write_text('{"corrupted": ', encoding="utf-8")
    corrupt_result = _load_learned_rules_pure_python(tmp_path)
    assert corrupt_result == []

    rules_file.write_text("", encoding="utf-8")
    empty_result = _load_learned_rules_pure_python(tmp_path)
    assert empty_result == []

    rules_file.unlink()
    missing_result = _load_learned_rules_pure_python(tmp_path)
    assert missing_result == []


def test_e2e_cross_project_sync(tmp_path: Path) -> None:
    """Verify synthesized skills and rules propagate to a separate project folder."""
    source_root = tmp_path / "source_repo"
    target_root = tmp_path / "target_project"

    source_root.mkdir(parents=True, exist_ok=True)
    target_root.mkdir(parents=True, exist_ok=True)

    # 1. Scaffold source repository with standard files
    (source_root / "AGENTS.md").write_text("# Unified AGENTS.md Standards\n", encoding="utf-8")
    (source_root / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")
    examples_dir = source_root / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)
    (examples_dir / "orchestrator_plan.yaml").write_text("plan_id: sample\n", encoding="utf-8")

    # 2. Scaffold learned skill in source_root / .agents / skills
    learned_skill_dir = source_root / ".agents" / "skills" / "learned-patch-enforcement"
    learned_skill_dir.mkdir(parents=True, exist_ok=True)
    skill_content = (
        "---\n"
        "name: learned-patch-enforcement\n"
        "description: Enforces patch-only tool execution.\n"
        "---\n\n"
        "# Patch Enforcement Instructions\n"
        "Always use apply_patch or replace_file_content.\n"
    )
    (learned_skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")

    # 3. Execute _sync_single_project in copy mode
    copied_count = _sync_single_project(repo_root=source_root, target_path=target_root, link=False)
    assert copied_count > 0

    target_skill_file = (
        target_root / ".agents" / "skills" / "learned-patch-enforcement" / "SKILL.md"
    )
    assert target_skill_file.exists()
    assert target_skill_file.read_text(encoding="utf-8") == skill_content
    assert (target_root / "AGENTS.md").exists()

    # 4. Verify project is registered in projects.json registry
    registered = _get_registered_projects(source_root)
    assert str(target_root.resolve()) in registered

    # 5. Verify symlink/junction sync mode
    target_link_root = tmp_path / "target_link_project"
    target_link_root.mkdir(parents=True, exist_ok=True)
    _sync_single_project(repo_root=source_root, target_path=target_link_root, link=True)

    target_link_skill_file = (
        target_link_root / ".agents" / "skills" / "learned-patch-enforcement" / "SKILL.md"
    )
    assert target_link_skill_file.exists()
    assert target_link_skill_file.read_text(encoding="utf-8") == skill_content
