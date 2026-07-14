"""Contract/golden pins for AG3-131 permission entities and HTTP bindings."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from agentkit.backend.governance.ccag.permission_records import (
    PermissionLeaseRecord,
    PermissionRequestRecord,
)

_ROOT = Path(__file__).parents[3]
_FORMAL_ROOT = _ROOT / "concept" / "formal-spec" / "principal-capabilities"
_CATALOG = _ROOT / "concept" / "technical-design" / "91_api_event_katalog.md"


def _formal_items(filename: str, key: str) -> list[dict[str, object]]:
    text = (_FORMAL_ROOT / filename).read_text(encoding="utf-8")
    match = re.search(r"```yaml\n(.*?)```", text, re.DOTALL)
    assert match is not None
    document = yaml.safe_load(match.group(1))
    return list(document[key])


def test_permission_record_fields_equal_formal_entity_goldens() -> None:
    entities = {str(item["id"]): item for item in _formal_items("entities.md", "entities")}
    request = entities["principal-capabilities.entity.permission-request"]
    lease = entities["principal-capabilities.entity.permission-lease"]
    request_fields = {"request_id", *request["attributes"]}  # type: ignore[misc]
    lease_fields = {"lease_id", *lease["attributes"]}  # type: ignore[misc]
    assert set(PermissionRequestRecord.model_fields) == request_fields
    assert set(PermissionLeaseRecord.model_fields) == lease_fields


def test_permission_command_signatures_match_rest_auth_golden() -> None:
    commands = {
        str(item["id"]): str(item["signature"])
        for item in _formal_items("commands.md", "commands")
    }
    assert commands["principal-capabilities.command.open-permission-request"] == (
        "POST /v1/governance/permission-requests operation open with matching "
        "project_api_token"
    )
    assert commands["principal-capabilities.command.grant-permission-lease"] == (
        "POST /v1/governance/permission-leases operation grant with strategist session"
    )
    assert commands["principal-capabilities.command.consume-permission-lease"] == (
        "POST /v1/governance/permission-leases operation consume with matching "
        "project_api_token"
    )


def test_fk91_catalog_pins_permission_endpoint_rows() -> None:
    catalog = _CATALOG.read_text(encoding="utf-8")
    assert "| `/v1/governance/permission-requests` | `GET` |" in catalog
    assert "| `/v1/governance/permission-requests` | `POST` |" in catalog
    assert "| `/v1/governance/permission-leases` | `POST` |" in catalog
