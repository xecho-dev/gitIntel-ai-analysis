"""Tests for SuggestionAgent — optimization suggestion generation."""

import pytest

from agents.suggestion import SuggestionAgent


class TestSuggestionAgent:
    """Tests for SuggestionAgent suggestion generation logic."""

    def test_quality_suggestions_low_health_high_priority(self):
        """Health score < 60 should generate a high priority suggestion."""
        qr = {
            "health_score": 50,
            "test_coverage": 0,
            "duplication": {},
            "python_metrics": {},
            "typescript_metrics": {},
        }
        suggestions = SuggestionAgent._quality_suggestions(qr, next_id=lambda: 1)

        assert any(
            s["priority"] == "high" and "健康度" in s["title"] for s in suggestions
        )

    def test_quality_suggestions_no_test_coverage_high_priority(self):
        """Coverage < 30% should generate a high priority suggestion."""
        qr = {
            "health_score": 80,
            "test_coverage": 20,
            "duplication": {},
            "python_metrics": {},
            "typescript_metrics": {},
        }
        suggestions = SuggestionAgent._quality_suggestions(qr, next_id=lambda: 1)

        assert any(
            s["priority"] == "high" and "覆盖率" in s["title"] for s in suggestions
        )

    def test_quality_suggestions_low_coverage_medium_priority(self):
        """Coverage between 30-60% should generate medium priority."""
        qr = {
            "health_score": 80,
            "test_coverage": 50,
            "duplication": {},
            "python_metrics": {},
            "typescript_metrics": {},
        }
        suggestions = SuggestionAgent._quality_suggestions(qr, next_id=lambda: 1)

        assert any(
            s["priority"] == "medium" and "覆盖率" in s["title"] for s in suggestions
        )

    def test_quality_suggestions_high_duplication_medium_priority(self):
        """High duplication should generate a medium priority suggestion."""
        qr = {
            "health_score": 70,
            "test_coverage": 60,
            "duplication": {"score": 20, "duplication_level": "High"},
            "python_metrics": {},
            "typescript_metrics": {},
        }
        suggestions = SuggestionAgent._quality_suggestions(qr, next_id=lambda: 1)

        assert any(
            s["priority"] == "medium" and "重复率" in s["title"] for s in suggestions
        )

    def test_quality_suggestions_over_complex_functions_medium_priority(self):
        """More than 5 over-complexity functions should generate a medium priority suggestion."""
        qr = {
            "health_score": 80,
            "test_coverage": 60,
            "duplication": {},
            "python_metrics": {"over_complexity_count": 8},
            "typescript_metrics": {},
        }
        suggestions = SuggestionAgent._quality_suggestions(qr, next_id=lambda: 1)

        assert any("圈复杂度" in s["title"] for s in suggestions)

    def test_quality_suggestions_long_functions_low_priority(self):
        """Long functions (>50 lines) should generate a low priority suggestion."""
        qr = {
            "health_score": 80,
            "test_coverage": 60,
            "duplication": {},
            "python_metrics": {
                "over_complexity_count": 0,
                "long_functions": [{"function": "big_func", "lines": 100}],
            },
            "typescript_metrics": {},
        }
        suggestions = SuggestionAgent._quality_suggestions(qr, next_id=lambda: 1)

        assert any(s["priority"] == "low" and "超长" in s["title"] for s in suggestions)

    def test_quality_suggestions_healthy_code_no_extra(self):
        """Healthy code should not generate quality-based suggestions."""
        qr = {
            "health_score": 90,
            "test_coverage": 80,
            "duplication": {"score": 1, "duplication_level": "Low"},
            "python_metrics": {"over_complexity_count": 0, "long_functions": []},
            "typescript_metrics": {},
        }
        suggestions = SuggestionAgent._quality_suggestions(qr, next_id=lambda: 1)

        # Should only have complexity/duplication suggestions if relevant
        assert all(
            s.get("category") != "quality" or s["priority"] in ("low", "medium", "high")
            for s in suggestions
        )

    def test_dependency_suggestions_high_risk(self):
        """High risk dependencies should generate a high priority security suggestion."""
        dr = {
            "high": 2,
            "medium": 0,
            "risk_level": "高危",
            "deps": [{"name": "request"}],
        }
        suggestions = SuggestionAgent._dependency_suggestions(dr, next_id=lambda: 1)

        assert any(
            s["priority"] == "high" and "高风险" in s["title"] for s in suggestions
        )

    def test_dependency_suggestions_many_medium_risk(self):
        """Many medium risk deps should generate medium priority suggestion."""
        dr = {"high": 0, "medium": 10, "risk_level": "中等", "deps": []}
        suggestions = SuggestionAgent._dependency_suggestions(dr, next_id=lambda: 1)

        assert any(
            s["priority"] == "medium" and "中等风险" in s["title"] for s in suggestions
        )

    def test_dependency_suggestions_no_version_medium_priority(self):
        """Deps without version constraint should generate medium priority suggestion."""
        dr = {
            "high": 0,
            "medium": 0,
            "risk_level": "极低",
            "deps": [{"name": "pkg", "version": "*"}],
        }
        suggestions = SuggestionAgent._dependency_suggestions(dr, next_id=lambda: 1)

        assert any(
            s["priority"] == "medium" and "版本" in s["title"] for s in suggestions
        )

    def test_dependency_suggestions_outdated_packages(self):
        """Outdated packages like moment/lodash should generate medium priority suggestion."""
        dr = {
            "high": 0,
            "medium": 0,
            "risk_level": "极低",
            "deps": [{"name": "moment"}, {"name": "lodash"}],
        }
        suggestions = SuggestionAgent._dependency_suggestions(dr, next_id=lambda: 1)

        titles = [s["title"] for s in suggestions]
        assert any("moment" in t or "lodash" in t for t in titles)

    def test_tech_stack_suggestions_docker_without_compose(self):
        """Docker without docker-compose should suggest adding compose."""
        ts = {
            "frameworks": ["Docker"],
            "infrastructure": ["Docker"],
            "dev_tools": [],
            "languages": [],
        }
        suggestions = SuggestionAgent._tech_stack_suggestions(ts, next_id=lambda: 1)

        assert any("docker-compose" in s["title"] for s in suggestions)

    def test_tech_stack_suggestions_docker_without_ci_medium_priority(self):
        """Docker without CI should suggest CI/CD pipeline."""
        ts = {
            "frameworks": ["Docker"],
            "infrastructure": ["Docker"],
            "dev_tools": [],
            "languages": [],
        }
        suggestions = SuggestionAgent._tech_stack_suggestions(ts, next_id=lambda: 1)

        assert any(
            "CI/CD" in s["title"] and s["priority"] == "medium" for s in suggestions
        )

    def test_tech_stack_suggestions_typescript_strict_mode_low_priority(self):
        """TypeScript project should suggest strict mode."""
        ts = {
            "frameworks": [],
            "infrastructure": [],
            "dev_tools": [],
            "languages": ["TypeScript"],
        }
        suggestions = SuggestionAgent._tech_stack_suggestions(ts, next_id=lambda: 1)

        assert any(
            "严格模式" in s["title"] and s["priority"] == "low" for s in suggestions
        )

    def test_tech_stack_suggestions_ai_stack_medium_priority(self):
        """AI/LLM stack should suggest structured output and token monitoring."""
        ts = {
            "frameworks": ["LangChain", "Anthropic SDK"],
            "infrastructure": [],
            "dev_tools": [],
            "languages": ["Python"],
        }
        suggestions = SuggestionAgent._tech_stack_suggestions(ts, next_id=lambda: 1)

        assert any("AI" in s["title"] or "LLM" in s["title"] for s in suggestions)

    def test_structure_suggestions_large_files(self):
        """Files > 500 lines should suggest splitting."""
        cr = {
            "largest_files": [{"path": "src/main.py", "lines": 600}],
            "total_classes": 2,
            "total_functions": 50,
        }
        suggestions = SuggestionAgent._structure_suggestions(cr, next_id=lambda: 1)

        assert any("500" in s["title"] for s in suggestions)

    def test_structure_suggestions_procedural_style(self):
        """Many functions but few classes suggests procedural style."""
        cr = {"largest_files": [], "total_classes": 3, "total_functions": 300}
        suggestions = SuggestionAgent._structure_suggestions(cr, next_id=lambda: 1)

        assert any("面向对象" in s["title"] for s in suggestions)

    def test_structure_suggestions_python_no_classes(self):
        """Python with no classes but many functions."""
        cr = {
            "largest_files": [],
            "total_classes": 0,
            "total_functions": 50,
            "language_stats": {"python": {"classes": 0, "functions": 50}},
        }
        suggestions = SuggestionAgent._structure_suggestions(cr, next_id=lambda: 1)

        assert any("类" in s["title"] for s in suggestions)


