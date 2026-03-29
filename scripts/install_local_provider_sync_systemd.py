#!/usr/bin/env python3
"""Install a systemd timer that normalizes local Codex provider metadata."""

from __future__ import annotations

import argparse
import shlex
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install and enable a systemd service/timer that keeps Codex history "
            "visible after provider switches on the local Linux host."
        )
    )
    parser.add_argument(
        "--store-dir",
        default="/srv/codex-persistent/shared",
        help="Persistent Codex history directory on the local host",
    )
    parser.add_argument(
        "--systemd-dir",
        default="/etc/systemd/system",
        help="Directory where systemd unit files should be written",
    )
    parser.add_argument(
        "--unit-prefix",
        default="codex-provider-sync",
        help="Prefix for the service and timer unit names",
    )
    parser.add_argument(
        "--interval",
        default="1min",
        help="systemd OnUnitActiveSec value for the timer",
    )
    parser.add_argument(
        "--target-provider",
        help=(
            "Optional explicit provider value. If omitted, the sync follows the "
            "newest open session or newest thread."
        ),
    )
    return parser.parse_args()


def build_exec(script_path: Path, store_dir: str, target_provider: str | None) -> str:
    parts = [
        "/usr/bin/env",
        "python3",
        str(script_path),
        "--store-dir",
        store_dir,
        "--apply",
    ]
    if target_provider:
        parts.extend(["--target-provider", target_provider])
    return shlex.join(parts)


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "sync_codex_provider_visibility_local.py"
    systemd_dir = Path(args.systemd_dir)
    service_name = f"{args.unit_prefix}.service"
    timer_name = f"{args.unit_prefix}.timer"
    service_path = systemd_dir / service_name
    timer_path = systemd_dir / timer_name
    exec_start = build_exec(script_path, args.store_dir, args.target_provider)

    service_body = f"""[Unit]
Description=Normalize Codex provider metadata in the persistent history store
ConditionPathExists={args.store_dir}/state_5.sqlite
ConditionPathExists={args.store_dir}/sessions

[Service]
Type=oneshot
ExecStart={exec_start}
"""

    timer_body = f"""[Unit]
Description=Run Codex provider metadata sync periodically

[Timer]
OnBootSec=30s
OnUnitActiveSec={args.interval}
AccuracySec=15s
Persistent=true
Unit={service_name}

[Install]
WantedBy=timers.target
"""

    systemd_dir.mkdir(parents=True, exist_ok=True)
    service_path.write_text(service_body, encoding="utf-8")
    timer_path.write_text(timer_body, encoding="utf-8")

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", timer_name], check=True)
    subprocess.run(["systemctl", "start", service_name], check=True)

    print("SERVICE_PATH", service_path)
    print("TIMER_PATH", timer_path)
    print("ENABLED_TIMER", timer_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
