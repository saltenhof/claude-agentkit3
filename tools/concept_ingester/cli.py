"""Command line interface for the concept ingester."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from tools.concept_ingester.config import IngesterConfig
from tools.concept_ingester.discovery import discover_chunks
from tools.concept_ingester.ingester import (
    IngestStrategy,
    open_client,
    run_ingest,
)
from tools.concept_ingester.schema import (
    COLLECTION_NAME,
    drop_collection,
    ensure_collection,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="concept-ingester", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("full", help="Drop and re-create the collection, then ingest everything.")
    sub.add_parser("delta", help="Ingest only changed/new chunks; delete chunks no longer present.")
    sub.add_parser("status", help="Show local discovery and remote chunk counts.")
    sub.add_parser("ensure-schema", help="Create the collection if it does not exist.")
    drop = sub.add_parser("drop", help="Drop the collection. Destructive.")
    drop.add_argument("--yes", action="store_true", help="Confirm destructive operation.")

    args = parser.parse_args(argv)
    cfg = IngesterConfig.from_env()

    if args.command == "full":
        report = run_ingest(IngestStrategy.FULL, cfg)
        _print_json(report.as_dict())
        return 0 if not report.errors else 1
    if args.command == "delta":
        report = run_ingest(IngestStrategy.DELTA, cfg)
        _print_json(report.as_dict())
        return 0 if not report.errors else 1
    if args.command == "status":
        return _status(cfg)
    if args.command == "ensure-schema":
        with open_client(cfg) as client:
            ensure_collection(client, cfg.collection_name)
        _print_json({"collection": cfg.collection_name, "ensured": True})
        return 0
    if args.command == "drop":
        if not args.yes:
            print("refusing to drop without --yes", file=sys.stderr)
            return 2
        with open_client(cfg) as client:
            existed = drop_collection(client, cfg.collection_name)
        _print_json({"collection": cfg.collection_name, "dropped": existed})
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


def _status(cfg: IngesterConfig) -> int:
    chunks = discover_chunks(cfg.concept_root, max_chars=cfg.chunk_max_chars)
    by_layer: dict[str, int] = {}
    for chunk in chunks:
        by_layer[chunk.layer] = by_layer.get(chunk.layer, 0) + 1
    payload: dict[str, object] = {
        "concept_root": str(cfg.concept_root),
        "collection": cfg.collection_name,
        "discovered": {
            "total": len(chunks),
            "by_layer": by_layer,
        },
    }
    try:
        with open_client(cfg) as client:
            ensure_collection(client, cfg.collection_name)
            collection = client.collections.get(cfg.collection_name)
            count = collection.aggregate.over_all(total_count=True).total_count
            payload["remote"] = {"collection_exists": True, "total_count": count}
    except Exception as exc:  # noqa: BLE001 - status is read-only diagnostic
        payload["remote"] = {"error": str(exc)}
    _print_json(payload)
    return 0


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["COLLECTION_NAME", "main"]
