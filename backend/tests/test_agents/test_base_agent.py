"""Tests for BaseAgent — shared utilities and base class behavior."""

import pytest
from agents.base_agent import AgentEvent, BaseAgent, _make_event


class TestMakeEvent:
    """Tests for the _make_event helper."""

    def test_make_event_with_data(self):
        data = {"key": "value"}
        event = _make_event("quality", "result", "analysis complete", 100, data)

        assert event["type"] == "result"
        assert event["agent"] == "quality"
        assert event["message"] == "analysis complete"
        assert event["percent"] == 100
        assert event["data"] == {"key": "value"}

    def test_make_event_without_data(self):
        event = _make_event("repo_loader", "status", "loading files", 50, None)

        assert event["type"] == "status"
        assert event["agent"] == "repo_loader"
        assert event["message"] == "loading files"
        assert event["percent"] == 50
        assert event["data"] is None

    def test_make_event_returns_correct_type(self):
        event = _make_event("tech_stack", "error", "failed", 0, None)
        assert isinstance(event, dict)
        assert isinstance(event, AgentEvent)


class TestCalcComplexity:
    """Tests for _calc_complexity helper."""

    def test_high_score_low_complexity(self):
        assert BaseAgent._calc_complexity(90) == "Low"

    def test_mid_score_low_complexity(self):
        assert BaseAgent._calc_complexity(80) == "Low"

    def test_threshold_80_boundary(self):
        assert BaseAgent._calc_complexity(79.9) == "Medium"

    def test_mid_score_medium_complexity(self):
        assert BaseAgent._calc_complexity(65) == "Medium"

    def test_threshold_50_boundary(self):
        assert BaseAgent._calc_complexity(50) == "Medium"
        assert BaseAgent._calc_complexity(49.9) == "High"

    def test_low_score_high_complexity(self):
        assert BaseAgent._calc_complexity(0) == "High"
        assert BaseAgent._calc_complexity(30) == "High"


class TestCalcMaintainability:
    """Tests for _calc_maintainability helper."""

    @pytest.mark.parametrize(
        "score,expected",
        [
            (95, "A+"),
            (85, "A"),
            (75, "A"),
            (74.9, "B+"),
            (65, "B+"),
            (64.9, "B"),
            (55, "B"),
            (54.9, "C"),
            (40, "C"),
            (39.9, "C-"),
            (0, "C-"),
        ],
    )
    def test_maintainability_grades(self, score, expected):
        assert BaseAgent._calc_maintainability(score) == expected


class TestWalkFiles:
    """Tests for BaseAgent._walk_files utility."""

    @pytest.mark.asyncio
    async def test_walk_files_all_extensions(self, temp_repo):
        files = await BaseAgent._walk_files(str(temp_repo))

        # Should include all source files
        paths = [f.replace("\\", "/") for f in files]
        assert any("main.py" in p for p in paths)
        assert any("app.tsx" in p for p in paths)
        assert any("package.json" in p for p in paths)
        assert any("requirements.txt" in p for p in paths)

    @pytest.mark.asyncio
    async def test_walk_files_filtered_by_extension(self, temp_repo):
        py_files = await BaseAgent._walk_files(str(temp_repo), extensions=[".py"])
        ts_files = await BaseAgent._walk_files(
            str(temp_repo), extensions=[".ts", ".tsx"]
        )

        py_paths = [f.replace("\\", "/") for f in py_files]
        ts_paths = [f.replace("\\", "/") for f in ts_files]

        assert all(p.endswith(".py") for p in py_paths)
        assert all(p.endswith((".ts", ".tsx")) for p in ts_paths)

    @pytest.mark.asyncio
    async def test_walk_files_respects_ignore_dirs(self, temp_repo):
        # Create a node_modules directory
        nm_dir = temp_repo / "node_modules"
        nm_dir.mkdir()
        (nm_dir / "dep.js").write_text("// should be ignored")
        (nm_dir / "sub" / "deep.js").write_text("// should be ignored")

        # Create a .venv directory
        venv_dir = temp_repo / ".venv"
        venv_dir.mkdir()
        (venv_dir / "lib.py").write_text("# should be ignored")

        files = await BaseAgent._walk_files(str(temp_repo))
        paths = [f.replace("\\", "/") for f in files]

        assert not any("node_modules" in p for p in paths)
        assert not any(".venv" in p for p in paths)

    @pytest.mark.asyncio
    async def test_walk_files_respects_max_files(self, temp_repo):
        files = await BaseAgent._walk_files(str(temp_repo), max_files=2)
        assert len(files) <= 2

    @pytest.mark.asyncio
    async def test_walk_files_empty_dir(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        files = await BaseAgent._walk_files(str(empty_dir))
        assert files == []

    @pytest.mark.asyncio
    async def test_walk_files_ignores_dotfiles(self, temp_repo):
        (temp_repo / ".hidden.ts").write_text("// hidden")
        files = await BaseAgent._walk_files(str(temp_repo))
        paths = [f.replace("\\", "/") for f in files]
        assert not any(".hidden" in p for p in paths)


class TestBaseAgentAbstract:
    """Tests to ensure BaseAgent is properly abstract and enforces interface."""

    def test_base_agent_is_abstract(self):
        """BaseAgent cannot be instantiated directly because stream is abstract."""
        with pytest.raises(TypeError) as exc_info:
            BaseAgent()
        assert "abstract" in str(exc_info.value).lower()

    def test_agent_event_typeddict_fields(self):
        """AgentEvent TypedDict has the expected structure."""
        event: AgentEvent = {
            "type": "result",
            "agent": "quality",
            "message": "done",
            "percent": 100,
            "data": {"score": 90},
        }
        assert event["type"] == "result"
        assert event["agent"] == "quality"
        assert event["percent"] == 100
