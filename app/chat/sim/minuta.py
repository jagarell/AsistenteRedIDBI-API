"""Documento de la minuta técnica (port de `minutaSections`, `mRules`, `annexHTML` y `pdfBody` del simulador).

Devuelve una lista de bloques sencillos (títulos, tablas, listas, anexos) que el gateway dibuja con su plantilla
HTML → PDF. Nada se inventa: lo que no se capturó queda como "Pendiente".
"""
import base64
import re
from typing import Any, Dict, List, Optional

from app.chat.sim.flow import CAT, build, fmt_date
from app.chat.sim.map import build_map
from app.chat.sim.map_print import render_print_png
from app.chat.sim.reading import CONN_TXT
from app.chat.sim.rules import evaluate, gen_pasos
from app.chat.sim.scoring import lvl, resumen_ia, scores
from app.chat.sim.util import Obj, fmt, jsround, uniq

CONN_L = {"RED": "Red por cable", "WIFI": "WiFi", "USB": "USB", "NONE": "Sin conexión", "NO": "No tiene"}
DT_LABEL = {"internet": "Internet", "router": "Router", "tplink": "TP-Link con chip", "switch": "Switch", "switch_managed": "Switch administrable",
            "ap": "Access point", "repeater": "Repetidor", "mesh": "Mesh", "server": "Servidor", "pc": "PC", "laptop": "Laptop",
            "raspberry": "Raspberry", "printer": "Impresora", "camera": "Cámara de vigilancia", "tablet": "Sunmi / tablet", "otro": "Otro equipo"}
VIABILITY = "Si no se siguen las recomendaciones de esta minuta, no es viable la implementación del punto de venta en el local."


def _del(d: Optional[Dict[str, Any]], k: Any) -> bool:
    dels = (d or {}).get("_del") or []
    return any(x in dels for x in k) if isinstance(k, list) else k in dels


def _rds(d: Optional[Dict[str, Any]], k: Any, t: str) -> str:
    return "" if _del(d, k) else t


def _rdj(items: List[Any], sep: str = " · ") -> str:
    return sep.join(str(x) for x in items if x)


def _row(label: str, value: Any, bad: bool = False, ask: str = "no se capturó") -> Dict[str, Any]:
    v = "" if value is None else str(value).strip()
    return {"label": label, "value": v, "bad": bad} if v else {"label": label, "pending": True, "note": ask}


def _city(addr: Any) -> str:
    p = [x.strip() for x in str(addr or "").split(",") if x.strip()]
    return p[-1] if len(p) > 1 else ""


def _cap(s: str) -> str:
    return s[:1] + s[1:].lower() if s else ""


def _table(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"t": "kv", "rows": rows}


