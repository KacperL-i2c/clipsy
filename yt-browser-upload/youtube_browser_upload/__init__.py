"""YouTube upload przez UI Studio (Playwright) — bez YouTube Data API v3.

Publiczne API:
    upload_to_youtube(...)   → UploadResult
    login_interactive(...)   → bool (pierwsze logowanie, zapis profilu)
"""
from __future__ import annotations

from .browser import login_interactive
from .exceptions import SessionExpiredError, StageError, YouTubeUploadError
from .logging_setup import setup_logging
from .uploader import UploadResult, upload_to_youtube

__all__ = [
    "upload_to_youtube",
    "login_interactive",
    "UploadResult",
    "YouTubeUploadError",
    "SessionExpiredError",
    "StageError",
    "setup_logging",
]

__version__ = "1.0.0"
