"""Unit tests for PlaceholderSubstitutor (AG3-027, FK-43 §43.4.2)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agentkit.backend.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    JenkinsConfig,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
)
from agentkit.backend.skills.errors import UnknownPlaceholderError
from agentkit.backend.skills.placeholder import (
    AK3_INTERPRETER_PLACEHOLDER,
    AK3_WRAPPER_PLACEHOLDER,
    SPAWN_SKILL_PROOF_PLACEHOLDER,
    PlaceholderSubstitutor,
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

#: AG3-052 E6 / AG3-056: code-producing default story_types must declare the
#: sonarqube + ci stanzas explicitly (opt-outs for this placeholder test).
#: multi_llm=False for this single-LLM fixture.
_OPT_OUT_PIPELINE = PipelineConfig(  # type: ignore[call-arg]
    config_version=SUPPORTED_CONFIG_VERSION,
    features=Features(multi_llm=False),
    sonarqube=SonarQubeConfig(available=False, enabled=False),
    ci=JenkinsConfig(available=False, enabled=False),
)


def _project_config(
    *,
    project_key: str = "my-proj",
    github_owner: str | None = "my-org",
    github_repo: str | None = "my-repo",
    wiki_stories_dir: str = "stories",
) -> ProjectConfig:
    return ProjectConfig(
        project_key=project_key,
        project_name="My Project",
        repositories=[RepositoryConfig(name="app", path=Path("."))],
        github_owner=github_owner,
        github_repo=github_repo,
        wiki_stories_dir=wiki_stories_dir,
        pipeline=_OPT_OUT_PIPELINE,
    )


# ---------------------------------------------------------------------------
# Happy paths — five mandatory placeholders
# ---------------------------------------------------------------------------

class TestMandatoryPlaceholders:
    def setup_method(self) -> None:
        self.sub = PlaceholderSubstitutor()
        self.cfg = _project_config()

    def test_gh_owner(self) -> None:
        result = self.sub.substitute("Owner: {{gh_owner}}", self.cfg)
        assert result == "Owner: my-org"

    def test_gh_repo(self) -> None:
        # FK-43 §43.4.2: gh_repo source is config.repositories[0].name
        result = self.sub.substitute("Repo: {{gh_repo}}", self.cfg)
        assert result == "Repo: app"

    def test_project_key(self) -> None:
        result = self.sub.substitute("Key: {{project_key}}", self.cfg)
        assert result == "Key: my-proj"

    def test_project_prefix(self) -> None:
        # FK-03 §3.2 / Pass-2: project_prefix defaults to project_key.upper()
        result = self.sub.substitute("Prefix: {{project_prefix}}", self.cfg)
        assert result == "Prefix: MY-PROJ"

    def test_all_four_together(self) -> None:
        template = (
            "owner={{gh_owner}} repo={{gh_repo}} "
            "key={{project_key}} prefix={{project_prefix}}"
        )
        result = self.sub.substitute(template, self.cfg)
        assert result == "owner=my-org repo=app key=my-proj prefix=MY-PROJ"

    def test_wiki_stories_dir_default(self) -> None:
        # AG3-113: surviving layout token resolves to config.wiki_stories_dir.
        result = self.sub.substitute("Dir: {{wiki_stories_dir}}", self.cfg)
        assert result == "Dir: stories"

    def test_wiki_stories_dir_custom(self) -> None:
        cfg = _project_config(wiki_stories_dir="docs/stories")
        result = self.sub.substitute("{{wiki_stories_dir}}/INDEX.md", cfg)
        assert result == "docs/stories/INDEX.md"

    def test_full_lowercase_vocabulary_together(self) -> None:
        template = (
            "owner={{gh_owner}} repo={{gh_repo}} key={{project_key}} "
            "prefix={{project_prefix}} wiki={{wiki_stories_dir}}"
        )
        result = self.sub.substitute(template, self.cfg)
        assert result == (
            "owner=my-org repo=app key=my-proj prefix=MY-PROJ wiki=stories"
        )

    def test_no_placeholders_passthrough(self) -> None:
        result = self.sub.substitute("no placeholders here", self.cfg)
        assert result == "no placeholders here"

    def test_repeated_placeholder(self) -> None:
        result = self.sub.substitute("{{project_key}}/{{project_key}}", self.cfg)
        assert result == "my-proj/my-proj"

    def test_none_github_owner_becomes_empty_string(self) -> None:
        cfg = _project_config(github_owner=None)
        result = self.sub.substitute("{{gh_owner}}", cfg)
        assert result == ""

    def test_explicit_project_prefix_overrides_default(self) -> None:
        # FK-03 §3.2 / FK-43 §43.4.2: explicit project_prefix wins.
        cfg = ProjectConfig(
            project_key="my-proj",
            project_name="My Project",
            project_prefix="ACME",
            repositories=[RepositoryConfig(name="app", path=Path("."))],
            pipeline=_OPT_OUT_PIPELINE,
        )
        result = self.sub.substitute("Prefix: {{project_prefix}}", cfg)
        assert result == "Prefix: ACME"

    def test_empty_repositories_raises_value_error(self) -> None:
        # FK-43 §43.4.2: gh_repo has no canonical source without a repository.
        cfg = ProjectConfig(
            project_key="my-proj",
            project_name="My Project",
            repositories=[],
            pipeline=_OPT_OUT_PIPELINE,
        )
        with pytest.raises(ValueError, match="gh_repo"):
            self.sub.substitute("{{gh_repo}}", cfg)


# ---------------------------------------------------------------------------
# Fail-closed: unknown placeholder
# ---------------------------------------------------------------------------

class TestUnknownPlaceholderError:
    def setup_method(self) -> None:
        self.sub = PlaceholderSubstitutor()
        self.cfg = _project_config()

    def test_unknown_placeholder_raises(self) -> None:
        with pytest.raises(UnknownPlaceholderError):
            self.sub.substitute("{{unknown_token}}", self.cfg)

    def test_error_detail_contains_placeholder(self) -> None:
        with pytest.raises(UnknownPlaceholderError) as exc_info:
            self.sub.substitute("{{bad_key}}", self.cfg)
        assert "bad_key" in exc_info.value.detail["placeholder"]

    def test_error_detail_contains_supported_list(self) -> None:
        with pytest.raises(UnknownPlaceholderError) as exc_info:
            self.sub.substitute("{{bad_key}}", self.cfg)
        supported = exc_info.value.detail["supported"]
        assert "gh_owner" in supported
        assert "gh_repo" in supported
        assert "project_key" in supported
        assert "project_prefix" in supported

    def test_first_occurrence_raises_immediately(self) -> None:
        # Substitution should raise on the first bad token it encounters.
        with pytest.raises(UnknownPlaceholderError):
            self.sub.substitute("{{gh_owner}} {{nope}} {{project_key}}", self.cfg)

    def test_config_only_substitute_rejects_spawn_proof(self) -> None:
        # AG3-110: the manifest-fed placeholder is NOT resolvable on the config-only
        # path; substitute() treats it as unknown (only substitute_spawn_header reads
        # the manifest).
        with pytest.raises(UnknownPlaceholderError):
            self.sub.substitute("{{AGENT_SPAWN_SKILL_PROOF}}", self.cfg)


# ---------------------------------------------------------------------------
# AG3-110 — manifest-fed spawn-proof header bridge (FK-31 §31.7.4 / FK-43 §43.4.2)
# ---------------------------------------------------------------------------

_STORY_EXECUTION_HEADER = (
    "AGENTKIT-SUBAGENT-V1 mode=story_execution role=story-worker "
    "story_id=AG3-110 skill_proof={{AGENT_SPAWN_SKILL_PROOF}}"
)


def _write_manifest(root: Path, token: str) -> None:
    (root / ".installed-manifest.json").write_text(
        json.dumps({"agent_spawn_skill_proof": token}), encoding="utf-8"
    )


class TestInstalledSkillSubstitution:
    def setup_method(self) -> None:
        self.sub = PlaceholderSubstitutor()
        self.cfg = _project_config()

    def test_resolves_installer_commands_through_the_shared_substitutor(
        self, tmp_path: Path
    ) -> None:
        _write_manifest(tmp_path, "proof-token")

        result = self.sub.substitute_materialized(
            "{{AK3_INTERPRETER}} -m existing; {{AK3_WRAPPER}} export-story-md "
            "proof={{AGENT_SPAWN_SKILL_PROOF}}",
            self.cfg,
            tmp_path,
            ak3_interpreter_command='"C:\\AgentKit Runtime\\python.exe"',
            ak3_wrapper_command='"C:\\AgentKit Runtime\\agentkit.exe"',
        )

        assert result == (
            '"C:\\AgentKit Runtime\\python.exe" -m existing; '
            '"C:\\AgentKit Runtime\\agentkit.exe" export-story-md proof=proof-token'
        )

    @pytest.mark.parametrize(
        ("token", "interpreter", "wrapper"),
        [
            (AK3_INTERPRETER_PLACEHOLDER, "", "agentkit"),
            (AK3_WRAPPER_PLACEHOLDER, "python", ""),
        ],
    )
    def test_rejects_empty_installer_command(
        self,
        tmp_path: Path,
        token: str,
        interpreter: str,
        wrapper: str,
    ) -> None:
        _write_manifest(tmp_path, "proof-token")

        with pytest.raises(ValueError, match="must be non-empty"):
            self.sub.substitute_materialized(
                f"{{{{{token}}}}}",
                self.cfg,
                tmp_path,
                ak3_interpreter_command=interpreter,
                ak3_wrapper_command=wrapper,
            )

    def test_resolves_manifest_token_into_header(self, tmp_path: Path) -> None:
        # AC3 positive: the resolved header carries the real token, not the literal.
        _write_manifest(tmp_path, "deadbeefcafe0123")
        result = self.sub.substitute_spawn_header(
            _STORY_EXECUTION_HEADER, self.cfg, tmp_path
        )
        assert "skill_proof=deadbeefcafe0123" in result
        assert SPAWN_SKILL_PROOF_PLACEHOLDER not in result

    def test_resolves_four_fk03_placeholders_too(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "tok")
        content = (
            "key={{project_key}} proof={{AGENT_SPAWN_SKILL_PROOF}}"
        )
        result = self.sub.substitute_spawn_header(content, self.cfg, tmp_path)
        assert result == "key=my-proj proof=tok"

    def test_missing_manifest_fails_closed_no_dummy(self, tmp_path: Path) -> None:
        # AC3 negative / FAIL-CLOSED: no manifest -> the placeholder is NOT replaced
        # by a dummy/empty token; the resolution raises so the header stays unresolved.
        with pytest.raises(UnknownPlaceholderError):
            self.sub.substitute_spawn_header(
                _STORY_EXECUTION_HEADER, self.cfg, tmp_path
            )

    def test_empty_token_fails_closed(self, tmp_path: Path) -> None:
        # An installed manifest with an EMPTY token is treated as no token (fail-closed).
        _write_manifest(tmp_path, "")
        with pytest.raises(UnknownPlaceholderError):
            self.sub.substitute_spawn_header(
                _STORY_EXECUTION_HEADER, self.cfg, tmp_path
            )

    def test_content_without_proof_placeholder_resolves_without_manifest(
        self, tmp_path: Path
    ) -> None:
        # Freestyle/other content that does NOT carry the proof placeholder still
        # resolves the five FK-03 placeholders even with no manifest installed.
        result = self.sub.substitute_spawn_header(
            "key={{project_key}}", self.cfg, tmp_path
        )
        assert result == "key=my-proj"

    def test_create_userstory_420_binds_every_executable_to_installer_values(
        self, tmp_path: Path
    ) -> None:
        from agentkit.backend.skills.bundle_store import shipped_skill_bundles_root

        source = (
            shipped_skill_bundles_root()
            / "create-userstory-core"
            / "4.2.0"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        _write_manifest(tmp_path, "proof-token")

        materialized = self.sub.substitute_materialized(
            source,
            self.cfg,
            tmp_path,
            ak3_interpreter_command='"C:\\AgentKit Runtime\\python.exe"',
            ak3_wrapper_command='"C:\\AgentKit Runtime\\agentkit.exe"',
        )

        assert "{{AK3_INTERPRETER}}" not in materialized
        assert "{{AK3_WRAPPER}}" not in materialized
        assert (
            '"C:\\AgentKit Runtime\\python.exe" '
            "-m agentkit.backend.vectordb.wait_for_weaviate"
        ) in materialized
        assert (
            '"C:\\AgentKit Runtime\\python.exe" '
            "tools/agentkit/projectedge.py create-story"
        ) in materialized
        assert '"C:\\AgentKit Runtime\\agentkit.exe" concept' in materialized
        assert (
            '"C:\\AgentKit Runtime\\agentkit.exe" export-story-md'
            in materialized
        )

    def test_lookup_userstory_410_binds_inline_wrapper_to_installer_value(
        self, tmp_path: Path
    ) -> None:
        from agentkit.backend.skills.bundle_store import shipped_skill_bundles_root

        source = (
            shipped_skill_bundles_root()
            / "lookup-userstory-core"
            / "4.1.0"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        _write_manifest(tmp_path, "proof-token")

        materialized = self.sub.substitute_materialized(
            source,
            self.cfg,
            tmp_path,
            ak3_interpreter_command='"C:\\AgentKit Runtime\\python.exe"',
            ak3_wrapper_command='"C:\\AgentKit Runtime\\agentkit.exe"',
        )

        assert "{{AK3_WRAPPER}}" not in materialized
        assert (
            '"C:\\AgentKit Runtime\\agentkit.exe" export-story-md'
            in materialized
        )

    def test_execute_userstory_410_uses_the_phase_owner_and_bound_wrapper(
        self, tmp_path: Path
    ) -> None:
        from agentkit.backend.skills.bundle_store import shipped_skill_bundles_root

        source = (
            shipped_skill_bundles_root()
            / "execute-userstory-core"
            / "4.1.0"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        _write_manifest(tmp_path, "proof-token")

        materialized = self.sub.substitute_materialized(
            source,
            self.cfg,
            tmp_path,
            ak3_interpreter_command='"C:\\AgentKit Runtime\\python.exe"',
            ak3_wrapper_command='"C:\\AgentKit Runtime\\agentkit.exe"',
        )

        assert "{{AK3_WRAPPER}}" not in materialized
        assert (
            '"C:\\AgentKit Runtime\\agentkit.exe" run-phase setup'
            in materialized
        )
        assert (
            '"C:\\AgentKit Runtime\\agentkit.exe" run-phase verify'
            in materialized
        )
        assert (
            '"C:\\AgentKit Runtime\\agentkit.exe" run-phase closure'
            in materialized
        )
        assert "agentkit.qa.structural_check" not in materialized
        assert "agentkit.qa.policy_engine" not in materialized
        assert "agentkit.bugfix.verify_reproducer" not in materialized
        assert "agentkit preflight" not in materialized
        assert "agentkit postflight" not in materialized
        assert "agentkit run-phase" not in source

    def test_concept_incubation_410_binds_text_fence_commands_to_interpreter(
        self, tmp_path: Path
    ) -> None:
        from agentkit.backend.skills.bundle_store import SkillBundleStore

        bundle = SkillBundleStore().get_bundle("concept-incubation-core")
        assert bundle.bundle_version == "4.1.0"
        source = (bundle.bundle_root / "references" / "process-core.md").read_text(
            encoding="utf-8"
        )
        _write_manifest(tmp_path, "proof-token")

        materialized = self.sub.substitute_materialized(
            source,
            self.cfg,
            tmp_path,
            ak3_interpreter_command='"C:\\AgentKit Runtime\\python.exe"',
            ak3_wrapper_command='"C:\\AgentKit Runtime\\agentkit.exe"',
        )

        assert "{{AK3_INTERPRETER}}" not in materialized
        assert (
            '"C:\\AgentKit Runtime\\python.exe" '
            "tools/agentkit/concept_toolchain/check.py"
        ) in materialized
        assert (
            '"C:\\AgentKit Runtime\\python.exe" '
            "tools/agentkit/concept_toolchain/semantic_gate.py"
        ) in materialized


# ---------------------------------------------------------------------------
# AG3-113 — FK-43 vocabulary parity + shipped-bundle full resolution (NO-STUB)
# ---------------------------------------------------------------------------

#: Tokens that the substitutor intentionally does NOT resolve and that may remain
#: literally in materialised content (story §2.1.5 / AC5 + AC8a exceptions):
#:  * ``<STORY-ID>`` / ``<ROUND>`` — non-``{{}}`` runtime markers (not matched here).
#:  * the conditional block directives ``{{#...}}`` / ``{{^...}}`` / ``{{/...}}`` —
#:    a SEPARATE render mechanism (out of scope, FK-43 §43.4.2 "keine Template-Engine").
_BLOCK_DIRECTIVE_RE = re.compile(r"\{\{[#^/][^}]+\}\}")

#: The re-cut bundles whose vocabulary must be FULLY resolvable. All must resolve with
#: a real ProjectConfig + a real installed manifest (NO substitutor mock).
_RECUT_BUNDLES = (
    "concept-incubation-core",
    "create-userstory-core",
    "lookup-userstory-core",
    "execute-userstory-core",
)


def _bundle_md_files(bundle_id: str) -> list[Path]:
    from agentkit.backend.skills.bundle_store import SkillBundleStore

    bundle = SkillBundleStore().get_bundle(bundle_id)
    return sorted(bundle.bundle_root.glob("**/*.md"))


def test_fk43_vocabulary_matches_concept_table() -> None:
    # AC2: the substitutor's config-fed vocabulary is exactly the FK-43 §43.4.2
    # lowercase table (4 identity tokens + the surviving wiki_stories_dir layout
    # token). The manifest-fed proof is separate and NOT in this set.
    from agentkit.backend.skills.placeholder import _MANDATORY_PLACEHOLDERS

    expected = [
        "gh_owner",
        "gh_repo",
        "project_key",
        "project_prefix",
        "wiki_stories_dir",
    ]
    assert sorted(_MANDATORY_PLACEHOLDERS) == expected
    assert SPAWN_SKILL_PROOF_PLACEHOLDER not in _MANDATORY_PLACEHOLDERS


class TestShippedBundleFullResolution:
    """AC5 / AC8a (NO-STUB): every shipped re-cut bundle .md resolves fully."""

    def setup_method(self) -> None:
        self.sub = PlaceholderSubstitutor()
        self.cfg = _project_config()

    @pytest.mark.parametrize("bundle_id", _RECUT_BUNDLES)
    def test_every_md_resolves_without_unknown_or_residual(
        self, bundle_id: str, tmp_path: Path
    ) -> None:
        # Real ProjectConfig + real installed manifest (NO mock of the substitutor).
        _write_manifest(tmp_path, "deadbeefcafe0123")
        md_files = _bundle_md_files(bundle_id)
        assert md_files, f"no .md files found for bundle {bundle_id}"
        for md in md_files:
            content = md.read_text(encoding="utf-8")
            # NO UnknownPlaceholderError (fail-closed-on-unknown stays valid because
            # the vocabulary is complete for these bundles).
            resolved = self.sub.substitute_materialized(
                content,
                self.cfg,
                tmp_path,
                ak3_interpreter_command='"C:\\AgentKit Runtime\\python.exe"',
                ak3_wrapper_command='"C:\\AgentKit Runtime\\agentkit.exe"',
            )
            # Strip the allowed conditional block directives, then assert NO residual
            # {{...}} token remains.
            residual = _residual_placeholders_after_blocks(resolved)
            assert residual == [], (
                f"residual {{{{...}}}} tokens in {md.name} of {bundle_id}: {residual}"
            )

    @pytest.mark.parametrize("bundle_id", ("create-userstory-core", "execute-userstory-core"))
    def test_resolution_is_idempotent_byte_identical(
        self, bundle_id: str, tmp_path: Path
    ) -> None:
        # AC8: repeated substitution of the same bundle + config is byte-identical
        # (prep for AG3-111 materialisation).
        _write_manifest(tmp_path, "deadbeefcafe0123")
        for md in _bundle_md_files(bundle_id):
            content = md.read_text(encoding="utf-8")
            first = self.sub.substitute_materialized(
                content,
                self.cfg,
                tmp_path,
                ak3_interpreter_command='"C:\\AgentKit Runtime\\python.exe"',
                ak3_wrapper_command='"C:\\AgentKit Runtime\\agentkit.exe"',
            )
            second = self.sub.substitute_materialized(
                content,
                self.cfg,
                tmp_path,
                ak3_interpreter_command='"C:\\AgentKit Runtime\\python.exe"',
                ak3_wrapper_command='"C:\\AgentKit Runtime\\agentkit.exe"',
            )
            assert first == second


def _residual_placeholders_after_blocks(text: str) -> list[str]:
    """Return residual ``{{...}}`` tokens after removing block directives."""
    from agentkit.backend.skills.placeholder import _PLACEHOLDER_RE

    without_blocks = _BLOCK_DIRECTIVE_RE.sub("", text)
    return _PLACEHOLDER_RE.findall(without_blocks)