def sections(X: Obj, R: Obj, a: Dict[str, Any], d: Dict[str, Any], validada_por: Optional[str]) -> Dict[str, List[Dict[str, Any]]]:
    pend_ask = "se saltó: se completa al editar la minuta"
    sec1 = [
        _row("Razón social", d.get("razon") or X.razon), _row("RUC", d.get("ruc") or X.ruc),
        _row("Nombre del local", d.get("nombre") or X.nombre), _row("Rubro", X.rubL), _row("Estado del local", X.estadoL),
        _row("Dirección", d.get("dir") or X.dir), _row("Ciudad", _city(d.get("dir") or X.dir), ask="no se pudo derivar de la dirección"),
        _row("Encargado del local", X.encargado), _row("Celular", X.celular, ask=pend_ask),
        _row("Correo", d.get("correo") or X.correo, ask=pend_ask),
        _row("Fecha de evaluación", X.fechaVisita),
        _row("Fecha de inicio", fmt_date(a["P50b"]["v"]) if a.get("P50b") and a["P50b"].get("v") else "", ask="sin fecha acordada"),
        _row("Técnico responsable", X.tecnico),
        _row("Validada por", validada_por or "No verificada: sin validar por el supervisor", bad=not validada_por),
    ]
    zonas_txt = " · ".join(c + ": " + ", ".join(z["z"] for z in X.zonas if z["canal"] == c) for c in X.canales)
    prep_txt = ", ".join(X.prep) or (", ".join(X.prepRef) + " (solo referencia, sin impresora)" if X.prepRef else ("No aplica" if X.simple else ""))
    neg = [_row("Áreas de preparación", prep_txt), _row("Canales y zonas de atención", zonas_txt), _row("Cantidad de cajas", str(X.cajas)),
           _row("Comandas en caja", a["P12b"]["label"] if a.get("P12b") else ("No aplica (retail)" if X.rub == "RETAIL" else ""))]
    sp = R.sp
    na = "No aplica" if (X.sinInt or X.porContratar) else ""
    RT = X.router or {}
    ipc, scn = X.ipconfig, X.scanner
    net: List[Dict[str, Any]] = []
    if not X.simple:
        net += [_row("Tipo de conexión", X.conL), _row("Proveedor", X.proveedor or RT.get("proveedor") or na)]
    net.append(_row("Plan contratado", f"{fmt(X.plan)} Mbps" if X.plan else ("Sin internet" if X.sinInt else "")))
    if X.obra:
        vel: Any = "No aplica (local en obra)"
    elif sp:
        vel = (f"Mejor de 2 pruebas: {fmt(sp.best)} Mbps ({jsround(sp.pct * 100)} % del plan) · subida {fmt(sp.d.get('u'))} Mbps · "
               f"ping {fmt(sp.d.get('p'))} ms ({fmt(sp.d.get('pd'))} y {fmt(sp.d.get('pu'))} ms con carga)")
    else:
        vel = na
    net.append(_row("Velocidad medida por cable", vel, ask="plan sin verificar: falta la prueba por cable junto al router" if R.V01 == "SIN VERIFICAR" else "falta una captura legible del speedtest"))
    if X.porContratar:
        need = "Por contratar antes de implementar"
    elif X.sinInt:
        need = "No aplica (sin internet: TP-Link con chip)"
    elif X.bw:
        need = f"Mínimo por equipo {fmt(X.bw.min)} Mbps · recomendado {fmt(X.bw.rec)} Mbps (~150 Mbps × {X.bw.zonas} zonas de atención)"
    else:
        need = ""
    net.append(_row("Plan necesario", need))
    if X.chip:
        net.append(_row("Señal del chip", X.chipL))
    if a.get("P16"):
        net.append(_row("Línea de respaldo", a["P16"]["label"]))
    if a.get("P17"):
        net.append(_row("Caídas de internet", a["P17"]["label"]))
    if ipc:
        net.append(_row("Red del local (ipconfig)", _rdj([_rds(ipc, "ip", f"IP {ipc.get('ip') or '—'}"), _rds(ipc, "mascara", f"máscara {ipc.get('mascara') or '—'}"),
                                                           _rds(ipc, "gw", f"puerta de enlace {ipc.get('gw') or '—'}")])))
    if scn:
        cam = "" if _del(scn, "cam") else (" · cámaras por DVR (una IP)" if scn.get("cam") == "DVR" else f" · cámaras por NVR ({fmt(scn.get('camIps')) or 'varias'} IP)" if scn.get("cam") == "NVR" else "")
        otros = " · otros: " + scn["otros"] if scn.get("otros") and not _del(scn, "otros") else ""
        head = _rdj([_rds(scn, "equipos", f"{fmt(scn.get('equipos') or 0)} equipos"), _rds(scn, "impresoras", f"impresoras: {scn.get('impresoras') or 'ninguna'}")])
        net.append(_row("Escáner de IP", re.sub(r"^ · ", "", f"{head}{otros}{cam}")))
    if not X.simple:
        net.append(_row("Dónde irá el router" if X.obra else "Ubicación del router", X.routerUbic or na))
    if X.router:
        net.append(_row("Router", f"{' '.join(x for x in [RT.get('marca'), RT.get('modelo')] if x) or 'Sin dato'}{(' · SN ' + RT['sn']) if RT.get('sn') else ''} · IP {RT.get('ip') or '—'}"))
        puertos = RT.get("puertos")
        net.append(_row("Puertos LAN", f"{'—' if puertos is None else fmt(puertos)} en total · {'—' if RT.get('libres') is None else fmt(RT['libres'])} libres · {'—' if RT.get('ocupados') is None else fmt(RT['ocupados'])} ocupados"))
    caj: List[Dict[str, Any]] = []
    for c in X.cajasInfo or []:
        if c.eq == "SI":
            val = f"PC o laptop conectada por {'WiFi' if c.pcWifi else 'cable de red'}{' (no se queda en el local)' if c.temporal else ''}"
        else:
            if c.eq in ("TABLET", "SUNMI", "IMIN"):
                head = c.eqL + (" (la comanda y el comprobante salen en la misma caja). " if c.posPropio else ". ")
            elif c.eq == "OTRO":
                head = f"Equipo indicado: {c.eqL}. "
            elif c.eq == "NO_SE":
                head = "Sin confirmar. "
            else:
                head = "Sin equipo. "
            tail = "Ya tiene Raspberry" if c.rasp else ("Adquirirá " + str(c.adqL).lower() if c.adq else "")
            val = head + tail
        caj.append(_row(f"Equipo de {c.nm}", val, bad=bool(c.pcWifi or (c.eq in ("TABLET", "SUNMI", "IMIN") and not c.posPropio))))
        if c.rasp or c.adq == "RASPBERRY":
            en = "" if c.raspEnergia is None else f" · toma de energía: {'sí' if c.raspEnergia else 'no'}"
            pu = "" if c.raspPunto is None else f" · punto de red: {'sí' if c.raspPunto else 'no'}"
            via = f" · {c.raspViaL.lower()}" if c.raspViaL else ""
            caj.append(_row(f"Raspberry de {c.nm}{'' if c.rasp else ' (por adquirir)'}",
                            f"{'Conectado' if c.rasp else 'Irá conectado'} por {'cable de red' if c.raspCable else 'WiFi'}{via}{en}{pu}",
                            bad=c.raspEnergia is False or c.raspPunto is False))
        if c.anydesk:
            caj.append(_row(f"AnyDesk de {c.nm}", _rdj([_rds(c.anydesk, "codigo", f"Código {c.anydesk.get('codigo') or '—'}"),
                                                           _rds(c.anydesk, "equipo", c.anydesk.get("equipo") or "equipo de caja")])))
        per = a.get(f"P22h#{c.i}")
        if per:
            caj.append(_row(f"Periféricos de {c.nm}", per["label"]))
    wifi: List[Dict[str, Any]] = []
    if a.get("WZ") and a["WZ"].get("v") == "REVISAR":
        wifi.append(_row("Revisión de WiFi por zona", " · ".join(f"{z['z']}: {fmt(z['dbm'])} dBm, {fmt(z['ping'])} ms ({z['cal']})" for z in X.wz)))
        if X.sinSenal:
            wifi.append(_row("Zonas sin buena señal", ", ".join(X.sinSenal), bad=True))
        if X.solWifi:
            wifi.append(_row("Solución WiFi", X.solWifi))
    wifi.append(_row("Cámaras en la red", f"Sí, {fmt(X.nCam) if X.nCam else '—'} cámaras" if X.camaras else ("No" if a.get("P47") else "")))
    ene = [_row("Tomas cerca de los equipos", a["P33"]["label"] if a.get("P33") else "", bad=X.tomas == "NO")]
    if X.tomas == "NO":
        ene.append(_row("Equipos sin tomas cerca", "Ninguno tiene tomas cerca" if X.ningunaToma else ", ".join(X.sinEnergia), bad=True))
        ene.append(_row("Apreciaciones del técnico", X.apreciacion))
    return {"sec1": sec1, "neg": neg, "net": net, "caj": caj, "wifi": wifi, "ene": ene}


