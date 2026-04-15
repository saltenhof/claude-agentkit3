from agentkit.prompt_composer import compose_prompt
from agentkit.prompting import compose_prompt as legacy_compose_prompt


def test_prompt_composer_namespace_reexports_legacy_api() -> None:
    assert compose_prompt is legacy_compose_prompt
