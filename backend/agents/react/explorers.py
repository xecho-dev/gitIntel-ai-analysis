"""
并行探索 Agent — 多个 Tool Use Agent 并行工作，探索仓库不同维度。

每个子 Agent 负责一个维度，独立运行 ReAct 循环，自主决定调用哪些工具：
  - TechStackExplorer:     技术栈识别（语言/框架/基础设施/包管理器）
  - QualityExplorer:       代码质量热点发现（安全问题/代码异味/测试覆盖）
  - ArchitectureExplorer:   架构模式识别（架构风格/分层/设计模式）

每个 Explorer 都是**真正的 Agent**，有严格的验证约束：
  - 无硬编码 fallback，所有分析由 LLM 驱动
  - 必须经过 ReAct 循环（Thought → Action → Observation）
  - 强制最小工具调用次数（默认 3 次），防止 LLM 跳过验证
  - 证据锚定验证：结论中的 evidence 必须与工具调用记录匹配
  - 预加载文件只给结构线索，不给可直接得出结论的内容

关键设计：
  - _EXPLORER_MIN_TOOL_CALLS: 强制最小工具调用次数
  - _anchor_evidence(): 验证 LLM 声称的 evidence 是否在工具调用记录中
  - 预加载文件只显示文件名，不显示内容摘要

用法：
    explorers = await ExplorerOrchestrator().explore_all(owner, repo, branch)
    # 返回 {
    #     "TechStackExplorer": {...},
    #     "QualityExplorer": {...},
    #     "ArchitectureExplorer": {...},
    # }
"""
import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

logger = logging.getLogger("gitintel")

# ─── Token 预算配置 ───────────────────────────────────────────────────────────

_MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "2048"))
_EXPLORER_MAX_ITERATIONS = int(os.getenv("EXPLORER_MAX_ITERATIONS", "4"))
_EXPLORER_MIN_TOOL_CALLS = int(os.getenv("EXPLORER_MIN_TOOL_CALLS", "3"))
_TOOL_RESULT_TRUNCATE = int(os.getenv("TOOL_RESULT_TRUNCATE", "1500"))


# ─── 工具工厂（延迟导入避免循环依赖）─────────────────────────────────────────

def _get_explorer_tools():
    from tools.github_tools import get_repo_info, get_file_tree, read_file_content, search_code
    from tools.code_tools import parse_file_ast, detect_code_smells, summarize_code_file
    return [
        get_repo_info,
        get_file_tree,
        read_file_content,
        search_code,
        parse_file_ast,
        detect_code_smells,
        summarize_code_file,
    ]


# ─── System Prompts（LLM 驱动的 ReAct 引导）─────────────────────────────────────

# 每个 Prompt 包含：
#   1. 角色 + 任务
#   2. 硬性规则（必须做什么，禁止做什么）
#   3. ReAct 工作流引导（先做什么，再做什么）
#   4. 输出格式要求

