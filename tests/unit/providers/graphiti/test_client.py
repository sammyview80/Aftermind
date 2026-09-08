from providers.graphiti.client import DEFAULT_URI, Neo4jClient


class FakeResult(list):
    pass


class FakeSession:
    def __init__(self, driver: "FakeDriver") -> None:
        self._driver = driver

    def run(self, query, **params):
        self._driver.calls.append((query, params))
        return FakeResult(self._driver.records)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeDriver:
    def __init__(self, records=None) -> None:
        self.records = records or []
        self.calls = []
        self.closed = False

    def session(self):
        return FakeSession(self)

    def close(self):
        self.closed = True


def test_run_executes_query_with_params_and_returns_records():
    driver = FakeDriver(records=[{"name": "PostgreSQL"}])
    client = Neo4jClient(driver=driver)

    result = client.run("MATCH (n) RETURN n", name="Aftermind", limit=5)

    assert result == [{"name": "PostgreSQL"}]
    assert driver.calls == [("MATCH (n) RETURN n", {"name": "Aftermind", "limit": 5})]


def test_close_closes_the_driver():
    driver = FakeDriver()
    Neo4jClient(driver=driver).close()
    assert driver.closed is True


def test_default_uri_is_bolt_localhost():
    assert DEFAULT_URI == "bolt://localhost:7687"


def test_driver_config_bounds_every_neo4j_wait():
    from providers.graphiti.client import driver_config

    assert driver_config(3.0) == {
        "connection_timeout": 3.0,
        "connection_acquisition_timeout": 3.0,
        "max_transaction_retry_time": 3.0,
    }
