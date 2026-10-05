---
name: sdlc-conventional-commit
description: >-
  Git version control and Conventional Commits workflow for SDLC tasks.
  Use when staging, inspecting, and committing code changes directly via agy-cli terminal.
---

# SDLC Conventional Commit: Version Control Guidelines

This skill guides the final staging and commit phase of the SDLC workflow.

---

## 1. Commit Directives (Via agy-cli Terminal Only)
- All Git operations must be executed directly in the terminal via `agy-cli`.
- Never bypass pre-commit hooks (`--no-verify` is strictly forbidden).
- **CRITICAL - NO AUTOMATED MERGING OR COMMITTING TO PROTECTED BRANCHES**:
  - Protected branches: `main`, `master`, `dev`, `develop`.
  - All AI agents and automated scripts are **STRICTLY PROHIBITED** from merging or committing into `main` or `dev`.
  - Merging into `main` or `dev` is exclusively reserved for the human user.
  - Pre-commit hook `no-commit-to-branch` will abort any attempt to commit directly on protected branches.

---

## 2. Conventional Commit Format
```text
<type>(<optional scope>): <short description in present tense>

[optional body explaining motivation and non-obvious details]
```

### Commit Types:
- **`feat`**: A new feature or major capability.
- **`fix`**: A bug fix.
- **`test`**: Adding missing tests or correcting existing tests.
- **`refactor`**: Code change that neither fixes a bug nor adds a feature.
- **`docs`**: Documentation-only changes.
- **`style`**: Changes that do not affect code meaning (formatting, whitespace).
- **`chore`**: Maintenance, build system, or dependencies updates.

---

## 3. Staging & Execution Workflow
1. Check changed files:
   ```powershell
   git status
   ```
2. Stage modified files:
   ```powershell
   git add <specific files>
   ```
3. Commit with compliant message:
   ```powershell
   git commit -m "feat(scope): concise explanation of change"
   ```
4. Confirm pre-commit hooks pass cleanly.
5. Push branch to remote:
   ```powershell
   git push -u origin <branch-name>
   ```
6. Create Pull Request targeting `main` (or `dev`) using the automated PR tool or GitHub CLI:
   ```powershell
   # Recommended: Automatically populate template from commits/tests and create PR
   harness-agent pr create --base main

   # Or manual GitHub CLI creation:
   gh pr create --base main --head <branch-name> --title "feat(scope): concise explanation" --body "Summary of changes"
   ```
7. Provide the resulting PR link directly to the user.

---

## 4. Remote Push & Pull Request Protocol
- **Automatic Push**: After committing changes to a feature or fix branch, the agent **MUST automatically push** the branch to the remote repository.
- **Pull Request Creation & Template Compliance**: The agent **MUST create a Pull Request** targeting `main` (or `dev`) using `harness-agent pr create --base main` (or GitHub CLI `gh`).
  - The PR body **MUST strictly populate `.github/pull_request_template.md`** (Description, Type of change, Test Configuration, Test Evidence / console output, and Checklist). `harness-agent pr create` does this automatically.
- **User Notification**: The agent **MUST output the PR URL** to the user so the human reviewer can inspect and merge. Automated merging to protected branches remains strictly prohibited.
