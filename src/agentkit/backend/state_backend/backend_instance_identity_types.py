"""Backend instance identity record owned by state-backend infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

_MIN_INSTANCE_INCARNATION = 1


@dataclass(frozen=True)
class BackendInstanceIdentityRecord:
    """Persistent backend instance identity plus boot incarnation.

    Persistence for ``backend_instance_id`` plus a monotone boot incarnation
    counter (FK-91 §91.1a rule 16).

    Raises:
        ValueError: On an empty ``backend_instance_id`` or an
            ``instance_incarnation`` below the minimum.
    """

    backend_instance_id: str
    instance_incarnation: int
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.backend_instance_id.strip():
            raise ValueError("backend_instance_id must not be empty")
        if self.instance_incarnation < _MIN_INSTANCE_INCARNATION:
            raise ValueError(
                "instance_incarnation must be >= "
                f"{_MIN_INSTANCE_INCARNATION}, got {self.instance_incarnation!r}",
            )


__all__ = ("BackendInstanceIdentityRecord",)
