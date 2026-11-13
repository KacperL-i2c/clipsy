# yt-browser-upload — upload wideo na YouTube przez UI Studio (Playwright)

Moduł wpycha wideo na YouTube **przez formularz YouTube Studio w prawdziwej
przeglądarce Chromium** — bez YouTube Data API v3, bez quota, bez audytu Google.
Motywacja: kanał #1 wpadł w `uploadLimitExceeded` (dzienny cap API, patrz
HANDOFF §3 pkt 21) — ścieżka przez UI tych limitów nie ma (limit kanału to
uploady, nie API calls, ale cap „nowego kanału" na API był poziomu kilku/dziennie;
przez UI limit jest znacznie wyższy i związany z wiekiem kanału).

**⚠️ Ryzyka (świadome, po stronie usera):** automatyzacja UI narusza litery
ToS YouTube — w razie detekcji ryzyko flagów/ograniczeń na koncie. Mitigacje:
rozłączne uploady (nie seriami 50/h), sesja z prawdziwego logowania (nie świeży
headless profil), `--disable-blink-features=AutomationControlled`, stabilny
profil na stałym dysku.

---

## Instalacja (na hoście homelaba, NIE w kontenerze clippyme-backend)

```bash
cd yt-browser-upload
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # pobiera Chromium (~150 MB)
```

Kontener `clippyme-backend` nie ma ani Chromium, ani X — moduł jest przeznaczony
na **host** (Ubuntu 24.04 + GNOME na homelabie).

## Pierwsze logowanie (jednorazowo, zapisuje profil sesji)

```bash
python examples/first_login.py
# albo z kodu:
from youtube_browser_upload import login_interactive
login_interactive(profile_dir="/mnt/AMPStorage/apps/yt-upload-profile")
```

Otwiera się widoczne okno Chromium → logujesz się ręcznie (login + hasło + 2FA).
Sesja ląduje w katalogu profilu (`launch_persistent_context` + `user_data_dir`).
**Kolejne uruchomienia (już `headless=True`) używają cookies z profilu — bez 2FA,
bez żadnych promptów.** Sesja Google wygasa rzadko (tygodnie–miesiące); gdy
wygaśnie, moduł rzuci `SessionExpiredError` → powtórz `login_interactive()`.

Tip: profil trzymaj na AMPStorage (przeżywa restarty), np.
`/mnt/AMPStorage/apps/yt-upload-profile`. Profil przenosi się między maszynami
Linux (to zwykły katalog Chromium).

## Użycie

```python
from youtube_browser_upload import upload_to_youtube

res = upload_to_youtube(
    video_path="output/3bedcd13/GTA_VI_clip_1.mp4",
    title="GTA VI leak — this scene is insane #shorts",
    description="Clipped with ClippyMe\n#shorts",
    tags=["gta6", "shorts", "gaming"],     # None albo lista, albo "a,b,c"
    privacy="unlisted",                     # public | unlisted | private
    thumbnail_path="cover.jpg",             # opcjonalne
    headless=True,                          # False → widoczne okno (debug / re-login)
    profile_dir="/mnt/AMPStorage/apps/yt-upload-profile",
)
print(res.video_id, res.url)   # np. dQw4w9WgXcQ https://youtu.be/dQw4w9WgXcQ
```

Przebieg (wszystko logowane etapami, `logging.getLogger("yt-upload")`):

1. launch persistent context → check sesji (brak + `headless=True` → `SessionExpiredError`;
   brak + `headless=False` → czeka na ręczne logowanie w oknie),
2. `studio.youtube.com` → dialog uploadu (input pliku),
3. `set_input_files` (upload rusza w tle), tytuł (czyści auto-wypełnienie nazwą
   pliku), opis, **„No, it's not made for kids"**, tagi, miniatura,
4. Next ×3 (Details → Video elements → Checks), wybór widoczności,
5. klik **Publish/Save** z długim timeoutem — Playwright sam czeka aż przycisk
   odblokuje się po uploadzie+processingu (zero `sleep`ów),
6. wyciągnięcie `video_id`/URL z dialogu potwierdzenia.

## Parametry `upload_to_youtube`

