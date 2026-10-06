---
name: sdlc-subtask-specifier
description: >-
  Generates comprehensive Sub-Specifications (sub-spec) for decomposed tasks before Orchestrator dispatch.
  Enforces SDLC rigor, risk assessment, criticality, function signatures, test cases, and status lifecycle.
---

# SDLC Sub-Specifier: Subtask Technical Specification Protocol

This skill enforces a mandatory software engineering protocol: **Before the Central Orchestrator dispatches any subtask to Worker Agents (Coder / Tester)**, the Orchestrator (or Researcher / Architect Agent) **must draft a formal Technical Sub-Specification (`sub-spec`)**.

The Sub-Spec serves as a strict technical contract between the Orchestrator and the executing Worker. It prevents hallucinations, architectural drift, out-of-scope modifications, and interface breakage.

---

## 1. Mandatory Sub-Spec Components

Every Sub-Spec must be populated with all 8 core SDLC dimensions:

```text
+------------------------------------------------------------------------+
|                             SUB-SPEC SCHEMA                            |
+------------------------------------------------------------------------+
| 1. METADATA & STATUS (Plan ID, Task ID, Role, Status)                  |
| 2. SCOPE & LOCKED FILES (Modifiable Files vs Locked Files)             |
| 3. CRITICALITY LEVEL & RISK ASSESSMENT (Blast Radius & Failure Points) |
| 4. PATCH CONTRACTS & INTERFACE SPECS (Signatures, Types, Patch Rules)  |
| 5. EDGE CASES & BOUNDARY CONDITIONS (Scenarios, Handling, Assertions)  |
| 6. TEST CASE SPECIFICATIONS (Happy Path, Boundary, Exception Paths)    |
| 7. EXACT PYTEST & CLI COMMANDS (Local Commands for Worker Execution)   |
| 8. VERIFICATION & FAILURE ROLLBACK (SDLC Quality Gates, Rollback)      |
+------------------------------------------------------------------------+
```

---

## 2. Dimension Definitions & Requirements

### 2.1. Criticality Level (`CriticalityLevel`)
- **`CRITICAL`**: Fundamental core infrastructure, data integrity, security, or a blocker for all downstream tasks.
- **`HIGH`**: Key feature implementation required for primary functional goals.
- **`MEDIUM`**: Secondary feature, performance optimization, non-blocking enhancement.
- **`LOW`**: Minor refactor, docstring additions, formatting, or variable cleanup.

### 2.2. Scope & Locked Files
Every Sub-Spec MUST explicitly distinguish between allowed targets and protected modules:
- **`Modifiable Files`**: Strict list of files or directories the worker is authorized to edit.
- **`Locked Files`**: Modules or files that the worker is strictly forbidden from modifying (e.g. evaluation gates, research pipelines, root configurations).

### 2.3. Risk Assessment & Blast Radius (`RiskLevel`)
- **Risk Level:** `LOW` | `MEDIUM` | `HIGH`
- **Failure Points & Error Vulnerabilities:** Specific failure modes (e.g., race conditions, timeouts, schema mismatch).
- **Blast Radius:** Scope of affected modules, public classes, or external files.
- **Mitigation & Rollback Strategy:** Defensive measures (e.g., fallback values, timeouts, try/except guards, rollback steps).

### 2.4. Lifecycle Status (`SpecStatus`)
- **`DRAFT`**: Sub-Spec is being drafted by Orchestrator/Researcher.
- **`REVIEWED`**: Technical feasibility reviewed and validated.
- **`APPROVED`**: Ready for Coder Agent execution.
- **`IN_PROGRESS`**: Worker Agent actively implementing code.
- **`TESTING`**: Tester Agent executing test suite and quality gates.
- **`COMPLETED`**: 100% test cases passed and merged.
- **`BLOCKED`**: Execution paused due to upstream failure or missing dependency.

### 2.5. Patch Contracts & Interface Definitions (`FunctionSpec`)
Every function, method, or class interface must be explicitly documented prior to coding:
```python
def function_name(param_1: str, param_2: Optional[int] = None) -> ReturnType:
    """Concise docstring explaining the function's purpose.

    Args:
        param_1 (str): Description, validation rules (non-empty, format).
        param_2 (Optional[int]): Description, default value.

    Returns:
        ReturnType: Explicit return type (prefer Pydantic BaseModel).

    Raises:
        ValueError: When param_1 fails validation constraints.
        FileNotFoundError: When target file is missing.
    """
```
- **Rule**: Never use untyped parameters or uncontrolled `Any`. 100% parameter and return types must be explicitly typed.
- **Patch-Only Rule Reminder**: For existing files, workers MUST apply minimal diff hunks using patch tools (`apply_patch`, `replace_file_content`). Full-file rewrites/overwrites are strictly prohibited.

