import subprocess

from integrations.claude_code.scope_mapper import derive_scope


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def test_derive_scope_uses_git_root_basename_as_project_id(tmp_path):
    repo = tmp_path / "my-project"
    repo.mkdir()
    _init_git_repo(repo)

    scope = derive_scope(cwd=str(repo))

    assert scope["project_id"] == "my-project"
    assert scope["tenant_id"] == "default"
    assert "agent_id" not in scope  # deliberately unset by default


def test_derive_scope_falls_back_to_cwd_outside_a_repo(tmp_path):
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    assert derive_scope(cwd=str(outside))["project_id"] == "not-a-repo"


def test_derive_scope_env_overrides_win(tmp_path, monkeypatch):
    repo = tmp_path / "real-repo"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.setenv("AFTERMIND_SCOPE_PROJECT", "overridden-project")
    monkeypatch.setenv("AFTERMIND_SCOPE_AGENT", "sub-agent-a")

    scope = derive_scope(cwd=str(repo))

    assert scope["project_id"] == "overridden-project"
    assert scope["agent_id"] == "sub-agent-a"


def test_derive_scope_includes_session_id_when_given(tmp_path):
    assert derive_scope(cwd=str(tmp_path), session_id="s1")["session_id"] == "s1"


def test_derive_scope_isolates_different_repos(tmp_path):
    repo_a = tmp_path / "aftermind"
    repo_b = tmp_path / "aglack"
    repo_a.mkdir()
    repo_b.mkdir()
    _init_git_repo(repo_a)
    _init_git_repo(repo_b)

    scope_a = derive_scope(cwd=str(repo_a))
    scope_b = derive_scope(cwd=str(repo_b))

    assert scope_a["project_id"] != scope_b["project_id"]
    assert scope_a["repository_id"] != scope_b["repository_id"]


def test_derive_scope_matches_hermes_scope_for_the_same_repo_and_no_agent_override(tmp_path, monkeypatch):
    """The cross-framework acceptance test's real precondition: with no
    AFTERMIND_SCOPE_AGENT override, Claude Code's and Hermes' derived
    scopes for the same repo must be identical, or shared recall can't
    work at all."""
    from integrations.hermes.hermes_plugin import _derive_scope as hermes_derive_scope

    repo = tmp_path / "shared-project"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.setattr("os.getcwd", lambda: str(repo))

    claude_code_scope = derive_scope(cwd=str(repo))
    hermes_scope = hermes_derive_scope()

    assert claude_code_scope == hermes_scope
