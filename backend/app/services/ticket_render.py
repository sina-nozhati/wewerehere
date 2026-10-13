"""Server-side ticket art: fill SVG templates (ticket-a/b) and export PNG/SVG."""

from __future__ import annotations

import base64
import logging
import os
import re
import sys
from contextlib import contextmanager
from io import BytesIO
import xml.etree.ElementTree as ET
from pathlib import Path

from datetime import datetime

from app.config import ROOT
from app.services.jalali_schedule import format_hero_schedule, ticket_city_line, ticket_locale
from app.services.ticket_layout import apply_field_layout
from app.services.ticket_png_headless import (
    headless_chromium_available,
    render_svg_png_headless,
)

_ARABIC_CHARS = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")

_WINDOWS_GTK_BIN_DIRS = (
    Path(os.environ.get("GTK_BIN", "")),
    Path(r"C:\Program Files\GTK3-Runtime Win64\bin"),
    Path(r"C:\GTK3-Runtime Win64\bin"),
)

SVG_NS = "http://www.w3.org/2000/svg"
XML_NS = "http://www.w3.org/XML/1998/namespace"
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


class TicketRenderError(RuntimeError):
    """Server-side PNG ticket export failed."""


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


def _prepare_windows_cairo_dll() -> None:
    """Allow cairocffi to load libcairo on Windows when GTK3 runtime is installed."""
    if sys.platform != "win32":
        return
    for bin_dir in _WINDOWS_GTK_BIN_DIRS:
        if not bin_dir.is_dir():
            continue
        bin_str = str(bin_dir.resolve())
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(bin_str)
            except OSError:
                pass
        path_env = os.environ.get("PATH", "")
        if bin_str.lower() not in path_env.lower():
            os.environ["PATH"] = bin_str + os.pathsep + path_env
        break


def _shape_fa_text(text: str) -> str:
    """Presentation forms + bidi for renderers without HarfBuzz (e.g. PyMuPDF)."""
    if not text or not _ARABIC_CHARS.search(text):
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
    except ImportError:
        return text
    return get_display(arabic_reshaper.reshape(text))


def _visible_field_text(field: str, value: str, locale: str) -> str:
    if field in ("name", "name_stub"):
        return _shape_fa_text(value)
    if field == "date" and locale == "fa":
        return _shape_fa_text(value)
    if field == "venue" and ticket_locale(value, "") != "en":
        return _shape_fa_text(value)
    if field == "city_line":
        return _shape_fa_text(value)
    return value


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


_M_PATH_START = re.compile(r"^m\s*([-\d.]+)\s*,\s*([-\d.]+)", re.I)


def _path_start_xy(d: str) -> tuple[float, float] | None:
    m = _M_PATH_START.match((d or "").strip())
    if not m:
        return None
    try:
        return float(m.group(1)), float(m.group(2))
    except ValueError:
        return None


def _strip_baked_sample_lettering(root: ET.Element) -> None:
    """Remove vector-outlined sample date/venue (سوم شهریور، مول پلاس، …) baked into ticket-b."""
    kill: list[tuple[ET.Element, ET.Element]] = []
    for parent in root.iter():
        for child in list(parent):
            if not child.tag.endswith("path"):
                continue
            cls = child.attrib.get("class", "")
            if "cls-8" not in cls:
                continue
            pt = _path_start_xy(child.attrib.get("d", ""))
            if pt is None:
                continue
            x, y = pt
            if x >= 125 and 58 <= y <= 95:
                kill.append((parent, child))
    for parent, child in kill:
        parent.remove(child)

    for parent in root.iter():
        for child in list(parent):
            cls = child.attrib.get("class", "")
            if "wwh-ticket-static-meta-values" in cls:
                parent.remove(child)

    for g in list(root.iter()):
        if g.attrib.get("id") == "wwh-ticket-dynamic-meta":
            gp = next((p for p in root.iter() if g in list(p)), None)
            if gp is not None:
                gp.remove(g)


