"""Mapa de red automático (port de `buildMap()` y `layout()` del simulador).

Cada equipo lleva su nivel (`tier`: 0 internet, 1 router, 2 switch, 3 equipos, 4 repetidores y cámaras), de dónde
sale la conexión (`style`: main, cable, camera, wifi, usb) y su estado (ok, pending = por implementar, broken = con falla).
"""
import re
from typing import Any, Dict, List, Optional

from app.chat.sim.util import Obj, jsround

CANVAS_W = 370
ROW_H = 128
NODE_W = 96


def build_map(X: Obj) -> Dict[str, Any]:
    nodes: List[Obj] = []
    links: List[Obj] = []

    def N(o: Dict[str, Any]) -> Obj:
        n = Obj(o)
        n["id"] = f"n{len(nodes)}"
        n["status"] = n.get("status") or "ok"
        nodes.append(n)
        return n

    def L(s: Optional[Obj], t: Optional[Obj], style: str, bad: bool = False) -> None:
        if s and t:
            links.append(Obj(id=f"l{len(links) + 1}", s=s["id"], t=t["id"], style=style, bad=bool(bad)))

    def pw(name: str) -> Optional[str]:
        if X.tomas == "NO":
            return "missing" if name in (X.sinEnergia or []) else None
        if X.tomas == "SI" and re.match(r"^(Router|TP-Link)", name):
            return "ok"
        return None

    ru = X.routerUbic or "Caja"
    inet = router = tp = sw = None
    if X.porContratar:
        inet = N({"type": "internet", "label": "Internet", "sub": "Por contratar", "tier": 0, "status": "pending"})
        router = N({"type": "router", "label": "Router", "ubic": ru, "tier": 1, "status": "pending", "power": pw("Router")})
        L(inet, router, "main")
    if X.hasInt:
        inet = N({"type": "internet", "label": "Internet", "sub": X.conL, "tier": 0})
        router = N({"type": "router", "label": "Router", "ubic": ru, "ip": None if X.obra else X.seg + ".1", "tier": 1,
                    "status": "pending" if X.obra else "ok", "power": pw("Router")})
        L(inet, router, "main")
    if X.r56:
        tp = N({"type": "tplink", "label": "TP-Link con chip", "sub": ("Chip " + X.chipProv.split(" (")[0]) if X.chipProv else "Chip por definir",
                "ubic": ru, "tier": 1, "status": "pending", "power": pw("TP-Link con chip")})
    if X.switchN:
        sw = N({"type": "switch", "label": f"Switch x{X.switchN}", "ubic": ru, "tier": 2, "status": "pending",
                "power": pw(f"Switch x{X.switchN}"), "ports": X.switchN})
        L(router, sw, "main")
    lan = sw or router
    ph = tp or lan
    caja_dev: List[Optional[Obj]] = []
    sw_ex0: Optional[Obj] = None
    rep_ex0: Optional[Obj] = None
    for c in X.cajasInfo or []:
        d: Optional[Obj] = None
        if c.eq == "SI":
            d = N({"type": "pc", "label": "PC " + c.nm, "ubic": "Caja", "tier": 3, "power": pw(c.eqName or f"PC de {c.nm}")})
            L(ph, d, "wifi" if c.pcWifi else "cable")
        elif c.eq in ("TABLET", "SUNMI", "IMIN"):
            t = N({"type": "tablet", "label": {"TABLET": "Tablet", "SUNMI": "Sunmi", "IMIN": "iMin"}[c.eq] + " " + c.nm,
                   "ubic": "Caja", "tier": 3, "power": pw(c.eqName)})
            L(ph, t, "wifi")
        if c.rasp or c.adq == "RASPBERRY":
            power = "missing" if c.raspEnergia is False else "ok" if c.raspEnergia else pw(f"Raspberry de {c.nm}")
            r = N({"type": "raspberry", "label": "Raspberry" + (" " + c.nm if X.cajas > 1 else ""), "ubic": ru, "tier": 3,
                   "status": "ok" if c.rasp else "pending", "power": power})
            par = ph
            if c.raspVia == "SWITCH":
                if sw:
                    par = sw
                else:
                    if not sw_ex0:
                        sw_ex0 = N({"type": "switch", "label": "Switch", "sub": "Existente", "ubic": ru, "tier": 2})
                        L(router or tp, sw_ex0, "main")
                    par = sw_ex0
            elif c.raspVia in ("REPETIDOR", "AP"):
                ap = c.raspVia == "AP"
                if not rep_ex0:
                    rep_ex0 = N({"type": "ap" if ap else "repeater", "label": "Access point" if ap else "Repetidor",
                                 "sub": "Existente", "ubic": "Local", "tier": 2})
                    L(router or tp, rep_ex0, "wifi")
                par = rep_ex0
            L(par, r, "wifi" if (c.rasp and c.raspCable is False) else "cable", bool(c.rasp and c.raspPunto is False))
            d = d or r
        elif c.adq:
            l = N({"type": "laptop" if c.adq == "LAPTOP" else "pc", "label": f"{c.adqL} {c.nm}", "ubic": "Caja", "tier": 3, "status": "pending"})
            L(ph, l, "cable")
            d = d or l
        caja_dev.append(d)
    if X.decision == "RASPBERRY" and not any(n.type == "raspberry" for n in nodes):
        r = N({"type": "raspberry", "label": "Raspberry", "ubic": ru, "tier": 3, "status": "pending"})
        L(ph, r, "cable")
    if X.sunmi:
        s_ = N({"type": "tablet", "label": "Sunmi con chip", "ubic": "Caja", "tier": 3, "status": "pending"})
        caja_dev.append(s_)

    def is_pcl(n: Optional[Obj]) -> bool:
        return bool(n) and n.type in ("pc", "laptop")

    if X.decision in ("PC_BASICA", "PC_CONTROLADOR") and not any(is_pcl(n) for n in nodes):
        l = N({"type": "laptop", "label": "Laptop o PC", "ubic": "Caja", "tier": 3, "status": "pending"})
        L(ph, l, "cable")
        caja_dev.append(l)
    usb_host = next((n for n in caja_dev if is_pcl(n)), None) or next((n for n in nodes if is_pcl(n)), None)
    sw_ex, rep_ex = sw_ex0, rep_ex0 if (rep_ex0 and rep_ex0.type == "repeater") else None
    for p in X.printers or []:
        if not p.con:
            continue
        wrong = bool(p.prep) and p.con in ("USB", "WIFI")
        ip_bad = p.con in ("RED", "WIFI") and bool(p.ip) and not p.ip.startswith(X.seg + ".")
        usb_ok = p.con == "USB" and p.usbTo == "PC" and usb_host
        usb_none = p.con == "USB" and (p.usbTo == "NINGUNO" or (p.usbTo == "PC" and not usb_host))
        if p.con == "NONE":
            sub = "Sin conexión"
        elif usb_none:
            sub = "USB sin conectar"
        elif p.con == "USB" and p.usbTo and p.usbTo != "PC":
            sub = f"USB a {(p.usbToL or 'otro equipo').lower()}: no válido"
        else:
            sub = None
        n = N({"type": "printer", "label": "IMP. " + p.name, "ubic": p.name if p.prep else "Caja", "ip": p.ip, "usb": p.con == "USB",
               "ipBad": ip_bad, "sub": sub, "tier": 3,
               "status": "pending" if p.con == "NO" else "broken" if (wrong or p.estado in ("FALLAS", "AVERIADA")) else "ok",
               "power": pw("IMP. " + p.name)})
        par = ph
        if p.via == "SWITCH" and not sw:
            if not sw_ex:
                sw_ex = N({"type": "switch", "label": "Switch", "sub": "Existente", "ubic": ru, "tier": 2})
                L(router or tp, sw_ex, "main")
            par = sw_ex
        elif p.via == "SWITCH" and sw:
            par = sw
        elif p.via == "REPETIDOR":
            if not rep_ex:
                rep_ex = N({"type": "repeater", "label": "Repetidor", "sub": "Existente", "ubic": "Local", "tier": 2})
                L(router or tp, rep_ex, "wifi")
            par = rep_ex
        if p.con == "RED" and p.via == "WIFI":
            L(router or tp, n, "wifi", wrong)
        elif p.con == "RED":
            L(par, n, "cable")
        elif p.con == "NO":
            L(ph, n, "cable")
        elif p.con == "WIFI":
            L(par if p.via == "REPETIDOR" else (router or tp or ph), n, "wifi", wrong)
        elif usb_ok:
            L(n, usb_host, "usb", wrong)
    wr = router or tp
    if X.sinSenal:
        ap = bool(re.search(r"access", X.solWifi or "", re.I))
        for z in X.sinSenal[:3]:
            r = N({"type": "ap" if ap else "repeater", "label": "Access point" if ap else "Repetidor", "ubic": z, "tier": 4, "status": "pending"})
            L(wr, r, "wifi")
    if X.camaras:
        c = N({"type": "camera", "label": f"Cámaras x{X.nCam or 1}", "ubic": "Zonas del local", "tier": 4})
        L(wr, c, "camera")
    # cada impresora USB va justo después del equipo al que se conecta
    for l in [l for l in links if l.style == "usb"]:
        pi = next((i for i, n in enumerate(nodes) if n.id == l.s), -1)
        ci = next((i for i, n in enumerate(nodes) if n.id == l.t), -1)
        if pi < 0 or ci < 0:
            continue
        pn = nodes.pop(pi)
        c2 = next(i for i, n in enumerate(nodes) if n.id == l.t)
        nodes.insert(c2 + 1, pn)
    # rayos de energía: con tomas cerca todos llevan rayo azul; sin tomas, rojo en los marcados (o en todos con "Ninguno")
    if X.tomas == "SI":
        for n in nodes:
            if n.type != "internet" and n.power != "missing":
                n.power = "ok"
    elif X.tomas == "NO":
        for n in nodes:
            if n.type == "internet":
                continue
            if X.ningunaToma:
                n.power = "missing"
            elif not n.power:
                n.power = "ok"
    layout(nodes)
    return {"nodes": nodes, "links": links}


