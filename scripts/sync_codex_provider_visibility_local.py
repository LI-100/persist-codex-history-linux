#!/usr/bin/env python3
"""Normalize Codex provider metadata on the local Linux host."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or normalize Codex provider metadata in a local persistent "
            "history store so the latest active provider context can see all "
            "stored threads."
        )
    )
    parser.add_argument(
        "--store-dir",
        default="/srv/codex-persistent/shared",
        help="Persistent Codex history directory on the local host",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Only print provider state and the inferred target provider",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite metadata to a single target provider",
    )
    parser.add_argument(
        "--target-provider",
        help=(
            "Explicit provider value to write. If omitted, use the provider from "
            "the newest open session, or else the newest thread in state_5.sqlite."
        ),
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create a backup before rewriting metadata",
    )
    parser.add_argument(
        "--skip-open-sessions",
        action="store_true",
        default=True,
        help=(
            "Do not rewrite session files that are currently open by a Codex "
            "process. This is enabled by default."
        ),
    )
    parser.add_argument(
        "--rewrite-open-sessions",
        action="store_true",
        help="Allow rewriting open session files. Use only when Codex is stopped.",
    )
    args = parser.parse_args()
    if not args.inspect and not args.apply:
        parser.error("Use --inspect or --apply.")
    if args.skip_open_sessions and args.rewrite_open_sessions:
        parser.error("Use only one of --skip-open-sessions or --rewrite-open-sessions.")
    if args.rewrite_open_sessions:
        args.skip_open_sessions = False
    return args


def read_session_provider(path: Path) -> str | None:
    with path.open("r", encoding="utf-8") as handle:
        first = handle.readline().strip()
    if not first:
        return None
    obj = json.loads(first)
    return obj.get("payload", {}).get("model_provider")


def inspect_session_counts(sessions_root: Path) -> Counter[str | None]:
    counts: Counter[str | None] = Counter()
    for path in sessions_root.rglob("*.jsonl"):
        counts[read_session_provider(path)] += 1
    return counts


def inspect_thread_counts(state_db: Path) -> list[tuple[str, int]]:
    conn = sqlite3.connect(state_db)
    try:
        cur = conn.cursor()
        cur.execute(
            "select model_provider, count(*) "
            "from threads group by model_provider order by count(*) desc, model_provider"
        )
        return [(row[0], row[1]) for row in cur.fetchall()]
    finally:
        conn.close()


def newest_thread_provider(state_db: Path) -> str | None:
    conn = sqlite3.connect(state_db)
    try:
        cur = conn.cursor()
        cur.execute(
            "select model_provider from threads "
            "order by updated_at desc limit 1"
        )
        row = cur.fetchone()
        return None if row is None else row[0]
    finally:
        conn.close()


def open_session_paths(sessions_root: Path) -> set[Path]:
    if shutil.which("lsof") is None:
        return set()
    cmd = ["lsof", "-Fn", "+D", str(sessions_root)]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise SystemExit(result.stderr.strip() or "lsof failed")
    paths = set()
    for line in result.stdout.splitlines():
        if not line.startswith("n"):
            continue
        candidate = Path(line[1:])
        if candidate.suffix == ".jsonl":
            paths.add(candidate)
    return paths


def newest_open_session_provider(sessions_root: Path) -> tuple[str | None, Path | None]:
    open_paths = open_session_paths(sessions_root)
    candidates: list[tuple[int, Path]] = []
    for path in open_paths:
        try:
            candidates.append((path.stat().st_mtime_ns, path))
        except FileNotFoundError:
            continue
    candidates.sort(reverse=True)
    for _, path in candidates:
        provider = read_session_provider(path)
        if provider:
            return provider, path
    return None, None


def infer_target_provider(state_db: Path, sessions_root: Path) -> tuple[str, str]:
    provider, path = newest_open_session_provider(sessions_root)
    if provider:
        return provider, f"newest open session: {path}"
    provider = newest_thread_provider(state_db)
    if provider:
        return provider, "newest thread in state_5.sqlite"
    raise SystemExit("Could not infer a target provider from sessions or threads.")


def backup_store(store_dir: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = store_dir.parent / f"provider-repair-backup-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    state_db = store_dir / "state_5.sqlite"
    src = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)
    dst = sqlite3.connect(str(backup_dir / "state_5.sqlite"))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    shutil.copytree(store_dir / "sessions", backup_dir / "sessions")
    return backup_dir


def rewrite_first_line(path: Path, new_provider: str) -> bool:
    with path.open("r", encoding="utf-8") as handle:
        lines = handle.readlines()
    if not lines:
        return False

    first = json.loads(lines[0])
    payload = first.get("payload", {})
    if payload.get("model_provider") == new_provider:
        return False

    payload["model_provider"] = new_provider
    first["payload"] = payload
    lines[0] = json.dumps(first, ensure_ascii=False, separators=(",", ":")) + "\n"

    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.writelines(lines)
        shutil.copymode(path, tmp_path)
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return True


def apply_changes(
    store_dir: Path,
    target_provider: str,
    skip_open_sessions: bool,
) -> tuple[int, int, int]:
    state_db = store_dir / "state_5.sqlite"
    sessions_root = store_dir / "sessions"
    open_paths = open_session_paths(sessions_root) if skip_open_sessions else set()

    conn = sqlite3.connect(state_db, timeout=30)
    try:
        cur = conn.cursor()
        cur.execute(
            "update threads set model_provider=? where model_provider<>?",
            (target_provider, target_provider),
        )
        threads_updated = cur.rowcount
        conn.commit()
    finally:
        conn.close()

    sessions_updated = 0
    sessions_skipped = 0
    for path in sessions_root.rglob("*.jsonl"):
        if path in open_paths:
            sessions_skipped += 1
            continue
        if rewrite_first_line(path, target_provider):
            sessions_updated += 1
    return threads_updated, sessions_updated, sessions_skipped


def main() -> int:
    args = parse_args()
    store_dir = Path(args.store_dir)
    state_db = store_dir / "state_5.sqlite"
    sessions_root = store_dir / "sessions"

    if not state_db.exists():
        raise SystemExit(f"Missing state database: {state_db}")
    if not sessions_root.exists():
        raise SystemExit(f"Missing sessions directory: {sessions_root}")

    target_provider = args.target_provider
    target_reason = "explicit --target-provider"
    if target_provider is None:
        target_provider, target_reason = infer_target_provider(state_db, sessions_root)

    print("TARGET_PROVIDER", target_provider)
    print("TARGET_REASON", target_reason)
    print("THREAD_PROVIDER_COUNTS")
    for row in inspect_thread_counts(state_db):
        print(row)
    print("SESSION_PROVIDER_COUNTS")
    for item in inspect_session_counts(sessions_root).most_common():
        print(item)
    print("OPEN_SESSION_FILES", len(open_session_paths(sessions_root)))

    if args.inspect:
        return 0

    if args.backup:
        backup_dir = backup_store(store_dir)
        print("BACKUP_DIR", backup_dir)

    threads_updated, sessions_updated, sessions_skipped = apply_changes(
        store_dir=store_dir,
        target_provider=target_provider,
        skip_open_sessions=args.skip_open_sessions,
    )
    print("THREADS_UPDATED", threads_updated)
    print("SESSION_FILES_UPDATED", sessions_updated)
    print("SESSION_FILES_SKIPPED", sessions_skipped)
    print("THREAD_PROVIDER_COUNTS_AFTER")
    for row in inspect_thread_counts(state_db):
        print(row)
    print("SESSION_PROVIDER_COUNTS_AFTER")
    for item in inspect_session_counts(sessions_root).most_common():
        print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
