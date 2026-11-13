# PLAN — Browser-upload na YouTube (Playwright, bez YT Data API v3): host-serwis + GUI + n8n routing

> Data: 2026-11-11 · Status: **FEASIBILITY + SONDY ZWERYFIKOWANE na żywym serwerze
> (2026-11-11, §0)** — plan gotowy do wykonania przez nową sesję bez dodatkowego
> kontekstu. Lustrzany wpis: `HANDOFF-clippyme-homelab.md` §7 pkt 13.
>
> **Co już istnieje:** moduł uploadera **NAPISANY**, katalog `yt-browser-upload/`
> (obok handoffu): `youtube_browser_upload/` (config/browser/studio_form/uploader)
> + `examples/{first_login,upload_example}.py` + README. **⚠️ NIE zweryfikowany
> E2E** — tylko syntax-check; selektory DOM Studio mogą wymagać 1-2 poprawek przy
> pierwszym live (pkt 1 kolejności, §6). Signature: `upload_to_youtube(video_path,
> title, description, tags=None, privacy="unlisted", thumbnail_path=None, *,
> headless=True, profile_dir=...)`.
>
> Wymagania usera (2026-11-11, po incydencie `uploadLimitExceeded` na kanale #1,
> §3 pkt 21): upload na YouTube **bez YouTube Data API v3** (omijamy quota/audyt)
> przez Playwright + trwały profil sesji (`launch_persistent_context`); „gotowy do
> wpięcia w nasz obecny pipeline". Decyzja usera: **integracja GUI-first** (reguła
> z nagłówka handoffu) — pytania rozstrzygnięte: pipeline DECYDUJE silnikiem
> per-job z GUI; n8n woła uploader po HTTP; ClippyMe backend nie uruchamia
> przeglądarki (kontener bez Chromium).

---

## 0. SONDY (2026-11-11, live — zmierzone, nie teoria)

| # | Sonda | Wynik |
|---|---|---|
| 1 | Host: python/venv/systemd | Python **3.12.3**, `venv` OK, systemd **255** — wszystko jest |
| 2 | Dysk / port | AMPStorage **423G wolne**; port **8790 WOLNY** (serwis tam) |
| 3 | **Klipy czytelne dla `ai`?** | `output/*/…_clip_N.mp4` = **`-rw-r--r--` (644)**, owner uid 996 (`systemd-timesync`) → **READ_OK na realnym mp4** — host-serwis czyta klipy BEZPOŚREDNIO z dysku (zero downloadu HTTP!). UWAGA: nazwy plików mają **SPACJE + em-dash** (`… — part 1_clip_1.mp4`) |
| 4 | metadata.json / runtime.json | `0600` uid 996 — ai NIE czyta (nieistotne: uploader potrzebuje tylko mp4/jpg) |
| 5 | X session (login headed) | GNOME chodzi jako user **`grejem` na `:0`** (NIE `ai`) → pierwsze logowanie przez **`ssh -X ai@192.168.100.2`** (okno renderuje się u usera lokalnie) albo login gdziekolwiek + rsync profilu (profil Chromium = przenośny katalog) |
| 6 | Porty host | 8000 API, 5175 dashboard, 5678 n8n (dual), 11434 Ollama → serwis na **192.168.100.2:8790** (**LAN bind!** pułapka 127.0.0.1 §6 handoffu) |
| 7 | Punkty zaczepienia backendu (grep live) | `config_store.py:43` (`"PUBLISH_TARGETS"` w VALID_CONFIG_KEYS), `:274` (resolve pattern), `:362` (env default); `schemas.py:186` (allow-list), `:197-200/:244` (walidator); `completion_webhook.py:34/50/84` (`_clip_targets`/`_clip_entry`/`build_completion_payload`); `settings.jsx:91` (Automation panel), `:168` (saveKeys), `:173-192` (tag-input pattern) |
| 8 | n8n | 2.46.6 (docs; `docker inspect` nie zwrócił wersji — niekrytyczne); workflow v3 `LpORWh7hK3bmiHI3` aktywny |

