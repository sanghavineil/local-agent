#!/usr/bin/env bash
# Stop hook: surface a macOS notification when a Claude Code session ends.
# Silently no-ops on non-macOS systems so the same script ships everywhere.

set -u

if ! command -v osascript >/dev/null 2>&1; then
  exit 0
fi

osascript -e 'display notification "Claude Code session done." with title "Claude" sound name "Pop"' >/dev/null 2>&1 || true
