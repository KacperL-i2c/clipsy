# PLAN — Multi-account publishing: różne shorts-y → różne konta (YouTube ×N, opc. TikTok / Instagram)

> Data: 2026-11-09 · Status: **FEASIBILITY ZWERYFIKOWANA (websearch na oficjalnych
> docs, stan VI-XI 2026)** — plan gotowy. Otwarte decyzje USERA: (a) lista kanałów YT,
> (b) path dla TikToka (draft vs Upload-Post vs własny audyt), (c) czy Instagram
> w ogóle (wymóg kont professional). Lustrzany wpis: `HANDOFF-clippyme-homelab.md`
> §7 pkt 11.
> Wymaganie usera: „google account manager — nie do zarządzania kontami, tylko żeby
> różne shorts-y szły na różne konta. Może też Instagram i TikTok. W apce albo w n8n
> — ale prosto."
>
> **UPDATE 2026-11-09 (noc #7): V1 (YouTube multi-account) ZAIMPLEMENTOWANY
> I PRZETESTOWANY — §3b backend (`PUBLISH_TARGETS` + `targets` w payloadzie),
> §3b GUI (Settings → Automation → „Publish targets", tag-input), §3c n8n workflow
> v2 „ClippyMe → Multi-publish" (Route by targets + 2 gałęzie; cred #2 placeholder
> `ss3URXj0WgSuoJO0`). Szczegóły, testy i pułapki: handoff §3 pkt 19. REZIDUALNE
> (USER): OAuth connect OBU credentiali (§3a — BEZ TEGO uploady nie ruszą) →
> targets w GUI → walidacyjny realny job. Kolejne kanały C/D = przepis w
> clippyme-n8n-integracja.md. V2 (§4) czeka na decyzje D1/D2.**

---

## 0. VERDICT (krótko)

**TAK, da się — i NAJPROŚCIEJ w n8n, nie w ClippyMe.**

| Platforma | Multi-konta? | Publiczne posty bez audytu? | Koszt wejścia | Rekomendacja |
|---|---|---|---|---|
| YouTube | ✅ osobne OAuth credential w n8n per kanał | ✅ **private-lock ZNIESIONY (2 XI 2026)** | zero | **v1 — robić** |
| TikTok | ✅ (osobny grant per konto) | ❌ bez audytu: tylko SELF_ONLY/private, ≤5 users/24h | audyt ryzykowny dla homelaba; draft-mode albo Upload-Post | v2 — decyzja D1 |
| Instagram | ✅ (tylko konta **professional**!) | ✅ dla własnych kont (Standard Access, bez App Review) | przerobienie kont IG na Business/Creator + Meta app | v2 — decyzja D2 |

**Anti-rekomendacja:** pełny „account manager" w ClippyMe (OAuth callback per platforma,
refresh tokeny, szyfrowany token-store, upload-clients ×3 różne API, GUI do tego) =
tygodnie pracy i duplikacja tego, co n8n już robi (credential store + upload nodes).
ClippyMe dostaje tylko **wybór targetów w GUI** (reguła GUI-first z nagłówka handoffu)
+ rozszerzenie payloadu completion webhooka. Credentials i upload = n8n.

---

## 1. FAKTY ZWERYFIKOWANE 2026-11-09 (oficjalne docs w wersji VI-XI 2026)

### 1a. YouTube Data API v3
- **Private-lock ZNIESIONY**: revision history (wpis 2 XI 2026) + reference
  `videos.insert`: „Videos uploaded from unverified API projects are **not** restricted
  to private viewing mode"; issuetracker (X 2026): compliance audit **nie jest już
  wymagany** do publicznych/scheduled uploadów. Sytuacja z 2020-04.2026 odwrócona —
  publiczne Shorts przez API działają od razu.
- **Granular quota (od VI 2026)**: `videos.insert` ma WŁASNY bucket — default
  **100 uploads/day per project** (1 unit/call) + 10 000 units/day na pozostałe
  metody. Extension form dopiero przy >100/day (wymaga audytu). Dawniej było ~6/day
  (1600 units/upload) — problem zniknął.
- **Multi-konto = multi-credential w n8n**: JEDEN Google Cloud OAuth client (ten sam
  clientId/secret + redirect `http://localhost:5678/rest/oauth2-credential/callback`)
  może zasilać WIELE n8n-credentiali „YouTube OAuth2" — każdy Connect wykonany
  zalogowany na inne konto Google = osobny grant.
