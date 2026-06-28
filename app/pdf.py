"""Render dopasowanego CV (dict, schemat jak cv.json) → PDF przez szablon + Chromium."""
import json
from jinja2 import Template
from playwright.sync_api import sync_playwright
from . import config

# mapowanie firma -> plik SVG „głowy" pracy (logo + stanowisko + daty), str. 2
HEAD_SVG = {
    "ASSEMBLY": "job_assembly.svg", "Publicis Le Pont": "job_publicis.svg",
    "Capgemini": "job_capgemini.svg", "accenture": "job_accenture.svg", "IKEA": "job_ikea.svg",
}

def _inject_head_svgs(cv_dict):
    assets = config.TEMPLATE_DIR / "assets"
    for e in cv_dict.get("experience", []):
        fn = HEAD_SVG.get(e.get("company"))
        if fn and (assets / fn).exists():
            e["head_svg"] = (assets / fn).read_text(encoding="utf-8")

def render_pdf(cv_dict, out_path):
    tpl = Template(config.TEMPLATE_HTML.read_text(encoding="utf-8"))
    svg = config.TEMPLATE_DIR / "assets" / "top.svg"
    top_svg = svg.read_text(encoding="utf-8") if svg.exists() else ""
    _inject_head_svgs(cv_dict)
    html = tpl.render(cv=cv_dict, top_svg=top_svg)
    # zapis w katalogu szablonu, żeby względne assets/ się rozwiązały
    tmp = config.TEMPLATE_DIR / "_render.html"
    tmp.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(tmp.as_uri(), wait_until="networkidle")
        pg.pdf(path=str(out_path), format="A4", print_background=True, prefer_css_page_size=True)
        b.close()
    return str(out_path)
