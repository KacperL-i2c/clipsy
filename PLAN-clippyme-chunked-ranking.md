# PLAN — Chunked (map-reduce) ranking lokalnego LLM dla długich wideo

> **STATUS 2026-11-08 (wieczór): ZIMPLEMENTOWANY I PRZETESTOWANY — lustrzany opis
> w `HANDOFF-clippyme-homelab.md` §3 pkt 12 (tam też odchylenia od tego planu:
> komponentowy estymator tok, THRESHOLD 8000, drop hallucynacji poza oknem).
> Testy §5 niżej: wszystkie zielone.**

> Data: 2026-11-08 · Status: ZWERYFIKOWANY sondami na żywym Ollama (6 probe'ów, 11 wywołań)
> **Lustrzana kopia: `HANDOFF-clippyme-homelab.md` §9** — tam też szukać nowej sesji.
> Problem: transkrypt 55-min wideo = **167 292 tokeny** → `HTTP 400: request exceeds
> context size (8192)` → cichy fallback TextTiling (score 0, tytuły "part 1..N").
> Dotyczy: każdy film >~12 min. Fix w 100% lokalny, bez zmian sprzętowych.
> Plan wykonywalny przez nową sesję bez dodatkowego kontekstu.

---

## 0. WERYFIKACJA WSTĘPNIA (sondy 2026-11-08 — wszystko zmierzone, nie teoria)

| # | Sonda | Wynik |
|---|---|---|
| 1 | VRAM baseline | 337/6144 MiB użyte (gnome-remote-desktop 86 MiB) — ogromny zapas |
| 2 | `num_ctx=16384` realnie | **VRAM peak 4171 MiB** ✅ (~2 GB headroom), działa na żywym Ollama |
| 3 | Tokeny: kalibracja 1-decimal TOON | **~17,7 tok/wiersz** + template ~4,4k; 570 wierszy = 13,5k tok |
| 4 | Precyzja znaczników czasu | 1-decimal = **−18% tok** vs 3-dec; integer = −36%, ALE ±0,5s zjada 0,6s tolerancji snap (`DEFAULT_MAX_SNAP=0.6`, `cut_ops.py:26`) → **wybrano 1-decimal** |
| 5 | Latencja / window (450-570 wierszy) | 13–23s (load 3-4s, prefill 5-8s, decode 9-11s) → **55 min wideo ≈ 6 min rankingu** (17-18 okien) |
| 6 | **minItems:1 w schema (Ollama grammar)** | **DZIAŁA** — wymusza ≥1 klip/okno; bez tego 4B zwraca `{"shorts":[]}` (sonda 2/3: 0 klipów wszędzie) |
| 7 | Template skrócony (bez włoskich przykładów) | język OK, ALE **klipy degeneracyjne 0,6-3,1s** ❌ → 4B POTRZEBUJE pełnego template (pełny = klipy 79-97s ✅) |
| 8 | `done_reason:"length"` przy num_predict=1024 | content EMPTY → **retry ratuje** (attempt 2: OK, 293 tok) → retry obowiązkowy |
| 9 | Język tytułów na polskim transkrypcie | pełny template = mieszanka PL/włoski; wzmianka w headerze pomaga częściowo → **znane ograniczenie** (patrz §7) |

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

---

## 1. ARCHITEKTURA (co gdzie leci)

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

## 2. ZMIANY PER PLIK

### 2a. `src/clippyme/pipeline/analysis/gemini_request.py` (+~90 linii, pure/host-testable)
```python
WINDOW_HEADER = """..."""   # jak w sondzie 5: window i/N, 1-3 clips FROM WINDOW,
    # absolute standards, >=15s anti-bug, LANGUAGE HARD reinforcement (bez nazwania
    # języka na sztywno! patrz 2d), minItems hint niepotrzebny (schema załatwia)

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

### 2b. `src/clippyme/pipeline/analysis/local_llm.py` (+~110 linii)
```python
WINDOW_SCHEMA = deepcopy(CLIP_JSON_SCHEMA); WINDOW_SCHEMA[...]["shorts"]["minItems"]=1

def generate_chunked(client, words, video_duration, instructions, creator) -> _Response:
    """Orkiestracja:
    1. windows = plan_windows(words)
    2. per okno (progress log: '🦙 window i/N t0-t1s → k clips (wall Xs)'):
       - prompt = build_viral_prompt_window(...)
       - response = client.models.generate_content(model=..., contents=prompt,
             config z num_ctx=16384, num_predict=1536)
       - UWAGA: generate_content używa schema wg numeru okna? → rozszerzyć
         _generate(...) o param schema=... (default CLIP_JSON_SCHEMA; okna dają WINDOW_SCHEMA)
       - po Ollama response: done_reason=="length" lub content pusty/invalid
         → sleep(3) + 1 retry; dalej raise → okno skipped (logged)
       - _salvage_clip na każdym klipie (duration clamp, score int, teksty)
       - NOWE w salvage: hook==title → hook = first 6 words of viral_reason
    3. merge: dedupe overlap (IoU>0.35 keep wyższy score), sort score desc,
       cap LOCAL_LLM_FINAL_TOPK (8)
    4. usage = suma prompt_eval/eval tokens wszystkich okien
    5. raise RuntimeError jeśli >50% okien fail → TextTiling fallback
    return _Response(json.dumps({"shorts": merged}), usage.pt, usage.ct)
    """
```

### 2c. `src/clippyme/pipeline/main.py` (~12 linii w get_viral_clips)
Po `prompt, words = build_viral_prompt(...)`, PRZED `generate_with_model_fallback`:
```python
if isinstance(client, LocalLLMClient) and \
        estimate_prompt_tokens(prompt) > int(os.getenv("LOCAL_LLM_CHUNK_THRESHOLD_TOKENS", "6000")):
    from clippyme.pipeline.analysis.local_llm import generate_chunked
    response = generate_chunked(client, words, video_duration, instructions, creator)
else:
    response, model_name = generate_with_model_fallback(...)
```
(dalszy kod parsujący wspólny; `model_name` ustawiony na LOCAL_LLM_MODEL dla logu)

### 2d. Uwaga do headera językowego (lesson z sonda 5→6)
Header NIE hardcoded'uje "POLISH" — wykrywanie języka w promptcie jest kruche.
Sformułowanie: *"EVERY text field MUST be in the SAME LANGUAGE as the transcript
window below. The example titles in this prompt are FORM PATTERNS only — copy
their structure, never their language."* Ograniczenie mieszanki językowej i tak
zostaje (4B + włoskie przykłady) → patrz §7.

## 3. MACIERZ BŁĘDÓW

| Sytuacja | Reakcja |
|---|---|
| prompt okna > ctx (400 "exceeds") | nie powinno wystąpić (budget 450 rows ≈ 8.7k+4.4k < 16384); gdyby: retry z rows/2 dla TEGO okna |
| done_reason=="length" / pusty content | sleep 3 + retry ×1 → potem skip okna (log ⚠️) |
| Ollama down (conn refused) | raise natychmiast → TextTiling fallback (jak dziś) |
| >50% okien failed | raise → TextTiling fallback |
| degenerate timing (<10s/>75s) | _salvage_clip (naprawa istniejąca, sonda potwierdza że potrzeba realna) |
| klipy chełpiące się timami poza oknem | clamp do [t0,t1] w salvage okna |
| duplikaty między oknami (overlap) | dedupe IoU>0.35 keep wyższy score |
| VRAM OOM (inny proces np. Whisper) | istniejąca ścieżka OOM w _generate (halve ctx → fallback model) działa per okno |

## 4. CONFIG (nowe zmienne .env, wszystkie z defaults — zero breaking changes)
```
LOCAL_LLM_CHUNK_THRESHOLD_TOKENS=6000   # est > to → chunked path
LOCAL_LLM_NUM_CTX=16384                 # (było 8192; VRAM potwierdzony 4171 MiB peak)
LOCAL_LLM_WINDOW_ROWS=450
LOCAL_LLM_WINDOW_OVERLAP_ROWS=60
LOCAL_LLM_CHUNK_TOPK=3                  # klipów per okno (w headerze)
LOCAL_LLM_FINAL_TOPK=8                  # globalny cap po merge
LOCAL_LLM_CHUNK_RETRIES=1
```
Po zmianie .env: `sudo docker restart clippyme-backend` (stale env, §6 HANDOFF).

## 5. TESTY (kolejność)

1. **Offline unit (host python3, bez GPU)** — skrypt scp-em (wzorzec §6 HANDOFF):
   - plan_windows na prawdziwym transkrypcie 6852 wierszy: kontiguity, overlap,
     wszystkie okna ≤ budget, brak luki/krzyżowania;
   - estimate_prompt_tokens: pełny prompt 246k chars → est ≥ 100k (musi przekroczyć threshold);
   - merge: syntetyczne klipy nachodzące (IoU 0.4 → dedupe), poza oknem → clamp.
2. **Smoke 1 okno w kontenerze** (docker exec): build_viral_prompt_window →
   generate_content → JSON valid, ≤ 16k tok, klip w oknie.
3. **E2E długie wideo**: ponowny processing TEGO SAMEGO filmu (Costa Rica 55min)
   przez **upload cache'owanego źródła** `output/9d84798e*/Zakochałem…mp4` (2.4 GB,
   omija yt-dlp 403) → oczekiwane: logi '🦙 window i/17', brak 400, klipy score ≥1,
   tytuły PL, duration 10-75s. Porównanie z obecnym runem (12 × score 0 "part N").
4. **Regression krótkie wideo**: ten sam 27s URL co job `196b2979` → ścieżka
   single-shot (est < threshold), wyniki porównywalne (score 87-92).
5. **VRAM watch podczas E2E**: `nvidia-smi` — peak < 5.5 GB (buffer dla Whispera).

## 6. ROLLOUT / ROLLBACK
- Edycje w repo = bind-mount live, ale python importy mrożą się na starcie
  procesu → **konieczny `docker restart clippyme-backend`** (FS kontenera
  przetrwa; upgrade yt-dlp przetrwa — tylko recreate czyści).
- Rollback: `git checkout -- <3 pliki>` + restart (repo to clone git; zmiany
  lokalne najpierw `git diff` review). Sondy nic nie zmieniają w kodzie.
- Gate `isinstance + threshold` = krótkie wideo NIE zmienia ścieżki (test 4).

## 7. ZNANE OGRANICZENIA (akceptowane v1, udokumentowane — nie bugi)
1. **Mieszanka językowa tytułów** na nie-włoskich transkryptach (PL dominuje,
   włoskie ogony zdarzają się — przykłady w template są silnym anchorem dla 4B).
   Mitigacja v2: osobny LOCAL_TEMPLATE bez przykładów + minItems (sonda 6 pokazała
   koszt: degeneracyjne czasy — wymagałoby mocniejszych constraintów; osobne zadanie).
2. **hook == title** czasem (pełny template) → deterministyczny fix w salvage (§2b).
3. **Duration overshoot** 79-97s → trim do 75s w salvage; koniec może paść
   nie-ideale → snap-to-words poprawia w 0.6s.
4. **Copy quality < Gemini** — ocena "co jest viralne" na poziomie 4B; vibe OK
   (sonda: trafne momenty, np. "Primo kokos" zgadza się z fabułą tail okna), ale
   to najsłabsze ogniwo. UI toggle Local↔Gemini (HANDOFF §7 pkt 7) pozostaje
   planowany dla maksymalnej jakości.
5. Latencja: ~6 min rankingu dla 55 min wideo (17 okien × ~20s) — akceptowalne,
   progress log per okno.

## 8. NAKŁAD PRACY
~200 linii w 3 plikach + testy. Implementacja 1.5-2h, E2E walidacja ~1h
(w tym processing 55-min wideo przez pipeline ~35 min).

## 9. ARTYFAKTY SONDU (usunięte z serwera, wyniki w tym dokumencie)
- probe 1: VRAM/tokens/precision → §0.2-0.4 · probe 2: empty-array trap → §0.6
- probe 3: headroom 456 tok za mały → rows 450 · probe 4: minItems działa + retry
- probe 5: final config (pełny template + header) · probe 6: trimmed template odrzucony
