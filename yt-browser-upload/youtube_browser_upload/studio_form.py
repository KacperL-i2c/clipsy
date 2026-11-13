"""Automatyzacja formularza uploadu YouTube Studio — etapy 1:1 z UI.

Kolejność etapów (zgodna z obecnym Studio):
  dialog uploadu → Details (plik/tytuł/opis/kids/tagi/miniatura)
  → Next ×3 (Video elements → Checks) → Visibility → Publish/Save → potwierdzenie.

Żadnych sztywnych sleepów: każda akcja to dynamiczne `wait_for` / klik z
actionability-checks Playwrighta (przycisk Publish/Save jest disabled aż do
końca upload+processing — klik z długim timeoutem sam to obsłuży).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from playwright.sync_api import (
    Locator,
    Page,
    TimeoutError as PWTimeout,
    Error as PlaywrightError,
)

from .config import (
    ATTACH_TIMEOUT_MS,
    CONFIRM_TIMEOUT_MS,
    CREATE_BUTTON,
    DESCRIPTION_BOX,
    DONE_BUTTON,
    FILE_INPUT,
    KIDS_RADIO_NOT_MADE,
    NAV_TIMEOUT_MS,
    NEXT_BUTTON,
    NEXT_STEPS,
    PRIVACY_RADIO_FMT,
    PUBLISHED_LINK,
    SHOW_MORE_BUTTON,
    STEP_TIMEOUT_MS,
    STUDIO_URL,
    TAGS_INPUT,
    THUMBNAIL_INPUT,
    TITLE_BOX,
    UPLOAD_MENU_ITEM,
    UPLOAD_URL,
    VIDEO_ID_RE,
    VIDEO_PREVIEW_IMG,
)
from .exceptions import StageError

log = logging.getLogger("yt-upload.form")


def extract_video_id(text: str) -> str | None:
    """Wyciąga 11-znakowe video_id z URL-a youtu.be/watch?v=/vi/shorts."""
    m = re.search(VIDEO_ID_RE, text or "")
    return m.group(1) if m else None


class StudioUploadForm:
    """Envelope nad jedną kartą (page) Studio — metody = etapy formularza."""

    def __init__(self, page: Page, log_: logging.Logger | None = None):
        self.page = page
        self.log = log_ or log

    # ------------------------------------------------------------------ #
    #  wewnętrzne                                                        #
    # ------------------------------------------------------------------ #

    def _resolve(
        self,
        selectors: tuple[str, ...],
        *,
        timeout_ms: int = STEP_TIMEOUT_MS,
        state: str = "visible",
        required: bool = True,
        what: str = "element",
    ) -> Locator | None:
        """Pierwszy pasujący selektor z krotki fallbacków.

        Najpierw scope dialogu uploadu (`ytcp-uploads-dialog` — precyzja),
        potem cała strona. `required=False` dla elementów opcjonalnych
        (tagi, miniatura) — zwraca None zamiast rzucać.
        """
        per_candidate = max(timeout_ms // max(len(selectors), 1), 1_500)
        dialog = self.page.locator("ytcp-uploads-dialog").first

        for sel in selectors:
            candidates = [self.page.locator(sel).first]
            try:
                if dialog.count() > 0:
                    candidates.insert(0, dialog.locator(sel).first)
            except PlaywrightError:
                pass
            for loc in candidates:
                try:
                    loc.wait_for(state=state, timeout=per_candidate)
                    return loc
                except PWTimeout:
                    continue

        if required:
            raise StageError(
                what,
                f"brak elementu po timeout ({timeout_ms} ms); selektory: {selectors!r}. "
                "Najpewniej zmieniło się UI Studio → update config.py.",
            )
        return None

    # ------------------------------------------------------------------ #
    #  etapy                                                             #
    # ------------------------------------------------------------------ #

    def open_upload_dialog(self) -> None:
        """Otwiera dialog uploadu: ścieżka główna /upload, fallback Create-menu."""
        self.log.info("🌐 Otwieram Studio (ścieżka uploadu)…")
        self.page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        try:
            self._resolve(
                FILE_INPUT,
                timeout_ms=ATTACH_TIMEOUT_MS,
                state="attached",
                what="input pliku w dialogu uploadu",
            )
            self.log.info("✅ Dialog uploadu otwarty")
            return
        except StageError:
            self.log.warning(
                "⚠️ /upload nie otworzyło dialogu — fallback: Studio → Create → Upload videos…"
            )

        self.page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        self._resolve(CREATE_BUTTON, what="przycisk Create").click()
        self._resolve(UPLOAD_MENU_ITEM, what="pozycja menu „Upload videos”").click()
        self._resolve(
            FILE_INPUT,
            timeout_ms=ATTACH_TIMEOUT_MS,
            state="attached",
            what="input pliku w dialogu uploadu",
        )
        self.log.info("✅ Dialog uploadu otwarty (ścieżka Create-menu)")

    def upload_video_file(self, video_path: str | Path) -> None:
        """Przekazuje plik inputowi dialogu — upload rusza w tle podczas wypełniania."""
        path = Path(video_path)
        size_mb = path.stat().st_size / (1024 * 1024)
        self.log.info("📤 Wgrywam plik: %s (%.1f MB)", path.name, size_mb)
        inp = self._resolve(
            FILE_INPUT, timeout_ms=ATTACH_TIMEOUT_MS, state="attached", what="input pliku"
        )
        inp.set_input_files(str(path))
        self.log.info("✅ Plik przekazany — upload/processing idzie w tle")

    def fill_title(self, title: str) -> None:
        """Tytuł. Studio SAM wypełnia go nazwą pliku → Ctrl+A + wpisanie czyści to."""
        self.log.info("✏️ Tytuł: %s", title[:110])
        box = self._resolve(TITLE_BOX, what="pole tytułu")
        box.click()
        self.page.keyboard.press("ControlOrMeta+a")
        self.page.keyboard.insert_text(title)

    def fill_description(self, description: str) -> None:
        self.log.info("📝 Opis (%d znaków)", len(description))
        box = self._resolve(DESCRIPTION_BOX, what="pole opisu")
        box.click()
        self.page.keyboard.press("ControlOrMeta+a")  # bezpieczne też przy pustym polu
        self.page.keyboard.insert_text(description)  # obsługuje \n w contenteditable

    def set_not_made_for_kids(self) -> None:
        """Zaznacza „No, it's not made for kids” (radio name=NOT_MADE_FOR_KIDS)."""
        self.log.info("👶 Ustawiam: nie dla dzieci (NOT_MADE_FOR_KIDS)")
        loc = self._resolve(KIDS_RADIO_NOT_MADE, required=False, timeout_ms=8_000)
        if loc is not None:
            loc.click()
            return
        # Fallback po etykiecie (UI po angielsku)
        try:
            self.page.get_by_text("No, it's not made for kids").first.click(
                timeout=STEP_TIMEOUT_MS
            )
        except PlaywrightError as exc:
            raise StageError(
                "audience",
                "nie znaleziono radia NOT_MADE_FOR_KIDS (zmiana UI albo nieangielski "
                "UI konta — check selektor w config.py)",
            ) from exc

    def add_tags(self, tags: list[str]) -> None:
        """Tagi: rozwija „Show more”, wpisuje po Enter na tag.

        Opcjonalny etap — brak pola nie wywala uploadu (warn + continue),
        żeby zmiana kosmetyczna UI nie zabijała publikacji w pipeline.
        """
        self.log.info("🏷️ Tagi (%d): %s", len(tags), ", ".join(tags))
        more = self._resolve(SHOW_MORE_BUTTON, required=False, timeout_ms=8_000)
        if more is not None:
            try:
                more.click()
            except PlaywrightError:
                pass  # sekcja mogła być już rozwinięta
        inp = self._resolve(TAGS_INPUT, required=False, timeout_ms=10_000)
        if inp is None:
            self.log.warning("⚠️ Brak pola tagów — pomijam (upload idzie dalej)")
            return
        inp.click()
        for tag in tags:
            self.page.keyboard.insert_text(tag)
            self.page.keyboard.press("Enter")

    def set_thumbnail(self, thumbnail_path: str | Path) -> None:
        """Miniatura (opcjonalna — wymaga konta ze zweryfikowanym telefonem)."""
        path = Path(thumbnail_path)
        self.log.info("🖼️ Miniatura: %s", path.name)
        inp = self._resolve(
            THUMBNAIL_INPUT, required=False, timeout_ms=10_000, state="attached"
        )
        if inp is None:
            self.log.warning(
                "⚠️ Brak inputu miniatury (konto bez weryfikacji telefonu / zmiana UI) — pomijam"
            )
            return
        inp.set_input_files(str(path))
        self.log.info("✅ Miniatura przekazana")

    def next_step(self, step_name: str, *, click_timeout_ms: int) -> None:
        """Klik Next — Playwright sam odczeka aż przycisk będzie aktywny."""
        self.log.info("⏭️ Next — opuszczam etap %s", step_name)
        btn = self._resolve(NEXT_BUTTON, what="przycisk Next")
        try:
            btn.click(timeout=click_timeout_ms)
        except PWTimeout as exc:
            raise StageError(
                f"next:{step_name}",
                "przycisk Next nie był klikalny — upload/processing nadal trwa "
                "albo YouTube dodał obowiązkowy krok formularza",
            ) from exc

    def set_visibility(self, privacy: str, radio_name: str) -> None:
        self.log.info("👁️ Widoczność: %s", privacy)
        loc = self._resolve(
            (PRIVACY_RADIO_FMT.format(name=radio_name),),
            what=f"radio widoczności {privacy}",
        )
        loc.click()

    def publish(self, *, click_timeout_ms: int) -> None:
        """Klik Publish/Save — pojedynczy klik CZEKA na koniec upload+processing."""
        self.log.info(
            "⏳ Publikacja — przycisk Publish/Save odblokuje się po uploadzie+processingu "
            "(maks. %.0f min)…",
            click_timeout_ms / 60_000,
        )
        btn = self._resolve(DONE_BUTTON, what="przycisk Publish/Save (done-button)")
        try:
            btn.click(timeout=click_timeout_ms)
        except PWTimeout as exc:
            raise StageError(
                "publish",
                f"przycisk nie odblokował się w {click_timeout_ms // 60_000} min — "
                "processing wciąż trwa (zwiększ publish_timeout_ms) albo zmieniło się UI",
            ) from exc
        self.log.info("✅ Publish/Save kliknięty — czekam na potwierdzenie Studio")

    def published_video_url(self) -> tuple[str | None, str | None]:
        """Link i video_id z dialogu potwierdzenia (fallbacki: a → img src)."""
        link = self._resolve(
            PUBLISHED_LINK, timeout_ms=CONFIRM_TIMEOUT_MS, required=False, state="attached"
        )
        if link is not None:
            vid = extract_video_id(link.get_attribute("href") or "")
            if vid:
                return f"https://youtu.be/{vid}", vid

        img = self._resolve(
            VIDEO_PREVIEW_IMG, timeout_ms=5_000, required=False, state="attached"
        )
        if img is not None:
            vid = extract_video_id(img.get_attribute("src") or "")
            if vid:
                return f"https://youtu.be/{vid}", vid

        self.log.warning(
            "⚠️ Nie odczytałem video_id z dialogu potwierdzenia (upload wylądował — "
            "sprawdź w Studio). Zmiana UI → update config.py."
        )
        return None, None

    # Wyeksportowane dla czytelności orkiestratora
    NEXT_STEPS = NEXT_STEPS
