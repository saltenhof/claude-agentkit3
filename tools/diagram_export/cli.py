"""CLI: generate Mermaid + Draw.io exports for the FK-17 data model."""

from __future__ import annotations

import argparse
from pathlib import Path

from tools.diagram_export.ak3_data_model import render_drawio, render_mermaid

DEFAULT_OUT_DIR = Path(__file__).resolve().parents[2] / "concept" / "technical-design" / "diagrams"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Target directory for generated diagram files.",
    )
    args = parser.parse_args(argv)
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    mermaid_path = out_dir / "data-model.mmd"
    drawio_path = out_dir / "data-model.drawio"

    mermaid_path.write_text(render_mermaid(), encoding="utf-8")
    drawio_path.write_text(render_drawio(), encoding="utf-8")

    print(f"wrote {mermaid_path}")
    print(f"wrote {drawio_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
