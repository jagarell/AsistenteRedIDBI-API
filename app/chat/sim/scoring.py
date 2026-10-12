"""Análisis IA (port de `scores`, `critInfra`, `critEquip`, `critWifi`, `cardDesc`, `verbo`, `resumenIA` y las Referencias)."""
import re
from typing import Any, Dict, List, Optional

from app.chat.sim.flow import CAT, PERFIL
from app.chat.sim.util import Obj, fmt, jsround, jsum, uniq

TILES = {
    "Conectividad de Red": ("router", "#1565C0", "#E3F2FD"),
    "Infraestructura Física": ("servr", "#F57C00", "#FFF3E0"),
    "Equipamiento": ("router", "#2E7D32", "#E8F5E9"),
    "Cobertura WiFi": ("wifi", "#D32F2F", "#FDEAEA"),
}


def lvl(v: Optional[float]) -> Dict[str, str]:
    if v is None:
        return {"label": "No aplica", "cls": "st-n", "color": "#90A4AE"}
    if v >= 80:
        return {"label": "Óptimo", "cls": "st-o", "color": "#2E7D32"}
    if v >= 65:
        return {"label": "Buena", "cls": "st-b", "color": "#1565C0"}
    if v >= 50:
        return {"label": "Regular", "cls": "st-r", "color": "#EF6C00"}
    return {"label": "Deficiente", "cls": "st-d", "color": "#C62828"}


def kpi(lst: List[Obj]) -> Obj:
    ap = [c for c in lst if c.r is not None]
    if not ap:
        return Obj(v=None, why=[])
    tot = jsum(c.w for c in ap)
    got = jsum(c.w * max(0, min(1, c.r)) for c in ap)
    why = [(f"{c.k}: no aplica{' (' + c.d + ')' if c.d else ''}" if c.r is None
            else f"{c.k}: {c.d} → {fmt(jsround(c.w * c.r * 10) / 10)} de {c.w}") for c in lst]
    return Obj(v=jsround(100 * got / tot), why=why, crit=lst)


def ratio(a: float, b: float) -> Optional[float]:
    return a / b if b > 0 else None


def crit_infra(X: Obj, R: Obj, a: Dict[str, Any]) -> List[Obj]:
    def has(id_: str) -> bool:
        return any(i.id == id_ for i in R.it)

    C: List[Obj] = []
    nP = okP = 0
    sin_dato = False
    if X.eqCable is not None and X.libres is not None:
        nP += X.eqCable
        okP += min(X.libres, X.eqCable)
    elif X.hasInt and not X.obra and not X.simple:
        sin_dato = True
    for c in X.cajasInfo or []:
        if (c.rasp or c.adq == "RASPBERRY") and c.raspPunto is not None and c.raspVia and c.raspVia != "ROUTER":
            nP += 1
            if c.raspPunto:
                okP += 1
    C.append(Obj(k="Puntos de red", w=30, r=okP / nP if nP else None,
                 d=f"{okP} de {nP} equipos por cable con puerto libre o punto de red" if nP
                 else ("sin dato de puertos" if sin_dato else "sin equipos por cable que medir")))
    dev = X.devices or []
    sin = len(X.sinEnergia) if X.tomas == "NO" else 0
    C.append(Obj(k="Tomas de energía", w=25, r=None if (X.simple or not X.tomas or not dev) else ratio(len(dev) - sin, len(dev)),
                 d="no aplica al rubro" if X.simple else "sin dato" if not X.tomas else f"{len(dev) - sin} de {len(dev)} equipos con toma cerca"))
    deb: List[bool] = []
    for c in X.cajasInfo or []:
        if c.eq == "SI":
            deb.append(bool(c.pcCable))
        if c.rasp:
            deb.append(bool(c.raspCable))
    for p in X.printers or []:
        if p.prep and p.con and p.con not in ("NO", "NONE"):
            deb.append(p.con == "RED" and p.via != "WIFI")
    ok_deb = len([x for x in deb if x])
    C.append(Obj(k="Conexión por cable", w=20, r=ratio(ok_deb, len(deb)),
                 d=f"{ok_deb} de {len(deb)} equipos que deben ir por cable lo están" if deb else "sin equipos que deban ir por cable"))
    ip_p = [p for p in X.printers or [] if p.con in ("RED", "WIFI") and p.ip]
    in_seg = len([p for p in ip_p if p.ip.startswith(X.seg + ".")])
    C.append(Obj(k="Segmento de red", w=10, r=ratio(in_seg, len(ip_p)),
                 d=f"{in_seg} de {len(ip_p)} impresoras de red en {X.seg}.x" if ip_p else "sin impresoras de red con IP"))
    C.append(Obj(k="Calidad del cableado", w=10, r=(0 if has("R65") else 1) if R.sp else None,
                 d=("velocidad limitada a ~100 Mbps (cable, puerto o switch de 10/100)" if has("R65") else "sin tope de 100 Mbps en la prueba por cable")
                 if R.sp else "sin prueba por cable"))
    C.append(Obj(k="Protección del cableado", w=5, r=None if (X.simple or a.get("P34c") is None) else (0 if X.cableElec else 1),
                 d="cable de red junto a electrodomésticos" if X.cableElec else "cableado lejos de electrodomésticos"))
    return C


