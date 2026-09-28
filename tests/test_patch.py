"""Tests for patch-only mechanism, diff patch generation, and tool-locking enforcement."""

from unittest.mock import AsyncMock

import pytest

from harness_agent.evaluator import PatchOnlyEvaluator
from harness_agent.models import (
    AgentRole,
    OrchestrationPlan,
    RunResult,
    SubTask,
    TaskCheck,
    ToolCallRecord,
)
from harness_agent.orchestrator import AgentOrchestrator
from harness_agent.patch import (
    DisallowedFullFileOverwriteError,
    apply_patch,
    multi_replace_file_content,
    validate_tool_call,
)


def test_fix_1_line_bug_in_1000_line_file(tmp_path):
    """TC: Fix a 1-line bug in a 1000-line file; verify it only outputs the diff patch."""
    # 1. Create a 1000-line file with a bug at line 500
    file_path = tmp_path / "large_module.py"
    lines = [f"def helper_func_{i}(): return {i}\n" for i in range(1, 500)]
    lines.append("total_sum = val_a - val_b  # BUG: should be addition +\n")  # Line 500
    lines.extend([f"def helper_func_{i}(): return {i}\n" for i in range(501, 1001)])

    file_path.write_text("".join(lines), encoding="utf-8")
    assert len(file_path.read_text(encoding="utf-8").splitlines()) == 1000

    # 2. Patch targeting only line 500 with context
    patch_diff = """--- a/large_module.py
+++ b/large_module.py
@@ -499,3 +499,3 @@
 def helper_func_499(): return 499
-total_sum = val_a - val_b  # BUG: should be addition +
+total_sum = val_a + val_b  # BUG: should be addition +
 def helper_func_501(): return 501
"""

    # 3. Apply the patch
    result = apply_patch(
        target_file="large_module.py",
        patch_content=patch_diff,
        workspace_dir=str(tmp_path),
        enforce_tool_lock=True,
    )

    # 4. Verify results
    assert result.success is True
    assert result.hunks_applied == 1
    assert result.lines_added == 1
    assert result.lines_removed == 1

    # Verify that result.diff_patch ONLY outputs the diff patch, not the 1000 lines
    diff_lines = result.diff_patch.splitlines()
    assert len(diff_lines) < 15, f"Diff patch too large: {len(diff_lines)} lines"
    assert "@@ -497,7 +497,7 @@" in result.diff_patch
    assert "-total_sum = val_a - val_b  # BUG: should be addition +" in result.diff_patch
    assert "+total_sum = val_a + val_b  # BUG: should be addition +" in result.diff_patch

    # 5. Verify file contents on disk
    updated_content = file_path.read_text(encoding="utf-8")
    updated_lines = updated_content.splitlines()
    assert len(updated_lines) == 1000
    assert updated_lines[499] == "total_sum = val_a + val_b  # BUG: should be addition +"
    assert updated_lines[0] == "def helper_func_1(): return 1"
    assert updated_lines[999] == "def helper_func_1000(): return 1000"


def test_tool_locking_blocks_full_file_overwrite(tmp_path):
    """Verify tool-locking blocks an attempt to rewrite the entire 1000-line file."""
    file_path = tmp_path / "large_module.py"
    lines = [f"line_{i}\n" for i in range(1, 1001)]
    file_path.write_text("".join(lines), encoding="utf-8")

    # A patch that attempts to rewrite all 1000 lines in one go
    full_rewrite_patch = """--- a/large_module.py
+++ b/large_module.py
@@ -1,1000 +1,2 @@
-everything deleted
+new_content
"""

    with pytest.raises(DisallowedFullFileOverwriteError) as exc_info:
        apply_patch(
            target_file="large_module.py",
            patch_content=full_rewrite_patch,
            workspace_dir=str(tmp_path),
            enforce_tool_lock=True,
        )

    assert "Tool-locking violation" in str(exc_info.value)
    assert "attempts to rewrite entire file" in str(exc_info.value)


def test_multi_replace_file_content_and_lock(tmp_path):
    """Test targeted multi_replace_file_content and its tool-locking protection."""
    file_path = tmp_path / "app.py"
    lines = [f"var_{i} = {i}\n" for i in range(1, 100)]
    lines.append("target_bug = False  # BUG\n")
    lines.extend([f"other_{i} = {i}\n" for i in range(1, 100)])
    file_path.write_text("".join(lines), encoding="utf-8")

    # Valid targeted replace
    result = multi_replace_file_content(
        target_file="app.py",
        replacements=[
            {
                "target_content": "target_bug = False  # BUG\n",
                "replacement_content": "target_bug = True  # FIXED\n",
            }
        ],
        workspace_dir=str(tmp_path),
        enforce_tool_lock=True,
    )
    assert result.success is True
    assert result.hunks_applied == 1
    assert "target_bug = True  # FIXED" in file_path.read_text(encoding="utf-8")
    assert "-target_bug = False  # BUG" in result.diff_patch
    assert "+target_bug = True  # FIXED" in result.diff_patch

    # Attempt to replace entire file content in one go should be blocked
    full_content = file_path.read_text(encoding="utf-8")
    with pytest.raises(DisallowedFullFileOverwriteError) as exc_info:
        multi_replace_file_content(
            target_file="app.py",
            replacements=[
                {
                    "target_content": full_content,
                    "replacement_content": "print('completely rewritten')\n",
                }
            ],
            workspace_dir=str(tmp_path),
            enforce_tool_lock=True,
        )
    assert "Replacing entire file content is disallowed" in str(exc_info.value)


