"""Immutable vocabulary and identifier patterns for the concept run model."""

from __future__ import annotations

import re


class RunModelConstants:
    """One cohesive namespace for the immutable run-model vocabulary.

    A class, not 60 module-level names: the vocabulary belongs together and
    is addressed as one namespace. Every attribute stays statically
    resolvable -- unlike the dynamic module ``__getattr__`` this replaced,
    which typed every constant as ``Any`` and turned a typo into a runtime
    error.
    """

    SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
    TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")
    RUN_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*-[0-9a-f]{8}$")
    PARTICIPANT_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
    PRINCIPAL_ID_RE = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*$")
    UNIT_ID_RE = re.compile(r"^SU-[0-9a-f]{8}-\d{4,}$")
    CLAIM_ID_RE = re.compile(r"^CLM-[0-9a-f]{8}-\d{4,}$")
    ATOM_ID_RE = re.compile(r"^ATM-[0-9a-f]{8}-\d{4,}$")
    RECEIPT_ID_RE = re.compile(r"^RCP-[0-9a-f]{8}-\d{4,}$")
    PACKAGE_ID_RE = re.compile(r"^PKG-[0-9a-f]{8}-\d{2,}$")
    FINDING_ID_RE = re.compile(r"^FND-[0-9a-f]{8}-\d{4,}$")
    SOURCE_ID_RE = re.compile(r"^SRC-[0-9a-f]{8}-\d{4,}$")
    ACTION_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
    ARRAY_REQUIRED = "must be an array"
    PRINCIPAL_ID_LABEL = "principal id"
    SOURCE_ID_LABEL = "source id"
    PACKAGE_ID_LABEL = "package id"
    PARTICIPANT_ID_LABEL = "participant id"
    RUN_ID_LABEL = "run id"
    ATOM_ID_LABEL = "atom id"
    RECEIPT_ID_LABEL = "receipt id"
    GIT_OBJECT_ID_LABEL = "git object id"
    CLAIM_ID_LABEL = "claim id"
    FINDING_ID_LABEL = "finding id"
    LEASE_OWNER_LOCATOR = "lease.owner"
    ROUND_SEAL_LOCATOR = "round.seal"
    RECEIPT_TARGET_LOCATOR = "receipt.target"

    RUN_STATES = (
        "FRAMING",
        "STAFFING",
        "PROPOSING",
        "CONVERGING",
        "SYNTHESIZING",
        "DECIDING",
        "PROMOTING",
        "PROMOTION_FAILED",
        "BLOCKED",
        "RECHECK",
        "CLOSED",
        "ABORTED",
    )
    LINEAR_STATE_RANK = {
        "FRAMING": 0,
        "STAFFING": 1,
        "PROPOSING": 2,
        "CONVERGING": 3,
        "SYNTHESIZING": 4,
        "DECIDING": 5,
        "PROMOTING": 6,
        "CLOSED": 7,
    }
    RUN_PROFILES = ("LIGHT_INCUBATION", "FULL_ATOM")
    DATA_CLASSES = ("open", "internal", "sensitive")
    SPAWN_MODES = ("harness-bridge", "llm-hub", "subagent", "cli-resume")
    PARTICIPANT_STATUSES = ("active", "failed", "replaced", "withdrawn")
    ROUND_OUTCOMES = ("received", "timeout", "failed", "excluded")
    BASE_REVISION_KINDS = ("git", "digest")
    REGISTER_DIGEST_KEYS = (
        "corpus_baseline",
        "source_intake_input_head",
        "source_intake_final_head",
        "source_register_input",
        "source_units_input",
        "claims_inventory_input",
        "derived_claims",
        "disposition_ledger",
        "source_register_final",
        "source_units_final",
        "atom_register",
    )
    SOURCE_PHASES = ("input", "derived")
    SOURCE_ROLES = (
        "BRIEFING",
        "PROPOSAL",
        "SYNTHESIS",
        "DISSENT_MAP",
        "PO_DECISION",
        "NORMATIVE_BASELINE",
        "EVIDENCE",
    )
    REVIEW_STATUSES = ("PASS", "PASS_WITH_GAPS", "FAIL", "N_A")
    CHANGE_KINDS = ("unchanged", "modified", "added", "removed")
    ARTIFACT_KINDS = (
        "briefing",
        "proposal",
        "synthesis",
        "dissent_map",
        "inventory",
        "ledger",
        "atom_register",
        "manifest",
        "receipt",
        "round_state",
        "coverage",
        "finding",
        "journal",
        "other",
    )
    VCS_DISPOSITIONS = ("versioned", "local")
    FINDING_SEVERITIES = ("P0", "P1", "P2")
    FINDING_STATUSES = ("open", "resolved", "accepted_by_po")
    SYNTHESIS_DISPOSITIONS = (
        "ADOPTED",
        "MERGED",
        "SUPERSEDED_BY_CLAIM",
        "REJECTED_WITH_REASON",
        "OPEN_QUESTION",
    )
    ATOM_TYPES = (
        "REQUIREMENT",
        "DOMAIN_FACT",
        "DECISION",
        "RATIONALE",
        "EVIDENCE",
        "PARAMETER_CANDIDATE",
        "REJECTION",
        "OPEN_QUESTION",
    )
    NORMATIVE_STATUSES = ("proposal", "accepted", "evidence", "rejected", "open")
    ATOM_DISPOSITIONS = (
        "COVERED_EXACT",
        "COVERED_SPLIT",
        "REJECTED",
        "OPEN_MISSING",
        "DEFERRED_BACKLOG",
        "EVIDENCE_ONLY",
        "OUT_OF_AUDIT",
        "SUPERSEDED",
    )
    COVERED_DISPOSITIONS = ("COVERED_EXACT", "COVERED_SPLIT")
    PROMOTION_DISPOSITIONS = ("promoted", "rejected", "deferred")
    SEMANTIC_GATES = ("authority-prose", "scope-consistency")
    SEMANTIC_GATE_KEYS = {"w2": "authority-prose", "w3": "scope-consistency"}
    SEMANTIC_GATE_STATUSES = ("passed", "blocked", "not_run")
    SEMANTIC_RECEIPT_STATUSES = ("passed", "failed")
    RECEIPT_VERDICTS = ("equivalent", "disagrees")
    LOCK_BACKENDS = ("filesystem", "git-remote")
    LIFECYCLES = ("current", "draft", "deprecated", "superseded")
    ASSERTION_STATUSES = (
        "draft",
        "active",
        "blocked_projection",
        "deprecated",
        "superseded",
    )
    EQUIVALENCE_STATUSES = (
        "unreviewed",
        "equivalent",
        "disagrees",
        "stale",
        "blocked_missing_target",
    )
    PROJECTION_KINDS = ("formal", "prose", "registry", "support", "test-oracle")
    DECISION_STATUSES = ("proposed", "accepted", "rejected", "superseded")
    SCOPE_NORMALIZE_RE = re.compile(r"[._-]+")
