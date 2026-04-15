# local-agent

Personal source of truth for shared coding-agent setup.

This repo is meant to make two things repeatable:

1. New machine setup
2. New project setup

The goal is that your agent behavior, shared instructions, durable context, skills, and MCP wiring are tracked here instead of living only in one machine's dotfiles.

## What this repo owns

- Home-level shared agent instructions
- Claude wrapper files
- Portable skill library
- MCP server definitions
- Claude settings defaults
- New-project templates for `AGENTS.md`, `CLAUDE.md`, and optional `.impeccable.md`
- Bootstrap scripts that sync those tracked files into the right local paths
- Drift checks and test coverage so the setup stays trustworthy over time
- A single CLI entrypoint for machine and project workflows

## Repo layout

- `skills/portable/`
  Portable skill set installed into both `~/.agents/skills` and `~/.claude/skills`
- `templates/home/`
  Home-level managed files like shared `AGENTS.md` and Claude wrapper content
- `templates/project/`
  Generated files for new repositories
- `manifests/`
  Structured definitions for skills, MCP servers, and Claude settings
- `config/machine.example.json`
  Example machine-local secret/config file
- `scripts/bootstrap_machine.py`
  New-machine entrypoint
- `scripts/sync_agent_parity.py`
  Idempotent home sync from repo -> local machine
- `scripts/init_project.py`
  New-project entrypoint
- `scripts/doctor.py`
  Drift detector for machine + project setup
- `scripts/local_agent.py`
  Unified CLI wrapper around the repo workflows
- `tests/`
  Regression coverage for sync, project init, and doctor checks
- `Makefile`
  Shortcuts for the common commands

## New machine flow

1. Clone this repo.
2. Create machine-local secrets/config:

```bash
cp config/machine.example.json config/machine.local.json
```

3. Fill in the secret values in `config/machine.local.json`.
4. Dry-run the bootstrap:

```bash
python3 scripts/bootstrap_machine.py --init-machine-local
```

5. Apply it:

```bash
python3 scripts/bootstrap_machine.py --apply --init-machine-local
```

Or use the unified CLI:

```bash
python3 scripts/local_agent.py bootstrap --apply --init-machine-local
```

What this does:

- writes `~/.agents/AGENTS.md` from `templates/home/AGENTS.md`
- links both `~/.codex/AGENTS.md` and `~/.claude/AGENTS.md` to that shared file
- writes `~/.claude/CLAUDE.md` from template
- writes `~/.claude/settings.json` from tracked settings defaults
- writes `~/.claude/.mcp.json` from tracked MCP manifest plus machine-local secrets
- syncs portable skills into both `~/.agents/skills` and `~/.claude/skills`
- updates the managed MCP block in `~/.codex/config.toml`
- only requires Claude env secrets for tools enabled in the active profile

If you are migrating an already-customized machine and want the repo-owned portable skill copies to become canonical, use:

```bash
python3 scripts/local_agent.py bootstrap --apply --init-machine-local --adopt-existing-skills
```

That will move conflicting non-symlink skill directories aside as timestamped backups and replace them with symlinks into this repo.

## New project flow

Dry-run in the target repo:

```bash
python3 ~/local-agent/scripts/init_project.py /path/to/project --with-impeccable-template
```

Apply:

```bash
python3 ~/local-agent/scripts/init_project.py /path/to/project --apply --with-impeccable-template
```

Or:

```bash
python3 ~/local-agent/scripts/local_agent.py init-project /path/to/project --apply --with-impeccable-template
```

This creates:

- `AGENTS.md`
- `CLAUDE.md`
- optional `.impeccable.md`

The generated `AGENTS.md` includes a managed copy of the shared home baseline plus a project-specific section for commands, domain context, and constraints.
That repo `AGENTS.md` is intended to be the shared project memory/context file for Claude, Codex, and any future agent you wire in.

If you rerun `init_project.py`, it refreshes only the managed shared-baseline block and leaves the project-specific section alone, as long as the file still contains the local-agent markers.

To verify a project is still in parity with the tracked templates:

```bash
python3 ~/local-agent/scripts/local_agent.py doctor --project /path/to/project --expect-impeccable
```

## Secrets and local state

Tracked in git:

- manifests
- templates
- portable skills
- bootstrap scripts

Not tracked in git:

- `config/machine.local.json`

Use `config/machine.local.json` for machine-specific secrets like:

- `FIGMA_API_KEY`
- `JIRA_HOST`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`

The sync scripts also fall back to process environment variables if a key is not present in `machine.local.json`.

## Commands

Dry-run home sync:

```bash
python3 scripts/sync_agent_parity.py
```

Apply home sync:

```bash
python3 scripts/sync_agent_parity.py --apply
```

Dry-run home sync via the unified CLI:

```bash
python3 scripts/local_agent.py sync
```

Check home drift:

```bash
python3 scripts/local_agent.py doctor
```

Dry-run machine bootstrap:

```bash
python3 scripts/bootstrap_machine.py --init-machine-local
```

Apply machine bootstrap:

```bash
python3 scripts/bootstrap_machine.py --apply --init-machine-local
```

Dry-run project init:

```bash
python3 scripts/init_project.py . --with-impeccable-template
```

Apply project init:

```bash
python3 scripts/init_project.py . --apply --with-impeccable-template
```

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

Or use `make test`.

## Source of truth rules

If you want to change shared behavior permanently:

- Shared agent defaults: edit `templates/home/AGENTS.md`
- Claude wrapper behavior: edit `templates/home/CLAUDE.md`
- Portable skills: edit files under `skills/portable/`
- MCP definitions: edit `manifests/mcp_servers.json`
- Claude default settings: edit `manifests/claude_settings.json`
- New-project generated files: edit `templates/project/`

Then rerun the appropriate script.

## Current assumptions

- This repo is the source of truth for agent setup.
- Claude, Codex, and future coding agents should share the same durable instructions from `~/.agents/AGENTS.md` and repo `AGENTS.md` where possible.
- Portable skills should be shared through `~/.agents/skills` where possible.
- Agent-specific home files are rendered from repo-managed templates/manifests.
- Existing unmanaged local files are not deleted automatically if that would be risky. The scripts prefer linking, updating managed files, or warning.
