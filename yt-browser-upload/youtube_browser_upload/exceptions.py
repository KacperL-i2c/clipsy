"""Wyjątki modułu uploadu — czytelne dla pipeline'u (loguj / retry / alert)."""
from __future__ import annotations


class YouTubeUploadError(Exception):
    """Baza wszystkich błędów modułu uploadu."""


class SessionExpiredError(YouTubeUploadError):
    """Profil nie ma ważnej sesji Google.

    Remedium: jednorazowe logowanie ręczne — `login_interactive()` albo
    `upload_to_youtube(..., headless=False)` (moduł sam poczeka na logowanie).
    """


class StageError(YouTubeUploadError):
    """Błąd konkretnego etapu formularza Studio.

    Najczęstsza przyczyna: zmiana UI YouTube Studio → zaktualizować selektor
    w `config.py` (patrz README „Utrzymanie selektorów").
    """

    def __init__(self, stage: str, detail: str = ""):
        self.stage = stage
        msg = f"Etap {stage!r}: {detail}" if detail else f"Etap {stage!r} nie powiódł się"
        super().__init__(msg)
