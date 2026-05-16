"""Worker type definitions for spawn and coordination.

``SpawnReason`` wird seit AG3-021 aus ``agentkit.core_types``
re-exportiert. Die kanonische Definition liegt im Foundation-Modul;
diese Datei haelt nur den BC-Stable-Importpfad fuer Worker-Konsumenten.
"""

from __future__ import annotations

from agentkit.core_types import SpawnReason

__all__ = ["SpawnReason"]
