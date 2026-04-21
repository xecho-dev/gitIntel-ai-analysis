"""
并行探索 Agent — 多个 Tool Use Agent 并行工作，探索仓库不同维度。

每个子 Agent 负责一个维度，可以独立调用工具探索：
  - TechStackExplorer:   技术栈识别
  - QualityExplorer:     质量热点发现
  - ArchitectureExplorer: 架构模式识别
  - DependencyExplorer:   依赖关系分析

这些 Agent 都基于 ReAct 模式，可以自主决定调用哪些工具。
可以并行运行（asyncio.gather），也可以串行运行。

用法：
    explorers = await ExplorerOrchestrator().explore_all(owner, repo, branch)
    # 返回 {
    #     "tech_stack": {...},
    #     "quality_hotspots": {...},
    #     "architecture": {...},
    #     "dependency": {...},
    # }
"""
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

logger = logging.getLogger("gitintel")

# ─── Token 预算配置（可由环境变量覆盖）───────────────────────────────────────

_MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "2048"))
_EXPLORER_MAX_ITERATIONS = int(os.getenv("EXPLORER_MAX_ITERATIONS", "2"))
_TOOL_RESULT_TRUNCATE = int(os.getenv("TOOL_RESULT_TRUNCATE", "1500"))

# ─── System Prompts（精简版，减少 token 消耗）────────────────────────────────

TECH_STACK_SYSTEM = """你是一名技术架构师，为 GitIntel 系统识别 GitHub 仓库的技术栈。

任务：识别仓库的 (1)编程语言 (2)框架/库 (3)基础设施 (4)开发工具 (5)包管理器 (6)部署方式。

工具：get_repo_info(仓库信息), get_file_tree(文件树), read_file_content(文件内容),
search_code(搜索代码), parse_file_ast(AST解析)。

工作流：先读配置文件(pyproject.toml等)→搜索代码特征确认框架→读入口文件→检查基础设施。

输出 JSON（不要任何额外文字）：
{
  "languages": ["Python"],
  "frameworks": [{"name": "FastAPI", "confidence": 0.95, "evidence": ["@app.route"]}],
  "infrastructure": ["Docker"],
  "dev_tools": ["pytest"],
  "package_manager": "pip",
  "deployment": ["Docker"],
  "config_files_found": ["pyproject.toml"],
  "confidence": 0.0-1.0,
  "summary": "一句话描述技术栈"
}

要求：confidence<0.5时标注不确定；每个框架给出evidence；无证据不猜测。"""

QUALITY_SYSTEM = """你是一名代码审计专家，为 GitIntel 发现仓库中的代码质量问题和潜在风险。

关注维度：(1)代码异味(过长函数>50行、深度嵌套>4层) (2)安全问题(硬编码密码/Secret、eval) (3)性能隐患(N+1、内存泄漏) (4)测试覆盖 (5)可维护性(紧耦合、循环依赖)。

工具：get_file_tree(文件树), read_file_content(读源码), search_code(搜索问题模式),
detect_code_smells(代码异味检测), parse_file_ast(AST解析)。

工作流：get_file_tree了解规模→搜索已知问题模式(硬编码/eval/密码)→detect_code_smells分析核心文件→读源码确认。

输出 JSON（hotspots按severity降序）：
{
  "hotspots": [
    {"type": "hardcoded_secret", "file": "path", "line": 10, "severity": "high",
     "description": "描述", "suggestion": "具体改进建议"}
  ],
  "quality_score": 0-100,
  "test_coverage_estimate": "low|medium|high",
  "main_concerns": ["最关注的3个问题"],
  "positive_patterns": ["做得好的地方"],
  "complexity": "Low|Medium|High",
  "maintainability": "Low|Medium|High",
  "llmPowered": true,
  "maint_score": 0-100,
  "comp_score": 0-100,
  "dup_score": 0-100,
  "test_score": 0-100,
  "coup_score": 0-100
}

说明：maint_score=可维护性评分，comp_score=复杂度评分(越低越好)，dup_score=代码独特率(越高越好)，test_score=测试覆盖评分，coup_score=耦合度评分(越低越好)。

要求：每个hotspot给出精确文件路径和行号；suggestion必须具体可执行。"""