_TECH_STACK_EXPLORER_INSTRUCTIONS = """## 你的角色
你是一名技术架构师，通过自主探索来识别 GitHub 仓库的技术栈。

## 核心原则
- **依赖 ≠ 使用**：requirements.txt / package.json 中列出 ≠ 实际使用了该框架
- **必须有代码证据**：配置文件只能定位方向，必须通过代码特征（import/decorator/API）才能确认
- **无验证不结论**：每个框架的 confidence > 0.5 必须有工具调用记录支撑

## 任务
识别仓库的：①编程语言 ②框架/库（必须实际使用，不是仅依赖声明）③基础设施 ④包管理器 ⑤部署方式。

## 工具
- get_file_tree(ref=branch): 获取完整文件树，快速了解仓库结构
- read_file_content(path, ref=branch): 读取文件内容（验证代码特征）
- search_code(query, language): 搜索代码特征（如 "from fastapi import"）
- parse_file_ast(content, language, file_path): AST 解析，识别类和函数定义
- summarize_code_file(content, language, file_path): 代码摘要
- get_repo_info(owner, repo): 获取仓库元信息

## 验证流程（必须遵循，按顺序执行）

### 第一步：目录扫描
先用 get_file_tree 了解整体结构，记录关键目录如 backend/、frontend/、src/、api/ 等。

### 第二步：定位配置文件（只给方向，不给结论）
读取以下文件确定**可能的**技术方向：
- pyproject.toml / requirements.txt / package.json / go.mod / Cargo.toml
- Dockerfile.* / docker-compose.yml / .github/workflows/*.yml

⚠️ 注意：这些文件只能告诉你"可能用了什么"，不能直接写进结论。

### 第三步：代码特征验证（必须！这是关键步骤）
对每个框架猜测，必须用 search_code 或 read_file_content 验证**实际代码证据**：
- FastAPI → 搜索 `from fastapi import` 或 `@app.` 或 `@router`
- React → 搜索 `import React` 或 `useState` 或 `useEffect`
- Next.js → 搜索 `next/` 或 `getServerSideProps` 或 `app router`
- LangGraph → 搜索 `from langgraph import` 或 `StateGraph`
- Vue → 搜索 `<template>` 或 `createApp` 或 `ref(`（注意与 Vue 的 ref 区分）

### 第四步：确认语言
- Python 文件多 → Python 后端
- JavaScript/TypeScript 文件多 → 前端 JS/TS
- 检查 Dockerfile 或 .github/workflows 中的基础镜像确认

### 第五步：部署方式
- 有 Dockerfile → Docker 容器化
- 有 docker-compose.yml → 多容器编排
- 检查 .github/workflows 中的部署动作

## 硬性规则（违反则结论无效）

1. **confidence 映射规则**：
   - 配置文件 + 代码特征验证 → confidence ∈ [0.8, 1.0]
   - 只有配置文件，无代码验证 → confidence ∈ [0.3, 0.5]，必须标注 "待验证"
   - 无配置文件，无代码验证 → 不输出该框架

2. **必须调用工具才能输出结论**：每个 iteration 至少调用 1 次工具，总计至少 3 次

3. **依赖声明不算证据**：requirements.txt 有 fastapi ≠ 用了 fastAPI，必须找到代码中的 import/使用

4. **精确的 evidence**：`evidence` 字段必须列出具体的工具调用结果，如：
   - `["search_code: 'from fastapi import' found in backend/main.py"]`
   - `["read_file_content: @app.get('/') in backend/main.py:12"]`

5. **降低 confidence 的场景**：
   - 配置文件中有但代码中从未出现 → confidence ≤ 0.4
   - 只有 Dockerfile 提到但无代码 → confidence = 0.3（可能是遗留配置）

## 输出格式
先输出推理过程，再输出 JSON：

## 推理过程
### 第一轮：目录扫描
...

### 第二轮：配置文件定位
...

### 第三轮：代码特征验证（关键）
...

### 最终结论
...

```json
{
  "languages": [{"name": "...", "confidence": 0.0-1.0, "evidence": ["..."]}],
  "frameworks": [
    {
      "name": "...",
      "confidence": 0.0-1.0,
      "status": "confirmed|unconfirmed|rejected",
      "evidence": ["具体工具调用结果：tool_name: 搜索内容 in 文件:行号"],
      "reason": "为什么确认/不确认"
    }
  ],
  "infrastructure": [{"name": "...", "evidence": ["..."]}],
  "dev_tools": ["..."],
  "package_manager": "...",
  "deployment": ["..."],
  "config_files_found": ["..."],
  "overall_confidence": 0.0-1.0,
  "summary": "一句话描述",
  "unverified_claims": ["依赖中有但未验证的框架..."]
}
```

注意：`unverified_claims` 必须列出所有配置文件提到但代码中未验证的依赖。"""


_QUALITY_EXPLORER_INSTRUCTIONS = """## 你的角色
你是一名代码审计专家，通过自主探索来发现仓库中的代码质量问题和潜在风险。

## 核心原则
- **每个 hotspot 必须有精确位置**：file + line，泛泛而谈无效
- **每个建议必须可执行**：不是"建议优化"，而是"在 xxx.py:23 将 yyy 改为 zzz"
- **工具返回什么就说什么**：不要脑补不存在的问题
- **没有发现问题也是有效结论**：输出 positive_patterns

## 任务
发现：①代码异味(过长函数/深度嵌套) ②安全问题(硬编码/Secret/eval) ③性能隐患(N+1/内存泄漏) ④测试覆盖不足 ⑤可维护性问题(紧耦合/循环依赖)。

## 工具
- get_file_tree(ref=branch): 获取完整文件树
- read_file_content(path, ref=branch): 读取文件内容（确认问题）
- search_code(query, language): 搜索问题模式（如 password=, eval(, subprocess.）
- detect_code_smells(content, language, file_path): 自动化代码异味检测
- parse_file_ast(content, language, file_path): AST 解析，识别圈复杂度
- summarize_code_file(content, language, file_path): 代码摘要

## 验证流程（必须遵循）

### 第一步：规模扫描
用 get_file_tree 了解仓库规模（文件总数、目录深度），判断问题发现的上限。

### 第二步：批量搜索（不要逐文件读取）
用 search_code 搜索已知问题模式：
- 安全：`password=`, `api_key=`, `secret=`, `token=`, `eval(`, `exec(`, `subprocess`
- 代码异味：`TODO`, `FIXME`, `HACK`, `XXX`
- 性能：`.query(` (SQL) , `for...for` (嵌套循环)

⚠️ 每个 search_code 必须指定 language 参数！

### 第三步：精确验证
对 search_code 发现的可疑文件，用 detect_code_smells 或 read_file_content 确认。
⚠️ 确认后必须记录精确的 file:line，不能说"某文件某处"

### 第四步：测试覆盖评估
检查测试文件比例：
- 有多少 .test.ts / _test.py / spec.ts 文件
- 核心业务文件是否都有对应测试

## 硬性规则（违反则结论无效）

1. **位置必填**：每个 hotspot 必须有 `file` + `line`，缺少则该条无效
2. **建议可执行**：`suggestion` 字段必须是可直接执行的修改，不是"建议优化代码"
3. **无证据不声称**：工具没有返回文件路径，不要声称发现了问题
4. **positive_patterns 必填**：即使没发现问题，也要列出做得好的地方
5. **每个 iteration 必须调用至少 1 次工具，总计至少 3 次**

## 输出格式
先输出推理过程，再输出 JSON：

## 推理过程
### 第一轮：规模扫描
...

### 第二轮：批量问题搜索
对每个 search_code 调用，记录：
- 搜索词
- 匹配文件数
- 可疑文件列表

### 第三轮：精确验证
对每个可疑文件，确认并记录：
- 文件路径
- 具体行号
- 问题类型

### 最终结论
...

```json
{
  "hotspots": [
    {
      "type": "security|smell|performance|test|maintainability",
      "file": "src/path/filename.py",
      "line": 42,
      "severity": "high|medium|low",
      "description": "精确描述问题（不是泛泛而谈）",
      "suggestion": "精确可执行的操作（不是\"建议优化\"）",
      "evidence": "工具返回的具体证据"
    }
  ],
  "quality_score": 0-100,
  "test_coverage_estimate": "low|medium|high",
  "main_concerns": ["最关心的 3 个问题"],
  "positive_patterns": ["做得好的 3 件事"],
  "complexity": "Low|Medium|High",
  "maintainability": "Low|Medium|High",
  "llmPowered": true,
  "maint_score": 0-100,
  "comp_score": 0-100,
  "dup_score": 0-100,
  "test_score": 0-100,
  "coup_score": 0-100,
  "search_results": [
    {"query": "搜索词", "files_found": ["file1", "file2"]}
  ]
}
```

注意：`search_results` 记录所有 search_code 的结果，供后续验证。"""


