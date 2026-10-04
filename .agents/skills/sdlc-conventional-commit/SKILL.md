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
