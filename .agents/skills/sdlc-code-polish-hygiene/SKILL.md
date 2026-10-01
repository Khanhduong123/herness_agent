---
name: sdlc-code-polish-hygiene
description: >-
  Tool-locked code polish and hygiene audit protocol.
  Enforces Net Line Delta <= 0, strips scaffold comments and debug leaks,
  cleans dead code and unused imports before conventional commit.
---

# Code Polish & Hygiene Auditor

## Overview
This skill provides a strict protocol for code polishing and hygiene auditing prior to final submission or conventional commit. It ensures that the codebase remains clean, lean, and free of temporary artifacts introduced during development.

## 1. Tool-Locked Execution
- **Strict Surgical Edits:** You MUST use surgical edit tools (`replace_file_content` / `multi_replace_file_content` / `apply_patch`).
- **No Full-File Regeneration:** Whole-file overwriting/regeneration is strictly prohibited to prevent context rot, accidental deletion of unrelated docstrings, and loss of functional blocks.

## 2. Hygiene Rules Checklist
Before finalizing a task, you must audit the code and apply the following hygiene rules:
- [ ] **Strip Temporary Debug Logs:** Remove all temporary logging statements (e.g., `print()`, `console.log()`, temporary breakpoint traces) introduced during debugging.
- [ ] **Strip Scaffold Notes:** Remove task-specific or transient comments (e.g., `# TODO handled by orchestrator`, `# DEBUG`, internal task IDs).
- [ ] **Strip Prompt Echoes:** Ensure no markdown, AI prompt fragments, or meta-commentary have leaked into the code comments.
- [ ] **Clean Dead Code:** Remove unreachable code, unused private functions, and obsolete variables.
- [ ] **Clean Unused Imports:** Remove unused imports (e.g., ensuring `flake8 F401` compliance).
- [ ] **Preserve Unrelated Documentation:** Do NOT delete existing, unrelated comments, docstrings, or essential utility code.

## 3. The Net Line Delta Rule
- **Rule (Net Line Delta <= 0):** The net lines added during the polish phase MUST be <= 0.
- **Rationale:** Polishing is meant to cut bloat, remove artifacts, and consolidate code. It should never expand the codebase size. If your polish phase results in a positive net line delta, you are likely introducing scope creep or unnecessary verbosity and must revert.