**Wniosek:** uploader jako **host-serwis** czyta klipy wprost z `output/`;
n8n woła go po HTTP z LAN IP; ClippyMe dostaje TYLKO persisted setting
(`UPLOAD_ENGINE`) + proxy statusu sesji. Payload webhooka już ma wszystko, czego
n8n potrzebuje (`job_id` root + `clips[].filename` → sciezka na dysku).

---

## 1. ARCHITEKTURA

```
ClippyMe GUI (Settings → Automation → „Upload engine": n8n API | Browser (Playwright))
   → config.json UPLOAD_ENGINE  (per-job snapshot przez merge_persistent_config)
        └─ completion webhook: engine NA POZIOMIE JOBA — TYLKO gdy =="browser"
           (empty/default = payload byte-legacy, konwencja targets)
ClippyMe backend: GET /api/upload-engine/status (proxy → host-serwis, token w .env)
   [dashboard: badge „Browser session: online/offline · queue: N"]

n8n workflow v4 (LpORWh7hK3bmiHI3; PUT + ZAWSZE POST activate):
   Webhook → „Filter clips" (BEZ zmian) → NOWY Code „Route by engine"
        ├─ brak engine / "n8n-api" (default!) → Keep youtube-default → Download → YT nodes  [v3 BEZ zmian]
        └─ engine=="browser" → Code „Build browser payload" (video_path =
              /mnt/AMPStorage/apps/clippyme/output/{job_id}/{filename};
              title slice 100, description "#shorts\n"+desc — paritet z YT node)
           → HTTP POST http://192.168.100.2:8790/upload [X-Upload-Token, timeout 900 s]

HOST: yt-upload-service (systemd --user? NIE — system unit, user=ai, :8790)
   serial queue (1 worker — Studio ma JEDEN dialog uploadu)
   └─ upload_to_youtube(headless=True, profile=/mnt/AMPStorage/apps/yt-upload-profile)
        └─ Chromium + trwała sesja Google (login 1× przez ssh -X; bez 2FA potem)
```

Zasady spójne z systemem: **n8n = publisher** (decyzja z PLAN multi-account §0),
ClippyMe = orkiestracja + GUI; **default = zachowanie legacy** (deploy bez zmiany
zachowania); config.json = source of truth; GUI-first (silnik wybierany w dashboardzie).

---

## 2. ZMIANY PER WARSTWA

### 2a. HOST — NOWY `/mnt/AMPStorage/apps/yt-browser-upload/`

Skopiować `yt-browser-upload/` + dopisać `service.py` (~150 linii) + unit + .env:

- **service.py** (FastAPI + uvicorn, bind `192.168.100.2:8790`):
  - **POST /upload** `{video_path, title, description, tags[], privacy,
    thumbnail_path?}` + header `X-Upload-Token` — **synchroniczny** (worker
    queue; odpowiedź = wynik uploadu): `200 {video_id, url, privacy, status}`.
    Błędy: 401 zły token · 403 `video_path` poza ALLOWED_ROOTS · 409
    `SessionExpiredError` (hint: ssh -X + first_login) · 422 walidacja ·
    503 kolejka pełna (>8 oczekujących) · 504 StageError/publish-timeout.
  - **GET /session** → `{logged_in (cache TTL 60 s — NIE otwierać przeglądarki
    per poll), queue_depth, last_result}` · **GET /health** → 200.
  - **Path guard**: `Path(video_path).resolve()` musi leżeć pod `ALLOWED_ROOTS`
    (default `/mnt/AMPStorage/apps/clippyme/output`) — inaczej 403 (serwis nie
    może być arbitrary-file-read).
- **.env** (0600): `UPLOAD_TOKEN=<openssl rand -hex 16>`, `ALLOWED_ROOTS`,
  `YT_UPLOAD_PROFILE=/mnt/AMPStorage/apps/yt-upload-profile`.
- **systemd unit** `yt-upload.service` (system, `User=ai`, `EnvironmentFile`,
  `Restart=on-failure`); logi → journald.
