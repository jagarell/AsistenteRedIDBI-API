"""Dibuja el mapa de red de la minuta (PNG) a partir del mapa editable.

Cable = línea continua, WiFi = guiones, USB = puntos, observado = rojo
discontinuo; equipos por adquirir con borde punteado. Incluye cajas de texto
y fotos de evidencia colocadas por el técnico en el editor.
"""
import io
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from app.chat.map_model import MapDocument, from_topology
from app.chat.schemas import Topology

_COLORS = {
    "internet": (55, 71, 79), "router": (21, 101, 192), "switch": (46, 125, 50),
    "computer": (0, 131, 143), "printer": (85, 85, 85), "access_point": (106, 27, 154),
    "repeater": (106, 27, 154), "camera": (198, 40, 40), "pos": (239, 108, 0), "other": (96, 125, 139),
}
_MARK = {"internet": "I", "router": "R", "switch": "S", "access_point": "A", "repeater": "W", "computer": "C",
         "printer": "P", "camera": "V", "pos": "$", "other": "·"}
_IMG_W = {"S": 130, "M": 190, "L": 270}
_FONT_PX = {"S": 14, "M": 17, "L": 22}
_LINK_GRAY = (120, 144, 156)
_RED = (198, 40, 40)
_NODE_R = 30
_W = 1100
_H = 760


_FONT_DIR = Path(__file__).parent / "fonts"


def _font(size: int, bold: bool = False):
    # La fuente por defecto de Pillow no trae tildes ni ñ: se incluye DejaVu.
    name = "DejaVuSansCondensed-Bold.ttf" if bold else "DejaVuSansCondensed.ttf"
    return ImageFont.truetype(str(_FONT_DIR / name), size)


def _clip(text: str, limit: int = 34) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _dashed(draw: ImageDraw.ImageDraw, p1: Tuple[float, float], p2: Tuple[float, float],
            color, width: int, dash: int, gap: int) -> None:
    x1, y1 = p1
    x2, y2 = p2
    length = max(1.0, ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5)
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    pos = 0.0
    while pos < length:
        end = min(length, pos + dash)
        draw.line([(x1 + ux * pos, y1 + uy * pos), (x1 + ux * end, y1 + uy * end)], fill=color, width=width)
        pos += dash + gap


def _hex(color: str, fallback=(255, 244, 204)):
    try:
        c = color.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:  # noqa: BLE001
        return fallback


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> List[str]:
    lines: List[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            cand = f"{cur} {word}".strip()
            if draw.textlength(cand, font=font) > max_w and cur:
                lines.append(cur)
                cur = word
            else:
                cur = cand
        lines.append(cur)
    return lines


def render_map_png(doc: MapDocument, images: Optional[Dict[str, bytes]] = None) -> bytes:
    if not doc.nodes and not doc.texts and not doc.images:
        return b""
    images = images or {}
    margin_x, margin_y = 110, 70
    img = Image.new("RGB", (_W, _H), "white")
    d = ImageDraw.Draw(img)
    f_label, f_small, f_legend = _font(18, True), _font(14), _font(15)

    def xy(x: float, y: float) -> Tuple[float, float]:
        return margin_x + x * (_W - 2 * margin_x), margin_y + y * (_H - 2 * margin_y - 40)

    pos = {n.id: xy(n.x, n.y) for n in doc.nodes}

    for l in doc.links:
        if l.source not in pos or l.target not in pos:
            continue
        a, b = pos[l.source], pos[l.target]
        color = _RED if l.observed else _LINK_GRAY
        if l.observed or l.style == "dashed":
            _dashed(d, a, b, color, 3, 12, 8)
        elif l.style == "dotted":
            _dashed(d, a, b, color, 3, 3, 8)
        else:
            d.line([a, b], fill=color, width=3)
        if l.observed:
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            d.text((mx - 170, my - 8), "WiFi: debería ir por cable", font=f_small, fill=_RED,
                   stroke_width=3, stroke_fill="white")

    for n in doc.nodes:
        cx, cy = pos[n.id]
        color = _hex(n.color, _COLORS.get(n.type, _COLORS["other"])) if n.color else _COLORS.get(n.type, _COLORS["other"])
        box = [cx - _NODE_R, cy - _NODE_R, cx + _NODE_R, cy + _NODE_R]
        if n.pending:
            d.ellipse(box, fill="white", outline=color, width=4)
        else:
            d.ellipse(box, fill=color)
        d.text((cx, cy), _MARK.get(n.type, "·"), font=f_label, fill=color if n.pending else "white", anchor="mm")
        d.text((cx, cy + _NODE_R + 6), _clip(n.label, 42), font=f_label, fill=(33, 33, 33), anchor="ma",
               stroke_width=3, stroke_fill="white")
        if n.detail:
            d.text((cx, cy + _NODE_R + 30), _clip(n.detail, 46), font=f_small, fill=(120, 120, 120), anchor="ma",
                   stroke_width=3, stroke_fill="white")

    for im in doc.images:
        raw = images.get(im.id)
        if not raw:
            continue
        try:
            photo = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception:  # noqa: BLE001
            continue
        w = _IMG_W.get(im.size, 190)
        h = int(photo.height * w / photo.width)
        photo = photo.resize((w, h))
        cx, cy = xy(im.x, im.y)
        left, top = int(cx - w / 2), int(cy - h / 2)
        img.paste(photo, (left, top))
        d.rectangle([left, top, left + w, top + h], outline=(46, 125, 50), width=3)
        if im.label:
            d.text((cx, top + h + 4), _clip(im.label, 30), font=f_small, fill=(33, 33, 33), anchor="ma",
                   stroke_width=3, stroke_fill="white")

    for tx in doc.texts:
        font = _font(_FONT_PX.get(tx.size, 17), True)
        lines = _wrap(d, tx.text, font, 220)
        w = int(max(d.textlength(line, font=font) for line in lines)) + 20
        h = len(lines) * (font.size + 4) + 14
        cx, cy = xy(tx.x, tx.y)
        left, top = int(cx - w / 2), int(cy - h / 2)
        d.rounded_rectangle([left, top, left + w, top + h], radius=8, fill=_hex(tx.color), outline=(176, 130, 40), width=2)
        for i, line in enumerate(lines):
            d.text((left + 10, top + 7 + i * (font.size + 4)), line, font=font, fill=(90, 60, 10))

    ly, lx = _H - 36, 60
    for text, kind in (("Cable", "cable"), ("WiFi", "wifi"), ("USB", "usb"), ("Observado", "obs")):
        seg = [(lx, ly), (lx + 50, ly)]
        if kind == "cable":
            d.line(seg, fill=_LINK_GRAY, width=3)
        elif kind == "wifi":
            _dashed(d, seg[0], seg[1], _LINK_GRAY, 3, 12, 8)
        elif kind == "usb":
            _dashed(d, seg[0], seg[1], _LINK_GRAY, 3, 3, 8)
        else:
            _dashed(d, seg[0], seg[1], _RED, 3, 12, 8)
        d.text((lx + 60, ly), text, font=f_legend, fill=(70, 70, 70), anchor="lm")
        lx += 160

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_topology_png(topology: Topology) -> bytes:
    """Mapa automático a partir de la topología del chat."""
    return render_map_png(from_topology(topology))
