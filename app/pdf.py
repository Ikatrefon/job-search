"""Render dopasowanego CV (dict, schemat jak cv.json) → PDF przez szablon + Chromium."""
import json
from jinja2 import Template
from playwright.sync_api import sync_playwright
from . import config

def render_pdf(cv_dict, out_path):
    tpl = Template(config.TEMPLATE_HTML.read_text(encoding="utf-8"))
    svg = config.TEMPLATE_DIR / "assets" / "top.svg"
    top_svg = svg.read_text(encoding="utf-8") if svg.exists() else ""
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