- Instalacja: `python3 -m venv .venv` → `pip install -r requirements.txt
  fastapi uvicorn` → `playwright install chromium` (host ma GNOME → biblioteki
  systemowe są; ew. `playwright install-deps chromium`).

### 2b. CLIPPYME BACKEND (4 pliki + testy; wzorzec PUBLISH_TARGETS 1:1)

- `storage/config_store.py`: klucz **`UPLOAD_ENGINE`** w `VALID_CONFIG_KEYS`
  (:43) + default `""` w mapie defaultów (:362) + czysta
  **`resolve_upload_engine(env)`** (`""`/garbage → `"n8n-api"`; `"browser"` →
  `"browser"`; host-testowalna).
- `api/schemas.py`: klucz w allow-liście (:186) + walidator (in
  `("", "n8n-api", "browser")` → inaczej 422).
- `jobs/completion_webhook.py`: `build_completion_payload(..., engine=None)` —
  `engine` na poziomie JOBA **tylko gdy == "browser"** (byte-compat, konwencja
  targets); `job_runner` woła `resolve_upload_engine(job_env)` — **snapshot
  dispatch-time** (zmiana GUI w trakcie joba NIE rerouteuje).
- `api/config_routes.py`: NOWY **GET /api/upload-engine/status** (za
  `require_trusted_config_request`): proxy GET `{BROWSER_UPLOAD_SERVICE_URL}/session`
  (env `BROWSER_UPLOAD_SERVICE_URL` + `BROWSER_UPLOAD_SERVICE_TOKEN`, timeout 4 s,
  urllib, **NIGDY nie raise** — `reachable:false` przy błędzie; wzorzec
  ollama/status).
- `.env` (+ **`docker restart clippyme-backend`** — stale-env §6):
  `BROWSER_UPLOAD_SERVICE_URL=http://192.168.100.2:8790`,
  `BROWSER_UPLOAD_SERVICE_TOKEN=<ten sam co serwis>`.
- **`docs/reference/configuration.md` — DODAĆ obie zmienne** (landmine
  docs-test z pkt 21: `test_every_env_var_read_by_the_code_is_documented`).

### 2c. DASHBOARD (2 pliki + testy; GUI-first)

- `client.js`: **`getUploadEngineStatus()`** (never throws, `null` przy błędzie —
  wzorzec getOllamaStatus).
- `settings.jsx` (Automation panel :91): segmented **„Upload engine"** (n8n API /
  Browser (Playwright)) → `saveKeys({UPLOAD_ENGINE})` (reuse Segmented z Ranking
  engine); status line „Browser session: online/offline · queue: N" (check przy
  otwarciu Settings); **warning** gdy engine=browser a `!reachable ||
  !logged_in` (+hint: `ssh -X ai@192.168.100.2` → first_login.py).
- `settings.test.jsx`: +3 (render segmented z configu, persist pick, warning
  browser+offline).

### 2d. N8N WORKFLOW v4 (ten sam ID `LpORWh7hK3bmiHI3`)

- Webhook → „Filter clips" (bez zmian) → NOWY Code **„Route by engine"**:
  `const eng = ((raw.body||raw).engine || '').toLowerCase(); return eng==='browser'
  ? items : [];` — pusty output = gałąź legacy śpi (keep-gate pattern; **NIE
  Switch/IF v2**).
- **Fan-out = JEDEN wpis connections** (pułapka noc #7 — `dict.update` nadpisuje!):
  `"Route by engine": {"main": [[{node: Keep youtube-default…}, {node: Build
  browser payload…}]]}`.
- Gałąź browser: Code „Build browser payload" (video_path z `job_id`+`filename`
  z payloadu; `const BROWSER_UPLOAD_PRIVACY='public'`; title slice 100;
  description `#shorts\n`+desc) → HTTP Request **POST /upload** (header
  `X-Upload-Token` jako credential Header Auth; timeout 900 s).
