"""Pytest configuration and shared fixtures for the backend test suite."""

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the backend package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ─── Async Event Loop Fixture ───────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ─── Mock LLM Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def mock_llm_response() -> MagicMock:
    """Returns a mock LLM response object that mimics LangChain chat model output."""
    mock = MagicMock()
    mock.content = '{"p0_paths": ["package.json", "pyproject.toml"], "p1_paths": ["src/main.py"], "p2_paths": []}'
    return mock


@pytest.fixture
def mock_llm_with_extra(mock_llm_response: MagicMock) -> MagicMock:
    """Mock LLM that requests additional files (need_more=true)."""
    mock = MagicMock()
    mock.content = '{"need_more": true, "reason": "Need more context", "additional_paths": ["src/utils.py", "src/models.py"]}'
    return mock


@pytest.fixture
def mock_llm_no_more(mock_llm_response: MagicMock) -> MagicMock:
    """Mock LLM that says no more files needed."""
    mock = MagicMock()
    mock.content = '{"need_more": false, "reason": "Already have enough context", "additional_paths": []}'
    return mock


# ─── Mock GitHub API Fixtures ──────────────────────────────────────────────

@pytest.fixture
def mock_github_tree_response() -> dict:
    """Mock GitHub tree API response."""
    return {
        "sha": "abc123sha",
        "truncated": False,
        "tree": [
            {"path": "package.json", "type": "blob", "size": 1024},
            {"path": "pyproject.toml", "type": "blob", "size": 512},
            {"path": "src/main.py", "type": "blob", "size": 2048},
            {"path": "src/utils.py", "type": "blob", "size": 768},
            {"path": "README.md", "type": "blob", "size": 256},
            {"path": "node_modules/foo/bar.js", "type": "blob", "size": 100},
        ],
    }


@pytest.fixture
def mock_github_file_content() -> dict[str, str]:
    """Mock file contents returned by GitHub API."""
    return {
        "package.json": '{"name": "test-project", "dependencies": {"react": "^18.0.0"}}',
        "pyproject.toml": "[project]\nname = 'test'\nversion = '0.1.0'",
        "src/main.py": "def main():\n    print('hello')\n\nif __name__ == '__main__':\n    main()",
        "README.md": "# Test Project",
    }


# ─── Mock HTTP Client Fixtures ─────────────────────────────────────────────

@pytest.fixture
def mock_httpx_async_client(
    mock_github_tree_response: dict,
    mock_github_file_content: dict,
) -> Generator[MagicMock, None, None]:
    """Mock httpx.AsyncClient for GitHub API calls."""
    import base64

    async def mock_get(url: str, **kwargs) -> MagicMock:
        response = MagicMock()
        response.status_code = 200

        if "/branches/" in url:
            response.json.return_value = {"commit": {"sha": "abc123sha"}}
        elif "/git/trees/" in url:
            response.json.return_value = mock_github_tree_response
        elif "/contents/" in url:
            path = url.split("/contents/")[1].split("?")[0]
            content = mock_github_file_content.get(path, "content not found")
            encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            response.json.return_value = {"encoding": "base64", "content": encoded}
        else:
            response.json.return_value = {"default_branch": "main"}

        return response

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = mock_get

    return mock_client


# ─── Temp Repository Fixtures ──────────────────────────────────────────────

@pytest.fixture
def temp_repo(tmp_path: Path) -> Generator[Path, None, None]:
    """Creates a temporary repository with Python and TypeScript source files."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    # Python file
    (src_dir / "main.py").write_text("""
def hello():
    return "Hello, world!"

class Greeter:
    def greet(self, name: str) -> str:
        if name:
            return f"Hello, {name}!"
        return "Hello!"
""")

    # TypeScript file
    (src_dir / "app.tsx").write_text("""
export function App() {
    return <div>Hello</div>;
}

