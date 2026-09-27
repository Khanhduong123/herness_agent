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

Every Sub-Spec must be populated with all 6 core SDLC dimensions:

```text
+------------------------------------------------------------------------+
|                             SUB-SPEC SCHEMA                            |
+------------------------------------------------------------------------+
| 1. METADATA & STATUS (Task ID, Name, Role, Spec Status)                |
| 2. CRITICALITY LEVEL (CRITICAL | HIGH | MEDIUM | LOW)                  |
| 3. RISK ASSESSMENT (Risk Level, Failure Points, Blast Radius, Plan)    |
| 4. FUNCTION & INTERFACE SPECS (Signatures, Parameters, Return Types)   |
| 5. TEST CASE SPECIFICATIONS (Happy Path, Edge Cases, Exception Paths)  |
| 6. SDLC ACCEPTANCE GATES (Black 100 cols, isort, flake8, 100% pytest)  |
+------------------------------------------------------------------------+
```

---

## 2. Dimension Definitions & Requirements

### 2.1. Criticality Level (`CriticalityLevel`)
- **`CRITICAL`**: Fundamental core infrastructure, data integrity, security, or a blocker for all downstream tasks.
- **`HIGH`**: Key feature implementation required for primary functional goals.
- **`MEDIUM`**: Secondary feature, performance optimization, non-blocking enhancement.
- **`LOW`**: Minor refactor, docstring additions, formatting, or variable cleanup.

### 2.2. Risk Assessment & Blast Radius (`RiskLevel`)
- **Risk Level:** `LOW` | `MEDIUM` | `HIGH`
- **Failure Points & Error Vulnerabilities:** Specific failure modes (e.g., race conditions, timeouts, schema mismatch).
- **Blast Radius:** Scope of affected modules, public classes, or external files.
- **Mitigation & Rollback Strategy:** Defensive measures (e.g., fallback values, timeouts, try/except guards, rollback steps).

### 2.3. Lifecycle Status (`SpecStatus`)
- **`DRAFT`**: Sub-Spec is being drafted by Orchestrator/Researcher.
- **`REVIEWED`**: Technical feasibility reviewed and validated.
- **`APPROVED`**: Ready for Coder Agent execution.
- **`IN_PROGRESS`**: Worker Agent actively implementing code.
- **`TESTING`**: Tester Agent executing test suite and quality gates.
- **`COMPLETED`**: 100% test cases passed and merged.
- **`BLOCKED`**: Execution paused due to upstream failure or missing dependency.

### 2.4. Function & Interface Specifications (`FunctionSpec`)
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

### 2.5. Test Case Specifications (`TestCaseSpec`)
Concrete test scenarios must be defined before code implementation:
1. **TC-01 (Happy Path):** Valid inputs returning exact expected outputs.
2. **TC-02 (Boundary & Edge Cases):** Empty collections, null/None, empty strings, zero values, max thresholds.
3. **TC-03 (Exception & Error Paths):** Invalid arguments raising expected exceptions (`pytest.raises`).
4. **TC-04 (Regression Guard):** Validating that existing module features remain functional.

### 2.6. SDLC Quality Gate Criteria
- [ ] Black line length = **100 characters** max.
- [ ] Imports ordered by `isort` (`profile = "black"`).
- [ ] Zero `flake8` lint errors (`E501`, `F401`, `F821`).
- [ ] 100% pass rate in pytest (`conda run -n pytorch pytest`).
- [ ] No unhandled exceptions or silent error swallowing.

### 2.7. Storage & Approval Workflow
- **Storage**: The Orchestrator MUST save every generated `sub-spec` locally as a Markdown file in the project's `.ai/plan/` directory (e.g., `.ai/plan/subtask_01_feature.md`).
- **User Approval**: After saving the file, the Orchestrator MUST ask the User for approval (e.g., *"Please review the sub-spec at `.ai/plan/subtask_01_feature.md`"*).
- **Execution**: The Orchestrator MUST NOT spawn the Sub-Agent until the User explicitly approves the Sub-Spec.

---

## 3. Sub-Spec Markdown Template

```markdown
# SUB-SPEC: [Task-ID] - [Task Name]

## 1. Environment & Setup (MANDATORY FIRST STEP)
- **Worktree Name:** `agent/[Task-ID]`
- **Command:** The Sub-Agent MUST start by running `herdr workspace create agent/[Task-ID]` via terminal, and then `cd` into it to do the work.

## 2. Overview & Metadata
- **Task ID:** subtask_01_feature_name
- **Assigned Role:** coder
- **Criticality:** HIGH
- **Status:** APPROVED
- **Depends On:** []

## 3. Risk Assessment
- **Risk Level:** MEDIUM
- **Blast Radius:** `src/harness_agent/runner.py` only
- **Failure Vulnerability:** Subprocess timeout when running commands on Windows.
- **Mitigation Strategy:** Implement `asyncio.wait_for` with explicit timeout handling.

## 4. Function & Interface Specifications
### Function: `build_command`
- **Location:** `src/harness_agent/runner.py`
- **Signature:** `def build_command(prompt: str, task: Optional[Task] = None) -> List[str]:`
- **Purpose:** Constructs command-line arguments for agy CLI invocation.
- **Raises:** `ValueError` if prompt is empty.

## 5. Test Case Specifications (QA Acceptance)
| Test ID | Scenario | Input | Expected Output |
| :--- | :--- | :--- | :--- |
| **TC-01** | Happy path command building | `prompt="hello"` | `['agy', '--print', 'hello', ...]` |
| **TC-02** | Empty prompt validation | `prompt=""` | Raises `ValueError` |
| **TC-03** | Sandbox flag injection | `extra_flags=['--sandbox']` | Command contains `'--sandbox'` |

## 6. SDLC Quality Gate Checklist
- [ ] Complete type annotations adhering to Python 3.10+.
- [ ] 100% pass rate in `conda run -n pytorch pytest`.
- [ ] No unused imports or dead code.
```
