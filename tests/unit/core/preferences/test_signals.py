from core.preferences.signals import extract_signals


def test_extracts_short_verbosity_signal():
    signals = extract_signals("dont give me long answers")
    assert any(s.dimension == "response_style.verbosity" and s.value == {"verbosity": "short"} for s in signals)


def test_extracts_detailed_verbosity_signal():
    signals = extract_signals("give me an architecture breakdown")
    assert any(s.dimension == "response_style.verbosity" and s.value == {"verbosity": "detailed"} for s in signals)


def test_extracts_stepwise_structure_signal():
    signals = extract_signals("just tell me the steps")
    assert any(s.dimension == "response_style.structure" and s.value == {"structure": "stepwise"} for s in signals)


def test_all_matches_are_explicit():
    signals = extract_signals("keep it short")
    assert all(s.explicit for s in signals)


def test_unrelated_text_yields_no_signals():
    assert extract_signals("the invoicing service uses Stripe") == ()


def test_empty_text_yields_no_signals():
    assert extract_signals("") == ()