_ARCHITECTURE_EXPLORER_INSTRUCTIONS = """## 你的角色
你是一名软件架构专家，通过自主探索来识别仓库的架构模式和设计决策。

## 核心原则
- **components 必须有依赖链**：每个组件必须明确 depends_on，不能孤立存在
- **架构风格必须有目录/文件证据**：不能说"看起来像微服务"，必须说"根据目录结构中有 api/services/models，推断为分层架构"
- **组件关系必须可追溯**：组件 A 调用组件 B，必须找到具体的 import/use 语句
- **信息不足就标注 unknown**：不要猜测，unknown 比错误结论好

## 任务
识别：①架构风格(单体/微服务/CleanArchitecture/DDD) ②设计模式(Repository/Middleware等) ③分层架构 ④模块组织 ⑤组件关系 ⑥架构问题。

## 工具
- get_file_tree(ref=branch): 获取完整文件树，理解目录结构
- read_file_content(path, ref=branch): 读取核心文件（入口文件/核心模块）
- parse_file_ast(content, language, file_path): AST 解析，理解类/接口关系
- search_code(query, language): 搜索架构模式代码（如 "class.*Repository", "@inject"）
- summarize_code_file(content, language, file_path): 代码摘要

## 验证流程（必须遵循）

### 第一步：目录结构分析
用 get_file_tree 获取完整结构，识别：
- 顶层模块：backend/, frontend/, src/, api/, services/
- 分层特征：routes/, controllers/, models/, schemas/, repositories/
- 配置文件：package.json, pyproject.toml, requirements.txt

### 第二步：入口文件理解
读取关键入口文件，理解整体架构：
- 后端：main.py, app.py, index.js, server.py
- 前端：pages/, app/ (Next.js), components/
- 根目录：package.json, pyproject.toml（看 scripts 和依赖）

### 第三步：组件关系追踪
用 search_code 搜索组件间调用关系：
- Python: `from X import`, `import Y`
- JS/TS: `from 'X'`, `require('Y')`, `import * as X`

⚠️ 这一步是关键！架构图必须基于实际的 import 关系，而不是目录名猜测。

### 第四步：设计模式识别
用 parse_file_ast 或 search_code 搜索：
- Repository 模式：`class.*Repository`, `def get.*\(`
- Factory 模式：`def create.*\(` 或 `classmethod`
- Middleware/Decorator：`@.*`, `middleware`
- 依赖注入：`inject`, `@injectable`

### 第五步：架构问题识别
- 循环依赖：search_code 搜索相互 import
- 跨层调用：routes 直接调用 models（应该通过 repository）
- 配置混乱：多个 config 文件，无统一管理

## 硬性规则（违反则结论无效）

1. **每个 component 必须注明 depends_on**：不能有无依赖的孤立组件
2. **依赖链必须有工具验证**：说 A 依赖 B，必须有 search_code 的 import 证据
3. **架构风格推断必须有依据**：必须列出"根据目录结构中有 X/Y/Z，推断为..."
4. **信息不足标注 unknown**：不要猜测架构风格
5. **必须有 strengths 和 concerns**：每个架构都有优点和缺点
6. **每个 iteration 必须调用至少 1 次工具，总计至少 3 次**

## 输出格式
先输出推理过程，再输出 JSON：

## 推理过程
### 第一轮：目录结构分析
记录目录树中的关键模块和分层

### 第二轮：入口文件理解
记录每个入口文件的主要模块和职责

### 第三轮：组件关系追踪（关键）
记录所有 import/use 关系：
- `from backend.agents import X` (X depends on agents)
- `from backend.graph import Y` (Y depends on graph)

### 第四轮：设计模式识别
...

### 最终架构结论
...

```json
{
  "architecture_style": "单体|分层|微服务|CleanArchitecture|DDD|...",
  "style_evidence": "根据 [具体目录/文件] 推断为 [架构风格]",
  "components": [
    {
      "name": "component_name",
      "responsibility": "该组件的主要职责",
      "depends_on": ["component_a", "component_b"],
      "file_path": "src/path/component.py",
      "dependency_evidence": "search_code: 'from component_a import' found in file"
    }
  ],
  "design_patterns": [
    {
      "pattern": "Repository|Factory|Middleware|...",
      "location": "file_path:class_name 或 file_path:line",
      "description": "描述该模式的具体实现",
      "evidence": "工具返回的具体证据"
    }
  ],
  "layers": [
    {
      "name": "layer_name",
      "files": ["file1", "file2"],
      "description": "该层的职责",
      "calls_to": ["other_layer"]
    }
  ],
  "dependency_graph": {
    "nodes": ["component1", "component2"],
    "edges": [["component1", "component2"]]
  },
  "complexity": "Low|Medium|High",
  "maintainability": "A|B|C|D|E",
  "summary": "深度架构描述（至少 3 句话）",
  "strengths": ["优点1", "优点2"],
  "concerns": ["问题1", "问题2"],
  "unknown_items": ["无法确定的架构决策..."]
}
```

注意：`dependency_graph` 必须与 components 的 depends_on 一致，`edges` 中的每条边必须有 search_code 证据。"""


