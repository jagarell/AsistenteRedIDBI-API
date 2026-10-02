"""Dibuja el mapa de red de la minuta (PNG) a partir de la topología.

Layout de árbol: Internet arriba, hijos debajo, cada padre centrado sobre sus
hijos. Cable = línea continua, WiFi = guiones, USB/Bluetooth = puntos,
observado (con falla) = rojo discontinuo; equipos por adquirir con borde
punteado y los detectados sin documentar en gris.
"""
import io
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from app.chat.schemas import ConnectionType, LinkStatus, Topology

_COLORS = {
    "internet": (55, 71, 79), "router": (21, 101, 192), "switch": (21, 101, 192),
    "computer": (0, 131, 143), "printer": (85, 85, 85), "access_point": (106, 27, 154),
    "camera": (239, 108, 0), "pos": (0, 131, 143), "detected": (189, 189, 189),
}
_LINK_GRAY = (120, 144, 156)
_RED = (198, 40, 40)
_NODE_R = 30
_W = 1100


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


def _layout(topology: Topology) -> Tuple[Dict[str, Tuple[float, float]], int]:
    children: Dict[str, List[str]] = {n.id: [] for n in topology.nodes}
    parent: Dict[str, str] = {}
    for l in topology.links:
        if l.target not in parent and l.source in children and l.target in children:
            parent[l.target] = l.source
            children[l.source].append(l.target)
    roots = [n.id for n in topology.nodes if n.id not in parent]

    x_next = [0.0]
    pos: Dict[str, Tuple[float, int]] = {}

    def place(node_id: str, depth: int) -> float:
        kids = children[node_id]
        if not kids:
            x = x_next[0]
            x_next[0] += 1
        else:
            xs = [place(k, depth + 1) for k in kids]
            x = sum(xs) / len(xs)
        pos[node_id] = (x, depth)
        return x

    for r in roots:
        place(r, 0)
    max_depth = max((d for _, d in pos.values()), default=0)
    cols = max(1.0, x_next[0] - 1)
    return {k: (x / cols if cols else 0.5, d) for k, (x, d) in pos.items()}, max_depth


def render_topology_png(topology: Topology) -> bytes:
    if not topology.nodes:
        return b""
    norm, max_depth = _layout(topology)
    row_h = 190
    height = 70 + row_h * max_depth + 150
    margin = 170
    img = Image.new("RGB", (_W, height), "white")
    d = ImageDraw.Draw(img)
    f_label, f_small, f_legend = _font(18, True), _font(14), _font(15)

    def xy(node_id: str) -> Tuple[float, float]:
        nx, depth = norm[node_id]
        return margin + nx * (_W - 2 * margin), 70 + depth * row_h

    by_id = {n.id: n for n in topology.nodes}
    for l in topology.links:
        if l.source not in norm or l.target not in norm:
            continue
        a, b = xy(l.source), xy(l.target)
        observed = l.status == LinkStatus.CON_FALLA
        color = _RED if observed else _LINK_GRAY
        if observed or l.connectionType == ConnectionType.WIFI:
            _dashed(d, a, b, color, 3, 12, 8)
        elif l.connectionType == ConnectionType.USB_BLUETOOTH:
            _dashed(d, a, b, color, 3, 3, 8)
        else:
            d.line([a, b], fill=color, width=3)
        if observed:
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            d.text((mx - 170, my - 8), "WiFi: debería ir por cable", font=f_small, fill=_RED,
                   stroke_width=3, stroke_fill="white")

    for n in topology.nodes:
        if n.id not in norm:
            continue
        cx, cy = xy(n.id)
        color = _COLORS.get(n.type, _COLORS["computer"])
        box = [cx - _NODE_R, cy - _NODE_R, cx + _NODE_R, cy + _NODE_R]
        if n.pending:
            d.ellipse(box, fill="white", outline=color, width=4)
            _dashed(d, (cx - _NODE_R, cy), (cx + _NODE_R, cy), (255, 255, 255), 4, 6, 6)
        else:
            d.ellipse(box, fill=color)
        d.text((cx, cy), n.type[:1].upper(), font=f_label, fill="white" if not n.pending else color, anchor="mm")
        d.text((cx, cy + _NODE_R + 6), _clip(n.label, 42), font=f_label, fill=(33, 33, 33), anchor="ma",
               stroke_width=3, stroke_fill="white")
        if n.detail:
            d.text((cx, cy + _NODE_R + 30), _clip(n.detail, 46), font=f_small, fill=(120, 120, 120), anchor="ma",
                   stroke_width=3, stroke_fill="white")

    ly = height - 40
    lx = 60
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
    d.ellipse([lx, ly - 8, lx + 16, ly + 8], fill=_COLORS["detected"])
    d.text((lx + 24, ly), "Detectado en el escáner, sin documentar", font=f_legend, fill=(70, 70, 70), anchor="lm")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
