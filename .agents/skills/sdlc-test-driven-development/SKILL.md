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
- All test files reside under `tests/` with the prefix `test_*.py`.
- Group tests logically by unit or scenario:
  - `test_models.py`: Schema validation, serialization, edge cases.
  - `test_runner.py`: Process spawning, timeout handling, CLI arg building.
  - `test_orchestrator.py`: DAG resolution, cycle detection, failure isolation.

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
