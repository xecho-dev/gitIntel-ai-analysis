"""
LangChain Prompts — 为每个分析 Agent 定义结构化的 Prompt 模板。

这些 Prompts 与 LangChain 的 Runnable 协议兼容，可配合 .invoke() / .stream()
使用，也可以在 Agent 内部作为 LLM 调用的模板。
"""
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate

# ─── 全局系统提示词 ────────────────────────────────────────────────

SYSTEM_GITINTEL = """你是一位专业的软件架构师和代码审计专家，隶属于 GitIntel 项目。
你的职责是根据分析数据，对 GitHub 仓库进行深度分析，输出高质量、结构化的建议。
你必须严格遵循 JSON 格式要求，不要输出任何非 JSON 内容。
"""

# ─── SuggestionAgent Prompt ─────────────────────────────────────────

SUGGESTION_SYSTEM = """{system_context}

【你的任务】
基于以下仓库分析数据，生成 3~5 条深度优化建议。

【分析数据】
{analysis_context}

【输出要求】
每条建议必须包含以下字段：
  - id: 整数，从 100 开始（避免与规则引擎 ID 冲突）
  - type: security | performance | refactor | general
  - title: 中文标题，不超过 30 字
  - description: 详细说明（中文，100-200字），包含具体建议和可操作的步骤
  - priority: high | medium | low
  - category: security | testing | complexity | dependency | architecture | infrastructure | readability | maintenance

请直接返回 JSON 数组，不要包含 markdown 代码块包裹。
"""

SUGGESTION_HUMAN = """仓库: {repo_path}@{branch}

分析数据：
{analysis_context}

请生成优化建议："""


def build_suggestion_prompt(
    repo_path: str,
    branch: str,
    analysis_context: str,
) -> ChatPromptTemplate:
    """构建 SuggestionAgent 的 LangChain Prompt。"""
    return ChatPromptTemplate.from_messages([
        ("system", SUGGESTION_SYSTEM),
        ("human", SUGGESTION_HUMAN),
    ])


# ─── RepoLoaderAgent LLM 决策 Prompt ─────────────────────────────────────
#
# RepoLoader 通过多轮 LLM 决策来智能判断需要加载哪些文件：
#   轮次 1（初始分类）: 基于文件树，决定哪些文件必须加载（P0）、哪些值得加载（P1）
#   轮次 2（深度决策）: 基于已加载的 P0+P1 内容，判断是否需要加载更多 P2 文件
#   轮次 3+（按需迭代）: 如果仍然不够，LLM 可以再次要求加载指定文件，最多 3 轮


def build_repo_loader_initial_prompt(
    repo_path: str,
    tree_list: str,
    total_files: int,
) -> ChatPromptTemplate:
    # 避免 .format() 处理 {{}}，使用 f-string 只替换必要的变量
    system_str = """你是一个代码仓库文件分类助手，擅长根据文件路径和类型判断文件的重要程度。

【你的任务】
分析仓库文件树，将文件分为三个优先级：
- P0（必须加载）：依赖配置文件 + 入口文件 + 核心业务逻辑源码
- P1（值得加载）：重要源码文件 + 配置/数据/样式文件
- P2（可跳过）：其他文件

【分类规则】
1. P0 必须是（硬性规则）：
   - 依赖配置文件：package.json, requirements.txt, go.mod, Cargo.toml, Gemfile, composer.json, pom.xml, build.gradle 等
   - 入口文件：app.js, main.py, index.ts, App.vue 等
   - 核心目录：src/, lib/, components/, api/, server/, cmd/, pkg/ 等

2. P1 应包含：
   - 源码文件：.js, .ts, .jsx, .tsx, .vue, .py, .go, .rs, .java, .rb, .php, .cs 等
   - 配置/数据文件：.json, .yaml, .yml, .toml, .xml, .ini, .html, .css, .scss 等
   - 文档文件：README.md, CHANGELOG.md 等（排除 node_modules 中的）

3. P2 包含：
   - node_modules/, build/, dist/, .git/ 中的文件
   - 二进制文件、图片、字体等
   - 无分析价值的配置文件

【输出格式】
严格返回 JSON 对象，不要用 markdown 代码块包裹，不要输出其他内容。
"""

    # 使用 {{}} 转义 JSON 中的大括号
    json_example = '{{"p0_paths": ["path1", ...], "p1_paths": ["path2", ...], "p2_paths": ["path3", ...]}}'
    human_str = f"""仓库: {repo_path}

【依赖配置文件识别规则】（以下 manifest 文件必须全部纳入 P0；lock 文件由系统自动排除）：
package.json, requirements.txt, requirements-dev.txt, Pipfile, pyproject.toml,
go.mod, Cargo.toml, Gemfile, composer.json, pom.xml, build.gradle

请分析以下文件树，决策每个文件的优先级：

文件树（共 {total_files} 个文件/目录）:
{tree_list}

请将文件分为：
- 必须加载（P0）：上述依赖配置文件 + 入口文件 + 核心业务逻辑源码
- 值得加载（P1）：重要源码文件
- 可跳过（P2）：其他文件

返回格式（必须是合法的 JSON 对象，不要用 markdown 包裹）：
{json_example}
"""
    return ChatPromptTemplate.from_messages([
        ("system", system_str),
        ("human", human_str),
    ])