# ─── 推理过程解析器 ───────────────────────────────────────────────────────────

def _extract_reasoning(content: str) -> str:
    """从 LLM 输出中提取推理过程部分。"""
    # 匹配 ## 推理过程 或 ## Reasoning 等标记
    patterns = [
        r"##\s*推理过程\s*([\s\S]+?)(?=```json|$)",
        r"##\s*Reasoning\s*([\s\S]+?)(?=```json|$)",
        r"##\s*分析\s*([\s\S]+?)(?=```json|$)",
        r"##\s*过程\s*([\s\S]+?)(?=```json|$)",
    ]
    for pat in patterns:
        m = re.search(pat, content, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _extract_json(text: str) -> dict:
    """从文本中提取 JSON（处理各种格式）。"""
    text = text.strip()

    # 策略1：直接解析
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # 策略2：从 ```json ``` 中提取
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 策略3：从 {...} 中提取（允许嵌套）
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return {}


# ─── 结果结构 ────────────────────────────────────────────────────────────────

@dataclass
class ExplorerResult:
    explorer_type: str = ""
    findings: dict = field(default_factory=dict)
    reasoning: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    error: str = ""
    duration_ms: float = 0.0

    @property
    def tool_call_count(self) -> int:
        """工具调用总次数。"""
        return len(self.tool_calls)

    @property
    def verification_status(self) -> str:
        """验证状态：fully_verified / partially_verified / insufficient / no_tools"""
        if not self.tool_calls:
            return "no_tools"
        if len(self.tool_calls) < _EXPLORER_MIN_TOOL_CALLS:
            return "insufficient"
        # 检查 findings 中是否有 warning
        findings_str = str(self.findings).lower()
        if "unverified" in findings_str or "warning" in findings_str:
            return "partially_verified"
        return "fully_verified"


# ─── 基础 Explorer（真正的 Agent 基类）────────────────────────────────────────

class BaseExplorerAgent:
    """所有探索 Agent 的基类——LLM 驱动的 ReAct 循环，无 fallback escape hatch。

    核心原则：
      - LLM 是唯一的分析引擎，不存在硬编码的规则兜底
      - 预加载文件只给结构线索，不给可直接得出结论的内容
      - 强制最小工具调用次数，确保 LLM 必须实际探索
      - 证据锚定验证：结论必须与工具调用记录匹配
    """

    MAX_ITERATIONS = _EXPLORER_MAX_ITERATIONS
    MAX_TOOL_CALLS = _EXPLORER_MAX_ITERATIONS * 2
    MIN_TOOL_CALLS = _EXPLORER_MIN_TOOL_CALLS  # 强制最小工具调用次数

    def __init__(self):
        self._llm = None   # 懒加载
        self._tools = None
        self.system_prompt = ""

    # ── LLM / 工具懒加载 ──────────────────────────────────────────────────────

    @property
    def llm(self):
        if self._llm is None:
            try:
                from utils.llm_factory import get_llm_with_tracking
                self._llm = get_llm_with_tracking(
                    agent_name=self.__class__.__name__,
                    max_tokens=_MAX_OUTPUT_TOKENS,
                )
            except ImportError:
                self._llm = None
        return self._llm

    @property
    def tools(self):
        if self._tools is None:
            self._tools = _get_explorer_tools()
        return self._tools

    # ── 主入口 ────────────────────────────────────────────────────────────────

    async def explore(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
        file_contents: dict[str, str] | None = None,
    ) -> ExplorerResult:
        """执行完整的 ReAct 探索。"""
        import time
        t0 = time.time()

        result = ExplorerResult(explorer_type=self.__class__.__name__)

        if self.llm is None:
            raise RuntimeError(
                f"[{self.__class__.__name__}] LLM 不可用，Agent 无法运行。"
                "请确保 OPENAI_API_KEY 或 ANTHROPIC_API_KEY 已配置。"
            )

        # 分支修正
        actual_branch = await self._resolve_branch(owner, repo, branch)
        if actual_branch and actual_branch != branch:
            logger.info(f"[{self.__class__.__name__}] 分支修正: {branch} -> {actual_branch}")
            branch = actual_branch

        try:
            findings, reasoning, tool_calls = await self._react_loop(
                owner, repo, branch, file_contents
            )
            result.findings = findings
            result.reasoning = reasoning
            result.tool_calls = tool_calls
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] ReAct 循环异常: {e}", exc_info=True)
            result.error = str(e)
            raise

        result.duration_ms = (time.time() - t0) * 1000
        return result

    # ── 核心 ReAct 循环 ───────────────────────────────────────────────────────

    async def _react_loop(
        self,
        owner: str,
        repo: str,
        branch: str,
        file_contents: dict[str, str] | None,
    ) -> tuple[dict, str, list[dict]]:
        """完整的 ReAct 推理循环，无逃逸舱。强制最小工具调用次数。"""
        # 初始消息：System Prompt + 任务上下文
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=self._build_task_context(owner, repo, branch, file_contents)),
        ]

        tool_calls_log: list[dict] = []
        iteration = 0
        min_tool_calls = _EXPLORER_MIN_TOOL_CALLS

        while iteration < self.MAX_ITERATIONS:
            iteration += 1
            logger.info(
                f"[{self.__class__.__name__}] 迭代 {iteration}/{self.MAX_ITERATIONS}，"
                f"消息数={len(messages)}, 已调用工具={len(tool_calls_log)}"
            )

            # LLM 推理：决定下一步工具调用
            # strict=False 适配 DashScope 代码模型（不支持严格的 function.arguments JSON 校验）
            llm_with_tools = self.llm.bind_tools(self.tools, parallel_tool_calls=False, strict=False)
            try:
                response = await llm_with_tools.ainvoke(messages)
                messages.append(response)
            except Exception as e:
                logger.error(f"[{self.__class__.__name__}] LLM 推理失败: {e}")
                break

            tool_calls = response.tool_calls or []

            # 如果没有工具调用，检查是否满足最小工具调用次数
            if not tool_calls:
                if len(tool_calls_log) < min_tool_calls:
                    # 强制注入继续探索的消息
                    remaining = min_tool_calls - len(tool_calls_log)
                    force_msg = (
                        f"你目前只完成了 {len(tool_calls_log)} 次工具调用，"
                        f"但必须至少完成 {min_tool_calls} 次才能给出结论。"
                        f"请继续调用工具进行探索（还差 {remaining} 次）：\n"
                        "- 搜索代码特征\n"
                        "- 读取关键文件验证\n"
                        "- 追踪依赖关系"
                    )
                    messages.append(HumanMessage(content=force_msg))
                    continue
                else:
                    logger.info(
                        f"[{self.__class__.__name__}] 工具调用已满足({len(tool_calls_log)}次)，LLM 选择结束"
                    )
                    break

            # 执行所有工具调用
            for tc in tool_calls:
                tc_result = await self._run_tool(owner, repo, branch, tc, iteration)
                tool_calls_log.append(tc_result["log"])
                messages.append(tc_result["message"])

                if tc_result["error"]:
                    logger.warning(
                        f"[{self.__class__.__name__}] 工具 {tc['name']} 执行失败: "
                        f"{tc_result['error']}"
                    )

            # 检查是否达到最小工具调用次数，如果是最后一次迭代，强制继续
            if len(tool_calls_log) < min_tool_calls and iteration >= self.MAX_ITERATIONS:
                # 达到最大迭代但未满足最小工具调用，追加一条强制消息
                messages.append(HumanMessage(
                    content=(
                        f"⚠️ 警告：已达到最大迭代次数({self.MAX_ITERATIONS})，"
                        f"但只完成了 {len(tool_calls_log)}/{min_tool_calls} 次工具调用。"
                        "请在最终结论中将所有未充分验证的项目标注为 'unverified' 或降低 confidence。"
                    )
                ))

            # 消息压缩：防止 token 膨胀，但始终保留完整的三元组
            self._prune_messages(messages)

        # 最终生成结论（传入工具调用统计，供 LLM 参考）
        messages.append(HumanMessage(
            content=(
                f"基于以上 {len(tool_calls_log)} 次工具调用的探索结果，给出最终结论。\n"
                "请在 JSON 的 evidence 字段中引用具体的工具调用结果。\n"
                "对于没有充分验证的项，必须降低 confidence 或标注为 unverified。"
            )
        ))

        try:
            final = await self.llm.ainvoke(messages)
            reasoning = _extract_reasoning(final.content)
            findings = _extract_json(final.content)

            # 证据锚定验证：将工具调用记录注入 findings
            findings = self._anchor_evidence(findings, tool_calls_log)

            logger.info(
                f"[{self.__class__.__name__}] 推理完成，"
                f"工具调用={len(tool_calls_log)}, 发现={list(findings.keys())}"
            )
            return findings, reasoning, tool_calls_log
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 最终结论生成失败: {e}")
            return {}, "", tool_calls_log

    def _anchor_evidence(self, findings: dict, tool_calls_log: list[dict]) -> dict:
        """将工具调用记录与 findings 中的证据进行锚定验证。

        如果 LLM 声称的 evidence 在 tool_calls_log 中找不到对应记录，
        则降低 confidence 或标注为 unverified。
        """
        if not tool_calls_log:
            # 没有任何工具调用，所有 confidence 必须降低
            findings = self._force_reduce_confidence(
                findings,
                reason="没有任何工具调用验证，所有结论基于预加载文件推断"
            )
            return findings

        # 构建工具调用结果的快速查找表
        tool_results: dict[str, list[str]] = {}
        for tc in tool_calls_log:
            tool_name = tc.get("tool", "")
            result_preview = tc.get("result", "")[:200]  # 取前 200 字符
            if tool_name not in tool_results:
                tool_results[tool_name] = []
            tool_results[tool_name].append(result_preview)

        # 检查 frameworks 中的 evidence
        if "frameworks" in findings and isinstance(findings["frameworks"], list):
            for fw in findings["frameworks"]:
                if not isinstance(fw, dict):
                    continue
                evidence = fw.get("evidence", [])
                if not evidence:
                    continue
                verified = []
                unverified = []
                for e in evidence:
                    if isinstance(e, str) and self._verify_evidence(e, tool_results):
                        verified.append(e)
                    else:
                        unverified.append(e)

                # 如果有未验证的证据，降低 confidence
                if unverified and not verified:
                    fw["confidence"] = round(fw.get("confidence", 1.0) * 0.3, 2)
                    fw["status"] = "unverified"
                    fw["unverified_evidence"] = unverified
                    fw["warning"] = (
                        "这些 evidence 未在工具调用记录中找到，请手动验证或降低 confidence"
                    )
                elif unverified:
                    fw["status"] = "partially_verified"
                    fw["unverified_evidence"] = unverified

        # 检查 components 中的 dependency_evidence
        if "components" in findings and isinstance(findings["components"], list):
            for comp in findings["components"]:
                if not isinstance(comp, dict):
                    continue
                dep_evidence = comp.get("dependency_evidence", "")
                if dep_evidence and not self._verify_evidence(dep_evidence, tool_results):
                    comp["dependency_verified"] = False
                    comp["warning"] = "dependency_evidence 未在工具调用记录中找到"

        # 检查 hotspots 中的 evidence
        if "hotspots" in findings and isinstance(findings["hotspots"], list):
            for hs in findings["hotspots"]:
                if not isinstance(hs, dict):
                    continue
                evidence = hs.get("evidence", "")
                if evidence and not self._verify_evidence(evidence, tool_results):
                    hs["evidence_verified"] = False
                    hs["severity"] = hs.get("severity", "medium")
                    hs["warning"] = "evidence 未在工具调用记录中找到，请确认"

        # 如果 overall_confidence 存在且工具调用很少，降低它
        if findings.get("overall_confidence") and len(tool_calls_log) < _EXPLORER_MIN_TOOL_CALLS:
            findings["overall_confidence"] = round(
                findings.get("overall_confidence", 1.0) * 0.5, 2
            )
            findings["verification_warning"] = (
                f"只完成了 {len(tool_calls_log)}/{_EXPLORER_MIN_TOOL_CALLS} 次工具调用，"
                "confidence 已降低"
            )

        return findings

    def _verify_evidence(self, evidence: str, tool_results: dict[str, list[str]]) -> bool:
        """验证某条 evidence 是否在工具调用记录中有对应结果。"""
        if not evidence or not tool_results:
            return False

        evidence_lower = evidence.lower()

        # 从 evidence 中提取搜索词和文件
        for tool_name, results in tool_results.items():
            for result in results:
                result_lower = result.lower()
                # 检查 evidence 中的关键信息是否在结果中
                # 例如：evidence = "search_code: 'from fastapi import' found in backend/main.py"
                # 需要检查 'from fastapi import' 和 'backend/main.py' 是否都在 result 中
                if self._evidence_matches_result(evidence, result):
                    return True
        return False

    def _evidence_matches_result(self, evidence: str, result: str) -> bool:
        """检查 evidence 是否与 result 匹配。"""
        evidence_lower = evidence.lower()
        result_lower = result.lower()

        # 提取 evidence 中的关键标记
        markers = []
        if "'" in evidence or '"' in evidence:
            # 可能是搜索词
            quoted = re.findall(r"['\"]([^'\"]+)['\"]", evidence)
            markers.extend([m.lower() for m in quoted])
        if " in " in evidence_lower:
            # 可能有文件路径
            match = re.search(r"in\s+([^\s,:\]]+)", evidence, re.IGNORECASE)
            if match:
                markers.append(match.group(1).lower())

        # 至少有一个标记匹配
        for marker in markers:
            if marker and len(marker) > 2:
                if marker in result_lower:
                    return True
        return False

    def _force_reduce_confidence(
        self, findings: dict, reason: str
    ) -> dict:
        """当没有工具调用时，强制降低所有 confidence。"""
        findings["verification_warning"] = reason

        if "frameworks" in findings and isinstance(findings["frameworks"], list):
            for fw in findings["frameworks"]:
                if isinstance(fw, dict):
                    fw["confidence"] = round(fw.get("confidence", 1.0) * 0.3, 2)
                    fw["status"] = "unverified"
                    fw["warning"] = reason

        if "confidence" in findings:
            findings["confidence"] = round(findings.get("confidence", 1.0) * 0.3, 2)

        if "overall_confidence" in findings:
            findings["overall_confidence"] = round(
                findings.get("overall_confidence", 1.0) * 0.3, 2
            )

        return findings

    # ── 工具执行 ──────────────────────────────────────────────────────────────

    async def _run_tool(
        self,
        owner: str, repo: str, branch: str,
        tc: dict, iteration: int,
    ) -> dict:
        """执行单个工具调用，返回 {"log": ..., "message": ToolMessage, "error": ...}。"""
        tool_name = tc["name"]
        raw_args = tc["args"]

        # 注入通用参数（owner/repo/ref）
        args = self._prepare_tool_args(owner, repo, branch, tool_name, raw_args)

        # 获取 tool_call_id
        tc_id = tc.get("id") or f"call_{iteration}_{tool_name}"

        def sync_invoke():
            for t in self.tools:
                if t.name == tool_name:
                    return t.invoke(args)
            raise ValueError(f"未知工具: {tool_name}")

        try:
            result = await asyncio.get_running_loop().run_in_executor(None, sync_invoke)
            obs = str(result)[:_TOOL_RESULT_TRUNCATE]
            logger.debug(f"[{self.__class__.__name__}] 工具 {tool_name} 成功，结果长度={len(obs)}")
            return {
                "log": {"tool": tool_name, "args": args, "result": obs[:500]},
                "message": ToolMessage(content=obs, tool_call_id=tc_id),
                "error": "",
            }
        except Exception as e:
            logger.warning(f"[{self.__class__.__name__}] 工具 {tool_name} 异常: {e}")
            return {
                "log": {"tool": tool_name, "args": args, "error": str(e)},
                "message": ToolMessage(content=f"[工具执行错误] {str(e)}", tool_call_id=tc_id),
                "error": str(e),
            }

    def _prepare_tool_args(
        self, owner: str, repo: str, branch: str,
        tool_name: str, args: dict,
    ) -> dict:
        """根据工具类型注入通用参数。"""
        if tool_name == "read_file_content":
            return {
                "owner": owner, "repo": repo,
                "path": args.get("path", ""), "ref": branch,
            }
        if tool_name == "get_file_tree":
            return {"owner": owner, "repo": repo, "ref": branch}
        if tool_name == "search_code":
            return {
                "owner": owner, "repo": repo,
                "query": args.get("query", ""),
                "language": args.get("language", ""),
            }
        if tool_name == "get_repo_info":
            return {"owner": owner, "repo": repo}
        return args

    # ── 消息压缩 ──────────────────────────────────────────────────────────────

    def _prune_messages(self, messages: list):
        """保留 System + 摘要 + 最近 2 轮完整三元组，防止 token 膨胀。"""
        if len(messages) <= 8:
            return

        system = messages[0]
        history = messages[1:]  # 跳过 SystemMsg

        if len(history) <= 6:
            return

        # 收集摘要：提取历史中的标题行
        summary_lines = ["## 前期探索摘要"]
        seen: set = set()
        for msg in history[:-6]:
            if isinstance(msg, HumanMessage):
                for line in (msg.content or "").split("\n"):
                    stripped = line.strip()
                    if stripped.startswith("## ") or stripped.startswith("### "):
                        key = stripped[:60]
                        if key not in seen:
                            seen.add(key)
                            summary_lines.append(f"  {stripped}")

        summary_msg = HumanMessage(content="\n".join(summary_lines))
        messages[:] = [system, summary_msg] + history[-6:]

    # ── 辅助 ──────────────────────────────────────────────────────────────────

    async def _resolve_branch(self, owner: str, repo: str, branch: str) -> str:
        """解析分支，尝试处理 main/master 不一致。"""
        if branch not in ("main", ""):
            return branch
        try:
            from tools.github_tools import _get_default_branch_impl
            result = await _get_default_branch_impl(owner, repo)
            return result if result else "main"
        except Exception as e:
            logger.warning(f"[{self.__class__.__name__}] 获取默认分支失败: {e}")
            return "main"

    def _build_task_context(
        self, owner: str, repo: str, branch: str,
        file_contents: dict[str, str] | None,
    ) -> str:
        """构建初始任务上下文。

        ⚠️ 重要：预加载文件只给结构线索（如文件名列表、目录树预览），
        不给可直接得出结论的内容（如完整的配置文件），以防止 LLM 跳过工具调用。
        """
        parts = [
            f"## 探索任务\n仓库: {owner}/{repo}@{branch}\n",
        ]

        if file_contents and len(file_contents) > 0:
            parts.append(f"\n## 结构线索（预加载的 {len(file_contents)} 个文件）\n")
            parts.append(
                "⚠️ 以下是预加载文件的**结构线索**，不是完整的文件内容。\n"
                "你必须通过**工具调用**来读取完整文件内容，不能仅凭这些线索下结论。\n\n"
            )

            # 按目录分组，只显示文件名和简短摘要（不含配置详情）
            by_dir: dict[str, list[str]] = {}
            for p in sorted(file_contents.keys()):
                # 提取目录前缀
                parts_list = p.split("/")
                if len(parts_list) > 1:
                    dir_name = parts_list[0]
                else:
                    dir_name = "."
                if dir_name not in by_dir:
                    by_dir[dir_name] = []
                # 只显示文件名，不显示内容摘要（防止 LLM 直接分析）
                by_dir[dir_name].append(parts_list[-1])

            for dir_name in sorted(by_dir.keys()):
                files = by_dir[dir_name]
                parts.append(f"### {dir_name}/\n")
                for f in sorted(files):
                    parts.append(f"- {f}\n")
                parts.append("\n")

            if len(file_contents) > 20:
                parts.append(f"_... 还有 {len(file_contents) - 20} 个文件未显示_\n")

            parts.append(
                "\n📌 **行动指南**：\n"
                "1. 基于以上结构线索，猜测可能的技术方向\n"
                "2. 用 get_file_tree 确认目录结构\n"
                "3. 用 read_file_content 或 search_code 验证猜测\n"
                "4. 至少完成 3 次工具调用才能给出结论\n"
            )
        else:
            parts.append(
                "\n仓库尚未预加载文件，请通过工具自行探索。\n"
                "请先用 get_file_tree 了解整体结构，然后用其他工具深入分析。"
            )

        return "".join(parts)

    # ── 子类必须实现 ──────────────────────────────────────────────────────────

    def _get_agent_name(self) -> str:
        raise NotImplementedError


