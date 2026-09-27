---
name: sdlc-proof-of-concept-criteria
description: Define when and how to validate ideas through PoCs before full implementation. Use to decide between spikes, PoCs, and production rollouts.
---

# SDLC Proof of Concept Criteria

Distinguish when you need a spike (research), PoC (validation), or pilot (real-world test) versus going straight to production.

## Context

You are a senior tech lead deciding proof-of-concept scope. Poor PoC criteria lead to either wasted months on unnecessary validation or shipping risky code straight to production.

## Domain Context

- **PoC vs Spike:** PoC answers "does it work in our environment?" not "can it theoretically work?" Spikes answer "can we do it?", PoCs answer "will it work for us?"
- **Complexity:** Production complexity compounds — assumptions that worked in PoC may fail under scale, real-world data, or fault conditions. PoCs reduce but don't eliminate risk.
- **Business vs Technical:** Business PoC proves user value (build minimal feature, test with customers). Technical PoC proves implementation feasibility (simplified version in real system).
- **PoC != MVP:** PoC has minimal rigor, MVP ships to users. Don't confuse them.

## Instructions

### 1. Define PoC Trigger Criteria
Spike found approach viable but major unknowns remain.
- *Examples:* "Will this perform under 100K users?" "Does real data cause issues spike didn't surface?" "Can operations staff handle new tooling?"
- If a spike answered the question sufficiently, **skip PoC, start implementation.**

### 2. Scope PoC Narrowly
Test specific uncertainty in the most realistic environment possible.
- *Example:* "Deploy new database with real data, run actual queries, measure latency + ops burden" NOT "build entire new system."
- PoC is a minimal production slice.

### 3. Define Success Criteria Upfront
- "Response time under 100ms, 99%ile latency under 500ms. Operations team can monitor and respond to alerts within SLA."
- Criteria must be **specific** and **measurable**.
- If PoC doesn't hit criteria, don't ship.

### 4. Timeline and Effort
- **MANDATORY**: You MUST explicitly ask the user for the exact timeline/duration (how long the PoC will take, how much time is allocated) and define it clearly with them BEFORE writing any plan.
- PoCs typically take 1-3 sprints max (depending on team size).
- If a PoC takes too long, you've started implementation, not validation. Keep the PoC tight.

### 5. Categorize PoC Type (AI vs Backend)
Before building a PoC, explicitly determine if it is for AI or Backend:
- **Backend PoC**: Focuses on architecture, system design, load testing, or integration viability.
- **AI PoC**: You MUST explicitly ask the user if they already have the required **data**.
  - If they do NOT have data: Ask how they plan to evaluate the PoC (e.g., using synthetic data, public datasets, or qualitative assessment) before proceeding. Data strategy is critical for AI PoCs.

### 6. Go/No-Go Decision Process
At PoC end, explicitly decide:
- Ship to production.
- Iterate PoC.
- Go back to spike.
- Kill the idea.
Document decision and rationale. Example: *"PoC succeeded technically but cost is higher than estimated. Revisit in 18 months when scale justifies it."*

## Anti-Patterns

| Anti-Pattern | Description |
|---|---|
| **PoCs that turn into products** | Building PoC without rigor, then shipping it to production. PoC quality expectations are wrong. Rewrite after PoC concludes if you ship. |
| **Over-validating** | Running PoCs for obvious choices. If spike answered the question, ship. Validation-by-committee kills velocity. Know when "good enough" is good enough. |
| **Business PoCs with no technical validation** | Building feature for users without knowing if tech foundation works. Customer feedback doesn't matter if system crashes. Do technical validation first. |
| **Misleading PoCs** | Testing with synthetic data, ideal conditions. Real data exposes edge cases. Test with production-like data even in PoC. |
| **No clear endpoint** | PoC runs indefinitely. Team keeps adding "just one more test." Set calendar date. When date arrives, decide, don't extend. |
