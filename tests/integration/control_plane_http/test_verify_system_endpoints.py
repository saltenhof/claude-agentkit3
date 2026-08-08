"""Negative paths of the two verify-system endpoints (AG3-241 AC 6).

Both operations exist because the raw observation can only be made on the
developer machine and the judgement may only be made here. A test that only shows
the good case does not satisfy AC 6; what has to hold is what happens when the
request has no right to be answered, when the identity does not resolve, and when
the core cannot answer:

1. missing / invalid authorization -- and no verdict or manifest anywhere in the
   body of the refusal;
2. an identity that resolves to no project registration -- ``404
   project_not_registered``, and for the conflict endpoint the adjudication is
   never consulted at all;
3. fail-closed when the core cannot answer -- ``503`` for both, plus the ``422``
   that keeps "this checkpoint cannot produce a bundle" distinct from "the core
   is down";
4. the surface fence: neither route is reachable on the UI-BFF listener.

Everything except the two boundaries a test cannot own runs for real: the
production :class:`ControlPlaneApplication`, its middleware chain, the real
``AuthMiddleware`` over real hashed tokens, the real tenant-scope middleware, the
real routes and the real evidence assembler. The doubles are the token/project
stores (state backend) and the project-registry lookup seam the route itself
exposes for exactly this purpose.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.auth.middleware import AuthMiddleware
from agentkit.backend.auth.tokens import register_prepared_project_api_token
from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplication,
    ControlPlaneApplicationRoutes,
)
from agentkit.backend.control_plane_http.surface_policy import ControlPlaneSurface
from agentkit.backend.control_plane_http.tenant_scope import TenantScopeMiddleware
from agentkit.backend.control_plane_http.verify_routes import VerifySystemRoutes
from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.verify_system.llm_evaluator import create_scope_conflict
from agentkit.harness_client.projectedge.credentials import prepare_project_api_token

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from agentkit.backend.auth.entities import ProjectApiToken
    from agentkit.backend.control_plane_http.responses import HttpResponse

_PROJECT = "ak3"
_STORY = "AG3-241"
_CONFLICT_PATH = f"/v1/projects/{_PROJECT}/story-conflict-assessments"
_EVIDENCE_PATH = f"/v1/projects/{_PROJECT}/verify-evidence-assemblies"


# ---------------------------------------------------------------------------
# State-backend doubles (auth storage + project master data). Authentication,
# tenant scoping, routing and assembly themselves run for real.
# ---------------------------------------------------------------------------


class _TokenRepository:
    """In-memory auth storage; token validation itself runs for real."""

    def __init__(self) -> None:
        self.rows: dict[str, ProjectApiToken] = {}

    def get(self, token_id: str) -> ProjectApiToken | None:
        return self.rows.get(token_id)

    def get_by_hash(self, token_hash: str) -> ProjectApiToken | None:
        return next(
            (row for row in self.rows.values() if row.token_hash == token_hash), None
        )

    def list_for_project(self, project_key: str) -> list[ProjectApiToken]:
        return [row for row in self.rows.values() if row.project_key == project_key]

    def insert(self, token: ProjectApiToken) -> None:
        self.rows[token.token_id] = token

    def mark_used(self, token_id: str, *, used_at: datetime) -> None:
        self.rows[token_id] = self.rows[token_id].model_copy(
            update={"last_used_at": used_at}
        )

    def revoke(self, project_key: str, token_id: str) -> None:
        del project_key
        self.rows.pop(token_id, None)


class _ProjectRepository:
    """In-memory project master data for the real tenant-scope middleware."""

    def __init__(self, *, known: frozenset[str] = frozenset({_PROJECT})) -> None:
        self._known = known

    def get(self, key: str) -> Project | None:
        if key not in self._known:
            return None
        return Project(
            key=key,
            name="AgentKit 3",
            story_id_prefix="AK3",
            configuration=ProjectConfiguration(
                repo_url="",
                default_branch="main",
                default_worker_count=1,
                repositories=["ak3-backend"],
            ),
        )


class _Harness:
    """One booted application plus the plaintext token that reaches it."""

    def __init__(
        self,
        app: ControlPlaneApplication,
        token: str,
        *,
        adjudications: list[object],
    ) -> None:
        self._app = app
        self.token = token
        #: Every create-time assessment the route actually consulted.
        self.adjudications = adjudications

    def post(
        self,
        path: str,
        payload: object,
        *,
        token: str | None = "",
        surface: ControlPlaneSurface = ControlPlaneSurface.PROJECT_API,
    ) -> HttpResponse:
        """POST through the REAL application; ``token=None`` sends no credential."""
        headers = {"X-Correlation-Id": "corr-ag3-241"}
        bearer = self.token if token == "" else token
        if bearer is not None:
            headers["Authorization"] = f"Bearer {bearer}"
        return self._app.handle_request(
            method="POST",
            path=path,
            body=json.dumps(payload).encode("utf-8"),
            request_headers=headers,
            surface=surface,
        )


def _harness(
    *,
    project_root_lookup: Callable[[str], Path | None],
    known_projects: frozenset[str] = frozenset({_PROJECT}),
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> _Harness:
    """Boot the production application with the verify-system routes wired."""
    tokens = _TokenRepository()
    auth = AuthMiddleware(token_repository=tokens)
    prepared = prepare_project_api_token(project_key=_PROJECT, label="edge")
    register_prepared_project_api_token(
        project_key=_PROJECT,
        label="edge",
        token_id=prepared.record.token_id,
        token_hash=prepared.record.token_hash,
        repository=tokens,
    )

    adjudications: list[object] = []
    if monkeypatch is not None:
        original = create_scope_conflict.assess_story_conflict

        def _recording(request: object, **kwargs: object) -> object:
            adjudications.append(request)
            return original(request, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(
            create_scope_conflict, "assess_story_conflict", _recording
        )

    app = ControlPlaneApplication(
        writer_lease_required=False,
        auth_middleware=auth,
        auth_middlewares={ControlPlaneSurface.PROJECT_API: auth},
        tenant_scope_middleware=TenantScopeMiddleware(
            repository=_ProjectRepository(known=known_projects),  # type: ignore[arg-type]
        ),
        routes=ControlPlaneApplicationRoutes(
            verify_system_routes=VerifySystemRoutes(
                project_root_lookup=project_root_lookup
            ),
        ),
    )
    return _Harness(app, prepared.plaintext_token, adjudications=adjudications)


def _conflict_payload() -> dict[str, object]:
    return {
        "story_id": "DRAFT-AG3-999",
        "story_description": "Add retry/backoff to the broker adapter.",
        "candidates": [
            {
                "story_id": "AG3-012",
                "score": 0.94,
                "title": "Broker adapter resilience",
                "snippet": "adds retry",
            }
        ],
    }


def _evidence_payload(*, story_id: str = _STORY) -> dict[str, object]:
    return {
        "story_id": story_id,
        "repositories": [
            {
                "repo_id": "app",
                "git_base_branch": "main",
                "role": "app",
                "affected": True,
                "changed_files": ["src/app.py"],
            }
        ],
        "collected_files": [],
    }


def _body(response: HttpResponse) -> dict[str, object]:
    decoded = json.loads(response.body.decode("utf-8"))
    assert isinstance(decoded, dict)
    return decoded


def _write_project_config(project_root: Path, *, pool: str | None) -> None:
    """Write a real project config the route's own loader reads."""
    from agentkit.backend.config.models import (
        SUPPORTED_CONFIG_VERSION,
        Features,
        LlmRolesConfig,
        PipelineConfig,
        ProjectConfig,
        RepositoryConfig,
    )

    roles = (
        None
        if pool is None
        else LlmRolesConfig(
            qa_review="chatgpt",
            semantic_review="chatgpt",
            adversarial_sparring="chatgpt",
            doc_fidelity="chatgpt",
            governance_adjudication="chatgpt",
            story_creation_review=pool,
        )
    )
    config = ProjectConfig(
        project_key=_PROJECT,
        project_name="AgentKit 3",
        repositories=[RepositoryConfig(name="ak3-backend", path="services/api")],
        story_types=["concept"],
        pipeline=PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            llm_roles=roles,
        ),  # type: ignore[call-arg]
    )
    config_dir = project_root / ".agentkit" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "project.yaml").write_text(
        json.dumps(config.model_dump(mode="json")), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# AC 6.1 -- missing / invalid authorization
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("path", "payload"),
    [(_CONFLICT_PATH, _conflict_payload()), (_EVIDENCE_PATH, _evidence_payload())],
    ids=["story-conflict-assessment", "verify-evidence-assembly"],
)
class TestAuthorizationIsRequired:
    """No credential and no wrong credential ever produces an answer."""

    def test_missing_authorization_is_refused_without_an_answer(
        self, tmp_path: Path, path: str, payload: dict[str, object]
    ) -> None:
        harness = _harness(project_root_lookup=lambda _key: tmp_path)

        response = harness.post(path, payload, token=None)

        assert response.status_code == int(HTTPStatus.UNAUTHORIZED)
        body = _body(response)
        # The refusal carries no judgement and no artefact -- not even an empty
        # one a caller could read as "assessed, nothing found".
        assert "verdict" not in body
        assert "manifest_hash" not in body
        assert "bundle_manifest_json" not in body

    def test_invalid_bearer_is_refused_without_an_answer(
        self, tmp_path: Path, path: str, payload: dict[str, object]
    ) -> None:
        harness = _harness(project_root_lookup=lambda _key: tmp_path)

        response = harness.post(path, payload, token="ak3_not-a-real-token")

        assert response.status_code == int(HTTPStatus.UNAUTHORIZED)
        body = _body(response)
        assert "verdict" not in body
        assert "manifest_hash" not in body

    def test_a_token_of_another_project_is_forbidden(
        self, tmp_path: Path, path: str, payload: dict[str, object]
    ) -> None:
        """A valid token is not a key to every tenant."""
        harness = _harness(project_root_lookup=lambda _key: tmp_path)
        foreign = prepare_project_api_token(project_key="other", label="edge")

        response = harness.post(path, payload, token=foreign.plaintext_token)

        assert response.status_code == int(HTTPStatus.UNAUTHORIZED)
        assert "verdict" not in _body(response)


