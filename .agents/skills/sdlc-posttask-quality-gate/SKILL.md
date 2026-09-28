---
name: sdlc-posttask-quality-gate
description: >-
  Mandatory quality gate verification after completing code edits in SDLC.
  Use after implementing features to run pytest, linters, and inspect git diff before completion.
---

# SDLC Post-Task Quality Gate: Verification Checklist

This skill defines the mandatory verification gates that must pass **AFTER** completing any code task.

---

## 1. Test Suite Verification (100% Pass Required)
- Run the full pytest suite in the `pytorch` environment:
  ```powershell
  conda run -n pytorch pytest
  ```
- **Rule**: If even 1 test fails, the task CANNOT be marked complete. Debug and resolve all failures first.

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

## 3. Git Diff Inspection
- Run `git diff` to review all modified lines.
- Verify:
  - No leftover `print()` debug statements or temporary scratch files.
  - No secrets, tokens, or hardcoded passwords.
  - Formatting matches the surrounding codebase.
  - **Patch-Only Compliance**: Verify the diff is minimal and atomic; ensure no existing files were rewritten in full or had unrelated lines modified.
