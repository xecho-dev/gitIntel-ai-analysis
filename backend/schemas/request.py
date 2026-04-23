from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    repo_url: str
    branch: str = "main"
    skip_cache: bool = False  # 跳过缓存，强制重新分析


class ExportPdfRequest(BaseModel):
    repo_url: str
    branch: str = "main"
    result_data: dict
    enable_ai_image: bool = False  # 是否启用 AI 生图
