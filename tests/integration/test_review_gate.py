"""Unit tests for CLI review command and Automated Critic Gate in PR and Worktree."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from harness_agent.cli import main
from harness_agent.core.dispatch import HerdrDispatcher
from harness_agent.core.models import AgentRole, AggregatedCriticReview, CriticFeedback
from harness_agent.core.pr import PRGenerator, PRResult

DISPATCH_CRITICS = "harness_agent.evaluation.critics.dispatch_parallel_critics"
GET_DIFF = "harness_agent.cli._get_git_diff"


def _make_review(approved: bool = True, issues: list[str] | None = None) -> AggregatedCriticReview:
    """Helper to construct an AggregatedCriticReview."""
    issues = issues or []
    feedbacks = {
        AgentRole.SECURITY_REVIEWER.value: CriticFeedback(
            role=AgentRole.SECURITY_REVIEWER,
            critic_name="security-reviewer",
            approved=approved,
            issues=issues if not approved else [],
        ),
        AgentRole.PERFORMANCE_REVIEWER.value: CriticFeedback(
            role=AgentRole.PERFORMANCE_REVIEWER,
            critic_name="performance-reviewer",
            approved=True,
            issues=[],
        ),
        AgentRole.REQUIREMENT_REVIEWER.value: CriticFeedback(
            role=AgentRole.REQUIREMENT_REVIEWER,
            critic_name="requirement-reviewer",
            approved=True,
            issues=[],
        ),
    }
    summary_lines = [
        "## Adversarial Critic Review Report",
        f"**Overall Status:** {'APPROVED' if approved else 'REJECTED'}",
        "",
        "### Critic: security-reviewer (SECURITY_REVIEWER) "
        + ("[PASSED]" if approved else "[FAILED]"),
    ]
    if not approved and issues:
        summary_lines.append("**Issues Detected:**")
        for iss in issues:
            summary_lines.append(f"- {iss}")
    else:
        summary_lines.append("No critical defects found.")
    return AggregatedCriticReview(
        approved=approved,
        critics_feedback=feedbacks,
        summary="\n".join(summary_lines),
    )


# ---------------------------------------------------------------------------
# 1. harness-agent review CLI tests
# ---------------------------------------------------------------------------


def test_review_cmd_approved(tmp_path: Path) -> None:
    """Verify harness-agent review succeeds with exit code 0 when critics approve."""
    runner = CliRunner()
    output_file = tmp_path / "report.json"
    mock_rev = _make_review(approved=True)

    with patch("harness_agent.cli._get_git_diff", return_value="diff --git a b"):
        with patch(DISPATCH_CRITICS, return_value=mock_rev):
            result = runner.invoke(main, ["review", "--base", "main", "-o", str(output_file)])
            assert result.exit_code == 0
            assert "[PASSED]" in result.output
            assert "[OK] Adversarial Critic Review: PASSED" in result.output
            assert output_file.exists()
            data = json.loads(output_file.read_text(encoding="utf-8"))
            assert data["approved"] is True


def test_review_cmd_rejected_fail_on_reject(tmp_path: Path) -> None:
    """Verify harness-agent review exits with 1 when critics reject under --fail-on-reject."""
    runner = CliRunner()
    output_file = tmp_path / "report.json"
    mock_rev = _make_review(approved=False, issues=["SQL Injection detected at line 10"])

    with patch("harness_agent.cli._get_git_diff", return_value="diff --git a b"):
        with patch(DISPATCH_CRITICS, return_value=mock_rev):
            result = runner.invoke(
                main,
                ["review", "--base", "main", "--fail-on-reject", "-o", str(output_file)],
            )
            assert result.exit_code == 1
            assert "[FAILED]" in result.output
            assert "SQL Injection detected" in result.output
            assert "[FAIL] Adversarial Critic Review: REJECTED" in result.output


def test_review_cmd_rejected_allow_reject() -> None:
    """Verify harness-agent review exits with 0 when critics reject under --allow-reject."""
    runner = CliRunner()
    mock_rev = _make_review(approved=False, issues=["Potential O(N^2) loop"])

    with patch("harness_agent.cli._get_git_diff", return_value="diff --git a b"):
        with patch(DISPATCH_CRITICS, return_value=mock_rev):
            result = runner.invoke(main, ["review", "--allow-reject"])
            assert result.exit_code == 0
            assert "[FAILED]" in result.output
            assert "[FAIL] Adversarial Critic Review: REJECTED" in result.output


def test_review_cmd_with_diff_file(tmp_path: Path) -> None:
    """Verify harness-agent review reads diff from --diff-file."""
    runner = CliRunner()
    diff_file = tmp_path / "custom.diff"
    diff_file.write_text("diff --git a/test.py b/test.py\n+def foo(): pass", encoding="utf-8")
    mock_rev = _make_review(approved=True)

    with patch("harness_agent.evaluation.critics.dispatch_parallel_critics", return_value=mock_rev):
        result = runner.invoke(main, ["review", "--diff-file", str(diff_file)])
        assert result.exit_code == 0
        assert "[OK] Adversarial Critic Review: PASSED" in result.output


def test_review_cmd_missing_diff_file() -> None:
    """Verify harness-agent review fails when --diff-file does not exist."""
    runner = CliRunner()
    result = runner.invoke(main, ["review", "--diff-file", "nonexistent_file.diff"])
    assert result.exit_code == 1
    assert "Diff file not found" in result.output


def test_review_cmd_markdown_output(tmp_path: Path) -> None:
    """Verify harness-agent review saves markdown summary when output ends with .md."""
    runner = CliRunner()
    md_file = tmp_path / "report.md"
    mock_rev = _make_review(approved=True)

    with patch("harness_agent.cli._get_git_diff", return_value="diff --git a b"):
        with patch(DISPATCH_CRITICS, return_value=mock_rev):
            result = runner.invoke(main, ["review", "-o", str(md_file)])
            assert result.exit_code == 0
            assert md_file.exists()
            content = md_file.read_text(encoding="utf-8")
            assert "## Adversarial Critic Review Report" in content


# ---------------------------------------------------------------------------
# 2. harness-agent pr create critic gate tests
# ---------------------------------------------------------------------------


def test_pr_create_critic_gate_approved() -> None:
    """Verify harness-agent pr create passes Critic Gate and calls create_pr."""
    runner = CliRunner()
    mock_rev = _make_review(approved=True)
    mock_res = PRResult(
        success=True,
        pr_url="https://github.com/org/repo/pull/123",
        title="feat: test",
        body="Body",
    )

    with patch("harness_agent.cli._get_git_diff", return_value="diff --git a b"):
        with patch(DISPATCH_CRITICS, return_value=mock_rev):
            with patch.object(PRGenerator, "create_pr", return_value=mock_res) as mock_create:
                result = runner.invoke(main, ["pr", "create", "--base", "main"])
                assert result.exit_code == 0
                assert "[OK] Adversarial Critics approved changes." in result.output
                assert mock_create.called
                call_kwargs = mock_create.call_args.kwargs
                assert call_kwargs.get("critic_review") == mock_rev


def test_pr_create_critic_gate_rejected_aborts() -> None:
    """Verify harness-agent pr create aborts when critics reject and not --draft."""
    runner = CliRunner()
    mock_rev = _make_review(approved=False, issues=["Command injection in runner.py"])

    with patch("harness_agent.cli._get_git_diff", return_value="diff --git a b"):
        with patch(DISPATCH_CRITICS, return_value=mock_rev):
            with patch.object(PRGenerator, "create_pr") as mock_create:
                result = runner.invoke(main, ["pr", "create", "--base", "main"])
                assert result.exit_code == 1
                assert (
                    "[FAIL] Pull request creation aborted: "
                    "Adversarial Critics detected critical issues." in result.output
                )
                assert "Command injection" in result.output
                mock_create.assert_not_called()


def test_pr_create_critic_gate_rejected_draft_proceeds() -> None:
    """Verify harness-agent pr create proceeds when critics reject if --draft is specified."""
    runner = CliRunner()
    mock_rev = _make_review(approved=False, issues=["Missing docstring"])
    mock_res = PRResult(
        success=True,
        pr_url="https://github.com/org/repo/pull/124",
        title="feat: draft PR",
        body="Body",
    )

    with patch("harness_agent.cli._get_git_diff", return_value="diff --git a b"):
        with patch(DISPATCH_CRITICS, return_value=mock_rev):
            with patch.object(PRGenerator, "create_pr", return_value=mock_res) as mock_create:
                result = runner.invoke(main, ["pr", "create", "--base", "main", "--draft"])
                assert result.exit_code == 0
                assert (
                    "[WARN] Adversarial Critics detected issues, continuing for draft PR."
                    in result.output
                )
                assert mock_create.called


def test_pr_create_critic_gate_no_review() -> None:
    """Verify harness-agent pr create skips critics check when --no-review is provided."""
    runner = CliRunner()
    mock_res = PRResult(
        success=True,
        pr_url="https://github.com/org/repo/pull/125",
        title="feat: no review",
        body="Body",
    )

    with patch("harness_agent.evaluation.critics.dispatch_parallel_critics") as mock_dispatch:
        with patch.object(PRGenerator, "create_pr", return_value=mock_res) as mock_create:
            result = runner.invoke(main, ["pr", "create", "--base", "main", "--no-review"])
            assert result.exit_code == 0
            mock_dispatch.assert_not_called()
            assert mock_create.called
            assert mock_create.call_args.kwargs.get("no_review") is True


def test_pr_template_embeds_critic_gate_summary(tmp_path: Path) -> None:
    """Verify PRGenerator.generate_pr_content populates ## Adversarial Critic Review Gate."""
    mock_rev = _make_review(approved=True)
    _, body = PRGenerator.generate_pr_content(
        repo_root=tmp_path,
        base_branch="main",
        critic_review=mock_rev,
    )
    assert "## Adversarial Critic Review Gate" in body
    assert "- [x] Security Reviewer" in body
    assert "- [x] Performance Reviewer" in body
    assert "- [x] Requirement Reviewer" in body
    assert "<details>" in body
    assert "Adversarial Critic Evaluation Summary" in body
    assert "## Adversarial Critic Review Report" in body


