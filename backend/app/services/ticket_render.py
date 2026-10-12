"""Server-side ticket art: fill SVG templates (ticket-a/b) and export PNG/SVG."""

from __future__ import annotations

import base64
import logging
import os
import re
from contextlib import contextmanager
from io import BytesIO
import xml.etree.ElementTree as ET
from pathlib import Path

from datetime import datetime

from app.config import ROOT
from app.services.jalali_schedule import format_hero_schedule, ticket_city_line, ticket_locale

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

logger = logging.getLogger(__name__)

REQUIRED_TICKET_FIELDS = frozenset(
    {"name", "name_stub", "date", "time", "venue", "city_line", "code1", "code2", "no1", "no2"}
)

_VAZIRMATN_TTF = ROOT / "assets" / "fonts" / "Vazirmatn-Regular.ttf"
_FONTCONFIG_PATH = ROOT / "storage" / "fonts" / "fonts.conf"
_FONT_FACE_CSS: str | None = None


class TicketFontError(FileNotFoundError):
    """Persian ticket font missing on server."""


def vazirmatn_font_path() -> Path:
    return _VAZIRMATN_TTF


def ensure_vazirmatn_font() -> Path:
    if not _VAZIRMATN_TTF.is_file():
        raise TicketFontError(
            f"Persian ticket font missing: {_VAZIRMATN_TTF} (run wwh-deploy install)"
        )
    return _VAZIRMATN_TTF


def _embedded_vazirmatn_css() -> str:
    """@font-face for CairoSVG/PNG export (file URL + data URI for browsers)."""
    global _FONT_FACE_CSS
    if _FONT_FACE_CSS is not None:
        return _FONT_FACE_CSS
    if not _VAZIRMATN_TTF.is_file():
        logger.error("ticket font missing at %s", _VAZIRMATN_TTF)
        _FONT_FACE_CSS = ""
        return _FONT_FACE_CSS
    file_url = _VAZIRMATN_TTF.resolve().as_uri()
    b64 = base64.b64encode(_VAZIRMATN_TTF.read_bytes()).decode("ascii")
    _FONT_FACE_CSS = (
        "@font-face{font-family:'Vazirmatn';"
        f"src:url('{file_url}') format('truetype'),"
        f"url('data:font/ttf;base64,{b64}') format('truetype');"
        "font-weight:100 900;font-style:normal;}"
    )
    return _FONT_FACE_CSS


@contextmanager
def _cairo_fontconfig_scope():
    """Point Fontconfig at bundled Vazirmatn for Pango/Cairo PNG export."""
    ensure_vazirmatn_font()
    font_dir = _VAZIRMATN_TTF.parent.resolve()
    _FONTCONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _FONTCONFIG_PATH.is_file():
        _FONTCONFIG_PATH.write_text(
            '<?xml version="1.0"?>\n'
            '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
            "<fontconfig>\n"
            f"  <dir>{font_dir}</dir>\n"
            "</fontconfig>\n",
            encoding="utf-8",
        )
    prev = os.environ.get("FONTCONFIG_FILE")
    os.environ["FONTCONFIG_FILE"] = str(_FONTCONFIG_PATH.resolve())
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("FONTCONFIG_FILE", None)
        else:
            os.environ["FONTCONFIG_FILE"] = prev


def _inject_persian_font(root: ET.Element) -> None:
    ensure_vazirmatn_font()
    css = _embedded_vazirmatn_css()
    if not css:
        return
    for el in root.iter():
        if not el.tag.endswith("style"):
            continue
        block = el.text or ""
        if "@font-face" in block and "Vazirmatn" in block:
            return
        el.text = css + block
        return
    defs = root.find(f"{{{SVG_NS}}}defs")
    if defs is None:
        defs = ET.Element(f"{{{SVG_NS}}}defs")
        root.insert(0, defs)
    style = ET.SubElement(defs, f"{{{SVG_NS}}}style")
    style.text = css


def _template_path(group: str) -> Path:
    name = "ticket-b.svg" if str(group).upper() == "B" else "ticket-a.svg"
    return ROOT / name


def _value_for(
    field: str,
    name: str,
    code: str,
    number: str | int,
    *,
    date_tagline: str = "",
    time_hm: str = "",
    venue: str = "",
    city: str = "",
) -> str:
    if field in ("name", "name_stub"):
        return name
    if field in ("code1", "code2"):
        return code
    if field in ("no1", "no2"):
        return str(number)
    if field == "date":
        return date_tagline
    if field == "time":
        return time_hm
    if field == "venue":
        return venue
    if field == "city_line":
        return ticket_city_line(city)
    return ""


def _apply_field_direction(el: ET.Element, field: str, value: str, locale: str) -> None:
    if field in ("name", "name_stub"):
        el.set("direction", "rtl")
        return
    if field == "time":
        el.set("direction", "ltr")
        el.set("unicode-bidi", "embed")
        return
    if field == "date":
        el.set("direction", "rtl" if locale == "fa" else "ltr")
        return
    if field == "venue":
        el.set("direction", "ltr" if ticket_locale(value, "") == "en" else "rtl")


