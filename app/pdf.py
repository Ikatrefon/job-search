"""Render dopasowanego CV (dict, schemat jak cv.json) → PDF przez szablon + Chromium."""
import json, re
from pathlib import Path
from jinja2 import Template
from playwright.sync_api import sync_playwright
from . import config

# mapowanie firma -> plik SVG „głowy" pracy (logo + stanowisko + daty)
HEAD_SVG = {
    "ASSEMBLY": "job_assembly.svg", "Publicis Le Pont": "job_publicis.svg",
    "Capgemini": "job_capgemini.svg", "accenture": "job_accenture.svg", "IKEA": "job_ikea.svg",
    "GEMACO": "job_gemaco.svg", "d-well": "job_dwell.svg", "GREY": "job_grey.svg",
}

# ── Auto-fix „ducha" z Figmy: logo eksportowane jako <rect fill="url(#pattern)"> ──
# Chromium źle renderuje SVG <pattern> w PDF (powiela kafelek). Zamieniamy każdy taki
# rect na bezpośredni <image> (ten sam data-URI, pozycja przeliczona z matrixa patternu).
_IMG_RE = re.compile(r'<image\b[^>]*\bid="([^"]+)"[^>]*>')
_PAT_RE = re.compile(r'<pattern\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</pattern>', re.S)
_USE_RE = re.compile(r'<use\b[^>]*?(?:xlink:href|href)="#([^"]+)"[^>]*?>')
_RECT_RE = re.compile(r'<rect\b[^>]*?fill="url\(#(pattern[^)"]+)\)"[^>]*?/>')

def _attr(tag, name, default=None):
    m = re.search(r'\b' + name + r'="([\d.eE+-]+)"', tag)
    return float(m.group(1)) if m else default

def _parse_transform(s):
    """Zwraca (a,b,c,d,e,f) z matrix()/scale()/translate() (Figma używa różnych)."""
    a = d = 1.0; b = c = e = f = 0.0
    if s:
        m = re.search(r'matrix\(([^)]+)\)', s)
        if m:
            v = [float(x) for x in re.split(r'[ ,]+', m.group(1).strip()) if x]
            if len(v) == 6:
                return tuple(v)
        sc = re.search(r'scale\(([^)]+)\)', s)
        if sc:
            v = [float(x) for x in re.split(r'[ ,]+', sc.group(1).strip()) if x]
            a = v[0]; d = v[1] if len(v) > 1 else v[0]
        tr = re.search(r'translate\(([^)]+)\)', s)
        if tr:
            v = [float(x) for x in re.split(r'[ ,]+', tr.group(1).strip()) if x]
            e = v[0]; f = v[1] if len(v) > 1 else 0.0
    return (a, b, c, d, e, f)

def depattern(svg):
    if "url(#pattern" not in svg:
        return svg
    images = {}
    for m in _IMG_RE.finditer(svg):
        tag, iid = m.group(0), m.group(1)
        href = re.search(r'(?:xlink:href|href)="([^"]+)"', tag)
        w, h = _attr(tag, "width"), _attr(tag, "height")
        if href and w and h:
            images[iid] = (href.group(1), w, h)
    patterns = {}
    for m in _PAT_RE.finditer(svg):
        pid, body = m.group(1), m.group(2)
        u = _USE_RE.search(body)
        if not u:
            continue
        tm = re.search(r'transform="([^"]+)"', u.group(0))
        patterns[pid] = (u.group(1),) + _parse_transform(tm.group(1) if tm else "")

    def repl(mo):
        tag = mo.group(0)
        pid = mo.group(1)
        if pid not in patterns:
            return tag
        iref, a, b, c, d, e, f = patterns[pid]
        if iref not in images or abs(b) > 1e-9 or abs(c) > 1e-9:
            return tag  # tylko proste skalowanie (bez rotacji/skosu)
        data, iw, ih = images[iref]
        rx = _attr(tag, "x", 0.0); ry = _attr(tag, "y", 0.0)
        rw = _attr(tag, "width"); rh = _attr(tag, "height")
        if rw is None or rh is None:
            return tag
        # zagnieżdżony <svg> = viewport, który KADRUJE obraz do ramki (jak pattern)
        xpx = e * rw; ypx = f * rh
        wpx = a * iw * rw; hpx = d * ih * rh
        return (f'<svg x="{rx:.3f}" y="{ry:.3f}" width="{rw:.3f}" height="{rh:.3f}" '
                f'viewBox="0 0 {rw:.3f} {rh:.3f}" preserveAspectRatio="none">'
                f'<image x="{xpx:.3f}" y="{ypx:.3f}" width="{wpx:.3f}" height="{hpx:.3f}" '
                f'preserveAspectRatio="none" xlink:href="{data}"/></svg>')

    return _RECT_RE.sub(repl, svg)

