"""Compatibility surface for the control-plane runtime package."""

from __future__ import annotations

# Deliberate RUNTIME re-import (not TYPE_CHECKING): this is the SSOT re-import of
# the canonical FK-56 operating-mode literal from its SINGLE foundation definition
# (``core_types.operating_mode``). It must be a runtime binding so the
# single-definition identity holds for consumers (and is assertable) -- moving it
# into a type-checking block would make ``control_plane.runtime.OperatingMode`` a
# different/absent object at runtime, defeating the AK2 SSOT consolidation.
from agentkit.backend.core_types.operating_mode import OperatingMode as OperatingMode

from ._di import (
    _default_di_edge_command_repository as _default_di_edge_command_repository,
)
from ._di import (
    _require_postgres_control_plane_backend as _require_postgres_control_plane_backend,
)
from ._edge_bundles import (
    _next_binding_version as _next_binding_version,
)
from ._edge_bundles import (
    _resolve_operating_mode as _resolve_operating_mode,
)
from ._models import (
    MergePrecondition as MergePrecondition,
)
from ._models import (
    OperationNotAbortableError as OperationNotAbortableError,
)
from ._models import (
    OperationNotFoundError as OperationNotFoundError,
)
from ._operation_records import (
    _build_claim_placeholder as _build_claim_placeholder,
)
from ._operation_records import (
    _control_plane_request_body_hash as _control_plane_request_body_hash,
)
from ._operation_records import (
    _object_claim_busy_rejection as _object_claim_busy_rejection,
)
from ._operation_records import (
    _ownership_transferred_rejection as _ownership_transferred_rejection,
)
from ._operation_records import (
    _rejection_result as _rejection_result,
)
from ._ownership_transfer_commands import (
    TakeoverConfirmCommand as TakeoverConfirmCommand,
)
from ._ownership_transfer_commands import (
    TakeoverDenyCommand as TakeoverDenyCommand,
)
from ._recovery_commands import RecoveryCommand as RecoveryCommand
from ._service import ControlPlaneRuntimeService as ControlPlaneRuntimeService