def rules_table(X: Obj, R: Obj, a: Dict[str, Any]) -> List[Dict[str, Any]]:
    L: List[Dict[str, Any]] = []

    def add(rule: str, res: str, ok: bool, text: str) -> None:
        L.append({"rule": rule, "result": res, "ok": ok, "status": text})

    has = lambda id_: any(i.id == id_ for i in R.it)  # noqa: E731
    if not X.obra:
        if R.V01 == "CUMPLE":
            st = (True, "Cumple")
        elif R.V01 == "OBSERVADO":
            st = (False, "Observado")
        else:
            st = (False, "Observado" if X.sinInt else "Sin dato")
        add("Velocidad por cable ≥ 70 % del plan", f"{fmt(R.sp.best)} Mbps de {fmt(X.plan)} Mbps" if R.sp else ("Sin internet" if X.sinInt else "Sin prueba por cable"), *st)
    if R.sp:
        add("Ping con carga ≤ 300 ms", f"{fmt(R.sp.mp)} ms", R.sp.mp <= 300, "Cumple" if R.sp.mp <= 300 else "Observado")
        add("Velocidad sin tope de 100 Mbps", "Limitada a ~94 Mbps" if has("R65") else "Sin tope", not has("R65"), "Revisar" if has("R65") else "Cumple")
    for c in X.cajasInfo or []:
        if c.eq == "SI":
            add(f"PC de {c.nm} por cable", "Conectada por WiFi" if c.pcWifi else "Conectada por cable", not c.pcWifi, "Observado" if c.pcWifi else "Cumple")
    for p in X.printers or []:
        if not p.con:
            continue
        if p.prep:
            add(f"IMP. {p.name} de red por cable", CONN_L[p.con], p.con == "RED", "Cumple" if p.con == "RED" else "Observado")
        if p.con in ("RED", "WIFI") and p.ip:
            ok = p.ip.startswith(X.seg + ".")
            add(f"IMP. {p.name} en el segmento del router", f"IP {p.ip} · router {X.seg}.x", ok, "Verificado" if ok else "Observado")
        if p.estado in ("FALLAS", "MANT"):
            add(f"IMP. {p.name} en buen estado", p.estadoL, False, "Observado" if p.estado == "FALLAS" else "Revisar")
    if X.libres is not None:
        add("Puertos libres para los equipos por cable", f"{fmt(X.libres)} libres · {X.eqCable or 0} equipos", not X.switchN, "Observado" if X.switchN else "Cumple")
    if X.tomas:
        add("Tomas de energía cerca", "Sí" if X.tomas == "SI" else "No", X.tomas == "SI", "Cumple" if X.tomas == "SI" else "Observado")
    if a.get("WZ") and a["WZ"].get("v") == "REVISAR":
        add("Buena señal WiFi en las zonas revisadas", "Sin buena señal: " + ", ".join(X.sinSenal) if X.sinSenal else "Todas con buena señal",
            not X.sinSenal, "Observado" if X.sinSenal else "Cumple")
    if X.bw and X.plan:
        ok = X.con == "CHIP" or X.plan >= X.bw.min
        add("Plan cubre el mínimo por equipo", f"{fmt(X.plan)} Mbps / mínimo {fmt(X.bw.min)} Mbps", ok, "Cumple" if ok else "Observado")
    pend = [] if X.simple else [k for k in a if re.match(r"^E", k) and a[k] and a[k].get("v") == "SKIP"]
    add("Evidencias completas", f"{len(pend)} pendientes" if pend else "Todas subidas", not pend, "Incompleto" if pend else "Verificado")
    return L


