"""Static compatibility exports for persistence JSON codec helpers."""

from __future__ import annotations

from agentkit.backend.state_backend.persistence_json_codec import (
    JsonRecord as _JsonRecord,
)
from agentkit.backend.state_backend.persistence_json_codec import (
    cast_json_record as cast_json_record,
)
from agentkit.backend.state_backend.persistence_json_codec import (
    dump_json as dump_json,
)
from agentkit.backend.state_backend.persistence_json_codec import (
    load_json as load_json,
)

__all__ = ["_JsonRecord", "dump_json", "load_json", "cast_json_record"]