ARCHITECTURE_SYSTEM = """你是一名软件架构专家，识别 GitHub 仓库的架构模式和设计决策。

关注维度：(1)架构风格(单体/微服务/CleanArchitecture/DDD等) (2)设计模式(Repository/Middleware等) (3)分层架构 (4)模块组织 (5)组件关系 (6)架构问题。

工具：get_file_tree(文件树), read_file_content(核心文件), parse_file_ast(AST),
search_code(架构模式搜索)。

工作流：分析目录结构→读入口文件和核心模块→parse_file_ast理解类/接口关系→搜索架构模式代码。

输出 JSON：
{
  "architecture_style": "Modular Monolith",
  "components": [{"name": "组件名", "responsibility": "职责", "depends_on": ["依赖"]}],
  "design_patterns": [{"pattern": "Repository", "location": "文件", "description": "用法"}],
  "layers": [{"name": "presentation", "files": ["关键文件"], "description": "职责"}],
  "complexity": "Low|Medium|High",
  "maintainability": "A|B|C|D|E",
  "summary": "深度架构描述",
  "strengths": ["好的架构决策"],
  "concerns": ["潜在问题"]
}

要求：maintainability评分要有依据；summary要有信息量。"""


# ─── 结果结构 ────────────────────────────────────────────────────────────────

@dataclass
class ExplorerResult:
    explorer_type: str
    findings: dict = field(default_factory=dict)
    tool_calls: list[dict] = field(default_factory=list)
    error: str = ""
    duration_ms: float = 0.0


# ─── 基础 Explorer ───────────────────────────────────────────────────────────