REPO_LOADER_DECISION_HUMAN = """仓库: {repo_path}

已加载 {loaded_count} 个文件:
{loaded_paths}

已加载文件内容摘要:
{content_summaries}

待候选文件（P2，共 {p2_count} 个）:
{p2_list}

请判断：基于已有文件内容，是否需要加载更多？
如需要，返回最多 {max_extra} 个文件路径（必须是上述列表中的路径）。
如不需要，need_more 设为 false。

返回格式（必须是合法的 JSON 对象，不要用 markdown 包裹）：
{{{{"need_more": true/false, "reason": "判断原因", "additional_paths": ["path1", ...]}}}}
"""


def build_repo_loader_decision_prompt(
    repo_path: str,
    loaded_paths: list[str],
    content_summaries: dict[str, str],
    p2_files: list[dict],
    max_extra: int = 30,
) -> ChatPromptTemplate:
    p2_list = "\n".join(f"- {f['path']} (~{f.get('size', 0)} bytes)" for f in p2_files[:50])
    loaded_paths_str = "\n".join(f"- {p}" for p in loaded_paths[:50])
    summaries_parts = [f"【{k}】: {v[:200]}" for k, v in list(content_summaries.items())[:20]]
    summaries_str = "\n\n".join(summaries_parts)
    return ChatPromptTemplate.from_messages([
        ("system", REPO_LOADER_SYSTEM.format(system_context="")),
        ("human", REPO_LOADER_DECISION_HUMAN.format(
            repo_path=repo_path,
            loaded_count=len(loaded_paths),
            loaded_paths=loaded_paths_str,
            content_summaries=summaries_str,
            p2_count=len(p2_files),
            p2_list=p2_list,
            max_extra=max_extra,
        )),
    ])


# ─── P1 决策 Prompt ─────────────────────────────────────────────────

P1_DECISION_HUMAN = """仓库: {repo_path}

已加载 P0 核心文件的分析结果:
{p0_summary}

已加载 {p0_loaded_count} 个 P0 核心文件。

待候选 P1 文件（共 {p1_count} 个）:
{p1_list}

待候选 P2 文件（共 {p2_count} 个）:
（暂不列出，基于文件类型判断）

请判断：基于 P0 文件的分析结果，是否需要加载 P1 文件？
- 如果项目架构清晰、核心代码已充分分析，可以跳过 P1
- 如果需要更全面的代码覆盖，建议加载 P1

返回格式（严格 JSON）:
{{{{"need_more": true/false, "reason": "判断原因（100字以内）"}}}}
"""


def build_p1_decision_prompt(
    repo_path: str,
    p0_summary: str,
    p0_loaded_count: int,
    p1_files: list[str],
    p1_count: int,
    p2_count: int,
) -> ChatPromptTemplate:
    p1_list = "\n".join(f"- {p}" for p in p1_files[:30])
    return ChatPromptTemplate.from_messages([
        ("system", REPO_LOADER_SYSTEM.format(system_context="")),
        ("human", P1_DECISION_HUMAN.format(
            repo_path=repo_path,
            p0_summary=p0_summary,
            p0_loaded_count=p0_loaded_count,
            p1_list=p1_list,
            p1_count=p1_count,
            p2_count=p2_count,
        )),
    ])


# ─── P2 决策 Prompt ─────────────────────────────────────────────────

P2_DECISION_HUMAN = """仓库: {repo_path}

已加载文件的代码分析结果:
{code_summary}

已加载 {loaded_count} 个文件。

待候选 P2 文件（共 {p2_count} 个，取前 50 个候选）:
{p2_list}

请判断：基于已加载文件的分析结果，是否需要加载更多 P2 文件？
如需要，返回最多 {max_extra} 个最重要的文件路径（必须是上述列表中的路径）。
如不需要，need_more 设为 false。

考虑因素：
- 补充核心模块的边界代码
- 加载还未分析过的关键业务逻辑
- 避免重复分析已加载文件的功能

返回格式（严格 JSON）:
{{{{"need_more": true/false, "reason": "判断原因（100字以内）", "additional_paths": ["path1", ...]}}}}
"""


def build_p2_decision_prompt(
    repo_path: str,
    code_summary: str,
    loaded_count: int,
    p2_files: list[dict],
    max_extra: int = 30,
) -> ChatPromptTemplate:
    p2_list = "\n".join(f"- {f['path']} (~{f.get('size', 0)} bytes)" for f in p2_files[:50])
    return ChatPromptTemplate.from_messages([
        ("system", REPO_LOADER_SYSTEM.format(system_context="")),
        ("human", P2_DECISION_HUMAN.format(
            repo_path=repo_path,
            code_summary=code_summary,
            loaded_count=loaded_count,
            p2_list=p2_list,
            p2_count=len(p2_files),
            max_extra=max_extra,
        )),
    ])


# ─── 通用摘要 Prompt ────────────────────────────────────────────────

SUMMARY_SYSTEM = """{system_context}

你是一位技术文档撰写专家。请根据提供的分析数据，撰写一份简洁的技术报告摘要。
"""

SUMMARY_HUMAN = """请为以下仓库分析撰写一份 200 字以内的中文摘要：

仓库：{repo_path}
分支：{branch}

分析摘要：
{analysis_summary}

报告应包含：
1. 项目概述（技术栈、语言）
2. 主要发现（质量评分、风险等级）
3. 最重要的一条建议
"""



def build_summary_prompt(
    repo_path: str,
    branch: str,
    analysis_summary: str,
) -> ChatPromptTemplate:
    """构建摘要报告的 LangChain Prompt。"""
    return ChatPromptTemplate.from_messages([
        ("system", SUMMARY_SYSTEM),
        ("human", SUMMARY_HUMAN),
    ])
