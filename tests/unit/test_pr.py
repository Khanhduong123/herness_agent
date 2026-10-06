"""Unit tests for Pull Request template engine and context collector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest
from click.testing import CliRunner

from harness_agent.cli import main
from harness_agent.core.models import AgentRole, AggregatedCriticReview, CriticFeedback
from harness_agent.core.pr import DEFAULT_PR_TEMPLATE, PRContext, PRGenerator, PRResult


@pytest.fixture(autouse=True)
def mock_critics_in_pr_tests(monkeypatch):
    mock_rev = AggregatedCriticReview(
        approved=True,
        critics_feedback={
            AgentRole.SECURITY_REVIEWER.value: CriticFeedback(
                role=AgentRole.SECURITY_REVIEWER,
                critic_name="security-reviewer",
                approved=True,
            ),
            AgentRole.PERFORMANCE_REVIEWER.value: CriticFeedback(
                role=AgentRole.PERFORMANCE_REVIEWER,
                critic_name="performance-reviewer",
                approved=True,
            ),
            AgentRole.REQUIREMENT_REVIEWER.value: CriticFeedback(
                role=AgentRole.REQUIREMENT_REVIEWER,
                critic_name="requirement-reviewer",
                approved=True,
            ),
        },
        summary="## Adversarial Critic Review Report\nAll checks passed.",
    )

    async def fake_dispatch(*args, **kwargs):
        return mock_rev

    monkeypatch.setattr(
        "harness_agent.evaluation.critics.dispatch_parallel_critics",
        fake_dispatch,
    )


def test_find_template(tmp_path: Path) -> None:
    """Verifies finding existing pull request template."""
    # When template does not exist
    assert PRGenerator.find_template(repo_root=tmp_path) is None

    # When template exists under .github
    gh_dir = tmp_path / ".github"
    gh_dir.mkdir(parents=True)
    template_file = gh_dir / "pull_request_template.md"
    template_file.write_text("## Description\n\nTemplate content", encoding="utf-8")

    found = PRGenerator.find_template(repo_root=tmp_path)
    assert found is not None
    assert found == template_file


def test_collect_git_context(tmp_path: Path) -> None:
    """Mock subprocess calls for git branch, log, diff, and verify categorization."""

    def mock_run(args, **kwargs):
        cmd = args
        cmd_str = " ".join(cmd)
        result = MagicMock()
        result.returncode = 0

        if "branch --show-current" in cmd_str:
            result.stdout = "feat/awesome-feature\n"
        elif "log" in cmd_str:
            result.stdout = (
                "a1b2c3d feat(core): implement core engine\n"
                "d4e5f6a fix(ui): fix broken button alignment\n"
                "f7g8h9i docs: update installation guide\n"
            )
        elif "diff --stat" in cmd_str:
            result.stdout = "src/core.py | 10 ++++++++++\n 1 file changed\n"
        elif "diff --name-only" in cmd_str:
            result.stdout = "src/core.py\nsrc/ui.py\n"
        else:
            result.stdout = ""

        result.stderr = ""
        return result

    with patch("subprocess.run", side_effect=mock_run):
        ctx = PRGenerator.collect_git_context(repo_root=tmp_path, base_branch="main")

        assert ctx.branch_name == "feat/awesome-feature"
        assert ctx.base_branch == "main"
        assert len(ctx.commits) == 3
        assert ctx.commits[0]["hash"] == "a1b2c3d"
        assert ctx.commits[0]["message"] == "feat(core): implement core engine"
        assert "src/core.py" in ctx.changed_files
        assert "src/ui.py" in ctx.changed_files
        assert "New feature" in ctx.inferred_types
        assert "Bug fix" in ctx.inferred_types
        assert "Documentation update" in ctx.inferred_types
        assert ctx.python_version != ""
        assert ctx.os_info != ""


def test_generate_pr_content_fills_checkboxes_and_system_info(tmp_path: Path) -> None:
    """Ensures [x] replacement works for feat, fix, docs, and Python/OS are injected."""
    template_dir = tmp_path / ".github"
    template_dir.mkdir(parents=True)
    template_path = template_dir / "pull_request_template.md"
    template_path.write_text(DEFAULT_PR_TEMPLATE, encoding="utf-8")

    mock_context = PRContext(
        branch_name="feat/my-feature",
        base_branch="main",
        commits=[
            {"hash": "111", "message": "feat: add feature", "sha": "111", "subject": "add"},
            {"hash": "222", "message": "fix: fix bug", "sha": "222", "subject": "fix"},
            {"hash": "333", "message": "docs: add docs", "sha": "333", "subject": "docs"},
        ],
        diff_stat="2 files changed",
        changed_files=["src/a.py", "docs/index.md"],
        inferred_types=["New feature", "Bug fix", "Documentation update"],
        python_version="3.10.12",
        os_info="Linux 5.15.0",
    )

    with patch.object(PRGenerator, "collect_git_context", return_value=mock_context):
        title, body = PRGenerator.generate_pr_content(repo_root=tmp_path, base_branch="main")

        assert title == "feat: my feature"
        assert "- [x] New feature" in body
        assert "- [x] Bug fix" in body
        assert "- [x] Documentation update" in body
        assert "- [ ] Breaking change" in body
        assert "- [x] Unit Tests" in body
        assert "- [x] Manual Verification" in body
        assert "* Python version: 3.10.12" in body
        assert "* OS: Linux 5.15.0" in body
        assert "- [x] My code follows the style guidelines" in body
        assert "- [x] I have performed a self-review" in body
        assert "<!-- Fixes # (issue) -->" in body


def test_generate_pr_content_with_issue_and_custom_title(tmp_path: Path) -> None:
    """Verifies custom title, issue replacement, and test output evidence injection."""
    mock_context = PRContext(
        branch_name="fix/login-bug",
        base_branch="main",
        commits=[
            {"hash": "444", "message": "fix: resolve login loop", "sha": "444", "subject": "fix"},
        ],
        diff_stat="1 file changed",
        changed_files=["src/auth.py"],
        inferred_types=["Bug fix"],
        python_version="3.11.0",
        os_info="Windows 10",
    )

    with patch.object(PRGenerator, "collect_git_context", return_value=mock_context):
        title, body = PRGenerator.generate_pr_content(
            repo_root=tmp_path,
            issue_id="42",
            custom_title="Custom Login Fix Title",
            test_output="10 passed, 0 failed in 1.2s",
        )

        assert title == "Custom Login Fix Title"
        assert "Fixes #42" in body
        assert "- [x] Console logs / Test Output included" in body
        assert "10 passed, 0 failed in 1.2s" in body


def test_create_pr_gh_cli_success(tmp_path: Path) -> None:
    """Mock successful gh pr create."""

    def mock_run(args, **kwargs):
        cmd = args
        cmd_str = " ".join(cmd)
        result = MagicMock()
        result.returncode = 0

        if "branch --show-current" in cmd_str:
            result.stdout = "feat/new-api\n"
        elif "push" in cmd_str:
            result.stdout = "Everything up-to-date\n"
        elif "auth status" in cmd_str:
            result.stdout = "Logged in to github.com\n"
        elif "pr create" in cmd_str:
            result.stdout = "https://github.com/testowner/testrepo/pull/15\n"
        else:
            result.stdout = ""

        result.stderr = ""
        return result

    with patch("shutil.which", return_value="/usr/bin/gh"):
        with patch("subprocess.run", side_effect=mock_run):
            with patch.object(
                PRGenerator,
                "generate_pr_content",
                return_value=("feat: api", "PR body content"),
            ):
                res = PRGenerator.create_pr(
                    repo_root=tmp_path,
                    base_branch="main",
                    title="feat: api",
                    body="PR body content",
                    push=True,
                    draft=True,
                )

                assert res.success is True
                assert res.pr_url == "https://github.com/testowner/testrepo/pull/15"
                assert res.web_fallback is False
                assert res.error_message is None


def test_create_pr_fallback_web_url(tmp_path: Path) -> None:
    """Mock gh auth status failure and verify constructed web URL fallback."""

    def mock_run(args, **kwargs):
        cmd = args
        cmd_str = " ".join(cmd)
        result = MagicMock()

        if "branch --show-current" in cmd_str:
            result.returncode = 0
            result.stdout = "feat/fallback-branch\n"
        elif "push" in cmd_str:
            result.returncode = 0
            result.stdout = "Pushed branch\n"
        elif "auth status" in cmd_str:
            result.returncode = 1
            result.stderr = "You are not logged in."
        elif "remote get-url origin" in cmd_str:
            result.returncode = 0
            result.stdout = "https://github.com/my-org/my-project.git\n"
        else:
            result.returncode = 0
            result.stdout = ""

        result.stderr = ""
        return result

    with patch("shutil.which", return_value="/usr/bin/gh"):
        with patch("subprocess.run", side_effect=mock_run):
            with patch.object(
                PRGenerator,
                "generate_pr_content",
                return_value=("feat: fallback", "PR body"),
            ):
                res = PRGenerator.create_pr(
                    repo_root=tmp_path,
                    base_branch="main",
                    push=True,
                )

                assert res.success is True
                assert res.web_fallback is True
                assert (
                    res.pr_url
                    == "https://github.com/my-org/my-project/pull/new/feat/fallback-branch"
                )


def test_create_pr_ssh_remote_url(tmp_path: Path) -> None:
    """Test web URL fallback with git@github.com SSH remote format."""

    def mock_run(args, **kwargs):
        cmd_str = " ".join(args)
        result = MagicMock()
        result.returncode = 0

        if "branch --show-current" in cmd_str:
            result.stdout = "fix/ssh-bug\n"
        elif "push" in cmd_str:
            result.stdout = "Pushed\n"
        elif "remote get-url origin" in cmd_str:
            result.stdout = "git@github.com:cool-user/cool-repo.git\n"
        else:
            result.stdout = ""

        result.stderr = ""
        return result

    with patch("shutil.which", return_value=None):  # No gh CLI installed
        with patch("subprocess.run", side_effect=mock_run):
            with patch.object(
                PRGenerator,
                "generate_pr_content",
                return_value=("fix: ssh", "PR body"),
            ):
                res = PRGenerator.create_pr(
                    repo_root=tmp_path,
                    base_branch="main",
                    push=False,
                )

                assert res.success is True
                assert res.web_fallback is True
                assert res.pr_url == "https://github.com/cool-user/cool-repo/pull/new/fix/ssh-bug"


def test_create_pr_detached_head(tmp_path: Path) -> None:
    """Verifies failure when running on detached HEAD."""

    def mock_run(args, **kwargs):
        cmd_str = " ".join(args)
        result = MagicMock()
        result.returncode = 0
        if "branch --show-current" in cmd_str:
            result.stdout = "\n"  # detached HEAD
        return result

    with patch("subprocess.run", side_effect=mock_run):
        res = PRGenerator.create_pr(repo_root=tmp_path)
        assert res.success is False
        assert "detached HEAD" in (res.error_message or "")


def test_create_pr_same_branch_as_base(tmp_path: Path) -> None:
    """Verifies failure when current branch is already base branch."""

    def mock_run(args, **kwargs):
        cmd_str = " ".join(args)
        result = MagicMock()
        result.returncode = 0
        if "branch --show-current" in cmd_str:
            result.stdout = "main\n"
        return result

    with patch("subprocess.run", side_effect=mock_run):
        res = PRGenerator.create_pr(repo_root=tmp_path, base_branch="main")
        assert res.success is False
        assert "already target base branch" in (res.error_message or "")


def test_create_pr_push_failure(tmp_path: Path) -> None:
    """Verifies failure when git push returns non-zero."""

    def mock_run(args, **kwargs):
        cmd_str = " ".join(args)
        result = MagicMock()
        if "branch --show-current" in cmd_str:
            result.returncode = 0
            result.stdout = "feat/unpushed\n"
        elif "push" in cmd_str:
            result.returncode = 1
            result.stdout = ""
            result.stderr = "remote rejected: master protected"
        else:
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
        return result

    with patch("subprocess.run", side_effect=mock_run):
        with patch.object(
            PRGenerator,
            "generate_pr_content",
            return_value=("feat: unpushed", "PR body"),
        ):
            res = PRGenerator.create_pr(repo_root=tmp_path, push=True)
            assert res.success is False
            assert "Git push failed" in (res.error_message or "")


def test_cli_pr_fill_stdout() -> None:
    """Tests harness-agent pr fill prints populated markdown."""
    runner = CliRunner()
    with patch.object(
        PRGenerator,
        "generate_pr_content",
        return_value=("feat: awesome", "## Description\n\nPopulated content"),
    ):
        result = runner.invoke(main, ["pr", "fill"])
        assert result.exit_code == 0
        assert "## Description" in result.output
        assert "Populated content" in result.output


def test_cli_pr_fill_output_file(tmp_path: Path) -> None:
    """Tests harness-agent pr fill -o output.md writes file correctly."""
    runner = CliRunner()
    output_file = tmp_path / "custom_pr.md"
    with patch.object(
        PRGenerator,
        "generate_pr_content",
        return_value=("feat: awesome", "## Output to file content"),
    ):
        result = runner.invoke(main, ["pr", "fill", "-o", str(output_file)])
        assert result.exit_code == 0
        assert f"PR template written to {output_file}" in result.output
        assert output_file.exists()
        assert output_file.read_text(encoding="utf-8") == "## Output to file content"


def test_cli_pr_create_dry_run() -> None:
    """Tests harness-agent pr create --dry-run."""
    runner = CliRunner()
    with patch.object(
        PRGenerator,
        "generate_pr_content",
        return_value=("feat: dry run feature", "## Dry Run Body"),
    ):
        result = runner.invoke(main, ["pr", "create", "--dry-run"])
        assert result.exit_code == 0
        assert "=== PR Title: feat: dry run feature ===" in result.output
        assert "## Dry Run Body" in result.output


def test_cli_pr_create_end_to_end() -> None:
    """Tests harness-agent pr create invokes PRGenerator.create_pr."""
    runner = CliRunner()
    mock_res = PRResult(
        success=True,
        pr_url="https://github.com/org/repo/pull/123",
        title="feat: end-to-end",
        body="Body",
        web_fallback=False,
    )
    with patch.object(PRGenerator, "create_pr", return_value=mock_res) as mock_create:
        result = runner.invoke(
            main,
            [
                "pr",
                "create",
                "--base",
                "dev",
                "--title",
                "feat: custom",
                "--issue",
                "99",
                "--draft",
            ],
        )
        assert result.exit_code == 0
        assert "Pull Request created successfully" in result.output
        assert "https://github.com/org/repo/pull/123" in result.output
        mock_create.assert_called_once_with(
            base_branch="dev",
            title="feat: custom",
            issue_id="99",
            push=True,
            draft=True,
            custom_description=None,
            critic_review=ANY,
            no_review=False,
        )


def test_cli_pr_create_web_fallback(tmp_path: Path) -> None:
    """Tests harness-agent pr create falls back to web link and draft file."""
    runner = CliRunner()
    mock_res = PRResult(
        success=True,
        pr_url="https://github.com/org/repo/pull/new/feat/branch",
        title="feat: web fallback",
        body="Fallback Body Content",
        web_fallback=True,
    )
    with runner.isolated_filesystem(temp_dir=tmp_path):
        with patch.object(PRGenerator, "create_pr", return_value=mock_res):
            result = runner.invoke(main, ["pr", "create"])
            assert result.exit_code == 0
            assert "gh CLI unavailable or not authenticated" in result.output
            assert "https://github.com/org/repo/pull/new/feat/branch" in result.output
            draft_path = Path(".github") / "PULL_REQUEST_DRAFT.md"
            assert draft_path.exists()
            assert draft_path.read_text(encoding="utf-8") == "Fallback Body Content"


def test_cli_pr_create_failure() -> None:
    """Tests harness-agent pr create with failure exit code and error message."""
    runner = CliRunner()
    mock_res = PRResult(
        success=False,
        error_message="Git push failed: network error",
    )
    with patch.object(PRGenerator, "create_pr", return_value=mock_res):
        result = runner.invoke(main, ["pr", "create"])
        assert result.exit_code != 0
        assert "Failed to create pull request: Git push failed: network error" in result.output


def test_generate_pr_content_narrative_overview(tmp_path: Path) -> None:
    """Verifies automated narrative overview, key changes, and commits/files sections."""
    mock_context = PRContext(
        branch_name="feat/billing-system",
        base_branch="main",
        commits=[
            {
                "hash": "abc1234",
                "message": "feat(billing): implement checkout webhook",
                "sha": "abc1234",
                "subject": "implement checkout webhook",
            },
            {
                "hash": "def5678",
                "message": "fix(billing): handle stripe timeout error",
                "sha": "def5678",
                "subject": "handle stripe timeout error",
            },
        ],
        diff_stat="2 files changed",
        changed_files=["src/billing/webhook.py", "src/billing/stripe.py"],
        inferred_types=["New feature", "Bug fix"],
        python_version="3.11.0",
        os_info="Linux",
    )

    with patch.object(PRGenerator, "collect_git_context", return_value=mock_context):
        title, body = PRGenerator.generate_pr_content(repo_root=tmp_path, base_branch="main")

        assert title == "feat: billing system"
        assert "### Overview" in body
        expected_overview = (
            "This pull request introduces new features and fixes bugs and stability "
            "issues on `feat/billing-system`."
        )
        assert expected_overview in body
        assert "### Key Changes" in body
        assert "- **feat (billing)**: implement checkout webhook" in body
        assert "- **fix (billing)**: handle stripe timeout error" in body
        assert "### Commits:" in body
        assert "- feat(billing): implement checkout webhook" in body
        assert "### Modified files:" not in body


def test_generate_pr_content_with_plan_goal_extraction(tmp_path: Path) -> None:
    """Verifies that plan goal is extracted from .ai/plans/main/ into PR overview."""
    plans_dir = tmp_path / ".ai" / "plans" / "main" / "2026-10-05"
    plans_dir.mkdir(parents=True)
    plan_file = plans_dir / "main_plan_billing_upgrade.md"
    plan_file.write_text(
        "---\n"
        "plan_id: plan_billing_upgrade\n"
        "goal: Upgrade billing engine to support automated Stripe webhooks.\n"
        "---\n\n"
        "# Plan details\n",
        encoding="utf-8",
    )

    mock_context = PRContext(
        branch_name="agent/billing_upgrade_task",
        base_branch="main",
        commits=[{"hash": "111", "message": "feat: billing hook", "sha": "111", "subject": "hook"}],
        diff_stat="1 file changed",
        changed_files=["src/hook.py"],
        inferred_types=["New feature"],
        python_version="3.11.0",
        os_info="Linux",
    )

    with patch.object(PRGenerator, "collect_git_context", return_value=mock_context):
        _, body = PRGenerator.generate_pr_content(repo_root=tmp_path, base_branch="main")

        assert "### Overview" in body
        assert "**Goal**: Upgrade billing engine to support automated Stripe webhooks." in body


def test_generate_pr_content_custom_description(tmp_path: Path) -> None:
    """Verifies that custom_description overrides the automated overview text."""
    mock_context = PRContext(
        branch_name="feat/auth",
        base_branch="main",
        commits=[{"hash": "222", "message": "feat: oauth login", "sha": "222", "subject": "oauth"}],
        diff_stat="1 file changed",
        changed_files=["src/auth.py"],
        inferred_types=["New feature"],
        python_version="3.11.0",
        os_info="Linux",
    )

    custom_desc = "Custom crafted description explaining why this OAuth change was necessary."

    with patch.object(PRGenerator, "collect_git_context", return_value=mock_context):
        _, body = PRGenerator.generate_pr_content(
            repo_root=tmp_path,
            custom_description=custom_desc,
        )

        assert "### Overview" in body
        assert custom_desc in body
        assert "### Key Changes" in body
        assert "- **feat**: oauth login" in body


def test_cli_pr_fill_with_description() -> None:
    """Tests harness-agent pr fill -d embeds custom description."""
    runner = CliRunner()
    with patch.object(
        PRGenerator,
        "generate_pr_content",
        return_value=("feat: awesome", "## Description\n\n### Overview\nMy custom description"),
    ) as mock_gen:
        result = runner.invoke(main, ["pr", "fill", "-d", "My custom description"])
        assert result.exit_code == 0
        assert "My custom description" in result.output
        mock_gen.assert_called_once_with(
            base_branch="main",
            issue_id=None,
            custom_title=None,
            custom_description="My custom description",
        )


def test_cli_pr_create_with_description() -> None:
    """Tests harness-agent pr create -d passes custom description to PRGenerator.create_pr."""
    runner = CliRunner()
    mock_res = PRResult(
        success=True,
        pr_url="https://github.com/org/repo/pull/123",
        title="feat: custom",
        body="Body",
        web_fallback=False,
    )
    with patch.object(PRGenerator, "create_pr", return_value=mock_res) as mock_create:
        result = runner.invoke(
            main,
            [
                "pr",
                "create",
                "--base",
                "main",
                "-d",
                "Feature overview narrative",
            ],
        )
        assert result.exit_code == 0
        mock_create.assert_called_once_with(
            base_branch="main",
            title=None,
            issue_id=None,
            push=True,
            draft=False,
            custom_description="Feature overview narrative",
            critic_review=ANY,
            no_review=False,
        )