class BaseExplorerAgent:
    """所有探索 Agent 的基类，定义统一的工具调用接口。"""

    MAX_ITERATIONS = _EXPLORER_MAX_ITERATIONS  # 由环境变量控制，默认 4
    MAX_TOOL_CALLS = _EXPLORER_MAX_ITERATIONS * 2  # 最多 tool calls 数

    def __init__(self):
        self.llm = self._get_llm()
        self.tools = self._get_tools()
        self.system_prompt = ""

    @staticmethod
    def _get_llm():
        try:
            from utils.llm_factory import get_llm_with_tracking
            return get_llm_with_tracking(agent_name="Explorer", max_tokens=_MAX_OUTPUT_TOKENS)
        except ImportError:
            return None

    @staticmethod
    def _get_tools():
        from tools.github_tools import get_repo_info, get_file_tree, read_file_content, search_code
        from tools.code_tools import parse_file_ast, detect_code_smells, summarize_code_file
        return [
            get_repo_info, get_file_tree, read_file_content,
            search_code, parse_file_ast, detect_code_smells, summarize_code_file,
        ]

    async def explore(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
        file_contents: dict[str, str] | None = None,
    ) -> ExplorerResult:
        """执行探索。"""
        import time
        t0 = time.time()

        result = ExplorerResult(explorer_type=self.__class__.__name__)

        # 确保分支存在：如果用户传入 main 但仓库实际是 master，自动修正
        if branch in ("main", ""):
            actual_branch = await self._get_default_branch(owner, repo)
            if actual_branch and actual_branch != branch:
                logger.info(f"[{self.__class__.__name__}] 分支修正: {branch} -> {actual_branch}")
                branch = actual_branch

        if self.llm is None:
            result.error = "LLM 不可用"
            result.findings = self._rule_based_fallback(owner, repo, branch, file_contents)
            result.duration_ms = (time.time() - t0) * 1000
            return result

        try:
            findings = await self._react_explore(owner, repo, branch, file_contents)
            result.findings = findings
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 探索失败: {e}")
            result.error = str(e)
            result.findings = self._rule_based_fallback(owner, repo, branch, file_contents)

        result.duration_ms = (time.time() - t0) * 1000
        return result

    async def _get_default_branch(self, owner: str, repo: str) -> str:
        """获取仓库的默认分支。"""
        try:
            # 直接调用底层 async 实现，避免 asyncio.run() 在 event loop 中的问题
            from tools.github_tools import _get_default_branch_impl
            result = await _get_default_branch_impl(owner, repo)
            logger.debug(f"[{self.__class__.__name__}] _get_default_branch({owner}/{repo}) -> {result}")
            return result if result else "main"
        except Exception as e:
            logger.warning(f"[{self.__class__.__name__}] _get_default_branch 失败: {e}")
            return "main"

    async def _react_explore(
        self, owner: str, repo: str, branch: str,
        file_contents: dict[str, str] | None
    ) -> dict:
        """基于 ReAct 的探索逻辑。"""
        # 优先使用 react_loader 已加载的文件内容，直接分析不再重复探索
        if file_contents and len(file_contents) > 0:
            logger.info(
                f"[{self.__class__.__name__}] 复用 {len(file_contents)} 个预加载文件，"
                "跳过 ReAct 探索，直接分析"
            )
            messages = [
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=self._build_initial_context(owner, repo, branch, file_contents)),
                HumanMessage(content="请基于以上文件内容，直接输出分析结果（JSON 格式）。"),
            ]
            try:
                final = await self.llm.ainvoke(messages)
                return self._parse_final_result(final.content)
            except Exception as e:
                logger.warning(f"[{self.__class__.__name__}] 分析失败: {e}")
                return self._rule_based_fallback(owner, repo, branch, file_contents)

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=self._build_initial_context(owner, repo, branch, file_contents)),
        ]

        for iteration in range(self.MAX_ITERATIONS):
            # ── DEBUG: 记录消息结构 ──
            msg_types = [f"{type(m).__name__}" for m in messages]
            has_dangling = any(
                type(messages[i]).__name__ == "HumanMessage" and
                type(messages[i+1]).__name__ == "ToolMessage"
                for i in range(len(messages) - 1)
            )
            logger.debug(f"[{self.__class__.__name__}] 迭代 {iteration+1}，消息数={len(messages)}, dangling={has_dangling}")

            llm_with_tools = self.llm.bind_tools(self.tools, parallel_tool_calls=False)

            try:
                response = await llm_with_tools.ainvoke(messages)
                messages.append(response)
            except Exception as e:
                logger.warning(f"[{self.__class__.__name__}] LLM 调用失败: {e}")
                # 移除本轮追加的 AI 消息，避免破坏消息链
                if messages and hasattr(messages[-1], "tool_calls"):
                    messages.pop()
                break

            tool_calls = response.tool_calls or []
            if not tool_calls:
                break

            for tc in tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]

                try:
                    obs = await self._execute_tool(owner, repo, branch, tool_name, tool_args)
                    # 安全提取 tool_call_id：从 response.tool_calls 中匹配同名工具
                    tc_id = None
                    if response.tool_calls:
                        for _tc in response.tool_calls:
                            if _tc.get("name") == tool_name:
                                tc_id = _tc.get("id")
                                break
                    tc_id = tc_id or tc.get("id") or f"call_{iteration}_{tool_name}"
                    obs_truncated = obs[:_TOOL_RESULT_TRUNCATE]
                    messages.append(ToolMessage(content=obs_truncated, tool_call_id=tc_id))
                    logger.debug(f"[{self.__class__.__name__}] 工具执行成功: {tool_name}, 结果长度: {len(obs_truncated)}")
                except Exception as e:
                    tc_id = None
                    if response.tool_calls:
                        for _tc in response.tool_calls:
                            if _tc.get("name") == tool_name:
                                tc_id = _tc.get("id")
                                break
                    tc_id = tc_id or tc.get("id") or f"call_{iteration}_{tool_name}"
                    messages.append(ToolMessage(content=f"[错误] {str(e)}", tool_call_id=tc_id))
                    logger.warning(f"[{self.__class__.__name__}] 工具执行失败: {tool_name}: {e}")

            # 防止消息历史无限膨胀：保留 SystemMsg + 摘要 + 最近 2 轮完整对话
            # 关键：必须保留完整三元组（Human + AI(tool_calls) + ToolMessage），
            # 避免 dangling ToolMessage 导致下一轮 LLM 调用报 400 错误。
            # 当 history=8 时：history[:-3]=[H1,A1,T1,H2,A2], history[-3:]=[T2,H3,A3]
            # T2 是 dangling（无对应结果），所以要改为 history[-6:] 保留 [H2,A2,T2,H3,A3,T3]
            if len(messages) > 8:
                system = messages[0]
                history = messages[1:]  # 跳过 SystemMsg

                if len(history) <= 3:
                    continue

                # 提取摘要信息：统计历史中的工具调用（跳过最后 6 条，保留 2 轮完整对话）
                summary_lines = ["## 前期探索摘要"]
                seen = set()
                for msg in history[:-6]:  # 跳过最后 6 条（2 轮完整对话）
                    if isinstance(msg, HumanMessage):
                        text = msg.content or ""
                        for line in text.split("\n"):
                            stripped = line.strip()
                            if stripped.startswith("## ") or stripped.startswith("### "):
                                key = stripped[:60]
                                if key not in seen:
                                    seen.add(key)
                                    summary_lines.append(f"  {stripped}")

                summary_msg = HumanMessage(content="\n".join(summary_lines))
                # 保留 SystemMsg + 摘要 + 最后 6 条（2 轮完整的 Human + AI(tool_calls) + Tool 三元组）
                messages[:] = [system, summary_msg] + history[-6:]

        # 最终生成结果
        messages.append(HumanMessage(
            content="基于以上探索结果，请以 JSON 格式返回最终发现。"
        ))

        try:
            final = await self.llm.ainvoke(messages)
            return self._parse_final_result(final.content)
        except Exception as e:
            logger.warning(f"[{self.__class__.__name__}] 最终结果解析失败: {e}")
            return {}

    async def _execute_tool(
        self, owner: str, repo: str, branch: str,
        tool_name: str, args: dict
    ) -> str:
        """执行工具。"""
        import asyncio

        # 注入通用参数
        if tool_name == "read_file_content":
            args = {"owner": owner, "repo": repo, "path": args.get("path", ""), "ref": branch}
        elif tool_name == "search_code":
            args = {"owner": owner, "repo": repo, "query": args.get("query", ""), "language": args.get("language", "")}
        elif tool_name == "get_file_tree":
            args = {"owner": owner, "repo": repo, "ref": branch}

        def sync_call():
            for t in self.tools:
                if t.name == tool_name:
                    return t.invoke(args)
            raise ValueError(f"未知工具: {tool_name}")

        result = await asyncio.get_running_loop().run_in_executor(None, sync_call)
        return str(result)[:_TOOL_RESULT_TRUNCATE]

    def _build_initial_context(self, owner, repo, branch, file_contents) -> str:
        parts = [f"探索任务: {owner}/{repo}@{branch}\n"]
        if file_contents:
            parts.append(f"已有文件内容（{len(file_contents)} 个文件）:")
            for p in list(file_contents.keys())[:15]:
                # 显示文件大小和小段内容预览，帮助 LLM 识别框架/模式
                content_preview = file_contents[p][:150].replace("\n", " ")
                parts.append(f"- {p}: {content_preview}...")
        return "\n".join(parts)

    def _parse_final_result(self, content: str) -> dict:
        import re
        text = content.strip()
        if "{" in text:
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
        return {}

    def _rule_based_fallback(self, owner, repo, branch, file_contents) -> dict:
        """规则引擎兜底。"""
        return {}


