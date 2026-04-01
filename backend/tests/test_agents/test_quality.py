"""Tests for QualityAgent — code quality analysis."""

import pytest
from unittest.mock import patch, MagicMock

from agents.quality import QualityAgent, _read_text, _cyclomatic_complexity, _q_load_parser


class TestReadText:
    """Tests for _read_text helper."""

    def test_read_text_utf8(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello, 世界!", encoding="utf-8")
        assert _read_text(str(f)) == "Hello, 世界!"

    def test_read_text_latin1_fallback(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"Hello \x80 World")  # Invalid UTF-8
        result = _read_text(str(f))
        assert "Hello" in result

    def test_read_text_missing_file(self):
        result = _read_text("/nonexistent/file.txt")
        assert result == ""


class TestCyclomaticComplexity:
    """Tests for _cyclomatic_complexity helper."""

    def test_simple_function_has_minimum_1(self):
        """A function with no branching should return at least 1."""
        mock_node = MagicMock()
        mock_node.type = "function_definition"
        mock_node.children = []
        assert _cyclomatic_complexity(mock_node) >= 1

    def test_function_with_if_increases_complexity(self):
        mock_if = MagicMock()
        mock_if.type = "if_statement"
        mock_if.children = []

        mock_func = MagicMock()
        mock_func.type = "function_definition"
        mock_func.children = [mock_if]

        # Should be 1 (base) + 1 (if) = 2
        assert _cyclomatic_complexity(mock_func) >= 2

    def test_function_with_multiple_branches(self):
        mock_if = MagicMock()
        mock_if.type = "if_statement"
        mock_if.children = []

        mock_for = MagicMock()
        mock_for.type = "for_statement"
        mock_for.children = []

        mock_and = MagicMock()
        mock_and.type = "and_operator"
        mock_and.children = []

        mock_func = MagicMock()
        mock_func.type = "function_definition"
        mock_func.children = [mock_if, mock_for, mock_and]

        # Should be 1 (base) + 3 (branches) = 4
        assert _cyclomatic_complexity(mock_func) >= 4


class TestQualityAgentStream:
    """Tests for QualityAgent.stream() — the main async generator."""

    @pytest.mark.asyncio
    async def test_stream_yields_status_event_first(self):
        agent = QualityAgent()
        events = []
        async for event in agent.stream("fake_repo_path", file_contents={}):
            events.append(event)
            if event["type"] == "result":
                break

        assert events[0]["type"] == "status"
        assert events[0]["agent"] == "quality"

    @pytest.mark.asyncio
    async def test_stream_with_empty_file_contents(self):
        agent = QualityAgent()
        events = []
        async for event in agent.stream("fake_repo_path", file_contents={}):
            events.append(event)
            if event["type"] in ("result", "error"):
                break

        # Should handle empty files gracefully
        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_stream_with_python_files(self, temp_python_repo):
        from agents.quality import QualityAgent

        agent = QualityAgent()
        events = []
        result_data = None

        async for event in agent.stream(str(temp_python_repo)):
            events.append(event)
            if event["type"] == "result":
                result_data = event["data"]
                break

        assert result_data is not None
        assert result_data["total_files"] > 0
        assert result_data["python_files"] >= 2

    @pytest.mark.asyncio
    async def test_stream_with_typescript_files(self, temp_repo):
        agent = QualityAgent()
        events = []
        result_data = None

        async for event in agent.stream(str(temp_repo)):
            events.append(event)
            if event["type"] == "result":
                result_data = event["data"]
                break

        assert result_data is not None
        assert result_data["typescript_files"] >= 1

    @pytest.mark.asyncio
    async def test_stream_result_contains_expected_fields(self, temp_python_repo):
        agent = QualityAgent()
        result_data = None

        async for event in agent.stream(str(temp_python_repo)):
            if event["type"] == "result":
                result_data = event["data"]
                break

        assert result_data is not None
        expected_keys = [
            "health_score", "test_coverage", "complexity", "maintainability",
            "python_metrics", "typescript_metrics", "duplication",
            "test_info", "total_files", "python_files", "typescript_files",
        ]
        for key in expected_keys:
            assert key in result_data, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_stream_percent_increases(self, temp_python_repo):
        agent = QualityAgent()
        percents = []

        async for event in agent.stream(str(temp_python_repo)):
            if event["percent"] is not None:
                percents.append(event["percent"])
            if event["type"] == "result":
                break

        assert percents == sorted(percents)

    @pytest.mark.asyncio
    async def test_stream_inmemory_mode_with_py_contents(self):
        """Test GitHub API mode: file_contents passed directly."""
        contents = {
            "src/main.py": "def foo():\n    return 1\n",
            "src/utils.py": "def bar():\n    return 2\n",
        }
        agent = QualityAgent()
        result_data = None

        async for event in agent.stream("owner/repo", file_contents=contents):
            if event["type"] == "result":
                result_data = event["data"]
                break

        assert result_data is not None
        assert result_data["python_files"] == 2
        assert result_data["total_files"] == 2


class TestQualityAgentMetrics:
    """Tests for QualityAgent metric computation methods."""

    def test_estimate_test_coverage_inmemory(self):
        py_contents = {
            "src/main.py": "",
            "src/utils.py": "",
            "tests/test_main.py": "",
        }
        ts_contents: dict[str, str] = {}

        result = QualityAgent._estimate_test_coverage_inmemory(py_contents, ts_contents)

        assert result["estimated_coverage"] > 0
        assert result["test_files"] == 1
        assert result["source_files"] == 2
        assert "pytest" in result["test_frameworks"]

    def test_estimate_test_coverage_inmemory_no_tests(self):
        py_contents = {"src/main.py": "", "src/utils.py": ""}
        ts_contents: dict[str, str] = {}

        result = QualityAgent._estimate_test_coverage_inmemory(py_contents, ts_contents)

        assert result["estimated_coverage"] == 0
        assert result["test_files"] == 0

    def test_estimate_test_coverage_detects_vitest(self):
        py_contents: dict[str, str] = {}
        ts_contents = {
            "src/App.tsx": "",
            "src/__tests__/App.test.tsx": "import { test } from 'vitest'",
        }

        result = QualityAgent._estimate_test_coverage_inmemory(py_contents, ts_contents)

        assert "Vitest" in result["test_frameworks"]

    def test_estimate_test_coverage_detects_jest(self):
        py_contents: dict[str, str] = {}
        ts_contents = {
            "src/App.tsx": "",
            "src/App.spec.tsx": "import { describe } from '@testing-library'",
        }

        result = QualityAgent._estimate_test_coverage_inmemory(py_contents, ts_contents)

        assert "Jest/Testing Library" in result["test_frameworks"]

    def test_estimate_test_coverage_caps_at_95(self):
        py_contents = {}
        ts_contents = {f"tests/test_{i}.tsx": "" for i in range(100)}

        result = QualityAgent._estimate_test_coverage_inmemory(py_contents, ts_contents)

        assert result["estimated_coverage"] <= 95.0

    def test_compute_health_score_perfect(self):
        py_metrics = {"avg_complexity": 1.0}
        ts_metrics: dict = {}
        duplication = {"score": 0}
        test_info = {"estimated_coverage": 100}

        score = QualityAgent._compute_health_score(py_metrics, ts_metrics, duplication, test_info)
        assert score == 100.0  # max with coverage bonus

    def test_compute_health_score_high_complexity_penalized(self):
        py_metrics = {"avg_complexity": 15.0}  # >10, penalized
        ts_metrics: dict = {}
        duplication = {"score": 0}
        test_info = {"estimated_coverage": 100}

        score = QualityAgent._compute_health_score(py_metrics, ts_metrics, duplication, test_info)
        assert score < 100.0

    def test_compute_health_score_high_duplication_penalized(self):
        py_metrics = {"avg_complexity": 2.0}
        ts_metrics: dict = {}
        duplication = {"score": 30}  # >15, penalized
        test_info = {"estimated_coverage": 50}

        score = QualityAgent._compute_health_score(py_metrics, ts_metrics, duplication, test_info)
        assert score < 100.0

    def test_compute_health_score_low_coverage_penalized(self):
        py_metrics = {"avg_complexity": 3.0}
        ts_metrics: dict = {}
        duplication = {"score": 2}
        test_info = {"estimated_coverage": 10}  # <30, penalized

        score = QualityAgent._compute_health_score(py_metrics, ts_metrics, duplication, test_info)
        assert score < 100.0

    def test_compute_health_score_bounded(self):
        py_metrics = {"avg_complexity": 20.0}
        ts_metrics = {"avg_complexity": 20.0}
        duplication = {"score": 50}
        test_info = {"estimated_coverage": 0}

        score = QualityAgent._compute_health_score(py_metrics, ts_metrics, duplication, test_info)
        assert 0 <= score <= 100

    def test_calc_duplication_inmemory_no_duplication(self):
        contents = {
            "a.py": "def foo():\n    return 1\n",
            "b.py": "def bar():\n    return 2\n",
        }
        result = QualityAgent._calc_duplication_inmemory(contents)

        assert "score" in result
        assert "duplication_level" in result
        assert result["duplication_level"] in ("Low", "Medium", "High")

    def test_calc_duplication_inmemory_with_duplication(self):
        duplicate_block = "def common():\n    return True\n"
        contents = {
            "a.py": duplicate_block + "def a():\n    return 1\n",
            "b.py": duplicate_block + "def b():\n    return 2\n",
            "c.py": duplicate_block + "def c():\n    return 3\n",
        }
        result = QualityAgent._calc_duplication_inmemory(contents)

        assert result["duplicated_blocks"] > 0


class TestQualityAgentWalk:
    """Tests for QualityAgent._walk_by_lang static method."""

    @pytest.mark.asyncio
    async def test_walk_by_lang_python_only(self, temp_python_repo):
        files = await QualityAgent._walk_by_lang(str(temp_python_repo), [".py"])
        paths = [f.replace("\\", "/") for f in files]
        assert all(p.endswith(".py") for p in paths)
        assert len(files) >= 2

    @pytest.mark.asyncio
    async def test_walk_by_lang_none_for_all_files(self, temp_python_repo):
        files = await QualityAgent._walk_by_lang(str(temp_python_repo), None)
        assert len(files) >= 3  # Python + test files

    @pytest.mark.asyncio
    async def test_walk_by_lang_respects_ignore_dirs(self, temp_python_repo):
        nm_dir = temp_python_repo / "node_modules"
        nm_dir.mkdir()
        (nm_dir / "foo.js").write_text("// ignored")

        py_files = await QualityAgent._walk_by_lang(str(temp_python_repo), [".py"])
        paths = [f.replace("\\", "/") for f in py_files]
        assert not any("node_modules" in p for p in paths)


class TestWalkPython:
    """Tests for QualityAgent._walk_python static method."""

    def test_walk_python_counts_functions(self):
        parser = _q_load_parser("python")

        source = b"""
def func_a():
    if True:
        return 1

def func_b(x):
    while x > 0:
        x -= 1
    return x
"""
        tree = parser.parse(source)
        funcs, classes, complexity = QualityAgent._walk_python(tree.root_node, [], 0)

        assert funcs >= 2
        assert classes == 0

    def test_walk_python_counts_classes(self):
        parser = _q_load_parser("python")

        source = b"""
class Foo:
    def method(self):
        pass

class Bar:
    pass
"""
        tree = parser.parse(source)
        funcs, classes, complexity = QualityAgent._walk_python(tree.root_node, [], 0)

        assert classes >= 2


class TestWalkTS:
    """Tests for QualityAgent._walk_ts static method."""

    def test_walk_ts_counts_functions(self):
        parser = _q_load_parser("typescript")

        source = b"""
export const foo = () => 1;
export function bar(x: number): number {
    return x * 2;
}
"""
        tree = parser.parse(source)
        funcs, classes, complexity = QualityAgent._walk_ts(tree.root_node)

        assert funcs >= 2

    def test_walk_ts_counts_classes(self):
        parser = _q_load_parser("typescript")

        source = b"""
class Greeter {
    greet(name: string) {
        return `Hello, ${name}`;
    }
}
interface Config {
    debug: boolean;
}
"""
        tree = parser.parse(source)
        funcs, classes, complexity = QualityAgent._walk_ts(tree.root_node)

        assert classes >= 1  # class
