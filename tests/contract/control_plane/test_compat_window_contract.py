"""Contract test: the /v1/compat window schema is stable (AG3-121 AC1).

The compat window is the dev<->central handshake's read surface (FK-91 §91.1a /
FK-10 §10.2.7). Its wire shape — two axes (``agent_runtime``, ``wire``), each a
closed ``min``/``max``/``recommended``/``blocked`` object — is a stable contract;
this test pins it so an accidental field rename/addition is caught.
"""

from __future__ import annotations

import json
from http import HTTPStatus

from agentkit.backend.control_plane_http.app import ControlPlaneApplication
from agentkit.backend.control_plane_http.version_handshake import default_compat_window

_AXIS_KEYS = {"min", "max", "recommended", "blocked"}


def test_compat_window_model_shape_is_stable() -> None:
    payload = default_compat_window().model_dump(mode="json")

    assert set(payload) == {"agent_runtime", "wire"}
    for axis in ("agent_runtime", "wire"):
        assert set(payload[axis]) == _AXIS_KEYS
        assert isinstance(payload[axis]["min"], str)
        assert isinstance(payload[axis]["max"], str)
        assert isinstance(payload[axis]["recommended"], str)
        assert isinstance(payload[axis]["blocked"], list)


def test_compat_endpoint_response_matches_model() -> None:
    app = ControlPlaneApplication()

    response = app.handle_request(method="GET", path="/v1/compat", body=b"")

    assert response.status_code == int(HTTPStatus.OK)
    assert json.loads(response.body) == default_compat_window().model_dump(mode="json")
