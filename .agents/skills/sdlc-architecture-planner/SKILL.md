---
name: sdlc-architecture-planner
description: >-
  Architectural design and planning skill for SDLC tasks.
  Use when designing new modules, APIs, schemas, or complex workflows before implementation.
---

# SDLC Architecture Planner: Design & Interface Definition

This skill guides the design phase before writing application code.

---

## 1. Interface-First Design
1. **Schema & Contract Definition**:
   - Always define data models with Pydantic v2 before writing execution logic.
   - Use explicit field types, default values, and descriptive docstrings:
     ```python
     from pydantic import BaseModel, Field

     class TaskSpec(BaseModel):
         name: str = Field(..., description="Unique task name")
         timeout: int = Field(default=60, description="Execution timeout in seconds")
     ```
2. **Type Safety & Typing**:
   - Enforce Python 3.10+ typing (`from __future__ import annotations`, `Optional`, `Dict`, `List`, `|`).
   - Ensure all public functions have strict parameter types and return type annotations.

---

## 2. Central Orchestrator Alignment
- If the feature involves multi-agent coordination:
  - Map each subtask to a specific role (`RESEARCHER`, `CODER`, `TESTER`, `REVIEWER`).
  - Declare dependency links (`depends_on`) to form a clean DAG without cycles.
  - Define evaluation checks (`TaskCheck`) to validate outputs programmatically.

---

## 3. Backward Compatibility & Non-Breaking Evolution
- Never alter existing public function signatures without updating call sites and tests.
- Deprecate gracefully when replacing old interfaces.