def crit_equip(X: Obj, R: Obj, a: Dict[str, Any]) -> List[Obj]:
    C: List[Obj] = []
    cj = X.cajasInfo or []

    def val(c: Obj) -> float:
        return 1 if ((c.eq == "SI" and not c.temporal) or c.rasp or c.posPropio) else 0.5 if c.adq else 0

    sc = jsum(val(c) for c in cj)

    def cdesc(c: Obj) -> str:
        if c.eq == "SI" and not c.temporal:
            t = "PC o laptop"
        elif c.posPropio:
            t = f"{c.eqL} (imprime en la misma caja)"
        elif c.rasp:
            t = "con Raspberry"
        elif c.adq:
            t = f"adquirirá {str(c.adqL).lower()} (½)"
        else:
            t = "sin equipo"
        return f"{c.nm}: {t}"

    C.append(Obj(k="Equipo de caja viable", w=30, r=ratio(sc, len(cj)), d=" · ".join(cdesc(c) for c in cj) if cj else "sin cajas"))
    pr = X.printers or []
    exist = len([p for p in pr if p.con and p.con != "NO"])
    C.append(Obj(k="Impresoras existentes", w=25, r=ratio(exist, len(pr)),
                 d=f"{exist} de {len(pr)} impresoras necesarias ya existen" if pr else "sin impresoras"))
    ex = [p for p in pr if p.con and p.con not in ("NO", "NONE")]
    ok = [p for p in ex if ((p.con == "RED") if p.prep else (p.con != "USB" or p.usbTo == "PC"))]
    C.append(Obj(k="Impresora adecuada", w=20, r=ratio(len(ok), len(ex)),
                 d=f"{len(ok)} de {len(ex)} impresoras del tipo correcto (preparación de red; USB solo con PC o laptop)" if ex else "sin impresoras conectadas"))
    EV = {"NUEVA": 1, "VIABLE": 1, "MANT": 0.5, "FALLAS": 0}
    est = [p for p in ex if p.estado]
    se = jsum(EV.get(p.estado, 0.5) for p in est)
    C.append(Obj(k="Estado de las impresoras", w=15, r=ratio(se, len(est)),
                 d=" · ".join(f"{p.name}: {str(p.estadoL or '').lower()}" for p in est) if est else "sin dato"))
    ad = [c for c in cj if a.get(f"E7#{c.i}") is not None]
    ad_ok = len([c for c in ad if c.anydesk and c.anydesk.get("codigo")])
    C.append(Obj(k="Acceso remoto (AnyDesk)", w=10, r=ratio(ad_ok, len(ad)),
                 d=f"{ad_ok} de {len(ad)} equipos de caja con código de AnyDesk" if ad else "no se pidió"))
    return C


def crit_wifi(X: Obj, R: Obj) -> Optional[List[Obj]]:
    if X.wifiSkip or not X.allZ:
        return None
    Z, bad = X.allZ, X.sinSenal or []
    C = [Obj(k="Zonas con buena señal", w=65, r=ratio(len(Z) - len(bad), len(Z)),
             d=f"{len(Z) - len(bad)} de {len(Z)} zonas y lugares de preparación{' (sin buena señal: ' + ', '.join(bad) + ')' if bad else ''}")]
    Q = {"Excelente": 1, "Buena": 0.85, "Regular": 0.5, "Mala": 0}
    wz = X.wz or []
    C.append(Obj(k="Calidad medida", w=20, r=jsum(Q[z["cal"]] for z in wz) / len(wz) if wz else None,
                 d=" · ".join(f"{z['z']} {z['cal'].lower()}" for z in wz) if wz else "no se midió por zona"))
    C.append(Obj(k="Solución definida", w=15, r=(1 if X.solWifi else 0) if bad else 1,
                 d=(f"se instalará {X.solWifi.lower()}" if X.solWifi else "falta definir la solución") if bad else "no hace falta"))
    return C


