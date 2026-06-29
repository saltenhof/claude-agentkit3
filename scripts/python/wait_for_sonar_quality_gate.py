#!/usr/bin/env python3
"""Wait for the SonarQube quality gate of the CURRENT analysis.

The scanner writes ``report-task.txt`` with the Compute Engine task id of the
analysis it just submitted. This script waits for that task to finish and then
reads the quality gate for exactly that analysis (``analysisId``).

This avoids the race where ``api/qualitygates/project_status?projectKey=...``
returns the *previous* analysis' status while the new analysis is still being
processed by the Compute Engine — which would make the gate check report a
stale OK/ERROR and fail (or pass) builds non-deterministically.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CE_STATUS_SUCCESS = "SUCCESS"
CE_STATUS_TERMINAL_FAILURES = {"FAILED", "CANCELED"}
GATE_FINAL_STATUSES = {"OK", "ERROR", "WARN"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wait for a SonarQube quality gate result.",
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--project-key", required=True)
    parser.add_argument("--token", default=os.environ.get("SONAR_AUTH_TOKEN", ""))
    parser.add_argument("--report-task-path", default=".scannerwork/report-task.txt")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-seconds", type=int, default=5)
    return parser.parse_args()


def _auth_header(token: str) -> dict[str, str]:
    if not token:
        return {}
    basic = base64.b64encode(f"{token}:".encode()).decode()
    return {"Authorization": f"Basic {basic}"}


def _get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(url, headers=_auth_header(token))
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _read_ce_task_id(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "ceTaskId":
            return value.strip()
    return None


def _wait_for_analysis_id(
    host: str, task_id: str, token: str, deadline: float, poll_seconds: int
) -> str:
    query = urllib.parse.urlencode({"id": task_id})
    url = f"{host.rstrip('/')}/api/ce/task?{query}"
    while time.monotonic() < deadline:
        try:
            task = _get_json(url, token)["task"]
        except (KeyError, urllib.error.URLError, TimeoutError) as exc:
            print(f"sonar ce task poll failed: {exc}", file=sys.stderr)
            time.sleep(poll_seconds)
            continue

        status = str(task.get("status", "")).upper()
        print(f"sonar ce task status: {status}")
        if status == CE_STATUS_SUCCESS:
            analysis_id = task.get("analysisId")
            if not analysis_id:
                raise SystemExit("sonar ce task reported SUCCESS without an analysisId")
            return str(analysis_id)
        if status in CE_STATUS_TERMINAL_FAILURES:
            raise SystemExit(f"sonar ce task did not succeed: {status}")
        time.sleep(poll_seconds)

    raise SystemExit("timed out waiting for the SonarQube compute-engine task")


def _gate_status(host: str, query: dict[str, str], token: str) -> str:
    url = f"{host.rstrip('/')}/api/qualitygates/project_status?{urllib.parse.urlencode(query)}"
    return str(_get_json(url, token)["projectStatus"]["status"]).upper()


def _resolve_gate_status(args: argparse.Namespace, deadline: float) -> str:
    task_id = _read_ce_task_id(Path(args.report_task_path))
    if task_id:
        analysis_id = _wait_for_analysis_id(
            args.host, task_id, args.token, deadline, args.poll_seconds
        )
        return _gate_status(args.host, {"analysisId": analysis_id}, args.token)

    print(
        f"report-task file {args.report_task_path!r} not found; "
        "falling back to project-level gate polling",
        file=sys.stderr,
    )
    while time.monotonic() < deadline:
        try:
            status = _gate_status(args.host, {"projectKey": args.project_key}, args.token)
        except (KeyError, urllib.error.URLError, TimeoutError) as exc:
            print(f"sonar quality gate poll failed: {exc}", file=sys.stderr)
            time.sleep(args.poll_seconds)
            continue
        if status in GATE_FINAL_STATUSES:
            return status
        time.sleep(args.poll_seconds)

    raise SystemExit("timed out waiting for the SonarQube quality gate")


def main() -> int:
    args = parse_args()
    deadline = time.monotonic() + args.timeout_seconds
    status = _resolve_gate_status(args, deadline)
    print(f"sonar quality gate status: {status}")
    return 0 if status == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