def _inject_ticket_base_fill(root: ET.Element) -> None:
    """Flat ticket paper behind artwork (PyMuPDF skips many complex paths)."""
    for el in root.iter():
        if el.tag.endswith("rect") and el.attrib.get("data-wwh-ticket-base") == "1":
            return
    vb = root.attrib.get("viewBox", "0 0 362 128").split()
    w, h = 362.0, 128.0
    if len(vb) >= 4:
        w, h = float(vb[2]), float(vb[3])
    rect = ET.Element(f"{{{SVG_NS}}}rect")
    rect.set("data-wwh-ticket-base", "1")
    rect.set("x", "0")
    rect.set("y", "0")
    rect.set("width", str(w))
    rect.set("height", str(h))
    rect.set("fill", "#e3e3e3")
    root.insert(0, rect)


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
        el.set(f"{{{XML_NS}}}lang", "fa")
        el.set("unicode-bidi", "embed")
        return
    if field == "time":
        el.set("direction", "ltr")
        el.set("unicode-bidi", "embed")
        return
    if field == "date":
        if locale == "fa":
            el.set("direction", "rtl")
            el.set(f"{{{XML_NS}}}lang", "fa")
            el.set("unicode-bidi", "embed")
        else:
            el.set("direction", "ltr")
        return
    if field == "venue":
        if ticket_locale(value, "") == "en":
            el.set("direction", "ltr")
        else:
            el.set("direction", "rtl")
            el.set(f"{{{XML_NS}}}lang", "fa")
            el.set("unicode-bidi", "embed")


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
    _strip_baked_sample_lettering(root)
    _inject_ticket_base_fill(root)
    _inject_persian_font(root)
    apply_field_layout(root, path.name)
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


def _pymupdf_png_available() -> bool:
    try:
        import fitz  # noqa: F401
    except ImportError:
        return False
    return True


def ticket_png_export_available() -> bool:
    if _cairo_png_available():
        return True
    if headless_chromium_available():
        return True
    return _pymupdf_png_available()


def ticket_png_diagnostics() -> dict[str, object]:
    """Which PNG pipeline auto mode will prefer (for /api/health and local debugging)."""
    from app.services.ticket_png_headless import headless_chromium_path

    forced = _ticket_png_backend()
    cairo = _cairo_png_available()
    chromium = headless_chromium_available()
    pymupdf = _pymupdf_png_available()
    if forced == "cairo":
        preferred = "cairo" if cairo else "unavailable"
    elif forced == "chromium":
        preferred = "chromium" if chromium else "unavailable"
    elif forced == "pymupdf":
        preferred = "pymupdf" if pymupdf else "unavailable"
    elif cairo:
        preferred = "cairo"
    elif chromium:
        preferred = "chromium"
    elif pymupdf:
        preferred = "pymupdf"
    else:
        preferred = "none"
    chrome_path = headless_chromium_path()
    return {
        "backendEnv": forced,
        "preferred": preferred,
        "cairo": cairo,
        "chromium": chromium,
        "chromiumPath": str(chrome_path) if chrome_path else None,
        "pymupdf": pymupdf,
    }


def _cairo_png_available() -> bool:
    _prepare_windows_cairo_dll()
    try:
        import cairocffi  # noqa: F401
    except OSError:
        return False
    return True


def _ticket_png_backend() -> str:
    forced = (os.environ.get("WW_TICKET_PNG_BACKEND") or "auto").strip().lower()
    if forced in ("cairo", "chromium", "browser", "pymupdf"):
        return "chromium" if forced == "browser" else forced
    return "auto"


def _render_ticket_png_cairo(svg_text: str, scale: float, out_w: int, out_h: int) -> bytes:
    import cairosvg

    ensure_vazirmatn_font()
    # CairoSVG lacks HarfBuzz joining; visual-order presentation forms are required.
    shaped = _svg_for_non_harfbuzz_rasterizer(svg_text)
    with _cairo_fontconfig_scope():
        return cairosvg.svg2png(
            bytestring=shaped.encode("utf-8"),
            output_width=out_w,
            output_height=out_h,
        )


def _render_ticket_png_pymupdf(svg_text: str, scale: float) -> bytes:
    import fitz

    doc = fitz.open(stream=svg_text.encode("utf-8"), filetype="svg")
    if doc.page_count < 1:
        raise TicketRenderError("empty SVG document")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return pix.tobytes("png")


def _pymupdf_failure_message(exc: Exception) -> str:
    if isinstance(exc, ImportError):
        return (
            "PNG export unavailable: pip install -r backend/requirements.txt "
            "(package pymupdf provides the fitz module)"
        )
    return f"PNG export failed: {exc}"


def _cairo_unavailable_message() -> str:
    if sys.platform == "win32":
        return (
            "PNG quality on Windows needs GTK3/Cairo (same as browser preview): install "
            "GTK3-Runtime Win64, add its bin folder to PATH, restart dev — or use PyMuPDF "
            "fallback (WW_TICKET_PNG_BACKEND=pymupdf) with reduced Persian/artwork fidelity"
        )
    return (
        "PNG export unavailable: install libcairo2/libpango (Linux) or pip install pymupdf"
    )


def _try_headless_chromium(svg_text: str, out_w: int, out_h: int) -> bytes | None:
    if not headless_chromium_available():
        return None
    try:
        return render_svg_png_headless(svg_text, out_w, out_h)
    except Exception as exc:
        logger.warning("Headless browser PNG failed: %s", exc)
        return None


