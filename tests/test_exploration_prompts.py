from docbot.exploration.prompts import build_system_prompt


def test_system_prompt_requires_strong_reason_to_underdelegate() -> None:
    prompt = build_system_prompt("Explore repo", "")
    lowered = prompt.lower()
    assert "under-delegate" in lowered
    assert "strong reason" in lowered


def test_system_prompt_contains_underdelegation_examples() -> None:
    prompt = build_system_prompt("Explore repo", "")
    lowered = prompt.lower()
    assert "tiny scope" in lowered
    assert "single cohesive module" in lowered
