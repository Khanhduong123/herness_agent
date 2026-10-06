---
name: sdlc-precode-adversarial-critic
description: >-
  Pre-implementation adversarial audit protocol for Sub-Specs.
  Falsifies designs before Coder dispatch, discovering edge cases,
  breaking changes, and race conditions, auto-enriching TestCaseSpec.
---

# Pre-Code Adversarial Critic

> [!NOTE]
> This skill defines an adversarial audit protocol for Sub-Specs. It is designed to intervene before the Coder writes any code, identifying flaws, edge cases, and potential failures at the design stage.

## 1. The Falsification Question

When reviewing a Sub-Spec, the primary question to ask is:

**"What input, concurrent condition, or breaking interface change would overturn this Sub-Spec?"**

The goal is not to prove that the Sub-Spec works, but to actively try to break it theoretically.

## 2. Pre-Flight Falsification Checklist

Before dispatching to the Coder, systematically evaluate the Sub-Spec against this checklist:

### 2.1 Concurrency & Race Conditions
- Are there shared resources being accessed?
- E.g., SQLite lock contention, async event loop blocking, file system race conditions.
- How does the design handle multiple simultaneous requests?

### 2.2 Boundary & Nullability Invariants
- What happens with empty collections (lists, dicts)?
- What if files or directories are missing?
- How does it handle corrupted schemas or unexpected JSON structures?
- Are nulls, None, or undefined values safely checked?

### 2.3 Upstream Contract Drift
- Does this design rely on external systems or upstream modules?
- What happens if Pydantic models change?
- How are breaking changes in dependencies handled?
- Does it affect downstream consumers negatively?

### 2.4 Performance Bottlenecks
- Are there hidden nested loops (O(N^2) complexity)?
- Are database queries unindexed or fetching too much data?
- Is there a memory leak risk from unbounded lists or caches?

### 2.5 Test Classification & Target Directory Verification
- Does every test case in the Sub-Spec specify an explicit `Test Category` (`Unit Test` or `Integration Test`)?
- Does every test target either `tests/unit/` or `tests/integration/`?
- **Rejection Rule**: Reject any Sub-Spec that omits the `Test Category` column or attempts to place test files in the root of `tests/`.

## 3. Auto-Enrichment Protocol

Any identified failure modes or edge cases from the Falsification Checklist MUST NOT simply be noted; they must be actively used to improve the Sub-Spec.

1. **Categorize:** Distinguish between a Fatal Blocker (requires architectural redesign) and a Non-blocking Advisory (can be handled in implementation).
2. **Enrich TestCaseSpec:** Automatically append the discovered failure modes to the Sub-Spec's `TestCaseSpec`.
   - Add them under **TC-02 Edge Cases** and **TC-03 Exception Paths**.
3. **Refine Sub-Spec:** Ensure the contract (Pydantic models, function signatures) accounts for these edge cases (e.g., adding `Optional`, handling exceptions).