| Parametr | Domyślnie | Opis |
|---|---|---|
| `video_path` | — | plik mp4 (obowiązkowy, walidowany) |
| `title` / `description` | — | tytuł (≤100 zn. pokroje YouTube sam) / opis (\n dozwolone) |
| `tags` | `None` | lista, string „a, b, c", albo None |
| `privacy` | `"unlisted"` | `public`/`unlisted`/`private` |
| `thumbnail_path` | `None` | jpg/png; wymaga konta z **zweryfikowanym telefonem** (inaczej YouTube odrzuci — moduł tego nie wykryje, warn w README) |
| `headless` | `True` | `False` = widoczne okno (pierwszy run / debug) |
| `profile_dir` | `~/.yt-browser-upload-profile` | katalog trwałego profilu |
| `browser_args` | stealth-set | dodatkowe argumenty Chromium |
| `publish_timeout_ms` | 45 min | maks. oczekiwanie na upload+processing |
| `login_wait_s` | 600 | ile czekać na ręczne logowanie przy `headless=False` |
| `logger` | `"yt-upload"` | dowolny logger pipeline'u |

Zwraca `UploadResult(video_id, url, title, privacy, video_path)`. Błędy:
`SessionExpiredError` (sesja wygasła), `StageError` ( konkretny etap formularza —
najczęściej zmiana UI → update selektora w `config.py`).

## Wpięcie w pipeline ClippyMe / n8n

Obecny łańcuch: completion webhook → n8n „Upload to YouTube" (node API).
Zamiennik/warunek awaryjny przy quota:

- **n8n → SSH Execute Command** na host: `.venv/bin/python examples/upload_example.py --file ... --title ... --privacy public` (węzeł SSH ma dostęp do hosta, klucz `ai@192.168.100.2` już działa),
- albo **mały serwis HTTP/FastAPI na hoście** (systemd) z kolejką, wołany z n8n HTTP node.

**Uwaga: uploady muszą iść SERYJNIE** — Studio ma jeden dialog uploadu; równoległe
`upload_to_youtube` na tym samym profilu się wykluczą. W pipeline: prosty
`threading.Lock()` albo kolejka (n8n sam serializuje przy MAX_CONCURRENT_JOBS=1).

## Struktura

```
youtube_browser_upload/
├── config.py        # selektory Studio (strukturalne, locale-independent), timeouty
├── browser.py       # launch_persistent_context, check sesji, login_interactive
├── studio_form.py   # etapy formularza: plik→tytuł→opis→kids→tagi→thumb→next×3→visibility→publish
├── uploader.py      # upload_to_youtube() — orkiestracja + logi etapów
├── exceptions.py    # YouTubeUploadError / SessionExpiredError / StageError
└── logging_setup.py # setup_logging() dla standalone, bez ruszania loggera pipeline'u
```

## Utrzymanie selektorów

YouTube co jakiś czas przebudowuje Studio. Selektory w `config.py` są celowo
**strukturalne** (`#next-button`, `#done-button`,
`tp-yt-paper-radio-button[name="UNLISTED"]`) — etykiety tekstowe to tylko
fallback dla UI po angielsku. Gdy etap padnie na `StageError`:

1. otwórz Studio ręcznie (F12, right-click na elemencie → Inspect),
2. znajdź stabilny atrybut (`id`, `name=` na `tp-yt-paper-radio-button`),
3. dopisz jako **nowy pierwszy** element krotki selektorów w `config.py`.

## Troubleshooting

- **`SessionExpiredError` przy headless** → `login_interactive()` jeszcze raz (jednorazowo, headed).
- **Studio otwiera „wybierz konto/kanał"** → profil może widzieć kilka kanałów brand; wybierz właściwy podczas `login_interactive` — zapamięta się.
- **Processing trwa wieki przy headless** → Google czasem wolniej procesuje z datacenter-owych IP; homelab = IP domowe, zwykle OK. Zwiększ `publish_timeout_ms`.
- **Headless wykrywany / captcha loop** → odpal z `headless=False` pod Xvfb: `xvfb-run -a python ...` (parametry okna zostają, okna nie widać).
- **Miniatura nie przyjęta** → konto bez zweryfikowanego numeru telefonu (wymóg YouTube dla custom thumbnails).
