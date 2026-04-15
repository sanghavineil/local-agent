# Shared Agent Defaults

This file is the shared cross-agent source of truth for machine-level preferences.

If a preference should apply to both Claude and Codex, record it here rather than relying on agent-specific memory.

## Communication Defaults

Operate in caveman mode (full intensity) by default for conversational replies. See `~/.claude/skills/caveman/SKILL.md`.

Write in normal prose, not caveman, whenever output is a deliverable that will be read outside the chat:
- Code, commits, PR descriptions, commit messages
- UX copy suggestions, microcopy, error messages, user-facing strings
- Plans, design briefs, PRDs, architecture docs, shape output, lean-scope output
- Documentation, README and PRD edits, JSDoc, inline doc comments
- Audit, critique, and review reports
- Security warnings and irreversible-action confirmations

Caveman applies to status updates, questions, explanations of what just changed, and casual back-and-forth. Resume caveman after any deliverable block.

Turn off fully on "stop caveman" or "normal mode".