# ---------------------------------------------------------------------------
# 3. harness-agent worktree merge critic gate tests
# ---------------------------------------------------------------------------


def test_worktree_merge_critic_gate_approved() -> None:
    """Verify harness-agent worktree merge proceeds when critics approve."""
    runner = CliRunner()
    mock_rev = _make_review(approved=True)

    with patch("harness_agent.cli._get_git_diff", return_value="diff --git a b"):
        with patch(DISPATCH_CRITICS, return_value=mock_rev):
            with patch.object(
                HerdrDispatcher,
                "merge_worktree_to_feature",
                return_value=(True, "Merged worktree successfully"),
            ) as mock_merge:
                result = runner.invoke(
                    main, ["worktree", "merge", "task_01", "--into", "feat/test"]
                )
                assert result.exit_code == 0
                assert "[OK] Adversarial Critics approved changes." in result.output
                assert "Merged worktree successfully" in result.output
                mock_merge.assert_called_once()


def test_worktree_merge_critic_gate_rejected_aborts() -> None:
    """Verify harness-agent worktree merge aborts when critics reject."""
    runner = CliRunner()
    mock_rev = _make_review(approved=False, issues=["Unsanitized eval() detected"])

    with patch("harness_agent.cli._get_git_diff", return_value="diff --git a b"):
        with patch(DISPATCH_CRITICS, return_value=mock_rev):
            with patch.object(HerdrDispatcher, "merge_worktree_to_feature") as mock_merge:
                result = runner.invoke(
                    main, ["worktree", "merge", "task_01", "--into", "feat/test"]
                )
                assert result.exit_code == 1
                assert (
                    "[FAIL] Worktree merge aborted: Adversarial Critics detected critical issues"
                    in result.output
                )
                assert "Unsanitized eval()" in result.output
                mock_merge.assert_not_called()


def test_worktree_merge_critic_gate_no_review() -> None:
    """Verify harness-agent worktree merge skips critics when --no-review is provided."""
    runner = CliRunner()

    with patch("harness_agent.evaluation.critics.dispatch_parallel_critics") as mock_dispatch:
        with patch.object(
            HerdrDispatcher,
            "merge_worktree_to_feature",
            return_value=(True, "Merged worktree successfully"),
        ) as mock_merge:
            result = runner.invoke(
                main,
                ["worktree", "merge", "task_01", "--into", "feat/test", "--no-review"],
            )
            assert result.exit_code == 0
            mock_dispatch.assert_not_called()
            mock_merge.assert_called_once()