# ─── 具体 Explorer ────────────────────────────────────────────────────────────

class TechStackExplorer(BaseExplorerAgent):
    """技术栈识别 Agent。"""

    def __init__(self):
        super().__init__()
        self.system_prompt = TECH_STACK_SYSTEM

    def _build_initial_context(self, owner, repo, branch, file_contents) -> str:
        parts = [
            f"# 技术栈识别任务\n",
            f"仓库: {owner}/{repo}@{branch}\n",
        ]

        if file_contents:
            parts.append("\n## 已加载的文件（包含内容预览）:\n")
            for p in list(file_contents.keys())[:20]:
                content_preview = file_contents[p][:150].replace("\n", " ")
                parts.append(f"- {p}: {content_preview}...")
            parts.append("\n请基于以上文件内容，识别这个仓库的技术栈。")
        else:
            parts.append("请先获取文件树，再逐步探索。")

        return "\n".join(parts)

    def _rule_based_fallback(self, owner, repo, branch, file_contents) -> dict:
        """基于已有文件内容做启发式识别。"""
        if not file_contents:
            return {"error": "无可用文件内容"}

        languages: set = set()
        frameworks: set = set()
        config_files: set = set()

        for path in file_contents.keys():
            lower = path.lower()
            # 语言
            if path.endswith(".py"): languages.add("Python")
            if path.endswith((".ts", ".tsx")): languages.add("TypeScript")
            if path.endswith((".js", ".jsx")): languages.add("JavaScript")
            if path.endswith(".go"): languages.add("Go")
            if path.endswith(".rs"): languages.add("Rust")
            if path.endswith(".java"): languages.add("Java")
            # 框架
            for content_key in file_contents:
                content = file_contents[content_key][:1000]
                if "fastapi" in content_key.lower(): frameworks.add("FastAPI")
                if "flask" in content_key.lower(): frameworks.add("Flask")
                if "django" in content_key.lower(): frameworks.add("Django")
                if "react" in content: frameworks.add("React")
                if "next" in content: frameworks.add("Next.js")
                if "langchain" in content: frameworks.add("LangChain")
                if "langgraph" in content: frameworks.add("LangGraph")
                if "express" in content: frameworks.add("Express")
                if "vue" in content: frameworks.add("Vue")
                if "angular" in content: frameworks.add("Angular")
            # 配置文件
            basename = path.split("/")[-1]
            if basename in ("package.json", "requirements.txt", "go.mod", "Cargo.toml",
                              "pyproject.toml", "Pipfile", "Gemfile", "composer.json",
                              "Makefile", "Dockerfile", "docker-compose.yml"):
                config_files.add(basename)

        return {
            "languages": sorted(languages),
            "frameworks": sorted(frameworks),
            "infrastructure": [],
            "config_files_found": sorted(config_files),
            "confidence": 0.6,
            "summary": f"识别到 {len(languages)} 种语言，{len(frameworks)} 种框架",
        }


