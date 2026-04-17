#!/usr/bin/env python3
"""Poll SonarQube until a project's quality gate has a final status."""

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

FINAL_STATUSES = {"OK", "ERROR", "WARN"}
PENDING_STATUSES = {"NONE", "PENDING", "IN_PROGRESS"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wait for a SonarQube quality gate result.",
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--project-key", required=True)
    parser.add_argument("--token", default=os.environ.get("SONAR_AUTH_TOKEN", ""))
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-seconds", type=int, default=5)
    return parser.parse_args()


def build_request(host: str, project_key: str, token: str) -> urllib.request.Request:
    query = urllib.parse.urlencode({"projectKey": project_key})
    url = f"{host.rstrip('/')}/api/qualitygates/project_status?{query}"
    request = urllib.request.Request(url)
    if token:
        basic = base64.b64encode(f"{token}:".encode()).decode()
        request.add_header("Authorization", f"Basic {basic}")
    return request


def load_status(host: str, project_key: str, token: str) -> str:
    request = build_request(host, project_key, token)
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return str(payload["projectStatus"]["status"]).upper()


def main() -> int:
    args = parse_args()
    deadline = time.monotonic() + args.timeout_seconds

    while time.monotonic() < deadline:
        try:
            status = load_status(args.host, args.project_key, args.token)
        except (KeyError, urllib.error.URLError, TimeoutError) as exc:
            print(f"sonar quality gate poll failed: {exc}", file=sys.stderr)
            time.sleep(args.poll_seconds)
            continue

        print(f"sonar quality gate status: {status}")
        if status == "OK":
            return 0
        if status in FINAL_STATUSES:
            return 1
        if status not in PENDING_STATUSES:
            print(f"unexpected quality gate status: {status}", file=sys.stderr)
            return 1
        time.sleep(args.poll_seconds)

    print("timed out waiting for SonarQube quality gate", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