def normalize_ticket_svg_xml(xml_str: str) -> str:
    """Strip ElementTree ns0: prefixes so browser innerHTML recognizes <svg>."""
    xml_str = re.sub(r"\bns\d+:", "", xml_str)
    xml_str = re.sub(r'\sxmlns:ns\d+="http://www\.w3\.org/2000/svg"', "", xml_str)
    if 'xmlns="http://www.w3.org/2000/svg"' not in xml_str:
        xml_str = re.sub(
            r"<svg(\s)",
            r'<svg xmlns="http://www.w3.org/2000/svg"\1',
            xml_str,
            count=1,
        )
    return xml_str


def _apply_city_line_direction(el: ET.Element, value: str) -> None:
    if ticket_locale("", value) == "en":
        el.set("direction", "ltr")
    else:
        el.set("direction", "rtl")


def fill_ticket_svg(
    group: str,
    holder_name: str,
    public_code: str,
    display_number: int,
    *,
    event_at: datetime | None = None,
    venue: str = "",
    city: str = "",
) -> str:
    path = _template_path(group)
    if not path.is_file():
        raise FileNotFoundError(f"ticket template missing: {path.name}")
    raw = normalize_ticket_svg_xml(path.read_text(encoding="utf-8"))
    root = ET.fromstring(raw)
    _inject_persian_font(root)
    code = re.sub(r"\D", "", public_code or "").zfill(4)[-4:]
    venue_line = venue or ""
    sched = format_hero_schedule(event_at, venue=venue_line, city=city or "")
    for el in root.iter():
        field = el.attrib.get("data-field")
        if not field:
            continue
        value = _value_for(
            field,
            holder_name,
            code,
            display_number,
            date_tagline=sched.tagline,
            time_hm=sched.time_hm,
            venue=venue_line,
            city=city or "",
        )
        el.text = value
        if field == "name":
            el.set("opacity", "0.24")
            el.set("fill", "#1a1520")
        _apply_field_direction(el, field, value, sched.locale)
        if field == "city_line":
            _apply_city_line_direction(el, value)
        for child in list(el):
            if child.tag.endswith("tspan"):
                el.remove(child)
    return normalize_ticket_svg_xml(
        ET.tostring(root, encoding="unicode", xml_declaration=True)
    )


def render_ticket_png(svg_text: str, scale: float = 4.0) -> bytes:
    try:
        import cairosvg
    except ImportError as e:
        raise RuntimeError("cairosvg not installed") from e
    vb = re.search(r'viewBox="([^"]+)"', svg_text)
    w, h = 362.0, 128.0
    if vb:
        parts = vb.group(1).split()
        if len(parts) >= 4:
            w, h = float(parts[2]), float(parts[3])
    with _cairo_fontconfig_scope():
        return cairosvg.svg2png(
            bytestring=svg_text.encode("utf-8"),
            output_width=int(w * scale),
            output_height=int(h * scale),
        )


def _svg_viewbox_size(svg_text: str) -> tuple[float, float]:
    vb = re.search(r'viewBox="([^"]+)"', svg_text)
    w, h = 362.0, 128.0
    if vb:
        parts = vb.group(1).split()
        if len(parts) >= 4:
            w, h = float(parts[2]), float(parts[3])
    return w, h


def render_ticket_pdf_from_png(png_bytes: bytes, width: float, height: float) -> bytes:
    from fpdf import FPDF

    w_pt = max(width * 2, 72.0)
    h_pt = max(height * 2, 72.0)
    pdf = FPDF(unit="pt", format=(w_pt, h_pt))
    pdf.set_margin(0)
    pdf.add_page()
    pdf.image(BytesIO(png_bytes), x=0, y=0, w=w_pt, h=h_pt)
    out = pdf.output()
    return out if isinstance(out, bytes) else out.encode("latin-1")


def ticket_template_field_names(group: str) -> set[str]:
    path = _template_path(group)
    if not path.is_file():
        return set()
    raw = path.read_text(encoding="utf-8")
    return set(re.findall(r'data-field="([^"]+)"', raw))


def render_ticket_bytes(
    group: str,
    holder_name: str,
    public_code: str,
    display_number: int,
    prefer_png: bool = True,
    *,
    event_at: datetime | None = None,
    venue: str = "",
    city: str = "",
    output_format: str = "png",
) -> tuple[bytes, str, str]:
    """Returns (body, media_type, filename_ext). output_format: png | pdf | svg."""
    svg = fill_ticket_svg(
        group,
        holder_name,
        public_code,
        display_number,
        event_at=event_at,
        venue=venue,
        city=city,
    )
    fmt = (output_format or "png").lower().strip()
    if fmt in ("png", "pdf") and prefer_png:
        try:
            ensure_vazirmatn_font()
            png = render_ticket_png(svg)
            if fmt == "pdf":
                w, h = _svg_viewbox_size(svg)
                return render_ticket_pdf_from_png(png, w, h), "application/pdf", "pdf"
            return png, "image/png", "png"
        except Exception as exc:
            logger.warning("ticket PNG export failed, falling back to SVG: %s", exc)
    return svg.encode("utf-8"), "image/svg+xml", "svg"
