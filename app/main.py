"""JOB SEARCH — MVP (etap 1): kanał ręczny → ocena → generacja (guardrail) → PDF → poczekalnia."""
import json, os, re
from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from . import config, db, engine, pdf

def _extract_text(path):
    if str(path).lower().endswith(".pdf"):
        import fitz
        doc = fitz.open(path)
        return "\n".join(pg.get_text() for pg in doc)
    try: return path.read_text(encoding="utf-8", errors="ignore")
    except Exception: return ""

app = FastAPI(title="Job Search — CV automat")
templates = Jinja2Templates(directory=str(config.APP_DIR / "templates"))
db.init()

def _threshold():
    return int(db.get_config("threshold", config.DEFAULT_THRESHOLD))

def _evaluate_ad(ad_id, model=None):
    """Ocena ogłoszenia. model=None → domyślny (Sonnet); model=Opus → ręczna eskalacja."""
    ad = db.get_ad(ad_id)
    base = engine.load_base_cv()
    used = model or engine._eval_model()
    # poprzednie wants/gaps — żeby pogłębiona ocena ich NIE wyczyściła, gdy model je pominie
    prev_wants = []; prev_gaps = {}
    try:
        pv = json.loads(ad.get("summary") or "")
        if isinstance(pv, dict): prev_wants = pv.get("wants") or []
        pg = json.loads(ad.get("gaps") or "")
        if isinstance(pg, dict): prev_gaps = {"missing": pg.get("missing") or [], "tune": pg.get("tune") or []}
    except Exception:
        pass
    try:
        score, verdict, wants, gaps = engine.evaluate(ad, base, model=model)
        if not wants and prev_wants: wants = prev_wants
        if not (gaps.get("missing") or gaps.get("tune")) and (prev_gaps.get("missing") or prev_gaps.get("tune")):
            gaps = prev_gaps
        db.update_ad_eval(ad_id, score,
                          json.dumps({"verdict": verdict, "wants": wants}, ensure_ascii=False),
                          json.dumps(gaps, ensure_ascii=False), used)
    except Exception as e:
        db.update_ad_eval(ad_id, 0, "", json.dumps({"error": f"Błąd oceny: {e}"}, ensure_ascii=False), used)

def _generate_cv(ad_id):
    """Generacja dopasowanego CV + guardrail + PDF (wolniejsze, na żądanie)."""
    ad = db.get_ad(ad_id)
    base = engine.load_base_cv()
    try:
        tailored, justification = engine.generate(ad, base, ad.get("summary") or "")
        tailored, warnings = engine.guardrail(base, tailored)
        out_ats = config.PDF_DIR / f"{ad_id}.pdf"            # ATS = domyślny plik
        out_gfx = config.PDF_DIR / f"{ad_id}_graphic.pdf"    # wersja graficzna (na żądanie)
        pdf.render_pdf(tailored, out_ats, template=config.TEMPLATE_ATS)
        pdf.render_pdf(tailored, out_gfx)
        db.save_cv(ad_id, tailored, justification, warnings, str(out_ats))
    except Exception as e:
        db.save_cv(ad_id, base, f"Błąd generacji: {e}", [], "")

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "ads": db.list_ads(), "threshold": _threshold(), "mock": config.USE_MOCK})

@app.post("/paste")
def paste(opis: str = Form(...), tytul: str = Form(""), firma: str = Form(""),
          link: str = Form(""), kraj: str = Form("")):
    ad_id = db.add_ad({"tytul": tytul, "firma": firma, "opis": opis,
                       "link": link, "kraj": kraj, "zrodlo": "manual"})
    _evaluate_ad(ad_id)            # tylko ocena (szybko); CV generuje się na żądanie w detalu
    return RedirectResponse(f"/ad/{ad_id}", status_code=303)

@app.get("/ad/{ad_id}", response_class=HTMLResponse)
def ad_detail(request: Request, ad_id: int):
    ad = db.get_ad(ad_id)
    if not ad:
        return RedirectResponse("/", status_code=303)
    cv = db.get_cv(ad_id)
    warnings = json.loads(cv["warnings"]) if cv and cv.get("warnings") else []
    profile = ""
    if cv:
        try: profile = "\n\n".join(json.loads(cv["content_json"]).get("profile", []))
        except Exception: pass
    # ocena: format = JSON; obsługa starszych wariantów (lista / tekst) wstecznie.
    # wants_raw/gaps_raw pokazujemy TYLKO dla starych wpisów tekstowych — nigdy surowego JSON-a.
    verdict = None; wants = None; wants_raw = ""
    try:
        v = json.loads(ad.get("summary") or "")
        if isinstance(v, dict): verdict, wants = v.get("verdict"), v.get("wants", [])
        elif isinstance(v, list): wants = v
        else: wants_raw = str(v)
    except Exception:
        wants_raw = ad.get("summary") or ""
    gaps_missing = gaps_tune = gaps_err = None; gaps_raw = ""
    try:
        g = json.loads(ad.get("gaps") or "")
        if isinstance(g, dict):
            gaps_missing, gaps_tune, gaps_err = g.get("missing", []), g.get("tune", []), g.get("error")
        else: gaps_raw = str(g)
    except Exception:
        gaps_raw = ad.get("gaps") or ""
    em = ad.get("eval_model")
    return templates.TemplateResponse(request, "detail.html", {
        "ad": ad, "cv": cv, "warnings": warnings, "profile": profile, "threshold": _threshold(),
        "verdict": verdict, "wants": wants, "wants_raw": wants_raw,
        "gaps_missing": gaps_missing, "gaps_tune": gaps_tune, "gaps_err": gaps_err,
        "gaps_raw": gaps_raw,
        "eval_model_label": config.MODEL_LABELS.get(em, em or ""),
        "is_opus": em == config.OPUS_MODEL})

