# PLAN — Full automation: harmonogram Discover + dedupe przetworzonych filmów

> **STATUS 2026-11-11 (późny wieczór): ZIMPLEMENTOWANY I PRZETESTOWANY E2E + GUI —
> lustrzany opis w `HANDOFF-clippyme-homelab.md` §3 pkt 21 (tam też odchylenia od
> planu: 1) TZ-fix — kontener UTC vs host CET → `now_local()` na zoneinfo
> Europe/Warsaw zamiast naive local; 2) `skipped_processed` przy full-skip zwraca
> 200 (nie 400); 3) docs-reference test naprawiony przy okazji (26 brakujących
> env-vars w configuration.md, w tym 23 pre-existing). Backend 34/34 nowe + pełny
> suite 1997/2 (docs-test FIXED, ffmpeg-resume = pre-existing flake); frontend
> discovery 13/13, full 402/8 baseline. E2E live: 3 scheduled fires (1 dispatch +
> 2 dedupe-skips), GUI screenshot. Stan końcowy: DISABLED (user ustawia w GUI).**

> Data: 2026-11-11 · Status: **FEASIBILITY + STAN ZWERYFIKOWANE sondami na żywym
> serwerze (2026-11-11 wieczór, §0)** — plan gotowy do wykonania przez nową sesję
> bez dodatkowego kontekstu. Lustrzany wpis: `HANDOFF-clippyme-homelab.md` §7 pkt 12.
>
> Wymagania usera (verbatim-ish, [USER PRIORITY → NASTĘPNA SESJA]):
> (a) „setting time when the workflow (starting in discovery page) triggers" —
> automatyczne uruchamianie search→process z Discover o ustawionej godzinie
> (godzina/y KONFIGUROWALNE W GUI — reguła GUI-first z nagłówka handoffu);
> (b) „if the video that been selected previously was been cut to shorts, dismiss it,
> or tell me in some way" — film już pocięty ma być pomijany ALBO wyraźnie oznaczony.
> ROZWIĄZANIE: oba — scheduled run POMIJA przetworzone (auto), GUI pokazuje badge
> „already cut" + checkbox disabled (informacja), scheduled run raportuje wynik.

---

## 0. WERYFIKACJA WSTĘPNA (sondy 2026-11-11 — zmierzone, nie teoria)

| # | Sonda | Wynik |
|---|---|---|
| 1 | SSH + backend | ✅ żywy; `/api/history` 200, 32 joby w historii |
| 2 | **`/api/history` shape** | item = `{clipCount, clips, cost, jobId, publishedCount, source, status, timestamp, title}` — **`source` to LABEL (tytuł), NIE URL** → dedupe NIE może iść z historii API |
| 3 | **`output/<job>/source_info.json`** | jest przy jobach URL: `{uploader_id, channel_url, webpage_url (z video_id!), banner}`; joby `fe5454a1`/`ff97ad61` (włoskie) go NIE mają, bo to **uploady plikowe** (mają pliki w `uploads/`) — mystery solved; `download.py:204-229` pisze sidecar best-effort przy KAŻDYM downloadzie URL (`_write_source_info`) |
| 4 | **`/api/search` candidates** | `video_id` ZAWSZE obecny (`youtube_search.py::_to_candidate` zwraca None bez id; url normalizowany do `watch?v=`) → **kandydat ma identyfikację dedupe za darmo** |
| 5 | **Dispatch choke points** | `app.py`: `/api/process` ~:432, `/api/batch` ~:487, `/api/search` dispatch ~:580 — wszystkie robią `build_main_cmd` + `submit_job` → 3 miejsca rejestracji (wspólny helper) |
| 6 | **FastAPI lifespan** | `app.py:141`; istniejące taski tła :164-171 (`process_queue`, `cleanup_jobs`, `background_updater_loop`) → scheduler = kolejny `asyncio.create_task`, wzorzec 1:1 |
| 7 | config_store | grupa „Automation" w `VALID_CONFIG_KEYS` istnieje (`SEARCH_LIMIT`, `SEARCH_ORDER`, `CALLBACK_WEBHOOK_URL`, `PUBLIC_BASE_URL`) → nowe klucze dokładnie tamże |
| 8 | TZ serwera | **Europe/Warsaw (CET)** → lokalny `datetime.now()` bez stref LOLIPOP jest OK (harmonogram = czas serwera = czasu usera) |
| 9 | `GEMINI_API_KEY` przy dispatchu | endpoint bierze klucz z nagłówka HTTP; **scheduler musi czytać `config.json`** (env procesu bywa dummy `local-no-key` — landmine §3 pkt 16 handoffu; przy `RANKING_PROVIDER=local` dummy jest OK, E2E-proven) |
| 10 | `MAX_CONCURRENT_JOBS=1`, queue 50 | scheduled run N jobów = kolejka FIFO; journal requeue po restarcie (istniejące) — zero dodatkowej pracy |