def render_ticket_png(svg_text: str, scale: float = 4.0) -> bytes:
    w, h = _svg_viewbox_size(svg_text)
    out_w, out_h = int(w * scale), int(h * scale)
    backend = _ticket_png_backend()
    cairo_error: Exception | None = None
    pymupdf_error: Exception | None = None

    use_cairo = backend in ("auto", "cairo")
    use_chromium = backend in ("auto", "chromium")
    use_pymupdf = backend in ("auto", "pymupdf")

    if use_cairo and _cairo_png_available():
        try:
            return _render_ticket_png_cairo(svg_text, scale, out_w, out_h)
        except TicketFontError as exc:
            cairo_error = exc
            logger.warning("Cairo font setup failed, trying headless browser: %s", exc)
        except Exception as exc:
            cairo_error = exc
            logger.warning("Cairo PNG export failed, trying headless browser: %s", exc)
    elif backend == "cairo":
        raise TicketRenderError(_cairo_unavailable_message())

    if use_chromium:
        png = _try_headless_chromium(svg_text, out_w, out_h)
        if png is not None:
            logger.info("ticket PNG via headless Chromium (%sx%s)", out_w, out_h)
            return png
        if backend == "chromium":
            raise TicketRenderError(
                "PNG export via browser failed; set WW_CHROMIUM_PATH to chrome.exe or msedge.exe"
            )

    if use_pymupdf and _pymupdf_png_available():
        try:
            shaped = _svg_for_non_harfbuzz_rasterizer(svg_text)
            return _render_ticket_png_pymupdf(shaped, scale)
        except Exception as exc:
            pymupdf_error = exc
            if backend == "pymupdf":
                raise TicketRenderError(_pymupdf_failure_message(exc)) from exc
            logger.warning("PyMuPDF PNG export failed: %s", exc)

    if cairo_error is not None:
        raise TicketRenderError(str(cairo_error)) from cairo_error
    if pymupdf_error is not None:
        raise TicketRenderError(_pymupdf_failure_message(pymupdf_error)) from pymupdf_error
    raise TicketRenderError(_cairo_unavailable_message())


def _svg_for_non_harfbuzz_rasterizer(svg_text: str) -> str:
    """Presentation forms + visual order for CairoSVG / PyMuPDF (no HarfBuzz).

    After get_display(), glyphs are already in left-to-right visual order, so
    direction must be ltr and text-anchor flipped vs the logical-RTL layout.
    Chromium must keep the original logical SVG — do not use this helper there.
    """
    root = ET.fromstring(svg_text)
    for el in root.iter():
        field = el.attrib.get("data-field")
        if not field or not (el.text or "").strip():
            continue
        original = el.text or ""
        if not _ARABIC_CHARS.search(original):
            continue
        locale = "fa"
        if field == "date" and not _ARABIC_CHARS.search(original):
            locale = "en"
        shaped = _visible_field_text(field, original, locale)
        if shaped == original:
            continue
        was_rtl = (el.attrib.get("direction") or "").lower() == "rtl"
        anchor = (el.attrib.get("text-anchor") or "start").lower()
        el.text = shaped
        el.set("direction", "ltr")
        el.set("unicode-bidi", "isolate")
        el.attrib.pop(f"{{{XML_NS}}}lang", None)
        if was_rtl:
            if anchor == "start":
                el.set("text-anchor", "end")
            elif anchor == "end":
                el.set("text-anchor", "start")
    return normalize_ticket_svg_xml(ET.tostring(root, encoding="unicode", xml_declaration=True))


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
    allow_svg_export: bool = False,
) -> tuple[bytes, str, str]:
    """Returns (body, media_type, filename_ext). User-facing exports must be PNG (or PDF)."""
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
    if fmt == "svg":
        if not allow_svg_export:
            raise TicketRenderError("SVG export is disabled for user-facing tickets")
        return svg.encode("utf-8"), "image/svg+xml", "svg"
    if fmt not in ("png", "pdf"):
        raise TicketRenderError(f"unsupported ticket format: {fmt}")
    if not prefer_png:
        raise TicketRenderError("PNG export required")
    try:
        png = render_ticket_png(svg)
    except TicketRenderError:
        raise
    except Exception as exc:
        logger.exception("ticket PNG export failed")
        raise TicketRenderError(str(exc)) from exc
    if fmt == "pdf":
        w, h = _svg_viewbox_size(svg)
        return render_ticket_pdf_from_png(png, w, h), "application/pdf", "pdf"
    return png, "image/png", "png"
