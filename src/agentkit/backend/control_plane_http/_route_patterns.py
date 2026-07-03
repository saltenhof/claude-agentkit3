"""Compiled route path patterns for the control-plane HTTP app (FK-72 §72.8.1).

Extracted verbatim from ``app.py`` so the app module's executed top-level stays
lean (PY_MODULE_TOP_LEVEL_MAX_LOC_100). They are imported back into ``app.py``
under the SAME names, so route matching is byte-for-byte unchanged -- this is a
pure structural move, no behaviour change.
"""

from __future__ import annotations

import re

# Legacy non-project paths (kept for non-project-scoped resources only):
_OPERATION_PATH_PATTERN = re.compile(
    r"^/v1/project-edge/operations/(?P<op_id>[^/]+)$",
)

# AG3-138: administrative abort of a hanging server-owned in-flight operation
# (FK-91 §91.1a ``admin_abort_inflight_operation``, FK-55 §55.5 admin_transition).
_OPERATION_ADMIN_ABORT_PATTERN = re.compile(
    r"^/v1/project-edge/operations/(?P<op_id>[^/]+)/admin-abort$",
)

# Project-scoped paths under /v1/projects/{project_key}/<bc>/...
_PROJECT_SCOPED_PREFIX = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/(?P<rest>.+)$",
)

# story-runs (project-scoped by project_key in path since AG3-090):
_PROJECT_PHASE_PATH_PATTERN = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/story-runs/(?P<run_id>[^/]+)"
    r"/phases/(?P<phase>[^/]+)/(?P<action>start|complete|fail|resume)$",
)
_PROJECT_CLOSURE_PATH_PATTERN = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/story-runs/(?P<run_id>[^/]+)/closure/complete$",
)
# Project-scoped story paths:
_PROJECT_STORIES_COLLECTION = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories$",
)
_PROJECT_STORY_DETAIL = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)$",
)
_PROJECT_STORY_APPROVE = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)/approve$",
)
_PROJECT_STORY_REJECT = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)/reject$",
)
_PROJECT_STORY_CANCEL = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)/cancel$",
)
_PROJECT_STORY_FIELDS = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)/fields$",
)
_PROJECT_STORY_FIELD_KEY = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)"
    r"/fields/(?P<field_key>[^/]+)$",
)
_PROJECT_STORY_SEARCH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/search$",
)
_PROJECT_DASHBOARD_BOARD = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/dashboard/board$",
)
_PROJECT_DASHBOARD_STORY_METRICS = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/dashboard/story-metrics$",
)