- **Brand channels**: konto Google z wieloma kanałami (brand accounts) — przy consent
  OAuth wybiera się tożsamość KANAŁU; każdy kanał = osobny grant = osobny credential
  w n8n. Bezpieczniej i czyściej: osobne konta Google per kanał.
- Limity wideo: ≤256 GB; klipy ClippyMe (10-75 s, 9:16) = OK dla Shorts.

### 1b. TikTok Content Posting API (stan VIII-X 2026)
- **Unaudited client**: posty TYLKO `SELF_ONLY` (private), max **5 users / 24 h**,
  konta muszą być private; 403 `unaudited_client_can_only_post_to_private_accounts`.
- **Direct Post audit** (publiczne posty): wymaga app „intended for wide audience" —
  prywatny homelab automation typowo ODRZUCONY (Mixpost dokumentuje, że review
  przechodzą realnie dopiero produkty publiczne). Czas: dni–2 tyg.
- **Path BEZ audytu — Upload API (draft/inbox)**: scope `video.upload`,
  `POST /v2/post/publish/inbox/video/init/` + chunked FILE_UPLOAD (lub
  PULL_FROM_URL z **zweryfikowaną domeną** — LAN odpada): wideo ląduje w inboxie
  TikToka jako DRAFT, user kończy publikację w apce (push notification). Działa dla
  unaudited clients — legal-clean, ale nie-fully-auto.
- Limity twarde: 6 req/min per user token; `spam_risk_too_many_posts` ~15 postów/day/
  creator (dzielone między wszystkie API clients); wytyczne ToS zabraniają apps
  „copying arbitrary content from other platforms" (klipy ClippyMe pochodzą z YT —
  świadoma decyzja usera, zaznaczone, nie blockuje draft/upload path).
- **n8n: BRAK oficjalnego (core) TikTok node** → HTTP Request nodes (chunk flow
  niewygodny w n8n) albo community node (patrz 1d).

### 1c. Instagram Content Publishing API (stan VI-IX 2026)
- **TYLKO konta professional** (Business albo Creator) podpięte do FB Page — konta
  osobiste API pominie. Decyzja usera: które konta przekształcić.
