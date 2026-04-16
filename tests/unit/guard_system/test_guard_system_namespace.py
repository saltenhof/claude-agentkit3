from agentkit.guard_system import ArtifactGuard, BranchGuard, GuardRunner, ScopeGuard


def test_guard_system_namespace_exposes_public_types() -> None:
    assert GuardRunner.__name__ == "GuardRunner"
    assert ArtifactGuard.__name__ == "ArtifactGuard"
    assert BranchGuard.__name__ == "BranchGuard"
    assert ScopeGuard.__name__ == "ScopeGuard"