def test_validate_tool_call_guards(tmp_path):
    """Test validate_tool_call checks permissions and blocks write_to_file on existing files."""
    existing_file = tmp_path / "existing.py"
    existing_file.write_text("print('hello')", encoding="utf-8")

    # 1. Overwriting existing file with write_to_file should be blocked
    valid, reason = validate_tool_call(
        tool_name="write_to_file",
        args={"target_file": "existing.py", "overwrite": True},
        workspace_dir=str(tmp_path),
        enforce_patch_only=True,
    )
    assert valid is False
    assert "Tool-locking violation" in reason
    assert "Overwriting existing file" in reason

    # 2. Writing to a brand new file is allowed
    valid, reason = validate_tool_call(
        tool_name="write_to_file",
        args={"target_file": "brand_new.py", "code_content": "print('new')"},
        workspace_dir=str(tmp_path),
        enforce_patch_only=True,
    )
    assert valid is True

    # 3. Disallowed tool check
    valid, reason = validate_tool_call(
        tool_name="write_to_file_overwrite",
        args={},
        workspace_dir=str(tmp_path),
        disallowed_tools=["write_to_file_overwrite"],
    )
    assert valid is False
    assert "forbidden by tool-locking policy" in reason

    # 4. Allowed tools restriction check
    valid, reason = validate_tool_call(
        tool_name="random_tool",
        args={},
        workspace_dir=str(tmp_path),
        allowed_tools=["apply_patch", "replace_file_content"],
    )
    assert valid is False
    assert "is not permitted" in reason


def test_patch_only_evaluator(tmp_path):
    """Test PatchOnlyEvaluator validates diff hunks and flags full-file writes."""
    evaluator = PatchOnlyEvaluator()
    check = TaskCheck(type="patch_only", target="")

    # Passing case: output contains unified diff hunks
    pass_res = RunResult(
        task_id="t1",
        success=True,
        exit_code=0,
        duration_seconds=1.0,
        output_text="@@ -10,3 +10,3 @@\n-old\n+new\n",
    )
    passed, msg = evaluator.evaluate(check, pass_res, str(tmp_path))
    assert passed is True

    # Failing case: plain text with no diff hunks
    fail_res = RunResult(
        task_id="t2",
        success=True,
        exit_code=0,
        duration_seconds=1.0,
        output_text="I fixed the bug by rewriting the code.",
    )
    passed, msg = evaluator.evaluate(check, fail_res, str(tmp_path))
    assert passed is False
    assert "Output does not contain diff hunks" in msg

    # Failing case: executed write_to_file on existing file
    existing = tmp_path / "foo.py"
    existing.write_text("x = 1", encoding="utf-8")
    overwrite_res = RunResult(
        task_id="t3",
        success=True,
        exit_code=0,
        duration_seconds=1.0,
        output_text="@@ -1,1 +1,1 @@\n-x=1\n+x=2",
        tool_calls=[ToolCallRecord(name="write_to_file", args={"target_file": "foo.py"})],
    )
    passed, msg = evaluator.evaluate(check, overwrite_res, str(tmp_path))
    assert passed is False
    assert "disallowed full-file write tool" in msg


def test_coder_worker_prompt_contains_patch_only_instructions():
    """Verify that AgentOrchestrator injects the Patch-Only rule into Coder prompt."""
    orchestrator = AgentOrchestrator()
    coder_worker = orchestrator.DEFAULT_WORKERS[AgentRole.CODER]
    assert coder_worker.enforce_patch_only is True
    assert "apply_patch" in (coder_worker.allowed_tools or [])

    subtask = SubTask(
        id="sub1",
        name="Fix Bug",
        role=AgentRole.CODER,
        instruction="Fix the bug at line 500.",
    )
    plan = OrchestrationPlan(
        plan_id="p1",
        goal="Fix issue",
        tasks=[subtask],
    )

    prompt = orchestrator._build_worker_prompt(plan, subtask, coder_worker, {})
    assert "PATCH, NEVER REGENERATE" in prompt
    assert "apply_patch" in prompt
    assert "tool-locked and strictly blocked" in prompt


@pytest.mark.asyncio
async def test_orchestrator_subtask_tool_locking_rejection(tmp_path, monkeypatch):
    """Verify that an orchestrator run fails if the worker executes a locked tool."""
    orchestrator = AgentOrchestrator()
    existing_file = tmp_path / "service.py"
    existing_file.write_text("def run(): pass\n", encoding="utf-8")

    subtask = SubTask(
        id="sub_lock",
        name="Update Service",
        role=AgentRole.CODER,
        instruction="Update service.py",
        workspace_dir=str(tmp_path),
        enforce_patch_only=True,
    )
    plan = OrchestrationPlan(
        plan_id="plan_lock",
        goal="Update service",
        tasks=[subtask],
    )

    # Mock runner to simulate an agent calling write_to_file on existing file
    mock_run_result = RunResult(
        task_id="sub_lock",
        success=True,
        exit_code=0,
        duration_seconds=1.0,
        output_text="Updated file",
        tool_calls=[
            ToolCallRecord(
                name="write_to_file",
                args={"target_file": "service.py", "overwrite": True},
            )
        ],
    )

    monkeypatch.setattr(
        "harness_agent.orchestrator.AgyRunner.execute_task",
        AsyncMock(return_value=mock_run_result),
    )
    result = await orchestrator.run_plan(plan)

    assert result.success is False
    assert result.failed_tasks == 1
    assert "Tool-locking violation" in result.task_results["sub_lock"].error_message
