"""Topología para la minuta (port de `mapSVGPrint()` del simulador): todo el ancho del A4 y siempre el 50 % de su alto.

Se dibuja en 1000 × 708 unidades (la proporción de 180 mm × 127,5 mm) y se entrega como PNG a 3× para que se lea
nítida en el PDF. Equipos por filas (hasta 7 por fila), líneas en escalera, leyenda dentro del mismo espacio.
"""
import io
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from app.chat.sim.map import CANVAS_W, map_height
from app.chat.sim.util import Obj

W, H, LEG, TOP = 1000, 708, 46, 10
SCALE = 3
FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"

DT_COLOR = {"internet": "#37474F", "router": "#1565C0", "tplink": "#1565C0", "switch": "#00838F", "switch_managed": "#00838F", "ap": "#6A1B9A",
            "repeater": "#6A1B9A", "mesh": "#6A1B9A", "server": "#37474F", "pc": "#2E7D32", "laptop": "#2E7D32", "raspberry": "#AD1457",
            "printer": "#E65100", "camera": "#00838F", "tablet": "#2E7D32", "otro": "#546E7A"}
LSTYLE = {"main": (5, None), "cable": (3, None), "camera": (2, (4, 3)), "wifi": (3, (9, 4)), "usb": (3, None)}
# tipos del documento editable (contrato de la app) -> tipos del simulador
TYPE_IN = {"access_point": "ap", "computer": "pc", "pos": "tablet", "other": "otro"}
STYLE_IN = {"solid": "cable", "dashed": "wifi", "dotted": "usb"}


def _font(size: float, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSansCondensed-Bold.ttf" if bold else "DejaVuSansCondensed.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), max(6, int(round(size * SCALE))))


