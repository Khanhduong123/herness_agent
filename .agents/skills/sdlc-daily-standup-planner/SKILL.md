---
name: sdlc-daily-standup-planner
description: Manage timelines, review progress, and prioritize daily tasks at the start of a new day. Use to keep projects (especially time-boxed PoCs) on track.
---

# SDLC Daily Standup & Timeline Manager

This skill ensures that you act as an effective Project Manager or Scrum Master at the start and end of every working day. For time-sensitive tasks, especially Proof of Concepts (PoCs), rigorous timeline tracking is critical to prevent scope creep.

## Context

When starting a new working session or day, jumping straight into code without reviewing the timeline often leads to missed deadlines. The agent must first re-orient itself, assess what has been done, and define strict goals for the current session.

## Instructions

### 1. Morning Check-in (Review Past Progress)
Before writing new code, you MUST:
- Read the overarching plan or sub-spec (e.g., `.ai/[task_id].md` or the PoC timeline).
- Inspect recent git commits or working tree status (`git log -n 5`, `git status`) to understand what was completed in the previous session.
- **Report Status:** Inform the user if the project is currently **On-track** (Đúng hạn) or **Delayed** (Trễ hạn) based on the original timeline.

### 2. Today's Priorities (Task Breakdown)
- Based on the remaining timeline, extract and present **1 to 3 critical tasks** that MUST be completed today.
- Assign a rough time estimate to each sub-task (e.g., "Task A: 2 hours").
- Ask the user to confirm this priority list before proceeding.

### 3. Risk & Blocker Identification
- Actively ask the user: *"Are there any blockers preventing progress today? (e.g., missing data, API keys, unclear requirements?)"*
- **Descoping Strategy:** If the project is delayed, you MUST proactively suggest features or tests that can be cut (descoped) to protect the final deadline.

### 4. End-of-Day Wrap-up (Optional)
- When the user indicates the day/session is over, review the day's commits.
- Update the main plan (`.ai/[task_id].md`) to cross off completed items.
- Note down any unfinished work as the starting point for the next day.

## Anti-Patterns

| Anti-Pattern | Description |
|---|---|
| **Blind Coding** | Starting a session by immediately writing code without checking if it aligns with today's required milestones. |
| **Ignoring Deadlines** | Continuing to add "nice-to-have" features when the core PoC is already behind schedule. |
| **Silent Delays** | Realizing a task will take longer than expected but failing to alert the user or suggest a descoping plan. |
