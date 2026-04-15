---
name: lean-scope-planner
description: Turn external inspiration, articles, screenshots, competitor features, and "let's build something like this" requests into a right-sized implementation scope for the current repo. Use when the agent should resist writing a naive PRD, ask only the highest-signal clarifying questions, compare minimum, recommended, and stretch options, and keep proposed work aligned with existing code patterns and anti-bloat constraints.
---

# lean-scope-planner

Use this skill before writing a PRD or implementation plan when the user is pointing at outside material and wants something adapted to the current repo, not copied wholesale.

## Workflow

### 1. Build a context packet

Read only the minimum source material needed to answer:

- what problem or behavior the source is demonstrating
- what constraints already exist in the repo
- what existing feature, file, or pattern is closest

Separate notes into:

- `Source says`
- `Repo says`
- `Inference`
- `Need to confirm`

If the user shared multiple articles or examples, map each source to one action: `adopt`, `adapt`, `reject`, or `defer`.

### 2. Ask only blocking questions

Do not start with a long questionnaire. Ask follow-ups only when the answer changes scope, sequencing, architecture, or success criteria.

Default to at most 3 short questions. Good triggers:

- conflicting product intent
- missing success metric
- unclear target user or workflow
- uncertainty about whether the idea belongs in the current phase
- tradeoffs between speed and robustness

If the missing information is low-risk, make a labeled assumption and continue.

### 3. Produce a scope memo before any PRD

Default output is a scope memo, not a PRD.

Include only:

- goal
- non-goals
- source behaviors worth copying
- minimum slice
- recommended slice
- stretch slice
- out of scope
- hidden costs or risks
- open questions or assumptions

Keep the first pass short. If the user did not ask for depth, prefer 5-10 bullets or roughly 250 words.

### 4. Run anti-bloat checks

Before recommending a slice, test it against these questions:

- Can this be absorbed by an existing file, component, service, or doc?
- Is there a smaller slice that still proves the value?
- Are you importing surface area from the source that the repo does not need?
- Does the plan introduce a new abstraction, dependency, or workflow with only one use site?
- Are you mixing core scope with cleanup, platform work, or nice-to-haves?

If the last two answers are yes, stop and justify it. If the justification is weak, cut it.

### 5. Choose the lightest planning artifact

Use this ladder:

- tiny or local change: respond in chat with a short scope memo
- medium multi-file change: write a small scoped plan to disk
- long-running or multi-turn work: persist findings, plan, and progress

Prefer existing project artifacts before inventing new ones:

- update an existing PRD if the work clearly belongs there
- update `PROGRESS.md` when work lands
- create a new scoped doc only when the work is large enough to need one

### 6. End with an implementation-ready slice

Before handing off to coding, state:

- chosen slice
- why it beats the bigger alternatives
- files or systems likely to change
- existing patterns to reuse
- tests or checks needed
- what is explicitly not included yet

Do not write a full PRD unless the user asks for one or approves the scope memo first.

## Default Guardrails

- Prefer adaptation over imitation.
- Prefer one narrow plan over a comprehensive roadmap.
- Prefer explicit non-goals over extra requirements.
- Prefer labeled assumptions over silent guessing.
- Prefer repo evidence over generic best practices.
- Treat "something like this" as inspiration, not authorization to clone the whole thing.
