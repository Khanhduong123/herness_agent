---
name: sdlc-posttask-quality-gate
description: >-
  Mandatory quality gate verification after completing code edits in SDLC.
  Use after implementing features to run pytest, linters, and inspect git diff before completion.
---

# SDLC Post-Task Quality Gate: Verification Checklist

This skill defines the mandatory verification gates that must pass **AFTER** completing any code task.

---

## 1. Test Suite & Full Regression Verification (100% Pass Required)
- Run the full pytest suite covering all modules in the `pytorch` environment:
  ```powershell
  conda run -n pytorch pytest tests/
  ```
- **Rule**: If even 1 test fails, the task CANNOT be marked complete. Running only isolated new test files is prohibited; full regression verification across `tests/` is mandatory. Debug and resolve all failures first.

---

## 2. Code Quality & Linting Verification
- Execute static analysis and formatting checks:
  ```powershell
  # Black formatting check
  conda run -n pytorch black --check src tests

  # isort import order check
  conda run -n pytorch isort --check-only src tests

  # Flake8 style and line length check
  conda run -n pytorch flake8 src tests
  ```

---

## 3. Mechanical Symbol & Interface Binding Verification (Truthfulness Gate)
1. **Import & Symbol Resolution:**
   - Every `import` and `from ... import ...` statement in modified files must resolve to
     an installed package or an existing workspace file.
   - Every public symbol called from internal modules must exist in the target module's AST or
     `__all__`.
2. **Dangling Symbol Policy:**
   - Any reference to an undefined or unexported function/class is classified as `CRITICAL`
     (phantom symbol hallucination).
   - Task execution is blocked until Coder either provides the missing definition or corrects
     the call.

---

## 4. Git Diff Inspection
- Run `git diff` to review all modified lines.
- Verify:
  - No leftover `print()` debug statements or temporary scratch files.
  - No secrets, tokens, or hardcoded passwords.
  - Formatting matches the surrounding codebase.
  - **Patch-Only Compliance**: Verify the diff is minimal and atomic; ensure no existing files were rewritten in full or had unrelated lines modified.

---

## 5. Merge Back, Full Regression & Pull Request Creation Gate
After committing in the subtask worktree and completing initial quality checks:
1. **Merge Back to Feature Branch**:
   Merge the subtask branch into the parent feature branch:
   ```powershell
   git merge --no-ff agent/<task_id>
   ```
2. **Execute Full Regression Suite**:
   Verify that all integration and regression tests pass cleanly on the feature branch:
   ```powershell
   conda run -n pytorch pytest tests/
   ```
3. **Execute Automated Adversarial Critics Gate**:
   Verify that all 3 adversarial critics (Security, Performance, Requirements) approve the diff:
   ```powershell
   conda run -n pytorch harness-agent review --base main
   ```
   **Rule**: PR creation is strictly blocked if any critic rejects the changes.
4. **Push Feature Branch to Remote**:
   The agent **MUST automatically push** the feature branch to the remote repository:
   ```powershell
   git push -u origin feat/<feature_name>
   ```
5. **Create Pull Request**:
   The agent **MUST create a Pull Request** targeting `main` (or `dev`) using the automated CLI tool:
   ```powershell
   conda run -n pytorch harness-agent pr create --base main
   ```
6. **Report PR Link to User**:
   The agent **MUST provide the resulting Pull Request URL directly to the user** in the response. Under no circumstances should the agent merge the PR into protected branches (merging remains exclusively the human user's authority).