def layout(nodes: List[Obj]) -> None:
    y = 12
    for t in range(5):
        row = [n for n in nodes if n.tier == t]
        for i in range(0, len(row), 4):
            ch = row[i:i + 4]
            for j, n in enumerate(ch):
                n.x = jsround((j + 0.5) * CANVAS_W / len(ch) - 48)
                n.y = y
            y += ROW_H


def map_height(m: Dict[str, Any]) -> int:
    return max([420] + [n.y + 130 for n in m["nodes"]])


# ---- al documento editable que viaja entre la app, el gateway y la minuta ---------------------------------
NODE_TYPE_OUT = {"ap": "access_point", "repeater": "repeater", "pc": "computer", "laptop": "computer", "tablet": "pos",
                 "raspberry": "raspberry", "tplink": "tplink", "switch_managed": "switch_managed", "mesh": "mesh", "server": "server"}


def to_document(m: Dict[str, Any]) -> Dict[str, Any]:
    """Mapa en el formato del editor: posiciones 0..1 y nombres de tipo/estilo del contrato."""
    h = map_height(m)
    nodes = []
    for n in m["nodes"]:
        nodes.append({
            "id": n.id, "label": n.label, "type": n.type, "x": round((n.x + 48) / CANVAS_W, 4), "y": round((n.y + 26) / h, 4),
            "pending": n.status == "pending", "status": n.status, "detail": n.sub, "location": n.ubic, "ip": n.ip,
            "ports": n.get("ports"), "power": n.power, "usb": bool(n.usb), "ipBad": bool(n.ipBad), "tier": n.tier,
        })
    links = [{"id": l.id, "source": l.s, "target": l.t, "style": l.style, "observed": bool(l.bad)} for l in m["links"]]
    return {"nodes": nodes, "links": links, "texts": [], "images": []}
