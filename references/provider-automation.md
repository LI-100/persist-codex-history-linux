# Provider Automation On One Linux Host

## Goal

Keep one shared Codex history visible after switching between:

- different OpenAI accounts
- different API keys
- different provider names over time

## Constraint

Codex visibility appears to key off the active `model_provider` value.

That means one stored thread set cannot be simultaneously native-visible under two different provider values at the same instant. A local automation job can still make the history follow the currently active provider by rewriting older metadata to match the latest active context.

## Practical Model

Use one persistent storage directory such as `/srv/codex-persistent/shared`, then run a local sync job that:

1. detects the provider from the newest open session, or else the newest thread
2. rewrites `threads.model_provider` in `state_*.sqlite`
3. rewrites the first `session_meta` line in closed `sessions/*.jsonl`
4. skips session files that are still open by running Codex processes

Skipping open files avoids corrupting a live session file. On the next timer run, that session becomes eligible once Codex closes it.

## Local Scripts

- `scripts/sync_codex_provider_visibility_local.py`
- `scripts/install_local_provider_sync_systemd.py`

Inspection example:

```bash
python scripts/sync_codex_provider_visibility_local.py --inspect
```

One-time repair with a backup:

```bash
python scripts/sync_codex_provider_visibility_local.py --apply --backup
```

Install a periodic systemd timer:

```bash
python scripts/install_local_provider_sync_systemd.py
```
