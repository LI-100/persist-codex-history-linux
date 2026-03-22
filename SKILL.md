---
name: persist-codex-history-linux
description: Keep Codex conversation history persistent on a Linux machine across API key changes, ChatGPT account logins, and Codex reconfiguration. Use when Codex needs to inspect or modify ~/.codex on a Linux host, separate auth state from chat history, migrate existing sessions into a stable storage directory, or verify that future logins still see the same history.
---

# Persist Codex History Linux

Persist Codex history on a Linux host by moving conversation/state files out of `~/.codex` into a stable server-side directory and symlinking them back. Keep auth files such as `auth.json` separate so changing API keys or ChatGPT accounts does not fork or replace the existing history.

## Quick Start

1. Inspect the target machine first.
2. Preserve only history/state data.
3. Leave auth and login material in place.
4. Verify the new symlink layout after migration.

Prefer using `scripts/persist_codex_history_linux.py` for the migration because it is deterministic and repeatable.

Example:

```bash
python scripts/persist_codex_history_linux.py \
  --host 45.205.25.118 \
  --user root \
  --password-env CODEX_SERVER_PASSWORD
```

## What To Persist

Move these into the shared storage directory and link them back into `~/.codex`:

- `sessions/`
- `memories/`
- `shell_snapshots/`
- `history.jsonl`
- `state_*.sqlite*`
- `logs_*.sqlite*`
- `session_index.jsonl` when present

Do not move these by default:

- `auth.json`
- API keys in shell profiles or env vars
- `config.toml` unless the user explicitly wants config shared too

## Workflow

### 1. Inspect the host

Check:

- whether `~/.codex` exists
- which history/state files are present
- whether Codex is currently running
- which Linux user owns the files

If Codex is actively running, prefer stopping it before migration. If that is not practical, proceed carefully and call out the risk that SQLite WAL/SHM files may change during the move.

### 2. Choose the persistent directory

Default to `/srv/codex-persistent/shared`. Use another path only if the server layout or permissions require it.

The persistent directory should outlive auth changes and Codex reinstalls for that Linux user.

### 3. Migrate and relink

Run the script or perform the same logic manually:

- create the persistent directory
- move history/state entries into it
- create symlinks at the original `~/.codex` paths
- write a short note in the persistent directory explaining that auth remains separate

If a target already exists in the persistent directory, back it up before overwriting.

### 4. Verify

Confirm:

- `~/.codex/sessions` is a symlink
- `~/.codex/history.jsonl` is a symlink
- SQLite files point into the persistent directory
- `~/.codex/auth.json` is still a normal file

After migration, advise the user to restart Codex once so future writes start cleanly from the new layout.

## References

Read [references/storage-layout.md](references/storage-layout.md) when you need the rationale, file list, and behavior notes for cross-auth shared history.
