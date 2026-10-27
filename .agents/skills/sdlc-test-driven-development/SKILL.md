---
name: sdlc-test-driven-development
description: >-
  Testing and QA automation methodology for SDLC tasks.
  Use when writing unit tests, regression tests, or integration tests with pytest.
---

# SDLC Test-Driven Development (TDD) & Quality Assurance

This skill defines the testing procedures required for every code change.

---

## 1. Test Organization

All test files MUST reside under subdirectories within `tests/` with the prefix `test_*.py`. Test files must NEVER be placed directly in the root of `tests/`.

### 1.1 Tri-Layer Test Verification Contract Matrix
| Layer | Target / Type | Scope & Constraints | External Dependencies & Mocking |
| :--- | :--- | :--- | :--- |
| **Layer 1** | **Unit Tests** (`tests/unit/`) | Pure logic, parsing, serialization, math, single unit isolation | Max 2 mocks per test. Never mock internal units or write tautological assertions. |
| **Layer 2** | **Integration Tests** (`tests/integration/`) | Multi-module flows, component integration, CLI commands, real filesystem/DB operations | Hard ban on mocking SQLite, embedded DBs, vector stores, or filesystems. Real `tmp_path` filesystems or temporary SQLite instances required. |
| **Layer 3** | **Deterministic Smoke Probe** | Process-level executable verification | Out-of-process subprocess launch (`conda run -n pytorch harness-agent smoke`). Zero mocking. |

### 1.2 Directory Structure
- **`tests/unit/`**: Testing single units, pure functions, Pydantic models, schema validation, fast in-memory operations, and fully mocked dependencies (max 2 mocks).
  - Examples: `test_models.py` (schemas, validation), `test_diff_parser.py` (pure string parsing).
- **`tests/integration/`**: Multi-module orchestration, CLI commands, process spawning, Herdr socket interactions, filesystem operations, and end-to-end workflows.
  - Examples: `test_runner.py` (process spawning, timeouts), `test_orchestrator.py` (DAG resolution, cycle detection, task dispatch).

### 1.3 Test Category Decision Matrix
| Characteristic | Unit Test (`tests/unit/`) | Integration Test (`tests/integration/`) |
| :--- | :--- | :--- |
| **Scope** | Single class, function, or data model | Multiple interacting modules, subsystem flows |
| **Dependencies** | Max 2 external mocks or pure in-memory | Real or mocked external processes, sockets, CLI; REAL filesystems & DBs |
| **Speed** | Milliseconds (< 100ms per test) | Seconds (< 5s per test) |
| **External I/O** | None (no subprocesses, no network sockets) | Subprocesses, file trees, multiplexer sockets |

### 1.4 Tie-Breaking Rule for Hybrid Tests
If a test contains both unit logic and multi-component or CLI interactions:
- Classify the test as an **Integration Test** (`tests/integration/`).
- Decouple isolated unit assertions into `tests/unit/` where feasible.

### 1.5 Mandatory Test Category Declaration
Every sub-agent and developer writing or modifying tests MUST explicitly declare the test category (`Unit Test` or `Integration Test`) and target directory (`tests/unit/` or `tests/integration/`) in their task reports and specifications.

---

## 2. Test Coverage Requirements
1. **Happy Path**: Verify the feature works as intended with expected inputs.
2. **Edge Cases**: Empty lists, None values, boundaries, zero values.
3. **Error Paths & Exceptions**: Verify invalid inputs trigger appropriate exceptions (e.g. `pytest.raises(ValueError)`).
4. **Asynchronous Testing**: Use `@pytest.mark.asyncio` for all coroutines.

---

## 3. Mocking & Isolation

- Use `unittest.mock.AsyncMock` or `MagicMock` to isolate network, external CLI, or slow subprocess calls.
- Never mock the actual class or unit under test.
- Limit mocks in Layer 1 unit tests to a maximum of 2 mocks per test function.

### 3.1 Anti-Patterns & Mocking Prohibitions
- **No Tautological Mock Assertions**: Prohibit asserting the exact mocked return value without exercising underlying domain logic (e.g., mocking `fn` to return `42` and only asserting `assert fn() == 42`). Tests must assert behavior and state transformations.
- **Hard Ban on Mocking Local Storage & DBs**: Prohibit mocking SQLite, vector stores, embedded databases, or file I/O in integration tests.
- **Mandatory Real Fixtures**:
  - Always use `tmp_path` pytest fixture for disk operations and file writes/reads.
  - Use SQLite `:memory:` databases or temporary file-backed SQLite instances created within `tmp_path` for all database operations.
