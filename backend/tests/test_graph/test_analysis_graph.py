"""Tests for analysis_graph — LangGraph workflow and SSE streaming."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from agents.base_agent import AgentEvent

from graph.analysis_graph import (
    _parse_url,
    _has_loader_result,
    _get_inputs,
    build_initial_state,
    node_repo_loader,
    node_suggestion,
    node_error,
    route_after_repo_loader,
    _build_graph,
)
from graph.state import SharedState


class TestParseUrl:
    """Tests for the _parse_url helper function."""

    @pytest.mark.parametrize("url,expected", [
        ("https://github.com/owner/repo", ("owner", "repo")),
        ("https://github.com/owner/repo.git", ("owner", "repo")),
        ("git@github.com:owner/repo.git", ("owner", "repo")),
        ("git@github.com:owner/repo", ("owner", "repo")),
        ("owner/repo", ("owner", "repo")),
        ("https://github.com/org-name/project-name", ("org-name", "project-name")),
    ])
    def test_parse_url_valid(self, url, expected):
        assert _parse_url(url) == expected

    @pytest.mark.parametrize("url", [
        "",
        "not-a-url",
        "https://gitlab.com/owner/repo",
        "https://github.com/",
        "https://github.com/owner",
    ])
    def test_parse_url_invalid(self, url):
        assert _parse_url(url) is None


class TestHasLoaderResult:
    """Tests for _has_loader_result."""

    def test_has_loader_result_with_loaded_files(self):
        state: SharedState = {"loaded_files": {"a.py": "content"}, "file_contents": {}}
        assert _has_loader_result(state) is True

    def test_has_loader_result_with_file_contents(self):
        state: SharedState = {"file_contents": {"a.py": "content"}}
        assert _has_loader_result(state) is True

    def test_has_loader_result_empty(self):
        state: SharedState = {"loaded_files": {}, "file_contents": {}}
        assert _has_loader_result(state) is False

    def test_has_loader_result_none(self):
        state: SharedState = {}
        assert _has_loader_result(state) is False


class TestGetInputs:
    """Tests for _get_inputs helper."""

    def test_get_inputs_prefers_loaded_files(self):
        state: SharedState = {
            "loaded_files": {"a.py": "content"},
            "file_contents": {"b.py": "old"},
            "local_path": "/path/to/repo",
            "branch": "main",
        }
        local_path, branch, contents = _get_inputs(state)
        assert contents == {"a.py": "content"}

    def test_get_inputs_falls_back_to_file_contents(self):
        state: SharedState = {
            "file_contents": {"b.py": "content"},
            "local_path": "/path/to/repo",
            "branch": "develop",
        }
        local_path, branch, contents = _get_inputs(state)
        assert contents == {"b.py": "content"}

    def test_get_inputs_extracts_repo_from_loader_result(self):
        state: SharedState = {
            "loaded_files": {},
            "repo_loader_result": {"repo": "myrepo", "owner": "myowner"},
            "branch": "main",
        }
        local_path, branch, contents = _get_inputs(state)
        assert local_path == "myrepo"
        assert branch == "main"


class TestBuildInitialState:
    """Tests for build_initial_state factory function."""

    def test_build_initial_state_returns_shared_state(self):
        state = build_initial_state("https://github.com/test/repo", "develop")

        assert state["repo_url"] == "https://github.com/test/repo"
        assert state["branch"] == "develop"
        assert state["loaded_files"] == {}
        assert state["file_contents"] == {}
        assert state["errors"] == []
        assert state["finished_agents"] == []
        assert state["llm_decision_rounds"] == 0
        assert state["llm_decision_history"] == []

    def test_build_initial_state_defaults(self):
        state = build_initial_state("owner/repo")
        assert state["branch"] == "main"


class TestNodeError:
    """Tests for error handler node."""

    def test_node_error_appends_to_errors(self):
        state: SharedState = {"errors": ["first error"]}
        result = node_error(state)
        assert "Pipeline: 进入错误处理节点" in result["errors"]


class TestRouteAfterRepoLoader:
    """Tests for conditional routing after repo_loader."""

    def test_route_to_code_parser_on_success(self):
        state: SharedState = {"loaded_files": {"a.py": "content"}, "file_contents": {}}
        assert route_after_repo_loader(state) == "code_parser"

    def test_route_to_error_on_failure(self):
        state: SharedState = {"loaded_files": {}, "file_contents": {}}
        assert route_after_repo_loader(state) == "error"


class TestBuildGraph:
    """Tests for graph construction."""

    def test_build_graph_returns_state_graph(self):
        graph = _build_graph()
        assert graph is not None

    def test_build_graph_compiles_without_error(self):
        """The module-level _workflow should compile successfully."""
        from graph.analysis_graph import _workflow
        assert _workflow is not None


class TestNodeRepoLoader:
    """Tests for node_repo_loader with mocked dependencies."""

    def test_node_repo_loader_with_empty_url(self):
        state: SharedState = {
            "repo_url": "",
            "branch": "main",
            "errors": [],
        }
        result = node_repo_loader(state)
        assert "errors" in result

    def test_node_repo_loader_with_mocked_github_api(self, mock_github_tree_response):
        """Test node_repo_loader fetches and classifies files."""
        with patch("agents.repo_loader.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            async def mock_get(url, **kwargs):
                resp = MagicMock()
                resp.status_code = 200
                if "/repos/test/repo/branches/" in url:
                    resp.json.return_value = {"commit": {"sha": "abc123sha"}}
                elif "/git/trees/" in url:
                    resp.json.return_value = mock_github_tree_response
                else:
                    resp.json.return_value = {"default_branch": "main"}
                return resp

            mock_client.get = mock_get
            mock_client_cls.return_value = mock_client

            with patch("agents.repo_loader._get_llm", return_value=None):
                state: SharedState = {
                    "repo_url": "https://github.com/test/repo",
                    "branch": "main",
                    "errors": [],
                    "file_contents": {},
                    "loaded_files": {},
                    "repo_tree": None,
                    "repo_sha": None,
                    "classified_files": None,
                    "llm_decision_rounds": 0,
                    "llm_decision_history": [],
                }
                result = node_repo_loader(state)

                assert "repo_loader_result" in result
                assert result["repo_loader_result"]["sha"] == "abc123sha"


class TestNodeSuggestion:
    """Tests for suggestion node."""

    def test_node_suggestion_with_no_prerequisites(self):
        """Without any prior results, suggestion should still run (rule engine fallback)."""
        state: SharedState = {
            "loaded_files": {"src/main.py": "def main(): pass"},
            "file_contents": {},
            "local_path": "test/repo",
            "branch": "main",
            "code_parser_result": None,
            "tech_stack_result": None,
            "quality_result": None,
            "dependency_result": None,
            "errors": [],
            "finished_agents": [],
        }
        result = node_suggestion(state)

        # Rule engine always generates at least one fallback suggestion
        assert "suggestion_result" in result
        assert "errors" in result
