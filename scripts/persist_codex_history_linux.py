#!/usr/bin/env python3
"""Persist Codex history on a Linux host while keeping auth separate."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

try:
    import paramiko
except ImportError as exc:  # pragma: no cover - handled in CLI usage
    raise SystemExit(
        "paramiko is required. Install it with: python -m pip install --user paramiko"
    ) from exc


def build_remote_script(codex_home: str, store_dir: str, dry_run: bool) -> str:
    q_home = shlex.quote(codex_home)
    q_store = shlex.quote(store_dir)
    dry = "1" if dry_run else "0"
    return f"""set -euo pipefail
RAW_CODEX_HOME={q_home}
RAW_STORE_DIR={q_store}
DRY_RUN={dry}
STAMP=$(date +%Y%m%dT%H%M%S)

if [ "$RAW_CODEX_HOME" = "~" ]; then
  CODEX_HOME="$HOME"
elif [ "${{RAW_CODEX_HOME#\\~/}}" != "$RAW_CODEX_HOME" ]; then
  CODEX_HOME="$HOME/${{RAW_CODEX_HOME#\\~/}}"
else
  CODEX_HOME="$RAW_CODEX_HOME"
fi

if [ "$RAW_STORE_DIR" = "~" ]; then
  STORE_DIR="$HOME"
elif [ "${{RAW_STORE_DIR#\\~/}}" != "$RAW_STORE_DIR" ]; then
  STORE_DIR="$HOME/${{RAW_STORE_DIR#\\~/}}"
else
  STORE_DIR="$RAW_STORE_DIR"
fi

run() {{
  if [ "$DRY_RUN" = "1" ]; then
    printf '[dry-run] %s\\n' "$*"
  else
    eval "$@"
  fi
}}

info() {{
  printf '%s\\n' "$1"
}}

ensure_placeholder() {{
  dst="$1"
  kind="$2"
  if [ ! -e "$dst" ] && [ ! -L "$dst" ]; then
    if [ "$kind" = dir ]; then
      run "mkdir -p $(printf '%q' "$dst")"
    else
      run ": > $(printf '%q' "$dst")"
    fi
    info "CREATE target placeholder: $dst"
  fi
}}

link_path() {{
  src="$1"
  dst="$2"
  kind="$3"
  parent=$(dirname "$dst")
  run "mkdir -p $(printf '%q' "$parent")"

  if [ -L "$src" ]; then
    info "SKIP already symlink: $src -> $(readlink "$src")"
    return 0
  fi

  if [ -e "$src" ]; then
    if [ -e "$dst" ] || [ -L "$dst" ]; then
      backup="${{dst}}.preexisting.${{STAMP}}"
      run "mv $(printf '%q' "$dst") $(printf '%q' "$backup")"
      info "BACKUP existing target: $dst -> $backup"
    fi
    run "mv $(printf '%q' "$src") $(printf '%q' "$dst")"
    info "MOVE $src -> $dst"
  else
    ensure_placeholder "$dst" "$kind"
  fi

  run "ln -sfn $(printf '%q' "$dst") $(printf '%q' "$src")"
  info "LINK $src -> $dst"
}}

info "Inspecting Codex home: $CODEX_HOME"
run "mkdir -p $(printf '%q' "$STORE_DIR")"
run "mkdir -p $(printf '%q' "$STORE_DIR/meta")"

link_path "$CODEX_HOME/sessions" "$STORE_DIR/sessions" dir
link_path "$CODEX_HOME/memories" "$STORE_DIR/memories" dir
link_path "$CODEX_HOME/shell_snapshots" "$STORE_DIR/shell_snapshots" dir
link_path "$CODEX_HOME/history.jsonl" "$STORE_DIR/history.jsonl" file

for item in "$CODEX_HOME"/state_*.sqlite "$CODEX_HOME"/state_*.sqlite-wal "$CODEX_HOME"/state_*.sqlite-shm "$CODEX_HOME"/logs_*.sqlite "$CODEX_HOME"/logs_*.sqlite-wal "$CODEX_HOME"/logs_*.sqlite-shm; do
  [ -e "$item" ] || [ -L "$item" ] || continue
  base=$(basename "$item")
  link_path "$item" "$STORE_DIR/$base" file
done

if [ -e "$CODEX_HOME/session_index.jsonl" ] || [ -L "$CODEX_HOME/session_index.jsonl" ]; then
  link_path "$CODEX_HOME/session_index.jsonl" "$STORE_DIR/session_index.jsonl" file
fi

readme="$STORE_DIR/meta/README.txt"
if [ "$DRY_RUN" = "1" ]; then
  info "[dry-run] WRITE $readme"
else
  cat > "$readme" <<'EOF'
This directory stores Codex conversation history and runtime state.
Auth files intentionally remain in the original ~/.codex directory so API keys
or ChatGPT account logins can change without replacing the shared history store.
EOF
fi

info "--- verification ---"
run "ls -ld $(printf '%q' "$CODEX_HOME")"
run "find $(printf '%q' "$CODEX_HOME") -maxdepth 1 \\( -name sessions -o -name memories -o -name shell_snapshots -o -name history.jsonl -o -name 'state_*.sqlite*' -o -name 'logs_*.sqlite*' -o -name session_index.jsonl -o -name auth.json \\) -printf '%M %p -> %l\\\\n' | sort"
run "find $(printf '%q' "$STORE_DIR") -maxdepth 1 \\( -name sessions -o -name memories -o -name shell_snapshots -o -name history.jsonl -o -name 'state_*.sqlite*' -o -name 'logs_*.sqlite*' -o -name session_index.jsonl \\) -printf '%M %p\\\\n' | sort"
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Move Codex chat/state files on a Linux host into a persistent "
            "directory and symlink them back, while leaving auth.json in place."
        )
    )
    parser.add_argument("--host", required=True, help="Linux host to configure")
    parser.add_argument("--port", type=int, default=22, help="SSH port")
    parser.add_argument("--user", required=True, help="SSH user")
    auth = parser.add_mutually_exclusive_group(required=True)
    auth.add_argument("--password", help="SSH password")
    auth.add_argument(
        "--password-env",
        help="Environment variable name containing the SSH password",
    )
    auth.add_argument("--key-file", help="Private key path for SSH auth")
    parser.add_argument(
        "--codex-home",
        default="~/.codex",
        help="Codex home on the remote Linux host",
    )
    parser.add_argument(
        "--store-dir",
        default="/srv/codex-persistent/shared",
        help="Persistent directory that should hold shared history",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print remote actions without modifying the host",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="SSH connect timeout in seconds",
    )
    return parser.parse_args()


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

    script = build_remote_script(args.codex_home, args.store_dir, args.dry_run)
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