def _rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def from_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Mapa editado en la app (posiciones 0..1) -> la forma interna del simulador."""
    nodes: List[Obj] = []
    ch = doc.get("canvasH") or 420
    for n in doc.get("nodes", []):
        t = TYPE_IN.get(n.get("type"), n.get("type") or "otro")
        if t not in DT_COLOR:
            t = "otro"
        status = n.get("status") or ("pending" if n.get("pending") else "ok")
        nodes.append(Obj(id=n["id"], type=t, label=n.get("label") or "", sub=n.get("detail") or n.get("sub"), ubic=n.get("location") or n.get("ubic"),
                         ip=n.get("ip"), tier=n.get("tier"), status=status, power=n.get("power"), usb=bool(n.get("usb")), ipBad=bool(n.get("ipBad")),
                         color=n.get("color"), ports=n.get("ports"),
                         x=int(round(float(n.get("x", 0.5)) * CANVAS_W - 48)), y=int(round(float(n.get("y", 0.5)) * ch - 26))))
    links = [Obj(id=l.get("id"), s=l["source"], t=l["target"], style=STYLE_IN.get(l.get("style"), l.get("style") or "cable"),
                 bad=bool(l.get("observed")), color=l.get("color")) for l in doc.get("links", [])]
    return {"nodes": nodes, "links": links, "texts": doc.get("texts", []), "images": doc.get("images", [])}


def line_color(l: Obj, s: Obj, t: Obj) -> str:
    if l.get("color"):
        return l["color"]
    if l.get("bad"):
        return "#D32F2F"
    child, host = (s, t) if l.style == "usb" else (t, s)
    if child.status == "pending" or l.get("status") == "pending":
        return "#9E9E9E"
    if l.style == "usb" and host.status == "pending":
        return "#9E9E9E"
    return "#1565C0"


def _wrap(text: Any, cw: float, f: float) -> List[str]:
    mx = max(8, int((cw - 8) // (f * 0.56)))
    words = str(text or "").split(" ")
    lines = [""]
    for w in words:
        cur = lines[-1]
        if len((cur + " " + w).strip()) > mx and cur:
            lines.append(w)
        else:
            lines[-1] = (cur + " " + w).strip()
    out = lines[:2]
    if len(lines) > 2:
        out[1] = out[1][: mx - 1] + "…"
    return out


class _Canvas:
    def __init__(self) -> None:
        self.img = Image.new("RGB", (W * SCALE, H * SCALE), (247, 249, 252))
        self.d = ImageDraw.Draw(self.img)

    def p(self, v: float) -> int:
        return int(round(v * SCALE))

    def line(self, pts: List[Tuple[float, float]], color: str, width: float, dash: Optional[Tuple[float, float]] = None) -> None:
        pts = [(self.p(x), self.p(y)) for x, y in pts]
        w = max(1, self.p(width))
        if not dash:
            self.d.line(pts, fill=_rgb(color), width=w, joint="curve")
            return
        on, off = self.p(dash[0]), self.p(dash[1])
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            length = math.hypot(x2 - x1, y2 - y1) or 1
            ux, uy = (x2 - x1) / length, (y2 - y1) / length
            pos = 0.0
            while pos < length:
                end = min(length, pos + on)
                self.d.line([(x1 + ux * pos, y1 + uy * pos), (x1 + ux * end, y1 + uy * end)], fill=_rgb(color), width=w)
                pos += on + off

    def circle(self, cx: float, cy: float, r: float, fill: Optional[str], outline: Optional[str] = None, width: float = 1.4,
               dash: bool = False) -> None:
        box = [self.p(cx - r), self.p(cy - r), self.p(cx + r), self.p(cy + r)]
        if dash:
            self.d.ellipse(box, fill=_rgb(fill) if fill else None)
            n = 28
            for i in range(n):
                if i % 2 == 0:
                    a0, a1 = 360 / n * i, 360 / n * (i + 1)
                    self.d.arc(box, a0, a1, fill=_rgb(outline or "#455A64"), width=max(1, self.p(width)))
        else:
            self.d.ellipse(box, fill=_rgb(fill) if fill else None, outline=_rgb(outline) if outline else None, width=self.p(width))

    def poly(self, pts: List[Tuple[float, float]], fill: str, outline: Optional[str] = None) -> None:
        self.d.polygon([(self.p(x), self.p(y)) for x, y in pts], fill=_rgb(fill), outline=_rgb(outline) if outline else None)

    def text(self, x: float, y: float, s: str, size: float, color: str, bold: bool = False, anchor: str = "ms") -> None:
        self.d.text((self.p(x), self.p(y)), s, font=_font(size, bold), fill=_rgb(color), anchor=anchor, stroke_width=self.p(1.5), stroke_fill=(247, 249, 252))

    # ---- íconos (24 × 24, escalados) ----
    def icon(self, kind: str, cx: float, cy: float, size: float, color: str) -> None:
        u = size / 24.0

        def P(x: float, y: float) -> Tuple[float, float]:
            return cx + (x - 12) * u, cy + (y - 12) * u

        w = max(1.0, 1.9 * u)

        def seg(*pts: Tuple[float, float]) -> None:
            self.line([P(*p) for p in pts], color, w)

        def rect(x0: float, y0: float, x1: float, y1: float, fill: bool = False) -> None:
            a, b = P(x0, y0), P(x1, y1)
            self.d.rectangle([self.p(a[0]), self.p(a[1]), self.p(b[0]), self.p(b[1])], outline=_rgb(color), fill=_rgb(color) if fill else None, width=self.p(w))

        def arc(cx2: float, cy2: float, r: float, a0: int, a1: int) -> None:
            c = P(cx2, cy2)
            rr = r * u
            self.d.arc([self.p(c[0] - rr), self.p(c[1] - rr), self.p(c[0] + rr), self.p(c[1] + rr)], a0, a1, fill=_rgb(color), width=self.p(w))

        def dot(x: float, y: float, r: float = 1.3) -> None:
            c = P(x, y)
            self.circle(c[0], c[1], r * u, color)

        if kind in ("router", "tplink"):
            rect(4, 12, 20, 18)
            seg((8, 15), (12, 15))
            arc(12, 12, 3.5, 215, 325)
            arc(12, 12, 6.5, 220, 320)
        elif kind in ("switch", "switch_managed"):
            rect(3, 8, 21, 16)
            for x in (7, 10, 13, 16):
                dot(x, 12, 0.9)
            if kind == "switch_managed":
                seg((12, 3), (12, 8))
                seg((12, 16), (12, 21))
        elif kind in ("ap", "repeater"):
            dot(12, 17, 1.5)
            arc(12, 17, 5, 225, 315)
            arc(12, 17, 9, 225, 315)
        elif kind == "mesh":
            for x, y in ((12, 5), (5, 18), (19, 18)):
                c = P(x, y)
                self.circle(c[0], c[1], 2 * u, None, color, 1.9 * u)
            seg((12, 7), (6, 16))
            seg((12, 7), (18, 16))
            seg((7, 18), (17, 18))
        elif kind == "server":
            rect(4, 3, 20, 10)
            rect(4, 14, 20, 21)
            seg((8, 6.5), (9, 6.5))
            seg((8, 17.5), (9, 17.5))
        elif kind == "pc":
            rect(3, 4, 21, 16)
            seg((8, 20), (16, 20))
            seg((12, 16), (12, 20))
        elif kind == "laptop":
            rect(5, 5, 19, 15)
            seg((2, 19), (22, 19))
        elif kind == "raspberry":
            rect(6, 6, 18, 18)
            for x in (9, 15):
                seg((x, 2), (x, 6))
                seg((x, 18), (x, 22))
            for y in (9, 15):
                seg((2, y), (6, y))
                seg((18, y), (22, y))
        elif kind == "printer":
            seg((6, 9), (6, 3), (18, 3), (18, 9))
            rect(3, 9, 21, 17)
            rect(7, 14, 17, 21)
        elif kind == "camera":
            seg((3, 7), (16, 11), (14, 16), (2, 12), (3, 7))
            seg((16, 11), (20, 10), (20, 14), (15, 15))
            seg((6, 13), (6, 18), (3, 18))
        elif kind == "tablet":
            rect(6, 2, 18, 22)
            seg((11, 18), (13, 18))
        elif kind == "internet":
            rect(10, 3, 14, 7)
            rect(4, 16, 8, 20)
            rect(16, 16, 20, 20)
            seg((12, 7), (12, 12))
            seg((6, 16), (6, 12), (18, 12), (18, 16))
        else:  # otro
            c = P(12, 12)
            self.circle(c[0], c[1], 9 * u, None, color, 1.9 * u)
            self.text(c[0], c[1] + 4 * u, "?", 13 * u, color, True, "ms")

    def bolt(self, x: float, y: float, size: float, color: str) -> None:
        u = size / 24.0
        pts = [(13, 2), (4, 14), (11, 14), (10, 22), (19, 10), (12, 10)]
        self.poly([(x + (px - 0) * u, y + py * u) for px, py in pts], color, "#FFFFFF")


def render_print_png(m: Dict[str, Any], doc: Optional[Dict[str, Any]] = None, images: Optional[Dict[str, bytes]] = None) -> bytes:
    if doc and doc.get("nodes"):
        m = from_document(doc)
    nodes: List[Obj] = sorted(m["nodes"], key=lambda n: (n.y, n.x))
    if not nodes:
        return b""
    avail = H - LEG - TOP
    rows: List[Dict[str, Any]] = []
    by_t: Dict[int, List[Obj]] = {}
    for n in nodes:
        if n.tier is not None:
            by_t.setdefault(n.tier, []).append(n)
    for t in sorted(by_t):
        lst = by_t[t]
        for i in range(0, len(lst), 7):
            rows.append({"y0": lst[i].y, "list": lst[i:i + 7]})
    for n in [n for n in nodes if n.tier is None]:
        r = next((r for r in rows if abs(r["y0"] - n.y) <= 40 and len(r["list"]) < 7), None)
        if r:
            r["list"].append(n)
        else:
            rows.append({"y0": n.y, "list": [n]})
    rows.sort(key=lambda r: r["y0"])
    row_h = avail / max(1, len(rows))
    s = min(1.0, row_h / 118)
    R_, F1, F2, LH = 17 * s, 13 * s, 11 * s, 13 * s
    P: Dict[str, Dict[str, Any]] = {}
    for ri, r in enumerate(rows):
        top = TOP + ri * row_h
        cw = W / len(r["list"])
        r["top"] = top
        for j, n in enumerate(r["list"]):
            P[n.id] = {"x": (j + 0.5) * cw, "y": top + R_ + 2, "row": ri, "cw": cw, "n": n}

    def bot_of(p: Dict[str, Any]) -> float:
        n = p["n"]
        ip = n.type not in ("internet", "camera", "tablet")
        k = len([x for x in (n.sub, n.ubic, 1 if ip else None) if x])
        return p["y"] + R_ + F1 + 1 + (len(_wrap(n.label, p["cw"], F1)) - 1) * LH + k * LH * 0.92 - F2 + 4 * s

    c = _Canvas()
    lane = {"l": 6.0, "r": W - 6.0}
    for l in m["links"]:
        a, b = P.get(l.s), P.get(l.t)
        if not a or not b:
            continue
        width0, dash = LSTYLE.get(l.style, LSTYLE["cable"])
        col = line_color(l, a["n"], b["n"])
        w = max(1.2, width0 * 0.55 * s + 0.4)
        dsh = tuple(x * 0.8 for x in dash) if dash else None
        if l.style == "usb":
            dx, dy = b["x"] - a["x"], b["y"] - a["y"]
            ln = math.hypot(dx, dy) or 1
            ux, uy = dx / ln, dy / ln
            x1, y1 = a["x"] + ux * (R_ + 2), a["y"] + uy * (R_ + 2)
            tx, ty = b["x"] - ux * (R_ + 2), b["y"] - uy * (R_ + 2)
            hx, hy = tx - ux * 9 * s, ty - uy * 9 * s
            c.line([(x1, y1), (hx, hy)], col, w)
            c.poly([(tx, ty), (hx - uy * 5 * s, hy + ux * 5 * s), (hx + uy * 5 * s, hy - ux * 5 * s)], col)
            continue
        if a["row"] == b["row"]:
            sg = 1 if b["x"] > a["x"] else -1
            pts = [(a["x"] + sg * R_, a["y"]), (b["x"] - sg * R_, a["y"])]
        else:
            up, dn = (a, b) if a["row"] < b["row"] else (b, a)
            gy = rows[dn["row"]]["top"] - 4 * s
            if dn["row"] - up["row"] > 1:
                below = rows[up["row"]]["top"] + row_h - 4 * s
                if dn["x"] < W / 2:
                    lane["l"] += 6
                    lx = lane["l"]
                else:
                    lane["r"] -= 6
                    lx = lane["r"]
                pts = [(up["x"], bot_of(up)), (up["x"], below), (lx, below), (lx, gy), (dn["x"], gy), (dn["x"], dn["y"] - R_)]
            else:
                pts = [(up["x"], bot_of(up)), (up["x"], gy), (dn["x"], gy), (dn["x"], dn["y"] - R_)]
        c.line(pts, col, w, dsh)
    for p in P.values():
        n, x, y, cw = p["n"], p["x"], p["y"], p["cw"]
        pend = n.status == "pending"
        col = "#D32F2F" if n.status == "broken" else (n.get("color") or DT_COLOR.get(n.type, "#546E7A"))
        if pend:
            c.circle(x, y, R_, "#FFFFFF", "#455A64", 1.4, dash=True)
        else:
            c.circle(x, y, R_, col)
        c.icon(n.type, x, y, R_ * 1.1 * 1.35, "#455A64" if pend else "#FFFFFF")
        if n.power:
            c.bolt(x + R_ * 0.4, y - R_ * 1.45, R_ * 1.08, "#1565C0" if n.power == "ok" else "#D32F2F")
        L1 = _wrap(n.label, cw, F1)
        show_ip = n.type not in ("internet", "camera", "tablet")
        L2 = [t for t in (n.sub, f"Ubic.: {n.ubic}" if n.ubic else None, ("IP: " + ("no aplica (USB)" if n.usb else (n.ip or "sin dato"))) if show_ip else None) if t]
        ty = y + R_ + F1 + 1
        for line in L1:
            c.text(x, ty, line, F1, "#B42318" if n.status == "broken" else "#1F2937", True)
            ty += LH
        for line in L2:
            c.text(x, ty, _wrap(line, cw, F2)[0], F2, "#B42318" if (line.startswith("IP") and n.ipBad) else "#4B5563")
            ty += LH * 0.92
    # leyenda dentro del mismo 50 %
    c.line([(0, H - LEG), (W, H - LEG)], "#E5E7EB", 0.5)
    lx, ly = 10.0, H - LEG + 16.0

    def item(draw, text: str) -> None:
        nonlocal lx, ly
        wd = len(text) * 6.2 + 40
        if lx + wd > W:
            lx, ly = 10.0, ly + 18
        draw(lx, ly)
        c.text(lx + 30, ly + 3.5, text, 10.5, "#4B5563", False, "ls")
        lx += wd

    item(lambda x, y: c.line([(x, y), (x + 24, y)], "#1565C0", 2.4), "Azul: conexión existente o con buena conexión de red")
    item(lambda x, y: c.line([(x, y), (x + 24, y)], "#9E9E9E", 2.4), "Plomo: por implementar")
    item(lambda x, y: c.line([(x, y), (x + 24, y)], "#D32F2F", 2.4), "Rojo: con falla / observado")
    item(lambda x, y: c.line([(x, y), (x + 24, y)], "#1565C0", 1.8, (7, 3)), "WiFi")
    item(lambda x, y: c.line([(x, y), (x + 24, y)], "#1565C0", 1.4, (3, 2.4)), "Cámara")
    item(lambda x, y: (c.line([(x, y), (x + 17, y)], "#1565C0", 1.8), c.poly([(x + 24, y), (x + 16, y - 4), (x + 16, y + 4)], "#1565C0")), "USB solo a PC o laptop")
    item(lambda x, y: c.circle(x + 12, y, 6, "#FFFFFF", "#455A64", 1, dash=True), "Equipo por implementar")
    item(lambda x, y: c.bolt(x + 7, y - 7, 13, "#1565C0"), "Hay toma de energía")
    item(lambda x, y: c.bolt(x + 7, y - 7, 13, "#D32F2F"), "Falta toma de energía")
    buf = io.BytesIO()
    c.img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
