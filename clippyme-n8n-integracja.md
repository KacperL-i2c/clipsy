# ClippyMe ↔ n8n Integration — homelab (192.168.100.2)

## Stan obecny (2026-11-11 wieczór — workflow v3, PL-routing OFF, jedno konto Google)

- **2026-11-11 późny wieczór — dwie zmiany (patrz handoff §3 pkt 21):**
  1. **FIX wyrażeń (v3-regresja):** deploy v3 nadpisał fix tytułów z pkt „TODO" — live miał znowu
     single-brace title i BRAK description. Obecny stan (GET-zweryfikowany, mirror zsynchronizowany):
     title `={{ ($('Keep <t>').item.json.title || 'Short').slice(0, 100) }}`,
     description `=#shorts\n{{ ($('Keep <t>').item.json.description || $('Keep <t>').item.json.title || '' }}`
     — na OBU gałęziach. Po każdym PUT: GET + sprawdź parametry WSZYSTKICH nodów.
  2. **PL-routing OFF** (user: jedno konto Google „na razie"): Code „Route by targets" ma
     `const ENABLE_PL_ROUTE = false;` — bez explicit targets wszystko → `youtube-default`.
     Włączenie: flip stałej + PUT + activate (PO podłączeniu credentiala #2).
- **⚠️ YT upload quota:** 2026-11-11 ~19:16 UTC kanał #1 wpadł w `uploadLimitExceeded`
  (dzienny cap kanału; execs 31/32 przeszły o 19:06/19:10 ze zepsutymi tytułami —
  **user: usunąć je z kanału**). Reset ~24h rolling; walidacja fixa wyrażeń = pierwszy realny
  job score ≥85 po resecie.
- ClippyMe działa na `homelab`: dashboard `http://192.168.100.2:5175`, API `http://192.168.100.2:8000`
- API token: patrz `/mnt/AMPStorage/apps/clippyme/.env` → `CLIPPYME_API_TOKEN` (nagłówek `X-API-Token`)
- Ranking: przełącznik w GUI (config.json `RANKING_PROVIDER=local|gemini`; stan: gemini);
  n8n może przełączać per-run: `POST /api/config {"keys":{"RANKING_PROVIDER":"local"}}` z samym `X-API-Token`
- Transkrypcja: lokalny Whisper `medium` (GPU); klipy mają AUTO-NAPISY wypalone (SUBTITLES_AUTO=1)
- **n8n: kontener 2.46.6**, obraz `docker.n8n.io/n8nio/n8n`, `--restart unless-stopped`
  - porty: **`-p 192.168.100.2:5678:5678 -p 127.0.0.1:5678:5678`** (LAN + loopback — patrz „OAuth redirect" niżej)
  - volume: `/mnt/AMPStorage/apps/n8n:/home/node/.n8n` (SQLite config DB — recreate kontenera NIE gubi danych,
    workflow auto-reaktywuje się po restarcie)
  - env: `N8N_SECURE_COOKIE=false`, `GENERIC_TIMEZONE=Europe/Warsaw`
  - owner: `kacperlipiec123@gmail.com` (Kacper Lipiec; konto + API key utworzone przez `/rest/owner/setup` + `/rest/api-keys`)
  - **n8n API key** (Header `X-N8N-API-KEY`): patrz handoff §8 / wygeneruj nowy w UI: Settings → n8n API → Create key

## Workflow „ClippyMe → Multi-publish" (v3, ID `LpORWh7hK3bmiHI3`, AKTYWNY)

> **v3 (2026-11-11): ROUTING JĘZYKOWY EN/PL.** Gdy klip NIE ma targets (per-clip ani
> job-level w `PUBLISH_TARGETS`), „Route by targets" wykrywa język z title+description
> (polskie diakrytyki ąćęłńóśźż albo częste słowa: się/jest/nie/jak/dlaczego…):
> **polski → `yt-kanal-a` (kanał #2), inny → `youtube-default` (kanał #1, grejemclips1)**.
> Explicit targets NADPISUJĄ detekcję (testowane 3 sondami z fake-URL: exec 28/29/30 —
> error zawsze we WŁAŚCIWEJ gałęzi Download). DO czasu podłączenia credentiala #2 polskie
> klipy będą ERROR w nodzie YT (placeholder) — decyzja usera, świadome.

Lustrzana kopia JSON: `~/Dokumenty/Projekty/Serwer/clippyme-n8n-workflow-youtube.json` (import/update przez
`PUT /api/v1/workflows/LpORWh7hK3bmiHI3` z `X-N8N-API-KEY`; po PUT zawsze `POST .../activate`).

```
Webhook (POST /webhook/clippyme-job-completed, respond: Immediately)
  → Code „Filter clips" (JS): status completed + viral_score ≥ 85 + !published → 1 item/klip
  → Code „Route by targets" (NOWY v2): per klip × per target → item {…klip, clippy_target}
        routing: clip.targets (per-clip override) || payload.targets (job-level) || ["youtube-default"]
        walidacja slugu [a-z0-9_-]{1,40} po obu stronach (ClippyMe 422 / n8n filtr)
  → 2 gałęzie równoległe (per kanał jedna gałąź):
     [youtube-default] Code „Keep youtube-default" → HTTP „Download clip (default)"
                       → YouTube „Upload to YouTube (default)"  [credential „YouTube OAuth2 (ClippyMe)" idQbewUmSTe3fo9j]
     [yt-kanal-a]      Code „Keep yt-kanal-a"      → HTTP „Download clip (kanal-a)"
                       → YouTube „Upload to YouTube (kanal-a)"  [credential „YouTube OAuth2 (ClippyMe 2)" ss3URXj0WgSuoJO0 — PLACEHOLDER]
```

- **Kontrakt targets (ClippyMe → n8n)**: config.json **`PUBLISH_TARGETS`** (GUI: Settings → Automation →
  „Publish targets", tag-input; per-job przez `merge_persistent_config` — snapshot z chwili dispatchu) →
  completion webhook payload: `targets` na poziomie joba + `targets` per klip (fallback job-level).
  **Empty = payload bez `targets` = zachowanie legacy (kanał #1)** — zweryfikowane round-tripem.
- Walidacja E2E (2026-11-09, runData z execucji): explicit `youtube-default` → Download (default);
  legacy bez targets → Download (default); `yt-kanal-a` → Download (kanal-a); `no-such-branch` → drop
  (success, zero uploadów). Fake URL 404 = oczekiwany error w nodzie Download właściwej gałęzi.
- **Credential #2 = PLACEHOLDER** (`PENDING-USER-SETUP-2`) — istnieje tylko po to, by workflow dał się aktywować.
- **Jak dodać kanał C/D** (powtarzalny przepis):
  1. n8n (pulpit homelaba, `http://localhost:5678`): Credentials → nowy „YouTube OAuth2" → TEN SAM clientId/secret
     → Connect zalogowany na docelowe konto Google / wybierając kanał brand. Nazwa = nazwa targetu w ClippyMe.
  2. Workflow: zduplikuj 3 nody (Keep → Download → Upload) z gałęzi yt-kanal-a, zmień nazwy + target w Keep
     (`clippy_target === '<nowy-target>'`) + podmień credential w nodzie Upload.
  3. ClippyMe GUI: Settings → Automation → Publish targets → dodaj `<nowy-target>`.
  4. Test: ręczny webhook payload z `targets:["<nowy-target>"]` + realnym video_url → upload na właściwy kanał.

- **Webhook payload → n8n**: `CALLBACK_WEBHOOK_URL` w ClippyMe USTAWIONE na
  `http://192.168.100.2:5678/webhook/clippyme-job-completed` (config.json; test: „Send test event" w GUI
  albo `POST /api/config/webhook/test` — sample payload niesie też bieżące `PUBLISH_TARGETS`).
- **Credential #1**: `YouTube OAuth2 (ClippyMe)` (ID `idQbewUmSTe3fo9j`) — na razie PLACEHOLDER
  (`clientId/clientSecret = PENDING-USER-SETUP`) — patrz TODO niżej.

## TODO (user): Google OAuth dla YouTube upload (OBIE gałęzie = oba kanały)

> **UPDATE 2026-11-11: KROK 1 (credential #1) ZROBIONY.** Google Cloud projekt +
> OAuth client utworzone przez usera na konie **grejemclips1@gmail.com** (Client ID
> `196024646238-...apps.googleusercontent.com`). Credential #1 wypełniony przez API
> (PATCH /rest/credentials/{id}, publiczny PUT nie działa) + Connect zrobiony przez
> usera w UI przez **ssh tunnel** `ssh -N -L 5678:127.0.0.1:5678 ai@192.168.100.2`
> → `localhost:5678` na maszynie roboczej (nie trzeba być przy homelabie!).
> **FIX tytułów:** YouTube nodes miały expressions z SINGLE braces `{ }` — n8n
> ewaluuje TYLKO `{{ }}` (prefiks `=` wystarczy nie) → upload brał formułę jako
> literalny tytuł. Poprawione oba nody (title+description) przez PUT workflow +
> POST activate; mirror JSON zsynchronizowany. **Walidacja E2E: exec #25 success,
> uploadId MR84ygi5zhE, tytuł AI z payloadu ("Ne ha trovato...")** ✓.
> ZOSTAŁO: credential #2 (`yt-kanal-a`) — TE SAME clientId/secret, Connect na drugie
> konto/kanał; potem targets w GUI + walidacyjny realny job.

1. Google Cloud Console → projekt (może być nowy) → włącz **YouTube Data API v3**.
2. OAuth consent screen: External, wypełnij minimalnie, dodaj `kacperlipiec123@gmail.com` jako test user.
   **Publish app (Production)** po skonfiguracji — inaczej (status „Testing") refresh token wygasa co ~7 dni.
   Bez weryfikacji Google pokaże ekran „unverified app" — Advanced → proceed (jednorazowo).
3. Credentials → **OAuth client ID → Web application**:
   - Authorized redirect URI: **`http://localhost:5678/rest/oauth2-credential/callback`**
     (dokładny URL pokaże n8n w oknie edycji credentiala — skopiuj stamtąd 1:1).
   - Loopback jest akceptowany przez Google na plain HTTP (dlatego kontener ma binding `127.0.0.1:5678`!).
4. W n8n (na pulpicie homelaba, żeby URL był `localhost`): otwórz `http://localhost:5678`,
   Credentials → **„YouTube OAuth2 (ClippyMe)"** (#1, kanał domyślny = target `youtube-default`) →
   wklej Client ID + Secret → **Connect** → zaakceptuj (zalogowany na konto KANAŁU #1).
5. **Multi-account (v2)**: kolejne kanały = kolejne credentials na TYM SAMYM OAuth client:
   - „YouTube OAuth2 (ClippyMe 2)" (ID `ss3URXj0WgSuoJO0`, obecnie placeholder) → wklej TEN SAM
     Client ID + Secret → Connect zalogowany na konto / wybierając kanał brand #2 (target `yt-kanal-a`).
   - Nazwij credential wg kanału; weryfikacja per credential: testowy upload privacy=private na właściwy kanał.
6. W ClippyMe GUI: Settings → Automation → **Publish targets** → dodaj `yt-kanal-a` (i kolejne targety).
7. Walidacja końcowa: realny krótki job (score ≥ 85) → klip sam ląduje na YouTube właściwego kanału
   (targets z GUI decydują). Podgląd: n8n Executions.

Nowe kanały C/D: duplikuj gałąź (Keep → Download → Upload) w workflow, nowy credential, nowy target w GUI —
rezept w sekcji „Workflow v2" wyżej.

Uwaga na scope: `youtube.upload` = sensitive scope; consent screen musi go obejmować (n8n requestuje
`https://www.googleapis.com/auth/youtube` + userinfo).

## Gotchas tej sesji (noc #6)

- **Expressions w parametrach budowanych przez API = `={{ ... }}` (podwójne braces!)** (2026-11-11):
  single braces `{ ... }` z prefiksem `=` to literalny STRING — YouTube upload wziął formułę
  `({ $('Keep...').item.json.title || 'Short' }).slice(0, 100)` jako tytuł wideo. Cała logika musi być
  W ŚRODKU `{{ }}` (`.slice()` poza klamrami też staje się tekstem!). Download URL miał poprawnie `{{ }}`
  — dlatego plik się pobierał, a tytuł nie. Objaw: tytuł/OPIS wideo na YT = surowy kod JS.

- **Webhook node typeVersion 2 owija body**: output = `{headers, params, query, body}` — treść POST-a jest
  pod `$json.body`, nie `$json`! (v1 zwracał body bezpośrednio). Code node w workflow czyta `raw.body || raw`.
- **Filter/IF v2 conditions budowane ręcznie przez API nie ewaluują się poprawnie** w n8n 2.46 (format
  warunków zmienia się między wersjami) → filtr zrobiony jako **Code node** (plain JS, stabilne API).
- **`POST /rest/login`** oczekuje pola `emailOrLdapLoginId` (nie `email`) + header `browser-id`; cookies
  `n8n-auth` w curl `-c/-b`.
- **`POST /rest/api-keys`** (wewnętrzny) wymaga `{label, scopes: ["resource:scope", ...], expiresAt: <unix>}`;
  publiczny API key potem w headerze `X-N8N-API-KEY`. Uwaga: publiczny `GET /api/v1/executions` zwracał
  Forbidden mimo scope `execution:read` — do podglądu wykonań używać wewnętrznego
  `GET /rest/executions?limit=N` (cookies z loginu) — zwraca spłaszczony „string-table" JSON.
- Workflow update przez `PUT /api/v1/workflows/{id}` **dezaktywuje** workflow → po każdej aktualizacji
  `POST /api/v1/workflows/{id}/activate`.
- YouTube node blokuje **aktywację** workflow gdy brak credentiala → placeholder credential utworzony przez API.
- **Budowa connections przez API (PUT): klucz `from` może być tylko JEDEN** — `dict.update(chain(...))`
  nadpisuje poprzednią gałąź o tym samym nodzie-źródle (w noc #7 kosztowało debugging: Route miał tylko
  gałąź yt-kanal-a, youtube-default martwa; objaw: „success" z pustym runData downstream). Fan-out = JEDNA
  lista node'ów w `connections["Route by targets"]["main"][0]`. Inspekcja runData: `GET /rest/executions/{id}?unflattened=true`
  (cookies) zwraca spłaszczony string-table — refs to INDEKSY płaskiej tablicy (`flat[int(ref)]`, bez offsetu).
- **Keep-gates jako Code nodes** (nie Switch/IF v2 — te nie ewaluują się budowane ręcznie przez API): każdy
  target ma Code „Keep <target>" filtrujący `clippy_target === '<target>'`; pusty output = gałąź śpi.
- **OAuth redirect na LAN IP nie przejdzie** (Google pozwala plain HTTP tylko dla loopback) → stąd dual-bind
  `127.0.0.1` + `192.168.100.2`; łączenie credentiala robić z pulpitu homelaba przez `localhost`.
- `docker rm -f n8n` → log „Last session crashed" jest normalny; dane w volume, webhook wraca aktywny.

## Kluczowe endpointy ClippyMe (OpenAPI: `http://192.168.100.2:8000/openapi.json`)

| Endpoint | Metoda | Opis |
|---|---|---|
| `/api/search` | POST | **Video searcher**: `{"query", "limit" (1-10), "order": "popular"\|"newest", "min_duration", "max_duration", "dry_run" (default true)}`. dry_run=true → lista kandydatów. dry_run=false → dispatch top-N (wtedy WYMAGA też `X-Gemini-Key: local-no-key`). Zwrotka: `{candidates[], selected[], jobs[{url, job_id}]}` |
| `POST /api/config` | POST | `{"keys":{"RANKING_PROVIDER":"local"}}` — przełączenie rankingu per-run (200 z samym tokenem) |
| `POST /api/config/webhook/test` | POST | sample payload na zapisany webhook — health-check integracji |
| `/api/jobs/active` | GET | aktywne joby serwera |
| `/api/process` | POST | multipart: `url` (YouTube) lub `file` (upload) → `{"job_id": ...}`. **Wymaga 2 nagłówków: `X-API-Token` ORAZ `X-Gemini-Key` (dummy `local-no-key`)** |
| `/api/status/{job_id}` | GET | status + lista klipów |
| `/api/pause|resume|stop|cancel/{job_id}` | POST | kontrola joba |
| `/api/batch` | POST | wiele URL-i naraz |
| `/api/history` | GET | zakończone joby z dysku (UWAGA: video_url względne; webhook payload ma absolutne) |
| `/api/compose/{job_id}/{clip_index}` | POST | re-render klipa (napisy, grading, hook) |
| `/api/reframe/{job_id}/{clip_index}` | POST | zmiana trybu kadrowania |
| `/api/publish/{job_id}/{clip_index}` | POST | publikacja przez Zernio |
| `/videos/{job_id}/{plik}.mp4` | GET | gotowe klipy (statyczne, bez tokena; nazwy mają SPACJE — n8n HTTP Request sobie radzi) |

Nagłówek autoryzacji dla `/api/*`: `X-API-Token: <token>` (lub `Authorization: Bearer`).

## Proponowane przepływy n8n (rozbudowa)

### 1) Trigger z n8n (Schedule/Manual) → search → dispatch
```
Schedule Trigger → HTTP Request: POST /api/search {"query":..., "limit":3, "order":"popular", "dry_run":false}
  [2 nagłówki: X-API-Token ORAZ X-Gemini-Key: local-no-key]
  → ClippyMe sam queue'uje joby; NIE pollujemy statusu (webhook zrobi swoje)
```
### 2) Automatyczny upload na YouTube Shorts — **ZROBIONE** (workflow wyżej)
Filtr progu viral_score ≥ 85 siedzi w Code node „Filter clips" (zmień stałą w jsCode).
### 3) Monitor kanałów — wbudowany live-monitor ClippyMe; n8n zbędne do klipowania.

## Bezpieczeństwo

- n8n słucha na LAN (`192.168.100.2:5678`) bez auth dodatkowego poza kontem — nie wystawiać na świat bez
  Caddy + BasicAuth/SSO (istniejący Caddy może to później zrobić).
- ClippyMe API token trzymano w n8n jako credential typu Header Auth przy budowie triggera (do zrobienia).
- YouTube OAuth client secret zostaje w n8n (volume na AMPStorage).
- Nie logować tokena w workflow.
