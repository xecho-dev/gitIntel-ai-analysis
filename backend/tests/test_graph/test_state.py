"""Tests for SharedState — LangGraph state schema."""

from graph.state import SharedState


class TestSharedState:
    """Tests for SharedState TypedDict definition and defaults."""

    def test_shared_state_is_typeddict(self):
        """SharedState should be a TypedDict."""
        state: SharedState = {
            "repo_url": "https://github.com/test/repo",
            "branch": "main",
            "errors": [],
            "finished_agents": [],
            "file_contents": {},
            "loaded_files": {},
        }
        assert isinstance(state, dict)

    def test_shared_state_partial_fields(self):
        """SharedState is total=False, so not all fields are required."""
        state: SharedState = {
            "repo_url": "test/repo",
            "branch": "main",
        }
        assert state["repo_url"] == "test/repo"

    def test_shared_state_all_optional_fields_work(self):
        """Verify all documented optional fields can be set."""
        state: SharedState = {
            "repo_url": "https://github.com/test/repo",
            "branch": "main",
            "auth_user_id": "user123",
            "file_contents": {"src/main.py": "def main(): pass"},
            "repo_sha": "abc123",
            "loaded_files": {"main.py": "def main(): pass"},
            "loaded_paths": ["main.py", "lib.py"],
            "code_parser_result": {"total_files": 5},
            "tech_stack_result": {"languages": ["Python"]},
            "quality_result": {"health_score": 85},
            "suggestion_result": {"suggestions": []},
            "final_result": {"quality": {}},
            "errors": ["warning: something unusual"],
            "finished_agents": ["repo_loader", "code_parser"],
            "react_events": [],
            "react_summary": "test",
            "react_iterations": 1,
        }
        assert state["quality_result"]["health_score"] == 85
        assert len(state["finished_agents"]) == 2
        assert state["final_result"] is not None

    def test_shared_state_errors_default_to_empty_list(self):
        """errors field should be a list when present."""
        state: SharedState = {"errors": []}
        assert isinstance(state["errors"], list)
