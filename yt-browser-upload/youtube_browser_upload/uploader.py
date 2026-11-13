"""upload_to_youtube — orkiestracja całego flow uploadu przez UI Studio."""
from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .browser import (
    _close_session,
    is_logged_in,
    launch_persistent_session,
    wait_for_manual_login,
)
from .config import (
    DEFAULT_PROFILE_DIR,
    LOGIN_WAIT_S,
    NEXT_STEPS,
    PRIVACY_RADIO_NAMES,
    PUBLISH_TIMEOUT_MS,
)
from .exceptions import SessionExpiredError, StageError, YouTubeUploadError
from .logging_setup import LOGGER_NAME
from .studio_form import StudioUploadForm

log = logging.getLogger(LOGGER_NAME)


@dataclass(frozen=True)
class UploadResult:
    """Wynik uploadu — do logowania/DB w pipeline. video_id/url bywają None,
    gdy dialog potwierdzenia zmienił strukturę (upload mimo wszystko się udał)."""

    video_id: str | None
    url: str | None
    title: str
    privacy: str
    video_path: str


def _normalize_tags(tags: str | Sequence[str] | None) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(",") if t.strip()]
    return [str(t).strip() for t in tags if str(t).strip()]


def upload_to_youtube(
    video_path: str | Path,
    title: str,
    description: str,
    tags: str | Sequence[str] | None = None,
    privacy: str = "unlisted",
    thumbnail_path: str | Path | None = None,
    *,
    headless: bool = True,
    profile_dir: str | Path | None = None,
    browser_args: list[str] | tuple[str, ...] | None = None,
    publish_timeout_ms: int = PUBLISH_TIMEOUT_MS,
    login_wait_s: int = LOGIN_WAIT_S,
    logger: logging.Logger | None = None,
) -> UploadResult:
    """Wgrywa wideo na YouTube przez formularz Studio (bez YouTube Data API).

    Pierwsze uruchomienie: `headless=False` → moduł sam poczeka na ręczne
    logowanie i zapisze profil sesji. Kolejne: `headless=True` (default)
    korzysta z zapisanych cookies — bez 2FA, bez promptów.

    Raises:
        SessionExpiredError: brak ważnej sesji przy headless=True → wywołaj
            `login_interactive()` albo run z headless=False.
        StageError: konkretny etap formularza nie wypadł (zwykle zmiana UI).
        YouTubeUploadError: walidacja wejścia / inne błędy modułu.
    """
    log_ = logger or log
    started = time.monotonic()

    # --- walidacja wejścia (fail fast, zanim odpalimy przeglądarkę) --------
    privacy_key = (privacy or "").strip().lower()
    if privacy_key not in PRIVACY_RADIO_NAMES:
        raise YouTubeUploadError(
            f"privacy={privacy!r} — dozwolone: {sorted(PRIVACY_RADIO_NAMES)}"
        )

    video_path = Path(video_path).expanduser().resolve()
    if not video_path.is_file():
        raise YouTubeUploadError(f"Nie znaleziono pliku wideo: {video_path}")

    thumbnail = None
    if thumbnail_path is not None:
        thumbnail = Path(thumbnail_path).expanduser().resolve()
        if not thumbnail.is_file():
            raise YouTubeUploadError(f"Nie znaleziono miniatury: {thumbnail}")

    title = str(title).strip()
    if not title:
        raise YouTubeUploadError("title nie może być pusty")
    tag_list = _normalize_tags(tags)

    profile = Path(profile_dir or DEFAULT_PROFILE_DIR).expanduser()
    log_.info(
        "🎬 upload_to_youtube: %s → %s (profil: %s, headless=%s)",
        video_path.name, privacy_key, profile, headless,
    )

    # --- sesja --------------------------------------------------------------
    pw, ctx = launch_persistent_session(
        profile, headless=headless, browser_args=browser_args
    )
    try:
        if not is_logged_in(ctx):
            if headless:
                raise SessionExpiredError(
                    "Profil nie ma ważnej sesji Google. Jednorazowo: "
                    "login_interactive() LUB upload_to_youtube(..., headless=False) "
                    "— moduł poczeka na ręczne logowanie (2FA) i zapisze profil."
                )
            log_.warning(
                "🔐 Brak ważnej sesji — czekam na ręczne logowanie w oknie "
                "przeglądarki (%.0f min na to)…", login_wait_s / 60,
            )
            wait_for_manual_login(ctx, timeout_s=login_wait_s)
            log_.info("✅ Zalogowano — profil sesji zapisany w %s (od teraz headless)", profile)

        # --- formularz -------------------------------------------------------
        page = ctx.new_page()
        form = StudioUploadForm(page, log_=log_)

        form.open_upload_dialog()
        form.upload_video_file(video_path)
        form.fill_title(title)
        form.fill_description(str(description))
        form.set_not_made_for_kids()
        if tag_list:
            form.add_tags(tag_list)
        if thumbnail is not None:
            form.set_thumbnail(thumbnail)

        # Details → Video elements → Checks; długi timeout kliku pokrywa przypadek,
        # gdy YouTube blokuje Next do końca processingu (zamiast pollingów).
        for step_name in NEXT_STEPS:
            form.next_step(step_name, click_timeout_ms=publish_timeout_ms)

        form.set_visibility(privacy_key, PRIVACY_RADIO_NAMES[privacy_key])
        form.publish(click_timeout_ms=publish_timeout_ms)

        url, video_id = form.published_video_url()
        elapsed = time.monotonic() - started
        log_.info("✅ Upload zakończony w %.1f s → %s (id=%s)", elapsed, url, video_id)
        return UploadResult(
            video_id=video_id,
            url=url,
            title=title,
            privacy=privacy_key,
            video_path=str(video_path),
        )
    finally:
        _close_session(pw, ctx)


__all__ = ["UploadResult", "upload_to_youtube", "StageError", "SessionExpiredError"]