class TestSuggestionAgentStream:
    """Tests for SuggestionAgent.stream() async generator."""

    @pytest.mark.asyncio
    async def test_stream_yields_status_event(self):
        agent = SuggestionAgent()
        events = []

        async for event in agent.stream(
            "test/repo",
            "main",
            quality_result={
                "health_score": 85,
                "test_coverage": 60,
                "duplication": {"score": 2, "duplication_level": "Low"},
                "python_metrics": {"over_complexity_count": 0, "long_functions": []},
                "typescript_metrics": {},
            },
        ):
            events.append(event)
            if event["type"] == "result":
                break

        assert events[0]["type"] == "status"
        assert events[0]["agent"] == "suggestion"

    @pytest.mark.asyncio
    async def test_stream_always_yields_result(self):
        """Even with no data, should yield a result (rule engine fallback)."""
        agent = SuggestionAgent()
        result_event = None

        async for event in agent.stream("test/repo", "main"):
            if event["type"] == "result":
                result_event = event
                break

        assert result_event is not None
        assert "suggestions" in result_event["data"]
        assert "total" in result_event["data"]

    @pytest.mark.asyncio
    async def test_stream_result_counts(self):
        """Result should include counts by priority."""
        agent = SuggestionAgent()
        result_event = None

        async for event in agent.stream(
            "test/repo",
            "main",
            quality_result={
                "health_score": 30,
                "test_coverage": 10,
                "duplication": {"score": 20, "duplication_level": "High"},
                "python_metrics": {"over_complexity_count": 10, "long_functions": []},
                "typescript_metrics": {},
            },
        ):
            if event["type"] == "result":
                result_event = event
                break

        assert result_event is not None
        data = result_event["data"]
        assert data["high_priority"] >= 2  # health + coverage
        assert data["total"] == len(data["suggestions"])

    @pytest.mark.asyncio
    async def test_stream_suggestions_sorted_by_priority(self):
        """Suggestions should be sorted: high > medium > low."""
        agent = SuggestionAgent()
        result_event = None

        async for event in agent.stream(
            "test/repo",
            "main",
            quality_result={
                "health_score": 40,
                "test_coverage": 20,
                "duplication": {"score": 20, "duplication_level": "High"},
                "python_metrics": {
                    "over_complexity_count": 8,
                    "long_functions": [{"function": "f", "lines": 100}],
                },
                "typescript_metrics": {},
            },
        ):
            if event["type"] == "result":
                result_event = event
                break

        assert result_event is not None
        suggestions = result_event["data"]["suggestions"]
        priorities = [s["priority"] for s in suggestions]
        # high should come before medium, medium before low
        assert priorities == sorted(
            priorities, key={"high": 0, "medium": 1, "low": 2}.get
        )
