"""Re-Export-Verbot fuer PROTECTED_QA_ARTIFACTS-Liste (AG3-023 §2.1.5.2).

Kanonischer Import ist ausschliesslich:
    from agentkit.governance.guard_system.protected_paths import (
        PROTECTED_QA_ARTIFACTS, LAYER_ARTIFACT_FILES, VERIFY_DECISION_FILE,
    )

Diese Tests stellen sicher, dass kein Deprecation-Shim am Alt-Ort oder
am BC-Top-Level zurueckkehrt (Zero Debt).
"""

from __future__ import annotations

import pytest


class TestNoLegacyReexport:
    """AG3-023 §2.1.5.2 — alte Importpfade muessen ImportError werfen."""

    def test_state_backend_paths_export_is_gone(self) -> None:
        from agentkit.state_backend import paths as state_paths

        for name in ("PROTECTED_QA_ARTIFACTS", "LAYER_ARTIFACT_FILES", "VERIFY_DECISION_FILE"):
            assert not hasattr(state_paths, name), (
                f"{name!r} darf nicht aus agentkit.state_backend.paths importierbar sein "
                "(Re-Export-Verbot)."
            )

    def test_no_bc_toplevel_reexport_in_governance(self) -> None:
        # Kein Re-Export aus governance/__init__.py
        from agentkit import governance

        for name in ("PROTECTED_QA_ARTIFACTS", "LAYER_ARTIFACT_FILES", "VERIFY_DECISION_FILE"):
            assert not hasattr(governance, name), (
                f"{name!r} darf nicht aus agentkit.governance Top-Level importierbar sein."
            )

    def test_no_legacy_module_governance_protected_paths(self) -> None:
        with pytest.raises(ModuleNotFoundError):
            __import__("agentkit.governance.protected_paths")

    def test_canonical_import_succeeds(self) -> None:
        from agentkit.governance.guard_system.protected_paths import (
            LAYER_ARTIFACT_FILES,
            PROTECTED_QA_ARTIFACTS,
            VERIFY_DECISION_FILE,
        )

        assert isinstance(PROTECTED_QA_ARTIFACTS, tuple)
        assert isinstance(LAYER_ARTIFACT_FILES, dict)
        assert isinstance(VERIFY_DECISION_FILE, str)