class QualityExplorer(BaseExplorerAgent):
    """质量热点发现 Agent。"""

    def __init__(self):
        super().__init__()
        self.system_prompt = QUALITY_SYSTEM

    def _rule_based_fallback(self, owner, repo, branch, file_contents) -> dict:
        """基于文件内容的启发式质量分析。"""
        if not file_contents:
            return {"error": "无可用文件内容"}

        hotspots = []
        score = 100
        concerns = []
        positives = []
        test_coverage = "unknown"

        # 统计各语言文件
        py_files, ts_files, js_files, go_files = [], [], [], []
        for path in file_contents:
            if path.endswith(".py"):
                py_files.append(path)
            elif path.endswith((".ts", ".tsx")):
                ts_files.append(path)
            elif path.endswith((".js", ".jsx")):
                js_files.append(path)
            elif path.endswith(".go"):
                go_files.append(path)

        total_files = len(py_files) + len(ts_files) + len(js_files) + len(go_files)

        if total_files == 0:
            concerns.append("仓库中未检测到源码文件，无法评估代码质量")
            score = 50
        else:
            positives.append(f"检测到 {total_files} 个源码文件")
            # 检查测试文件
            test_files = [p for p in file_contents if "test" in p.lower() or "spec" in p.lower()]
            if test_files:
                positives.append(f"存在测试文件: {len(test_files)} 个")
                test_coverage = "medium"
            else:
                concerns.append("未检测到测试文件，测试覆盖率可能不足")
                test_coverage = "low"
                score -= 15

            # 启发式：单个文件过大风险
            for path, content in file_contents.items():
                lines = content.count("\n")
                if lines > 300:
                    hotspots.append({
                        "type": "large_file",
                        "file": path,
                        "severity": "medium",
                        "description": f"文件行数较多（{lines} 行），建议拆分",
                        "suggestion": "考虑按功能模块拆分文件，每个文件控制在 300 行以内",
                    })
                    score -= 5
                elif lines > 500:
                    hotspots.append({
                        "type": "very_large_file",
                        "file": path,
                        "severity": "high",
                        "description": f"文件过大（{lines} 行），难以维护",
                        "suggestion": "必须拆分文件，建议按功能/领域划分",
                    })
                    score -= 10

            # 硬编码检测（启发式）
            for path, content in file_contents.items():
                if any(k in content for k in ("password=", "api_key=", "secret=", "token=")):
                    if "#" not in content.split("password=", 1)[0].split("\n")[-1]:
                        hotspots.append({
                            "type": "potential_secret",
                            "file": path,
                            "severity": "high",
                            "description": "文件中可能包含密钥/密码字面量",
                            "suggestion": "使用环境变量或密钥管理服务替代硬编码",
                        })
                        score -= 10
                        break

        # 计算五维评分
        test_score = 80 if test_coverage == "high" else (50 if test_coverage == "medium" else 20)
        maint_score = max(0, min(100, score))
        comp_score = 100 - max(0, min(100, score))  # 复杂度反向

        return {
            "hotspots": hotspots[:10],
            "quality_score": max(0, score),
            "test_coverage_estimate": test_coverage,
            "main_concerns": concerns[:5] or ["代码结构正常"],
            "positive_patterns": positives[:5],
            "complexity": "High" if score < 60 else ("Medium" if score < 80 else "Low"),
            "maintainability": "High" if score >= 80 else ("Medium" if score >= 60 else "Low"),
            "llmPowered": False,
            "maint_score": maint_score,
            "comp_score": comp_score,
            "dup_score": 80,  # 无法检测，保守估计
            "test_score": test_score,
            "coup_score": 70,  # 无法检测，保守估计
        }


