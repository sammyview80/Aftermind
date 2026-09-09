from core.recall.domain_router import DomainRouter
from domain.enums.memory_domain import MemoryDomain
from domain.models.checkpoint import Checkpoint
from domain.models.recall_query import RecallQuery


def test_empty_query_routes_as_continuation():
    routing = DomainRouter().route(RecallQuery(text=""))

    assert MemoryDomain.SESSION in routing.domains
    assert MemoryDomain.PROJECT in routing.domains
    assert routing.include_checkpoint is True


def test_continue_phrasing_routes_session_and_project():
    routing = DomainRouter().route(RecallQuery(text="Continue what we were working on"))

    assert set(routing.domains) >= {MemoryDomain.SESSION, MemoryDomain.PROJECT}
    assert routing.include_checkpoint is True


def test_company_policy_query_routes_organization_and_turns_checkpoint_off():
    routing = DomainRouter().route(RecallQuery(text="What does our company use for expense approval?"))

    assert MemoryDomain.ORGANIZATION in routing.domains
    assert MemoryDomain.SESSION not in routing.domains
    assert routing.include_checkpoint is False
    assert routing.include_knowledge is True


def test_existing_checkpoint_keeps_checkpoint_included_even_off_topic():
    checkpoint = Checkpoint(goal="Migrate billing workers")
    routing = DomainRouter().route(RecallQuery(text="What does our company use for expense approval?"), checkpoint)

    assert routing.include_checkpoint is True


def test_user_phrasing_routes_user_domain():
    routing = DomainRouter().route(RecallQuery(text="What's my timezone?"))
    assert MemoryDomain.USER in routing.domains


def test_generic_query_defaults_to_project_and_session():
    routing = DomainRouter().route(RecallQuery(text="What database does the billing service use?"))
    assert set(routing.domains) == {MemoryDomain.PROJECT, MemoryDomain.SESSION}


def test_preferences_are_always_included():
    for text in ("", "continue", "company policy", "random question"):
        routing = DomainRouter().route(RecallQuery(text=text))
        assert routing.include_preferences is True
