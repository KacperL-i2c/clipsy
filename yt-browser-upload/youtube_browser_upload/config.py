"""Konfiguracja modułu: selektory Studio, timeouty, stałe.

SELEKTORY — zasada: strukturalne ID wewnętrznych komponentów Studio i atrybuty
`name` (`tp-yt-paper-radio-button[name="UNLISTED"]`) są NIEZALEŻNE OD JĘZYKA
konta; widoczne etykiety ("Publish", "Show more") zależą od locale profilu.
Dlatego każda krotka to lista kandydatów primary → fallback; fallbacki tekstowe
zakładają UI po angielsku (kontekst `locale="en-US"` w browser.py to wymusza
na poziomie przeglądarki, o ile konto nie ma wymuszonego języka w ustawieniach).

Elementy input[type=file] w Studio są ukryte (`display:none`) — dla nich używaj
`state="attached"` (set_input_files nie wymaga widoczności).
"""
from __future__ import annotations

from pathlib import Path

# --- profil / URL ---------------------------------------------------------

DEFAULT_PROFILE_DIR = Path("~/.yt-browser-upload-profile")
STUDIO_URL = "https://studio.youtube.com/"
# Legacy entry: przekierowuje prosto w dialog uploadu Studio (pomija klikanie
# Create → Upload videos — mniej punktów awarii). Fallback UI w studio_form.py.
UPLOAD_URL = "https://www.youtube.com/upload"

# --- timeouty (ms) --------------------------------------------------------

NAV_TIMEOUT_MS = 60_000            # goto + SPA Studio (ciężki bundle)
LOGIN_CHECK_TIMEOUT_MS = 15_000    # jak szybko studio redirectuje na logowanie
STEP_TIMEOUT_MS = 20_000           # pojedyncza akcja UI (klik, wypełnienie pola)
ATTACH_TIMEOUT_MS = 90_000         # pojawienie się dialogu uploadu po /upload
CONFIRM_TIMEOUT_MS = 20_000        # dialog potwierdzenia po Publish
# Upload + processing potrafi trwać długo (rozmiar pliku, obciążenie YouTube).
# Playwright sam czeka aż przycisk Publish/Save stanie się aktywny — bez sleepów.
PUBLISH_TIMEOUT_MS = 45 * 60_000
LOGIN_WAIT_S = 600                 # ile czekać na ręczne logowanie (headless=False)

# Details → Video elements → Checks → Visibility = 3× Next przed Publish/Save.
NEXT_STEPS = ("Details", "Video elements", "Checks")

# --- widoczność (atrybuty `name` radiobuttonów — locale-independent) ------

PRIVACY_RADIO_NAMES = {
    "public": "PUBLIC",
    "unlisted": "UNLISTED",
    "private": "PRIVATE",
}
PRIVACY_RADIO_FMT = 'tp-yt-paper-radio-button[name="{name}"]'

# --- selektory (kolejno: primary → fallbacki) -----------------------------

FILE_INPUT = (
    'input[type="file"][accept*="video"]',
    'input[type="file"]',
)

TITLE_BOX = (
    "#title-textfield #textbox",
    'ytcp-textbox#title-textfield div[contenteditable="true"]',
)

DESCRIPTION_BOX = (
    "#description-textfield #textbox",
    '#description-textfield div[contenteditable="true"]',
)

KIDS_RADIO_NOT_MADE = (
    'tp-yt-paper-radio-button[name="NOT_MADE_FOR_KIDS"]',
)
KIDS_RADIO_MADE = (
    'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS"]',
)

SHOW_MORE_BUTTON = (
    "ytcp-button#toggle-button",
    'ytcp-button:has-text("Show more")',
)

TAGS_INPUT = (
    "ytcp-form-tags-input input",
    'input[aria-label="Tags"]',
)

THUMBNAIL_INPUT = (
    'input[type="file"][accept*="image"]',
)

NEXT_BUTTON = (
    "ytcp-button#next-button",
    'ytcp-button:has-text("Next")',
)

# Finalny przycisk dialogu: "Publish" (public) / "Save" (unlisted, private) —
# to samo `id="done-button"`; Playwright sam odczeka aż przestanie być disabled.
DONE_BUTTON = (
    "ytcp-button#done-button",
    'ytcp-button:has-text("Publish")',
    'ytcp-button:has-text("Save")',
)

CREATE_BUTTON = (
    "ytcp-button#create-icon",
    '#create-icon',
)

UPLOAD_MENU_ITEM = (
    'tp-yt-paper-item:has-text("Upload videos")',
    'ytcp-text-menu tp-yt-paper-item:has-text("Upload")',
)

# Dialog potwierdzenia ("Video published" / "Video saved")
PUBLISHED_LINK = (
    'ytcp-uploads-dialog a[href*="youtu.be/"]',
    'ytcp-uploads-dialog a[href*="watch?v="]',
    'a[href*="youtu.be/"]',
    'a[href*="watch?v="]',
)
# Fallback bez kotwicy: src miniatury podglądu = https://i.ytimg.com/vi/<ID>/...
VIDEO_PREVIEW_IMG = (
    'ytcp-uploads-dialog img[src*="i.ytimg.com/vi/"]',
    'img[src*="i.ytimg.com/vi/"]',
)

# Awatar w prawym górnym rogu Studio = pozytywny sygnał zalogowania.
STUDIO_AVATAR = "#avatar-btn"

VIDEO_ID_RE = r"(?:youtu\.be/|watch\?v=|/vi/|shorts/|embed/)([A-Za-z0-9_-]{11})"
