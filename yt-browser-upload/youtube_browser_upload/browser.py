"""Trwała sesja przeglądarki (launch_persistent_context) + logowanie.

Kluczowa idea: `user_data_dir` przechowuje cookies sesji Google — raz zalogowany
profil (ręcznie, z 2FA) pozwala na headless uploady bez żadnych promptów,
aż do naturalnego wygaśnięcia sesji (wtedy `SessionExpiredError`).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from playwright.sync_api import (
    BrowserContext,
    Locator,
    Playwright,
    TimeoutError as PWTimeout,
    sync_playwright,
)

from .config import (
    DEFAULT_PROFILE_DIR,
    LOGIN_CHECK_TIMEOUT_MS,
    LOGIN_WAIT_S,
    NAV_TIMEOUT_MS,
    STUDIO_AVATAR,
    STUDIO_URL,
)

log = logging.getLogger("yt-upload.browser")

# ⚠️ Regexy wait_for_url MUSZĄ być zakotwiczone (^scheme://host) — luźny
# "studio\.youtube\.com" dopasował się do parametru continue= na stronie
# logowania Google → fałszywy pozytyw "zalogowano" po 3 s (bug z pierwszego
# smoke testu 2026-11-12).
RE_ON_STUDIO = re.compile(r"^https://studio\.youtube\.com")
RE_ON_ACCOUNTS = re.compile(r"^https://accounts\.google\.com")

# Minimalny set stealth: Studio nie powinno widzieć `navigator.webdriver`,
# a kontenery/root potrzebują --no-sandbox + --disable-dev-shm-usage.
STEALTH_ARGS = (
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
)
CONTAINER_ARGS = (
    "--no-sandbox",
    "--disable-dev-shm-usage",
)


def launch_persistent_session(
    profile_dir: str | Path | None = None,
    *,
    headless: bool = True,
    browser_args: list[str] | tuple[str, ...] | None = None,
    timezone_id: str = "Europe/Warsaw",
):
    """Odpala Chromium z trwałym profilem sesji.

    Zwraca `(playwright, context)` — oba trzeba posprzątać (`ctx.close()`,
    `pw.stop()`; patrz `_close_session`). Katalog profilu jest tworzony
    w razie potrzeby i przetrwa restarty (cookies = no 2FA na kolejnych runach).
    """
    profile = Path(profile_dir or DEFAULT_PROFILE_DIR).expanduser()
    profile.mkdir(parents=True, exist_ok=True)

    args = list(STEALTH_ARGS) + list(CONTAINER_ARGS)
    if browser_args:
        args.extend(browser_args)

    log.info("🌐 Chromium (headless=%s, profil: %s)", headless, profile)
    pw = sync_playwright().start()
    try:
        ctx = pw.chromium.launch_persistent_context(
            str(profile),
            headless=headless,
            locale="en-US",           # wspiera fallbacki tekstowe w config.py
            timezone_id=timezone_id,
            viewport={"width": 1366, "height": 850},
            accept_downloads=False,
            args=args,
        )
        ctx.set_default_timeout(20_000)
        return pw, ctx
    except Exception:
        pw.stop()
        raise


def _close_session(pw: Playwright, ctx: BrowserContext) -> None:
    """Sprzątaniem też nie wolno zabić głównego wyjątku — best-effort."""
    for fn in (ctx.close, pw.stop):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            log.debug("Cleanup: %s", exc)


def is_logged_in(ctx: BrowserContext) -> bool:
    """Sprawdza sesję: Studio redirectuje niezaalogowanych na accounts.google.com.

    Sygnały: (a) URL uciekł na accounts.google.com → brak sesji;
    (b) awatar Studio obecny → sesja OK; (c) URL został w studio.youtube.com
    → sesja najpewniej OK (awatar bywa opóźniony przez SPA).
    """
    page = ctx.new_page()
    try:
        page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        if "accounts.google.com" in page.url:
            return False
        try:
            page.wait_for_url(
                RE_ON_ACCOUNTS, timeout=LOGIN_CHECK_TIMEOUT_MS
            )
            return False
        except PWTimeout:
            pass
        try:
            page.wait_for_selector(STUDIO_AVATAR, state="attached", timeout=10_000)
            return True
        except PWTimeout:
            return "studio.youtube.com" in page.url
    finally:
        page.close()


def wait_for_manual_login(ctx: BrowserContext, *, timeout_s: int = LOGIN_WAIT_S) -> None:
    """Czeka aż user zaloguje się ręcznie w oknie przeglądarki (headless=False).

    Wymaga, żeby kontekst był uruchomiony z `headless=False`. Po zalogowaniu
    Google wraca na studio.youtube.com — na to czekamy.
    """
    page = ctx.new_page()
    try:
        page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        if "accounts.google.com" not in page.url:
            return
        log.info("🔐 Zaloguj się w oknie przeglądarki (login + 2FA). Czekam do %d min…",
                 timeout_s // 60)
        page.wait_for_url(RE_ON_STUDIO, timeout=timeout_s * 1000)
    finally:
        page.close()


def login_interactive(
    profile_dir: str | Path | None = None,
    *,
    headless: bool = False,
    wait_minutes: int = 15,
    browser_args: list[str] | tuple[str, ...] | None = None,
) -> bool:
    """Pierwsze logowanie: otwiera okno z trwałym profilem i czeka na login+2FA.

    Profil zapisuje się na dysku → kolejne `upload_to_youtube(headless=True)`
    już go użyją. Zwraca True, jeśli sesja jest zapisana.
    """
    if headless:
        log.warning("login_interactive z headless=True nie ma sensu przy braku sesji "
                    "— wymuszam headless=False")
        headless = False

    pw, ctx = launch_persistent_session(
        profile_dir, headless=headless, browser_args=browser_args
    )
    try:
        page = ctx.new_page()
        page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        if "accounts.google.com" not in page.url:
            log.info("✅ Sesja już jest ważna — nic do zrobienia (profil: %s)",
                     profile_dir or DEFAULT_PROFILE_DIR)
            return True
        log.info("🔐 Zaloguj się ręcznie w otwartym oknie (masz ~%d min). "
                 "Po zalogowaniu Studio wróci samo, profil zapisze cookies.",
                 wait_minutes)
        try:
            page.wait_for_url(
                RE_ON_STUDIO, timeout=wait_minutes * 60_000
            )
            log.info("✅ Zalogowano — profil sesji gotowy; od teraz headless bez 2FA")
            return True
        except PWTimeout:
            log.error("❌ Nie zalogowano w %d min — profil może być niekompletny",
                      wait_minutes)
            return False
    finally:
        _close_session(pw, ctx)


def first_visible(locators: list[Locator]) -> Locator | None:
    """Pomocnicze: pierwszy z listy locatorów, który cokolwiek przypiął."""
    for loc in locators:
        try:
            if loc.count() > 0:
                return loc
        except Exception:  # noqa: BLE001
            continue
    return None
