"""Task-management domain errors."""

from __future__ import annotations


class TaskManagementError(RuntimeError):
    """Base class for task-management failures."""


class TaskNotFoundError(TaskManagementError):
    """Raised when a task identity is not present in the project partition."""

    def __init__(self, project_key: str, task_id: str) -> None:
        super().__init__(
            f"Task {task_id!r} was not found in project {project_key!r}.",
        )
        self.project_key = project_key
        self.task_id = task_id


class TaskAlreadyExistsError(TaskManagementError):
    """Raised when a create command conflicts with an existing task."""

    def __init__(self, project_key: str, task_id: str) -> None:
        super().__init__(
            f"Task {task_id!r} already exists in project {project_key!r}.",
        )
        self.project_key = project_key
        self.task_id = task_id


class InvalidTaskTransitionError(TaskManagementError):
    """Raised when a lifecycle command violates the task state machine."""

    def __init__(self, task_id: str, status: object, command: str) -> None:
        super().__init__(
            f"Task {task_id!r} in status {status!r} cannot be changed via "
            f"{command!r}; task-management transitions fail closed.",
        )
        self.task_id = task_id
        self.status = status
        self.command = command


class InvalidTaskLinkTargetError(TaskManagementError):
    """Raised when a task link points to an invalid or missing target."""

    def __init__(self, project_key: str, target_kind: object, target_id: str) -> None:
        super().__init__(
            f"Task link target {target_kind!r}:{target_id!r} is invalid or missing "
            f"in project {project_key!r}.",
        )
        self.project_key = project_key
        self.target_kind = target_kind
        self.target_id = target_id


class TaskLinkNotFoundError(TaskManagementError):
    """Raised when an unlink command targets a non-existing task link."""

    def __init__(
        self,
        project_key: str,
        task_id: str,
        target_kind: object,
        target_id: str,
        kind: object,
    ) -> None:
        super().__init__(
            f"Task link ({project_key!r}, {task_id!r}, {target_kind!r}, "
            f"{target_id!r}, {kind!r}) was not found.",
        )
        self.project_key = project_key
        self.task_id = task_id
        self.target_kind = target_kind
        self.target_id = target_id
        self.kind = kind
