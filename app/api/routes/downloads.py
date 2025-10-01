from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.downloads import get_downloads_dir

router = APIRouter()

_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_DOWNLOAD_NAMES = {
    ".pdf": "rapor.pdf",
    ".xlsx": "rapor.xlsx",
}


@router.get("/downloads/{file_name}")
async def download_generated_report(file_name: str) -> FileResponse:
    safe_name = Path(file_name).name
    if safe_name != file_name:
        raise HTTPException(status_code=400, detail="Gecersiz dosya adi")

    downloads_dir = get_downloads_dir()
    file_path = downloads_dir / safe_name
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Dosya bulunamadi")

    suffix = file_path.suffix.lower()
    media_type = _MEDIA_TYPES.get(suffix, "application/octet-stream")
    download_name = _DOWNLOAD_NAMES.get(suffix, safe_name)
    return FileResponse(file_path, media_type=media_type, filename=download_name)