def scores(X: Obj, R: Obj, a: Dict[str, Any]) -> Obj:
    en_obra = X.obra and not R.sp
    conn = None if en_obra else (R.con.pct if R.con else None)
    conn_crit = None if en_obra else (R.con.get("crit") if R.con and R.con.get("crit") else None)
    conn_w = ["Local en obra: la conectividad se valida en la segunda visita"] if en_obra else (list(R.con.steps) if R.con else ["Sin datos del plan"])
    inf = kpi(crit_infra(X, R, a))
    eq = kpi(crit_equip(X, R, a))
    wc = crit_wifi(X, R)
    wf = kpi(wc) if wc else Obj(v=None, why=[])

    def cl(v: Optional[float]) -> Optional[float]:
        return None if v is None else max(0, min(100, v))

    def card(k: str, v: Optional[float], why: List[str], crit: Optional[List[Obj]]) -> Obj:
        icon, tint, bg = TILES[k]
        return Obj(k=k, v=cl(v), why=why, crit=crit, icon=icon, tint=tint, bg=bg)

    cards = [
        card("Conectividad de Red", conn, conn_w, conn_crit),
        card("Infraestructura Física", inf.v, inf.why, inf.get("crit")),
        card("Equipamiento", eq.v, eq.why, eq.get("crit")),
        card("Cobertura WiFi", wf.v,
             wf.why if wc else ["No aplica por el perfil del rubro (sin mozos con tablet, en obra, Retail u Otro)"], wf.get("crit")),
    ]
    vals = [c.v for c in cards if c.v is not None]
    g = jsround(jsum(vals) / len(vals)) if vals else 0
    return Obj(cards=cards, g=g, att=len([c for c in cards if c.v is not None and c.v < 65]), areas=len(vals))


def card_desc(c: Obj, X: Obj, R: Obj) -> str:
    if c.k == "Conectividad de Red":
        if c.v is None and X.obra:
            return "Local en obra: la conectividad se valida en la segunda visita."
        if X.porContratar:
            return "El cliente va a contratar internet antes de implementar. Se valida en la segunda visita."
        if X.sinInt:
            return "El local no tiene internet. Se recomienda un TP-Link con entrada de chip para la impresión."
        bw = X.bw
        parts = [f"Plan de {fmt(X.plan)} Mbps por {(X.conL or '').lower()}."]
        if R.sp:
            parts.append(f"Prueba por cable: {fmt(R.sp.best)} Mbps ({jsround(R.sp.pct * 100)} % del plan).")
        elif R.V01:
            parts.append("Plan sin verificar por cable.")
        if bw:
            if X.con == "CHIP":
                parts.append(f"Internet por chip: cubre los equipos. Recomendado: {fmt(bw.rec)} Mbps.")
            elif X.plan < bw.min:
                parts.append(f"No cubre el mínimo de los equipos ({fmt(bw.min)} Mbps).")
            else:
                parts.append(f"Cubre el mínimo de los equipos ({fmt(bw.min)} Mbps); recomendado {fmt(bw.rec)} Mbps para {bw.zonas} zona(s) de atención.")
        s = " ".join(parts)
    elif c.crit:
        bad = [f"{q.k.lower()}: {q.d}" for q in c.crit if q.r is not None and q.r < 1]
        if not bad:
            s = "Cumple todos los criterios medidos."
        else:
            t = "; ".join(bad[:3]) + ("…" if len(bad) > 3 else "") + "."
            s = t[:1].upper() + t[1:]
    else:
        w = [re.sub(r" \(−\d+\)$", "", x) for x in c.why]
        t = (w[0] + ".") if len(w) == 1 else "; ".join(w[:3]) + ("…" if len(w) > 3 else "") + "."
        s = t[:1].upper() + t[1:]
    if c.k == "Infraestructura Física" and X.apreciacion:
        s += f" Apreciación del técnico: {X.apreciacion}"
    return s