def otros_equipos(m: Dict[str, Any]) -> List[Dict[str, str]]:
    out = []
    for n in m["nodes"]:
        if n.type in ("printer", "internet"):
            continue
        det = " · ".join(x for x in [n.sub, f"IP {n.ip}" if n.ip else None] if x) or "—"
        st = "Por implementar" if n.status == "pending" else "Con falla / observado" if n.status == "broken" else "Existente"
        out.append({"eq": n.label, "tipo": DT_LABEL.get(n.type, "Otro equipo"), "ubic": n.ubic or "—", "det": det, "st": st})
    return out


def _cell(caption: str, title: str, lines: List[str], refs: List[Dict[str, str]]) -> Dict[str, Any]:
    return {"caption": "Imagen de: " + caption, "title": title, "lines": [x for x in lines if x], "evidence": refs}


def annex(X: Obj, a: Dict[str, Any], N: List[Dict[str, Any]]) -> Dict[str, Any]:
    def ok(id_: str) -> bool:
        return bool(a.get(id_)) and a[id_].get("v") == "OK"

    def D(id_: str) -> Dict[str, Any]:
        return (a[id_].get("data") or {}) if ok(id_) else {}

    def ref(id_: str) -> List[Dict[str, str]]:
        code, _, scope = id_.partition("#")
        return [{"code": code, "scope": scope}]

    gen: List[Dict[str, Any]] = []
    for n in N:
        if n["kind"] == "ev" and ok(n["id"]):
            dd = D(n["id"])
            id_ = n["id"]
            if id_ == "E1":
                d12 = _rdj([_rds(dd, "d1", f"{fmt(dd.get('d1'))}"), _rds(dd, "d2", f"{fmt(dd.get('d2'))}")], " y ")
                ping = _rdj([_rds(dd, "p", f"Ping {fmt(dd.get('p'))} ms"),
                             "" if _del(dd, "pd") and _del(dd, "pu") else f"({_rdj([_rds(dd, 'pd', fmt(dd.get('pd'))), _rds(dd, 'pu', fmt(dd.get('pu')))], '/')} ms con carga)"], " ")
                gen.append(_cell("Speedtest por cable", "Speedtest por cable", [
                    _rdj([d12 + ("" if _del(dd, "d1") and _del(dd, "d2") else " Mbps"), _rds(dd, "u", f"subida {fmt(dd.get('u'))} Mbps")]), ping, f"Ubic.: {X.routerUbic or '—'}"], ref(id_)))
            elif id_ == "E1b":
                gen.append(_cell("Speedtest con chip", "Speedtest con chip", [f"Chip {X.chipL or ''}: " + _rdj([
                    _rds(dd, "d", f"descarga {fmt(dd.get('d'))} Mbps"), _rds(dd, "u", f"subida {fmt(dd.get('u'))} Mbps"), _rds(dd, "p", f"ping {fmt(dd.get('p'))} ms")], ", ")], ref(id_)))
            elif id_ == "E1c":
                gen.append(_cell("ipconfig", "ipconfig", [_rdj([_rds(dd, "ip", f"IP {dd.get('ip') or '—'}"), _rds(dd, "mascara", f"máscara {dd.get('mascara') or '—'}")]),
                                                           _rds(dd, "gw", f"Puerta de enlace {dd.get('gw') or '—'}")], ref(id_)))
            elif id_ == "E1d":
                gen.append(_cell("Escáner de IP", "Escáner de IP", [_rds(dd, "equipos", f"{fmt(dd.get('equipos') or 0)} equipos en la red"),
                                                                    f"Impresoras: {dd['impresoras']}" if dd.get("impresoras") and not _del(dd, "impresoras") else ""], ref(id_)))
            elif id_.startswith("E7#"):
                gen.append(_cell("AnyDesk", "AnyDesk", [_rds(dd, "codigo", f"Código {dd.get('codigo') or '—'}"), _rds(dd, "equipo", dd.get("equipo") or "")], ref(id_)))
        if n["kind"] == "check" and n["id"] != "EVQ" and a.get(n["id"]):
            for it in n["items"]:
                if ok(f"{n['id']}#{it['k']}"):
                    gen.append(_cell(it["k"], it["k"], [re.sub(r" · que se vea la toma de energía.*$", "", it["t"])], ref(f"{n['id']}#{it['k']}")))
    RT = X.router or {}
    rc: List[Dict[str, Any]] = []
    if ok("E2u"):
        rc.append(_cell("Router · Ubicación", "Ubicación", [f"Ubic.: {X.routerUbic or '—'}", f"IP {RT['ip']}" if RT.get("ip") else ""], ref("E2u")))
    if ok("E2"):
        rc.append(_cell("Router · Puertos", "Puertos", [f"{fmt(RT['puertos'])} puertos · {'—' if RT.get('libres') is None else fmt(RT['libres'])} libres · {'—' if RT.get('ocupados') is None else fmt(RT['ocupados'])} ocupados" if RT.get("puertos") is not None else ""], ref("E2")))
    if ok("E2e"):
        rc.append(_cell("Router · Etiqueta (SN y modelo)", "Etiqueta (SN y modelo)", [f"{RT.get('marca') or ''} {RT.get('modelo') or ''}".strip(),
                                                                                     f"SN {RT['sn']}" if RT.get("sn") else "", f"Proveedor {RT['proveedor']}" if RT.get("proveedor") else ""], ref("E2e")))
    oq = next((n for n in N if n["id"] == "EVQ"), None)
    oc = [_cell(it["k"], it["k"], [re.sub(r" · que se vea la toma de energía.*$", "", it["t"])], ref(f"EVQ#{it['k']}"))
          for it in (oq["items"] if oq else []) if ok(f"EVQ#{it['k']}")]
    blocks: List[Dict[str, Any]] = []
    if rc:
        blocks.append({"heading": f"Router principal · Ubic.: {X.routerUbic or '—'}", "cells": rc})
    if oc:
        blocks.append({"heading": "Otros equipos del local", "cells": oc})
    LBL = {"E5a": "Etiqueta (SN y modelo)", "E5b": "Conexiones", "E5": "Selftest (hoja de prueba)"}
    prn: List[Dict[str, Any]] = []
    for p in X.printers or []:
        K = "#" + p.name
        cs = []
        for c in ("E5a", "E5b", "E5"):
            if not ok(c + K):
                continue
            dd = D(c + K)
            mm = f"{_rds(dd, 'marca', dd.get('marca') or '')} {_rds(dd, 'modelo', dd.get('modelo') or '')}".strip()
            if c == "E5a":
                d = [mm, f"SN {dd['sn']}" if dd.get("sn") and not _del(dd, "sn") else ""]
            elif c == "E5b":
                d = [_rds(dd, "ver", f"Se ve {CONN_TXT.get(dd.get('ver'), '—')}.")]
            elif dd.get("ip") and not _del(dd, "ip"):
                d = [mm, _rdj([f"IP {dd['ip']}", _rds(dd, "mac", f"MAC {dd.get('mac') or '—'}")]), _rds(dd, "gw", f"Puerta de enlace {dd.get('gw') or '—'}")]
            elif dd.get("ip"):
                d = [mm, _rds(dd, "mac", f"MAC {dd['mac']}" if dd.get("mac") else ""), _rds(dd, "gw", f"Puerta de enlace {dd['gw']}" if dd.get("gw") else "")]
            else:
                d = [f"{dd.get('marca') or ''} {dd.get('modelo') or ''}".strip(), "USB: sin IP ni MAC"]
            cs.append(_cell(f"IMP. {p.name} · {LBL[c]}", LBL[c], d, ref(c + K)))
        if cs:
            prn.append({"heading": f"IMP. {p.name} · Ubic.: {p.name if p.prep else 'Caja'}", "cells": cs})
    v = a.get("P49a", {}).get("v") if a.get("P49a") else None
    vids = v if isinstance(v, list) else ([{"d": "Video del local", "u": v}] if v else [])
    return {"general": gen, "other": blocks, "printers": prn, "videos": vids}


