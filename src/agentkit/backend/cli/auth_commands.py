"""Interactive CLI surface for first access and secret lifecycle operations."""

from __future__ import annotations

import getpass
import json
import ssl
import sys
import urllib.parse
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.harness_client.projectedge.auth_operator import (
    authenticate_strategist,
    issue_project_token,
    revoke_project_token,
    rotate_strategist_password,
    validate_project_token,
)
from agentkit.harness_client.projectedge.client import (
    HttpsJsonTransport,
    LocalEdgePublisher,
    ProjectEdgeClient,
)
from agentkit.harness_client.projectedge.credentials import (
    CredentialMissingError,
    CredentialStateError,
    ProjectCredentialFile,
    load_active_project_credentials,
    load_pending_project_credentials,
    prepare_project_api_token,
    project_api_token_id,
    project_credentials_path,
    reconcile_pending_for_active_credentials,
    store_active_project_credentials,
)
from agentkit.harness_client.projectedge.private_files import exclusive_private_file_lock
from agentkit.harness_client.projectedge.runtime import read_bound_skill_bundle_version

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping
    from contextlib import AbstractContextManager

SecretReader = Callable[[str], str]

_INTERACTIVE_REQUIRED = (
    "This command handles a one-time secret and requires an attached terminal. "
    "Run it directly from an interactive terminal; redirected, agent, and CI "
    "invocations are refused."
)
_STRATEGIST_PASSWORD_PROMPT = "Strategist password: "


