"""Silnik: ocena ogłoszenia + generacja dopasowanego CV + guardrail.

Bez ANTHROPIC_API_KEY działa w trybie MOCK (deterministycznie, offline) — żeby cały
pipeline (baza→ocena→generacja→PDF→poczekalnia) dało się przejść bez palenia wywołań.
Z kluczem używa Claude: ocena = tani model, generacja = mocniejszy, bazowe CV cache'owane.
"""
import json, re, copy
from . import config, db

def _eval_model(): return db.get_config("eval_model", config.EVAL_MODEL)
def _gen_model(): return db.get_config("gen_model", config.GEN_MODEL)

# ---------- bazowe CV ----------
def load_base_cv():
    return json.loads(config.CV_BASE_JSON.read_text(encoding="utf-8"))

def extra_context():
    """Tekst dodatkowych dokumentów kandydata (sidecar .txt per dokument)."""
    parts = []
    for d in db.list_docs():
        p = config.DOCS_DIR / (str(d["id"]) + ".txt")
        if p.exists():
            t = p.read_text(encoding="utf-8", errors="ignore").strip()
            if t: parts.append(f"--- {d['orig']} ---\n{t}")
    return "\n\n".join(parts)

def cv_to_text(cv):
    """Bazowe CV jako zwięzły tekst do promptu/oceny."""
    parts = [cv.get("name",""), " ".join(cv.get("profile",[])), cv.get("lecturer","")]
    parts += cv.get("itsme",[])
    for a in cv.get("additional",[]): parts.append(f"{a['label']}: {a['text']}")
    for e in cv.get("experience",[]):
        parts.append(f"{e['company']} — {e['role']} ({e['dates']})")
        parts += e.get("bullets",[])
    parts += cv.get("education",{}).get("fields",[])
    parts += cv.get("tech_skills",[]) + cv.get("about_me",[]) + cv.get("interests",[])
    return "\n".join(parts)

_WORD = re.compile(r"[a-zA-Z]{3,}")
def _tokens(s): return set(w.lower() for w in _WORD.findall(s or ""))