def build_document(state_answers: Dict[str, Any], ctx: Dict[str, Any], edits: Optional[Dict[str, Any]] = None,
                   meta: Optional[Dict[str, Any]] = None, map_doc: Optional[Dict[str, Any]] = None,
                   map_images: Optional[Dict[str, bytes]] = None) -> Dict[str, Any]:
    a = state_answers
    edits = edits or {}
    meta = meta or {}
    N, X = build(a, ctx)
    R = evaluate(X, a)
    S = scores(X, R, a)
    d = edits.get("datos") or {}
    o = edits.get("obs") or {}
    ed = edits.get("ed") or {}
    cambios = edits.get("cambios") or []
    name = d.get("nombre") or X.nombre or "el local"
    fecha = X.fechaVisita or meta.get("fecha") or ""
    sec = sections(X, R, a, d, meta.get("validatedBy"))
    m = build_map(X)
    otros = otros_equipos(m)
    rules = rules_table(X, R, a)
    recs = ed.get("tobe") or [{"t": i.t, "d": i.d} for i in R.it if i.tipo != "AVISO"]
    pasos = a["P52a"]["v"] if a.get("P52a") else gen_pasos(X, R, a)
    pr = [p for p in X.printers or [] if p.con]
    pago = uniq([*[p for p in (o.get("pago") or []) if p != "Otro"], *([o["pagoOtro"]] if "Otro" in (o.get("pago") or []) and o.get("pagoOtro") else [])])
    has_obs = bool(o.get("tec") or o.get("serie") or o.get("viab") or pago or o.get("otroT") or cambios)
    kpis = [{"label": c.k.replace(" de Red", ""), "value": c.v, "level": lvl(c.v)["label"], "color": lvl(c.v)["color"]} for c in S.cards if c.v is not None]
    glob = {"label": "Puntuación global", "value": S.g, "level": lvl(S.g)["label"], "color": "#22286b"}

    blocks: List[Dict[str, Any]] = []
    num = [0]

    def h2(text: str, cls: str = "") -> None:
        num[0] += 1
        blocks.append({"t": "h2", "n": f"{num[0]}.", "text": text, "cls": cls})

    h2("Datos generales")
    blocks.append(_table(sec["sec1"]))
    h2("Antecedentes")
    blocks.append({"t": "para", "text": f'La visita se realiza para la implementación del punto de venta, donde el local se encuentra en estado de "{X.estadoL}". '
                                    "En la visita se realizarán acciones como validar los equipos tecnológicos y de red y el estado de los mismos, y se le recomendará una mejor infraestructura si lo necesitara."})
    h2("Desarrollo y hallazgos")
    blocks.append({"t": "h3", "text": "Negocio"})
    blocks.append(_table(sec["neg"]))
    blocks.append({"t": "h3", "text": "Internet"})
    blocks.append(_table(sec["net"]))
    if sec["caj"]:
        blocks.append({"t": "h3", "text": "Equipos de caja"})
        blocks.append(_table(sec["caj"]))
    if pr:
        rows = []
        for p in pr:
            bad = p.estado in ("FALLAS", "MANT") or (p.prep and p.con != "RED")
            if p.con == "NO":
                est = "Por adquirir"
            elif p.prep and p.con != "RED":
                est = "Debe ser de red" + (f" · {p.estadoL.lower()}" if p.estadoL else "")
            else:
                est = p.estadoL or "Sin dato"
            rows.append({"cells": [f"IMP. {p.name}", p.name if p.prep else "Caja", (" ".join(x for x in [p.marca, p.modelo] if x) or "Sin dato") + (f" · SN {p.sn}" if p.sn else ""),
                                   "No aplica (USB)" if p.con == "USB" else (p.ip + (f" · {p.mac}" if p.mac else "") if p.ip else "Sin dato"),
                                   CONN_L[p.con] + (f" · {p.viaL.lower()}" if p.viaL else ""), est], "badLast": bool(bad)})
        blocks.append({"t": "h3", "text": "Impresoras"})
        blocks.append({"t": "table", "head": ["Nombre", "Ubicación", "Marca y modelo · SN", "IP · MAC", "Conexión", "Estado"], "rows": rows, "firstBold": True})
    if otros:
        blocks.append({"t": "h3", "text": "Equipos varios"})
        blocks.append({"t": "table", "head": ["Equipo", "Tipo", "Ubicación", "Detalle", "Estado"],
                       "rows": [{"cells": [e["eq"], e["tipo"], e["ubic"], e["det"], e["st"]], "lastCls": "ok" if e["st"] == "Existente" else "" if e["st"] == "Por implementar" else "bad"} for e in otros], "firstBold": True})
    blocks.append({"t": "h3", "text": "WiFi y cámaras"})
    blocks.append(_table(sec["wifi"]))
    blocks.append({"t": "h3", "text": "Energía eléctrica"})
    blocks.append(_table(sec["ene"]))
    h2("Topología de red")
    blocks.append({"t": "map"})
    h2("Validación técnica automática")
    blocks.append({"t": "rules", "rows": rules})
    h2("Recomendaciones")
    blocks.append({"t": "ul", "items": [{"b": i["t"] + ".", "text": i["d"]} for i in recs] or [{"text": "Sin recomendaciones."}]})
    if has_obs:
        h2("Observaciones")
        if o.get("tec"):
            blocks.append({"t": "para", "text": o["tec"]})
        if o.get("serie"):
            blocks.append({"t": "para", "text": f"Serie de facturación: {o['serie']}"})
        if o.get("viab"):
            blocks.append({"t": "para", "text": f"¿El cliente acepta la recomendación? {o.get('viabOtro') if o['viab'] == 'Otro' else o['viab']}"})
        if pago:
            blocks.append({"t": "para", "text": f"El método de pago que utilizan en el local es el siguiente: {', '.join(pago)}."})
        if o.get("otroT"):
            blocks.append({"t": "para", "b": f"{o['otroT']}:", "text": o.get("otroC") or ""})
        for c in cambios:
            blocks.append({"t": "para", "text": f"Cambio pedido en el chat: {c}"})
    h2("Resumen ejecutivo")
    blocks.append({"t": "exec", "status": R.estado, "ok": R.estado == "APTO", "text": resumen_ia(X, R, name)})
    h2("Aviso de viabilidad")
    blocks.append({"t": "viab", "text": VIABILITY})
    h2("Pasos a seguir")
    blocks.append({"t": "h3", "text": "Por parte del equipo técnico:"})
    blocks.append({"t": "ul", "items": [{"text": p["t"]} for p in pasos if p["p"] != "Cliente"]})
    blocks.append({"t": "h3", "text": f"Por parte de {name}:"})
    blocks.append({"t": "ul", "items": [{"text": p["t"]} for p in pasos if p["p"] == "Cliente"]})
    ann = annex(X, a, N)
    if ann["general"] or ann["other"] or ann["printers"] or ann["videos"]:
        label = "Anexo A."
        if ann["general"] or ann["other"] or ann["printers"]:
            blocks.append({"t": "h2", "n": label, "text": "Evidencias utilizadas", "cls": "annex"})
            if ann["general"]:
                blocks.append({"t": "grid", "cols": 2, "cells": ann["general"]})
            if ann["other"]:
                blocks.append({"t": "h3", "text": "Otros equipos"})
                for b in ann["other"]:
                    blocks.append({"t": "block", "heading": b["heading"], "cols": 3, "cells": b["cells"]})
            if ann["printers"]:
                blocks.append({"t": "h3", "text": "Impresoras"})
                for b in ann["printers"]:
                    blocks.append({"t": "block", "heading": b["heading"], "cols": 3, "cells": b["cells"]})
        if ann["videos"]:
            lab = "Anexo B." if label and (ann["general"] or ann["other"] or ann["printers"]) else "Anexo A."
            blocks.append({"t": "h2", "n": lab, "text": "Videos del local y de los equipos", "cls": "" if lab == "Anexo B." else "annex"})
            blocks.append({"t": "table", "head": ["N.°", "Video", "Enlace"], "rows": [{"cells": [str(i + 1), v.get("d") or "", v.get("u") or ""]} for i, v in enumerate(ann["videos"])], "firstBold": False})
            blocks.append({"t": "note", "text": "Enlaces agregados por el técnico: recorrido del local, ubicación de los equipos de red y del sistema de impresiones."})

    # fotos obligatorias que faltan (con alguna ausente no se genera el PDF)
    missing: List[str] = []
    for n in N:
        if n["kind"] == "check" and n["id"] == "EV":
            for it in n["items"]:
                if not it.get("opt") and not (a.get(f"EV#{it['k']}") and a[f"EV#{it['k']}"].get("v") == "OK"):
                    missing.append(it["k"])
    png = render_print_png(m, map_doc, map_images or {})
    return {
        "title": "MINUTA TÉCNICA DE RED", "subtitle": name, "date": fecha,
        "header": f"Minuta técnica · {name} · {fecha}",
        "intro": f"Minuta generada por el Asistente Virtual de Red a partir de las respuestas del técnico y de las evidencias fotográficas de la visita del {fecha}.",
        "kpis": kpis, "global": glob, "estado": R.estado, "blocks": blocks, "viabilityNotice": VIABILITY,
        "mapPngBase64": base64.b64encode(png).decode() if png else "",
        "mapLegend": "Azul: conexión existente · plomo: por implementar · rojo: con falla / observado · flecha: USB",
        "missingMandatory": missing,
        "scores": {"g": S.g, "cards": [{"k": c.k, "v": c.v} for c in S.cards]},
    }
