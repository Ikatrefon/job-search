# JOB SEARCH — automat CV (MVP, etap 1)

Wklejasz ogłoszenie → system ocenia dopasowanie do Twojego bazowego CV, generuje
**dopasowane CV w PDF** (treść tylko z bazowego CV) i pokazuje je w poczekalni do akceptacji.
**Nie wysyła** aplikacji — decyzja zawsze Twoja.

## Uruchomienie
```bash
cd "JOB SEARCH"
# (raz) zależności są w app/.venv ; jeśli brak:  python3 -m venv app/.venv && app/.venv/bin/pip install fastapi "uvicorn[standard]" anthropic jinja2 python-multipart playwright && app/.venv/bin/python -m playwright install chromium

# tryb realny (Claude):
export ANTHROPIC_API_KEY=sk-ant-...
app/.venv/bin/uvicorn app.main:app --reload --port 8200
# → http://localhost:8200
```
Bez `ANTHROPIC_API_KEY` działa **tryb MOCK** (offline, deterministycznie) — cały przepływ
da się przejść bez wywołań API (ocena = pokrycie słów, generacja = przestawienie treści).

## Jak to działa (etap 1)
kanał ręczny (wklejka) → **ocena** (tani model: score 0-100 + czego chce ogłoszenie + luki)
→ jeśli ≥ próg: **generacja** (mocniejszy model: przestawia/akcentuje PRAWDZIWĄ treść)
→ **guardrail** (twarde niezmienniki: zero nowych firm/skilli, daty/role/kontakt z bazy, flaguje możliwe dopiski)
→ **PDF** z szablonu → **poczekalnia** (akceptuj / odrzuć / popraw / eksportuj).

## Struktura
- `template/` — szablon CV (wierne odwzorowanie bazowego CV): `template.html` (Jinja2+CSS), `cv.json` (bazowe CV = źródło prawdy), `assets/` (logotypy, zdjęcie).
- `app/config.py` — ścieżki, modele (eval=Haiku, gen=Sonnet), próg, klucz.
- `app/db.py` — SQLite (`ogloszenia`, `cv_wygenerowane`, `konfiguracja`).
- `app/engine.py` — ocena + generacja (Anthropic, cache bazowego CV) + guardrail; tryb mock.
- `app/pdf.py` — dopasowane CV → szablon → Chromium (Playwright) → PDF.
- `app/main.py` — FastAPI + poczekalnia (Tailwind).
- `app/data/` — `jobsearch.db` + `pdfs/` (generowane PDF-y).

## Zasada nadrzędna
Warstwa źródeł odcięta od silnika: ogłoszenie wchodzi we wspólnym formacie. MVP = kanał ręczny;
Adzuna (etap 2) i scrapery (etap 3) dokłada się później bez ruszania silnika.

## Następne kroki
- Etap 2: integracja API Adzuna + cron + dociąganie pełnego opisu spod linku.
- Bogatsza edycja w „popraw" (teraz: podsumowanie). Mocniejszy guardrail (weryfikacja LLM + podświetlanie zmian).
- Render PDF: rozważyć WeasyPrint zamiast Chromium dla lżejszego VPS.