class ArchitectureExplorer(BaseExplorerAgent):
    """架构模式识别 Agent。"""

    def __init__(self):
        super().__init__()
        self.system_prompt = ARCHITECTURE_SYSTEM

    def _rule_based_fallback(self, owner, repo, branch, file_contents) -> dict:
        """基于文件结构的启发式架构分析。"""
        if not file_contents:
            return {"error": "无可用文件内容"}

        languages = set()
        dirs: set = set()
        components = []
        layers: list = []
        patterns: list = []

        # 分析目录结构
        for path in file_contents:
            parts = path.split("/")
            if len(parts) > 1:
                dirs.add(parts[0])
            if len(parts) > 2:
                dirs.add(f"{parts[0]}/{parts[1]}")

            # 语言统计
            if path.endswith(".py"):
                languages.add("Python")
            elif path.endswith((".ts", ".tsx")):
                languages.add("TypeScript")
            elif path.endswith(".go"):
                languages.add("Go")
            elif path.endswith(".rs"):
                languages.add("Rust")
            elif path.endswith(".java"):
                languages.add("Java")

        # 检测组件
        for d in sorted(dirs):
            if any(d.startswith(x) for x in ("src/", "lib/", "app/")):
                components.append({
                    "name": d.split("/")[-1] if "/" in d else d,
                    "responsibility": f"模块: {d}",
                    "depends_on": [],
                })

        # 检测分层架构
        layer_names = {
            "api": ["routes", "endpoints", "controllers", "handlers"],
            "service": ["services", "business", "usecases"],
            "data": ["models", "schemas", "entities", "db", "repository"],
            "util": ["utils", "helpers", "common"],
        }
        for layer, keywords in layer_names.items():
            for d in dirs:
                if any(kw in d for kw in keywords):
                    layers.append({
                        "name": layer,
                        "files": [d],
                        "description": f"{layer}层: {d}",
                    })

        # 检测设计模式
        for path, content in file_contents.items():
            if "class.*Repository" in content:
                patterns.append({
                    "pattern": "Repository",
                    "location": path,
                    "description": "使用 Repository 模式分离数据访问",
                })
            if "class.*Service" in content:
                patterns.append({
                    "pattern": "Service Layer",
                    "location": path,
                    "description": "使用 Service 层分离业务逻辑",
                })

        # 推断架构风格
        style = "Single Module"
        if len(dirs) > 5:
            style = "Modular"
        if any("microservice" in d.lower() for d in dirs):
            style = "Microservices"

        concerns = ["建议添加测试" if not any("test" in d.lower() for d in dirs) else ""]
        concerns = [c for c in concerns if c]

        return {
            "architecture_style": style,
            "components": components[:8],
            "design_patterns": patterns[:5],
            "layers": layers[:4],
            "complexity": "Low" if len(dirs) < 5 else ("Medium" if len(dirs) < 10 else "High"),
            "maintainability": "B" if len(dirs) < 8 else "C",
            "summary": f"检测到 {len(languages)} 种语言，{len(dirs)} 个目录模块，架构风格: {style}",
            "strengths": ["目录结构清晰" if dirs else "文件数量较少"],
            "concerns": concerns,
        }