class _DeferredProjectTokenTransport:
    """Build the handed-off bearer transport after CP8 materializes its lock."""

    def __init__(
        self,
        *,
        base_url: str,
        ca_file: str | None,
        project_root: Path,
        project_key: str,
        project_api_token: str,
        planned_skill_bundle_version: str | None = None,
    ) -> None:
        self._base_url = base_url
        self._ca_file = ca_file
        self._project_root = project_root
        self._project_key = project_key
        self._project_api_token: str | None = project_api_token
        self._planned_skill_bundle_version = planned_skill_bundle_version
        self._session: HttpsJsonTransport | None = None

    def authenticated_transport(self) -> HttpsJsonTransport:
        """Return the bearer transport, creating it from the CP8 lock once."""
        if self._session is not None:
            return self._session
        project_api_token = self._project_api_token
        if project_api_token is None:
            raise RuntimeError("installer project token is no longer available")
        self._session = _build_project_token_transport(
            self._base_url,
            self._ca_file,
            project_api_token=project_api_token,
            project_key=self._project_key,
            skill_bundle_version=(
                read_bound_skill_bundle_version(self._project_root)
                or self._planned_skill_bundle_version
            ),
        )
        self._project_api_token = None
        self._planned_skill_bundle_version = None
        return self._session

    def send(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        """Send through the lazily created project-token transport."""
        return self.authenticated_transport().send(
            method=method,
            path=path,
            payload=payload,
            headers=headers,
            timeout=timeout,
        )

    def clear_secret(self) -> None:
        """Forget a token that was not consumed because installation stopped."""
        self._project_api_token = None
        self._session = None


@dataclass
class InstallerAuthContext:
    """Locked ProjectEdge credential used during project registration."""

    project_edge_client: ProjectEdgeClient
    transport: _DeferredProjectTokenTransport
    credential_lock: AbstractContextManager[None]
    _lock_released: bool = False

    def clear_secret(self) -> None:
        """Drop the in-memory bearer and release its lifecycle lock."""
        self.transport.clear_secret()
        if not self._lock_released:
            self.credential_lock.__exit__(None, None, None)
            self._lock_released = True


def add_auth_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the strategist bootstrap/login/rotation/token command family."""
    auth = subparsers.add_parser("auth", help="Manage first access and credentials")
    commands = auth.add_subparsers(dest="auth_command", required=True)

    bootstrap = commands.add_parser("bootstrap", help="Initialize the strategist password once")
    bootstrap.add_argument(
        "--auth-config",
        default=None,
        help="Core strategist auth file (defaults to AGENTKIT_AUTH_CONFIG or the user config path)",
    )

    login = commands.add_parser("login", help="Verify strategist login")
    _add_core_flags(login)
    login.add_argument("--project-key", required=True)

    password = commands.add_parser("rotate-password", help="Rotate the strategist password")
    _add_core_flags(password)
    password.add_argument("--project-key", required=True)
    password.add_argument(
        "--op-id",
        default=None,
        help="Reuse the operation id printed by an interrupted password rotation",
    )

    issue = commands.add_parser("issue-token", help="Issue a project token for external handoff")
    _add_core_flags(issue)
    issue.add_argument("--project-key", required=True)
    issue.add_argument("--label", default="project-edge")

    store = commands.add_parser("store-token", help="Verify and store a handed-off project token")
    _add_core_flags(store)
    store.add_argument("--project-key", required=True)
    store.add_argument("--project-root", required=True)
    store.add_argument("--label", default="project-edge")
    store.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing active laptop credential after explicit token rotation",
    )

    revoke = commands.add_parser("revoke-token", help="Revoke a project token")
    _add_core_flags(revoke)
    revoke.add_argument("--project-key", required=True)
    revoke.add_argument("--token-id", required=True)
    revoke.add_argument(
        "--op-id",
        default=None,
        help="Reuse the operation id printed by an interrupted token revocation",
    )


def dispatch_auth_command(args: argparse.Namespace) -> int:
    """Dispatch one parsed auth command."""
    handlers = {
        "bootstrap": _cmd_bootstrap,
        "login": _cmd_login,
        "rotate-password": _cmd_rotate_password,
        "issue-token": _cmd_issue_token,
        "store-token": _cmd_store_token,
        "revoke-token": _cmd_revoke_token,
    }
    handler = handlers.get(str(args.auth_command))
    if handler is None:
        return 1
    return handler(args)


def prepare_installer_auth_context(
    args: argparse.Namespace,
    *,
    planned_skill_bundle_version: str | None = None,
) -> InstallerAuthContext:
    """Prove writer readiness, then lock and prepare the installer credential."""
    project_root = Path(args.project_root)
    project_key = str(args.project_key)
    credential_path = project_credentials_path(project_root)
    active = _load_required_installer_credential(credential_path, project_key)
    transport = _DeferredProjectTokenTransport(
        base_url=str(args.control_plane_base_url),
        ca_file=args.control_plane_ca_file,
        project_root=project_root,
        project_key=project_key,
        project_api_token=active.project_api_token,
        planned_skill_bundle_version=planned_skill_bundle_version,
    )
    from agentkit.backend.installer.writer_client import InstallerWriterClient

    try:
        InstallerWriterClient(
            transport,
            project_key=project_key,
            op_id="writer-readiness-probe",
        ).assert_ready()
    except BaseException:
        transport.clear_secret()
        raise

    # The readiness round-trip above is deliberately before this first local
    # effect: acquiring the lifecycle lock creates its parent and persistent
    # ``credentials.lock`` file, and later reconciliation may unlink a pending
    # crash sidecar.
    credential_lock = exclusive_private_file_lock(credential_path)
    credential_lock.__enter__()
    try:
        locked_active = _load_required_installer_credential(
            credential_path,
            project_key,
        )
        if locked_active != active:
            raise CredentialStateError(
                "Project credential changed during writer readiness; retry with its current value",
            )
        reconcile_pending_for_active_credentials(
            credential_path,
            active=locked_active,
        )
        return InstallerAuthContext(
            project_edge_client=ProjectEdgeClient(
                transport=transport,
                publisher=LocalEdgePublisher(project_root=project_root),
            ),
            transport=transport,
            credential_lock=credential_lock,
        )
    except BaseException:
        transport.clear_secret()
        credential_lock.__exit__(*sys.exc_info())
        raise


def _load_required_installer_credential(
    credential_path: Path,
    project_key: str,
) -> ProjectCredentialFile:
    """Read the active credential without reconciling or creating local state."""

    try:
        active = load_active_project_credentials(
            credential_path,
            project_key=project_key,
        )
    except CredentialMissingError as missing:
        try:
            pending = load_pending_project_credentials(credential_path)
        except CredentialMissingError:
            pending = None
        if pending is not None:
            if pending.project_key != project_key or not _is_initial_pending_state(pending):
                raise CredentialStateError(
                    "Pending project credential cannot initialize this project",
                ) from None
            raise CredentialStateError(
                "Pending project credential cannot replace the required handed-off active token",
            ) from None
        raise CredentialMissingError(
            "Project credential is missing; run 'agentkit auth store-token' on this client first",
        ) from missing
    try:
        pending = load_pending_project_credentials(credential_path)
    except CredentialMissingError:
        pending = None
    if pending is not None and pending.model_copy(update={"status": "active"}) != active:
        raise CredentialStateError(
            "Active and pending project credentials describe different issuances",
        )
    return active


def _is_initial_pending_state(pending: ProjectCredentialFile) -> bool:
    """Return whether a pending credential is a first issuance, not a rotation."""

    return pending.status == "pending" and pending.superseded_token_id is None


def provision_installer_project_token(
    args: argparse.Namespace,
    auth_context: InstallerAuthContext | None = None,
) -> int:
    """Complete ``register-project`` without issuing or copying a credential."""
    owns_context = auth_context is None
    context = auth_context
    try:
        context = context or prepare_installer_auth_context(args)
    except Exception as exc:  # noqa: BLE001 - CLI boundary maps transport/domain errors
        print(f"project credential verification failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if owns_context and context is not None:
            context.clear_secret()
    return 0


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    if not _require_interactive_terminal():
        return 1
    password = _read_new_password(getpass.getpass)
    if password is None:
        return 1
    try:
        from agentkit.backend.auth.credentials import StrategistCredentialStore

        configured_path = Path(args.auth_config) if args.auth_config is not None else None
        StrategistCredentialStore(configured_path).initialize_password(password)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"auth bootstrap failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "initialized", "username": "admin"}, sort_keys=True))
    return 0


def _cmd_login(args: argparse.Namespace) -> int:
    if not _require_interactive_terminal():
        return 1
    password = getpass.getpass(_STRATEGIST_PASSWORD_PROMPT)
    try:
        authenticate_strategist(
            _build_transport(args.base_url, args.ca_file),
            password=password,
            project_key=str(args.project_key),
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"auth login failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "authenticated", "username": "admin"}, sort_keys=True))
    return 0


def _cmd_rotate_password(args: argparse.Namespace) -> int:
    if not _require_interactive_terminal():
        return 1
    current = getpass.getpass("Current strategist password: ")
    replacement = _read_new_password(getpass.getpass)
    if replacement is None:
        return 1
    operation_id = str(args.op_id) if args.op_id is not None else f"op-{uuid.uuid4().hex}"
    print(json.dumps({"status": "rotation_requested", "op_id": operation_id}, sort_keys=True))
    try:
        session = authenticate_strategist(
            _build_transport(args.base_url, args.ca_file),
            password=current,
            project_key=str(args.project_key),
        )
        rotate_strategist_password(
            session,
            new_password=replacement,
            op_id=operation_id,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"password rotation failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"status": "rotated", "username": "admin", "op_id": operation_id},
            sort_keys=True,
        ),
    )
    return 0


def _cmd_issue_token(args: argparse.Namespace) -> int:
    if not _require_interactive_terminal():
        return 1
    password = getpass.getpass(_STRATEGIST_PASSWORD_PROMPT)
    operation_id = f"op-{uuid.uuid4().hex}"
    prepared = prepare_project_api_token(
        project_key=str(args.project_key),
        label=str(args.label),
    )
    print(
        json.dumps(
            {
                "status": "issuance_requested",
                "op_id": operation_id,
                "token_id": prepared.record.token_id,
            },
            sort_keys=True,
        ),
    )
    try:
        session = authenticate_strategist(
            _build_transport(args.base_url, args.ca_file),
            password=password,
            project_key=str(args.project_key),
        )
        result = issue_project_token(
            session,
            project_key=str(args.project_key),
            label=str(args.label),
            op_id=operation_id,
            prepared_token=prepared,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"project token issue failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "issued",
                "token_id": result.token_id,
                "project_api_token": result.project_api_token,
            },
            sort_keys=True,
        ),
    )
    return 0


def _cmd_store_token(args: argparse.Namespace) -> int:
    if not _require_interactive_terminal():
        return 1
    try:
        _require_https_base_url(str(args.base_url))
        project_api_token = getpass.getpass("Project API token: ")
        project_api_token_id(project_api_token)
        transport = _build_project_token_transport(
            str(args.base_url),
            args.ca_file,
            project_api_token=project_api_token,
            project_key=str(args.project_key),
        )
        validate_project_token(transport, project_key=str(args.project_key))
        credential_path = project_credentials_path(Path(args.project_root))
        credential = store_active_project_credentials(
            credential_path,
            project_key=str(args.project_key),
            project_api_token=project_api_token,
            label=str(args.label),
            replace_active=bool(args.replace),
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"project token storage failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "active",
                "credential_path": str(credential_path),
                "token_id": credential.token_id,
            },
            sort_keys=True,
        ),
    )
    return 0


def _cmd_revoke_token(args: argparse.Namespace) -> int:
    if not _require_interactive_terminal():
        return 1
    password = getpass.getpass(_STRATEGIST_PASSWORD_PROMPT)
    operation_id = str(args.op_id) if args.op_id is not None else f"op-{uuid.uuid4().hex}"
    print(
        json.dumps(
            {
                "status": "revocation_requested",
                "token_id": str(args.token_id),
                "op_id": operation_id,
            },
            sort_keys=True,
        ),
    )
    try:
        session = authenticate_strategist(
            _build_transport(args.base_url, args.ca_file),
            password=password,
            project_key=str(args.project_key),
        )
        revoke_project_token(
            session,
            project_key=str(args.project_key),
            token_id=str(args.token_id),
            op_id=operation_id,
            credential_path=None,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"project token revocation failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "revoked",
                "token_id": str(args.token_id),
                "op_id": operation_id,
            },
            sort_keys=True,
        ),
    )
    return 0


def _add_core_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--ca-file", default=None)


def _build_transport(
    base_url: str,
    ca_file: str | None,
    *,
    skill_bundle_version: str | None = None,
) -> HttpsJsonTransport:
    context = ssl.create_default_context(cafile=ca_file) if ca_file else None
    return HttpsJsonTransport(
        base_url=base_url,
        ssl_context=context,
        skill_bundle_version=skill_bundle_version,
    )


def _build_project_token_transport(
    base_url: str,
    ca_file: str | None,
    *,
    project_api_token: str,
    project_key: str,
    skill_bundle_version: str | None = None,
) -> HttpsJsonTransport:
    _require_https_base_url(base_url)
    context = ssl.create_default_context(cafile=ca_file) if ca_file else None
    return HttpsJsonTransport(
        base_url=base_url,
        ssl_context=context,
        skill_bundle_version=skill_bundle_version,
        bearer_token=project_api_token,
        project_key=project_key,
    )


def _require_https_base_url(base_url: str) -> None:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Project API tokens may only be sent over HTTPS")


def _require_interactive_terminal() -> bool:
    if sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty():
        return True
    print(_INTERACTIVE_REQUIRED, file=sys.stderr)
    return False


def _read_new_password(reader: SecretReader) -> str | None:
    first = reader("New strategist password: ")
    second = reader("Confirm new strategist password: ")
    if not first:
        print("Password must not be empty.", file=sys.stderr)
        return None
    if first != second:
        print("Password confirmation does not match.", file=sys.stderr)
        return None
    return first


__all__ = [
    "InstallerAuthContext",
    "add_auth_parser",
    "dispatch_auth_command",
    "prepare_installer_auth_context",
    "provision_installer_project_token",
]