- Po PUT: **GET + sprawdź parametry WSZYSTKICH nodów** (lekcja pkt 21) + mirror
  JSON sync + **POST activate** (PUT dezaktywuje).
- **v2 (OSOBNO, po walidacji v1):** error-output YT node → gałąź browser jako
  fallback przy `uploadLimitExceeded`.

---

## 3. PUŁAPKI

- **Uploader sam = NIE zweryfikowany E2E** — plan zakłada *smoke-first* (§5 pkt 1):
  pierwszy unlisted upload + poprawki selektorów ZANIM cokolwiek pójdzie w n8n.
- **Serial uploads**: Studio ma jeden dialog → serwis ma 1 workera; równoległe
  POST /upload czekają w kolejce (503 przy >8 — n8n i tak dostaje klipy sekwencyjnie
  przy MAX_CONCURRENT_JOBS=1, ale webhooki mogą przyjść naraz).
- **1 profil = 1 kanał** (spójne z decyzją usera: jedno konto Google; multi-kanał
  v2 = mapowanie target→profile_dir w .env serwisu + drugi login).
- Nazwy plików ze **spacjami/em-dash** → JSON body, nie shell (sonda: READ_OK na
  pliku z „ — part 1_").
- **LAN IP nie 127.0.0.1** (webhook trap §6) — URL serwisu = 192.168.100.2:8790.
- Engine = **snapshot at dispatch** (jak targets) — spójne z filozofią job env.
- `.env` zmiany → `docker restart clippyme-backend`; docs-test landmine (pkt 21).
- Bot-detection: sesja TYLKO z realnego loginu (nigdy „świeży" headless); przy
  problemach headless → `xvfb-run -a`; przez pierwszy tydzień wołać unlisted
  (BG: przy `privacy=public` od razu ryzyko review flagów rośnie).

---

## 4. TESTY (house style)

1. **Backend unit**: `resolve_upload_engine` (round-trip/garbage→n8n-api), 422
   walidator, payload: `engine` obecny TYLKO przy browser (byte-legacy przy
   default), proxy (mock serwisu: ok/unreachable/timeout).
2. **Frontend**: +3 (wyżej).
3. **Live smoke uploader (PRZED resztą!)**: `ssh -X` login → unlisted upload
   realnym klipem z `output/` → verify w Studio → poprawki selektorów wg
   `StageError.stage`.
4. **E2E serwisu**: curl POST /upload realnym klipem → `200 {video_id, url}`;
   GET /session → `logged_in:true`; GET /api/upload-engine/status (token) →
   `reachable:true`.
5. **E2E całości (GUI)**: flip engine w GUI → readback config → realny job
   score ≥85 → klip wylatuje przez przeglądarkę (journald serwisu + video w
   Studio) → flip back → legacy payload (exec n8n: gałąź browser śpi).
6. **Rollback**: `UPLOAD_ENGINE` clear w GUI (albo `POST /api/config` z `""`) →
   payload bez engine → v3 zachowanie 1:1. Serwis/unit może zostać (martwy).

---

## 5. KOLEJNOŚĆ + NAKŁAD

1. **Smoke uploader** (login ssh -X + unlisted + selektor-fixes): ~1 h ← **BLOKADA CAŁOŚCI**
2. Host serwis + systemd + login headless verify: ~2 h
3. Backend (config+payload+proxy+docs): ~1,5 h + testy
4. GUI: ~1 h + testy
5. n8n v4: ~1 h
6. E2E live całości: ~1 h
   (v2 quota-fallback: +2 h po walidacji v1)

## 6. CO NIE JEST W ZAKRESIE / OTWARTE

- credential #2 / `ENABLE_PL_ROUTE` — osobny wątek usera (nie blokuje: gałąź
  browser działa wg PROFILU przeglądarki = kanał #1, tak jak dziś legacy).
- Multi-channel profiles v2 (mapowanie targets→profile).
- Per-clip engine override — nie planowane (engine = decyzja globalna GUI).
- Zernio publish path (`/api/publish`) — nietknięte.
