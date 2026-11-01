"""Unit tests for self-improving cognitive loop.

Covers:
1. test_heuristic_gate_clean_run_zero_tokens
2. test_deterministic_pattern_matching_zero_tokens
3. test_native_agy_command_construction
4. test_decayed_lfu_and_grace_period
5. test_grace_period_overflow_fallback
6. test_json_state_and_markdown_view_render
7. test_skill_yaml_safe_dump_and_hard_cap
8. test_contextual_rule_selection
9. test_cli_learn_reflect_command
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from harness_agent.cli import main
from harness_agent.core.state import WALEvent
from harness_agent.hooks.bootstrap_context import select_relevant_rules
from harness_agent.learning.harvester import TelemetryHarvester
from harness_agent.learning.models import IncidentTrajectory, IncidentType, LearnedRule
from harness_agent.learning.reflector import KnowledgeReflector


def test_heuristic_gate_clean_run_zero_tokens() -> None:
    """Clean WAL events (no status_code != 0) return empty list (0 tokens)."""
    harvester = TelemetryHarvester()

    clean_events = [
        WALEvent(
            session_id="session_clean",
            step_index=1,
            event_type="action_start",
            tool_name="read_file",
            status_code=0,
            latency_ms=10.0,
            error_message="",
        ),
        WALEvent(
            session_id="session_clean",
            step_index=2,
            event_type="action_end",
            tool_name="read_file",
            status_code=0,
            latency_ms=12.0,
            error_message="",
        ),
    ]

    # Harvest clean session
    trajectories = harvester.harvest(
        session_id="session_clean",
        wal_events=clean_events,
        critic_issues=[],
    )
    assert trajectories == []


def test_deterministic_pattern_matching_zero_tokens() -> None:
    """Feed error with BOM -> matcher creates IncidentTrajectory(is_deterministic=True)."""
    harvester = TelemetryHarvester()

    bom_error_event = WALEvent(
        session_id="session_bom",
        step_index=3,
        event_type="action_error",
        tool_name="read_file",
        status_code=1,
        latency_ms=5.0,
        error_message="SyntaxError: unexpected character after line continuation \\ufeff in file",
    )

    trajectories = harvester.harvest(
        session_id="session_bom",
        wal_events=[bom_error_event],
        critic_issues=[],
    )

    assert len(trajectories) == 1
    traj = trajectories[0]
    assert traj.is_deterministic is True
    assert traj.incident_type == IncidentType.TOOL_ERROR_RECOVERY
    assert "BOM" in traj.root_cause_hypothesis or "UTF-8" in traj.root_cause_hypothesis
    assert "utf-8-sig" in traj.resolution.lower() or "bom" in traj.resolution.lower()


def test_native_agy_command_construction() -> None:
    """Verify KnowledgeReflector builds correct CLI invocation with low effort."""
    reflector = KnowledgeReflector(
        model="gemini-3.8-flash-low",
        effort="low",
    )

    traj = IncidentTrajectory(
        session_id="session_test",
        incident_type=IncidentType.TOOL_ERROR_RECOVERY,
        trigger_error="Some unexpected runtime exception",
        failing_tool="custom_tool",
        recovery_tool="",
        root_cause_hypothesis="Unknown edge case",
        resolution="Add null check",
        is_deterministic=False,
    )

    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(
            {
                "rule": {
                    "id": "rule_custom_123",
                    "title": "Null check custom_tool",
                    "trigger_context": "unexpected runtime exception",
                    "directive": "Add null check",
                    "tags": ["custom"],
                },
                "anti_pattern": None,
                "procedural_skill": None,
            }
        )
        mock_run.return_value = mock_proc

        result = reflector.execute_native_reflection(traj)

        assert mock_run.called
        cmd_args = mock_run.call_args[0][0]
        assert cmd_args[0] == "agy"
        assert cmd_args[1] == "-p"
        assert "--model" in cmd_args
        assert cmd_args[cmd_args.index("--model") + 1] == "gemini-3.8-flash-low"
        assert "--effort" in cmd_args
        assert cmd_args[cmd_args.index("--effort") + 1] == "low"
        assert result is not None
        assert result["rule"]["id"] == "rule_custom_123"


def test_decayed_lfu_and_grace_period() -> None:
    """Create 35 rules: 30 old with high hit_count, 5 new with hit_count=1 created within 7 days.
    Run pruning to cap of 30.
    Assert newly created rules within 7-day grace period are immune to eviction.
    """
    now = 1000000.0
    day = 86400.0

    reflector = KnowledgeReflector()

    rules: list[LearnedRule] = []
    # 30 old rules created 20 days ago, hit_count between 10 and 39
    for i in range(30):
        rules.append(
            LearnedRule(
                id=f"rule_old_{i}",
                title=f"Old Rule {i}",
                trigger_context=f"context_{i}",
                directive=f"directive_{i}",
                hit_count=10 + i,
                created_at=now - (20 * day),
                last_hit_at=now - (20 * day),
            )
        )

    # 5 new rules created 2 days ago (within 7-day grace period), hit_count=1
    new_rule_ids = set()
    for i in range(5):
        rid = f"rule_new_{i}"
        new_rule_ids.add(rid)
        rules.append(
            LearnedRule(
                id=rid,
                title=f"New Rule {i}",
                trigger_context=f"new_context_{i}",
                directive=f"new_directive_{i}",
                hit_count=1,
                created_at=now - (2 * day),
                last_hit_at=now - (2 * day),
            )
        )

    assert len(rules) == 35

    pruned = reflector.prune_rules(rules, max_rules=30, now=now)
    assert len(pruned) == 30

    pruned_ids = {r.id for r in pruned}
    # All 5 new rules must survive because they are immune in grace period
    for rid in new_rule_ids:
        assert rid in pruned_ids, f"New rule {rid} within grace period was evicted!"

    # 5 old rules with lowest priority score were evicted
    evicted_ids = {r.id for r in rules if r.id not in pruned_ids}
    assert len(evicted_ids) == 5
    for eid in evicted_ids:
        assert eid.startswith("rule_old_")


def test_grace_period_overflow_fallback() -> None:
    """Create 35 rules where ALL 35 rules are < 7 days old (all in grace period).
    Run pruning with cap of 30.
    Assert fallback engages: immunity is bypassed, hard cap of 30 is strictly enforced,
    and the 5 lowest-scored rules are evicted.
    """
    now = 1000000.0
    day = 86400.0

    reflector = KnowledgeReflector()

    rules: list[LearnedRule] = []
    # All 35 rules created 3 days ago (< 7 days grace period)
    # hit_count from 1 to 35
    for i in range(35):
        rules.append(
            LearnedRule(
                id=f"rule_{i:02d}",
                title=f"Rule {i}",
                trigger_context=f"context_{i}",
                directive=f"directive_{i}",
                hit_count=i + 1,
                created_at=now - (3 * day),
                last_hit_at=now - (3 * day),
            )
        )

    assert len(rules) == 35
    for r in rules:
        assert r.is_in_grace_period(grace_period_days=7.0, now=now) is True

    pruned = reflector.prune_rules(rules, max_rules=30, now=now)
    assert len(pruned) == 30

    pruned_ids = {r.id for r in pruned}
    # Lowest scored rules (rule_00, rule_01, rule_02, rule_03, rule_04) must be evicted
    for i in range(5):
        assert f"rule_{i:02d}" not in pruned_ids
    for i in range(5, 35):
        assert f"rule_{i:02d}" in pruned_ids


def test_json_state_and_markdown_view_render(tmp_path: Path) -> None:
    """Save rules.json and verify generated rules.md renders properly."""
    reflector = KnowledgeReflector(output_dir=tmp_path)

    rules = [
        LearnedRule(
            id="rule_sql_injection",
            title="Sanitize SQL Queries",
            trigger_context="database error, sql injection",
            directive="Use parameterized SQL bindings.",
            tags=["sql", "security"],
            hit_count=4,
            created_at=time.time(),
            last_hit_at=time.time(),
        ),
        LearnedRule(
            id="rule_path_traversal",
            title="Resolve Safe Paths",
            trigger_context="path traversal",
            directive="Always use path.resolve() within bounds.",
            tags=["path", "security"],
            hit_count=2,
            created_at=time.time(),
            last_hit_at=time.time(),
        ),
    ]

    reflector.save_rules(rules, render_markdown=True)

    json_path = tmp_path / "rules.json"
    md_path = tmp_path / "rules.md"

    assert json_path.is_file()
    assert md_path.is_file()

    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(loaded) == 2
    assert loaded[0]["id"] == "rule_sql_injection"

    md_content = md_path.read_text(encoding="utf-8")
    assert "# Semantic Memory: Learned Rules" in md_content
    assert "Sanitize SQL Queries (`rule_sql_injection`)" in md_content
    assert "Use parameterized SQL bindings." in md_content
    assert "Resolve Safe Paths (`rule_path_traversal`)" in md_content


def test_skill_yaml_safe_dump_and_hard_cap(tmp_path: Path) -> None:
    """Generate skills using yaml.safe_dump.

    Verify valid YAML parsing on complex descriptions (colons, quotes).
    Generate 16 skills; verify 16th triggers archiving least active to skills-archive.
    """
    skills_dir = tmp_path / "skills"
    archive_dir = tmp_path / "archive"

    reflector = KnowledgeReflector(
        skills_dir=skills_dir,
        skills_archive_dir=archive_dir,
    )

    # 1. Verify safe YAML with complex characters
    frontmatter = {
        "name": "learned-complex-skill",
        "description": "Complex text with: colons, 'single quotes', \"double quotes\" and # hash",
        "tags": ["testing", "yaml"],
    }
    skill_file = reflector.save_procedural_skill(
        skill_name="learned-complex-skill",
        frontmatter=frontmatter,
        content="# Complex Skill Instruction\nDo step A and then step B.",
    )
    assert skill_file.is_file()
    raw_text = skill_file.read_text(encoding="utf-8")
    parts = raw_text.split("---")
    parsed_fm = yaml.safe_load(parts[1])
    assert parsed_fm["name"] == "learned-complex-skill"
    assert "colons" in parsed_fm["description"]

    # 2. Generate 16 skills and verify 16th triggers archiving the oldest
    # Clean directory for pure 16 skills test
    for p in skills_dir.iterdir():
        if p.is_dir():
            import shutil

            shutil.rmtree(p)

    base_time = 1000000.0
    for i in range(16):
        s_name = f"learned-skill-{i:02d}"
        s_file = reflector.save_procedural_skill(
            skill_name=s_name,
            frontmatter={"name": s_name, "description": f"Skill {i}"},
            content=f"Instruction for skill {i}",
        )
        # Set mtime explicitly to simulate chronological generation
        mtime = base_time + (i * 100)
        import os

        os.utime(s_file, (mtime, mtime))
        os.utime(s_file.parent, (mtime, mtime))

    # Re-enforce skill cap to make sure archive triggered
    reflector._enforce_skill_cap()

    active_skills = [p for p in skills_dir.iterdir() if p.is_dir()]
    archived_skills = [p for p in archive_dir.iterdir() if p.is_dir()]

    assert len(active_skills) == 15
    assert len(archived_skills) >= 1
    # Oldest skill learned-skill-00 must be in archive
    assert (archive_dir / "learned-skill-00").exists()
    assert not (skills_dir / "learned-skill-00").exists()


def test_contextual_rule_selection() -> None:
    """Setup rules tagged with powershell, sql, python.
    Query for task with goal: 'Write PostgreSQL query' and file query.sql.
    Verify selected rules prioritize sql over powershell.
    """
    now = time.time()
    rule_global = LearnedRule(
        id="rule_global_anchor",
        title="Check permissions first",
        trigger_context="general access",
        directive="Always check permissions before writing files.",
        tags=["general"],
        hit_count=50,  # Highest score anchor
        created_at=now,
        last_hit_at=now,
    )
    rule_sql = LearnedRule(
        id="rule_sql_patterns",
        title="PostgreSQL Indexing Directives",
        trigger_context="sql postgres query database",
        directive="Always use indexed columns in WHERE clauses.",
        tags=["sql", "postgres"],
        hit_count=5,
        created_at=now,
        last_hit_at=now,
    )
    rule_python = LearnedRule(
        id="rule_python_patterns",
        title="Python PEP8 Formatting",
        trigger_context="pep8 flake8 black python",
        directive="Follow strict 100 char limit in python files.",
        tags=["python"],
        hit_count=4,
        created_at=now,
        last_hit_at=now,
    )
    rule_ps1 = LearnedRule(
        id="rule_ps1_patterns",
        title="PowerShell UTF8 Execution",
        trigger_context="powershell utf-8 encoding scripts",
        directive="Pass -Encoding utf8 to Set-Content.",
        tags=["powershell"],
        hit_count=6,
        created_at=now,
        last_hit_at=now,
    )

    all_rules = [rule_global, rule_sql, rule_python, rule_ps1]
    context_keywords = ["sql", "postgres", "query.sql", ".sql", "write postgresql query"]

    selected = select_relevant_rules(all_rules, context_keywords=context_keywords, max_rules=3)

    assert len(selected) == 3
    # Top 1 anchor is rule_global (highest score)
    assert selected[0].id == "rule_global_anchor"

    # Contextual matches must contain rule_sql
    selected_ids = [r.id for r in selected]
    assert "rule_sql_patterns" in selected_ids
    # rule_sql must be ranked before rule_ps1 in the context matches
    sql_idx = selected_ids.index("rule_sql_patterns")
    if "rule_ps1_patterns" in selected_ids:
        ps1_idx = selected_ids.index("rule_ps1_patterns")
        assert sql_idx < ps1_idx


def test_cli_learn_reflect_command(tmp_path: Path) -> None:
    """Run harness-agent learn reflect via Click test runner; verify exit code 0."""
    runner = CliRunner()
    output_dir = tmp_path / "learned"
    skills_dir = tmp_path / "skills"

    result = runner.invoke(
        main,
        [
            "learn",
            "reflect",
            "--output-dir",
            str(output_dir),
            "--skills-dir",
            str(skills_dir),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "[OK]" in result.output or "[DRY-RUN]" in result.output
