# Provider Visibility And Resume

## Symptom

The Linux host still has session files and thread rows, but `/resume` shows only one thread or only a subset of the stored history.

## Likely Cause

Some stored Codex histories include `model_provider` metadata in:

- `sessions/*/*.jsonl` session metadata
- `state_*.sqlite` `threads.model_provider`

If those provider values do not match the current provider context used by the running Codex client, resume history may appear incomplete even though the raw history files still exist.

## Important Rule

Do not assume the correct provider is always `openai`.

The right target provider depends on the machine's actual usage. A host may have history from:

- OpenAI
- another API-compatible provider
- multiple providers over time

Also do not assume different provider values can all stay natively visible at the same time. In practice, Codex appears to show history for one active provider context at a time. If the machine switches providers, the stored metadata usually has to be normalized again to the newly active provider.

## Safe Workflow

1. Inspect current provider values first.
2. Back up `state_*.sqlite` and `sessions/` before changing anything.
3. Choose an explicit target provider only after confirming what the user wants visible in `/resume`.
4. Rewrite provider metadata only when the user wants a single visible provider context.

## Script

Use `scripts/repair_codex_provider_visibility.py`.

Inspection example:

```bash
python scripts/repair_codex_provider_visibility.py \
  --host your-linux-host \
  --user your-user \
  --password-env CODEX_SERVER_PASSWORD \
  --inspect
```

Repair example:

```bash
python scripts/repair_codex_provider_visibility.py \
  --host your-linux-host \
  --user your-user \
  --password-env CODEX_SERVER_PASSWORD \
  --target-provider your-provider-name \
  --apply
```

For one Linux host that should keep following the latest active provider automatically, read [references/provider-automation.md](provider-automation.md).
