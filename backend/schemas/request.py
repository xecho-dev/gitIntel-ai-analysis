from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    repo_url: str
    branch: str = "main"


class ExportPdfRequest(BaseModel):
    repo_url: str
    branch: str = "main"
    result_data: dict
