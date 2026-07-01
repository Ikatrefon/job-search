"""Warstwa źródeł ofert — odcięta od silnika. Każde źródło zwraca listę ofert
w JEDNYM formacie: {tytul, firma, opis, link, kraj, zrodlo}. Silnik (ocena/generacja)
tego nie dotyka. Teraz: Arbeitnow (bez klucza). Adzuna dołożymy jako kolejny adapter.
"""
import json, re, html, urllib.request

def _clean(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h or ""))).strip()

def _get_json(url, timeout=25):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "jobsearch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

# ---------- Arbeitnow (feed, bez klucza; głównie DE/UE) ----------
def fetch_arbeitnow(keywords, limit=20):
    """Pobiera feed i filtruje LOKALNIE po słowach kluczowych (API nie ma wyszukiwarki)."""
    data = _get_json("https://www.arbeitnow.com/api/job-board-api").get("data", [])
    kws = [k.lower() for k in keywords if k.strip()]
    out = []
    for j in data:
        title = j.get("title", "")
        desc = _clean(j.get("description", ""))
        hay = (title + " " + desc + " " + " ".join(j.get("tags", []))).lower()
        if kws and not any(k in hay for k in kws):
            continue
        out.append({
            "tytul": title, "firma": j.get("company_name", ""), "opis": desc,
            "link": j.get("url", ""), "kraj": j.get("location", ""), "zrodlo": "arbeitnow",
        })
        if len(out) >= limit:
            break
    return out

# ---------- Adzuna (wyszukiwarka + UE; wymaga app_id/app_key) — DO WŁĄCZENIA ----------
def fetch_adzuna(app_id, app_key, what, where="", country="pl", limit=20):
    if not (app_id and app_key):
        return []
    import urllib.parse
    q = urllib.parse.urlencode({
        "app_id": app_id, "app_key": app_key, "what": what, "where": where,
        "results_per_page": min(limit, 50), "content-type": "application/json",
    })
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1?{q}"
    results = _get_json(url).get("results", [])
    out = []
    for j in results:
        out.append({
            "tytul": j.get("title", ""), "firma": (j.get("company") or {}).get("display_name", ""),
            "opis": _clean(j.get("description", "")), "link": j.get("redirect_url", ""),
            "kraj": (j.get("location") or {}).get("display_name", ""), "zrodlo": "adzuna",
        })
        if len(out) >= limit:
            break
    return out