def verbo(i: Obj, X: Obj) -> Optional[str]:
    m = re.match(r"^IMP\. ([^:]+?)(?::| averiada| con fallas| sin conexión| fuera|$)", i.t)
    nm = m.group(1) if m else None
    sw = X.solWifi
    if sw:
        wifi_what = "access points" if re.search(r"access", sw, re.I) else "repetidores y access points" if sw.lower() == "ambos" else "repetidores"
    else:
        wifi_what = "repetidores o access points"
    M = {
        "R56": lambda: f"independizar la red de impresión con un {i.eq}",
        "A_IMP_RASPBERRY": lambda: "instalar un kit Raspberry como controlador de impresiones",
        "TABLET": lambda: "instalar un kit Raspberry como controlador de impresiones",
        "R60": lambda: "instalar un kit Raspberry como controlador de impresiones",
        "R57": lambda: "ubicar el Raspberry junto al router en un lugar ventilado",
        "A_IMP_PC_CONTROLADOR": lambda: "usar una laptop o PC como controlador de impresiones",
        "A_IMP_PC_BASICA": lambda: "usar una laptop o PC básica con USB para pre-cuentas y comprobantes",
        "A_SUNMI": lambda: "usar un Sunmi con chip en caja",
        "R51": lambda: (f"adquirir una impresora de red por cable para {nm}" if re.search(r"Aún no tiene", i.d)
                        else f"cambiar la impresora de {nm} por una de red por cable"),
        "IMP-AV": lambda: f"reparar o reemplazar la impresora de {nm}",
        "IMP-MT": lambda: f"darle mantenimiento a la impresora de {nm}",
        "OBRA": lambda: "solicitar una segunda visita técnica cuando el local esté habitado para validar la conectividad",
        "OBRA_PUNTOS": lambda: "realizar las conexiones de puntos de red y de energía",
        "OBRA_DN": lambda: "ir cotizando los equipos por implementar con Desarrollo de Negocios",
        "SIN_INT": lambda: "contratar el proveedor de internet e instalar el router antes del inicio" if X.inaug else None,
        "R59": lambda: f"cambiar el cable o el conector de la impresora de {nm}",
        "IMP-NC": lambda: f"verificar la conexión de la impresora de {nm}",
        "IMP": lambda: "adquirir la impresora de caja",
        "R55 · V04": lambda: f"cambiar la IP de la impresora de {nm} al segmento del router",
        "RASP_PTO": lambda: "implementar " + ((re.search(r"falta (.+) para el Raspberry", i.t) or [None, "el punto de red"])[1]) + " para el Raspberry",
        "CAM_NVR": lambda: ("independizar la red de internet de las cámaras o ampliar el plan a 1000 Mbps" if i.tipo == "OBS"
                            else "ampliar el plan de internet a 1000 Mbps por las cámaras del NVR"),
        "R16": lambda: f"mantener la impresora USB de {nm} conectada a la PC o laptop con el controlador",
        "SWITCH": lambda: f"agregar un switch de {X.switchN} puertos e implementar los puntos de red",
        "ENERGIA": lambda: "instalar tomas de energía cerca de los equipos",
        "R19": lambda: f"instalar {wifi_what} en {', '.join(X.sinSenal)}",
        "R53": lambda: "subir el plan de internet o independizar la red de las cámaras de la de impresión",
        "R54": lambda: (f"subir el plan de internet para cubrir al menos {fmt(X.bw.min)} Mbps" if i.tipo == "OBS"
                        else f"subir el plan de internet a {fmt(X.bw.rec)} Mbps"),
        "R67 · V01": lambda: "revisar con el proveedor la velocidad contratada",
        "V03 · R11": lambda: "conectar la PC de caja por cable de red",
        "SAT": lambda: "evaluar internet satelital y programar una segunda visita",
        "R10": lambda: "mantener el router, el Raspberry y las impresoras lejos del calor y la grasa, o cubrirlos para evitar grasa y sobretemperatura",
        "R_ELEC": lambda: "aislar el cable de red que pasa cerca de electrodomésticos",
        "USB": lambda: f"conectar la impresora USB de {nm} solo a una PC o laptop, o cambiarla por una de red",
        "R63": lambda: "probar los periféricos de cada caja",
        "SUPRESOR": lambda: "instalar un supresor de picos",
    }
    fn = M.get(i.id)
    return fn() if fn else None


def resumen_ia(X: Obj, R: Obj, nombre: Optional[str] = None) -> str:
    name = nombre or X.nombre or "el local"
    fr = uniq([x for x in (verbo(i, X) for i in R.it if i.tipo != "AVISO") if x])
    if not fr:
        return f"Para el establecimiento {name} la infraestructura está lista: no se recomiendan cambios para iniciar con el punto de venta."
    lst = fr[0] if len(fr) == 1 else ", ".join(fr[:-1]) + " y " + fr[-1]
    if X.obra:
        cierre = "Como el local está en obra, la conectividad se validará en la segunda visita."
    elif R.estado == "APTO":
        cierre = "Con esto el local queda listo para iniciar con el punto de venta."
    elif R.estado == "NO APTO":
        cierre = "Mientras no se resuelva el internet, no es viable iniciar."
    else:
        cierre = "Con estos cambios el local queda listo para iniciar con el punto de venta."
    return f"Para el establecimiento {name} se recomienda {lst}. {cierre}"