**Wniosek:** dedupe po **`video_id`** (z kandydatów searcha), rejestr persistowany w
`data/`, uzupełniany (a) at-dispatch w 3 choke points, (b) backfill scanem
`output/*/source_info.json` przy starcie (pokrywa joby sprzed feature'u).
Scheduler = **po stronie ClippyMe** (decyzja A: reguła GUI-first — godzina/query w
dashboardzie, nie w n8n UI; dedupe i tak musi siedzieć po stronie searcha).

---

## 1. ARCHITEKTURA

```
Discover (GUI: „Auto-discovery" panel: ON/OFF, godziny, query)   → config.json (3 nowe klucze)
   ClippyMe backend — lifespan task `discovery_scheduler_loop` (tick 30 s, local time)
        ├─ tick: resolve_discovery_schedule(config) → enabled? HH:MM ∈ times? (nie odpalony dziś?)
        ├─ RUN: TA SAMA ścieżka co POST /api/search dry_run=false (wspólny helper):
        │    search_videos → filter_and_rank → DEDUPE (rejestr video_id)
        │    → dispatch świeżych (cap limit) → raport {dispatched, skipped_processed}
        ├─ raport: GET /api/discovery/schedule (GUI poll) + event webhooka do n8n (tylko scheduled)
        └─ nigdy nie raise (best-effort, log)
Rejestr przetworzonych: data/discovery_processed.json (video_id → {job_id, url, title, dispatched_at})
   ├─ at-dispatch: /api/process + /api/batch + /api/search (3 choke points, wspólny register)
   ├─ backfill: lifespan scan output/*/source_info.json (webpage_url → video_id, job_id = dirname)
   └─ cap 500 wpisów (FIFO prune), atomowy write (wzorzec journal/config_store), 0600
```

Zasady spójne z systemem: **config.json = source of truth** (scheduler czyta
`load_persistent_config()` bezpośrednio co tick — odporność na stale-env §6 handoffu);
n8n **ZERO zmian** (event `discovery.*` przepływa przez istniejący Webhook → „Filter
clips" i znika jako 0 items — harmless no-op, zweryfikowane zachowanie filtra).

## 2. ZMIANY PER PLIK

### 2a. NOWY `src/clippyme/storage/discovery_registry.py` (~120 linii, pure/host-testable — ścieżki iniekowane)
```python
def extract_video_id(url: str) -> Optional[str]:
    """youtube.com/watch?v=, youtu.be/, /shorts/, /embed/, m.youtube → id; else None."""

def load_registry(path) -> dict            # corrupt/garbage → {} (wzorzec _read_raw_config)
def save_registry(path, registry) -> None  # atomowy tmp+os.replace+fsync+chmod 0600 (wzorzec journal)
def register_dispatch(registry, video_id, url, title, job_id, now=None) -> dict  # + prune(500)
def processed_video_ids(registry) -> set
def forget_video(registry, video_id) -> dict    # manualny override (false-positive)
def backfill_from_output(output_dir, registry, now=None) -> dict
    # scan <output>/*/source_info.json → webpage_url → video_id → wpis {job_id: dirname};
    # istniejący wpis NIE nadpisywany; brak source_info.json = skip (uploady)
```

### 2b. NOWY `src/clippyme/jobs/discovery_scheduler.py` (~150 linii)
```python
def due_times(times: list[str], now: datetime, last_fired: dict) -> list[str]:
    """Pure: HH:MM pasujące do now (±tick) i niewystrzelone dziś (last_fired[HH:MM]==date)."""

async def discovery_scheduler_loop(context) -> Never:
    # tick 30s; config = load_persistent_config() (ŹRÓDŁO PRAWDY, nie os.environ!);
    # sched = resolve_discovery_schedule(config+env); jeśli disabled/query pusty → sleep;
    # due = due_times(...); async with _RUN_LOCK (no overlap): run_scheduled_once(...)
    # wszytko w try/except → log ⚠️, NIGDY fatal (wzorzec ae_updater_task)

async def run_scheduled_once(context) -> dict:
    # 1) search_videos (asyncio.to_thread, reuse integrations) → filter_and_rank
    # 2) dedupe: fresh = [c for c in selected if video_id ∉ processed_video_ids(registry)]
    # 3) dispatch fresh przez WSPPÓLNY helper dispatch_candidates (2d) — cap limit
    # 4) raport {dispatched: [...], skipped_processed: N, query, at}
    # 5) notify: POST CALLBACK_WEBHOOK_URL {"event":"discovery.scheduled_run", ...}
    #    reuse completion_webhook.post_webhook (no-retry fire-and-forget wystarczy v1)
    # 6) last_result → in-memory state (poll GUI); brak fresh → dispatch 0, raport skipped
```

### 2c. `src/clippyme/storage/config_store.py` — 3 nowe klucze w `VALID_CONFIG_KEYS` (grupa Automation)
```python
"DISCOVERY_SCHEDULE_ENABLED"   # "1"/"0", empty = 0 (default OFF)
"DISCOVERY_SCHEDULE_TIMES"     # "HH:MM[,HH:MM...]" max 12, empty = brak okien
"DISCOVERY_SCHEDULE_QUERY"     # query scheduled runów, ≤200 znaków, empty = scheduler idle
```
+ czysta **`resolve_discovery_schedule(env)`** (wzorzec `resolve_publish_targets`):
enabled garbage→OFF; times parse+walidacja formatu, garbage pojedynczego okna → skip
(całość garbage → []); query strip; **malformed setting NIGDY nie zabija schedulera**.
Env-sync genericzny (jak SEARCH_LIMIT) — scheduler i tak czyta config bezpośrednio.

### 2d. `src/clippyme/api/app.py`
1. **Wspólny helper dispatchu** (refaktor out z search_endpoint :569-593):
   `async def dispatch_candidates(selected, api_key, registry) -> {jobs, skipped_processed}`
   — pętla 1:1 (uuid, OUTPUT_DIR, build_main_cmd, submit_job, QueueFullError→break)
   + **skip przetworzonych** + `register_dispatch` per wysłany job.
2. **`search_endpoint`**: response candidates+selected wzbogacone o `processed: bool`
   (+ `processed_job_id`); dispatch przez helper; `skipped_processed` w response;
   request bez nowych flag (v1: przetworzone ZAWSZE skipowane przy dispatchu —
   manualne „odcutkowanie" = forget endpoint).
3. **3 choke points** `/api/process` (:432) i `/api/batch` (:487): po submit_job →
   `register_dispatch(extract_video_id(url))` best-effort (niepowodzenie zapisu = log,
   dispatch NIGDY nie failuje przez rejestr).
4. **Lifespan**: `discovery_task = asyncio.create_task(discovery_scheduler_loop(...))`
   (obok :164-171) + cancel w shutdown; **backfill** raz przy starcie
   (`await asyncio.to_thread(backfill_from_output, OUTPUT_DIR, registry)`).
5. **NOWE endpointy** (za `require_trusted_config_request`):
   - `GET /api/discovery/schedule` → `{enabled, times, query, next_run, last_run}` 
     (last_run z in-memory state schedulera: `{at, dispatched, skipped_processed, error}`),
   - `POST /api/discovery/processed/forget` `{"video_id": "..."}` → usunięcie wpisu
     (manualny re-dispatch; GUI v2).

### 2e. `src/clippyme/api/schemas.py` — allow-list + walidatory (422):
`DISCOVERY_SCHEDULE_ENABLED in ("","0","1")`; `DISCOVERY_SCHEDULE_TIMES` regex
`^([01]\d|2[0-3]):[0-5]\d(,([01]\d|2[0-3]):[0-5]\d){0,11}$`; `DISCOVERY_SCHEDULE_QUERY`
≤200 znaków (strip).

### 2f. `src/clippyme/jobs/completion_webhook.py` (+~15 linii)
`build_discovery_payload(report)` — whitelist `{event, at, query, dispatched[{url, job_id}],
skipped_processed}`; reuse `post_webhook`; wywołane TYLKO z scheduled runów (manualne
GUI searchy nie spamują webhooka).

### 2g. Frontend — `dashboard/src/features/discovery/discovery.jsx` + `client.js` (+~150 linii)
1. **Panel „Auto-discovery"** (nad formularzem searcha — feature co-located, user:
   „starting in discovery page"): Switch ON/OFF (`saveKeys({DISCOVERY_SCHEDULE_ENABLED})`),
   input „Run at (HH:MM, HH:MM)" (`DISCOVERY_SCHEDULE_TIMES`), input „Query"
   (`DISCOVERY_SCHEDULE_QUERY`), hint „Server time (Warsaw). Fresh videos only —
   already-processed are skipped.", walidacja HH:MM client-side (toast).
2. **Status line** (poll `getDiscoverySchedule()` co 30 s gdy enabled): „Next run
   18:30 · Last: 12:00 → 2 dispatched, 1 skipped" (wzorzec pollingu z useActiveJobs:
   30 s enabled / brak polla disabled).
3. **Kandydaci**: badge **„already cut"** na wierszu z `processed: true` + checkbox
   disabled + toggle **„Hide processed"** (default OFF — widoczność first, user chce
   „tell me in some way"); licznik „N already cut" przy „Process selected".
4. `client.js`: `getDiscoverySchedule()` (null przy błędzie), `forgetProcessed(videoId)`
   (v1 bez UI — API-only).

### 2h. CSS — `.dvauto*` na KOŃCU `app.css` (wzorzec `.dvrow`), EOL LF.

## 3. KONFIG (config.json; GUI preferred — Discover → Auto-discovery)
```
DISCOVERY_SCHEDULE_ENABLED: "1"          # default "0" (OFF — zero zachowania po deploycie)
DISCOVERY_SCHEDULE_TIMES: "09:00,18:30"  # max 12 okien dziennie
DISCOVERY_SCHEDULE_QUERY: "italian comedy prank"   # single query v1; lista = v2
# reuse: SEARCH_LIMIT / SEARCH_ORDER jako defaults dla scheduled runów (bez nowych kluczy)
```
Po zmianie działa **BEZ restartu** (scheduler czyta config co tick) — pełna reguła GUI-first.

## 4. MACIERZ BŁĘDÓW

| Sytuacja | Reakcja |
|---|---|
| yt-dlp search fail w scheduled run | log ⚠️ + last_run{error} + raport skipped; następny tick normalny |
| QUERY pusty przy enabled | scheduler idle (log raz na start, nie spamować co tick); GUI warning przy zapisie |
| rejestr corrupt/nieczytelny | load → {} + log (fail-open; dedupe traci pamięć, nie blokuje dispatchy) |
| write rejestru fail (disk full/EACCES) | log; dispatch NIE failuje (rejestr best-effort) |
| kandydat bez video_id | niemożliwe z _to_candidate (None wcześniej odfiltrowany); defensywnie: skip dedupe, dispatch |
| backend restart mid-scheduled-run | joby w kolejce = journal requeue (istniejące); scheduled run się nie dubluje (last_fired in-memory per proces; po restarcie okno dziś-wystrzelane może odpalić ponownie → dedupe i tak pominie przetworzone — akceptowalne) |
| duplicate URL w kolejce (manual + scheduled) | poza zakresem v1 (MAX_CONCURRENT=1; drugi job zrobi drugi set klipów — user widzi w Active jobs); v2: soft-guard |
| Ollama/Gemini down przy dispatchu | joby wlecą i spadną jak dziś (TextTiling/fail) — poza zakresem schedulera |
| zegar przesunięty / DST | lokalny datetime serwera (CET/CEST automatycznie); tick 30 s toleruje ±30 s |

## 5. TESTY (kolejność)

1. **Offline unit (host python3, pure)**: `extract_video_id` (watch/short/youtu.be/
   embed/m./garbage → None); `resolve_discovery_schedule` garbage-matrix (jak
   `resolve_publish_targets` testy); registry: round-trip/prune-500/corrupt→{}/atomic
   (tmp dir); `due_times`: fake now, multi-okna, rollover północy, already-fired;
   dedupe-rank mixed fresh/processed (kolejność rankingu zachowana); backfill na
   tmp fixtures (source_info.json / brak / garbage JSON / istniejący wpis).
2. **API testy (pytest w kontenerze, `-e CLIPPYME_API_TOKEN=`)**: dry_run oznacza
   `processed` (mock registry); dispatch skipuje + `skipped_processed` (mock
   submit_job); forget endpoint round-trip; `GET /api/discovery/schedule` 403 bez
   trustu; schemas 422-matrix (times garbage, enabled garbage, query 201 znaków).
3. **Scheduler integration**: fake clock + fake dispatch w injectowalnym context —
   3 ticki: due→run, ten sam HH:MM drugi raz dziś→skip, północ→nowy dzień→run;
   never-raise (SearchError → tick przechodzi).
4. **E2E live (serwer)**:
   a. dry_run `{"query":"GTA VI"}` → kandydat `rz1B4B2yBZY` ma `processed: true`
      (backfill po starcie go widzi z source_info.json joba ee07f971) ✓,
   b. dispatch limit=3 mieszający processed+fresh → dispatch TYLKO fresh,
      `skipped_processed>=1`, job w Active jobs ✓,
   c. scheduled: `DISCOVERY_SCHEDULE_TIMES` = teraz+1 min (POST /api/config) → tick
      odpala → last_run w `GET /api/discovery/schedule` + joby + event webhooka
      (n8n exec albo receiver) ✓; drugi dzień-ten-sam-HH:MM → no-op ✓,
   d. restart backendu → scheduler re-armuje się, rejestr przetrwał, backfill idempotentny ✓,
   e. regresja: manualny GUI search na świeżym query = zachowanie nietknięte ✓,
   f. pełne suite backend (baseline 425) + frontend (baseline 395/8 fontowych) ✓.
5. **GUI live (przeglądarka)**: panel renderuje, switch/times/query zapisują (GET
   readback), badge „already cut" + disabled checkbox, „Hide processed" filtruje,
   status line next/last run ✓ (screenshots).

## 6. ROLLOUT / ROLLBACK
- Feature **default OFF** (`DISCOVERY_SCHEDULE_ENABLED` empty→0) — deploy = zero
  zmiany zachowania; user włącza w GUI.
- Rollback kodu: backup katalog `.backup-20261111-scheduled-discovery/` (przed
  edycjami; wzorzec poprzednich sesji) + `git checkout` plików + `docker restart
  clippyme-backend`. `data/discovery_processed.json` może zostać (nie szkodzi).
- Restart backendu JEDEN po deployu (python importy mrożą się na starcie — §6 handoffu).

## 7. PUŁAPKI (z sond + handoff)
- (a) **Scheduler czyta `load_persistent_config()`, NIE os.environ** — env procesu
  bywa dummy (landmine §3 pkt 16); `GEMINI_API_KEY` do dispatch env: config.json →
  env fallback → brak/dummy: dispatch MIMO TO działa przy `RANKING_PROVIDER=local`
  (proven), przy gemini z dummy → TextTiling — last_run raportuje warning w v2 (log v1).
- (b) `data/config.json` nieczytelny dla `ai` bezpośrednio (0600, uid kontenera) —
  weryfikacja przez `GET /api/config`, nie cat (§3 pkt 14).
- (c) Rejestr write = best-effort; NIGDY nie blokować dispatcha (choke points w try/except).
- (d) Backfill raz na proces w lifespan (to_thread); idempotentny (istniejące wpisy
  nie są nadpisywane — job_id z pierwszego dispatchu wygrywa).
- (e) Tick 30 s + `last_fired` per HH:MM keyed by date — bez tego multi-tick w oknie
  ±tick odpali run N razy; asyncio.Lock przeciw overlap (search trwa 5-15 s).
- (f) search yt-dlp = CPU 5-15 s → `asyncio.to_thread` (już jest w endpoint; helper
  musi zachować). Rate-bucket „search" NIE dotyczy schedulera (internal path) —
  nowy endpoint `/api/discovery/schedule` bez rate-limitu (poll 30 s, filozofia
  „status polling not limited" z §3 pkt 15).
- (g) Wyniki YT search są zmienne między wywołaniami (trap (c) §3 pkt 17) — nie
  porównywać candidates 1:1 między runami; dedupe po video_id jest stabilny.
- (h) pytest: `-e CLIPPYME_API_TOKEN=` (dotenv ładuje token → 401 w trusted routes);
  suite jest md5-stabilny dla config.json (§3 pkt 16) — zachować chdir-isolation w
  nowych testach rejestru (tmp_path, nie realny data/).
- (i) n8n event `discovery.scheduled_run` przepływa przez „Filter clips" jako 0
  items (body.clips brak → Code node zwróci pusto) — nie budować obsługi w n8n w v1;
  ew. V2: osobny n8n workflow na Discord-notify (user: „tell me" też tam).
- (j) GUI times input = czas SERWERA (Warsaw); hint w UI (user może być w innej TZ).

## 8. KOLEJNOŚĆ + NAKŁAD
1. Backup `.backup-20261111-scheduled-discovery/` → registry (2a) + unit testy (~1 h)
2. config_store + schemas + resolve (2c/2e) + testy (~45 min)
3. app.py: helper dispatchu + choke points + endpointy + lifespan + backfill (2d) + testy API (~1.5 h)
4. Scheduler loop + due logic + webhook event (2b/2f) + integration testy (~1.5 h)
5. GUI panel + badges + status (2g/2h) + frontend testy (~1.5 h)
6. E2E live §5.4 (a-f) + GUI live §5.5 (~1 h) + update handoffu §7 pkt 12 + ten plan (status → ZROBIONE)

**Razem: ~7-8 h** (jedna sesja nocna z zapasem). Backend ~380 linii + GUI ~150 linii.

## 9. REZYDUA V2 (nie blokuje, po decyzjach usera)
- Multi-query scheduled (lista query z rotacją per run / per dzień).
- „Mark as not processed" z GUI ( dziś API-only forget) + przycisk przy badge'u.
- n8n Discord notify na `discovery.scheduled_run` (embed: co dispatchnęło, co skipnęło).
- Soft-guard duplikatów URL w kolejce (manual + scheduled race).
- per-run spread czasowy dla batchy (Wait nodes) — przy >2-3 jobach/run (anty-spam,
  patrz pułapki ToS w PLAN-clippyme-multi-account-publishing.md §5).
