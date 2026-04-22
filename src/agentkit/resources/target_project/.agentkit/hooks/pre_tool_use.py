"""Project-local pre-tool hook wrapper."""

from __future__ import annotations

from agentkit.governance.hookruntime import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
