# Codex Linux History Persistence

## Goal

Keep a Linux machine's Codex history stable even when the user:

- switches API keys
- switches ChatGPT accounts
- runs `codex login` again
- reinstalls or reconfigures Codex

The reliable pattern is:

1. Keep authentication local to `~/.codex`.
2. Move conversation/state data to a separate persistent directory.
3. Symlink the original paths back to the persistent directory.

## Common History Paths

Usually preserve:

- `~/.codex/sessions/`
- `~/.codex/memories/`
- `~/.codex/shell_snapshots/`
- `~/.codex/history.jsonl`
- `~/.codex/state_*.sqlite`
- `~/.codex/state_*.sqlite-wal`
- `~/.codex/state_*.sqlite-shm`
- `~/.codex/logs_*.sqlite`
- `~/.codex/logs_*.sqlite-wal`
- `~/.codex/logs_*.sqlite-shm`
- `~/.codex/session_index.jsonl` when present

Usually do not preserve as shared history:

- `~/.codex/auth.json`
- shell environment variables holding API keys
- unrelated temporary files unless the user explicitly asks

## Suggested Persistent Root

Use `/srv/codex-persistent/shared` by default on single-user servers.

If multiple Linux users should share one history store, the migration usually needs:

- a shared group
- coordinated file ownership/ACLs
- a shared Codex storage root outside any single user's home

That is a different setup from the single-user default in this skill.

## Verification Checklist

- `ls -la ~/.codex` shows symlinks for history entries
- `auth.json` remains a normal file
- the persistent directory contains the moved data
- restarting Codex still shows previous conversation history
