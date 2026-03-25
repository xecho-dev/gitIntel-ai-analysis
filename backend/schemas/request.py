from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    repo_url: str
    branch: str = "main"


class HealthRequest(BaseModel):
    pass