# ---------------------------------------------------------------------------
# AC 6.2 -- the identity resolves to no project registration
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUnknownIdentityIsNotRegistered:
    """A project the registry does not know gets a stable 404, never a guess."""

    def test_conflict_assessment_404s_and_never_consults_the_adjudication(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The filesystem anchor comes from the registry, so an unknown identity
        stops BEFORE the LLM assessment -- it is never asked."""
        harness = _harness(
            project_root_lookup=lambda _key: None, monkeypatch=monkeypatch
        )

        response = harness.post(_CONFLICT_PATH, _conflict_payload())

        assert response.status_code == int(HTTPStatus.NOT_FOUND)
        body = _body(response)
        assert body["error_code"] == "project_not_registered"
        assert "verdict" not in body
        # The expensive, judgement-bearing act never ran.
        assert harness.adjudications == []

    def test_evidence_assembly_404s_for_an_unregistered_project(self) -> None:
        harness = _harness(project_root_lookup=lambda _key: None)

        response = harness.post(_EVIDENCE_PATH, _evidence_payload())

        assert response.status_code == int(HTTPStatus.NOT_FOUND)
        body = _body(response)
        assert body["error_code"] == "project_not_registered"
        assert "manifest_hash" not in body

    def test_an_unknown_tenant_is_stopped_by_the_tenant_scope_first(
        self, tmp_path: Path
    ) -> None:
        """A project key outside the master data never reaches the route at all."""
        harness = _harness(
            project_root_lookup=lambda _key: tmp_path,
            known_projects=frozenset(),
        )

        response = harness.post(_CONFLICT_PATH, _conflict_payload())

        assert response.status_code == int(HTTPStatus.NOT_FOUND)
        assert "verdict" not in _body(response)


# ---------------------------------------------------------------------------
# AC 6.3 -- fail-closed when the core cannot answer
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConflictAssessmentFailsClosed:
    """No verdict is invented when the assessment cannot be performed."""

    def test_no_configured_pool_is_503_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A registered project whose config assigns no create-time pool.

        Nothing about this is a caller defect and nothing about it is a PASS: the
        adjudication has no owner, so the operation is unavailable.

        This also arms the "never consulted" assertion of the 404 test above: the
        SAME recording seam shows one consultation here, so an empty list there
        means "not asked", not "the spy never worked".
        """
        _write_project_config(tmp_path, pool=None)
        harness = _harness(
            project_root_lookup=lambda _key: tmp_path, monkeypatch=monkeypatch
        )

        response = harness.post(_CONFLICT_PATH, _conflict_payload())

        assert response.status_code == int(HTTPStatus.SERVICE_UNAVAILABLE)
        body = _body(response)
        assert body["error_code"] == "story_conflict_assessment_unavailable"
        assert "verdict" not in body
        assert len(harness.adjudications) == 1

    def test_unreadable_project_config_is_503_unavailable(
        self, tmp_path: Path
    ) -> None:
        """A registered root without a config is an outage, not a verdict."""
        harness = _harness(project_root_lookup=lambda _key: tmp_path)

        response = harness.post(_CONFLICT_PATH, _conflict_payload())

        assert response.status_code == int(HTTPStatus.SERVICE_UNAVAILABLE)
        body = _body(response)
        assert body["error_code"] == "story_conflict_assessment_unavailable"
        assert "verdict" not in body

    def test_a_candidate_less_request_is_rejected_at_the_boundary(
        self, tmp_path: Path
    ) -> None:
        """An assessment with nothing to assess is a malformed question (400).

        It is deliberately NOT a PASS: the caller only asks when stage 1 surfaced
        candidates, so an empty set means the request was built wrong.
        """
        _write_project_config(tmp_path, pool=None)
        harness = _harness(project_root_lookup=lambda _key: tmp_path)

        response = harness.post(
            _CONFLICT_PATH, {**_conflict_payload(), "candidates": []}
        )

        assert response.status_code == int(HTTPStatus.BAD_REQUEST)
        body = _body(response)
        assert body["error_code"] == "invalid_story_conflict_assessment_payload"
        assert "verdict" not in body


@pytest.mark.integration
class TestEvidenceAssemblyFailsClosed:
    """No manifest is invented when the checkpoint cannot produce one."""

    def test_a_checkpoint_without_a_story_directory_is_422_rejected(
        self, tmp_path: Path
    ) -> None:
        """The core owns ``story.md``; without it there is no bundle to stamp.

        422 keeps this distinct from a malformed body (400) and from an
        unavailable core (503): the request was well-formed and the core was up.
        """
        harness = _harness(project_root_lookup=lambda _key: tmp_path)

        response = harness.post(_EVIDENCE_PATH, _evidence_payload())

        assert response.status_code == int(HTTPStatus.UNPROCESSABLE_ENTITY)
        body = _body(response)
        assert body["error_code"] == "verify_evidence_assembly_rejected"
        assert "manifest_hash" not in body

    def test_a_story_without_a_specification_is_422_rejected(
        self, tmp_path: Path
    ) -> None:
        """A story directory that exists but carries no ``story.md``."""
        (tmp_path / "stories" / _STORY).mkdir(parents=True)
        harness = _harness(project_root_lookup=lambda _key: tmp_path)

        response = harness.post(_EVIDENCE_PATH, _evidence_payload())

        assert response.status_code == int(HTTPStatus.UNPROCESSABLE_ENTITY)
        body = _body(response)
        assert body["error_code"] == "verify_evidence_assembly_rejected"
        assert "mandatory story spec is missing" in str(body["error"])

    def test_an_unreadable_story_specification_is_503_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A disk fault while reading core-owned artefacts is an outage (503).

        The fault is injected at the OS boundary (``Path.read_text``) because an
        I/O error is the one condition a test cannot provoke portably by
        arranging real files. Everything above it -- the route, the assembler,
        the error mapping -- runs for real.
        """
        import pathlib

        story_dir = tmp_path / "stories" / _STORY
        story_dir.mkdir(parents=True)
        (story_dir / "story.md").write_text("# AG3-241\n", encoding="utf-8")
        original = pathlib.Path.read_text

        def _faulty_read(self: pathlib.Path, *args: object, **kwargs: object) -> str:
            if self.name == "story.md":
                raise OSError("device I/O error")
            return original(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(pathlib.Path, "read_text", _faulty_read)
        harness = _harness(project_root_lookup=lambda _key: tmp_path)

        response = harness.post(_EVIDENCE_PATH, _evidence_payload())

        assert response.status_code == int(HTTPStatus.SERVICE_UNAVAILABLE)
        body = _body(response)
        assert body["error_code"] == "verify_evidence_assembly_unavailable"
        assert "manifest_hash" not in body

    def test_a_malformed_checkpoint_is_400_not_422(self, tmp_path: Path) -> None:
        """A body that is not a checkpoint never reaches the assembler."""
        harness = _harness(project_root_lookup=lambda _key: tmp_path)

        response = harness.post(
            _EVIDENCE_PATH, {"story_id": _STORY, "repositories": []}
        )

        assert response.status_code == int(HTTPStatus.BAD_REQUEST)
        body = _body(response)
        assert body["error_code"] == "invalid_verify_evidence_assembly_payload"
        assert "manifest_hash" not in body

    def test_a_complete_checkpoint_is_assembled_and_stamped(
        self, tmp_path: Path
    ) -> None:
        """The positive case, so the negatives above prove refusal, not breakage."""
        from agentkit.backend.core_types.verify_evidence import VerifyEvidenceFile

        story_dir = tmp_path / "stories" / _STORY
        story_dir.mkdir(parents=True)
        (story_dir / "story.md").write_text("# AG3-241\n", encoding="utf-8")
        payload = _evidence_payload()
        payload["collected_files"] = [
            VerifyEvidenceFile.from_content(
                repo_id="app", path="src/app.py", content="print('app')\n"
            ).model_dump(mode="json")
        ]
        harness = _harness(project_root_lookup=lambda _key: tmp_path)

        response = harness.post(_EVIDENCE_PATH, payload)

        assert response.status_code == int(HTTPStatus.OK)
        body = _body(response)
        assert len(str(body["manifest_hash"])) == 64
        assert "src/app.py" in body["merge_paths"]
        manifest = json.loads(str(body["bundle_manifest_json"]))
        assert manifest["manifest_hash"] == body["manifest_hash"]


# ---------------------------------------------------------------------------
# The surface fence: an edge-facing project-token path, never a UI path
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("path", "payload"),
    [(_CONFLICT_PATH, _conflict_payload()), (_EVIDENCE_PATH, _evidence_payload())],
    ids=["story-conflict-assessment", "verify-evidence-assembly"],
)
def test_neither_route_is_exposed_on_the_ui_bff_listener(
    tmp_path: Path, path: str, payload: dict[str, object]
) -> None:
    """The UI never assesses a conflict and never assembles evidence.

    The listener refuses before the route: an edge project token is not a
    principal the UI-BFF surface accepts at all, and the route itself is on the
    project-only list behind it. Either refusal is admissible; answering is not.
    """
    harness = _harness(project_root_lookup=lambda _key: tmp_path)

    response = harness.post(path, payload, surface=ControlPlaneSurface.UI_BFF)

    assert response.status_code in {
        int(HTTPStatus.FORBIDDEN),
        int(HTTPStatus.NOT_FOUND),
    }
    body = _body(response)
    assert body["error_code"] in {
        "listener_route_not_exposed",
        "listener_principal_forbidden",
    }
    assert "verdict" not in body
    assert "manifest_hash" not in body
