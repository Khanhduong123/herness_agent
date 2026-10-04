---
name: sdlc-planning-task-breakdown
description: Breaks work into ordered tasks. Use when you have a spec or clear requirements and need to break work into implementable tasks. Use when a task feels too large to start, when you need to estimate scope, or when parallel work is possible.
---

# SDLC Planning and Task Breakdown

## Overview

Decompose work into small, verifiable tasks with explicit acceptance criteria. Good task breakdown is the difference between an agent that completes work reliably and one that produces a tangled mess. Every task should be small enough to implement, test, and verify in a single focused session.

## When to Use

- You have a spec and need to break it into implementable units (Sub-Specs).
- A task feels too large or vague to start.
- Work needs to be parallelized across multiple agents or sessions.
- You need to communicate scope to a human.
- The implementation order isn't obvious.

**When NOT to use:** Single-file changes with obvious scope, or when the spec already contains well-defined tasks.

## The Planning Process

### Step 1: Enter Plan Mode

Before writing any code or Sub-Spec, operate in read-only mode:

- Read the spec and relevant codebase sections
- Identify existing patterns and conventions
- Map dependencies between components
- Note risks and unknowns

**Do NOT write code during planning.** The output is a master plan document saved to the project folder at `.ai/plans/main/YYYY-MM-DD/main_[plan_id].md` (with YAML frontmatter containing mandatory `plan_id` and `goal`), which outlines the sequence of Sub-Specs to generate.

### Step 2: Identify Dependencies & Parallel Execution (DAG)

Map what depends on what:

```
Database schema
    │
    ├── API models/types
    │       │
    │       ├── API endpoints
    │       │       │
    │       │       └── Frontend API client
    │       │               │
    │       │               └── UI components
    │       │
    │       └── Validation logic
    │
    └── Seed data / migrations
```

Implementation order follows the dependency graph bottom-up: build foundations first.
**Crucial Analysis:** Explicitly check which tasks do NOT have dependencies on each other. If tasks are independent (e.g., building Frontend UI components while Backend API is being built against a mocked interface), highlight that they can be executed **in parallel** by multiple specialized agents to accelerate progress. You MUST include this parallelism analysis in the plan document before execution.

### Step 3: Slice Vertically

Instead of building all the database, then all the API, then all the UI — build one complete feature path at a time:

**Bad (horizontal slicing):**
```
Task 1: Build entire database schema
Task 2: Build all API endpoints
Task 3: Build all UI components
```

**Good (vertical slicing):**
```
Task 1: User can create an account (schema + API + UI for registration)
Task 2: User can log in (auth schema + API + UI for login)
Task 3: User can create a task (task schema + API + UI for creation)
```

Each vertical slice delivers working, testable functionality.

### Step 4: Write Task Breakdown (Before Generating Sub-Specs)

Each task defined in the plan should follow this structure. Later, each task will be formally expanded using the `sdlc-subtask-specifier` skill into its own `.ai/plans/subtasks/YYYY-MM-DD/subtask_[id].md` file.

```markdown
## Task [N]: [Short descriptive title]

**Plan ID:** `plan_[feature_name]`
**Task ID:** `subtask_[N]_[slug]`
**Assigned Role:** `coder` (Dedicated Domain Expert)
**Description:** One paragraph explaining what this task accomplishes.

**Acceptance criteria:**
- [ ] [Specific, testable condition]
- [ ] [Specific, testable condition]

**Dependencies:** [Task numbers this depends on, or "None"]
**Parallelizable With:** [List of task numbers that can be run at the same time, or "None"]

**Files likely touched:**
- `src/path/to/file.py`
- `tests/path/to/test.py`

**Estimated scope:** [Small: 1-2 files | Medium: 3-5 files | Large: 5+ files]
```

### Step 5: Order and Checkpoint

Arrange tasks so that:

1. Dependencies are satisfied (build foundation first).
2. Each task leaves the system in a working state.
3. Verification checkpoints occur after every 2-3 tasks.
4. High-risk tasks are early (fail fast).

Add explicit checkpoints:
```markdown
## Checkpoint: After Tasks 1-3
- [ ] All tests pass (`conda run -n pytorch pytest`)
- [ ] Review with human before proceeding
```

## Task Sizing Guidelines

| Size | Files | Scope | Example |
|------|-------|-------|---------|
| **XS** | 1 | Single function or config change | Add a validation rule |
| **S** | 1-2 | One component or endpoint | Add a new API endpoint |
| **M** | 3-5 | One feature slice | User registration flow |
| **L** | 5-8 | Multi-component feature | Search with filtering and pagination |
| **XL** | 8+ | **Too large — break it down further** | — |

If a task is L or larger, it should be broken into smaller tasks.

**When to break a task down further:**
- It touches two or more independent subsystems.
- You find yourself writing "and" in the task title.

## Output Files

- **Plan document:** Save the implementation plan to the project folder at `.ai/plans/main/YYYY-MM-DD/main_[plan_id].md` (do not save it to a separate artifact folder).
- **Next Step:** Once the plan is approved by the user, the Orchestrator will use `sdlc-subtask-specifier` to generate individual `.ai/plans/subtasks/YYYY-MM-DD/subtask_[task_id].md` files for each task in the plan.

## Verification

Before finishing the planning phase, confirm:
- [ ] Task dependencies are identified and ordered correctly (DAG).
- [ ] No task touches more than ~5 files (M size max).
- [ ] Tasks are sliced vertically (delivering complete features).
- [ ] The human has reviewed and approved the plan in `.ai/plans/main/YYYY-MM-DD/main_[plan_id].md`.