### 2.6. Edge Cases & Boundary Conditions
Every Sub-Spec MUST detail at least 3-5 concrete edge cases and boundary conditions. Each entry must clearly state:
1. **Failure Scenario**: Specific abnormal or edge condition (e.g., missing file/path, empty strings, None/null inputs, Windows `\` vs POSIX `/` separators, CRLF vs LF line endings, subprocess timeouts, permission errors, concurrent task access).
2. **Handling Logic**: Expected defensive programming pattern (graceful fallback, default value assignment, specific custom exception raising, path normalization via `Path`).
3. **Verification Method / Test Assertion**: Specific test check (e.g. `pytest.raises(FileNotFoundError)`, assert normalized path, mock timeout).

### 2.7. Test Case Specifications (`TestCaseSpec`)
Concrete test scenarios must be defined before code implementation:
1. **TC-01 (Happy Path):** Valid inputs returning exact expected outputs.
2. **TC-02 (Boundary & Edge Cases):** Empty collections, null/None, empty strings, zero values, max thresholds.
3. **TC-03 (Exception & Error Paths):** Invalid arguments raising expected exceptions (`pytest.raises`).
4. **TC-04 (Regression Guard):** Validating that existing module features remain functional.

### 2.8. Exact Pytest & CLI Commands
Every Sub-Spec MUST provide exact, copy-pasteable commands for the worker to run locally (e.g., `conda run -n pytorch pytest tests/test_foo.py`).

### 2.9. Verification & Failure Rollback
- Maximum **3 iteration cycles** between Coder and Critics/Pytest.
- If defects or test failures persist after 3 remediation cycles, the subtask must be aborted and rolled back:
  1. Dump git diff and traceback to `.ai/failures/<task_id>_<timestamp>.log`.
  2. Terminate the Herdr worker pane.
  3. Remove the abandoned worktree (`git worktree remove --force .worktrees/agent/<task_id>`) and branch (`git branch -D agent/<task_id>`).
  4. Escalate to the human User.

### 2.10. SDLC Quality Gate Criteria
- [ ] Explicit `## Scope & Locked Files` section present.
- [ ] Explicit `## Patch Contracts & Interface Definitions` section present.
- [ ] Explicit `## Edge Cases & Boundary Conditions` section includes at least 3-5 concrete scenarios.
- [ ] Black line length = **100 characters** max.
- [ ] Imports ordered by `isort` (`profile = "black"`).
- [ ] Zero `flake8` lint errors (`E501`, `F401`, `F821`).
- [ ] 100% pass rate in pytest (`conda run -n pytorch pytest`).
- [ ] No unhandled exceptions or silent error swallowing.
- [ ] Strictly follow "Patch, never regenerate" rule (use diff hunks, no full-file rewrites).

### 2.11. Storage & Approval Workflow
- **Storage**: The Orchestrator MUST save every generated `sub-spec` locally as a Markdown file in the project's dedicated plan directory: `.ai/plans/subtasks/YYYY-MM-DD/[plan_id]/subtask_01_[feature].md` using 2-digit zero-padded numbers (`01`, `02`, ..., `10`). This isolates tasks per plan, prevents filename collisions across concurrent or sequential plans, and guarantees strictly numeric sorting.
- **User Approval**: After saving the file, the Orchestrator MUST ask the User for approval (e.g., *"Please review the sub-spec at `.ai/plans/subtasks/YYYY-MM-DD/[plan_id]/subtask_01_[feature].md`"*).
- **Execution**: The Orchestrator MUST NOT spawn the Sub-Agent until the User explicitly approves the Sub-Spec.

---

## 3. Sub-Spec Markdown Template

```markdown
# SUB-SPEC: [Task-ID] - [Task Name]

- **Plan ID:** `[plan_id]`
- **Task ID:** `[task_id]`
- **Target Feature Branch:** `feat/[feature_name]`
- **Isolated Worktree Branch:** `agent/[task_id]`
- **Assigned Worker Role:** Coder (`worker_[task_id]`)
- **Status Lifecycle:** `PENDING`

---

## 1. Scope & Locked Files
- **Modifiable Files**:
  - `path/to/modifiable_file.py`
  - `tests/test_modifiable_file.py`
- **Locked Files**:
  - `src/harness_agent/evaluation/*`
  - `src/harness_agent/research/*`

---

## 2. Requirements & Deliverables
Detailed bulleted breakdown of requirements and expected functional changes.

---

## 3. Patch Contracts & Interface Definitions
### Function: `function_name`
- **Location:** `src/harness_agent/module.py`
- **Signature:** `def function_name(param1: str, param2: Optional[int] = None) -> ReturnType:`
- **Purpose:** Brief description.
- **Raises:** `ValueError` if param1 is invalid.
- **Patch Rule:** Use minimal diff hunks via `replace_file_content` / `apply_patch`. Full-file overwrite is prohibited.

---

## 4. Edge Cases & Boundary Conditions
1. **Missing or Non-Existent File/Directory**:
   - **Handling Logic:** Check path existence; raise `FileNotFoundError` with clear message.
   - **Verification:** Unit test asserts `pytest.raises(FileNotFoundError)`.
2. **Empty String or Null Arguments**:
   - **Handling Logic:** Validate input stripping; raise `ValueError` or fallback gracefully.
   - **Verification:** Assert exception or default return value.
3. **Cross-Platform Path Inconsistencies**:
   - **Handling Logic:** Normalize paths using `pathlib.Path` or `.as_posix()`.
   - **Verification:** Assert path resolution on both POSIX and Windows.

---

## 5. Test Case Specifications (QA Acceptance)
| Test ID | Scenario | Input | Expected Output |
| :--- | :--- | :--- | :--- |
| **TC-01** | Happy path execution | `param="valid"` | Expected result |
| **TC-02** | Empty input validation | `param=""` | Raises `ValueError` |
| **TC-03** | Boundary condition handling | `param="edge"` | Handled cleanly |

---

## 6. Exact Pytest & CLI Commands
- `conda run -n pytorch pytest tests/test_module.py`
- `conda run -n pytorch pytest tests/`

---

## 7. Verification & Failure Rollback
- Maximum 3 iteration cycles between Coder and Critics/Pytest.
- If defects persist after 3 cycles, terminate worker pane, remove worktree `git worktree remove --force .worktrees/agent/[task_id]`, delete branch `git branch -D agent/[task_id]`, and log error to `.ai/failures/[task_id]_[timestamp].log`.

---

## 8. SDLC Quality Gate Checklist
- [ ] Complete type annotations adhering to Python 3.10+.
- [ ] 100% pass rate in `conda run -n pytorch pytest`.
- [ ] No unused imports or dead code.
- [ ] Patch-only rule verified (no full-file overwrite).
```
