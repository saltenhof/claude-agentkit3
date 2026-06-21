"""Deterministic integrity-hash computation for the Sonar attestation.

FK-33 §33.6.3 NAMES the commit-bound attestation's integrity bindings
(quality-gate hash, quality-profile hash, analysis-scope hash) and the tool
versions, but pins NO hash recipe and NO specific endpoint per field. This
module is the ONE place that computes those hashes deterministically from
AUTHORITATIVE SonarQube Web-API data, so both AG3-052's gate adapter and the
AG3-056 pre-merge scan runner share a single attestation-construction truth
(no second Sonar truth, FIX-4 / ERROR-B).

The real SonarQube ``api/qualitygates/project_status`` response carries ONLY
``projectStatus.{status,conditions,periods,...}`` — it does NOT expose any
``qualityGateHash``/``qualityProfileHash``/``analysisScopeHash``/
``scannerVersion`` field (the predecessor bug read those non-existent keys, so
only fakes that invented them passed). The integrity hashes are therefore
COMPUTED here from the endpoints that actually expose the underlying
definitions:

* quality-gate hash  <- ``api/qualitygates/get_by_project`` (the gate the
  project is bound to) + ``api/qualitygates/show`` (its conditions:
  metric/op/error threshold);
* quality-profile hash <- ``api/qualityprofiles/search?project=<key>`` (per
  language: profile key + ``rulesUpdatedAt``/``lastUsed``);
* analysis-scope hash  <- ``api/settings/values?component=<key>`` for the
  scope keys (sources/tests/inclusions/exclusions/coverage exclusions).

Each hash is a SHA-256 over a CANONICAL, ORDER-INDEPENDENT serialization of
the authoritative values (JSON with sorted keys, lists sorted by a stable key)
so the same configuration always yields the same digest regardless of the
order Sonar happened to return the entries in. Any required authoritative read
that is unreachable/absent fails closed via :class:`SonarApiError` — a
"produced" attestation never carries an empty/placeholder integrity hash.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from agentkit.integration_clients.sonar import SonarApiError

if TYPE_CHECKING:
    from agentkit.integration_clients.sonar import SonarClient

#: Analysis-scope setting keys hashed for the analysis-scope binding. These are
#: the SonarQube settings that define WHAT was analysed; a drift in any of them
#: changes the meaning of a green gate, so they are bound into the attestation.
SCOPE_SETTING_KEYS: tuple[str, ...] = (
    "sonar.sources",
    "sonar.tests",
    "sonar.inclusions",
    "sonar.exclusions",
    "sonar.test.inclusions",
    "sonar.test.exclusions",
    "sonar.coverage.exclusions",
)


def _sha256_canonical(material: Any) -> str:
    """Return the SHA-256 hex digest of a canonical JSON serialization.

    The material is serialized with ``sort_keys=True`` and compact separators
    so the digest is independent of dict insertion order. Callers are
    responsible for making any *list* order canonical (e.g. sorting condition
    entries) before passing the material in.

    Args:
        material: A JSON-serializable structure (already list-order-canonical).

    Returns:
        64-char lowercase SHA-256 hex digest.
    """
    canonical = json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_quality_gate_hash(client: SonarClient, project_key: str) -> str:
    """Compute the quality-gate hash from the project's active gate definition.

    Reads the gate the project is bound to (``api/qualitygates/get_by_project``)
    and that gate's conditions (``api/qualitygates/show``), then hashes a
    canonical, order-independent view of ``{name, conditions:[{metric,op,error}]}``.

    Args:
        client: Thin ``integrations.sonar`` client (scoped token).
        project_key: The Sonar project/component key.

    Returns:
        The deterministic quality-gate hash.

    Raises:
        SonarApiError: When the gate or its conditions cannot be sourced
            authoritatively (fail-closed; never an empty hash).
    """
    gate_body = client.qualitygates_get_by_project(project_key).json_body
    gate = gate_body.get("qualityGate")
    if not isinstance(gate, dict):
        raise SonarApiError(
            "qualitygates/get_by_project returned no qualityGate object for "
            f"project={project_key!r} (cannot bind quality_gate_hash; fail-closed)"
        )
    gate_name = gate.get("name")
    if not isinstance(gate_name, str) or not gate_name:
        raise SonarApiError(
            "qualitygates/get_by_project returned no qualityGate.name for "
            f"project={project_key!r} (fail-closed)"
        )
    show_body = client.qualitygates_show(gate_name).json_body
    raw_conditions = show_body.get("conditions")
    conditions: list[dict[str, str]] = []
    if isinstance(raw_conditions, list):
        for entry in raw_conditions:
            if isinstance(entry, dict):
                conditions.append(
                    {
                        "metric": _required_str(entry, "metric", "qualitygates/show"),
                        "op": _optional_str(entry, "op"),
                        "error": _optional_str(entry, "error"),
                    }
                )
    conditions.sort(key=lambda c: (c["metric"], c["op"], c["error"]))
    return _sha256_canonical({"name": gate_name, "conditions": conditions})


def compute_quality_profile_hash(client: SonarClient, project_key: str) -> str:
    """Compute the quality-profile hash from the project's active profiles.

    Reads the project's active profiles (``api/qualityprofiles/search?project``)
    and hashes a canonical, order-independent view of one entry per language:
    ``{language, key, rulesUpdatedAt, lastUsed}``. A rules update or a profile
    swap changes the digest (config drift detection, FK-33 §33.6.3).

    Args:
        client: Thin ``integrations.sonar`` client (scoped token).
        project_key: The Sonar project/component key.

    Returns:
        The deterministic quality-profile hash.

    Raises:
        SonarApiError: When the profiles cannot be sourced authoritatively
            (fail-closed; never an empty hash).
    """
    body = client.qualityprofiles_search(project_key).json_body
    raw_profiles = body.get("profiles")
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise SonarApiError(
            "qualityprofiles/search returned no profiles for "
            f"project={project_key!r} (cannot bind quality_profile_hash; "
            "fail-closed)"
        )
    profiles: list[dict[str, str]] = []
    for entry in raw_profiles:
        if not isinstance(entry, dict):
            continue
        profiles.append(
            {
                "language": _required_str(entry, "language", "qualityprofiles/search"),
                "key": _required_str(entry, "key", "qualityprofiles/search"),
                "rulesUpdatedAt": _optional_str(entry, "rulesUpdatedAt"),
                "lastUsed": _optional_str(entry, "lastUsed"),
            }
        )
    if not profiles:
        raise SonarApiError(
            "qualityprofiles/search carried no usable profile entries for "
            f"project={project_key!r} (fail-closed)"
        )
    profiles.sort(key=lambda p: (p["language"], p["key"]))
    return _sha256_canonical(profiles)


def compute_analysis_scope_hash(client: SonarClient, project_key: str) -> str:
    """Compute the analysis-scope hash from the project's scope settings.

    Reads the scope settings (``api/settings/values?component=<key>`` for
    :data:`SCOPE_SETTING_KEYS`) and hashes a canonical, order-independent view
    of each present key's value(s). The single-valued (``value``), multi-valued
    (``values``) and field-valued (``fieldValues``) shapes the settings API
    returns are all normalised; absent keys are simply omitted (an unset scope
    setting is part of the canonical scope, recorded as not-present).

    Args:
        client: Thin ``integrations.sonar`` client (scoped token).
        project_key: The Sonar project/component key.

    Returns:
        The deterministic analysis-scope hash.

    Raises:
        SonarApiError: When the settings cannot be sourced authoritatively
            (fail-closed; never an empty hash).
    """
    body = client.settings_values(
        component=project_key, keys=SCOPE_SETTING_KEYS
    ).json_body
    raw_settings = body.get("settings")
    if not isinstance(raw_settings, list):
        raise SonarApiError(
            "settings/values returned no settings array for "
            f"component={project_key!r} (cannot bind analysis_scope_hash; "
            "fail-closed)"
        )
    scope: dict[str, Any] = {}
    wanted = set(SCOPE_SETTING_KEYS)
    for entry in raw_settings:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if not isinstance(key, str) or key not in wanted:
            continue
        scope[key] = _normalize_setting_value(entry)
    return _sha256_canonical(scope)


def _normalize_setting_value(entry: dict[str, Any]) -> Any:
    """Normalise one settings entry to an order-independent canonical value."""
    if "value" in entry and isinstance(entry["value"], str):
        return {"value": entry["value"]}
    values = entry.get("values")
    if isinstance(values, list):
        return {"values": sorted(str(v) for v in values)}
    field_values = entry.get("fieldValues")
    if isinstance(field_values, list):
        canonical_fields = [
            {str(k): str(v) for k, v in field.items()}
            for field in field_values
            if isinstance(field, dict)
        ]
        canonical_fields.sort(key=lambda f: json.dumps(f, sort_keys=True))
        return {"fieldValues": canonical_fields}
    return {}


def _required_str(entry: dict[str, Any], key: str, endpoint: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise SonarApiError(
            f"{endpoint} entry carried no {key!r} (fail-closed; cannot bind a "
            "complete integrity hash)"
        )
    return value


def _optional_str(entry: dict[str, Any], key: str) -> str:
    value = entry.get(key)
    return value if isinstance(value, str) else ""


__all__ = [
    "SCOPE_SETTING_KEYS",
    "compute_analysis_scope_hash",
    "compute_quality_gate_hash",
    "compute_quality_profile_hash",
]
