from core.formation.domain_classifier import classify_domain
from domain.enums.memory_domain import MemoryDomain


def test_classifies_organization_policy():
    assert classify_domain("Company policy requires manager approval for expenses") == MemoryDomain.ORGANIZATION


def test_classifies_session_blocker():
    assert classify_domain("Current blocker is failing Docker build") == MemoryDomain.SESSION


def test_classifies_user_fact():
    assert classify_domain("The user's timezone is PST") == MemoryDomain.USER


def test_defaults_to_project_for_architectural_facts():
    assert classify_domain("Aftermind uses SQLite for canonical storage") == MemoryDomain.PROJECT


def test_empty_text_defaults_to_project():
    assert classify_domain("") == MemoryDomain.PROJECT
