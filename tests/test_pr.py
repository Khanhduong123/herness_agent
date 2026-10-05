"""Unit tests for Pull Request template engine and context collector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from harness_agent.core.pr import DEFAULT_PR_TEMPLATE, PRContext, PRGenerator


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

        assert title == "feat: add feature"
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
