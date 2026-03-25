from typing import TypedDict, Optional


class AnalysisState(TypedDict):
    repo_url: str
    branch: str
    # 各 Agent 结果
    architecture_result: Optional[dict]
    quality_result: Optional[dict]
    dependency_result: Optional[dict]
    optimization_result: Optional[dict]
    # 元数据
    errors: list[str]
