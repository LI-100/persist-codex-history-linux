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
  --host your-linux-host \
  --user your-user \
  --password-env CODEX_SERVER_PASSWORD
```

If history files exist but `/resume` only shows a subset of threads, inspect provider metadata before changing anything:

```bash
python scripts/repair_codex_provider_visibility.py \
  --host your-linux-host \
  --user your-user \
  --password-env CODEX_SERVER_PASSWORD \
  --inspect
```

If one Linux host keeps switching between providers or accounts and you want the shared history to follow the latest active provider automatically, use the local automation scripts:

```bash
python scripts/install_local_provider_sync_systemd.py
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

### 5. Diagnose provider visibility issues

Some Codex builds appear to surface resume history according to provider metadata stored in session/state files. When that metadata is inconsistent with the active login, `/resume` may show only part of the stored history even though the session files still exist.

Use `scripts/repair_codex_provider_visibility.py` to:

- inspect which `model_provider` values exist in `state_*.sqlite` and session metadata
- back up the relevant files before any repair
- rewrite provider metadata to an explicitly chosen provider when the user wants all stored history visible under the current provider context

Do not hard-code `openai` in your reasoning or repairs. The target provider may be any provider name used on that machine.

For one local Linux host, use `scripts/sync_codex_provider_visibility_local.py` when:

- the machine should keep history visible after provider switches
- the latest active provider should become the canonical visible context
- you want to skip session files that are still open by running Codex processes

This does not make two different provider values simultaneously native-visible. It makes the history follow the newest active provider context over time.

## References

Read [references/storage-layout.md](references/storage-layout.md) when you need the rationale, file list, and behavior notes for cross-auth shared history.
Read [references/provider-visibility.md](references/provider-visibility.md) when history exists on disk but `/resume` only shows part of it.
Read [references/provider-automation.md](references/provider-automation.md) when one Linux host should keep following the latest active provider automatically.
