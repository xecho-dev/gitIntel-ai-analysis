"""
导出相关路由 (/api/export)
PDF 导出功能
"""
import io
import re

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from dependencies import get_auth_user_id
from schemas.request import ExportPdfRequest
from services.pdf_service import build_pdf_bytes

router = APIRouter(prefix="/api/export", tags=["export"])


@router.post("/pdf")
async def api_export_pdf(req: ExportPdfRequest, request: Request):
    """将分析结果导出为 PDF 报告（需要登录）"""
    auth_user_id = get_auth_user_id(request)

    pdf_bytes = build_pdf_bytes({
        "repo_url": req.repo_url,
        "branch": req.branch,
        **req.result_data,
    }, enable_ai_image=req.enable_ai_image)

    repo_name = re.sub(r"[^a-zA-Z0-9_-]", "_", req.repo_url.split("/")[-1].replace(".git", ""))
    filename = f"gitintel_{repo_name}_{req.branch}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
