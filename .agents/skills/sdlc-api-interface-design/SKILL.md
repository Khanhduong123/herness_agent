---
name: sdlc-api-interface-design
description: Guides stable API and interface design following SDLC principles. Use when designing APIs, module boundaries, or any public interface. Use when creating REST endpoints, defining type contracts (Pydantic models) between modules, or establishing boundaries.
---

# SDLC API and Interface Design

## Overview

Design stable, well-documented interfaces that are hard to misuse. Good interfaces make the right thing easy and the wrong thing hard. This applies to REST APIs (FastAPI), module boundaries, component interfaces, and any surface where one piece of code talks to another.

## When to Use

- Designing new API endpoints (FastAPI routers).
- Defining module boundaries or contracts between teams.
- Establishing database schemas that inform API shape.
- Changing existing public interfaces.

## Core Principles

### Hyrum's Law

> With a sufficient number of users of an API, all observable behaviors of your system will be depended on by somebody, regardless of what you promise in the contract.

Design implications:
- **Be intentional about what you expose.** Every observable behavior is a potential commitment.
- **Don't leak implementation details.** If users can observe it, they will depend on it.
- **Plan for deprecation at design time.**

### The One-Version Rule

Avoid forcing consumers to choose between multiple versions of the same dependency or API. Extend rather than fork.

### 1. Contract First

Define the interface before implementing it. Use Pydantic v2 schemas and Python `Protocol` or `ABC`.

```python
from typing import Protocol, List
from uuid import UUID
from pydantic import BaseModel

class CreateTaskInput(BaseModel):
    title: str
    description: str | None = None

class Task(BaseModel):
    id: UUID
    title: str
    description: str | None

class TaskAPI(Protocol):
    async def create_task(self, input_data: CreateTaskInput) -> Task:
        """Creates a task and returns the created task with server-generated fields."""
        ...

    async def get_task(self, task_id: UUID) -> Task:
        """Returns a single task or raises NotFoundError."""
        ...
```

### 2. Consistent Error Semantics

Pick one error strategy and use it everywhere. For FastAPI, define a standard exception handler.

```python
from pydantic import BaseModel
from typing import Any

class APIErrorDetail(BaseModel):
    code: str        # Machine-readable: "VALIDATION_ERROR"
    message: str     # Human-readable: "Email is required"
    details: Any | None = None

class APIErrorResponse(BaseModel):
    error: APIErrorDetail

# Status code mapping
# 400 → Client sent invalid data
# 401 → Not authenticated
# 403 → Authenticated but not authorized
# 404 → Resource not found
# 409 → Conflict (duplicate, version mismatch)
# 422 → Validation failed (semantically invalid)
# 500 → Server error (never expose internal details)
```

### 3. Validate at Boundaries

Trust internal code. Validate at system edges where external input enters using Pydantic:

```python
from fastapi import APIRouter, HTTPException
from starlette import status

router = APIRouter()

@router.post("/api/tasks", response_model=Task, status_code=status.HTTP_201_CREATED)
async def create_task(task_input: CreateTaskInput):
    # FastAPI automatically validates task_input using Pydantic.
    # After validation, internal code trusts the types.
    task = await task_service.create(task_input)
    return task
```

Where validation belongs:
- API route handlers (user input)
- External service response parsing (third-party data -- **always treat as untrusted**)
- Environment variable loading (configuration via `pydantic-settings`)

### 4. Prefer Addition Over Modification

Extend interfaces without breaking existing consumers:

```python
# Good: Add optional fields
class CreateTaskInput(BaseModel):
    title: str
    description: str | None = None
    priority: str | None = None  # Added later, optional
    labels: list[str] | None = None  # Added later, optional

# Bad: Change existing field types or remove fields
class CreateTaskInput(BaseModel):
    title: str
    # description: str  # Removed — breaks existing consumers
    priority: int       # Changed from str to int — breaks existing consumers
```

### 5. Predictable Naming

| Pattern | Convention | Example |
|---------|-----------|---------|
| REST endpoints | Plural nouns, no verbs | `GET /api/tasks`, `POST /api/tasks` |
| Query params | snake_case | `?sort_by=created_at&page_size=20` |
| Response fields | snake_case (or camelCase if required by frontend) | `{"created_at": ..., "task_id": ...}` |
| Boolean fields | is/has/can prefix | `is_complete`, `has_attachments` |
| Enum values | UPPER_SNAKE | `"IN_PROGRESS"`, `"COMPLETED"` |

### 6. Honouring an Idempotency Key

Accepting an `Idempotency-Key` is the contract. Honouring it is the implementation.

**Derive the key from the intent, not the attempt.**
```python
import uuid

# ✗ new key per attempt — every retry is a new charge
uuid.uuid4()

# ✓ derived from an immutable identifier (client generates once)
request.headers.get('idempotency-key')
```

**Claim atomically. A check followed by an act is a race:**

```python
from sqlalchemy.exc import IntegrityError

# ✓ let the unique constraint pick the winner
try:
    await db.execute(
        "INSERT INTO idempotency_keys (key, state) VALUES (:key, 'in_progress')",
        {"key": idempotency_key}
    )
except IntegrityError:
    return await replay_or_reject(idempotency_key)

result = await charge_card(amount)
await db.execute(
    "UPDATE idempotency_keys SET state = 'succeeded', response = :resp WHERE key = :key",
    {"key": idempotency_key, "resp": result}
)
```

**Guard the payload.**
```python
if existing_record.request_hash != hash_payload(request.body()):
    raise HTTPException(status_code=422, detail="idempotency key reused with a different payload")
```

## REST API Patterns

### Resource Design

```
GET    /api/tasks              → List tasks
POST   /api/tasks              → Create a task
GET    /api/tasks/{id}         → Get a single task
PATCH  /api/tasks/{id}         → Update a task (partial)
DELETE /api/tasks/{id}         → Delete a task

GET    /api/tasks/{id}/comments → List comments for a task
POST   /api/tasks/{id}/comments → Add a comment to a task
```

### Pagination

```python
class Pagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int

class PaginatedTasks(BaseModel):
    data: list[Task]
    pagination: Pagination
```

## Python Interface Patterns

### Use Discriminated Unions for Variants

```python
from typing import Literal, Union
from pydantic import BaseModel, Field
from datetime import datetime

class PendingStatus(BaseModel):
    type: Literal['pending']

class InProgressStatus(BaseModel):
    type: Literal['in_progress']
    assignee: str
    started_at: datetime

class CompletedStatus(BaseModel):
    type: Literal['completed']
    completed_at: datetime
    completed_by: str

TaskStatus = Union[PendingStatus, InProgressStatus, CompletedStatus]

def get_status_label(status: TaskStatus) -> str:
    if status.type == 'pending':
        return 'Pending'
    elif status.type == 'in_progress':
        return f'In progress ({status.assignee})'
    elif status.type == 'completed':
        return f'Done on {status.completed_at}'
```

### Input/Output Separation

```python
# Input: what the caller provides
class CreateTaskInput(BaseModel):
    title: str
    description: str | None = None

# Output: what the system returns
class TaskOutput(BaseModel):
    id: UUID
    title: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    created_by: str
```

## Verification

After designing an API:
- [ ] Every endpoint has typed input and output schemas (Pydantic).
- [ ] Error responses follow a single consistent format.
- [ ] Validation happens at system boundaries only.
- [ ] List endpoints support pagination.
- [ ] New fields are additive and optional (backward compatible).
- [ ] State-changing endpoints honour an idempotency key appropriately.
