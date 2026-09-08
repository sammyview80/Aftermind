from providers.llm.base import load_prompt


def test_load_prompt_reads_expected_files():
    for name in ("candidate_extractor", "evaluator", "reconciler", "checkpoint"):
        text = load_prompt(name)
        assert text
        assert text.startswith("# Aftermind")


def test_load_prompt_is_cached():
    assert load_prompt("reconciler") is load_prompt("reconciler")


def test_reconciler_prompt_mentions_all_actions():
    text = load_prompt("reconciler")
    for action in ("IGNORE", "CREATE", "UPDATE", "MERGE", "SUPERSEDE"):
        assert action in text
