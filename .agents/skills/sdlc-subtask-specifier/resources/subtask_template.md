---
plan_id: [plan_id]
task_id: [task_id]
---
# Sub-Task Specification: [task_id] - [Task Name]

## [ROLE ANCHOR]
- **Assigned Role:** [Leaf Coder Worker / QA Tester / Specifier]
- **Task Identifier:** `[task_id]` - [Task Name]
- **Target Feature Branch:** `feat/[feature_name]`
- **Isolated Worktree Branch:** `agent/[task_id]`
- **Criticality Level:** [CRITICAL | HIGH | MEDIUM | LOW]
- **Status Lifecycle:** `PENDING`

---

## 1. Scope & File Boundaries (Mandatory Compliance)
- **Modifiable Files (Explicitly authorized):**
  - `src/harness_agent/path/to/module.py`
  - `tests/unit/test_module.py`
- **Locked Files (Strictly forbidden to modify):**
  - `src/harness_agent/evaluation/*`
  - `AGENTS.md`
- **Execution Prohibitions:**
  - DO NOT use `ManageTask` or scheduling loops (`schedule`).
  - DO NOT run background processes; all execution must be synchronous and blocking.
  - DO NOT overwrite entire existing files (patch-only rule via `replace_file_content` / `apply_patch`).
  - DO NOT call `invoke_subagent` or `define_subagent`.

---

## 2. Detailed Implementation Instructions
<!-- Step-by-step technical requirements and deliverables for this subtask -->
1.
2.

---

## 3. Patch Contracts & Interface Definitions
### Function / Class: `function_name`
- **Location:** `src/harness_agent/path/to/module.py`
- **Signature:**
  ```python
  def function_name(param_1: str, param_2: Optional[int] = None) -> ReturnType:
      """Concise summary of function behavior.

      Args:
          param_1 (str): Description and validation rules.
          param_2 (Optional[int]): Description and default value.

      Returns:
          ReturnType: Explicit return type (prefer Pydantic BaseModel).

      Raises:
          ValueError: When input fails validation constraints.
      """
  ```
- **Patch Rule:** Minimal diff hunks only. Full-file overwrites are strictly tool-locked.

---

## 4. Edge Cases & Boundary Conditions
<!-- Detail at least 3-5 concrete edge cases per AGENTS.md requirements -->
1. **[Edge Case 1 - Missing files / Uninitialized configuration]**:
   - *Handling Logic:* Check file existence before reading; raise descriptive `FileNotFoundError`.
   - *Test Assertion:* `pytest.raises(FileNotFoundError)`
2. **[Edge Case 2 - Cross-platform path separators (Windows `\` vs POSIX `/`)]**:
   - *Handling Logic:* Normalize paths using `pathlib.Path` or `.as_posix()`.
   - *Test Assertion:* Assert path normalization on both Windows and Linux paths.
3. **[Edge Case 3 - Null, empty strings, or boundary inputs]**:
   - *Handling Logic:* Validate and strip strings; provide defensive defaults or raise `ValueError`.
   - *Test Assertion:* Assert graceful fallback or expected exception.

---

## 5. Test Case Specifications (QA Acceptance)
| Test ID | Category | Target Directory | Scenario | Input | Expected Output |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TC-01** | Unit Test | `tests/unit/` | Happy path execution | `param="valid"` | Expected return value |
| **TC-02** | Unit Test | `tests/unit/` | Empty string validation | `param=""` | Raises `ValueError` |
| **TC-03** | Integration Test | `tests/integration/` | End-to-end component flow | `...` | Test passes |

---

## 6. Exact Pytest & Local CLI Commands
```powershell
conda run -n pytorch pytest tests/unit/test_[module].py
```

---

## 7. Definition of Done & Completion Signal
- **100% Pytest Pass:** All assigned unit and integration tests must pass cleanly.
- **Completion Contract:** Worker writes `.ai/status/[task_id].complete` and outputs `[WORKER_COMPLETED]` at the end of execution.
- **Rollback Protocol:** Maximum 3 remediation loops between Coder and Critics. If unresolved after 3 cycles, terminate the worker pane, remove the worktree, and escalate to the user.
