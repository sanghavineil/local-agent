---
name: docs-closeout
description: Reconcile repository documentation after a task or documentation housekeeping pass. Use when finishing implementation, closing out a shipped slice, syncing `PRD.md` and `PROGRESS.md`, deciding whether `README.md` or `docs/README.md` need updates, or moving specs between `docs/`, `docs/completed/`, `docs/deferred/`, and `docs/reports/`.
---

# docs-closeout

Use this skill to keep repo documentation accurate at closeout. Treat it as a targeted reconciliation pass, not a license to rewrite every markdown file.

## Workflow

### 1. Classify the work

Decide whether the work is:

- `active` - still implementation-ready or partly shipped
- `complete` - implemented and verified
- `deferred` - intentionally postponed
- `report` - narrative, retrospective, or research-only

Keep partly shipped work `active`. Ask only if moving a spec would be risky.

### 2. Read the minimum doc set

Start with:

- `PRD.md`
- `PROGRESS.md`

Read these only when relevant:

- `README.md` for setup, architecture, workflow, or user-facing capability changes
- `docs/README.md` when a doc file is added, moved, renamed, completed, or deferred
- `ADMIN_OPERATIONS.md` when admin models, admin actions, or operational workflows changed
- the touched spec and the target folder README before changing lifecycle placement

### 3. Apply lifecycle rules

- Keep implementation-ready specs in `docs/` root.
- Move a spec to `docs/completed/` only after implementation and verification.
- Move a spec to `docs/deferred/` only when it is explicitly postponed.
- Keep narrative memos and retrospectives in `docs/reports/`.
- Fix links and parent references after every move or rename.

### 4. Update only the files that changed meaning

- `PRD.md`: sync phase status, navigation, and active, deferred, or completed placement.
- `PROGRESS.md`: record shipped slices, verification, and historically relevant housekeeping.
- `README.md`: update only when onboarding, architecture, workflow, or repo navigation changed.
- `docs/README.md`: sync inventory when docs enter, leave, or move within lifecycle folders.
- `ADMIN_OPERATIONS.md`: sync when admin models, admin site config, or operational workflows changed.
- folder `README.md` files: update only when their guidance becomes inaccurate.

### 5. Run a closeout check

- Search for old paths after every move or rename.
- Confirm completed specs are not still referenced as active.
- Confirm deferred specs are not still marked ready.
- Note explicitly when docs-only changes need no runtime checks.

### 6. Report the outcome

State:

- docs updated
- docs moved between lifecycle folders, if any
- intentionally stale or follow-up docs, if any

## Guardrails

- Prefer targeted edits over broad rewrites.
- Do not archive early.
- Do not rewrite `README.md` for internal-only implementation details.
- Keep `PROGRESS.md` additive; preserve useful delivery history.
- Follow existing repo conventions before inventing new document structure.
