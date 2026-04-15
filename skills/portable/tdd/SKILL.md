---
name: tdd
description: Use for non-trivial async or frontend work, race-condition-prone bug fixes, or any task where robustness matters more than speed. Produces a short preflight, prefers tests first, allows repro-first for UI concurrency bugs, stops on ambiguity, and pushes toward the smallest robust implementation.
---

# tdd

Use this skill for:

- async or frontend changes
- race-condition-prone bug fixes
- state or data-flow changes
- work where the user explicitly wants a more robust first pass

Do not use the full workflow for low-risk edits such as docs-only, comments-only, formatting-only, import-only, or other changes with no logic, state, async, API, or schema impact. For those, use a one-line rationale and keep moving.

## Workflow

### 1. Preflight first

Before editing code, produce a short preflight in chat. Keep it to at most 8 bullets or roughly 150-200 words unless the task is genuinely complex.

Cover only:

- goal and non-goals
- touched state, data flow, and async boundaries
- main failure modes
- smallest robust implementation
- existing pattern to reuse
- test-first vs repro-first
- anything ambiguous or risky enough to stop on

If the preflight finds ambiguity, a new architectural pattern, a new dependency, or a new concurrency mechanism without an established pattern, stop and ask the user before coding.

If the preflight is clear and the task is not blocked, proceed without waiting for approval unless the user explicitly asked to review the preflight first.

### 2. Start with proof

Prefer tests first when practical.

Use repro-first instead when classic test-first is awkward but the bug can be reproduced deterministically, especially for:

- UI race conditions
- stale-closure bugs
- unmount-during-async bugs
- duplicate-submit or in-flight request issues
- out-of-order response handling

Good repro-first artifacts include:

- a failing integration or component test
- a deterministic browser or harness repro
- a deferred-promise or fake-timer test for ordering or cancellation

Do not implement first and promise to add tests later unless the user explicitly approves that tradeoff.

### 3. Implement the smallest robust fix

Reuse existing patterns before creating new ones.

Apply repo rules from `CLAUDE.md`, especially:

- `Fix Quality - Root Cause Over Band-Aids`
- `Anti-Bloat Rules`
- `Concurrency And Race Conditions`

For React async code, explicitly reason about:

- stale closures
- unmount safety
- cancellation or abort handling
- duplicate invocation guards
- last-request-wins vs queued behavior

If a `useCallback` both reads and sets the same state across `await` boundaries, follow the repo's ref-mirror pattern.

### 4. Verify before calling it done

Before finishing, report:

- what checks you ran
- what behavior or race condition the checks prove
- any residual risk or untested edge case
- why this was the smallest robust option

For frontend code changes, always run at least the lightweight frontend check required by `CLAUDE.md`. Add targeted tests when behavior, state, or async flows changed.
