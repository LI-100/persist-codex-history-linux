#!/usr/bin/env python3
"""Inspect or repair Codex model_provider metadata on a Linux host."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

try:
    import paramiko
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "paramiko is required. Install it with: python -m pip install --user paramiko"
    ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or repair Codex session/thread model_provider metadata on a "
            "Linux host so stored history remains visible across provider contexts."
        )
    )
    parser.add_argument("--host", required=True, help="Linux host to inspect")
    parser.add_argument("--port", type=int, default=22, help="SSH port")
    parser.add_argument("--user", required=True, help="SSH user")
    auth = parser.add_mutually_exclusive_group(required=True)
    auth.add_argument("--password", help="SSH password")
    auth.add_argument("--password-env", help="Environment variable containing the SSH password")
    auth.add_argument("--key-file", help="Private key path")
    parser.add_argument(
        "--store-dir",
        default="/srv/codex-persistent/shared",
        help="Persistent Codex history directory on the remote host",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Only inspect provider values and do not modify the host",
    )
    parser.add_argument(
        "--target-provider",
        help="Rewrite stored provider metadata to this explicit provider value",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the repair. A backup is created first.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="SSH connect timeout in seconds",
    )
    args = parser.parse_args()
    if not args.inspect and not (args.apply and args.target_provider):
        parser.error("Use --inspect, or use --apply together with --target-provider.")
    return args


def resolve_password(args: argparse.Namespace) -> str | None:
    if args.password is not None:
        return args.password
    if args.password_env is not None:
        value = os.environ.get(args.password_env)
        if not value:
            raise SystemExit(
                f"Environment variable {args.password_env!r} is not set or empty."
            )
        return value
    return None


def build_remote_script(store_dir: str, inspect_only: bool, target_provider: str | None) -> str:
    q_store = shlex.quote(store_dir)
    target = "" if target_provider is None else target_provider
    q_target = shlex.quote(target)
    mode = "inspect" if inspect_only else "apply"
    return f"""set -euo pipefail
STORE_DIR={q_store}
MODE={shlex.quote(mode)}
TARGET_PROVIDER={q_target}
STAMP=$(date +%Y%m%dT%H%M%S)
export STORE_DIR MODE TARGET_PROVIDER STAMP

python3 - <<'PY'
import json
import sqlite3
from collections import Counter
from pathlib import Path
import shutil
import os

store = Path(os.environ['STORE_DIR'])
mode = os.environ['MODE']
target_provider = os.environ['TARGET_PROVIDER']
state_db = store / 'state_5.sqlite'
sessions_root = store / 'sessions'

if not state_db.exists():
    raise SystemExit(f"Missing state database: {{state_db}}")
if not sessions_root.exists():
    raise SystemExit(f"Missing sessions directory: {{sessions_root}}")

def inspect():
    conn = sqlite3.connect(state_db)
    cur = conn.cursor()
    cur.execute("select model_provider, count(*) from threads group by model_provider order by count(*) desc, model_provider")
    print("THREAD_PROVIDER_COUNTS")
    for row in cur.fetchall():
        print(row)
    conn.close()

    counts = Counter()
    for f in sessions_root.rglob('*.jsonl'):
        with f.open('r', encoding='utf-8') as fh:
            first = fh.readline().strip()
        if not first:
            continue
        obj = json.loads(first)
        payload = obj.get('payload', {{}})
        counts[payload.get('model_provider')] += 1
    print("SESSION_PROVIDER_COUNTS")
    for item in counts.most_common():
        print(item)

if mode == 'inspect':
    inspect()
    raise SystemExit(0)

backup_dir = store.parent / f"provider-repair-backup-{{STAMP}}"
backup_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(state_db, backup_dir / state_db.name)
shutil.copytree(sessions_root, backup_dir / 'sessions')
print(f"BACKUP_DIR={{backup_dir}}")

conn = sqlite3.connect(state_db)
cur = conn.cursor()
cur.execute("update threads set model_provider=? where model_provider<>?", (target_provider, target_provider))
print("THREADS_UPDATED", cur.rowcount)
conn.commit()
conn.close()

changed = 0
for f in sessions_root.rglob('*.jsonl'):
    with f.open('r', encoding='utf-8') as fh:
        lines = fh.readlines()
    if not lines:
        continue
    first = json.loads(lines[0])
    payload = first.get('payload', {{}})
    if payload.get('model_provider') != target_provider:
        payload['model_provider'] = target_provider
        first['payload'] = payload
        lines[0] = json.dumps(first, ensure_ascii=False) + '\\n'
        with f.open('w', encoding='utf-8', newline='') as fh:
            fh.writelines(lines)
        changed += 1
print("SESSION_FILES_UPDATED", changed)

inspect()
PY
"""


def main() -> int:
    args = parse_args()
    password = resolve_password(args)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kwargs = {
        "hostname": args.host,
        "port": args.port,
        "username": args.user,
        "timeout": args.timeout,
    }
    if password is not None:
        connect_kwargs["password"] = password
    if args.key_file is not None:
        connect_kwargs["key_filename"] = str(Path(args.key_file))

    script = build_remote_script(args.store_dir, args.inspect, args.target_provider)
    client.connect(**connect_kwargs)
    try:
        stdin, stdout, stderr = client.exec_command("bash -s")
        stdin.write(script)
        stdin.channel.shutdown_write()
        rc = stdout.channel.recv_exit_status()
        sys.stdout.write(stdout.read().decode("utf-8", "replace"))
        sys.stderr.write(stderr.read().decode("utf-8", "replace"))
        return rc
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
