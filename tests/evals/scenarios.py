"""Scripted multi-session scenarios for the Milestone 7 benchmark suite.

Each scenario follows the shape from the milestone spec:

  Session 1: choose an architecture decision (fact X is true).
  Session 2: change that decision (fact X -> fact Y).
  Session 3: continue implementation (new, unrelated-content turn).
  Session 4: ask what the current state is and what changed.

A "correct" answer at session 4 must surface Y as current and X only as
history (or not at all) — this is what the recall-accuracy, staleness,
and continuity metrics all key off of.

30 topics (>= the milestone's 20-50 target) are generated from a fixed
list of (subject, aspect, old, new) tuples rather than hand-written one
by one, so the suite is easy to extend by appending a row.
"""
from dataclasses import dataclass, field

# (subject, aspect, old_value, new_value) — every value string below is
# unique across the whole list and none is a substring of another, so
# scenarios can be run against a shared service without one topic's
# value coincidentally matching another's (e.g. a broker named the same
# as an unrelated cache).
_TOPICS: list[tuple[str, str, str, str]] = [
    ("Aftermind", "message broker", "ActiveMQ", "RabbitMQ"),
    ("Aftermind", "database", "SQLite", "PostgreSQL"),
    ("Billing", "cache layer", "Memcached", "Hazelcast"),
    ("Billing", "payment gateway", "Stripe", "Adyen"),
    ("Search", "search index", "Elasticsearch", "OpenSearch"),
    ("Search", "ranking model", "BM25Ranker", "LearnedRanker"),
    ("Auth", "identity provider", "Auth0", "Okta"),
    ("Auth", "token format", "OpaqueTokens", "SignedJWTs"),
    ("Notifications", "queue backend", "AmazonSQS", "ApacheKafka"),
    ("Notifications", "delivery provider", "Twilio", "MessageBird"),
    ("Analytics", "warehouse", "Redshift", "Snowflake"),
    ("Analytics", "ETL tool", "ApacheAirflow", "Dagster"),
    ("Frontend", "framework", "VueJS", "ReactJS"),
    ("Frontend", "state manager", "ReduxStore", "ZustandStore"),
    ("Infra", "orchestrator", "DockerSwarm", "Kubernetes"),
    ("Infra", "cloud provider", "GoogleCloud", "AmazonWebServices"),
    ("CI", "pipeline runner", "Jenkins", "GitHubActions"),
    ("CI", "artifact registry", "NexusRepo", "ArtifactoryRepo"),
    ("Observability", "logging stack", "ElkStack", "LokiStack"),
    ("Observability", "tracing backend", "ZipkinTracer", "JaegerTracer"),
    ("Recommendations", "model store", "MlflowRegistry", "CustomRegistry"),
    ("Recommendations", "feature store", "FeastStore", "TectonStore"),
    ("Checkout", "tax engine", "Avalara", "TaxJar"),
    ("Checkout", "fraud detection", "SiftScience", "Riskified"),
    ("Support", "helpdesk platform", "Zendesk", "Intercom"),
    ("Support", "chatbot engine", "Dialogflow", "RasaEngine"),
    ("Mobile", "push provider", "OneSignal", "FirebasePush"),
    ("Mobile", "crash reporting", "SentryReports", "Crashlytics"),
    ("DataPlatform", "streaming engine", "KafkaStreamsEngine", "ApacheFlink"),
    ("DataPlatform", "storage format", "CsvFormat", "ParquetFormat"),
]


@dataclass(frozen=True)
class Session:
    statement: str
    checkpoint: bool = False
    checkpoint_goal: str = ""
    checkpoint_current: str = ""
    checkpoint_next_steps: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    subject: str
    aspect: str
    old_value: str
    new_value: str
    sessions: tuple[Session, ...]
    query: str
    expected_contains: tuple[str, ...]
    expected_stale: tuple[str, ...]


def _build_scenario(index: int, subject: str, aspect: str, old: str, new: str) -> Scenario:
    sessions = (
        Session(statement=f"{subject}'s {aspect} is {old}, chosen after the initial architecture review."),
        Session(statement=f"{subject} changed its {aspect} from {old} to {new} after a team decision."),
        Session(
            statement=f"Implementation work continues on the {aspect} integration for {new}.",
            checkpoint=True,
            checkpoint_goal=f"Migrate {subject}'s {aspect} to {new}",
            checkpoint_current=f"Implementing the {aspect} integration for {new}",
            checkpoint_next_steps=(f"Finish {aspect} migration for {subject}",),
        ),
    )
    return Scenario(
        scenario_id=f"{index:02d}-{subject.lower()}-{aspect.replace(' ', '_')}",
        subject=subject,
        aspect=aspect,
        old_value=old,
        new_value=new,
        sessions=sessions,
        query=f"What is {subject}'s {aspect} now, and what changed?",
        expected_contains=(new,),
        expected_stale=(old,),
    )


def generate_scenarios() -> list[Scenario]:
    return [_build_scenario(i, subject, aspect, old, new) for i, (subject, aspect, old, new) in enumerate(_TOPICS, start=1)]


SCENARIOS = generate_scenarios()
