import sys

import pytest

from providers.graphiti.graphiti_client import _deterministic_embedding


def test_deterministic_embedding_is_deterministic():
    assert _deterministic_embedding("Aftermind") == _deterministic_embedding("Aftermind")


def test_deterministic_embedding_differs_for_different_text():
    assert _deterministic_embedding("Aftermind") != _deterministic_embedding("PostgreSQL")


def test_deterministic_embedding_is_a_unit_vector():
    vec = _deterministic_embedding("Aftermind")
    norm = sum(v * v for v in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_build_graphiti_raises_clear_error_without_graphiti_core(monkeypatch):
    monkeypatch.setitem(sys.modules, "graphiti_core", None)

    from providers.graphiti.graphiti_client import _build_graphiti

    with pytest.raises(ImportError, match="pip install graphiti-core neo4j"):
        _build_graphiti("bolt://localhost:7687", "neo4j", "password")