# ─── 具体 Explorer ────────────────────────────────────────────────────────────

class TechStackExplorer(BaseExplorerAgent):
    """真正的技术栈识别 Agent——LLM 驱动，工具探索，推理验证。"""

    def __init__(self):
        super().__init__()
        self.system_prompt = _TECH_STACK_EXPLORER_INSTRUCTIONS

    def _get_agent_name(self) -> str:
        return "TechStackExplorer"


class QualityExplorer(BaseExplorerAgent):
    """真正的代码质量分析 Agent——LLM 驱动，工具探索，安全审查。"""

    def __init__(self):
        super().__init__()
        self.system_prompt = _QUALITY_EXPLORER_INSTRUCTIONS

    def _get_agent_name(self) -> str:
        return "QualityExplorer"


class ArchitectureExplorer(BaseExplorerAgent):
    """真正的架构识别 Agent——LLM 驱动，工具探索，模式发现。"""

    def __init__(self):
        super().__init__()
        self.system_prompt = _ARCHITECTURE_EXPLORER_INSTRUCTIONS

    def _get_agent_name(self) -> str:
        return "ArchitectureExplorer"


# ─── 编排器 ────────────────────────────────────────────────────────────────

class ExplorerOrchestrator:
    """并行探索编排器。

    同时启动多个 Explorer Agent，每个 Agent 独立探索一个维度。
    通过 asyncio.gather 实现真正的并行，每个 Agent 走完整的 ReAct 循环。

    用法：
        orchestrator = ExplorerOrchestrator()
        results = await orchestrator.explore_all("owner", "repo", "main")
        # results = {
        #     "TechStackExplorer": {"findings": {...}, "reasoning": "...", "_meta": {...}},
        #     "QualityExplorer": {...},
        #     "ArchitectureExplorer": {...},
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
        """并行运行所有 Explorer。"""
        logger.info(f"[ExplorerOrchestrator] 开始并行探索: {owner}/{repo}")

        tasks = [
            _safe_explore(explorer, owner, repo, branch, file_contents)
            for explorer in self.explorers
        ]

        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for explorer, outcome in zip(self.explorers, outcomes):
            name = explorer.__class__.__name__
            if isinstance(outcome, Exception):
                logger.error(f"[{name}] 异常: {outcome}")
                output[name] = {"error": str(outcome)}
            else:
                result: ExplorerResult = outcome
                logger.info(
                    f"[{name}] 完成: {result.duration_ms:.0f}ms, "
                    f"tools={result.tool_call_count}, "
                    f"verification={result.verification_status}, "
                    f"findings={list(result.findings.keys()) or []}"
                )
                output[name] = {
                    **result.findings,
                    "_reasoning": result.reasoning,
                    "_meta": {
                        "duration_ms": round(result.duration_ms, 1),
                        "error": result.error,
                        "tool_calls": result.tool_calls,
                        "tool_call_count": result.tool_call_count,
                        "verification_status": result.verification_status,
                        "min_tool_calls_required": _EXPLORER_MIN_TOOL_CALLS,
                    },
                }

        logger.info(f"[ExplorerOrchestrator] 全部探索完成: {list(output.keys())}")
        return output


# ─── 安全执行封装 ─────────────────────────────────────────────────────────────

async def _safe_explore(
    explorer: BaseExplorerAgent,
    owner: str, repo: str, branch: str,
    file_contents: dict[str, str] | None,
) -> ExplorerResult:
    """执行单个 Explorer，捕获所有异常确保 orchestrator 不崩溃。"""
    try:
        return await explorer.explore(owner, repo, branch, file_contents)
    except Exception as e:
        logger.error(f"[{explorer.__class__.__name__}] explore 异常: {e}", exc_info=True)
        return ExplorerResult(
            explorer_type=explorer.__class__.__name__,
            error=str(e),
        )
