"""Pipeline-engine integration fixtures (AG3-176 offline installer seams)."""

from __future__ import annotations

import pytest
from tests.support.installer_offline_stubs import install_offline_vectordb_stubs


@pytest.fixture(autouse=True)
def _offline_vectordb_installer_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    install_offline_vectordb_stubs(monkeypatch)
