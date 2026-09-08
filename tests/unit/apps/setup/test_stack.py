from apps.setup import stack


def test_ensure_env_creates_from_example_and_fills_local_defaults(tmp_path):
    (tmp_path / ".env.example").write_text("LLM_API_KEY=\nNEO4J_PASSWORD=\n# comment\nOPENKNOWLEDGE_URL=\n")
    logs = []

    values = stack.ensure_env(tmp_path, log=logs.append, have_ok=True)

    written = stack.read_env_file(tmp_path / ".env")
    assert written["NEO4J_PASSWORD"] and written["NEO4J_PASSWORD"] == values["NEO4J_PASSWORD"]
    assert written["OPENKNOWLEDGE_URL"] == stack.DEFAULT_OPENKNOWLEDGE_URL
    assert written["DATABASE_PATH"] == "./aftermind.db"
    assert written["NEO4J_URI"] == "bolt://localhost:7687"
    assert "# comment" in (tmp_path / ".env").read_text()  # comments preserved
    assert any("no LLM configured" in line for line in logs)  # warned, not blocked


def test_ensure_env_is_idempotent_and_respects_existing_values(tmp_path):
    (tmp_path / ".env").write_text("NEO4J_PASSWORD=keepme\nOPENKNOWLEDGE_URL=http://10.0.0.5:7000\nLLM_API_KEY=k\nLLM_MODEL=m\n")

    first = stack.ensure_env(tmp_path, log=lambda _: None, have_ok=True)
    second = stack.ensure_env(tmp_path, log=lambda _: None, have_ok=True)

    assert first["NEO4J_PASSWORD"] == second["NEO4J_PASSWORD"] == "keepme"
    assert second["OPENKNOWLEDGE_URL"] == "http://10.0.0.5:7000"


def test_ensure_env_leaves_openknowledge_unset_without_ok_cli(tmp_path):
    (tmp_path / ".env").write_text("")
    values = stack.ensure_env(tmp_path, log=lambda _: None, have_ok=False)
    assert not values.get("OPENKNOWLEDGE_URL")


def test_write_env_values_updates_in_place_and_appends_new(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1\n# note\nB=2\n")
    stack.write_env_values(path, {"B": "3", "C": "4"})
    assert path.read_text() == "A=1\n# note\nB=3\nC=4\n"


def test_report_summary_lists_every_component():
    report = stack.StackReport(env={"DATABASE_PATH": "./x.db", "NEO4J_URI": "bolt://h:1"}, sqlite=True, neo4j=False)
    text = report.summary()
    assert "SQLite" in text and "ok" in text
    assert "in-memory fallback" in text
    assert "local markdown fallback" in text