def _extract_json(txt):
    txt = txt.strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*\n?", "", txt); txt = re.sub(r"\n?```$", "", txt)
    a, b = txt.find("{"), txt.rfind("}")
    return json.loads(txt[a:b+1])

# ---------- ANTHROPIC ----------
def _client():
    import anthropic
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

def _ad_text(ad):
    return (f"TITLE: {ad.get('tytul','')}\nCOMPANY: {ad.get('firma','')}\n"
            f"COUNTRY: {ad.get('kraj','')}\n\nDESCRIPTION:\n{ad.get('opis','')}")

EVAL_SYS = (
    "Jesteś doświadczonym rekruterem i doradcą kariery. Oceniasz, na ile bazowe CV kandydata "
    "pasuje do konkretnego ogłoszenia o pracę. Bądź wnikliwy i szczery — nie ogólnikowy.\n"
    "Weź pod uwagę: twarde wymagania vs mile widziane, poziom seniority (czy kandydat nie jest za słaby/za mocny), "
    "transfer doświadczenia z innej branży/roli, ukryte oczekiwania i ton/kulturę, oraz realne ryzyka i czerwone flagi.\n"
    "Odpowiedz WYŁĄCZNIE w formacie JSON, po POLSKU:\n"
    '{"score": <int 0-100, realistyczny>, '
    '"verdict": "2-4 zdania szczerej oceny: czy to realne dopasowanie, dla kogo, główne ryzyko/przewaga (seniority, branża)", '
    '"wants": ["3-6 najważniejszych, KONKRETNYCH rzeczy których pracodawca naprawdę szuka (priorytety)"], '
    '"gaps_missing": ["czego w CV brakuje CAŁKOWICIE względem ogłoszenia — z krótkim czemu to ważne (lub [])"], '
    '"gaps_tune": ["co JEST w CV ale warto wyeksponować/przeformułować pod to ogłoszenie — konkretnie (lub [])"]}'
)

def evaluate(ad, base_cv, model=None):
    """Zwraca (score:int, verdict:str, wants:list, gaps:dict{missing,tune})."""
    if config.USE_MOCK:
        return _mock_evaluate(ad, base_cv)
    cv_text = cv_to_text(base_cv)
    extra = extra_context()
    if extra: cv_text += "\n\nDODATKOWE DOKUMENTY KANDYDATA:\n" + extra
    msg = _client().messages.create(
        model=model or _eval_model(), max_tokens=1400,
        system=[{"type":"text","text":"BASE CV:\n"+cv_text,"cache_control":{"type":"ephemeral"}},
                {"type":"text","text":EVAL_SYS}],
        messages=[{"role":"user","content":_ad_text(ad)}])
    d = _extract_json(msg.content[0].text)
    return (int(d.get("score",0)), d.get("verdict",""), d.get("wants",[]),
            {"missing": d.get("gaps_missing",[]), "tune": d.get("gaps_tune",[])})

GEN_SYS = """You tailor the candidate's BASE CV to a specific job ad.
HARD RULES (the product depends on this):
- Use ONLY facts present in the BASE CV. Do NOT invent skills, tools, employers, dates or achievements.
- Keep every experience entry's company, role and dates EXACTLY as in the base.
- You MAY: reorder/select bullets, lightly rephrase wording to mirror the ad's language, rewrite the profile summary, reorder skills/itsme to surface what matters for this ad.
- Output the FULL CV as JSON with the SAME schema/keys as the base CV.
Return ONLY JSON: {"cv": <full cv object, same schema as base>, "justification": "2-4 sentences: why this score, what was emphasized, what gaps remain"}."""

def generate(ad, base_cv, summary):
    if config.USE_MOCK:
        return _mock_generate(ad, base_cv, summary)
    cv_json = json.dumps(base_cv, ensure_ascii=False)
    extra = extra_context()
    sys_cv = "BASE CV (JSON):\n" + cv_json
    if extra: sys_cv += "\n\nDODATKOWE DOKUMENTY KANDYDATA (prawdziwy materiał — wolno z niego czerpać):\n" + extra
    msg = _client().messages.create(
        model=_gen_model(), max_tokens=4000,
        system=[{"type":"text","text":sys_cv,"cache_control":{"type":"ephemeral"}},
                {"type":"text","text":GEN_SYS}],
        messages=[{"role":"user","content":_ad_text(ad)+f"\n\nMATCH SUMMARY:\n{summary}"}])
    d = _extract_json(msg.content[0].text)
    return d.get("cv", copy.deepcopy(base_cv)), d.get("justification","")

# ---------- MOCK ----------
def _mock_evaluate(ad, base_cv):
    at, ct = _tokens(ad.get("opis","")+" "+ad.get("tytul","")), _tokens(cv_to_text(base_cv))
    if not at: return 0, "(mock)", ["(mock) brak opisu"], {"missing":[], "tune":[]}
    overlap = at & ct
    score = max(5, min(98, round(100*len(overlap)/max(12,len(at)))))
    wants = [f"(mock) {w}" for w in sorted(list(overlap))[:6]] or ["(mock) brak"]
    missing = [f"(mock) {m}" for m in sorted(list(at - ct))[:6]]
    return score, "(mock) wstępna ocena na podstawie pokrycia słów", wants, {"missing": missing, "tune": []}

def _mock_generate(ad, base_cv, summary):
    cv = copy.deepcopy(base_cv)
    at = _tokens(ad.get("opis","")+" "+ad.get("tytul",""))
    cv["itsme"] = sorted(cv.get("itsme",[]), key=lambda b: -len(_tokens(b)&at))   # najtrafniejsze wyżej
    if cv.get("profile"):
        cv["profile"][0] = f"[Tailored for: {ad.get('tytul','the role')}] " + cv["profile"][0]
    return cv, "(mock) CV przestawione pod ogłoszenie: najtrafniejsze kompetencje podciągnięte wyżej. Treść wyłącznie z bazowego CV."

# ---------- GUARDRAIL ----------
def guardrail(base_cv, cv):
    """Twarde niezmienniki: zero nowych firm/skilli/edukacji, daty/role z bazy, kontakt z bazy.
    Zwraca (oczyszczone_cv, ostrzeżenia[])."""
    warn = []
    out = copy.deepcopy(cv)
    extra_tok = _tokens(extra_context())   # treść dokumentów też = „prawda"

    # tożsamość i kontakt — zawsze z bazy
    for k in ("name","contact","photo","badge","signature"):
        if k in base_cv: out[k] = base_cv[k]

    # doświadczenie: tylko firmy z bazy; firma/rola/daty wymuszone z bazy; bullety sprawdzane
    base_exp = {e["company"]: e for e in base_cv.get("experience",[])}
    fixed_exp = []
    for e in out.get("experience",[]):
        b = base_exp.get(e.get("company"))
        if not b:
            warn.append(f"Pominięto nieznane doświadczenie: {e.get('company')}"); continue
        e["company"], e["role"], e["dates"], e["logo"] = b["company"], b["role"], b["dates"], b.get("logo")
        if "aside" in b: e["aside"] = b["aside"]
        base_tok = set().union(*[_tokens(x) for x in b.get("bullets",[])]) if b.get("bullets") else set()
        base_tok |= extra_tok
        for blt in e.get("bullets",[]):
            t = _tokens(blt)
            if t and base_tok and len(t & base_tok)/len(t) < 0.45:
                warn.append(f"[{b['company']}] możliwe dopisanie: \"{blt[:70]}...\"")
        fixed_exp.append(e)
    # firmy z bazy pominięte przez model → dołącz w oryginale (nie gubimy historii)
    present = {e["company"] for e in fixed_exp}
    for comp, b in base_exp.items():
        if comp not in present: fixed_exp.append(copy.deepcopy(b))
    # zachowaj kolejność jak w bazie
    order = [e["company"] for e in base_cv.get("experience",[])]
    out["experience"] = sorted(fixed_exp, key=lambda e: order.index(e["company"]) if e["company"] in order else 999)

    # tech_skills / education / additional — podzbiór bazy
    base_sk = set(base_cv.get("tech_skills",[]))
    kept = [s for s in out.get("tech_skills",[]) if s in base_sk]
    drop = [s for s in out.get("tech_skills",[]) if s not in base_sk]
    if drop: warn.append("Usunięto nieznane umiejętności: " + ", ".join(drop))
    out["tech_skills"] = kept or base_cv.get("tech_skills",[])
    out["education"] = base_cv.get("education", out.get("education"))
    for k in ("about_me","interests","quotes","lecturer"):
        if k in base_cv: out[k] = base_cv[k]
    return out, warn
