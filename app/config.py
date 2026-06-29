"""Konfiguracja MVP — ścieżki, modele, progi."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # JOB SEARCH/

# wczytaj .env (proste, bez zależności) — nie nadpisuje istniejących zmiennych środowiska
_env = BASE_DIR / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
APP_DIR = BASE_DIR / "app"
TEMPLATE_DIR = BASE_DIR / "template"                        # szablon CV (HTML/CSS + assets)
TEMPLATE_HTML = TEMPLATE_DIR / "template.html"             # wersja graficzna (dla człowieka)
TEMPLATE_ATS = TEMPLATE_DIR / "template_ats.html"          # wersja ATS (czysty tekst, domyślna)
CV_BASE_JSON = TEMPLATE_DIR / "cv.json"                     # bazowe CV = źródło prawdy

DATA_DIR = APP_DIR / "data"
PDF_DIR = DATA_DIR / "pdfs"
DOCS_DIR = DATA_DIR / "docs"          # dodatkowe dokumenty kandydata
DB_PATH = DATA_DIR / "jobsearch.db"

# Anthropic — ocena tania/szybka, generacja mocniejsza
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
EVAL_MODEL = os.environ.get("JS_EVAL_MODEL", "claude-sonnet-4-6")   # głębsza ocena (wyjście małe → tanio)
GEN_MODEL = os.environ.get("JS_GEN_MODEL", "claude-sonnet-4-6")
OPUS_MODEL = "claude-opus-4-8"                                       # do ręcznej eskalacji „pogłęb analizę"

# Modele do wyboru w Ustawieniach (id, etykieta)
MODELS = [
    ("claude-haiku-4-5-20251001", "Haiku 4.5 — szybki i tani"),
    ("claude-sonnet-4-6", "Sonnet 4.6 — zbalansowany"),
    ("claude-opus-4-8", "Opus 4.8 — najmocniejszy, najdroższy"),
]
VALID_MODEL_IDS = {m[0] for m in MODELS}
MODEL_LABELS = {mid: label.split(" — ")[0] for mid, label in MODELS}   # krótka nazwa do UI

# Próg dopasowania — poniżej nie generujemy CV (nie palimy wywołań)
DEFAULT_THRESHOLD = int(os.environ.get("JS_THRESHOLD", "60"))

USE_MOCK = not bool(ANTHROPIC_API_KEY)                      # bez klucza → tryb mock (pipeline działa offline)

for d in (DATA_DIR, PDF_DIR, DOCS_DIR):
    d.mkdir(parents=True, exist_ok=True)