def _load_svg(name):
    p = config.TEMPLATE_DIR / "assets" / name
    return depattern(p.read_text(encoding="utf-8")) if p.exists() else ""

def _strip_header_text(svg, kws=("MICHAL", "DUCHOWSKI", "michal.duchowski")):
    """Usuwa z top.svg <text> nazwiska i kontaktu — w wersji ATS dajemy je tekstem HTML
    (badge/łuk/zdjęcie zostają w SVG). Dzięki temu nazwisko/kontakt = czysty, wczesny tekst."""
    def repl(m):
        return "" if any(k in m.group(0) for k in kws) else m.group(0)
    return re.sub(r'<text\b.*?</text>', repl, svg, flags=re.S)

def _inject_head_svgs(cv_dict):
    for e in cv_dict.get("experience", []):
        fn = HEAD_SVG.get(e.get("company"))
        if fn:
            svg = _load_svg(fn)
            if svg:
                e["head_svg"] = svg

# auto-fit: gdy któraś .page się przelewa (dłuższe treści pod ofertę) — zamiast ciąć,
# delikatnie zmniejsz font/odstępy sekcji doświadczenia i renderuj ponownie, aż wejdzie.
_OVERFLOW_JS = "() => [...document.querySelectorAll('.page')].some(p => p.scrollHeight > p.clientHeight + 2)"

def _fit_css(f):
    return ("<style>"
            f".blk-top{{font-size:{14*f:.2f}pt!important}}"
            f".blk-bot,.job2 ul.bul,.ats-job ul.bul{{font-size:{12*f:.2f}pt!important}}"
            f".job3 ul.bul,.ats-job.job3 ul.bul{{font-size:{11*f:.2f}pt!important}}"
            f".job2{{margin-bottom:{18*f:.1f}pt!important}}"
            f".job3{{margin-bottom:{max(7,20*f):.1f}pt!important}}"
            f".ats-job{{margin-bottom:{max(9,22*f):.1f}pt!important}}"
            f".ats-job.job3{{margin-bottom:{max(8,20*f):.1f}pt!important}}"
            f"ul.bul li{{margin-bottom:{1.5*f:.2f}pt!important}}"
            "</style>")

def render_pdf(cv_dict, out_path, template=None):
    """Render CV → PDF. template=None → wersja graficzna; config.TEMPLATE_ATS → wersja ATS.
    Oba warianty dostają top_svg/edu_svg/head_svg — szablon używa tego, czego potrzebuje.
    Auto-fit: jeśli strony się przelewają, zmniejsza font doświadczenia (aż do ~0.82) zamiast ciąć."""
    template = template or config.TEMPLATE_HTML
    tpl = Template(template.read_text(encoding="utf-8"))
    top_svg = _load_svg("top.svg")
    top_svg_ats = _strip_header_text(top_svg)          # bez nazwiska/kontaktu (te dajemy tekstem w ATS)
    edu_svg = _load_svg("edu.svg")
    _inject_head_svgs(cv_dict)
    base_html = tpl.render(cv=cv_dict, top_svg=top_svg, top_svg_ats=top_svg_ats, edu_svg=edu_svg)
    # zapis w katalogu szablonu, żeby względne assets/ się rozwiązały; nazwa unikalna per plik wyjściowy
    tmp = config.TEMPLATE_DIR / f"_render_{Path(out_path).stem}.html"
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        fit = 1.0
        while True:
            html = base_html if fit >= 0.999 else base_html.replace("</head>", _fit_css(fit) + "</head>", 1)
            tmp.write_text(html, encoding="utf-8")
            pg.goto(tmp.as_uri(), wait_until="networkidle")
            if fit <= 0.82 or not pg.evaluate(_OVERFLOW_JS):
                break
            fit -= 0.05
        pg.pdf(path=str(out_path), format="A4", print_background=True, prefer_css_page_size=True)
        b.close()
    return str(out_path)