# ---- Referencias (solo en el Análisis IA; nunca en la minuta ni en el PDF) ----
REF_MIN: List[Dict[str, Any]] = CAT["REF_MIN"]
REF_RULE: Dict[str, List[str]] = CAT["REF_RULE"]
REF_MAP: Dict[str, List[str]] = CAT["REF_MAP"]
REF_SUGERIBLE: List[str] = CAT["REF_SUGERIBLE"]
REF_FAM: Dict[str, str] = CAT["REF_FAM"]
REF_W: Dict[str, int] = CAT["REF_W"]


def ref_feat(X: Obj) -> Dict[str, Any]:
    eqs = [c.eq for c in X.cajasInfo or []]
    return {"rub": X.rub, "est": X.estadoV or "EN_OPERACION", "np": len(X.prep or []), "cj": X.cajas or 1,
            "con": "POR_CONTRATAR" if X.porContratar else (X.con or ""),
            "eq": "TABLET" if "TABLET" in eqs else "SI" if "SI" in eqs else "NO" if eqs else "",
            "usb": any(p.con == "USB" for p in X.printers or []), "cam": bool(X.camaras)}


def ref_sim(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    m = {
        "rub": 1 if a["rub"] == b["rub"] else 0.6 if (REF_FAM.get(a["rub"]) and REF_FAM.get(a["rub"]) == REF_FAM.get(b["rub"])) else 0,
        "np": 1 - min(1, abs(a["np"] - b["np"]) / 3),
        "con": 0.5 if (not a["con"] or not b["con"]) else 1 if a["con"] == b["con"] else 0,
        "cj": 1 - min(1, abs(a["cj"] - b["cj"]) / 2),
        "eq": 0.5 if (not a["eq"] or not b["eq"]) else 1 if a["eq"] == b["eq"] else 0,
        "usb": 1 if a["usb"] == b["usb"] else 0,
        "cam": 1 if a["cam"] == b["cam"] else 0,
        "est": 1 if a["est"] == b["est"] else 0.4,
    }
    tot = jsum(REF_W.values())
    return {"pct": jsround(100 * jsum(REF_W[k] * m[k] for k in REF_W) / tot), "m": m}


def ref_freq(r: str) -> int:
    return len([x for x in REF_MIN if r in x["r"]])


def ref_data(X: Obj, R: Obj) -> Dict[str, Any]:
    f = ref_feat(X)
    top = [{**x, **ref_sim(f, x)} for x in REF_MIN]
    top.sort(key=lambda x: -x["pct"])  # sort estable, igual que JS
    gen = set()
    for i in R.it:
        for k in REF_MAP.get(i.id, []):
            gen.add(k)
    recs = []
    for i in R.it:
        if i.tipo == "AVISO":
            continue
        ks = REF_MAP.get(i.id, [])
        recs.append({"t": i.t, "n": max(ref_freq(k) for k in ks) if ks else 0})
    cnt: Dict[str, int] = {}
    for x in top[:5]:
        for r in x["r"]:
            if r in REF_SUGERIBLE and r not in gen and r in REF_RULE:
                cnt[r] = cnt.get(r, 0) + 1
    sug = sorted([(r, n) for r, n in cnt.items() if n >= 2], key=lambda t: -t[1])[:4]
    seen, top3 = set(), []
    for x in top:
        if x["n"] in seen:
            continue
        seen.add(x["n"])
        top3.append(x)
        if len(top3) == 3:
            break
    return {"top": top3, "recs": recs,
            "sug": [{"r": r, "n": n, "t": REF_RULE[r][0], "d": REF_RULE[r][1]} for r, n in sug], "f": f}


def ref_rub(r: str) -> str:
    p = PERFIL.get(r)
    return re.sub(r"^(Un|Una|El)\s+", "", p["un"]) if p else str(r or "").lower()


def ref_why(x: Dict[str, Any]) -> str:
    s: List[str] = []
    if x["m"]["rub"] == 1:
        s.append("mismo rubro")
    elif x["m"]["rub"] > 0:
        s.append("rubro parecido")
    if x["m"]["np"] == 1:
        s.append(f"{x['np']} área{'' if x['np'] == 1 else 's'} de preparación")
    if x["m"]["cj"] == 1:
        s.append(f"{x['cj']} caja{'s' if x['cj'] > 1 else ''}")
    if x["m"]["con"] == 1:
        s.append("misma conexión")
    if x["m"]["eq"] == 1:
        s.append("mismo equipo de caja")
    if x["usb"] and x["m"]["usb"] == 1:
        s.append("impresora USB")
    if x["cam"] and x["m"]["cam"] == 1:
        s.append("con cámaras")
    return " · ".join(s)