@app.get("/pdf/{ad_id}")
def get_pdf(ad_id: int):
    """Domyślnie wersja ATS (= cv.pdf_path)."""
    cv = db.get_cv(ad_id)
    if not cv or not cv.get("pdf_path"):
        return RedirectResponse(f"/ad/{ad_id}", status_code=303)
    # inline → iframe wyświetla podgląd zamiast pobierać; pobieranie wymusza atrybut download na linku
    return FileResponse(cv["pdf_path"], media_type="application/pdf",
                        headers={"Content-Disposition": "inline"})

@app.get("/pdf/{ad_id}/graphic")
def get_pdf_graphic(ad_id: int):
    """Wersja graficzna (na bezpośredni kontakt z człowiekiem)."""
    path = config.PDF_DIR / f"{ad_id}_graphic.pdf"
    if not path.exists():
        return RedirectResponse(f"/ad/{ad_id}", status_code=303)
    return FileResponse(str(path), media_type="application/pdf",
                        headers={"Content-Disposition": "inline"})

@app.post("/ad/{ad_id}/meta")
def update_meta(ad_id: int, tytul: str = Form(""), firma: str = Form(""),
                kraj: str = Form(""), link: str = Form("")):
    db.update_ad_meta(ad_id, tytul.strip(), firma.strip(), kraj.strip(), link.strip())
    return RedirectResponse(f"/ad/{ad_id}", status_code=303)

@app.post("/reorder")
async def reorder(request: Request):
    data = await request.json()
    db.reorder(data.get("ids", []))
    return {"ok": True}

@app.post("/ad/{ad_id}/delete")
def delete_ad(ad_id: int):
    cv = db.get_cv(ad_id)
    if cv and cv.get("pdf_path"):
        try: os.remove(cv["pdf_path"])
        except OSError: pass
    try: os.remove(config.PDF_DIR / f"{ad_id}_graphic.pdf")
    except OSError: pass
    db.delete_ad(ad_id)
    return RedirectResponse("/", status_code=303)

@app.post("/ad/{ad_id}/deepen")
def deepen(ad_id: int):
    _evaluate_ad(ad_id, model=config.OPUS_MODEL)   # ręczna eskalacja do Opus
    return RedirectResponse(f"/ad/{ad_id}", status_code=303)

@app.post("/ad/{ad_id}/generate")
def generate_cv(ad_id: int):
    _generate_cv(ad_id)
    return RedirectResponse(f"/ad/{ad_id}", status_code=303)

@app.post("/ad/{ad_id}/edit")
def edit_cv(ad_id: int, profile: str = Form(...)):
    """„Popraw" bez wywołania modelu: edycja podsumowania + ponowny render PDF."""
    cv = db.get_cv(ad_id)
    if cv:
        content = json.loads(cv["content_json"])
        content["profile"] = [p.strip() for p in profile.split("\n\n") if p.strip()]
        out_ats = config.PDF_DIR / f"{ad_id}.pdf"
        out_gfx = config.PDF_DIR / f"{ad_id}_graphic.pdf"
        pdf.render_pdf(content, out_ats, template=config.TEMPLATE_ATS)
        pdf.render_pdf(content, out_gfx)
        db.save_cv(ad_id, content, cv["justification"],
                   json.loads(cv["warnings"]) if cv.get("warnings") else [], str(out_ats), edited=1)
    return RedirectResponse(f"/ad/{ad_id}", status_code=303)

@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    base = engine.load_base_cv()
    return templates.TemplateResponse(request, "settings.html", {
        "threshold": _threshold(),
        "models": config.MODELS,
        "eval_model": db.get_config("eval_model", config.EVAL_MODEL),
        "gen_model": db.get_config("gen_model", config.GEN_MODEL),
        "mock": config.USE_MOCK,
        "base_cv_name": base.get("name", "Bazowe CV"),
        "docs": db.list_docs()})

@app.post("/docs/upload")
async def upload_doc(file: UploadFile = File(...)):
    if file and file.filename:
        orig = file.filename
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", orig)[:60] or "dokument"
        did = db.add_doc(orig, safe)
        dest = config.DOCS_DIR / f"{did}_{safe}"
        dest.write_bytes(await file.read())
        (config.DOCS_DIR / f"{did}.txt").write_text(_extract_text(dest), encoding="utf-8")
    return RedirectResponse("/settings", status_code=303)

@app.post("/docs/{doc_id}/delete")
def delete_doc(doc_id: int):
    if db.get_doc(doc_id):
        for f in config.DOCS_DIR.glob(f"{doc_id}_*"):
            try: f.unlink()
            except OSError: pass
        sidecar = config.DOCS_DIR / f"{doc_id}.txt"
        if sidecar.exists(): sidecar.unlink()
        db.del_doc(doc_id)
    return RedirectResponse("/settings", status_code=303)

@app.post("/settings")
def save_settings(threshold: int = Form(...), eval_model: str = Form(...), gen_model: str = Form(...)):
    db.set_config("threshold", threshold)
    if eval_model in config.VALID_MODEL_IDS: db.set_config("eval_model", eval_model)
    if gen_model in config.VALID_MODEL_IDS: db.set_config("gen_model", gen_model)
    return RedirectResponse("/settings", status_code=303)