# ─── 编排器 ────────────────────────────────────────────────────────────────

class ExplorerOrchestrator:
    """并行探索编排器。

    同时启动多个 Explorer Agent，每个 Agent 独立探索一个维度。
    通过 asyncio.gather 实现真正的并行。

    使用示例：
        orchestrator = ExplorerOrchestrator()
        results = await orchestrator.explore_all("owner", "repo", "main")
        # results = {
        #     "tech_stack": {...},
        #     "quality_hotspots": {...},
        #     "architecture": {...},
        # }
    """

    def __init__(self):
        self.explorers = [
            TechStackExplorer(),
            QualityExplorer(),
            ArchitectureExplorer(),
        ]

    async def explore_all(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
        file_contents: dict[str, str] | None = None,
    ) -> dict[str, dict]:
        """并行运行所有 Explorer。

        Args:
            owner:        仓库所有者
            repo:         仓库名
            branch:       分支名
            file_contents: 可选，预加载的文件内容

        Returns:
            每个 Explorer 的发现结果
        """
        logger.info(f"[ExplorerOrchestrator] 开始并行探索: {owner}/{repo}")

        # 真正并行执行所有 Explorer（asyncio.gather）
        tasks = [
            explorer.explore(owner, repo, branch, file_contents)
            for explorer in self.explorers
        ]
        results: list[tuple[str, Any]] = []

        done = asyncio.gather(*tasks, return_exceptions=True)
        try:
            outcomes = await done
        except Exception as e:
            logger.error(f"[ExplorerOrchestrator] gather 异常: {e}")
            outcomes = []

        for explorer, outcome in zip(self.explorers, outcomes):
            name = explorer.__class__.__name__
            if isinstance(outcome, Exception):
                logger.error(f"[{name}] 异常: {outcome}")
                results.append((name, {"error": str(outcome)}))
            else:
                result: ExplorerResult = outcome
                logger.info(
                    f"[{name}] 完成: "
                    f"{result.duration_ms:.0f}ms, "
                    f"findings={list(result.findings.keys()) if result.findings else []}"
                )
                results.append((name, {
                    **result.findings,
                    "_meta": {
                        "duration_ms": round(result.duration_ms, 1),
                        "error": result.error,
                        "tool_calls": len(result.tool_calls),
                    },
                }))

        output = dict(results)
        logger.info(f"[ExplorerOrchestrator] 全部探索完成: {list(output.keys())}")
        return output
