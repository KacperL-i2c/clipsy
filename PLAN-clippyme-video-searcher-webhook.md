# PLAN — ClippyMe: Video Searcher + Completion Webhook (przed n8n)

> **STATUS 2026-11-08 (noc #5): ZIMPLEMENTOWANY — sekcje 1-3 zrobione i przetestowane
> (detale + testy + E2E: HANDOFF §3 pkt 17, §10). Pozostał tylko pkt 4 KOLEJNOŚĆ
> (n8n install + workflow = user: LAST).**

> Powstał 2026-11-08 (nowa sesja, po HANDOFF-clippyme-homelab.md §7 pkt 4).
> Wymagania usera (verbatim-ish):
> 1. „video searcher" triggerowany przez API — n8n wywołuje event, ClippyMe szuka
>    najnowszych i najpopularniejszych filmów YT po tagach/query, a na podstawie
>    listy (liczba KONFIGUROWALNA) startuje ich processing.
> 2. Sposób na przekazanie gotowych shortsów do n8n (nie musi być Google Drive) —
>    n8n pobiera klipy i uploaduje na YT.
> 3. Ranking engine (local/gemini) zmienialny z aplikacji LUB z n8n.
> 4. **Konfiguracja n8n = OSTATNI KROK** (najpierw funkcje po stronie ClippyMe).

## 0. STAN WERYFIKOWANY (sondy 2026-11-08, ta sesja)

| # | Sonda | Wynik |
|---|---|---|
| 1 | Kontenery healthy (backend up, frontend, NC AIO, HA...) | ✅ 14/14 healthy |
| 2 | Ollama / GPU | 3 modele (qwen3:4b-instruct, qwen2.5:3b, gemma3:1b); GPU 105/6144 MiB idle |
| 3 | config.json | `RANKING_PROVIDER=gemini`, prawdziwy klucz Gemini obecny (maskowany `AQ.A...9...`), `SUBTITLES_AUTO=1`, `classic_white` |
| 4 | **`POST /api/config` token-only (bez Origin)** | **200 OK** → n8n może zmieniać `RANKING_PROVIDER` (i wszystko inne) samym `X-API-Token` ✅ |
| 5 | **yt-dlp search POPULAR: `ytsearch3:query` flat-playlist** | ✅ działa: `title \| views=7398249 \| dur=255` — view_count i duration JUŻ w flat mode |
| 6 | **yt-dlp search NEWEST: `.../results?search_query=...&sp=CAI%3D`** | ✅ działa (sort po dacie uploadu, malejąco) |
| 7 | OpenAPI | `/api/batch` istnieje (multi-URL dispatch — reuse dla searchera); `/api/config/cookies` POST (cookies można wgrać przez API — plan B przy 403) |

Wniosek: **searcher da się zrobić bez YouTube Data API key** (yt-dlp flat extract).
Bot-detection 403 dotyczył pełnych downloadów; metadata/search działa (sondy 5-6).
Plan B przy degradacji: cookies.txt przez `POST /api/config/cookies` (endpoint JEST).

## 1. FEATURE A — Video Searcher (`POST /api/search`)

### 1.1 API (backend)
```
POST /api/search            [X-API-Token; za require_trusted_config_request jak config]
{
  "query": "powerlifting motivation",   // wymagane
  "limit": 3,                            // ile filmów FINALNIE (default z configu SEARCH_LIMIT)
  "order": "newest" | "popular",         // default popular
  "min_duration": 60,                    // sekundy, opcjonalne (flat duration filter)
  "max_duration": 3600,                  // opcjonalne
  "dry_run": true|false                  // default true (GUI preview); false → od razu dispatch
}
→ 200 { "query", "order", "candidates": [ {url, video_id, title, channel,
         view_count, duration, age_days, upload_date} ... ] (do limit*oversample przed filtrami),
         "selected": [ ...limit sztuk... ],
         "job_ids": [...] }              // job_ids tylko przy dry_run=false
```
- Dispatch przy `dry_run=false`: reuse wewnętrznej mechaniki `/api/batch` (job per URL,
  kolejka, MAX_CONCURRENT_JOBS=1 respektowane). NIE dublować logiki job_runnera.
- **Oversample:** fetch `min(limit*4, 30)` kandydatów, potem filtry duration → sort
  (popular: view_count desc; newest: już posortowane z sp=CAI=) → weź `limit`.
- Wywołanie yt-dlp (WERYFIKOWANE sondami — kopiuj 1:1):
  - popular: `yt-dlp --flat-playlist --print "%(url)s\t%(title)s\t%(view_count)s\t%(duration)s\t%(channel)s" "ytsearch{M}:{query}"`
  - newest: `yt-dlp ... "https://www.youtube.com/results?search_query={urllib.parse.quote(query)}&sp=CAI%3D"`
  - flat entries mają view_count/duration; czasem NA (sonda 6) → traktować jako 0/None i odfiltrowywać dopiero przy sortowaniu popular.
- Timeout subprocessu ~60s; błąd yt-dlp → 502 z treścią stderr (log + czytelny błąd).
- Auth: header `X-API-Token`; też `X-Gemini-Key` NIE jest tu wymagane (to wymóg
  `/api/process` — searcher dispatch idzie przez wewnętrzny batch, nie HTTP self-call).

### 1.2 Persisted settings (GUI-first — reguła z nagłówka handoffu)
- `SEARCH_LIMIT` (default 3) + `SEARCH_ORDER` (default `popular`) w
  `VALID_CONFIG_KEYS` (config_store) + schemas allow-list/walidacja — wzorzec 1:1
  z `SUBTITLES_AUTO`/`RANKING_PROVIDER` (merge_persistent_config per-job nie dotyczy
  endpointu search, ale defaults muszą być czytelne z config.json).
- Per-request parametry nadpisują defaults.

### 1.3 GUI (wymóg reguły: konfigurowalne/triggeralne = widoczne w dashboardzie)
- Nowy widok/panel **„Discovery"** (tab między Create a History albo panel w Create):
  - input query + select order (Popular/Newest) + number „How many" (default z configu)
  - przycisk **Search** → lista kandydatów (tytuł, kanał, views, duration, age) z checkboxami
  - przycisk **Process selected (N)** → POST /api/process per zaznaczony (reuse
    istniejącego client.js `processVideo`/batch) → normalny flow Active jobs
  - przycisk **Process top N** (auto, = dry_run:false na /api/search)
  - pusty stan + error state (403/bot-detection → hint o cookies w Settings)
- Frontend testy: render wyników, Process selected woła właściwe endpointy, defaults z configu.

### 1.4 Testy Feature A
1. Unit backend (mock subprocess yt-dlp): parsing flat output, filtry duration,
   sortowanie popular/newest, oversample→limit, NA view_count przy sortcie, 502 path.
2. API test: 401 bez tokena, dry_run=true nie tworzy jobów, dry_run=false tworzy
   (mock batch dispatch), walidacja 422 (pusty query, limit 1-10).
3. Live E2E na serwerze: `POST /api/search {"query":"...", "dry_run":true}` → realni
   kandydaci; potem process 1 wybranego krótkiego (27s cache pattern jak w handoffie).
4. GUI w przeglądarce: search → lista → Process selected → job w panelu Active jobs.

## 2. FEATURE B — Completion webhook (n8n pobiera gotowe klipy)

### 2.1 Mechanizm (backend)
- Persisted key **`CALLBACK_WEBHOOK_URL`** (empty = disabled) w VALID_CONFIG_KEYS +
  schemas (URL format walidacja, http/https) — Settings row „Completion webhook".
- Hook point: przejście joba w stan terminalny (completed/stopped) w job_runner —
  JEDNO miejsce (zweryfikować, że dotyczy też jobów z GUI i z /api/batch; spike:
  gdzie dziś jest journal write terminalny — tam podpiąć, najlepiej po zapisie
  metadanych klipów).
- Payload POST JSON (fire-and-forget, timeout 10s, 3 retry: 5s/30s/60s, failure = log only):
```json
{
  "event": "job.completed",
  "job_id": "...",
  "status": "completed",
  "source": {"label": "...", "url": "..."},
  "finished_at": "2026-11-08T21:00:00Z",
  "clips": [
    {"index": 0, "filename": "...clip_1.mp4",
     "video_url": "http://192.168.100.2:8000/videos/{job}/...",
     "thumbnail_url": ".../thumbnails/...",
     "title": "...", "description": "...", "viral_score": 92, "duration_s": 34.2}
  ]
}
```
  - URL-e ABSOLUTNE (base z env CLIPPYME_BIND/host — zweryfikować jaki base ma dziś
    video_url w /api/history i użyć tego samego źródła prawdy).
- NIE blokować finalizacji joba webhookiem (asyncio.to_thread / task; wyjątek = log).

### 2.2 GUI (Settings)
- Nowy wiersz **„Completion webhook"**: URL input + Switch enable + **Test** button
  (nowy endpoint `POST /api/config/webhook/test` → wysyła sample payload na zapisany
  URL i zwraca status/odpowiedź — user widzi OK/błąd w UI, GUI-first ✅).
- Hint: „n8n → Workflow → Webhook node; wklej production URL tutaj".

### 2.3 Testy Feature B
1. Unit: payload shape (whitelist pól, absolutne URL-e), retry przy 500, brak calla
   gdy URL pusty, brak calla dla failed? (DECYZJA: wysyłaj też failed z
   status=failed — n8n może chcieć logować; flaga v2 jeśli user nie chce).
2. API: zapis/odczyt klucza, 422 na garbage URL, test-endpoint mockuje webhook.
3. Live E2E: webhook.receiver (python http.server) na serwerze → job 27s → payload
   dotrał, video_url downloadowalny (curl 200).
4. GUI: zapis URL, Test → toast OK, wylogowanie pola przy clear.

## 3. Ranking provider z n8n — JUŻ DZIAŁA (sonda 4)
- `POST /api/config {"keys":{"RANKING_PROVIDER":"local"|"gemini"}}` z samym
  `X-API-Token` = 200 (bez Origin). Workflow n8n: Set node (provider) → HTTP Request
  → dopiero potem dispatch. GUI switch zostaje (obojętnie kto ostatni ustawił —
  config.json jest source of truth; panel Settings zawsze pokazuje stan).
- NIC nie budujemy; tylko udokumentować w cheat-sheet n8n.

## 4. KOLEJNOŚĆ (n8n = ostatni krok, decyzja usera)

| # | Krok | Nakład |
|---|---|---|
| 1 | Feature A backend: /api/search + config keys + unit/API testy | ~2h |
| 2 | Feature A GUI: Discovery panel + frontend testy | ~1.5-2h |
| 3 | Feature B backend: webhook + test endpoint + testy | ~1.5h |
| 4 | Feature B GUI: Settings row + Test + testy | ~1h |
| 5 | **n8n install** (LAN!): `docker run -d --name n8n --restart unless-stopped -p 192.168.100.2:5678:5678 -e N8N_SECURE_COOKIE=false -e GENERIC_TIMEZONE=Europe/Warsaw -v /mnt/AMPStorage/apps/n8n:/home/node/.n8n docker.n8n.io/n8nio/n8n`; user zakłada konto admina przy 1. wejściu; credential Header Auth (X-API-Token) | ~30 min |
| 6 | n8n workflow „work": trigger (schedule/manual) → (opcjonalnie Set RANKING_PROVIDER → POST /api/config) → POST /api/search (dry_run=false, limit z configu) → jobs lecą sami → **Webhook node łapie completion** → Discord (embed: tytuł, score, linki /videos/...) → [v2 po koncie Google: YouTube upload node] | ~1-2h |
| 7 | E2E całości + aktualizacja clippyme-n8n-integracja.md (jest STARE: mówi qwen2.5:7b, nie zna /api/search ani webhooka) + HANDOFF | ~30 min |

## 5. Pułapki / otwarte decyzje

- (a) **403 bot-detection** może trafić też w search przy skalowaniu — plan B:
  cookies przez istniejący `POST /api/config/cookies` (GUI Settings już ma pole?).
- (b) view_count=NA w flat mode (sonda 6) — nie crashować, traktować jako unknown.
- (c) search wywołanie yt-dlp = CPU ~5-15s; uruchamiać w to_thread, nie w event loopie.
- (d) webhook payload przy batch (wiele jobów) — per-job (każdy job osobny POST).
- (e) base URL dla absolutnych linków: użyć tego samego źródła co /api/history video_url.
- (f) od usera PO instalacji n8n: **Discord webhook URL** (Server → Channel →
  Integrations → Webhooks → New Webhook → Copy URL); ew. konto Google do uploadu (pkt 5 handoffu).

## 6. Side questy (bez zmian, z handoffu §7 pkt 6)
- pin/upgrade yt-dlp w requirements.lock (przetrwa recreate),
- `passwd ai` (user),
- rezyduum: pełny long-form E2E z renderem+napisami przy najbliższym long-form uploadzie.