- **Bez App Review dla własnych kont**: Standard Access („app serves only accounts
  you own or manage") — review niepotrzebne. App Review + Business Verification
  dopiero gdy app obsługuje obce konta.
- Flow: `POST /{ig-user-id}/media` (container: `media_type=REELS`, `video_url` —
  **MUSI być publicznie osiągalny dla serwerów Meta**; LAN 192.168.x = NIE działa;
  alternatywa bez publicznego URL: resumable `rupload.facebook.com/ig-api-upload/`,
  tylko Facebook Login) → poll `status_code=FINISHED` (klip <1 min: ~1-2 min wait)
  → `POST /{ig-user-id}/media_publish`.
- Limit: **~50 publikacji / 24 h rolling per konto** (docs podają 50 albo 100 —
  prawdę pokazuje `GET /{ig-id}/content_publishing_limit`; limit NIE resetuje się
  o północy); błąd limitu = code 9, subcode 2207042. Wymogi: PPA na Page, 2FA
  na Page u usera tokenu.

### 1d. n8n (2.46.6 na homelabie)
- YouTube node: core, proven (workflow `LpORWh7hK3bmiHI3`), multi-credential działa.
- TikTok: brak core node. Community: **Upload-Post** (`n8n-nodes-upload-post`,
  verified, instalacja z Community Nodes) — TikTok + Instagram + YouTube + LinkedIn +
  X + ... w jednym API, **multi-user per platform** (ich dashboard zarządza kontami)
  = gotowy mini „account manager"; ich app ma zrobiony audyt → **publiczne posty od
  1. dnia**; free tier + płatne plany. Wada: binary/klipy przechodzą przez serwery
  3rd party.
- Instagram: brak dedykowanego „publish reel" core node → 3× HTTP Request na Graph
  API (proste) albo Upload-Post.
- Gotchas istniejące (patrz clippyme-n8n-integracja.md / §8 handoffu): PUT workflow
  → dezaktywacja (po update ZAWSZE POST activate); webhook typeVersion 2 owija body
  (`$json.body`); filtr jako Code node (nie Filter v2).

---

## 2. ARCHITEKTURA (rekomendowana)

```
ClippyMe (GUI: wybór targetów per job; Settings → „Publishing")
  └─ completion webhook (payload + clips[].targets)            [mała zmiana backendu]
       └─ n8n workflow v2 „ClippyMe → Multi-publish"
            Code „Filter clips" (score threshold, !published)          [istnieje]
            → Code „Route by targets" (NOWY): per klip × per target
                 ├─ "yt-kanal-a"  → YouTube node, credential A         [istnieje node]
                 ├─ "yt-kanal-b"  → YouTube node, credential B         [nowy credential]
                 ├─ "tiktok-u1"   → TikTok path (draft DIY lub Upload-Post)
                 └─ "ig-konto"    → Graph API 3-step albo Upload-Post
```

Zasada spójna z resztą systemu: **ClippyMe = orkiestracja + GUI; n8n = publisher +
credential store.** Jedyny kontrakt między nimi = payload webhooka (`targets`).

---

## 3. V1 — YouTube multi-account (najmniejszy krok, ~2-3 h)

### 3a. USER (Google side) — BLOKADA CAŁOŚCI
1. Najpierw dokończyć istniejące TODO OAuth (clippyme-n8n-integracja.md → „TODO":
   Google Cloud → YouTube Data API v3 → consent → OAuth client z redirectem
   `http://localhost:5678/...` → wkleić do „YouTube OAuth2 (ClippyMe)" → Connect).
2. Kolejne kanały: dla każdego — w n8n na pulpicie homelaba (`http://localhost:5678`,
   loopback!): Credentials → nowy „YouTube OAuth2" credential → **ten SAM clientId/
   secret** → Connect, zalogowany na docelowe konto Google / wybierając docelowy
   kanał brand. Nazwać credentiali wg kanału (`yt-kanal-a`, `yt-kanal-b`, ...).
3. Weryfikacja per credential: testowy upload privacy=private na właściwy kanał.

### 3b. ClippyMe backend (~60-80 linii + testy; wzorzec: config keys + webhook whitelist)
- `storage/config_store.py`: NOWY klucz **`PUBLISH_TARGETS`** — JSON array nazw
  targetów (np. `["yt-kanal-a","yt-kanal-b"]`); empty = backward-compat (payload
  bez targets → n8n robi to co dziś). Walidacja: JSON array stringów
  `[a-z0-9_-]{1,40}` → 422 inaczej. Per-job przez `merge_persistent_config`
  (proven pattern, bez restartu).
- `jobs/completion_webhook.py`: `build_completion_payload` — dodać `targets` do
  per-clip whitelist (fallback na targets poziomu joba). Test no-leaks rozszerzyć
  (targets OK, reszta whitelisty bez zmian).
- GUI (Settings → Automation / nowy panel „Publishing"): edycja listy targetów
  (tag-input: enter dodaje, × usuwa) + hint „nazwy muszą zgadzać się z nazwami
  credentiali/targetów w n8n". GUI first (reguła z nagłówka handoffu).
- (v1.5 opcjonalnie) per-klip wybór targetów w Results view — v1 wystarczy per-JOB.

### 3c. n8n workflow v2 (update istniejącego: `PUT` + ZAWSZE `POST .../activate`)
- Istniejący Code „Filter clips" (score ≥85, !published) zostaje.
- NOWY Code „Route by targets": per klip czyta `clip.targets || jobTargets ||
  ["youtube-default"]`; emituje `{clip, target}` items.
- **Osobny YouTube node per kanał** (n8n nie ma dynamic pick credentiala w jednym
  node) + Switch/IF po `target`. Przy 2-4 kanałach OK; >4-5 → rozważyć Upload-Post
  albo HTTP resumable upload (jeden node, tokeny z credentiali generic).
- Description/tytuł per target: opcjonalna mutacja w Code (spready anty-duplikatowe).

### 3d. Testy V1
1. Manual webhook (wzorzec komendy z §8 handoffu): payload z `targets:["yt-kanal-a"]`
   → upload na kanał A; `targets:["yt-kanal-b"]` → kanał B; bez targets → zachowanie
   compat jak dziś (kanał #1).
2. Realny job score ≥85 → auto-upload na wybrane kanały; podgląd w n8n Executions.
3. Quota sanity: 3 uploady pod rząd → brak błędów quota (bucket 100/day, koszt 1/call).

---

## 4. V2 — TikTok + Instagram (DECYZJE USERA ZANIM SIĘ KODZI)

**Decyzja D1 (TikTok):**
- (A) **Draft-mode DIY** (0 zł, bez audytu): n8n HTTP nodes — init FILE_UPLOAD →
  PUT chunk(s) na `upload_url` → poll status (6 req/min limit; szczegóły chunków:
  TikTok Media Transfer Guide podczas implementacji). Klip = DRAFT w inboxie,
  user publikuje w apce TikToka. Zaleta: clean, zero zależności. Wada: dotyk telefonu
  per post.
- (B) **Upload-Post community node**: full-auto PUBLICZNE posty (ich audyt),
  multi-user = ich dashboard robi „account manager" za nas; koszt subskrypcji
  (free tier ograniczony); klipy przechodzą przez ich serwery (LAN i tak nieosiągalny
  dla TikToka — przeszkoda ta sama).
- (C) **Własny audyt Direct Post**: tylko przy skali; ryzyko odrzucenia homelaba.
- **Rekomendacja: (A) na start**; (B) gdy user chce full-auto public.

**Decyzja D2 (Instagram):**
- Warunek konieczny: konta IG przerobione na professional (Business/Creator) +
  FB Page + Meta app (dev mode wystarcza na własne konta — bez App Review).
  Konta mają zostać osobiste → IG odpada.
- Path DIY: 3 requesty Graph API z HTTP nodes + Wait na FINISHED. Problem:
  `video_url` musi być PUBLICZNY — ClippyMe serwuje `/videos/` na LAN. Opcje:
  publiczny URL przez Caddy + DNS (long-random path pragmatycznie; Meta fetchuje
  URL raz) albo resumable `rupload` (Facebook Login, brak public URL).
- Path Upload-Post: multipart z n8n (binary), brak problemu public URL, multi-user.
- **Rekomendacja: po D1; IG przez to samo co TikTok (spójny multi-user), DIY tylko
  przy „0 zł" i gotowości do wystawienia publicznego URL.**

---

## 5. PUŁAPKI (do implementacji)
- **LAN-IP nieosiągalny z chmury** (powtórka z pułapki webhook 127.0.0.1, §6 handoffu):
  serwery Meta/TikTok nie widzą `192.168.100.2:8000/videos/...` — TT PULL_FROM_URL
  i IG video_url odpadają bez publicznego URL; FILE_UPLOAD/multipart omija problem.
- YT: jeden Google project = WSPÓLNY bucket 100 uploads/day na wszystkie kanały
  (limit per-project, nie per-channel). Więcej = extension form (+audyt).
- YT brand account: consent wybiera kanał — łatwo podpiąć niewłaściwy; nazwy
  credentiali wg kanału + testowy private-upload na weryfikację.
- n8n: osobny YouTube node per credential (brak dynamic pick) — graf rośnie
  liniowo z liczbą kanałów.
- TT: 6 req/min/user; ~15 postów/day/creator (`spam_risk_too_many_posts`); unaudited
  wymaga kont private i SELF_ONLY; draft-mode omija UI-consent constraints.
- IG: PPA + 2FA na Page; 50/day rolling (bez resetu o północy); poll FINISHED
  przed publish (publish za wcześnie = błąd); limit error code 9 / subcode 2207042.
- Payload whitelist: `targets` musi przejść `build_completion_payload` (test
  no-leaks); walidować format w config_store — nie przepuszczać dowolnych stringów
  do switcha w n8n.
- n8n update: `PUT /api/v1/workflows/{id}` dezaktywuje → ZAWSZE `POST .../activate`.
- ToS/anty-spam (świadome, po stronie usera): ten sam klip na wiele kont naraz =
  ryzyko strike/spam-detekcji na każdej platformie; mitigacja: spready czasowe
  (Wait nodes) + per-target warianty tytułu/description w Code node (ClippyMe
  generuje copy per klip — łatwo mutować).

---

## 6. KOLEJNOŚĆ + NAKŁAD
1. **USER**: dokończyć TODO OAuth (credential YT #1) — BEZ TEGO NIC (pkt 4 handoffu).
2. V1 backend+GUI (`PUBLISH_TARGETS` + payload + panel): ~60-80 linii backend +
   ~60 linii GUI + testy — ~2 h.
3. V1 n8n (credential #2 + Code route + osobne YT nodes): ~1-2 h + testy manual.
4. (decyzje D1/D2) → V2: TikTok draft-DIY ~3-4 h; Upload-Post ~1-2 h (install node
   z Community Nodes + konfiguracja users w ich dashboard); IG-DIY ~4-6 h
   (+ publiczny URL).
