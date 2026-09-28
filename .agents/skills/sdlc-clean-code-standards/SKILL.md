---
name: sdlc-clean-code-standards
description: >-
  Coding standards and PEP 8 formatting guidelines for SDLC implementation.
  Use during coding to ensure high-quality, type-safe, and lint-compliant code.
---

# SDLC Clean Code Standards: Implementation Guidelines

This skill enforces coding quality standards during the implementation phase.

---

## 1. Formatting & Style Rules
- **Black Formatter**: Maximum line length = **100 characters** (defined in `pyproject.toml`).
  - Break long strings or function arguments across multiple lines.
- **isort**: Profile `black`, multi-line output = 3.
- **Flake8**:
  - No unused imports (`F401`).
  - No undefined names (`F821`).
  - No lines exceeding 100 characters (`E501`).
  - No bare `except:` clauses (`E722`).

---

## 2. Code Modularity & Best Practices
- **Single Responsibility Principle**: Each function/class does exactly one thing well.
- **Defensive Error Handling**: Catch specific exceptions (`ValueError`, `FileNotFoundError`), never swallow errors silently.
- **Documentation**: Provide module docstrings and class/method docstrings.
- **Preserve Comments**: Never strip existing comments or unrelated code during file edits.
- **Atomic Edits**: Keep changes minimal, focused solely on the task requirements.

---

## 3. Patch-Only Rule & Tool-Locking Policy ("Patch, Never Regenerate")
- **Mandatory Tooling**: Coders and Reviewers MUST ONLY use patch-based tools (`apply_patch`, `replace_file_content`, or `multi_replace_file_content`) to modify existing files.
- **Tool-Locking Restriction**: Full-file rewrites (e.g. using `write_to_file` on existing files) are strictly prohibited and locked.
- **Hunk-Based Editing**: All changes must be emitted as bounded diff hunks. Do not regenerate surrounding unchanged code.