export const CONFIG = { debug: true };
""")

    # Package.json
    (tmp_path / "package.json").write_text('{"name": "test", "dependencies": {"react": "^18.0.0"}}')

    # Requirements.txt
    (tmp_path / "requirements.txt").write_text("fastapi>=0.100.0\npydantic>=2.0.0\n")

    return tmp_path


@pytest.fixture
def temp_python_repo(tmp_path: Path) -> Generator[Path, None, None]:
    """Creates a temp repo with multiple Python files for quality analysis tests."""
    (tmp_path / "main.py").write_text("""
import os
import sys

def process(data):
    if data:
        for item in data:
            if item > 0:
                print(item)
    return True

class Handler:
    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)

    def get_all(self):
        return self.items

    def filter_positive(self):
        result = []
        for item in self.items:
            if item > 0:
                result.append(item)
        return result

if __name__ == "__main__":
    h = Handler()
    h.add(-1)
    h.add(2)
    h.add(0)
    print(h.filter_positive())
""")

    (tmp_path / "utils.py").write_text("""
def add(a: int, b: int) -> int:
    return a + b

def multiply(a: int, b: int) -> int:
    return a * b

def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
""")

    (tmp_path / "test_main.py").write_text("""
import pytest
from main import process, Handler

def test_process():
    assert process([1, 2, 3]) == True
    assert process([]) == True

def test_handler():
    h = Handler()
    h.add(1)
    h.add(2)
    assert h.get_all() == [1, 2]
""")

    return tmp_path


# ─── Mock AgentEvent Fixtures ───────────────────────────────────────────────

@pytest.fixture
def sample_agent_events() -> list[dict]:
    """Sample AgentEvent dicts for testing."""
    return [
        {"type": "status", "agent": "quality", "message": "Scanning...", "percent": 10, "data": None},
        {"type": "progress", "agent": "quality", "message": "Analyzing...", "percent": 50, "data": None},
        {"type": "result", "agent": "quality", "message": "Done", "percent": 100, "data": {
            "health_score": 85.0,
            "test_coverage": 60,
            "complexity": "Low",
            "maintainability": "A",
            "python_metrics": {
                "total_functions": 5,
                "total_classes": 1,
                "avg_complexity": 3.2,
                "max_complexity": 5,
                "over_complexity_count": 0,
                "long_functions": [],
                "large_files": [],
            },
            "typescript_metrics": {},
            "duplication": {"score": 2.1, "duplicated_blocks": 0, "total_blocks_checked": 50, "duplication_level": "Low"},
            "test_info": {"estimated_coverage": 60, "test_files": 1, "source_files": 2, "test_frameworks": ["pytest"]},
            "total_files": 3,
            "python_files": 2,
            "typescript_files": 1,
        }},
    ]


# ─── Mock SharedState Fixtures ─────────────────────────────────────────────

@pytest.fixture
def mock_shared_state() -> dict:
    """Mock SharedState dict for graph tests."""
    return {
        "repo_url": "https://github.com/test/repo",
        "branch": "main",
        "auth_user_id": "user123",
        "file_contents": {},
        "loaded_files": {},
        "loaded_paths": [],
        "repo_sha": None,
        "code_parser_result": None,
        "tech_stack_result": None,
        "quality_result": None,
        "dependency_result": None,
        "suggestion_result": None,
        "optimization_result": None,
        "final_result": None,
        "errors": [],
        "finished_agents": [],
        "react_events": [],
        "react_summary": "",
        "react_iterations": 0,
        "explorer_result": None,
        "explorer_events": [],
        "architecture_result": None,
        "architecture_events": [],
    }


# ─── Patch Decorators ───────────────────────────────────────────────────────

def patch_llm(return_response: MagicMock | None = None):
    """Decorator to patch the LLM getter so it returns a mock response."""
    def decorator(func):
        return patch("agents.repo_loader._get_llm", return_value=return_response)(func)
    return decorator


def patch_httpx_client(mock_client: MagicMock):
    """Decorator to patch httpx.AsyncClient."""
    return patch("httpx.AsyncClient", return_value=mock_client)
