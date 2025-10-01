from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional, Tuple

__all__ = [
    "DOWNLOAD_TTL",
    "get_downloads_dir",
    "store_temporary_download",
    "purge_expired_downloads",
    "build_download_url",
]

_DOWNLOADS_DIR = Path(os.getenv("DOWNLOAD_DIR", "downloads")).resolve()
_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOAD_TTL = timedelta(hours=1)


def _iter_download_files() -> Iterable[Path]:
    try:
        yield from (p for p in _DOWNLOADS_DIR.iterdir() if p.is_file())
    except FileNotFoundError:  # pragma: no cover - directory removed externally
        _DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        return


def purge_expired_downloads(*, now: Optional[datetime] = None) -> None:
    cutoff = (now or datetime.now(timezone.utc)) - DOWNLOAD_TTL
    for file_path in _iter_download_files():
        try:
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime <= cutoff:
            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                continue


def get_downloads_dir() -> Path:
    """Return the directory where generated downloads are stored."""
    purge_expired_downloads()
    return _DOWNLOADS_DIR


def store_temporary_download(content: bytes, *, suffix: str) -> Tuple[str, Path]:
    purge_expired_downloads()
    normalized = suffix if suffix.startswith(".") else f".{suffix}"
    filename = f"{uuid.uuid4().hex}{normalized}"
    file_path = _DOWNLOADS_DIR / filename
    file_path.write_bytes(content)
    return filename, file_path


def build_download_url(file_name: str, base_url: str | None = None) -> str:
    import os
    from urllib.parse import quote
    base = (base_url or os.getenv("PUBLIC_BASE_URL", "")).rstrip("/")
    path = f"/downloads/{quote(file_name)}"
    return f"{base}{path}" if base else path

