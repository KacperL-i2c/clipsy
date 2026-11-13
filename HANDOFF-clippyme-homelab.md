# HANDOFF — ClippyMe (fully local) na serwerze `homelab` (192.168.100.2)

> **ZASADA OBOWIĄZUJĄCA OD 2026-11-08 (wieczór): KAŻDA zmiana w ClippyMe musi
> wspierać GUI (dashboard).** Żadna nowa funkcja / flaga / przełącznik nie może
> kończyć się na edycji `.env` + `docker restart` — musi mieć swoje UI w
> Settings (persisted setting przez `POST /api/config` → `data/config.json`,
> mechanizm `merge_persistent_config` aplikuje per-job BEZ restartu) albo inny
> widoczny odpowiednik w dashboardzie. Backend-only zmiany (np. wewnętrzne
> naprawy pipeline'u) są OK, ale wszystko co konfigurowalne / przełączalne /
> widoczne dla użytkownika → GUI first. Patrz wzorzec: przełącznik
> Local↔Gemini (§7 pkt 7 → zrobione, §3 pkt 13).

> Data: 2026-11-08→11 (8 sesji) · Ostatnia sesja (wieczór #8, 2026-11-11):
> **n8n fix tytułów (v3-regresja) + PL-routing OFF (jedno konto Google) + FULL
> AUTOMATION „schleuder" (§7 pkt 12): zrobione i przetestowane E2E + GUI.
> Scheduler DISABLED — user ustawia query/godziny w Discover. YT quota hit
> (user: posprzątać dzisiejsze uploady).**
> Ten dokument pozwala nowej sesji kontynuować bez utraty kontekstu.
> Świeżość (koniec noc #6): clippyme-backend/frontend healthy, n8n Up (2.46.6, dual-bind
> 192.168.100.2+127.0.0.1 :5678), workflow AKTYWNY, CALLBACK_WEBHOOK_URL → n8n potwierdzony
> GET /api/config, RANKING_PROVIDER=gemini nietknięty. n8n API key = §8.

---

## 1. Dostęp i poświadczenia

| Co | Wartość |
|---|---|
| SSH | `ssh ai@192.168.100.2` (klucz działa, BatchMode OK) — **używaj TYLKO konta `ai`** |
| Hasło sudo (usera `ai`) | `stbr` (4 znaki — SLABE, rekomendowane `passwd ai` przez użytkownika) |
| Wzorzec sudo przez ssh | `ssh ai@... 'echo "stbr" | sudo -S -p "" bash -c "..."'` |
| Dashboard ClippyMe | `http://192.168.100.2:5175` |
| Backend API | `http://192.168.100.2:8000` (OpenAPI: `/docs`, `/openapi.json`) |
| CLIPPYME_API_TOKEN | `096785f69980af041bfee3ccb674e419` (nagłówek `X-API-Token`; w przeglądarce: Settings → „API token") |
| Dummy klucz Gemini w przeglądarce | `local-no-key` (frontend wymaga niepustego pola; backend ignoruje) |
| Przeglądarka — pamięć | token i gemini-key siedzą w localStorage przeglądarki użytkownika |

**Ważne kontekstowo:** serwer to homelab użytkownika (MACHINIST X99, Xeon E5-2680 v3, 24C/48T, 15.4GB RAM, Ubuntu 24.04, pulpit GNOME). Na nim działają też: NextCloud AIO (docker), Home Assistant, ESPHome, Caddy, printago-fuse, AMP + 2 serwery Minecraft (natywne, user `amp`). Reboot = wywala graczy MC + przestawia NextCloud na ~2-3 min.

---

## 2. Architektura (stan na koniec sesji)

```
YouTube/upload ──▶ ClippyMe (docker: clippyme-backend + clippyme-frontend, GPU image)
                   ├─ transkrypcja: Faster-Whisper medium na GPU (CUDA) ✅
                   ├─ ranking momentów: Ollama qwen3:4b-instruct na GPU (PATCH, patrz §4) ✅
                   │    └─ długie wideo (>~12 min): CHUNKED map-reduce po oknach
                   │       (450 rzędów/okno, patrz §9 — zimplementowane, §3 pkt 12) ✅
                   │    └─ provider: Local↔Gemini przełącznik w GUI (§3 pkt 13) ✅
                   ├─ fallback rankingu: qwen2.5:3b (chain w shimie), potem TextTiling
                   ├─ reframe: YOLOv8/MediaPipe na GPU ✅
                   ├─ auto-napisy: karaoke burn po każdym klipie, IN-PLACE
                   │    (SUBTITLES_AUTO/SUBTITLE_PRESET, default ON; §3 pkt 14) ✅
                   ├─ panel „Active jobs": podgląd + kontrola WSZYSTKICH jobów
                   │    serwera cross-session (GET /api/jobs/active; §3 pkt 15) ✅
                   └─ brak jakiegokolwiek API chmurowego w transkrypcji/reframie
                      (Gemini/Deepgram opcjonalne przez GUI; NIE są wymagane)
Ollama 0.40.15 (systemd, host, port 11434 na 0.0.0.0)
GPU: NVIDIA RTX 2060 6GB (driver 595.99.02, CUDA 13.2, nvidia-container-toolkit)
Repo ClippyMe: /mnt/AMPStorage/apps/clippyme  (bind-mount .:/app do kontenera → patche live bez rebuildu!)
n8n: ZAINSTALOWANY (2026-11-08 noc #6): kontener `n8n` 2.46.6, porty 192.168.100.2:5678 + 127.0.0.1:5678,
     volume /mnt/AMPStorage/apps/n8n (SQLite — trwały), workflow „ClippyMe → YouTube Shorts" AKTYWNY
     (webhook receiver + filtr score≥85 + download + YT upload; YT OAuth credential = placeholder, patrz §3 pkt 18;
     docs: clippyme-n8n-integracja.md — zaktualizowany, lustrzany JSON workflow obok handoffu)
```

 modele w Ollama (po sprzątaniu 2026-11-08 pm): **qwen3:4b-instruct (aktywny)**, qwen2.5:3b (fallback), gemma3:1b — razem 4,9G.

---

## 3. Co zrobiono (skrót chronologiczny)

1. Konto `ai` (uid 1004, grupa sudo, klucz SSH = klucz grejema).
2. Sprzęt: wykryto RTX 2060 → driver `nvidia-driver-595-open` + reboot → `nvidia-container-toolkit` + `daemon.json` (runtime nvidia) → reboot.
3. ClippyMe: clone do `/mnt/AMPStorage/apps/clippyme`, `.env` (whisper, LAN bind, token), build `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d`. Obraz ~12GB — UWAGA: root disk był przy tym przy 96-99%.
4. Patch lokalnego LLM (§4) + Ollama setup (systemd override: `OLLAMA_HOST=0.0.0.0`, `OLLAMA_KEEP_ALIVE=1m`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`).
5. Upgrade Ollama 0.13.0 → **0.40.15** (nowy silnik naprawił qwen3: `ollama pull` + `/tmp/ollama_install.sh` jako root).
6. yt-dlp w kontenerze: runtime upgrade 2026.07.04 → **2026.10.26** (`docker exec clippyme-backend pip install -U yt-dlp`) — **nie-trwałe** (zniknie przy recreate/rebuild kontenera).
7. Test E2E przeszedł w 100% lokalnie: score 87, polski/włoski tytuł AI, hook, render 9:16.
8. Reboot #3 (użytkownik zaakceptował) — odblokowanie zawieszonego drivera GPU (patrz §6 „GPU wedge").
9. **Sesja 2026-11-08 (popołudnie): FIX rankingu lokalnego LLM.** Job `bdf39dfe` przeszedł, ALE fallback TextTiling: qwen3 zwrócił poprawny JSON, jednak klipy 5.0s i 4.1s były ZA KRÓTKIE — `ViralClip` wymaga duration 10-75s → validate_and_dedupe je wyrzucał → score 0, tytuł „part 1". Naprawa: `local_llm.py` — nowa funkcja `_salvage_clip()` + `_video_duration_from_prompt()` (czyta `VIDEO_DURATION_SECONDS:` z promptu): rozszerza krótkie klipy do ≥10s (najpierw end, potem start, clamp do długości wideo), przycina >75s, naprawia start>end, clampuje score 1-100 (int), viral_reason ≥20 znaków, tytuł ≤110, hook ≤160. Test E2E po naprawie (job `196b2979`): **3 klipy, score 92/90/89, włoskie tytuły AI, ścieżka strict, zero dropów** ✅. UWAGA: API wymaga nagłówka `X-Gemini-Key` (dummy `local-no-key`) oprócz `X-API-Token` — ważne dla n8n.
10. **Sesja 2026-11-08 (popołudnie): FIX YOLO/curl-23 przy reframie.** Pierwszy długi job (12 klipów, „Zakochałem się…🇨🇷") — klipy 1-4 padły na `YOLO('yolov8n.pt')`: ultralytics próbował downloadu do `/app`, a backend działa jako uid 996 bez prawa zapisu do roota repo (curl 23 = EACCES; detale w §6). Fix: `yolov8n.pt` położony w `/app/yolov8n.pt` → klipy 5+ renderują się poprawnie (face tracking, 9:16). Klipy 1-4 do ewentualnego odtworzenia po zakończeniu joba. → **ODTWORZONE (2026-11-08 wieczór, patrz §3 pkt 11).**
11. **Sesja 2026-11-08 (wieczór): FIX „files don't exist" przy downloadzie klipów.** Objaw: po zakończeniu joba `9d84798e` (12 klipów Costa Rica) frontend nie mógł pobrać ŻADNEGO klipu — `/videos/...` 404. Przyczyna: `clip_filename_for()` w `src/clippyme/clips/clip_resolve.py` odrzucał poprawne `clip_filename` z metadanych przez naive check `".." not in raw` — tytuł filmu „Zakochałem się w nim... 🇨🇷" zawiera `...`, a `".." in "..."` = True → path-traversal guard false-positive → fallback do pozycyjnej nazwy `{base}_clip_{N}.mp4` (bez tytułu klipa), której NIE MA na dysku (pipeline zapisuje `{tytuł_klipa}_clip_{N}.mp4`). Fix: check zmieniony na `raw not in (".", "..")` (separatory `/` `\` i tak zabronione, więc komponent == `.`/`..` to jedyna realna zagrożenie). Dotyczy KAŻDEGO filmu z `...` w tytule. Po fixie: `docker restart clippyme-backend` → `/api/history` zwraca video_url zgodne z dyskiem, downloady 200 OK. UWAGA: `/api/status/{id}` po restarcie zwraca 404 „Job not found" dla WSZYSTKICH jobów — to NORMALNE (in-memory `jobs` dict żyje tylko w życiu procesu; frontend po restarcie używa `/api/history`, który skanuje dysk). Klipy 1-4 (YOLO pad) odtworzone przez POST `/api/reframe/{job}/{clip_index}` `{"reframe_mode":"auto"}` (~6.5 min/klip, wymaga `X-API-Token`, source_* slices + yolov8n.pt na miejscu).
12. **Sesja 2026-11-08 (wieczór): IMPLEMENTACJA chunked rankingu (§9) — GOTOWA I PRZETESTOWANA.** Zmiany w 3 plikach (+228/-31, git diff potwierdza): `gemini_request.py` (WINDOW_HEADER_TEMPLATE, `encode_words_toon_window` 1-decimal, `plan_windows` 450/60 z glue ogona, `build_viral_prompt_window`, `estimate_tokens_for()` — **komponentowy estymator tok** (4400 template + 17.7/row + 0.68/char) zamiast planowego chars×0.68 — ten zawyżał template 2.4× i MISROUTOWAŁ krótkie wideo do chunked; `estimate_prompt_tokens` (chars×0.68) zostawiony dla kompatybilności), `local_llm.py` (WINDOW_SCHEMA minItems=1, `generate_chunked` — retry per okno, usage sum, >50% fail → raise → TextTiling, `_clamp_clip_to_window` — **zwraca bool: klip w całości poza oknem = HALLUCYNACJA → DROP** (smoke test wykrył model kopiujący czasy przykładów z template), `_merge_window_clips` IoU>0.35 + top-K, fix hook==title (pierwsze 6 słów reason) w `_salvage_clip`, `_generate(schema=, num_predict=)` + OOM-rekursja przenosi parametry), `main.py` (gate isinstance+threshold; **FIX podczas testów: brakujący `creator=` w wywołaniu generate_chunked** (NameError → TextTiling na 27s) + **THRESHOLD 6000→8000** — realny 27s transkrypt (80 słów) = est 6092 > 6000 i szedł błędnie w chunked; 8000 daje margines, single-shot bezpieczny do ~160 rzędów ≈ 9.7k tok realnych < 16384 ctx). Testy §9.5: **(1) offline unit 33/33** (plan_windows na realnych 6852 rzędach → 18 okien, budget/contiguity/overlap; estymaty; merge/clamp/salvage/parse; fake-client E2E: retry ratuje puste okno, dead-window skip, >50% raise). **(2) smoke 1 okna w kontenerze** — 13114 tok prompt < 16384, 25.3s, 3 klipy. **(3) pełny ranking realnego 55-min transkryptu w kontenerze** — 18/18 okien ×~30s = 534s, 53 klipy → merge 8, parse strict, wszystkie dur 10-75s, score 95×8 (jednolite high-score = znane zachowanie 4B), VRAM peak **3939 MiB** ✅. **(4) regresja 27s (re-upload cache'owanego pliku `uploads/196b2979*.mp4`, job `a4161a0a`)** — single-shot path potwierdzony (input=5246 tok, brak logów chunked), **score 87** (= referencja 87-92 z joba `196b2979`), włoski tytuł bez miksów, klip 16.7s wyrenderowany ✅. **(5) VRAM** — 3939 MiB peak < 5.5 GB target. Tytuły miks PL/IT na długim wideo = znane ograniczenie §9.7 (akceptowane v1). **Rezydualne:** pełny E2E z renderem klipów na długim wideo do wykonania przy najbliższym prawdziwym long-form uploadzie (źródło Costa Rica usunięte z dysku — tylko ranking-stage zwalidowany na realnym transkrypcie; loop renderu bez zmian, dowiady z 12-clip joba). Backend zrestartowany po deployu; .env ma nowe zmienne (THRESHOLD=8000, NUM_CTX=16384, WINDOW_ROWS=450, OVERLAP=60, CHUNK_TOPK=3, FINAL_TOPK=8, CHUNK_RETRIES=1).

13. **Sesja 2026-11-08 (wieczór/noc): PRZEŁĄCZNIK Local LLM ↔ Gemini — ZROBIONY (backend + GUI), patrz §7 pkt 7.** Motywacja: jakość copy 4B < Gemini (§9.7 pkt 4) — przełącznik = escape hatch jakości, dostępny z dashboardu bez ssh/restartu.
    - **Backend (4 pliki):** `storage/config_store.py` — nowy persisted key **`RANKING_PROVIDER`** (`local`|`gemini`|empty=auto) w `VALID_CONFIG_KEYS` + nowa czysta funkcja **`resolve_ranking_provider(env)`** (empty/garbage → auto: `local` gdy `LOCAL_LLM_BASE_URL` ustawione, inaczej `gemini` — zachowuje legacy behavior; host-testowalna, używana identycznie przez pipeline i API). `api/schemas.py` — key w allow-liście + walidacja wartości (422 przy złej). `pipeline/main.py` (`get_viral_clips`) — provider z `resolve_ranking_provider(os.environ)`; gałąź **local** czyści VRAM Whispera (jak dotychczas), gałąź **gemini** NIE czyści (brak kontencji GPU z chmurą), ostrzega+fallback gdy `local` bez `LOCAL_LLM_BASE_URL`. `api/config_routes.py` — nowy endpoint **`GET /api/config/ollama/status`**: server-side health-check (`?check=true` → GET `LOCAL_LLM_BASE_URL/api/tags`, timeout 4s, zwraca reachable+models+model+effective_provider; bez check = tani odczyt configu — używa go App do guarda). Endpoint za `require_trusted_config_request` (Origin/X-API-Token).
    - **Frontend (5 plików):** `api/client.js` — `getOllamaStatus(check)` (never throws). `components/icon.jsx` — nowe ikony `cpu`/`activity`/`cloud`. `features/settings/settings.jsx` — nowy wiersz **„Ranking engine"** (Segmented Local (Ollama) / Cloud (Gemini), zapis przez `saveKeys({RANKING_PROVIDER})` → działa per-job bez restartu) + panel „Ollama status · model" (badge online/offline, przycisk Check, baza + liczba modeli) + hard-warning przy `gemini` gdy klucz w przeglądarce jest pusty/dummy `local-no-key` (cichy TextTiling!) + hint o kosztach chmury + warning gdy local a Ollama nie odpowiada / nie skonfigurowana. `hooks/useJobSubmission.js` — guard: przy `rankingProvider==='gemini'` dummy `local-no-key` otwiera modal „Add your Gemini key" (przy local dummy jest OK). `app/App.jsx` — pobiera `effective_provider` przy starcie (`getOllamaStatus()` bez check — tani), podaje do `useJobSubmission` + `onRankingProviderChange` do SettingsView (live sync guarda).
    - **Kluczowe odkrycie:** `LOCAL_LLM_*` NIE są w env kontenera (compose ich nie przekazuje) — `load_dotenv()` w `app.py`/`main.py` ładuje `.env` do procesu API przy starcie (stąd `docker exec env` ich nie pokaże!); job env = kopia os.environ API + overlay config.json at dispatch → **zmiana Settings działa dla następnego joba BEZ restartu** (ten sam mechanizm co TRANSCRIPTION_PROVIDER). UWAGA: `GEMINI_MODEL` z env kontenera (qwen2.5:7b) NIE jest nadpisywany przez dotenv (override=False) — ale shim i tak wymusza `LOCAL_LLM_MODEL` (qwen3) — kosmetyczne.
    - **Testy:** (1) backend unit w kontenerze: `pytest tests/storage/test_config_store.py tests/api/test_config_routes.py` → **42/42** (uwaga: uruchamiać z `-e CLIPPYME_API_TOKEN=` bo dotenv ładuje token z .env → 401 w testach zaufanych tras; pytest zainstalowany pip-em w kontenerze = **nie-trwałe przy recreate**). (2) frontend: `docker exec clippyme-frontend npm test` → **359/367** (+13 nowych testów settings: switch save/warnings/auto-default; 8 FAIL to **pre-existing/environmental** fontowe testy `usWeightClass` na TTF — nie związane z żadną sesją; pułapka: `vi.clearAllMocks()` NIE resetuje `mockResolvedValue` → leak implementacji między testami). (3) regresja E2E 27s (re-upload `uploads/196b2979*.mp4`, job `79693156`): **completed 45s, score 92, ścieżka 🦙 local, VRAM freed** ✅. (4) **GUI zweryfikowane w przeglądarce** (screenshots): switch Local↔Gemini klika się, zapisuje (config.json), badge ONLINE z live probe, warningi appear/disappear zgodnie z trybem, toast „Saved". (5) round-trip API: POST gemini → effective gemini → POST local → effective local; invalid wartość → 422.
    - **Rollback:** kopie oryginalnych plików w `/mnt/AMPStorage/apps/clippyme/.backup-20261108-ranking-switch/` (12 plików; **NIE używać `git checkout` na main.py** — carryje patche chunked z §3 pkt 12!). Finalny stan: `data/config.json` ma `RANKING_PROVIDER: "local"` (explicit).
    - **Frontend bez rebuildu:** kontener `clippyme-frontend` = **Vite dev server z bind-mount `./dashboard:/app`** → zmiany GUI są live przez HMR (Dockerfile.prod/nginx to tylko opt-in ścieżka produkcyjna — przy przejściu na prod pamiętać o `docker compose -f ... -f docker-compose.prod.yml build frontend`).

    - **Log-clarity fix (2026-11-08, po pytaniu usera „czy to używa Gemini?"):** stare logi w trybie local mogę mylić — `(model: gemini-3.5-flash)` to był kosmetyczny print `GEMINI_MODEL` (Settings dropdown zapisuje go do config.json; shim go IGNORUJE — wymusza `LOCAL_LLM_MODEL`), a `Initializing Gemini with model chain...` to chain używany TYLKO przez gałąź chmurową. Dodatkowo single-shot path wypisywała fikcyjny koszt chmurowy (`cost=$0.009867` dla lokalnego callu). Po naprawie logi local są zgodne z prawdą: `Analyzing transcript — ranking engine: local Ollama...` → `Local LLM mode: ... (model: qwen3:4b-instruct)` → `Local model chain: qwen3 (fallback: qwen2.5) → http://...:11434` → `Token Usage (qwen3:4b-instruct) ... cost=unknown`. **Regresja po naprawie: 2× E2E 27s (jobs `833b533a`, `5b391888`) completed, score OK, ścieżka 🦙.** UWAGA: `GEMINI_MODEL` w config.json (dropdown) dotyczy TYLKO trybu gemini — zmiana modelu LOKALNEGO = `.env LOCAL_LLM_MODEL` + restart (§4). Bonus: user wpisał PRAWDZIWY klucz Gemini do Settings (config.json `GEMINI_API_KEY: AQ.Ab8RN6...`) + dropdown `gemini-3.5-flash` — tryb Cloud jest teraz w pełni funkcjonalny (będzie płatny per token).

14. **Sesja 2026-11-08 (noc #2): AUTO-NAPISY (§7 pkt 8) — ZROBIONE I PRZETESTOWANE E2E + GUI.** Klip z downloadu ma wypalone karaoke napisy automatycznie, zero ręcznych klików. Domyślnie ON.
    - **KLUCZOWE ODKRYCIE (koryguje spec §7 pkt 8):** punkt zaczepienia z handoffu („main.py ~:1056-1065") to LEGACY/ŚCIEŻKA CLI — realny job renderuje przez **`pipeline/orchestrator.py` `_render_one_clip`** (~:636, po `legacy.select_cover_frame(clip_final)`, przed `clip["qa"] = last_report` + printem `✅ Clip i/total ready`). Patch jest w OBU miejscach (main.py loop :1067-1077 dla CLI + orchestrator dla jobów), żeby nie rozjechać zachowań.
    - **Shared helper:** `editing/subtitles.py::auto_burn_subtitles_inplace(clip_path, transcript, clip_start, clip_end, env=None)` — czyta settings przez `resolve_subtitle_settings`, `generate_ass_karaoke(preset)` → `burn_subtitles` do `<clip>.subtmp.mp4` → `os.replace` IN-PLACE (ten sam `clip_filename` — historia/video_url bez zmian), `finally` sprząta `.auto.ass` + tmp. Zwraca bool (False = skip: auto off / brak transkryptu / brak słów w zakresie). Błędy propagują — caller loguje i kontynuuje (klip już wyrenderowany).
    - **Settings (proven pattern z przełącznika rankingu, kopiuj 1:1):** `storage/config_store.py` — nowe klucze **`SUBTITLES_AUTO`** (`"1"`/`"0"`, empty=default ON) + **`SUBTITLE_PRESET`** (klucz z `SUBTITLE_PRESETS`, empty=default classic_white) w `VALID_CONFIG_KEYS` + `load_persistent_config` + nowa czysta funkcja **`resolve_subtitle_settings(env)`** (lazy import SUBTITLE_PRESETS — storage nie ciągnie editing stacku; garbage preset → None, garbage auto → ON). `api/schemas.py` — allow-list + walidacja (`SUBTITLES_AUTO` in ("","0","1"); `SUBTITLE_PRESET` musi być kluczem z SUBTITLE_PRESETS → 422). Aplikacja per-job przez `merge_persistent_config` (job env overlay at dispatch) → **zmiana w GUI działa dla następnego joba BEZ restartu**.
    - **Reframe re-burn:** `clips/reframe_service.py` — po sukcesie subprocessu (wewnątrz `clip_lock`): re-burn przez `auto_burn_subtitles_inplace(target_path, data.get("transcript"), clip_data start/end, reframe_env)` w `asyncio.to_thread`. Log: `Auto-subtitles re-burned onto reframed clip ...`. Failure = log error, reframe i tak sukces (klip już przereenderowany). Bez tego klip po reframe straciłby napisy (pułapka (b) ze spec).
    - **Frontend (Settings — GUI first):** nowy Panel **„Captions"** (między API keys a Publishing): wiersz „Auto-napisy" (Switch `label="Auto-napisy"`, zapis `saveKeys({SUBTITLES_AUTO})`) + grid 6 presetów z mini-podglądami (reuse `SUBTITLE_PRESETS` z `lib/uiOptions.js` + globalne klasy `subgrid`/`subpre` — preview fonts z pariety testowanej backendem) + hint „Classic is the server default…". Grid disabled+przygaszony gdy auto OFF. Empty preset → UI pokazuje Classic jako selected („(subsPreset || 'classic_white')").
    - **Testy:** (1) backend unit: **44/44** (`test_config_store.py` + `test_config_routes.py`; +2 nowe: resolve round-trip/auto-off-flavors/garbage-preset + POST round-trip/422/clear); full editing suite napisów **314 passed** (regresja subtitles.py). (2) frontend: **17/17 settings.test.jsx** (+4 nowe: default ON/Classic, toggle persist, persisted=0 dim grid, preset click persist); full suite 363/371 (8 FAIL = znane fontowe `usWeightClass`, baseline z §3 pkt 13). (3) **E2E 27s auto ON (job `c6d5b2a2`)**: completed, log `💬 Auto-subtitles burned into clip`, klatka z klipu potwierdza karaoke caption (biały + żółty highlight, czarny outline) ✅. (4) **E2E reframe (ten job, clip 0 → disabled)**: log `Auto-subtitles re-burned onto reframed clip`, klatka = letterbox + napisy przetrwały ✅ (~2 min dla 12s klipa). (5) **E2E auto OFF (job `e1dc7cd6`)**: brak linii burn, klatka czysta — stare zachowanie ✅. (6) **GUI live w przeglądarce** (screenshots): panel renderuje, switch ON/OFF zapisuje (backend potwierdzony GET po każdym kliku), preset click zapisuje, disabled grid przy OFF ✅.
    - **Stan końcowy config.json:** `SUBTITLES_AUTO: "1"`, `SUBTITLE_PRESET: "classic_white"`, `RANKING_PROVIDER: "gemini"` (przywrócony stan usera — user przełączył na Cloud przez GUI po poprzedniej sesji; NADPISUJE info z pkt 13 o „final local"). E2E testy robiły tymczasowo local, przywrócone.
    - **Caveat v1 (akceptowany w spec):** ręczny Compose na klipie z auto-napisami dorysuje drugą warstwę napisów NA WIERZCHU (compose działa na `clip_filename`; brak dedup). W praktyce: używać compose świadomie albo wyłączyć auto przed ręcznym compose per klip.
    - **Drobiazg środowiskowy:** `data/config.json` NIE jest czytelny dla usera `ai` bezpośrednio (owner = uid kontenera, 0600) — czytać przez `GET /api/config` (token), nie przez cat/scp.

15. **Sesja 2026-11-08 (noc #3): PANEL „ACTIVE JOBS" (§7 pkt 9) — ZROBIONY I PRZETESTOWANY E2E + GUI.** Job wysłany z innego urządzenia/przeglądarki jest widoczny na żywo w dashboardzie (stage/progress/ETA/logi) i sterowalny z panelu; na tabie History pulsuje badge z liczbą aktywnych.    - **Backend (2 pliki + testy):** NOWY moduł `jobs/active_jobs.py` — czysta funkcja `active_job_summaries(jobs, *, now=None, queue_order=(), grace_seconds=120, log_tail_lines=8)`: **whitelist pól** (job_id, status, attempt/max_attempts, stage, progress, detail, eta_seconds, updated_at, label, label_type, log_tail, queue_position) — NIGDY env/argv/handle procesu/ścieżki (test asercją na payloadzie); statusy z `ACTIVE_STATES` (job_control: queued/processing/paused) + finished w **grace 120 s** od `operations.updated_at` (żeby panel nie mrugał); label z argv (token http/https) albo basename(`input_path`); sort: in-flight najpierw (processing/paused wg świeżości), potem kolejka FIFO (`queue_position` = indeks w `job_queue._queue`, czytane defensywnie), finished na końcu. `api/app.py` — endpoint **`GET /api/jobs/active`** za `require_trusted_config_request`, bez rate-limitu (konsekwentnie z filozofią „status polling intentionally NOT limited" w security.py).
    - **Frontend (GUI first):** `api/client.js` — `getActiveJobs()` (zwraca **null** przy błędzie — „offline" ≠ „pusto", panel nie znika przez chwilowy zanik sieci); NOWY hook `hooks/useActiveJobs.js` — poll **4 s gdy coś działa / 15 s heartbeat gdy pusto** (heartbeaten po to, by job z innego urządzenia zapalił badge), nie rzuca, serwer = jedyne źródło prawdy (nic do localStorage); NOWY komponent `features/active-jobs/activeJobs.jsx` — panel nad listą historii: wiersz = label (icon globe/file) + badge statusu (RUNNING/DONE/paused/queued…, mapa STATUS_BADGE) + słowo stage (mapa STAGE_WORDS jak w stepperze) + ETA (`~N min left`) + relTime od updated_at + **pasek postępu** (reuse `.pbar-wrap/.pbar/.pbar-pct`) + rozwijalny log tail (`<details>`) + **kontrolki inline** (Pause/Resume/Stop & keep/Discard — te same endpointy co ProcessingView; Open tylko dla finished); `currentJobId` oznacza wiersz badge'em „this browser"; klik wiersza: running → **attach** do ProcessingView (`setJobId`+status processing+tab create), finished → **ścieżka historii** (`restoreJob` z dysku → widok wyników). `components/headers.jsx` — TopNav przyjmuje `activeCount` → badge **`.ajbadge`** na tabie History (animacja `blink` z app.css, pulsuje), znika przy 0. CSS dopisany na KOŃCU `styles/app.css` (`.ajrow/.ajbadge/.ajlog/…`, EOL LF).
    - **Testy:** backend **7/7** (NOWY `tests/api/test_active_jobs_api.py`: whitelist + no-leaks, FIFO positions, grace on/off, paused listed, 403 cross-site/untrusted) + regresja **371 passed** (tests/api + tests/jobs — app.py zmieniany). Frontend **12/12** nowe (hook: cadence busy 4 s/idle 15 s, offline keeps rows; panel: render/kontrolki z job_id/Open/attach/offline/this-browser); full suite **375 passed / 8 FAIL** = niezmieniony baseline fontowy (`usWeightClass`, §3 pkt 13). UWAGA przy fake timers: `waitFor` nie działa z `vi.useFakeTimers` (jego wewnętrzny setTimeout nigdy nie odpala) — używać `act` + `advanceTimersByTimeAsync`.
    - **E2E + GUI (żywe, przeglądarka opencode na 192.168.100.2:5175):** (1) job wysłany curl-em (symulacja innego urządzenia) → widoczny w panelu przeglądarki **BEZ lokalnej historii** (kluczowy scenariusz!); (2) badge „1" na History (zweryfikowany geometrycznie: 16×16 px, visible); (3) RUNNING 52→70% z ETA „<1 min left", log tail z rankingu; (4) **Pause kliknięty w panelu → backend `paused` → Resume → `processing`** (potwierdzone `/api/jobs/active` po każdym kliku; UI dogania w ≤1 cykl polla); (5) grace: finished wisi ~2 min i znika (zmierzone); (6) **Open** (finished) → restore z dysku → pełny widok wyników („1 clips ready", score 92); (7) **klik w running wiersz → attach** → ProcessingView („Cutting your clips.") steruje jobem; (8) po zakończeniu wszystkich: badge znika (activeCount=0).
    - **Konfig po testach przywrócona:** `RANKING_PROVIDER=gemini` (stan usera z pkt 14), SUBTITLES bez zmian. W trakcie testów było local.
    - **Pułapki:** (a) po restarcie backendu panel listuje TYLKO to, co żyje w `jobs` dict (requeued queued-joby wracają przez journal — OK); (b) `job_queue._queue` to prywatny atrybut asyncio.Queue — czytany w try/except; (c) nie dodawać tego endpointu do rate-limitów (poll co 4 s = 15 req/min); (d) panel celowo NIE renderuje się gdy lista pusta (zero noise w History).
    - **Rezyduum v2 (opcjonalne, nie blokuje):** klik w `paused` wiersz z innej przeglądarki attachuje (działa jak running), ale brak dedykowanego widoku „queue" dla batcha — zgodnie z planem; `restore_finished_job` dla `failed/cancelled` zwraca 400/404 → toast (Open pokazujemy tylko dla completed/stopped, więc ścieżka nieosiągalna z GUI).
    - **Backup:** `.backup-20261108-active-jobs/` (5 plików: `src/clippyme/api/app.py`, `dashboard/src/api/client.js`, `dashboard/src/components/headers.jsx`, `dashboard/src/app/App.jsx`, `dashboard/src/styles/app.css`).

16. **Sesja 2026-11-08 (wieczór #4): WYBÓR MODELU OLLAMA Z GUI (§7 pkt 10) — ZROBIONY I PRZETESTOWANY E2E + GUI.** Settings → Ranking engine → wiersz **„Local model"**: dropdown z modelami wykrytymi na Ollamie (server-side probe), zapis persisted `LOCAL_LLM_MODEL`, działa per-job BEZ restartu. Opcja „Default (.env)" = empty → fallback do wartości `.env`.
    - **Backend (3 pliki):** `storage/config_store.py` — klucz **`LOCAL_LLM_MODEL`** w `VALID_CONFIG_KEYS` (z komentarzem dlaczego bez env-syncu) + default z env w `load_persistent_config` + **special-case w `save_persistent_config`: ten klucz POMIJANY w synchronizacji os.environ** (pułapka #1 ze spec — generic loop zrobiłby `os.environ.pop` przy empty i zniszczyłby .env default załadowany dotenv-em; a przy non-empty wpisałby pick do procesu API, gdzie przeżyłby późniejszy „Default (.env)" clear — job env to kopia os.environ). GUI value żyje TYLKO w config.json; nakłada je `merge_persistent_config` na job env at dispatch (empty → skip → .env wartość z procesu). **Shim i pipeline: ZERO zmian** (`os.getenv("LOCAL_LLM_MODEL")` czyta job env). `api/schemas.py` — klucz w allow-liście + `LOCAL_LLM_MODEL_RE` (`^[A-Za-z0-9][A-Za-z0-9._:/-]{0,71}$` — format-only, NIE twarda lista: model można pull-nąć później; 422 przy garbage). `api/config_routes.py` — `_ollama_probe` zwraca teraz listę dictów `{name, size, parameter_size}` (VRAM hints z /api/tags; sort PRZENIESIONY do route, bo mocki/mogą zwracać nieposortowane), endpoint `/api/config/ollama/status` zwraca `models` (names, backward-compat) + NOWE `models_detail`, a pole **`model` czyta `load_persistent_config()`** (efektywną wartość config-overlay), nie gołe os.environ — bez tego status nie pokazałby GUI picka (bo ten celowo nie wchodzi do os.environ!).
    - **Frontend (2 pliki):** `settings.jsx` — state `localModel` (+ sync w `refreshConfig` z `c.LOCAL_LLM_MODEL`), computed `ollamaModels`/`localModelDetail`/`localModelGB`, nowy wiersz **„Local model"** za blokiem cloud: select (aria-label „Local model", opcja „Default (.env)" = `""`, off-list pick dodawany do opcji zamiast zniknąć), przycisk Check (reuse `checkOllama`), **dim `opacity: .45` + disabled gdy `effectiveRanking !== 'local'`** (visible-always: można wybrać model zanim przełączy się na Local), warning „Not in the detected Ollama list" gdy pick ∉ models przy reachable, hint „≈ X.X GB on disk — weights over ~3 GB risk VRAM OOM" gdy size > 3 GiB. Wiersz „Ollama status · <model>" pokazuje teraz efektywny model z endpointu. `settings.test.jsx` — **poprawka istniejącego testu**: `getByText(/qwen3:4b-instruct/)` → anchored `/^Ollama status · qwen3:4b-instruct$/` (option w nowym selectcie też matchuje nieanchored regex → „found multiple"). Pill „LOCAL" w top-nav to status online przeglądarki (`Offline/Working/Local`, headers.jsx:26) — NIE ranking provider; nie mylić przy debugu.
    - **Testy:** (1) backend unit: **48/48** (config tests; +1 `test_sync_env_with_persistent_config_never_writes_file` po fixce landmine poniżej) — NOWE: `test_local_llm_model_never_touches_process_env` (pułapka #1: set/clear NIE rusza os.environ, config.json tak), `test_local_llm_model_roundtrip_and_validation` (200/422×3 garbage/clear → GET), `test_ollama_status_model_refers_persisted_overlay` (status model = GUI pick mimo-env default), probe test przepisany na dicty + `models_detail`. Pełna regresja **391/391** z md5-stabilnym config.json. (2) frontend: **21/21** settings (+4: lista wykrytych + persist pick, preselect + off-list warning, dim przy gemini, VRAM hint >3GB); full suite **379 passed / 8 FAIL** = niezmieniony baseline fontowy. (3) **API round-trip live**: POST gemma3:1b → GET gemma3:1b → status model gemma3:1b → POST garbage → 422 → POST "" → GET = qwen3:4b-instruct (.env default). (4) **E2E job (27s cache `uploads/196b2979*.mp4`, job `bc42a366-60da-4258-8f17-2be466bb7d23`)** z `RANKING_PROVIDER=local` + `LOCAL_LLM_MODEL=gemma3:1b`: **completed 106s, score 87, napisy burned, log `Local LLM mode: … (model: gemma3:1b)` + `Local model chain: gemma3:1b (fallback: qwen2.5:3b)` + `Token Usage (gemma3:1b)`** ✅ — GUI pick doszedł do subprocessu z ZERO zmian w shimie. (5) **GUI live w przeglądarce**: select renderuje 3 wykryte modele, disabled+dim przy Cloud, enabled po przełączeniu na Local, pick gemma3:1b → backend potwierdzony GET, „Default (.env)" → config.json bez klucza (fallback .env), powrót na Cloud → znowu dim.
    - **Stan końcowy config.json przywrócony:** `RANKING_PROVIDER: "gemini"`, `LOCAL_LLM_MODEL` BRAK (Default/.env = qwen3:4b-instruct), `SUBTITLES_AUTO: "1"`, `SUBTITLE_PRESET: "classic_white"` (stan usera z pkt 14 nietknięty). Uwaga: gemma3:1b dał score 87 + generyczny tytuł (jak oczekiwane od 1B — jakość < qwen3, §9.7); test był o mechanizmie, nie jakości.
    - **Backup:** `.backup-20261108-model-selector/` (7 plików: `src/clippyme/storage/config_store.py`, `src/clippyme/api/schemas.py`, `src/clippyme/api/config_routes.py`, `tests/storage/test_config_store.py`, `tests/api/test_config_routes.py`, `dashboard/src/features/settings/settings.jsx`, `dashboard/src/features/settings/settings.test.jsx` + `src/api/app.py.importfix` sprzed fixki bootstrapu).
    - **BONUS — ZNALEZIONY I USUNIĘTY LANDMINE (import-time config wipe):** pełna regresja pytest (tests/storage+api+jobs) NISZCZYŁA realny `data/config.json`. Przyczyna: **`app.py` (import-time): `save_persistent_config(load_persistent_config())`** — round-trip nadpisywał plik WIDOKIEM ENV importującego procesu. Każdy proces bez prawdziwych sekretów w env (pytest pod docker exec — env compose/dotenv = dummy `local-no-key`; narzędzia CLI) cicho zamieniał zapisane klucze na swoje wartości („local-only 36B” za pierwszym razem; pełny snapshot z `GEMINI_API_KEY: local-no-key` za drugim — realny klucz Gemini GINE z pliku; to też tłumaczy notki z pkt 14/15 o „config przywrócony po testach”). **Fix:** nowa `config_store.sync_env_with_persistent_config()` — TYLKO env-sync (config.json = source of truth, zero zapisu); w app.py wywołana zamiast round-tripu + `save_persistent_config(...)` tylko gdy config.json NIE istnieje (first-boot bootstrap zachowany 1:1). NOWY test `test_sync_env_with_persistent_config_never_writes_file` (plik nietknięty mimo dryAGING env, env bierze wartość z pliku, LOCAL_LLM_MODEL niesynchronizowany). Dowód: backend **48/48** (config tests), pełna regresja **391/391**, md5 config.json **identyczny przed/po** pełnym suite i po `import clippyme.api.app` w świeżym procesie.
    - **⚠️ SKUTEK UBOCZNY (wymaga akcji USERA):** realny klucz Gemini przetrwał tylko w pamięci procesu API (po restartcie = dummy `local-no-key` w env i pliku; skuteczna wartość CHMUROWA rankingu = dummy → joby spadałyby do TextTiling bez explict re-save). Klucz NADAL jest w localStorage przeglądarki użytkownika (pole Gemini w Settings jest nim pre-filled) — **USER musi otworzyć Settings i kliknąć w pole Gemini (blur auto-save)**, ew. wkleić ponownie. Nic innego na serwerze nie ucierpiało (model/subtitles/provider odtworzone: `RANKING_PROVIDER=gemini`, `GEMINI_MODEL=gemini-3.5-flash`, `SUBTITLES_AUTO=1`, `SUBTITLE_PRESET=classic_white`, brak `LOCAL_LLM_MODEL` = default `.env`).

17. **Sesja 2026-11-08 (noc #5): VIDEO SEARCHER + COMPLETION WEBHOOK (§10) — ZROBIONE I PRZETESTOWANE E2E + GUI.** Dwa nowe feature'y wg requestu usera (searcher API-triggerowany + droga dostarczenia shortsów do n8n); konfiguracja n8n = następny krok (user: LAST).
    - **Feature A — `POST /api/search` (searcher):** NOWY `src/clippyme/integrations/youtube_search.py` — lazy import yt_dlp (host-testable), `extract_flat=True` (metadata-only, 1 request ~5-15s, zero downloadów), popular=`ytsearch{N}:{query}` (sort client-side po view_count desc), newest=`.../results?search_query=...&sp=CAI%3D` (sort po dacie), oversample `min(limit*4, 30)`, filtry duration (min/max s), NA view_count/duration → None (sonda: flat bywa NA), dedupe po video_id, cookies z `_resolve_cookies_path` (reuse download.py). Endpoint w `app.py`: `require_trusted_config_request` + rate-bucket **„search"** (10/30s); **dry_run=true (default) = zero kontaktu z kolejką i NIE wymaga X-Gemini-Key**; dry_run=false → dispatch pętla 1:1 z /api/batch (uuid, OUTPUT_DIR, build_main_cmd, submit_job, QueueFullError→break; **wymaga X-Gemini-Key jak /api/process**) → zero dispatchów = 400 „Queue is full". Config: nowe klucze **`SEARCH_LIMIT`** (1-10, default 3) + **`SEARCH_ORDER`** (popular|newest) + czysty `resolve_search_defaults(env)`; request-parametry nadpisują defaults.
    - **Feature A GUI:** NOWY tab **„Discover"** (`dashboard/src/features/discovery/discovery.jsx`; `headers.jsx` TABS + `icon.jsx` +Search/Webhook z lucide 0.344). Formularz (query/order/limit/min/max duration) → lista `.dvrow` (checkbox, tytuł, kanał, views fmt 1.5M, duration fmt 5:05, link YouTube) → **top-N backendu preselektowane** → „Process selected (N)": 1 → `handleProcess` (attach ProcessingView, setTab create), >1 → `handleBatchProcess` (→ History + Active jobs) — App.jsx `onDiscoveryProcessUrls`, pełny reuse guarda klucza. CSS `.dvform/.dvrow/…` na KOŃCU app.css.
    - **Feature B — completion webhook:** NOWY `src/clippyme/jobs/completion_webhook.py`: `build_completion_payload` (WHITELIST: event/job_id/status/finished_at/clip_count/clips[index,filename,video_url ABSOLUTNE,title,description (tiktok→instagram fallback),viral_score,start,end,duration_s,published] — nigdy env/argv/ścieżki; deleted_after_publish i brak video_url → skip), `post_webhook` (urllib → (ok,code,snippet)), `fire_completion_webhook` (disabled gdy URL pusty; retries 5/30/60s, best-effort, NIGDY nie raise), `notify_job_terminal` (cheap env check → asyncio.create_task+to_thread, referencje w module-level set). Hook: `job_runner.py` `finally` run_job — fire TYLKO gdy `status ∈ TERMINAL_STATES`, PO `_notify()` (journal first); shutdown-CancelledError (status processing) = silent. Config: **`CALLBACK_WEBHOOK_URL`** (empty=off) + **`PUBLIC_BASE_URL`** (empty=relative URLs). NOWY `POST /api/config/webhook/test` (config_routes) — sample payload, timeout 6s, bez retry, zwraca ok/status/response.
    - **Feature B GUI:** Settings → NOWY Panel **„Automation"**: wiersz „Completion webhook" (input URL zapis onBlur, badge set/off, clear-X) + **„Send test event"** (toast sukcesu/błędu) + „Public base URL" + „Discovery defaults" (limit number + Segmented Popular/Newest). `client.js`: `searchVideos` (parsuje detail z błędu), `testWebhook`.
    - **Ranking provider z n8n — JUŻ DZIAŁA (zero zmian):** sonda potwierdziła `POST /api/config {"keys":{"RANKING_PROVIDER":...}}` z samym `X-API-Token` (bez Origin) = 200 → workflow n8n: Set → POST config → dispatch.
    - **Testy:** backend **417 passed** (pełna regresja tests/storage+api+jobs, `-e CLIPPYME_API_TOKEN=`; baseline 391 → +26: NOWE `tests/api/test_search_api.py`, `tests/jobs/test_completion_webhook.py` (whitelist+absolute URLs, lokalny http.server round-trip, retries, runner wiring completed + silent-shutdown), config_store +4 resolve/round-trip). Frontend **391 passed / 8 FAIL = niezmieniony baseline fontowy** (było 379 → +12: discovery.test.jsx 6, settings.test.jsx +6). config.json stabilny po suite (chdir-isolation).
    - **E2E live (real YT, serwer):** (1) search dry_run „memes compilation" popular → realni kandydaci z views/duration, ranking views-desc ✓. (2) dispatch „short comedy skit" → job `78af68b1` **completed** (3-min video, klip z napisami) → webhook odpalił się z DOKŁADNIE zaplanowanym backoffem 4 próby (5/30/60s) — delivery failed TYLKO bo receiver na `127.0.0.1:9999` z perspektywy KONTENERA to kontener (PUŁAPKA: webhook target = host LAN IP). (3) receiver rebound `0.0.0.0:9999` + config URL=`http://192.168.100.2:9999/hook` → `/api/config/webhook/test` → 204 + sample payload z absolutnym video_url dotarł ✓. (4) dispatch newest → job `595c22bb` **completed ~90s** (43s wideo, score 87, włoski tytuł AI, napisy burned) → **webhook DOSTARCZONY**: job_id, clip filename, video_url absolutny (curl 206 = downloadowalny), title/description/viral_score/duration ✓; /api/history spójny z payloadem ✓.
    - **GUI live (przeglądarka opencode):** Discover tab renderuje; seed limit/order z configu ✓; search „italian comedy prank" → „10 found · 3 selected by ranking", top-3 po views preselektowane (4.3M/6.1M/776k), „Process selected (3)" ✓ (screenshot). Settings → Automation: webhook badge „set", **Send test event → delivered** (receiver hit #3) ✓. UWAGA: przeglądarka opencode potrzebowała `localStorage.clippyme_api_token` = SUROWY token string (JSON-wrapped → 401; apiFetch czyta plain string).
    - **Pułapki tej sesji:** (a) webhook target `127.0.0.1` z kontenera = kontener, nie host — zawsze host LAN IP; (b) `pkill -f webhook_recv.py` przez ssh zabija WŁASNY remote command (match na cmdline); (c) YT search wyniki variable między wywołaniami — response `candidates` = kolejność ekstrakcji, `selected` = ranked; nie porównywać 1:1 między callami; (d) Segmented klik na już-aktywną opcję = no-op (guard `id===value`).
    - **Backup:** `.backup-20261108-searcher-webhook/` (14 plików).
    - **Stan końcowy config.json:** `RANKING_PROVIDER: "gemini"` (przywrócony stan usera), `CALLBACK_WEBHOOK_URL: "http://192.168.100.2:9999/hook"` (test receiver — `nohup python3 /tmp/webhook_recv.py`, port 9999, log `/tmp/webhook_recv.log`; **znika po reboot** — przy n8n podmienić na n8n webhook URL), `PUBLIC_BASE_URL: "http://192.168.100.2:8000"`, `SEARCH_LIMIT: "3"`, `SEARCH_ORDER: "popular"`, klucz Gemini/subtitles nietknięte.

18. **Sesja 2026-11-08 (noc #6): n8n INSTALL + WORKFLOW „ClippyMe → YouTube Shorts" (§7 pkt 4) — ZAINSTALOWANE I PRZETESTOWANE do granicy OAuth credentiala.** Decyzja usera: workflow output = **YouTube upload**, próg **viral_score ≥ 85**; konto Google = user side (pkt 5).
    - **Instalacja:** kontener `n8n` (obraz `docker.n8n.io/n8nio/n8n`, **2.46.6**), `--restart unless-stopped`, volume `/mnt/AMPStorage/apps/n8n:/home/node/.n8n`, env `N8N_SECURE_COOKIE=false` + `GENERIC_TIMEZONE=Europe/Warsaw`. **Dual-bind: `-p 192.168.100.2:5678:5678 -p 127.0.0.1:5678:5678`** — LAN bind dla webhooka z kontenera clippyme-backend (sonda `docker exec clippyme-backend curl http://192.168.100.2:5678` = 200), loopback bind DLACZEGO: Google OAuth przyjmuje plain-HTTP redirect TYLKO z loopback → connect credentiala robić z pulpitu homelaba na `http://localhost:5678`. Recreate kontenera (zrobiony podczas sesji) NIE gubi danych (SQLite w volume) i workflow auto-reaktywuje się.
    - **Konto ownera + API key:** utworzone programowo: `POST /rest/owner/setup` (user: `kacperlipiec123@gmail.com`), login `POST /rest/login` z polem **`emailOrLdapLoginId`** (nie `email`!) + header `browser-id`, potem `POST /rest/api-keys` z `{label, scopes: [resource:scope,...], expiresAt: <unix>}` → publiczny key w headerze `X-N8N-API-KEY`. Pułapka: publiczny `GET /api/v1/executions` = Forbidden mimo scope `execution:read` → podgląd wykonań przez WEWNĘTRZNY `GET /rest/executions?limit=N` (cookies) — zwraca spłaszczony „string-table" JSON (refs = indeksy tablicy).
    - **Workflow (ID `LpORWh7hK3bmiHI3`, AKTYWNY):** `Webhook (POST /webhook/clippyme-job-completed, respond Immediately — ważne: ClippyMe retry 5/30/60 s, instant-200 = brak duplikatów)` → `Code node „Filter clips"` (JS: `status==='completed'` + per-clip `viral_score>=85` + `!published`) → `HTTP Request „Download clip"` (GET `video_url`, responseFormat=file → property `data`, timeout 120 s) → `YouTube „Upload to YouTube"` (upload, binaryProperty=`data`, `title[:100]`, regionCode PL, categoryId 24, description `#shorts\n`+description, privacyStatus **public**, notMadeForKids). Lustrzany JSON: `clippyme-n8n-workflow-youtube.json` obok handoffu (update = `PUT /api/v1/workflows/{id}` + **zawsze `POST .../activate`** — PUT dezaktywuje!).
    - **DWA PUŁAPKI (kosztowały debugging):** (a) **Webhook node typeVersion 2 owija body**: output item json = `{headers, params, query, body}` — payload ClippyMe siedzi w `$json.body`, nie `$json` (v1 zwracał body flat). Code node czyta `raw.body || raw` (odporny na oba). (b) **Filter/IF v2 conditions budowane ręcznie przez API nie ewaluują się w 2.46** (format warunków wersjonowany, ręczny JSON cichy DROP — objaw: execution `success`, `lastNodeExecuted`=filter, output pusty) → filtr zrealizowany jako **Code node plain JS** (stabilne). Debugging: włączone `saveDataSuccessExecution: all` + `saveExecutionProgress` w settings workflow, runData czytany z `/rest/executions/{id}` (string-table resolver).
    - **Testy:** (1) webhook round-trip: ClippyMe `POST /api/config/webhook/test` → 200 „Workflow was started" ✓ (powtórzone po recreate). (2) logic: payload score 99 + fake URL → Filter PASS → Download 404 → execution `error` w „Download clip" (dokładnie oczekiwane); score 80 → `success`, stop na filtrze ✓. (3) **real clip download: ręczny webhook payload z REALNYM `video_url` z `/api/history`** (klip ~7 MB, nazwa pliku ze SPACJAMI — n8n HTTP Request radzi sobie) → `binaryDataSizeBytes: 6985261` ✓ → error dopiero na YouTube node = **placeholdery credential** ✓. (4) `CALLBACK_WEBHOOK_URL` przestawiony w config.json na `http://192.168.100.2:5678/webhook/clippyme-job-completed` (test receiver z /tmp NIE jest już wskazywany — wygaśnie sam po reboot).
    - **Credential:** `YouTube OAuth2 (ClippyMe)` (ID `idQbewUmSTe3fo9j`) utworzony przez API z `clientId/clientSecret = PENDING-USER-SETUP` — placeholder PO to, by workflow dał się aktywować (YouTube node blokuje activation bez credentiala). **TODO USER (patrz clippyme-n8n-integracja.md „TODO"):** Google Cloud → włącz YouTube Data API v3 → consent screen (External + user jako test user; **publish do Production** inaczej refresh token wygasa co ~7 dni) → OAuth client Web application z redirect **`http://localhost:5678/rest/oauth2-credential/callback`** → wklej Client ID+Secret w n8n na pulpicie homelaba → Connect. Po tym: walidacyjny realny job (score ≥ 85) → klip sam wylatuje na YT.
    - **Artifacts:** `clippyme-n8n-integracja.md` (pełny rewrite — instalacja, workflow, gotchas, TODO user), `clippyme-n8n-workflow-youtube.json` (lustrzana kopia workflow). n8n API key = **§8** (JWT, expiresAt 2038; można wygenerować nowy: Settings → n8n API).
    - **Stan końcowy sesji (zweryfikowany, koniec noc #6 / 2026-11-09 nad ranem):** kontenery `clippyme-backend`/`clippyme-frontend` healthy + `n8n` Up; workflow `LpORWh7hK3bmiHI3` **aktywny** (przetrwał recreate — SQLite w volume); `GET /api/config`: `CALLBACK_WEBHOOK_URL = http://192.168.100.2:5678/webhook/clippyme-job-completed`, `RANKING_PROVIDER = gemini` (stan usera nietknięty, klucz Gemini w config.json). **Otwarte (user):** Google Cloud OAuth (pkt 1-4 w clippyme-n8n-integracja.md → „TODO") + walidacyjny realny job (score ≥ 85 → auto-upload). **Otwarte (sesja):** pkt 2 (403/cookies), pkt 6 drobiazgi, rezyduum long-form E2E.

19. **Sesja 2026-11-09 (noc #7): MULTI-ACCOUNT PUBLISHING V1 (§7 pkt 11 → plan `PLAN-clippyme-multi-account-publishing.md` §3) — ZROBIONE I PRZETESTOWANE E2E + GUI.** Różne shorts-y → różne kanały YT: ClippyMe = wybór targetów w GUI + `targets` w payloadzie webhooka; n8n = routing per kanał (credential store). Zgodnie z planem: ZERO „account managera" w apce.
    - **Backend (5 plików, +~120 linii):** `storage/config_store.py` — nowy klucz **`PUBLISH_TARGETS`** (JSON array slugów, np. `["yt-kanal-a","yt-kanal-b"]`; empty = legacy) w `VALID_CONFIG_KEYS` + env default + czysty **`resolve_publish_targets(env)`** (json.loads → slug-walidacja `^[a-z0-9_-]{1,40}$` → dedupe → cap 12; garbage dowolnego kształtu → `[]` — malformed setting NIGDY nie może zabić webhooka; host-testowalny). Env-sync genericzny (jak SEARCH_LIMIT) + **per-job przez `merge_persistent_config`** = snapshot z chwili dispatchu. `api/schemas.py` — `PUBLISH_TARGET_NAME_RE` + `PUBLISH_TARGETS_MAX=12` + walidator w ConfigUpdateRequest (JSON array, slug, brak duplikatów, ≤12 → 422 inaczej; `json` import). `jobs/completion_webhook.py` — `_clip_targets` (per-clip override z result clip, walidowany, fallback job-level) + `_clip_entry`/`build_completion_payload(..., targets=None)` dodają `targets` do payloadu joba ORAZ per klip **tylko gdy niepuste** (backward-compat: bez klucza = identyczny payload legacy) + `fire_completion_webhook(..., targets=None)` (None → derive z env) + `notify_job_terminal(..., targets=None)` pass-through. `jobs/job_runner.py` — `finally` woła `notify_job_terminal(..., targets=resolve_publish_targets(env))` gdzie `env` = job env z domergowanym configiem (snapshot dispatch-time: zmiana GUI w trakcie joba NIE reroute'uje go). `api/config_routes.py` — `/api/config/webhook/test` niesie teraz bieżące targets w sample payloadzie.
    - **Frontend (3 pliki, GUI first):** `settings.jsx` — Automation panel, nowy wiersz **„Publish targets"** (git-branch icon): input + Add (Enter też), chips z ×, badge `N targets`/`default`, slug-walidacja po stronie klienta (toast błędu), zapis `saveKeys({PUBLISH_TARGETS: JSON.stringify(list)}` lub `''` przy ostatnim usunięciu); sync z `GET /api/config` w refreshConfig (try/except parse). `icon.jsx` — `GitBranch` w mapie („git-branch"; lucide 0.344 wymaga jawnej mapy!). `settings.test.jsx` — 4 nowe testy (chips+badge z configu, add via Enter/Add-button z round-tripem, odrzucenie złego sluga + toast, remove→shortened→clear). **Pułapka testowa:** hint wiersza zawiera literalny `<code>yt-kanal-a</code>` → getByText musi być anchored do `.chip` (`selector`), inaczej „found multiple".
    - **n8n workflow v2** (ID ten sam `LpORWh7hK3bmiHI3`, nazwa → **„ClippyMe → Multi-publish"**, AKTYWNY; mirror JSON zaktualizowany): Webhook → Filter clips (bez zmian) → NOWY Code **„Route by targets"** (re-read payloadu z `$('Job completed').first().json.body||raw` — job-level targets NIE przetrwają w itemach Filtra; routing jak wyżej + walidacja slugów JS-side) → **fan-out do gałęzi**: [Code „Keep youtube-default" → HTTP „Download clip (default)" → YT „Upload to YouTube (default)" cred #1 idQbewUmSTe3fo9j] + [Code „Keep yt-kanal-a" → HTTP „Download clip (kanal-a)" → YT „Upload to YouTube (kanal-a)" **cred #2 „YouTube OAuth2 (ClippyMe 2)" `ss3URXj0WgSuoJO0` = PLACEHOLDER `PENDING-USER-SETUP-2`**]. Keep-gates jako Code nodes (`$input.all().filter(i => i.json.clippy_target === '<t>')`) — NIE Switch/IF v2 (znana pułapka). Tytuł/description w YT nodach czytają z `$('Keep …').item.json.*` (bezpośredni rodzic — pewne item-linking).
    - **🚨 NAJWIĘKSZA PUŁAPKA SESJI (kosztowała debugging):** budowa `connections` przez API — `connections.update(chain("Route","KeepA")); connections.update(chain("Route","KeepB"))` **NADPISUJE** klucz „Route by targets" (jeden from-node = jeden klucz dict!) → youtube-default gałąź MARTWA (objaw: webhook „success", downstream pusty). Fan-out = JEDEN wpis: `"Route by targets": {"main": [[{node: KeepA...},{node: KeepB...}]]}`. Inspekcja runData z curl: `GET /rest/executions/{id}?unflattened=true` (cookies) → **string-table**: `data` = JSON-string tablicy; refs = stringowe indeksy PŁASKIEJ tablicy (`flat[int(ref)]`, ZERO offsetu); runData node-map = `flat[int(flat[int(flat[0]["resultData"])]["runData"])]`.
    - **Testy:** (1) backend: nowe + regresja = **425 passed** (baseline 417 → +8: resolve sanitize/cap, round-trip+env-sync+clear, API round-trip/422×7/payload targets×4/clip-override/fire-derive/runner-wiring legacy+snapshot). (2) frontend: **395 passed / 8 FAIL** = niezmieniony baseline fontowy (usWeightClass). (3) API round-trip live: POST valid 200 → GET readback; POST garbage/`["Kanal A!"]` → 422; clear → empty. (4) **Webhook E2E**: targets set → `/api/config/webhook/test` dostarcza payload z `targets` (payload-level + per-clip); clear → payload bez `targets` (byte-legacy). (5) **n8n routing runData (4 sondy, fake URL 404 = error we właściwej gałęzi):** explicit `youtube-default` → Download (default); **legacy bez targets → Download (default) = backward compat ✓**; `yt-kanal-a` → Download (kanal-a) ✓; `no-such-branch` → drop, success (zero uploadów) ✓. (6) **Full loop**: ClippyMe config targets → webhook/test → n8n exec #23: Route → Keep yt-kanal-a → Download (kanal-a) ✓. (7) **GUI live w przeglądarce**: wiersz renderuje, add chip `yt-kanal-a` → backend `["yt-kanal-a"]`, badge „1 TARGET", remove → backend `''` (screenshot). **Stan końcowy: `PUBLISH_TARGETS` = ''** (default; nazwy kanałów = decyzja usera po OAuth), reszta configu nietknięta (RANKING_PROVIDER=gemini, CALLBACK_WEBHOOK_URL→n8n).
    - **Backup:** `.backup-20261109-multi-account/` (10 plików: 5 backend + 3 testy + 2 dashboard).
    - **Otwarte (USER — bez tego uploady nie ruszą):** OAuth TODO (clippyme-n8n-integracja.md): Google Cloud → YT Data API v3 → consent → OAuth client (`http://localhost:5678/rest/oauth2-credential/callback`) → wklej do **OBU** credentiali (#1 kanał domyślny, #2 = kanał `yt-kanal-a`) → Connect z odpowiednimi kontami → test private-upload per kanał → targets w GUI. Kolejne kanały C/D = przepis „Jak dodać kanał" w doc n8n.

20. **Sesja 2026-11-11: GOOGLE OAUTH — CREDENTIAL #1 PODŁĄCZONY + FIX TYTUŁÓW UPLOADU (dokończenie pkt 18/19 TODO).** User utworzył Google Cloud projekt + OAuth client (Web application, redirect `http://localhost:5678/rest/oauth2-credential/callback`) na konie **grejemclips1@gmail.com** (kanał #1 = `youtube-default`). Client ID/Secret wstrzyknięte do credentiala `idQbewUmSTe3fo9j` przez WEWNĘTRZNE API (`PATCH /rest/credentials/{id}` po loginie cookies; publiczny `PUT /api/v1/credentials/{id}` zwraca "PUT method not allowed"). Connect zrobiony w przeglądarce usera przez **SSH tunnel** `ssh -N -L 5678:127.0.0.1:5678 ai@192.168.100.2` → `http://localhost:5678` na maszynie roboczej (Google akceptuje plain-HTTP tylko z loopback — tunnel UDZIELA localhost bez obecności przy homelabie; tunnel działa dla całego flow łącznie z redirectem callback). Consent: konto `grejemclips1`, unverified-app → Advanced → proceed.
    - **NOWA PUŁAPKA (kosztowała debugging): single-braces expressions.** YouTube nodes (OBIE gałęzie) miały `title: "={ (...).slice(0,100) }"` — n8n traktuje `{ }` jako tekst literalny (ewaluuje TYLKO `{{ }}` po prefiksie `=`) → wideo na YT z tytułem będącym surową formułą JS; description analogicznie. FIX: `={{ ($('Keep <target>').item.json.title || 'Short').slice(0, 100) }}` + description `=#shorts\n{{ ... }}` (cała logika w klamrach — `.slice()` POZA `{{ }}` też jest literałem!). Update przez `PUT /api/v1/workflows/{id}` + ZAWSZE `POST .../activate`. Mirror JSON zsynchronizowany.
    - **Walidacja E2E (manual webhook, realne klipy z /api/history, score 99/92, target `youtube-default`):** exec #24 success (pierwszy upload po OAuth) i exec #25 success — uploadId **MR84ygi5zhE**, tytuł z payloadu AI ("Ne ha trovato uno da 10.000 euro...") ✓. Upload Krótki (user potwierdził klasyfikację). Wykonanie n8n czytane przez `/rest/executions/{id}?unflattened=true` (string-table: refs liczbowe 1-2 poziomy w głąb; upload node zwraca `{uploadId}`).
    - **Otwarte (USER):** credential #2 `ss3URXj0WgSuoJO0` (`yt-kanal-a`) — TE SAME clientId/secret + Connect na drugie konto/kanał; potem `PUBLISH_TARGETS` w GUI + walidacyjny realny job. Cleanup: 2 testowe wideo do usunięcia z kanału (jeden z tytułem-formułą sprzed fixa, jeden walidacyjny MR84ygi5zhE).
21. **Sesja 2026-11-11 (wieczór #8): n8n FIX TYTUŁÓW (v3-regresja) + ROUTING PL OFF (decyzja usera: JEDNO konto Google) + FULL AUTOMATION „schleuder" (§7 pkt 12 → plan `PLAN-clippyme-scheduled-discovery.md`) — ZROBIONE I PRZETESTOWANE E2E + GUI.**
    - **n8n — REGRESJA v3 (odkryta przez usera: uploady z tytułem-formułą):** deploys v3 (routing językowy, pkt 20 wieczór) zbudowano ze STAREGO zestawu nodów sprzed fixa tytułów → live workflow miał znowu single-brace `={ ... }` w title i BRAK parametru description. FIX (PUT + activate, mirror JSON zsynchronizowany z GET): oba nody YT (default + kanal-a): `title = "={{ ($('Keep <t>').item.json.title || 'Short').slice(0, 100) }}"` + `description = "=#shorts\n{{ ($('Keep <t>').item.json.description || $('Keep <t>').item.json.title || '') }}"` (PRAWDZIWA nowlina w stringu, nie literalne `\n`!). **LEKCJA: po każdym PUT zweryfikować GET-em parametry WSZYSTKICH nodów, nie tylko nowo dodanych.**
    - **ROUTING PL WYŁĄCZONY (decyzja usera 2026-11-11: „nie dodamy drugiego konta Google; jak zapytam, to później"):** Code node „Route by targets" ma teraz `const ENABLE_PL_ROUTE = false;` — bez explicit targets WSZYSTKO leci do `youtube-default` (polskie klipy przestają ERROR-ować na placeholderowym credentialu #2). Włączenie po podłączeniu #2: flip jednej stałej w Code node (PUT + activate).
    - **⚠️ YT UPLOAD QUOTA (user-side):** exec 33 (19:16) i walidacyjny exec 34 (19:53) padły na `uploadLimitExceeded` („The user has exceeded the number of videos they may upload") — dzienny limit kanału (nowe kanały mają niskie caps); execs 31/32 (19:06/19:10) zdążyły się WYUPLOADOWAĆ ze STARYMI zepsutymi tytułami. **USER: przejrzeć kanał #1 i usunąć dzisiejsze uploady z tytułami-formułami** (w tym GTA VI F466B7KHpus jeśli tytuł to formuła — upload był po deploymencie v3). Fix wyrażeń zweryfikowany w live JSON; real-upload walidacja = najbliższy job score ≥85 po resecie quota (~24h rolling).
    - **SCHLEUDER (scheduled auto-discovery + dedupe) — zaimplementowana wg planu:** NOWE pliki `src/clippyme/storage/discovery_registry.py` (rejestr `data/discovery_processed.json`: video_id → {job_id, url, title, dispatched_at}; atomic 0600 writes; corrupt → {} fail-open; cap 500 FIFO; `extract_video_id` watch/shorts/embed/live/youtu.be; `backfill_from_output` scanuje `output/*/source_info.json`) + `src/clippyme/jobs/discovery_scheduler.py` (loop tick 30 s w lifespan obok worker/cleanup tasków; `due_times`/`next_run_time`/`run_due_tick` pure-host-testable; per-okno `last_fired[HH:MM]=date` przeciw double-fire; `run_scheduled_once` = search → dedupe → dispatch → raport → webhook `discovery.scheduled_run` (single-attempt, n8n filter i tak go dropuje jako 0 clips); **NIGDY nie raise**). app.py: wspólny `_dispatch_search_candidates` (search endpoint + scheduler — JEDNA ścieżka, skip processed + register po submiście), register też w `/api/process` (URL-only) i `/api/batch`, backfill raz na start w lifespan (**14 źródeł zbackfillowanych, w tym GTA VI rz1B4B2yBZY → job 3bedcd13**), endpointy **`GET /api/discovery/schedule`** (enabled/times/query/next_run/last_run/server_time; za require_trusted) + **`POST /api/discovery/processed/forget`** (usunięcie wpisu, 404 nieznany; remedy dla false-positive i failed jobs). completion_webhook.py: `build_discovery_payload` (whitelist) + `fire_discovery_webhook`.
    - **Config keys (GUI: Discover → Auto-discovery):** `DISCOVERY_SCHEDULE_ENABLED` ("1"/empty=OFF), `DISCOVERY_SCHEDULE_TIMES` ("HH:MM,HH:MM" max 12; regex `^([01]\d|2[0-3]):[0-5]\d$` wspólny config_store↔schemas), `DISCOVERY_SCHEDULE_QUERY` (≤200 znaków). Scheduler czyta `load_persistent_config()` CO TICK (config = source of truth, odporność na stale-env; zmiany w GUI działają bez restartu). Default OFF = deploy bez zmiany zachowania.
    - **🚨 PUŁAPKA SESJI — TZ KONTENERA:** backend kontener chodzi w **UTC**, host w **CET** (Europe/Warsaw). Naive `datetime.now()` w schedulerze = UTC → okna ustawione po hostowemu odpalałyby o godzinę za późno, a `server_time` w statusie kłamała. FIX: `now_local()` w discovery_scheduler (`zoneinfo.ZoneInfo("Europe/Warsaw")`, graceful fallback na container-local gdy brak tzdata — zweryfikowane: zoneinfo działa w obrazie) + `SCHEDULE_TZ_NAME` w statusie. Pierwsze E2E „nie odpaliło" właśnie przez to (okna 20:57/21:00 host = 21:57/22:00 kontener).
    - **E2E live (3 odpalenia na żywym serwerze):** okno 21:00 (przypadkowo stary wpis po restarcie z tz-fixem) → **1 dispatched** (video `mWNzA27Kfw4` → job `a8ecfb76`, zarejestrowany w rejestrze z tytułem); okna 21:02 i 21:05 → **0 dispatched, 1 skipped (already cut)** — dedupe zadziałał na żywo dokładnie wg wymagania usera („dismiss it, or tell me in some way" — zrobiło OBA: auto-skip + raport w last_run + badge w GUI). Job `a8ecfb76` FAILED na **age-gate** („Sign in to confirm your age" — video 18+, brak cookies.txt na serwerze; znane §6 ograniczenie, nie bug) → **DESIGN DECISION: rejestracja at-DISPATCH — failed job zostaje w rejestrze (brak retry-loopów na permanentnie failujących video); remedy = forget endpoint.** Walidacja GUI (przeglądarka): panel renderuje, switch guard (ON bez query → toast „Set a search query before enabling…"), save round-trip (toast „Auto-discovery saved", config readback OK), **status line z żywymi danymi: „Next run: 08:30 · Last run 21:05: 0 dispatched, 1 skipped (already cut)"**, screenshot. **PUŁAPKA GUI-testowa:** pushToast renderuje z opóźnieniem (pollować .toasts); React onBlur = event `focusout` (nie `blur`); przy sterowaniu inputami przez evaluate — native setter + input event w OSOBNYM ticku niż blur (React batching czyta stary stan).
    - **Stan końcowy config.json:** `DISCOVERY_SCHEDULE_*` puste (scheduler armed ale disabled — user ustawia godziny/query w GUI wg własnego harmonogramu), `SEARCH_LIMIT` puste (default 3), reszta nietknięta. Registry: 14 wpisów (backfill) — mWNzA27Kfw4 forgotten (age-gate demo).
    - **Testy:** backend NOWE **34/34** (tests/storage/test_discovery_registry.py 7, tests/jobs/test_discovery_scheduler.py 14, tests/api/test_discovery_api.py 13; harness jak test_search_api — TestClient bez lifespan, chdir(tmp) izoluje config.json I rejestr). Pełny suite (całe drzewo, ~23 min): **1997 passed / 2 failed / 30 skipped** — (1) `tests/repository/test_docs.py::test_every_env_var_read_by_the_code_is_documented` — **NAPRAWIONY**: dodano sekcję „Ranking engine/Discovery and automation" do `docs/reference/configuration.md` (26 brakujących zmiennych: moje 3 DISCOVERY_* + 23 pre-existing LOCAL_LLM_*/RANKING/SUBTITLES/SEARCH/WEBHOOK — ten test wcześniej NIGDY nie był uruchamiany; stare „pełne regresje" = tylko tests/storage+api+jobs); (2) `tests/pipeline/test_ffmpeg_resume_e2e.py` — **pre-existing env-flake** (`ProcessTreeTerminationError: processes survived terminate+kill` — proces w D-state; zero styku z moimi zmianami; rezyduum). Pułapka: `-e CLIPPYME_API_TOKEN=` nadal obowiązuje; dodatkowo testy hermetyzować względem **os.environ** (import appa syncuje REAL config.json do env — `CALLBACK_WEBHOOK_URL` wycieka do testów „disabled-webhook"). Frontend: discovery **13/13** (+7 nowych; pułapka: najpierw scp testów, potem liczyć, że namespace mocka clienta ma WSZYSTKIE używane eksporty), full suite **402 passed / 8 FAILED = niezmieniony baseline fontowy** (usWeightClass, subtitlePreviewFonts.test.js).
    - **Backup:** `.backup-20261111-scheduled-discovery/` (9 plików: app.py, schemas.py, config_store.py, completion_webhook.py, discovery.jsx, client.js, app.css, test_search_api.py; nowe pliki nie mają backupu — są dodawane, nie modyfikowane).
    - **„Backend not available" na nowym urządzeniu = BRAK API TOKENU, nie sieć (2026-11-11 późny wieczór):** user zgłosił, że z innego komputera strona „nie działa". Diagnoza (zweryfikowana kodem + live): porty OK (backend `0.0.0.0:8000`, frontend `0.0.0.0:5175`), frontend używa relative URLs + Vite proxy (`/api,/videos,/thumbnails,/fonts → http://backend:8000`, same-origin = LAN-safe by design), Vite `allowedHosts` zawsze przepuszcza hosty-IP → strona ŁADUJE się z każdego urządzenia w LAN. **„Backend unavailable…" (history.jsx) brał się z 401** — `useBackendStatus`/Active jobs/History biły o `CLIPPYME_API_TOKEN`, którego świeża przeglądarka nie ma (token jest per-device w localStorage; §6). **FIX (GUI-first):** `useBackendStatus` rozróżnia teraz 401 (`authRequired: true`) od sieciówki; App renderuje żółty banner „This server is protected by an API token… enter it once per device (Settings → API token), then reload" + przycisk „Enter token" → Settings. E2E live: cleared localStorage → banner ✓ → token → banner znika, app w pełni działa ✓. Testy: NOWY `useBackendStatus.test.js` **5/5** (200/401/401-na-jednym-probe/sieciówka/abort-refresh), full frontend **407 passed / 8 FAIL = baseline fontowy**. **Instrukcja dla usera (nowe urządzenie):** `http://192.168.100.2:5175` → kliknij „Enter token" → wklej token (§1) → Save → reload; **+ Gemini key w Settings gdy ranking=gemini** (submit wymaga `X-Gemini-Key` z przeglądarki; dummy `local-no-key` wystarczy przy local). Jeśli po tokenie nadal nie działa na jakimś urządzeniu → dopiero wtedy sieć (subnet/VLAN/firewall) — diagnostyka: `curl http://192.168.100.2:8000/api/health` (401 = osiągalny; timeout = blok sieci).
    - **ZERO-PASTE LAN ONBOARDING (2026-11-11 noc, request usera: „żeby nie wklejać tokena ani klucza Gemini na każdym urządzeniu"):** dwie zmiany, model bezpieczeństwa zachowany dla maszyn: (1) **API token — wstrzykiwany przez Vite proxy**: `vite.config.js` czyta `CLIPPYME_API_TOKEN` z `dashboard/.env.local` (NOWY plik, obok vite.config) i dokłada `X-API-Token` do WSZYSTKICH proxowanych requestów (`headers: proxyAuth` na /api,/videos,/thumbnails,/fonts) — przeglądarka z ŻADNEGO urządzenia nie potrzebuje tokena (setHeader REPLACuje ew. stary nagłówek z przeglądarki — zweryfikowane curl: wrong-token via 5175 = 200), a bezpośredniewołania :8000 (n8n, curl) NADAL wymagają tokena (401 bez). (2) **Gemini key — fallback server-side**: `app.py::_resolve_ranking_key(header)` w /api/process,/api/batch,/api/search — brak/dummy `local-no-key` w headerze → server-persisted `GEMINI_API_KEY` z config.json (Settings); realny header nadal wygrywa; 400 „Missing X-Gemini-Key" USUNIĘTE. Guard w GUI: `/api/config/ollama/status` ma nowe pole **`gemini_key_configured`** (bool, non-secret; placeholder = unset) → App czyta je przy boocie i podaje do useJobSubmission jako `serverGeminiKey` — modal „Add your Gemini key" otwiera się tylko gdy ranking=gemini I brak klucza server-side I brak w przeglądarce. **E2E live: CAŁKOWICIE świeża przeglądarka (localStorage.length=0): brak banneru, search działa, „Process selected" dispatchuje job (cb4da5ed — 1h cats compilation) ZERO wklejonych sekretów; ranking log potwierdza ścieżkę Gemini z server key.** Testy: backend +3 (optional header/dispatch, dummy→server-key fallback, real-header-wins) + RATE_LIMIT_ENABLED=0 w fixture'ach client (429 order-flake między plikami testowymi — pre-existing, naprawiony hermetyzacją); frontend +4 guard testy (useJobSubmission.test.jsx 40/40), full suite bez zmian (407/8 baseline). **UWAGI:** (a) `dashboard/.env.local` zawiera token — plik w repo (bind-mount); (b) zmiana vite.config wymaga `docker restart clippyme-frontend` (konfig czytany na starcie); (c) n8n workflow/cheat-sheet nadal wysyłają `X-Gemini-Key: local-no-key` — nieszkodliwe, server-key przejmuje; (d) dump z duplikatem nagłówka X-API-Token (przeglądarka+proxy) — http-proxy `setHeader` zastępuje, nie duplikuje (zweryfikowane).
    - **Otwarte (USER):** (a) włączyć schleuder w GUI: Discover → Auto-discovery → query + godziny (Europe/Warsaw) → switch ON — zostawione OFF świadomie; (b) posprzątać dzisiejsze uploady z tytułami-formułami na kanale #1; (c) cookies.txt do Settings gdy auto-discovery trafia age-restricted/403 video (endpoint istnieje); (d) credential #2 + `ENABLE_PL_ROUTE=true` „jak user zapyta"; (e) YT upload quota reset ~24h rolling od 18:16 UTC.

    - **ROUTING JĘZYKOWY EN/PL (v3, 2026-11-11 wieczór — request usera: „english → main, polish → second") — ⚠️ OD 2026-11-11 późny wieczór NIEAKTYWNY (pkt 21: `ENABLE_PL_ROUTE=false`, jedno konto Google); historia:** „Route by targets" dostaje fallback językowy gdy brak explicit targets: diakrytyki PL (`[ąćęłńóśźż]`) albo częste polskie słowa w title+description → `yt-kanal-a`; inaczej `youtube-default`. Explicit targets (per-clip / `PUBLISH_TARGETS` w GUI) NADPISUJĄ detekcję — zachowanie V1 nietknięte. Deploy: PUT workflow + activate (v3). Testy 3 sondami (fake video_url 404 = error we właściwej gałęzi): exec 28 EN→default ✓, exec 29 PL→kanal-a ✓, exec 30 PL+explicit-default→default ✓ (override wygrywa). **Świadomy stan przejściowy (user):** polskie klipy lecą do gałęzi kanal-a i ERROR-ują w nodzie YT na placeholderowym credentialu #2 — aż user podłączy drugie konto. Realny upload usera w tym stanie: job `3bedcd13` (GTA VI, score 88, EN) → exec 26 → **uploadId F466B7KHpus** na kanale #1 ✓ (potwierdzone live; kolejne 3 joby usera w kolejce/przetwarzaniu wmomą testu). Exec 27 (17:49) = pusty event (0 klipów po filtrze) — nie-WYBUCH, przypuszczalnie „Send test event" z GUI.

---

## 4. Patch lokalnego LLM — szczegóły

**Pliki** (w repo → bind-mount → aktywna natychmiast, ale patrz „stale env" w §6!):
- `src/clippyme/pipeline/analysis/local_llm.py` — NOWY plik: shim zgodny z interfejsem google-genai (`client.models.generate_content`, `response.text`, `usage_metadata`), mówi do Ollamy `/api/chat` z `format=<JSON-schema>` (grammar wymusza klucze!), **`_salvage_clip()`: naprawia timingi (min 10s / max 75s, clamp do długości wideo z promptu), score 1-100 (int), viral_reason ≥20 zn., tytuł ≤110, hook ≤160, hook==title → pierwsze 6 słów reason** — bez tego walidacja wyrzuca krótkie klipy i job spada do TextTiling; retry OOM: ctx →halve→ fallback model, sleep 4s. **+ chunked ranking dla długich wideo: `generate_chunked()` (§9, §3 pkt 12), WINDOW_SCHEMA minItems=1, `_clamp_clip_to_window` (drop hallucynacji), `_merge_window_clips` (IoU>0.35, top-K).**
- `src/clippyme/pipeline/main.py` — w `get_viral_clips` po `client = genai.Client(...)`: jeśli `LOCAL_LLM_BASE_URL` ustawione → czyści cache Whispera (`_whisper_models.clear()` + `torch.cuda.empty_cache()`, drukuje 🧹) i podmienia client na `LocalLLMClient`. **+ gate chunked: `isinstance(LocalLLMClient) && estimate_tokens_for(words, text) > LOCAL_LLM_CHUNK_THRESHOLD_TOKENS` → `generate_chunked` zamiast `generate_with_model_fallback`.**
- `src/clippyme/pipeline/analysis/gemini_request.py` — bez zmian w ścieżce Gemini; **+ pure helpers chunked: `plan_windows`, `build_viral_prompt_window`, `encode_words_toon_window`, `estimate_tokens_for`, `WINDOW_HEADER_TEMPLATE`.**
- Gdy Ollama padnie albo >50% okien chunked padnie → wbudowany fallback TextTiling (klipy tematyczne, score 0, tytuły „part 1/2").

**Zmienne w `.env`** (repo root):
```
TRANSCRIPTION_PROVIDER=whisper
GPU_RUNTIME=nvidia
MAX_CONCURRENT_JOBS=1
CLIPPYME_BIND=0.0.0.0
CLIPPYME_API_TOKEN=096785...
ALLOWED_ORIGINS=http://192.168.100.2:5175,...
GEMINI_API_KEY=local-no-key          # dummy, wymagany przez early-return w main.py
GEMINI_MODEL=qwen3:4b-instruct       # też w data/config.json (Settings nadpisuje env!)
GEMINI_FALLBACK_MODELS=qwen2.5:3b
LOCAL_LLM_BASE_URL=http://192.168.100.2:11434
LOCAL_LLM_MODEL=qwen3:4b-instruct    # WYGAŚLA nad GEMINI_MODEL w shimie
LOCAL_LLM_FALLBACK_MODEL=qwen2.5:3b
LOCAL_LLM_KEEP_ALIVE=0               # zwalnia VRAM po każdym callu (ważne przy 6GB)
LOCAL_LLM_NUM_CTX=16384              # chunked path (§9); single-shot dziedziczy też 16384
LOCAL_LLM_CHUNK_THRESHOLD_TOKENS=8000  # est tok > to → chunked (§3 pkt 12: 8000 nie 6000!)
LOCAL_LLM_WINDOW_ROWS=450
LOCAL_LLM_WINDOW_OVERLAP_ROWS=60
LOCAL_LLM_CHUNK_TOPK=3
LOCAL_LLM_FINAL_TOPK=8
LOCAL_LLM_CHUNK_RETRIES=1
WHISPER_MODEL=medium
HF_HOME=/app/data/hf-cache
MPLCONFIGDIR=/tmp/mpl
```

**Zmiana modelu w przyszłości:** **OD 2026-11-08 (wieczór #4): GUI — Settings → Ranking engine → „Local model"** (persisted `LOCAL_LLM_MODEL` w config.json, per-job bez restartu, §3 pkt 16; „Default (.env)" = empty). Legacy path nadal działa: `ollama pull <model>` → `sed .env LOCAL_LLM_MODEL=` → restart backendu → config.json pusty dla tego klucza. Limit praktyczny na 6GB: wagi ≤2.5-3GB (4B q4 OK; 7B q4 = marginalny OOM; GUI pokazuje hint GB z /api/tags).

**PRZEŁĄCZNIK (2026-11-08 noc): ZROBIONY** — provider rankingu zmienia się z GUI (Settings → „Ranking engine": Local (Ollama) / Cloud (Gemini)), persisted jako `RANKING_PROVIDER` w `data/config.json`, aplikowany per-job bez restartu. Detale i testy: §3 pkt 13 / §7 pkt 7. Stary mechanizm (obecność `LOCAL_LLM_BASE_URL` w `.env` = tryb local) nadal działa jako domyślny „auto", gdy setting jest pusty.

---

## 5. Kontener/compose

- Start: `cd /mnt/AMPStorage/apps/clippyme && sudo docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`
- **Po każdej zmianie `.env`: `sudo docker restart clippyme-backend`** (env compose jest zamrażany przy tworzeniu kontenera; dotenv nie nadpisuje istniejących env — zmiany .env bez restartu NIE działają dla zmiennych, które compose przekazuje).
- Wolumeny: `.:/app` (repo live!), `./data`, `./output`, `./uploads` → wszystko na AMPStorage (429G wolne).
- docker data-root: **ZMIGROWANY (2026-11-08 pm) → `/mnt/NextCloudDisk/docker-data` + containerd root → `/mnt/NextCloudDisk/containerd`**. Docker 29.4.1 używa **containerd image store** (`driver-type: io.containerd.snapshotter.v1`) — obrazy/warstwy leżą w containerd (37G), nie w docker-data (2,9G)! Zmienione: `/etc/docker/daemon.json` (`"data-root"`, backup `.bak-*`) + `/etc/containerd/config.toml` (`root = ...`). Kopiowanie: rsync -aHAX przy stopniętym docker+containerd (~7 min total). Weryfikacja: wszystkie kontenery healthy, CUDA: True w backendzie, yt-dlp 2026.10.26 przetrwał (restart demona nie czyści FS kontenera — tylko recreate!). Root disk: 97% → **68% (68G wolne)**. Backuple configów: `/etc/docker/daemon.json.bak-*`, `/etc/containerd/config.toml.bak-*`.

---

## 6. Gotowce / pułapki (nauczone boleśnie)

- **Import-time config wipe (USUNIĘTY 2026-11-08 wieczór #4, §3 pkt 16)**: dawniej `app.py` przy imporcie robił `save_persistent_config(load_persistent_config())` → każdy proces importujący backend (pytest, CLI) nadpisywał `data/config.json` swoim env-view (dummy klucze!). Teraz `sync_env_with_persistent_config()` (env-only) + create-only przy first boot. **Pełny pytest suite jest bezpieczny dla config.json** (md5-stabilny, dowód w pkt 16) — ale nadal uruchamiać backend testy z `-e CLIPPYME_API_TOKEN=` (dotenv ładuje token → 401 w testach zaufanych tras).
- **Stale env**: po zmianie `.env` — zawsze `docker restart clippyme-backend`. Objaw: stary model/klucz w jobach.
- **`data/config.json` nadpisuje env** (Settings z UI; `merge_persistent_config`) — trzymać spójnie z .env.
- **YOLO `yolov8n.pt` = curl error 23 przy reframie (naprawione 2026-11-08 pm)**: backend (PID 1) działa jako uid 996 `appuser`, ale root repo `/mnt/AMPStorage/apps/clippyme` jest `ai:ai drwxr-xr-x` → appuser NIE może pisać do `/app` (curl 23 = write error, EACCES). `docker exec` działa jako root — więc ręczny test downloadu przechodzi, a job nie (mylące!). Każdy clip padal deterministycznie na `YOLO('yolov8n.pt')` → próba downloadu z GitHuba do CWD `/app` → EACCES. Fix: plik położony ręcznie w `/app/yolov8n.pt` (6,5MB, mode 644 root:root — world-READABLE wystarczy; `attempt_download_asset` sprawdza `file.exists()` przed downloadem). Job w trakcie odtworzył się MID-RUN (klip 5+ OK). Plik jest w bind-mouncie repo → przeżywa recreate/rebuild. UWAGA: przy świeżym clone repo trzeba ponownie plicować (`curl -L -o /mnt/AMPStorage/apps/clippyme/yolov8n.pt https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8n.pt`). Klipy 1-4 joba `Zakochałem…🇨🇷` padły (reframe) → **ODTWORZONE 2026-11-08 wieczór przez `/api/reframe` per clip_index (§3 pkt 11)**.
- **GPU wedge**: po serii crashy runnerów CUDA cały driver odmawiał („CUDA-capable device(s) busy or unavailable", `cudaErrorDevicesUnavailable` nawet dla torch na idle GPU). Remedia: **reboot serwera** (rmmod nvidia_uvm blokowany przez gnome-remote-desktop). Jeśli tylko Ollama szwankuje: `sudo systemctl restart ollama`. Po naprawie Ollamy (0.40.15) + mniejszy model → nie powinno wracać.
- **403 „page needs to be reloaded" przy YouTube**: bot-detection IP serwera. Zrobione: runtime upgrade yt-dlp (2026.10.26) — metadata już działa (test 5un2xMWr21g OK z ostrzeżeniem o deno/EJS — deno JEST w obrazie, więc in-job challenge solver może działać). Jeśli dalej 403 przy pełnym download: **cookies.txt przez Settings** (ekspor z przeglądarki użytkownika, np. rozszerzenie „Get cookies.txt LOCALLY" na youtube.com) lub zakładka Upload.
- **sudo -S + heredoc zagnieżdżony przez ssh = zawodzi** (cisza, nic się nie dzieje). Wzorzec: pliki lokalnie → `scp` → wykonanie zdalne; hasło sudo zawsze stdin (`echo stbr | sudo -S -p ""`). UWAGA: `echo stbr | sudo -S nohup skrypt </dev/null &` = sudo nie dostanie hasła (redirect `/dev/null` nadpisuje pipe) — wstawić `</dev/null` do wnętrza: `sudo -S bash -c 'nohup skrypt </dev/null ... &'`.
- **Docker 29+ = containerd image store**: `docker info` pokazuje `driver-type: io.containerd.snapshotter.v1` i `Storage Driver: overlayfs` → obrazy/warstwy w `/var/lib/containerd` (u nas 37G), a `/var/lib/docker` ma tylko metadane/volumes (~3G). Migracja data-root = PRZENOSIĆ OBA (`daemon.json` data-root + `config.toml` root containerd). Bonus: du źródła przy RUNNING kontenerach zawyża rozmiar (żywe warstwy) — porównywać po stopie.
- **`..` substring-check w filename guardach = pułapka na `...` w tytułach (naprawione 2026-11-08 wieczór, §3 pkt 11)**: tytuły YT z `...` (ellipsis) sanitize'ują się do nazw plików zawierających `...`; guard `".." not in raw` false-positive'uje i cicho odwraca naming na pozycyjny → 404 na downloadzie. Reguła: przy zabronionych separatorach sprawdzać tylko `raw not in (".", "..")`.
- **Job render path = orchestrator, NIE main.py loop (2026-11-08 noc #2)**: joby z dashboardu renderują klipy przez `pipeline/orchestrator.py::_render_one_clip` (print `✅ Clip i/total ready`), a print w main.py (`✅ Clip N ready`, bez /total) to legacy/CLI path — zmiany w renderze muszą trafić w OBA miejsca (auto-napisy tak robią, §3 pkt 14). Punkt zaczepienia ze spec §7 pkt 8 („main.py ~:1056") był mylący — weryfikuj zawsze, KTÓRY kod realnie wykonuje job (`docker logs` pokazuje format printu).
- `pip install -U yt-dlp` w kontenerze jako root — WARNING pipa, ignorować.
- Frontend: gemini-key + api-token w localStorage — czyść na innym urządzeniu/przeglądarce ponownie (Settings).
- `Whisper model: ... (CPU mode)` w logu joba = hardware.py nie przeszedł tiny-testu CUDA (wtedy transkrypcja na CPU — wolna, ale działa). Sprawdź GPU przy tym.

---

## 7. ZADANIA OTWARTE (w kolejności)

1. ~~**TEST qwen3:4b-instruct E2E**~~ — ✅ **NAPRAWIONE I PRZETESTOWANE (2026-11-08 pm, patrz §3 pkt 9).** Diagnoza potwierdzona (klipy 4-5s < minimum 10s ze schema ViralClip), ALE wniosek „niemożliwe na 27s" był ZŁY: schema wymaga 10-75s (nie 15-60s — to tylko cel z promptu), więc klipy 10-27s są jak najbardziej możliwe. Fix: `_salvage_clip()` w `local_llm.py` naprawia timingi. Retest na tym samym 27s wideo (job `196b2979`): 3 klipy, score 92/90/89, włoskie tytuły, strict path, zero dropów. **Lokalny pipeline = operational także dla krótkich wideo.** ~~DO ZROBIENIA nadal: test na prawdziwym długim wideo (10-60 min)~~ → **WYKONANY (2026-11-08 pm, job `9d84798e`, 55 min „Zakochałem się…🇨🇷"): ranking LLM PADŁ — transkrypt 167 292 tokenów > ctx 8192 → HTTP 400 → fallback TextTiling (12 klipów score 0 „part N", klipy 1-4 dodatkowo bez reframu — curl 23, patrz §6).** ~~FIX ZAPLANOWANY: chunked map-reduce ranking — §9~~ → **ZIMPLEMENTOWANY I PRZETESTOWANY (2026-11-08 wieczór, patrz §3 pkt 12): wszystkie testy §9.5 zielone (33/33 unit, smoke, pełny ranking 18 okien, regresja 27s score 87, VRAM 3939 MiB). LONG-FORM LOCAL PIPELINE = OPERATIONAL.** Rezydualne: pełny E2E z renderem przy najbliższym long-form uploadzie (§3 pkt 12).
2. **Odpowiedź użytkownikowi na 403 YouTube**: wyjaśnić cookies.txt (Settings → upload cookies) lub Upload tab; ewentualnie test pełnego downloadu po upgrade yt-dlp (metadata działa).
3. ~~**Migracja docker data-root**~~ — ✅ **ZROBIONA (2026-11-08 pm, patrz §5).** Docker → `/mnt/NextCloudDisk/docker-data`, containerd → `/mnt/NextCloudDisk/containerd` (uwaga: docker 29 używa containerd image store — migrowane OBA katalogi). Stare `/var/lib/docker` + `/var/lib/containerd` usunięte. Root disk 97% → 68%.
4. **n8n**: ~~instalacja kontenera + workflow~~ — ✅ **ZROBIONE (2026-11-08 noc #6, patrz §3 pkt 18):** kontener 2.46.6 (dual-bind LAN+loopback, volume na AMPStorage), workflow „ClippyMe → YouTube Shorts" aktywny (webhook → Code filtr score≥85 → download → YT upload), `CALLBACK_WEBHOOK_URL` przepięty na n8n. **REZIDUALNE (user): Google Cloud OAuth (YouTube Data API v3 + consent + client z redirect `http://localhost:5678/rest/oauth2-credential/callback`) → wkleić do credentiala „YouTube OAuth2 (ClippyMe)" w n8n → walidacyjny realny job.** Docs: `clippyme-n8n-integracja.md` (zaktualizowany noc #6). UWAGA: `/api/process` wymaga nagłówka `X-Gemini-Key` (dummy `local-no-key`) — patrz dokument n8n.
5. **Krok 2 (konta Google)**: użytkownik tworzy ręcznie (nie da się automatycznie — ToS/telefon/captcha). Potem: publikacja przez Zernio (w ClippyMe) LUB YouTube OAuth w n8n.
6. Drobiazgi: `passwd ai` (silniejsze hasło); trwałość upgrade yt-dlp po **recreate/rebuildzie** (pin w requirements.lock lub AUTO update; restart demona NIE czyści); ~~stare modele Ollama~~ ✅ usunięte (2026-11-08 pm): qwen2.5:7b, Qwen:latest, mistral, llama3.1:8b/latest + q5 → zostały qwen3:4b-instruct, qwen2.5:3b, gemma3:1b (4,9G, było 26G); ~~fallback chain w config.json~~ — w chwili pisania config.json nie istniał; **OD 2026-11-08 istnieje** (Settings: RANKING_PROVIDER, GEMINI_MODEL, SUBTITLES_AUTO/SUBTITLE_PRESET, prawdziwy klucz Gemini — aktualny stan patrz §3 pkt 14); zamiast tego poprawiono `.env`: GEMINI_MODEL=qwen3:4b-instruct, GEMINI_FALLBACK_MODELS=qwen2.5:3b (uwaga: shim i tak wymusza LOCAL_LLM_MODEL — czysto kosmetyczne).
7. ~~**[PRZYSZŁOŚĆ] Przełącznik UI: lokalny LLM ↔ Gemini**~~ — ✅ **ZROBIONY (2026-11-08 noc, patrz §3 pkt 13): backend (persisted `RANKING_PROVIDER` + `resolve_ranking_provider` + `/api/config/ollama/status`) i GUI (Settings „Ranking engine" Segmented + Ollama health panel + warningi dummy-key/koszty + guard w submit). Zmiana działa per-job BEZ restartu kontenera. Testy: 42/42 backend, 13/13 nowych frontend, E2E regresja 27s (job `79693156`, score 92), GUI zweryfikowane screenshots.** Szczegóły mechanizmu:
   - **Obecny mechanizm** (`main.py` → `get_viral_clips`): jeśli env `LOCAL_LLM_BASE_URL` ustawione → podmiana clienta na `LocalLLMClient` (shim); brak → google-genai (Gemini). Zmiana providera = edycja `.env` + restart (pitfall stale-env, §6).
   - **Backend**: dodać persisted setting, np. `RANKING_PROVIDER=local|gemini`, płynący przez mechanizm `merge_persistent_config` (`data/config.json` overlay — UWAGA §6: config.json nadpisuje env!). W `get_viral_clips` czytać setting, nie tylko env. Zweryfikować, czy overlay jest aplikowany per-job (wtedy zmiana bez restartu) czy tylko na starcie (wtedy minimalny reload).
   - **Frontend (Settings)**: select/switch „Ranking: Local (Ollama) / Cloud (Gemini)"; przy `gemini` — wymusić niepusty prawdziwy klucz Gemini (localStorage gemini-key, dziś dummy `local-no-key`, leci jako nagłówek `X-Gemini-Key`) i pokazać hint o kosztach; przy `local` — health-check Ollamy (`GET :11434/api/tags`) + nazwa aktywnego modelu z `.env`/configu.
   - **Pułapki**: (a) gałąź lokalna czyści VRAM Whispera (`_whisper_models.clear()` + `empty_cache()`) — w gałęzi Gemini tego NIE robić; (b) przy Gemini klucz z localStorage musi być prawdziwy — UI ma to wymusić, inaczej job spadnie do TextTiling; (c) przy Local zweryfikować, że Ollama żyje, bo cichy fallback = TextTiling (score 0, „part 1"); (d) `X-Gemini-Key: local-no-key` w headerze requestu jest OK też dla trybu lokalnego — nie mylić z prawdziwym kluczem do rankingu.
   - **Kolejność**: po n8n (pkt 4), nieblokujące — n8n i tak woła `/api/process`, więc używa tego, co wybrane w UI.
8. ~~**[USER PRIORITY 2026-11-08 noc] Auto-napisy („beautiful subtitles") wprost w pipeline renderu — AUTOMATYCZNIE po utworzeniu klipa**~~ — ✅ **ZROBIONE I PRZETESTOWANE (2026-11-08 noc #2, patrz §3 pkt 14).** Auto-burn karaoke napisów po każdym klipie (orchestrator + legacy main.py loop), re-burn po reframe, persisted settings `SUBTITLES_AUTO`/`SUBTITLE_PRESET` (GUI Settings → „Captions", per-job bez restartu), helper `auto_burn_subtitles_inplace` w `editing/subtitles.py`. Testy: 44/44 backend unit, 314 testów napisowych, 17/17 settings frontend, E2E 27s ON (klatka z napisami) / OFF (czysto) / reframe (napisy przetrwały), GUI round-trip w przeglądarce. Rezyduum: pełny long-form E2E z napisami przy najbliższym uploadzie; compose na klipie z auto-napisami nakłada drugą warstwę (caveat v1, §3 pkt 14). Oryginalna spec (dla historii):
   - **Cel**: po udanym `process_video_to_vertical()` (+ `normalize_audio` + `select_cover_frame`) w main.py **automatycznie** wypalić karaoke napisy na finalnym 9:16 klipie — klip z downloadu od razu ma napisy, zero ręcznych klików. Domyślnie **ON**, preset z GUI.
   - **Punkt zaczepienia (ZWERYFIKOWANY 2026-11-08 noc)**: main.py ~:1056-1065 — zaraz po `select_cover_frame(clip_final_path)`, przed printem „✅ Clip N ready". Warunek: `clips_data['transcript']` obecny w metadata (słowa z timestampami word-level — pipeline już je zapisuje „for subtitles"). Slice transkryptu [start,end] klipa → `generate_ass_karaoke(...)` → `burn_subtitles(video, ass, clip_final_path)` **IN-PLACE** (ten sam `clip_filename` — historia/video_url bez zmian), NIE tworzyć `composed_*`. Wzorzec parametrów: `compose.py::_apply_subtitles` (band/kolejność warstw, offset_y, position).
   - **Backend — mechanizm settings = PROVEN pattern z przełącznika rankingu (§3 pkt 13, kopiuj 1:1)**: klucze **`SUBTITLES_AUTO`** (`"1"`/`"0"`, empty=default ON) i **`SUBTITLE_PRESET`** (klucz z `SUBTITLE_PRESETS`, empty=default preset) — dodać do `VALID_CONFIG_KEYS` (config_store) + `_ALLOWED_CONFIG_KEYS` + walidator wartości (schemas.py) + `GET /api/config` zwraca je automatycznie. Aplikacja per-job przez `merge_persistent_config` → **zmiana w GUI działa dla następnego joba BEZ restartu** (nie edytować `.env`! — reguła GUI-first z nagłówka handoffu). Opcjonalnie v2: `SUBTITLE_POSITION`.
   - **Frontend (Settings — GUI first)**: toggle „Auto-napisy (nagrywanie w klipie)" + picker presetu (reuse per-preset picker z compose/edit modal) + mini-podgląd; zapis przez `saveConfig({SUBTITLES_AUTO, SUBTITLE_PRESET})`. Per-job override w formularzu uploadu = v2 (nie blokuje).
   - **Pułapki**: (a) `burn_subtitles` = dodatkowy pass re-enkodu — rozważyć fold w ten sam ffmpeg co `normalize_audio` albo zaakceptować +1 pass/klip (~10-20% czasu renderu); (b) **`/api/reframe` nadpisuje `clip_final_path` IN-PLACE → po re-renderze napisy znikają — re-burn też tam** (reframe ma dostęp do job metadata i word tokens; patrz §6/reframe); (c) język napisów = język transkryptu (Whisper word tokens) — zawsze poprawny, w przeciwieństwie do tytułów LLM (mieszanka PL/IT, §9.7); (d) ASS brace-strip (`_strip_ass_braces`) już jest — nie wywalać; (e) VRAM nie dotyczy (libass = CPU); (f) sanityzacja tokenów ASR częściowo w silniku — przetestować na polskim; (g) w pipeline brak grade/hook/logo warstw z compose — plain karaoke burn wystarczy (nie ciągnąć całego `_apply_subtitles`); (h) kolejność vs `normalize_audio`: palić napisy PO normalize (normalize działa na audio, burn na wideo — kolejność obojętna, ale niefoldować jedno w drugie bez testu).
   - **Testy**: (1) E2E krótkie wideo (cache `uploads/196b2979*.mp4`, 27s) z `SUBTITLES_AUTO=1` → klip ma napisy **bez ręcznego compose** (weryfikacja: ffprobe/1 klatka z napisem + `✅` log); (2) `SUBTITLES_AUTO=0` → brak napisów (regresja starego zachowania); (3) `/api/reframe` klipa → napisy przetrwały; (4) ręczny compose nadal działa i może nadpisać presetem (idempotencja: compose działa na `clip_filename`); (5) GUI: toggle+picker zapisują się i widnieją w `GET /api/config`.
   - **Kolejność**: **PODBITA NA ŻYCZANIE USERA (2026-11-08)** — najbliższy duży task, może iść równolegle/też przed n8n (pkt 4; n8n pobiera finalne klipy → napisy w klipie pomagają workflowowi publikacji). Nakład: ~60-100 linii backend + settings UI wg wzorca rankingu; implementacja ~1-1.5h + walidacja.
9. ~~**[USER REQUEST 2026-11-08 noc] Panel „Active jobs" — aktualnie aktywne joby w GUI (cross-session).**~~ — ✅ **ZROBIONE I PRZETESTOWANE (2026-11-08 noc #3, patrz §3 pkt 15):** `GET /api/jobs/active` (whitelist pól, FIFO positions, grace 120 s) + panel nad historią z kontrolkami Pause/Resume/Stop/Discard/Open + pulsujący badge na tabie History + polling 4 s (busy) / 15 s (idle). Testy: 7/7 backend, 371 regresja, 12/12 frontend, 375/8 baseline GUI; E2E żywe: curl-job widoczny w czystej przeglądarce, Pause/Resume z panelu potwierdzone API, Open→results, attach→ProcessingView. Backup: `.backup-20261108-active-jobs/`. Oryginalna spec (dla historii): Problem: Create/ProcessingView śledzi TYLKO jeden `jobId` z localStorage **tego** przeglądarki (useSessionPersistence). Job wysłany z innego urządzenia/przeglądarki (albo po wyczyszczeniu storage) jest niewidoczny na żywo — widać go dopiero w History (bez progresu/logów/ETAI w formie kart klipów). Backend tymczasem MA wszystko w pamięci (`jobs` dict: status/attempt/logs/ETA z `runtime_state.collect_runtime_metrics` + `estimate_eta`) + crash-safe journal (`jobs/job_journal.py`, queued są requeue'owane po restarcie) + pełne kontrolki per job (`/api/pause|resume|stop|cancel/{id}` — istnieją!) + `POST /api/history/{job_id}/restore` (otwarcie widoku dowolnego joba). Brakuje wyłącznie GUI + jednego taniego endpointu.
   - **Backend**: nowy **`GET /api/jobs/active`** (za `require_trusted_config_request`) — filtr `jobs` dict do `queued|processing` (+ ew. świeżo `completed/failed` z grace ~2 min, żeby panel nie mrugał), per job whitelist pól: `job_id, status, attempt/max_attempts, created/started_ts, stage, eta_seconds, progress (z runtime_state), log_tail (ostatnie ~8 linii), label (url / nazwa pliku), queue_position` (MAX_CONCURRENT_JOBS=1 → pokaż pozycję w kolejce). **Whitelist, nie serilizacja całego dict** — `env` jest już popped pre-dispatch (job_runner), ale journal_env ma tylko publiczne pola; nigdy nie zwracać env/ścieżek z credentials. Tani endpoint (in-memory, zero disk scan). Dla requeued-po-restarcie id stoi w `jobs` → `/api/status/{id}` dalej działa.
   - **Frontend (GUI first)**: (a) **badge w top-nav** przy History: „Active jobs (N)" z pulsem gdy N>0; (b) **panel/sekcja Active jobs** (top of History tab albo osobny widok) — wiersz per job: label, stage + progress bar, ETA, queue position, rozwijalny log tail; (c) **kontrolki inline**: Pause/Resume/Stop/Cancel (endpointy istnieją — reuse `cancelJob/pauseJob/resumeJob/stopJob` z api/client); (d) klik → otwórz istniejący job viewer przez `restoreJob` (`POST /api/history/{id}/restore`); (e) polling co ~3-5s tylko gdy N>0 (nowy lekki hook, NIE reuse useJobPolling — ten jest single-job); (f) ProcessingView (single-job) zostaje bez zmian — panel go uzupełnia, nie zastępuje.
   - **Pułapki**: (a) po restarcie backendu `/api/status/{id}` 404 dla starych jobów — panel listuje tylko to, co żyje w `jobs` dict (requeued queued-jobs mają nowe dispatche → OK); (b) nie dublować stanu — panel = server truth, localStorage tylko dla „ostatnio oglądany"; (c) batch (/api/batch) tworzy wiele job_id — panel pokazuje każdy osobno (dziś ProcessingView ma batch strip tylko kosmetyczny); (d) Live Monitor ma własny status endpoint (`/api/live-monitor/status`) — poza zakresem pkt 9 (ew. link później); (e) rate-limit: polling listy co 3-5s = ~12-20 req/min < throttles w app.py; (f) pruning grace-window completed/failed, żeby panel nie „gubił" ostatniego joba natychmiast po zakończeniu.
   - **Testy**: (1) unit backendu: filtr statusów, whitelist pól (no secrets — asercja na brak `env`/`GEMINI`/token w payloadzie), kolejka >1; (2) GUI test: panel renderuje N aktywnych, kontrolki wołają właściwe endpointy; (3) E2E manual: submit dłuższego joba z przeglądarki A → widoczny + stoppable z przeglądarki B; (4) requeue po restarcie: queued job przeżywa `docker restart` i nadal jest w panelu; (5) delete-guard: próba usunięcia aktywnego joba → 409 (już działa — tylko potwierdzić w panelu).
   - **Kolejność**: po pkt 8 (auto-napisy) lub równolegle — niezależne. Nakład: backend ~50-80 linii + GUI panel ~150-200 linii; ~2h + walidacja.
10. ~~**[USER REQUEST 2026-11-08 noc #2] Wybór modelu Ollama z GUI — detekcja dostępnych modeli + selector.**~~ — ✅ **ZROBIONY I PRZETESTOWANY (2026-11-08 wieczór #4, patrz §3 pkt 16):** persisted `LOCAL_LLM_MODEL` (config.json-only, świadomie BEZ syncu do os.environ — pułapka #1), format-validation 422, `/api/config/ollama/status` wzbogacony o `models_detail` (size/parameter_size) i czytający efektywny model z config-overlay, GUI select „Local model" (dim przy gemini, off-list warning, VRAM hint, „Default (.env)"). Testy: 47/47 backend, 21/21 settings (379/8 full suite = baseline), E2E job `bc42a366` na gemma3:1b (log chain potwierdzony), GUI round-trip w przeglądarce. Backup: `.backup-20261108-model-selector/`. Oryginalna spec (dla historii): Dziś model lokalny jest hardcoded: `.env LOCAL_LLM_MODEL=qwen3:4b-instruct` + fallback `LOCAL_LLM_FALLBACK_MODEL=qwen2.5:3b`; shim (`local_llm.py:233`) robi `model = os.getenv("LOCAL_LLM_MODEL") or model` — ZERO auto-detekcji (lista z `/api/tags` służy tylko do wyświetlenia w panelu Ollama status). Zmiana modelu = ssh + sed .env + restart (§4). Cel: **Settings → Ranking engine (sekcja local): dropdown „Local model" z listą modeli wykrytych na Ollamie, zapis persisted, działa per-job BEZ restartu** — dokładnie reguła GUI-first.
    - **Detekcja — JUŻ JEST**: `GET /api/config/ollama/status?check=true` (pkt 13) robi GET `LOCAL_LLM_BASE_URL/api/tags` (timeout 4s) i zwraca `models: [nazwy]` (+ `reachable`, `model`, `effective_provider`). Ewentualnie wzbogacić o `size`/`details.parameter_size` z /api/tags (Ollama je zwraca) — do hintu o VRAM.
    - **Backend — klucz persisted `LOCAL_LLM_MODEL` (uwaga: TA SAMA nazwa co env!):** dodać do `VALID_CONFIG_KEYS` + `load_persistent_config` default `os.environ.get("LOCAL_LLM_MODEL", "")`. **Elegancki efekt: shim nie wymaga ŻADNEJ zmiany** — `merge_persistent_config` (job_runner :26-34) nakłada WSZYSTKIE niepuste klucze configu na job env at dispatch → `os.getenv("LOCAL_LLM_MODEL")` w subprocessie pipeline'u czyta wartość z GUI automatycznie. Empty = fallback do `.env` (overlay pomija puste — backward compat 1:1). Revalidate walidator: tylko format (np. `^[A-Za-z0-9._:/-]+$`), **NIE** twarda lista — model można pull-nąć później / Ollama może być down przy zapisie; niepasujący do wykrytych = soft warning w GUI.
    - **PUŁAPKA #1 (przetestować!):** `save_persistent_config` przy pustej wartości robi `os.environ.pop(key)` — dla `LOCAL_LLM_MODEL` to WYKASOWAŁOBY wartość z `.env` załadowaną przez dotenv do procesu API → kolejne joby bez fallbacku `.env` (shim spadłby na chain GEMINI_MODEL!). Potrzebny special-case jak HF_TOKEN: przy empty czyścić TYLKO config.json, NIE os.environ (albo zapamiętać .env default na starcie appki). To jedyna realna zmiana poza config_store/schemas.
    - **Frontend (Settings → sekcja local, pod Ollama status):** select „Local model" z `getOllamaStatus(true)` (models już lecą); pokazuj efektywną wartość z `GET /api/config` (będzie zwracane automatycznie po dodaniu do VALID_CONFIG_KEYS); zapis `saveConfig({LOCAL_LLM_MODEL})`; opcja „Default (.env)" = empty; warning gdy wybrany nie ma się na wykrytej liście albo Ollama offline; **przygaszać gdy RANKING_PROVIDER=gemini** (setting wtedy nieaktywny); hint VRAM gdy `size` > ~3GB (6GB karta — §4).
    - **Pułapki pozostałe**: (a) config.json nadpisuje env (§6) — `.env LOCAL_LLM_MODEL` staje się fallback-only; trzymać spójnie; (b) większy model zmienia założenia chunked (num_ctx=16384 mierzone na 4B; 7B przy 16384 = marginalny OOM, §4) — OOM-path shimu (ctx halve → LOCAL_LLM_FALLBACK_MODEL → TextTiling) już jest; (c) reframe subprocess dostaje persisted config przez `reframe_env` (reframe_service) — nowy klucz płynie automatycznie, nic nie robić; (d) `GET /api/config` nie maskuje tej wartości (to nie secret — OK, nie dodawać do maskowanych); (e) nie mylić z `GEMINI_MODEL` (dropdown cloud) — to są dwa różne selectory.
    - **Testy**: (1) unit backend: klucz w VALID_CONFIG_KEYS, save/clear round-trip (**asercja: empty NIE kasuje os.environ/.env wartości** — pułapka #1), GET /api/config go zwraca, 422 na garbage format; (2) ollama/status zwraca models (mock /api/tags); (3) frontend: selector renderuje wykryte modele, wybór persistence, warning off-list, dim przy gemini; (4) **E2E**: na serwerze jest już `gemma3:1b` (idealny kandydat!) — przestawić w GUI na gemma3:1b → job 27s → log `Local model chain: gemma3:1b ...` → wrócić na qwen3:4b-instruct; (5) setting przeżywa `docker restart` (config.json persisted); (6) ścieżka OOM: wybrać model >6GB (jeśli dostępny) → fallback/qwen → TextTiling (opcjonalny, možna pominąć).
    - **Nakład**: backend ~30-60 linii (config_store + schemas + testy; shim i pipeline bez zmian), frontend ~80-120 linii. **~1h + walidacja.** Kolejność: mały, niezależny — sensowny przed/przed n8n (pkt 4), nie blokuje pkt 9.
11. **[USER REQUEST 2026-11-09] Multi-account publishing („account manager"): różne shorts-y → różne konta YT (+ ew. TikTok / Instagram).** Feasibility zweryfikowana websearchem (2026-11-09, oficjalne docs) — **WYKONALNE; rekomendacja: n8n jako publisher + credential store (multi-credential), ClippyMe TYLKO wybór targetów w GUI (reguła GUI-first) + rozszerzenie payloadu webhooka o `clips[].targets`; NIE budować pełnego account managera w apce** (OAuth per platforma + token store + upload-clients ×3 = tygodnie pracy, duplikacja n8n). **Full plan: `PLAN-clippyme-multi-account-publishing.md`** (obok handoffu; decyzje usera D1: TikTok draft-vs-Upload-Post, D2: czy IG w ogóle). Kluczowe fakty z researchu: **YT private-lock ZNIESIONY (2 XI 2026)** + granular quota = **100 uploads/day/project** (koszt 1 unit; extension dopiero >100/day); multi-konto YT = kilka n8n-credentiali na TYM SAMYM OAuth client (każdy Connect = inne konto/kanał brand); **TikTok bez audytu = tylko private/SELF_ONLY (≤5 users/24h)** — public wymaga Direct Post audit (homelab typowo odrzucony) albo Upload-Post community node (ich audyt, multi-user, płatny/free tier), path bez audytu = draft/inbox API (user publikuje w apce); **IG tylko konta professional + FB Page** (dev mode bez App Review dla własnych kont, ~50 publikacji/24h rolling) i `video_url` kontenera MUSI być publiczny (LAN nieosiągalny dla serwerów Meta — powtórka pułapki 127.0.0.1). ~~Kolejność: najpierw TODO OAuth user (pkt 4) → V1 YT multi-account (~2-3h) → V2 TT/IG po decyzjach D1/D2~~ → **V1 ZROBIONE (2026-11-09 noc #7, patrz §3 pkt 19): backend `PUBLISH_TARGETS` + payload `targets` + GUI Settings→Automation→„Publish targets" + n8n workflow v2 „Multi-publish" (Route by targets, 2 gałęzie, cred #2 placeholder) — routing zweryfikowany runData, backward-compat legacy payloadu zachowany. REZIDUALNE (USER): OAuth connect OBU credentiali (pkt 3a planu) → potem realny walidacyjny job. V2 (TikTok/Instagram) = decyzje D1/D2 usera.**

12. **~~[USER REQUEST 2026-11-11 → NASTĘPNA SESJA, USER PRIORITY] FULL AUTOMATION: harmonogram Discover + dedupe przetworzonych filmów.~~ — ✅ ZROBIONE (2026-11-11 wieczór #8, patrz §3 pkt 21): scheduler ClippyMe-side (lifespan task, tick 30 s, tz Europe/Warsaw przez zoneinfo), rejestr dedupe `data/discovery_processed.json` (at-dispatch + backfill z source_info.json — 14 źródeł), 3 klucze `DISCOVERY_SCHEDULE_*` (GUI: Discover → Auto-discovery), endpointy `GET /api/discovery/schedule` + `POST /api/discovery/processed/forget`, webhook `discovery.scheduled_run`, GUI badge „already cut" + Hide-processed + status line. E2E live: 3 odpalenia (dispatch + 2× dedupe-skip), GUI screenshot. Stan: DISABLED — user ustawia query/godziny w GUI. Oryginalne notki projektowe (dla historii): Wymagania usera (verbatim-ish): (a) „setting time when the workflow (starting in discovery page) triggers" — automatyczne uruchamianie search→process z Discover o ustawionej godzinie (godzina/y KONFIGUROWALNE W GUI — reguła GUI-first z nagłówka!); (b) dedupe: „if the video that been selected previously was been cut to shorts, dismiss it, or tell me in some way" — film już pocięty ma być pomijany ALBO wyraźnie oznaczony.
    - **Stan wyjściowy (po sesji 2026-11-11):** Discover tab działa (`POST /api/search`, dry_run + dispatch; defaults `SEARCH_LIMIT`/`SEARCH_ORDER` w config.json — **query NIE jest persisted**, leci per-request); cały łańcuch uploadu OPERATIONAL (OAuth cred #1 podłączony, routing językowy EN/PL v3 w n8n — patrz §3 pkt 20); workflow n8n aktywny; `MAX_CONCURRENT_JOBS=1` (harmonogram musi liczyć się z kolejką).
    - **Otwarte decyzje projektowe (zweryfikować w nowej sesji):** (A) **Gdzie scheduler:** (1) ClippyMe-side (rekomendacja: reguła GUI-first — nowe klucze configu np. `DISCOVERY_SCHEDULE_ENABLED` / `DISCOVERY_SCHEDULE_CRON` / `DISCOVERY_SCHEDULE_QUERY` / `DISCOVERY_SCHEDULE_LIMIT` / `DISCOVERY_SCHEDULE_ORDER` + persisted `DISCOVERY_QUERY` lista zapytań, wewnętrzny scheduler w backendzie (asyncio loop / APScheduler) wołający tę samą ścieżkę co `POST /api/search dry_run=false` + dedupe na poziomie search) vs (2) n8n Schedule Trigger → HTTP `POST /api/search {dry_run:false,...}` (prostsze, ale konfiguracja godziny/query siedzi w n8n UI = słabiej GUI-first i dedupe musi iść po stronie searcha i tak). (B) **Tożsamość dedupe:** `/api/search` zwraca `video_id`; dispatch zapisuje URL (zawiera video_id) w job argv — porównywać po video_id/URL przeciwko historii jobów (na żywo z `/api/history`/output dirs albo dedykowany store przetworzonych id; zweryfikować co siedzi w `source_info.json` / metadanych joba). (C) **UX dedupe:** kandydaci już pocięci → badge „already cut" + checkbox disabled w Discover + filtr „hide processed"; scheduled run pomija je automatycznie + informacja (toast/log/webhook — user: „or tell me in some way"; kandydat: Discord webhook albo completion-style event).
    - **Testy:** unit dedupe-rankingu (mieszane fresh/processed), API search z flagą processed, GUI badge/filtr/checkbox, E2E scheduled run (zmockowany czas) → dispatch → upload → drugi run pomija te same video_id.
    - **Powiązane:** credential #2 nadal placeholder (polskie klipy ERROR-ują do czasu podłączenia — §3 pkt 20); ew. przejęcie „Send test event"/monitoringu.
13. **[USER REQUEST 2026-11-11 (noc, po incydencie quota §3 pkt 21)] Browser-upload na YouTube (Playwright, bez YT Data API v3) — PLAN GOTOWY (`PLAN-clippyme-browser-upload.md` obok; moduł uploadera już NAPISANY: `yt-browser-upload/`, ⚠️ NIE zweryfikowany E2E).** Motywacja: `uploadLimitExceeded` na kanale #1 — ścieżka przez UI Studio omija quota API. Architektura (sondy §0 planu): **host-serwis** (systemd, `192.168.100.2:8790`, serial queue, path-guard do `output/`) wołany przez n8n v4 (Code „Route by engine" wg `engine` w payloadzie — TYLKO gdy =="browser", byte-compat); ClippyMe TYLKO GUI setting `UPLOAD_ENGINE` (Settings → Automation, segmented) + proxy statusu sesji — wzorzec PUBLISH_TARGETS 1:1. Sondy: klipy `output/` czytelne dla `ai` (644, READ_OK), port 8790 wolny, python 3.12.3+venv OK, X jako `grejem` → pierwsze logowanie przez **`ssh -X ai@…`** (okno lokalnie u usera). Default = legacy `n8n-api` (deploy bez zmiany zachowania). Kolejność: **smoke uploader (BLOKADA)** → serwis → backend/GUI → n8n v4 → E2E.

---

## 8. Szybka ściąga komend

```bash
SSH='ssh -o BatchMode=yes ai@192.168.100.2'
TOK='096785f69980af041bfee3ccb674e419'
# status joba
$SSH "curl -s -H 'X-API-Token: $TOK' http://127.0.0.1:8000/api/status/<job_id>"
# restart backendu po zmianie .env
$SSH 'echo stbr | sudo -S -p "" docker restart clippyme-backend'
# logi rankingu (single-shot)
$SSH 'echo stbr | sudo -S -p "" docker logs clippyme-backend 2>&1 | grep "Job Output" | grep -E "🦙|Token Usage|TextTiling" | tail'
# logi chunked rankingu (długie wideo): per-okno postęp + merge
$SSH 'echo stbr | sudo -S -p "" docker logs clippyme-backend 2>&1 | grep "Job Output" | grep -E "Chunked ranking|window [0-9]+/|merged|hallucinated" | tail -30'
# historia zadań (po restarcie backendu /api/status zwraca 404 — używać /api/history!)
$SSH "curl -s -H 'X-API-Token: $TOK' http://127.0.0.1:8000/api/history | python3 -m json.tool | head -50"
# health GPU w kontenerze
$SSH 'echo stbr | sudo -S -p "" docker exec clippyme-backend python3 -c "import torch; print(torch.zeros(1).cuda())"'
# restart Ollamy (gdy modele przestają się ładować, a GPU wygląda wolnym)
$SSH 'echo stbr | sudo -S -p "" systemctl restart ollama'
# przełącznik rankingu local↔gemini (GUI preferred: Settings → Ranking engine; to samo przez API):
$SSH "curl -s -X POST -H 'Origin: http://192.168.100.2:5175' -H 'X-API-Token: $TOK' -H 'Content-Type: application/json' -d '{\"keys\":{\"RANKING_PROVIDER\":\"gemini\"}}' http://127.0.0.1:8000/api/config"
# health-check Ollamy server-side (reachable + models + effective provider):
$SSH "curl -s -H 'Origin: http://192.168.100.2:5175' -H 'X-API-Token: $TOK' 'http://127.0.0.1:8000/api/config/ollama/status?check=true'"
# panel Active jobs (cross-session; whitelist pól; używany przez GUI History):
$SSH "curl -s -H 'Origin: http://192.168.100.2:5175' -H 'X-API-Token: $TOK' http://127.0.0.1:8000/api/jobs/active | python3 -m json.tool"
# auto-napisy: toggle + preset (GUI preferred: Settings → Captions; to samo przez API):
$SSH "curl -s -X POST -H 'Origin: http://192.168.100.2:5175' -H 'X-API-Token: $TOK' -H 'Content-Type: application/json' -d '{\"keys\":{\"SUBTITLES_AUTO\":\"1\",\"SUBTITLE_PRESET\":\"classic_white\"}}' http://127.0.0.1:8000/api/config"
# wybór lokalnego modelu rankingu (GUI preferred: Settings → Ranking engine → Local model; empty = .env default):
$SSH "curl -s -X POST -H 'Origin: http://192.168.100.2:5175' -H 'X-API-Token: $TOK' -H 'Content-Type: application/json' -d '{\"keys\":{\"LOCAL_LLM_MODEL\":\"gemma3:1b\"}}' http://127.0.0.1:8000/api/config"
# MULTI-ACCOUNT: publish targets (GUI preferred: Settings → Automation → Publish targets; empty = legacy kanał #1):
$SSH "curl -s -X POST -H 'Origin: http://192.168.100.2:5175' -H 'X-API-Token: $TOK' -H 'Content-Type: application/json' -d '{\"keys\":{\"PUBLISH_TARGETS\":\"[\\\"yt-kanal-a\\\",\\\"yt-kanal-b\\\"]\"}}' http://127.0.0.1:8000/api/config"
# SCHLEUDER — status harmonogramu auto-discovery (next/last run; last_run = raport ostatniego odpalenia):
$SSH "curl -s -H 'X-API-Token: $TOK' -H 'Origin: http://192.168.100.2:5175' http://127.0.0.1:8000/api/discovery/schedule | python3 -m json.tool"
# SCHLEUDER — ustawienie harmonogramu (GUI preferred: Discover → Auto-discovery; GODZINY = Europe/Warsaw!):
$SSH "curl -s -X POST -H 'Origin: http://192.168.100.2:5175' -H 'X-API-Token: $TOK' -H 'Content-Type: application/json' -d '{\"keys\":{\"DISCOVERY_SCHEDULE_ENABLED\":\"1\",\"DISCOVERY_SCHEDULE_TIMES\":\"09:00,18:30\",\"DISCOVERY_SCHEDULE_QUERY\":\"italian comedy prank\"}}' http://127.0.0.1:8000/api/config"
# SCHLEUDER — logi scheduled runów + dedupe rejestracja:
$SSH 'echo stbr | sudo -S -p "" docker logs clippyme-backend 2>&1 | grep -E "Scheduled discovery|Discovery dedupe|scheduler armed" | tail -15'
# DEDUPE — forget video_id (re-dispatch źródła; 404 = nie było w rejestrze):
$SSH "curl -s -X POST -H 'Origin: http://192.168.100.2:5175' -H 'X-API-Token: $TOK' -H 'Content-Type: application/json' -d '{\"video_id\":\"<11-znakowe-id>\"}' http://127.0.0.1:8000/api/discovery/processed/forget"
# MULTI-ACCOUNT: ręczny test routingu w n8n (fake URL → error w nodzie Download WŁAŚCIWEJ gałęzi = routing OK):
curl -s -X POST http://192.168.100.2:5678/webhook/clippyme-job-completed -H 'Content-Type: application/json' -d '{"status":"completed","targets":["yt-kanal-a"],"clips":[{"viral_score":99,"published":false,"video_url":"http://192.168.100.2:8000/videos/<job>/<plik>.mp4","title":"T","description":"D"}]}'
# n8n — runData INSPEKCJA (które nody odpaliły; string-table: refs = indeksy płaskiej tablicy, flat[int(ref)]):
#   login (cookies) → GET /rest/executions/{id}?unflattened=true → data = JSON-string tablicy
#   runData = flat[int(flat[int(flat[0]["resultData"])]["runData"])]  → {node: [run,...]}
# VIDEO SEARCHER — dry run (sama lista kandydatów; bez X-Gemini-Key):
$SSH "curl -s -X POST -H 'X-API-Token: $TOK' -H 'Content-Type: application/json' -d '{\"query\":\"short comedy skit\",\"limit\":3,\"order\":\"popular\",\"min_duration\":15}' http://127.0.0.1:8000/api/search | python3 -m json.tool"
# VIDEO SEARCHER — dispatch top-N do pipeline'u (WYMAGA też X-Gemini-Key; dry_run=false):
$SSH "curl -s -X POST -H 'X-API-Token: $TOK' -H 'X-Gemini-Key: local-no-key' -H 'Content-Type: application/json' -d '{\"query\":\"short comedy skit\",\"limit\":1,\"order\":\"newest\",\"dry_run\":false}' http://127.0.0.1:8000/api/search | python3 -m json.tool"
# COMPLETION WEBHOOK — test round-tripu (wysyła sample payload na zapisany CALLBACK_WEBHOOK_URL):
$SSH "curl -s -X POST -H 'Origin: http://192.168.100.2:5175' -H 'X-API-Token: $TOK' http://127.0.0.1:8000/api/config/webhook/test | python3 -m json.tool"
# testy frontendu (Vite dev kontener ma node+deps; bind-mount → zawsze aktualny kod):
$SSH 'echo stbr | sudo -S -p "" docker exec clippyme-frontend npm test'
# testy backendu (pytest pipiem do kontenera = nie-trwałe przy recreate; token musi być pusty, bo dotenv go ładuje):
$SSH 'echo stbr | sudo -S -p "" docker exec -e CLIPPYME_API_TOKEN= clippyme-backend sh -c "pip install -q pytest && python3 -m pytest tests -q"'
# n8n — status + wersja:
$SSH 'echo stbr | sudo -S -p "" docker ps --filter name=n8n --format "{{.Names}} {{.Status}}" && docker exec n8n n8n --version'
# n8n — status workflow (N8NKEY = publiczny API key, header X-N8N-API-KEY; skopiuj z §3 pkt 18 / wygeneruj nowy w UI Settings → n8n API):
N8NKEY='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI5Y2QzZDRlOC1kYmYzLTQ2MjMtYjg3ZC04MjU1MWYwMmVhYTgiLCJpc3MiOiJuOG4iLCJqdGkiOiIxYTMzOWJlNS0zOTZhLTRiODUtYmNkYy0zNmE2NjQ3YTk5NzAiLCJpYXQiOjE3OTQxNzU4MjYsImV4cCI6MjE0NzQ4MzY0NywiYXVkIjoicHVibGljLWFwaSJ9.-8rlBd67Mmkd5zcpM4oYOtGhINqJd0HmJ7PRuzaHXrQ'
curl -s http://192.168.100.2:5678/api/v1/workflows/LpORWh7hK3bmiHI3 -H "X-N8N-API-KEY: $N8NKEY" | python3 -m json.tool | head -5
# n8n — (re)aktywacja workflow po PUT/update (PUT ZAWSZE dezaktywuje!):
curl -s -X POST http://192.168.100.2:5678/api/v1/workflows/LpORWh7hK3bmiHI3/activate -H "X-N8N-API-KEY: $N8NKEY" -H 'Content-Type: application/json' -d '{}'
# n8n — podgląd wykonań (publiczny /api/v1/executions bywa Forbidden! → login + WEWNĘTRZNY endpoint):
curl -s -c /tmp/n8n_cookies.txt -X POST http://192.168.100.2:5678/rest/login -H 'Content-Type: application/json' -H 'browser-id: dbg' -d '{"emailOrLdapLoginId":"kacperlipiec123@gmail.com","password":"kuzkaA123"}' -o /dev/null
curl -s -b /tmp/n8n_cookies.txt -H 'browser-id: dbg' 'http://192.168.100.2:5678/rest/executions?limit=5' | python3 -c "import json,sys; [print(e['id'],'|',e['status']) for e in json.load(sys.stdin)['data']['results']]"
# n8n — ręczny test webhooka (omija ClippyMe; score 99 = PASS przez filtr, 80 = DROP):
curl -s -X POST http://192.168.100.2:5678/webhook/clippyme-job-completed -H 'Content-Type: application/json' -d '{"status":"completed","clips":[{"viral_score":99,"published":false,"video_url":"http://192.168.100.2:8000/videos/<job>/<plik>.mp4","title":"T","description":"D"}]}'
# lustrzana kopia workflow (update: PUT /api/v1/workflows/{id} + activate):
#   ~/Dokumenty/Projekty/Serwer/clippyme-n8n-workflow-youtube.json
```

## 9. PLAN IMPLEMENTACJI — chunked ranking dla długich wideo (ZWERYFIKOWANY, GOTOWY)

> **STATUS 2026-11-08 (wieczór): ZIMPLEMENTOWANY — patrz §3 pkt 12. Wszystkie testy
> §9.5 zielone. Odchylenia od planu (celowe, opisane w kodzie): (a) estymator tok
> komponentowy `estimate_tokens_for()` zamiast chars×0.68 (planowy zawyżał template
> i misroutingował krótkie wideo); (b) THRESHOLD 8000 nie 6000 (realny 27s = est
> 6092 > 6000 — za ciasno); (c) `_clamp_clip_to_window` DROPuje klipy w całości
> poza oknem (hallucynacje — smoke test je wykrył), klipy brzegowe clampuje;
> (d) generate_chunked bierze `creator=os.getenv(...)` inline.**

> Lustrzana kopia: `PLAN-clippyme-chunked-ranking.md` (obok handoffu; tam wykonywać
> edycje — sekcje ponumerowane 0-9). Status: wszystkie założenia sprawdzone sondami
> na żywym Ollama (6 probe'ów, 11 wywołań, 2026-11-08). Brak otwartych hipotez.

### 9.0 WERYFIKACJA WSTĘPNIA (sondy — wszystko zmierzone, nie teoria)

| # | Sonda | Wynik |
|---|---|---|
| 1 | VRAM baseline | 337/6144 MiB użyte (gnome-remote-desktop 86 MiB) — ogromny zapas |
| 2 | `num_ctx=16384` realnie | **VRAM peak 4171 MiB** ✅ (~2 GB headroom), działa na żywym Ollama |
| 3 | Tokeny: kalibracja 1-decimal TOON | **~17,7 tok/wiersz** + template ~4,4k; 570 wierszy = 13,5k tok |
| 4 | Precyzja znaczników czasu | 1-decimal = **−18% tok** vs 3-dec; integer = −36%, ALE ±0,5s zjada 0,6s tolerancji snap (`DEFAULT_MAX_SNAP=0.6`, `cut_ops.py:26`) → **wybrano 1-decimal** |
| 5 | Latencja / window (450-570 wierszy) | 13-23s (load 3-4s, prefill 5-8s, decode 9-11s) → **55 min wideo ≈ 6 min rankingu** (17-18 okien) |
| 6 | **minItems:1 w schema (Ollama grammar)** | **DZIAŁA** — wymusza ≥1 klip/okno; bez tego 4B zwraca `{"shorts":[]}` (sonda 2/3: 0 klipów wszędzie) |
| 7 | Template skrócony (bez włoskich przykładów) | język OK, ALE **klipy degeneracyjne 0,6-3,1s** ❌ → 4B POTRZEBUJE pełnego template (pełny = klipy 79-97s ✅) |
| 8 | `done_reason:"length"` przy num_predict=1024 | content EMPTY → **retry ratuje** (attempt 2: OK, 293 tok) → retry obowiązkowy |
| 9 | Język tytułów na polskim transkrypcie | pełny template = mieszanka PL/włoski; wzmianka w headerze pomaga częściowo → **znane ograniczenie** (§9.7) |

**Finalna konfiguracja okna (zweryfikowana end-to-end na 3 oknach):**
```
rows/window = 450, overlap = 60 rows (~30s)
TOON 1-decimal, transcript_text = wycinek okna (kontekst narracyjny)
schema = CLIP_JSON_SCHEMA + shorts.minItems=1
num_ctx=16384, temperature=0.3, num_predict=1536
template = PEŁNY GEMINI_PROMPT_TEMPLATE + WINDOW_HEADER (przed template)
retry: empty content / done_reason==length / invalid JSON → 1 powtórka (sleep 3)
→ potem deterministyczna naprawa w _salvage_clip (istnieje!) + snap-to-words (istnieje!)
```

### 9.1 ARCHITEKTURA (co gdzie leci)

```
get_viral_clips (main.py)
  ├─ build_viral_prompt(...)                      [bez zmian]
  ├─ estimate = est_tokens(prompt)                [NOWE, gemini_request.py]
  ├─ if isinstance(client, LocalLLMClient) and est > THRESHOLD:
  │     response = local_llm.generate_chunked(    [NOWE, local_llm.py]
  │         client, windows, video_duration, instructions, creator)
  │       └─ per okno: build_viral_prompt_window  [NOWE, gemini_request.py]
  │            → client.models.generate_content   [bez zmian interfejsu]
  │            → _salvage_clip per klip           [istnieje]
  │            → merge: dedupe IoU>0.35, sort score, top-K
  │       (response w tym samym formacie _Response — parser dalej bez zmian)
  ├─ else: generate_with_model_fallback(...)      [bez zmian]
  └─ TextTiling fallback                          [bez zmian — gdy chunking raise]
```

Zasada: **ścieżka Gemini i parser NIE są ruszone** (gate: `isinstance`). Wszystkie
naprawy timingów/języka deterministyczne w istniejącym `_salvage_clip` + snap.

### 9.2 ZMIANY PER PLIK

**2a. `src/clippyme/pipeline/analysis/gemini_request.py` (+~90 linii, pure/host-testable)**
```python
WINDOW_HEADER = """..."""   # window i/N, 1-3 clips FROM WINDOW, absolute standards,
    # >=15s anti-bug, LANGUAGE HARD reinforcement (BEZ nazwania języka na sztywno)

def estimate_prompt_tokens(prompt: str) -> int:
    """Kalibracja z sonda: 246111 chars -> 167292 tok (Ollama qwen3 tokenizer).
    Zachowawczo: chars * 0.68 (=167292/246111)."""

def plan_windows(words, target_rows=450, overlap_rows=60) -> list[tuple[int,int]]:
    """[(start_row, end_row)] contiguity + overlap; ostatnie okno doklejone do końca."""

def build_viral_prompt_window(transcript_result, words, i, n, t0, t1,
                              video_duration, instructions=None, creator=None) -> str:
    """HEADER + GEMINI_PROMPT_TEMPLATE.format(...) z:
    - transcript_text = ' '.join(words okna)  (kontekst, ~1.1k tok)
    - words_toon = TOON okna z s/e zaokrąglonymi do .1f
    - fences dla instructions (reuse istniejącej logiki untrusted)"""
```

**2b. `src/clippyme/pipeline/analysis/local_llm.py` (+~110 linii)**
```python
WINDOW_SCHEMA = deepcopy(CLIP_JSON_SCHEMA); WINDOW_SCHEMA[...]["shorts"]["minItems"]=1

def generate_chunked(client, words, video_duration, instructions, creator) -> _Response:
    """1. windows = plan_windows(words)
    2. per okno (progress log: '🦙 window i/N t0-t1s → k clips (wall Xs)'):
       - prompt = build_viral_prompt_window(...)
       - response = client.models.generate_content(...)
         (_generate rozszerzone o param schema=... — okna dają WINDOW_SCHEMA)
       - done_reason=="length" lub pusty/invalid content → sleep(3) + 1 retry;
         dalej raise → okno skipped (logged)
       - _salvage_clip na każdym klipie
       - NOWE w salvage: hook==title → hook = first 6 words of viral_reason
    3. merge: dedupe overlap (IoU>0.35 keep wyższy score), sort score desc,
       cap LOCAL_LLM_FINAL_TOPK (8)
    4. usage = suma tokenów wszystkich okien
    5. raise RuntimeError jeśli >50% okien fail → TextTiling fallback
    return _Response(json.dumps({"shorts": merged}), usage.pt, usage.ct)"""
```

**2c. `src/clippyme/pipeline/main.py` (~12 linii w get_viral_clips)**
Po `build_viral_prompt(...)`, PRZED `generate_with_model_fallback`:
```python
if isinstance(client, LocalLLMClient) and \
        estimate_prompt_tokens(prompt) > int(os.getenv("LOCAL_LLM_CHUNK_THRESHOLD_TOKENS", "6000")):
    from clippyme.pipeline.analysis.local_llm import generate_chunked
    response = generate_chunked(client, words, video_duration, instructions, creator)
else:
    response, model_name = generate_with_model_fallback(...)
```

**2d. Header językowy** (lesson sonda 5→6): NIE hardcodować "POLISH" — wykrywanie
języka kruche. Formuła: *"EVERY text field MUST be in the SAME LANGUAGE as the
transcript window below. The example titles in this prompt are FORM PATTERNS only —
copy their structure, never their language."*

### 9.3 MACIERZ BŁĘDÓW

| Sytuacja | Reakcja |
|---|---|
| prompt okna > ctx (400 "exceeds") | nie powinno wystąpić (450 rows ≈ 8.7k+4.4k < 16384); gdyby: retry z rows/2 dla TEGO okna |
| done_reason=="length" / pusty content | sleep 3 + retry ×1 → potem skip okna (log ⚠️) |
| Ollama down (conn refused) | raise natychmiast → TextTiling fallback (jak dziś) |
| >50% okien failed | raise → TextTiling fallback |
| degenerate timing (<10s/>75s) | _salvage_clip (naprawa istniejąca; sonda potwierdza że potrzeba realna) |
| klipy z timami poza oknem | clamp do [t0,t1] w salvage okna |
| duplikaty między oknami (overlap) | dedupe IoU>0.35 keep wyższy score |
| VRAM OOM (inny proces np. Whisper) | istniejąca ścieżka OOM w _generate (halve ctx → fallback model) per okno |

### 9.4 CONFIG (nowe zmienne .env, wszystkie z defaults — zero breaking changes)
```
LOCAL_LLM_CHUNK_THRESHOLD_TOKENS=6000   # est > to → chunked path
LOCAL_LLM_NUM_CTX=16384                 # (było 8192; VRAM potwierdzony 4171 MiB peak)
LOCAL_LLM_WINDOW_ROWS=450
LOCAL_LLM_WINDOW_OVERLAP_ROWS=60
LOCAL_LLM_CHUNK_TOPK=3                  # klipów per okno (w headerze)
LOCAL_LLM_FINAL_TOPK=8                  # globalny cap po merge
LOCAL_LLM_CHUNK_RETRIES=1
```
Po zmianie .env: `sudo docker restart clippyme-backend` (stale env, §6).

### 9.5 TESTY (kolejność)
1. **Offline unit (host python3, bez GPU)** — skrypt scp-em (wzorzec §6):
   plan_windows na 6852 wierszy (kontiguity/overlap/budget), estimate (246k chars
   → est ≥ 100k > threshold), merge IoU-dedupe na syntetycznych klipach.
2. **Smoke 1 okna w kontenerze** (docker exec): prompt okna → generate_content
   → JSON valid, ≤16k tok, klip w oknie.
3. **E2E długie wideo**: reprocessing TEGO SAMEGO filmu (Costa Rica 55 min) przez
   **upload cache'owanego źródła** `output/9d84798e*/Zakochałem…mp4` (2.4 GB, omija
   yt-dlp 403) → oczekiwane: logi '🦙 window i/17', brak 400, score ≥1, tytuły PL,
   duration 10-75s. Porównanie z runem TextTiling (12 × score 0 „part N").
   **→ WYKONANE 2026-11-08 wieczór z modyfikacją: źródło 2.4 GB już nie istnieje
   (wyczyszczone z dysku), więc ranking-stage zwalidowano bezpośrednio na realnym
   cache'owanym transkrypcie w kontenerze (18 okien, §3 pkt 12). Rezyduum: pełny
   E2E z renderem klipów przy najbliższym long-form uploadzie.**
4. **Regression krótkie wideo**: ten sam 27s URL co job `196b2979` → single-shot
   path (est < threshold), wyniki porównywalne (score 87-92).
5. **VRAM watch podczas E2E**: `nvidia-smi` — peak < 5.5 GB (buffer dla Whispera).

### 9.6 ROLLOUT / ROLLBACK
- Edycje = bind-mount live, ale python importy mrożą się na starcie procesu →
  **`docker restart clippyme-backend`** po zmianach (FS przetrwa; yt-dlp upgrade
  przetrwa — tylko recreate czyści).
- Rollback: `git checkout -- <3 pliki>` + restart (repo = clone git; najpierw `git diff`).
- Gate `isinstance + threshold` = krótkie wideo NIE zmienia ścieżki (test 4).

### 9.7 ZNANE OGRANICZENIA (akceptowane v1, NIE bugi)
1. **Mieszanka językowa tytułów** na nie-włoskich transkryptach (przykłady w
   template = silny anchor dla 4B). Mitigacja v2: LOCAL_TEMPLATE bez przykładów
   + minItems (sonda 6: koszt = degeneracyjne czasy; osobne zadanie).
2. **hook == title** czasem → deterministyczny fix w salvage (§9.2b).
3. **Duration overshoot** 79-97s → trim do 75s w salvage; snap poprawia koniec w 0.6s.
4. **Copy quality < Gemini** — najsłabsze ogniwo; UI toggle Local↔Gemini (§7 pkt 7)
   pozostaje planowany jako escape hatch jakości.
5. Latencja: ~6 min rankingu / 55 min wideo — akceptowalne, log per okno.

### 9.8 NAKŁAD PRACY
~200 linii w 3 plikach + testy. Implementacja 1.5-2h, E2E walidacja ~1h
(processing 55-min wideo przez pipeline ~35 min).

### 9.9 ARTYFAKTY SONDU (usunięte z serwera; wyniki w powyższych tabelach)
probe 1: VRAM/tokens/precision · probe 2: empty-array trap · probe 3: headroom
456 tok za mały → rows 450 · probe 4: minItems działa + retry · probe 5: final
config (pełny template + header) · probe 6: trimmed template odrzucony.

---

---

## 10. PLAN IMPLEMENTACJI — Video Searcher + Completion Webhook (2026-11-08 noc #5, TA SESJA)

> **STATUS: ZIMPLEMENTOWANY I PRZETESTOWANY (§3 pkt 17) — backend 417/417,
> frontend 391/8-fontowe, E2E live search→dispatch→webhook delivery ✓, GUI ✓.
> Pozostało TYLKO: n8n install + workflow (pkt 5-6 poniżej) — decyzja usera: LAST.**

> Wymagania usera (2026-11-08): (1) „video searcher" triggerowany przez API — n8n
> woła event, ClippyMe szuka najnowszych/najpopularniejszych filmów YT po query,
> i dla listy (liczba KONFIGUROWALNA) startuje processing; (2) droga przekazania
> gotowych shortsów do n8n (nie musi być Google Drive); (3) ranking provider
> zmienialny z aplikacji LUB z n8n; (4) **konfiguracja n8n = OSTATNI krok**.
> Rozbudowany plan + sondy: `PLAN-clippyme-video-searcher-webhook.md`.
> Sondy (weryfikacja): POST /api/config działa token-only (200); yt-dlp search
> `ytsearch3:` i results-URL `sp=CAI%3D` działają w kontenerze (flat mode zwraca
> view_count+duration); lucide-react 0.344 MA ikony Search + Webhook.

### 10.1 Feature A — `POST /api/search`
- NOWY plik `src/clippyme/integrations/youtube_search.py`: `search_candidates(query, order, fetch)`
  (lazy import yt_dlp, `extract_flat=True`, cookiefile z `_resolve_cookies_path`,
  popular=`ytsearch{fetch}:{query}`, newest=`.../results?search_query=...&sp=CAI%3D`;
  wyciąga url/title/channel/view_count/duration), czysty `filter_and_rank(candidates, limit, order,
  min_duration, max_duration)` (host-testable, NA view_count = 0 przy sortcie popular),
  `search_videos(...)` z oversample `min(limit*4, 30)`.
- `storage/config_store.py`: nowe klucze **`SEARCH_LIMIT`** (default „3"), **`SEARCH_ORDER`**
  („popular"/„newest"), **`CALLBACK_WEBHOOK_URL`** (empty=disabled), **`PUBLIC_BASE_URL`**
  (empty=relative URLs w webhooku) + czyste resolve'y `resolve_search_defaults(env)`,
  `resolve_webhook_url(env)`, `resolve_public_base_url(env)` (wzorzec
  `resolve_ranking_provider`).
- `api/schemas.py`: `SearchRequest` (query 1..200, limit 1-10, order pattern,
  min/max_duration 0..36000, dry_run bool=True) + 4 klucze w `_ALLOWED_CONFIG_KEYS`
  + walidacje (SEARCH_LIMIT cyfry, SEARCH_ORDER enum, webhook/base URL http-s).
- `api/app.py`: endpoint `POST /api/search` — `require_trusted_config_request` +
  rate-limit „search" (cap 10 / 30s); search w `asyncio.to_thread`; `SearchError`→502;
  `dry_run=false` → dispatch pętla 1:1 z /api/batch (własny job_id, OUTPUT_DIR,
  build_main_cmd, submit_job; **wymaga nagłówka X-Gemini-Key jak /api/process**).
- GUI: NOWY tab **„Discover"** (`features/discovery/discovery.jsx` + `headers.jsx` TABS):
  formularz (query/order/limit/duration) → lista kandydatów z checkboxami →
  „Process selected": 1 sztuka → `handleProcess` (attach ProcessingView), >1 →
  `handleBatchProcess`; defaults z `GET /api/config` (SEARCH_LIMIT/ORDER).
  `client.js`: `searchVideos(payload)`.

### 10.2 Feature B — Completion webhook
- NOWY plik `src/clippyme/jobs/completion_webhook.py`: czysty
  `build_completion_payload(job_id, status, result, base_url)` (WHITELIST pól —
  nigdy env/argv/ścieżki; clips z `result["clips"]`: index/filename/video_url
  absolutne/title/description/viral_score/duration) + `post_webhook(url, payload,
  timeout)` (urllib, zwraca ok/code/snippet) + `fire_completion_webhook(..., retries=(5,30,60))`
  (best-effort, NIGDY nie raise) + `notify_job_terminal(...)` (asyncio.create_task
  z referencją w module-level set — fire-and-forget).
- Hook: `jobs/job_runner.py` w bloku `finally` run_job — fire TYLKO gdy
  `job["status"] in job_control.TERMINAL_STATES` (cancelled/stopped/failed/completed;
  shutdown-CancelledError = status nie-terminalny → nie fire; skip-dispatch już-terminalnych
  jobów = fire OK, bo to ich pierwsze przejście do terminalnego w tym przebiegu).
- `api/config_routes.py`: NOWY `POST /api/config/webhook/test` — wysyła sample
  payload na zapisany URL (timeout 6s, bez retry), zwraca ok/status_code/response.
- GUI (Settings): NOWY Panel **„Automation"**: wiersz „Completion webhook" (input URL
  + przycisk Test) + wiersz „Public base URL" (absolutne linki w webhooku) +
  wiersz „Search defaults" (limit + Segmented Popular/Newest). `client.js`: `testWebhook()`.

### 10.3 Ranking provider z n8n — JUŻ DZIAŁA
`POST /api/config {"keys":{"RANKING_PROVIDER":"local"|"gemini"}}` z samym `X-API-Token`
= 200 (sonda). n8n: Set → POST config → dispatch. Zero zmian w kodzie.

### 10.4 Kolejność + testy (n8n LAST — decyzja usera)
1. Backup: `.backup-20261108-searcher-webhook/` (wszystkie modyfikowane pliki).
2. Backend A (module/config/schemas/endpoint) + testy (`tests/api/test_search_api.py`
   z mockiem `_extract`, config testy w istniejących plikach).
3. Backend B (webhook module + job_runner hook + test endpoint) + testy
   (`tests/jobs/test_completion_webhook.py`).
4. Frontend: Discovery tab + Settings Automation + client.js + testy.
5. Deploy: scp → `docker restart clippyme-backend`; pytest w kontenerze
   (`-e CLIPPYME_API_TOKEN=`); `npm test` (baseline 379 passed / 8 font FAIL).
6. Live E2E: curl /api/search dry_run=true (real YT); dry_run=false limit 1
   (job + webhook receiver `python3 http.server`-owy na serwerze); GUI w przeglądarce.
7. Aktualizacja: n8n doc (jest STARE — qwen2.5:7b, brak /api/search/webhook), handoff,
   PLAN doc status.
8. (osobny krok, po userze) n8n install LAN + workflow — POZA tą sesją chyba że user powie.

### 10.5 Pułapki
- (a) search endpoint: NIE wymagać X-Gemini-Key przy dry_run (czysta metadata);
  wymagać przy dispatch (kontrakt jak /api/process).
- (b) webhook fire w `finally` — po `_notify()`; payload budować z `job.get("result")`
  (ma clips z video_url po `_build_clips`); failed bez resultu → clips: [].
- (c) yt_dlp import LAZY w youtube_search (host pytest nie ma yt_dlp — mock `_extract`).
- (d) rate-limit bucket „search" osobny (search = ~5-15s CPU+net).
- (e) Discovery tab nie może rozjechać goTab/resetToCreate (goTab('create') resetuje
  tylko create-flow stany — discovery bez własnych przejść).

Koniec handoffu — nowa sesja: §9 jest ~~do implementacji~~ **ZROBIONY (§3 pkt 12)**;
przełącznik Local↔Gemini **ZROBIONY (§3 pkt 13)** — zmieniaj provider z GUI (Settings →
Ranking engine), nie przez .env. Auto-napisy **ZROBIONE (§3 pkt 14)** — toggle/preset
w GUI (Settings → Captions). Panel Active jobs **ZROBIONY (§3 pkt 15)** — podgląd
wszystkich jobów serwera + kontrolki w GUI (History). Wybór modelu Ollama z GUI
**ZROBIONY (§3 pkt 16)** — Settings → Ranking engine → „Local model" (per-job bez
restartu). **§10 Video Searcher + Completion Webhook ZROBIONE (§3 pkt 17, noc #5):
`POST /api/search` + tab Discover + completion webhook (Settings → Automation) + 4 nowe
klucze configu.** **n8n + workflow „ClippyMe → YouTube Shorts" ZROBIONE (§3 pkt 18,
noc #6): kontener 2.46.6 (dual-bind LAN+loopback), workflow aktywny, webhook przepięty
(CALLBACK_WEBHOOK_URL → n8n).** **MULTI-ACCOUNT V1 ZROBIONE (§3 pkt 19, noc #7):
`PUBLISH_TARGETS` (backend + GUI: Settings → Automation → „Publish targets") +
`targets` w payloadzie webhooka + workflow v2 „ClippyMe → Multi-publish" (Route by
targets → gałąź per kanał; cred #2 „ClippyMe 2" = placeholder `ss3URXj0WgSuoJO0`) —
backward-compat legacy payloadu zweryfikowany runData.**
Następne w kolejności: **(1) FULL AUTOMATION — harmonogram Discover (godzina w GUI) + dedupe przetworzonych filmów = NOWY TASK §7 pkt 12 (USER PRIORITY, start nowej sesji). (2) OAuth credential #2 (`yt-kanal-a`, kanał polski) — TE SAME clientId/secret + Connect na drugie konto (credential #1 ZROBIONY 2026-11-11, §3 pkt 20; upload walidowany F466B7KHpus; routing EN/PL już aktywny — polskie klipy ERROR-ują do czasu podłączenia #2)** → opcjonalnie targets w GUI → walidacyjny realny job, pkt 2 (odpowiedź user 403/cookies), pkt 5 (konta Google), **V2 multi-account (TikTok/Instagram) po decyzjach D1/D2 usera — plan §4.**
Test receiver webhooka: OBSOLETE (CALLBACK_WEBHOOK_URL przepięty na n8n noc #6;
`/tmp/webhook_recv.py` i tak znika po reboot).
Przy najbliższym
long-form uploadzie: pełny E2E z renderem (rezyduum z §3 pkt 12) + napisy (rezyduum
z §3 pkt 14). **Akcja z pkt 16 WYKONANA (2026-11-08): realny klucz Gemini z powrotem
w config.json (GET maskuje jako „AQ.A...9lTg" — user zrobił clear+re-paste z
localStorage).** Każdy nowy task = GUI first (reguła z nagłówka).
