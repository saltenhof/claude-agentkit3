"""Command line interface for the concept ingester."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from tools.concept_ingester.config import IngesterConfig
from tools.concept_ingester.discovery import discover
from tools.concept_ingester.ingester import (
    IngestStrategy,
    open_client,
    run_ingest,
)
from tools.concept_ingester.schema import (
    CHUNK_COLLECTION_NAME,
    GLOSSARY_COLLECTION_NAME,
    SCHEMA_PROJECTION_VERSION,
    drop_all_collections,
    ensure_all_collections,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="concept-ingester", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("full", help="Drop and re-create both collections, then ingest everything.")
    sub.add_parser("delta", help="Ingest only changed/new objects; delete objects no longer present.")
    sub.add_parser("status", help="Show local discovery and remote object counts.")
    sub.add_parser("ensure-schema", help="Create both collections if they do not exist.")
    drop = sub.add_parser("drop", help="Drop both collections. Destructive.")
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
            ensure_all_collections(client)
        _print_json(
            {
                "ensured": True,
                "collections": [CHUNK_COLLECTION_NAME, GLOSSARY_COLLECTION_NAME],
                "schema_projection_version": SCHEMA_PROJECTION_VERSION,
            }
        )
        return 0
    if args.command == "drop":
        if not args.yes:
            print("refusing to drop without --yes", file=sys.stderr)
            return 2
        with open_client(cfg) as client:
            existed = drop_all_collections(client)
        _print_json({"dropped": existed})
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


def _status(cfg: IngesterConfig) -> int:
    result = discover(cfg.concept_root, max_chars=cfg.chunk_max_chars)

    by_layer: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    cross_cutting_chunks = 0
    for chunk in result.chunks:
        by_layer[chunk.layer] = by_layer.get(chunk.layer, 0) + 1
        if chunk.cross_cutting:
            cross_cutting_chunks += 1
        elif chunk.domain:
            by_domain[chunk.domain] = by_domain.get(chunk.domain, 0) + 1

    glossary_by_kind: dict[str, int] = {}
    glossary_by_domain: dict[str, int] = {}
    for term in result.glossary_terms:
        glossary_by_kind[term.term_kind] = glossary_by_kind.get(term.term_kind, 0) + 1
        if term.domain:
            glossary_by_domain[term.domain] = glossary_by_domain.get(term.domain, 0) + 1

    payload: dict[str, object] = {
        "concept_root": str(cfg.concept_root),
        "schema_projection_version": result.schema_projection_version,
        "domain_registry_hash": result.domain_registry_hash,
        "discovered": {
            "chunks": {
                "total": len(result.chunks),
                "by_layer": by_layer,
                "by_domain": by_domain,
                "cross_cutting": cross_cutting_chunks,
            },
            "glossary_terms": {
                "total": len(result.glossary_terms),
                "by_kind": glossary_by_kind,
                "by_domain": glossary_by_domain,
            },
        },
    }
    try:
        with open_client(cfg) as client:
            ensure_all_collections(client)
            chunk_count = (
                client.collections.get(CHUNK_COLLECTION_NAME)
                .aggregate.over_all(total_count=True)
                .total_count
            )
            glossary_count = (
                client.collections.get(GLOSSARY_COLLECTION_NAME)
                .aggregate.over_all(total_count=True)
                .total_count
            )
            payload["remote"] = {
                "collections": {
                    CHUNK_COLLECTION_NAME: {"exists": True, "total_count": chunk_count},
                    GLOSSARY_COLLECTION_NAME: {"exists": True, "total_count": glossary_count},
                }
            }
    except Exception as exc:  # noqa: BLE001 - status is read-only diagnostic
        payload["remote"] = {"error": str(exc)}
    _print_json(payload)
    return 0


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CHUNK_COLLECTION_NAME", "GLOSSARY_COLLECTION_NAME", "main"]
