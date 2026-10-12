"""Reglas de la visita (port de `evaluate()`, `bwNeed()`, `rate()` y `genPasos()` del simulador)."""
import re
from typing import Any, Dict, List, Optional

from app.chat.sim.flow import CAT, fmt_date
from app.chat.sim.util import Obj, fmt, jsround, jsum, num, truthy, uniq

MOZOS: List[str] = CAT["MOZOS"]


def bw_need(X: Obj, a: Dict[str, Any]) -> Obj:
    det: List[str] = []
    total = [0]

    def add(n: int, mb: int, t: str) -> None:
        if n > 0:
            total[0] += n * mb
            det.append(f"{t} {n}×{mb}")

    for c in X.cajasInfo or []:
        if c.eq == "SI":
            add(1, 10 if c.pcWifi else 5, "PC por WiFi" if c.pcWifi else "PC por cable")
        elif c.eq == "TABLET":
            add(1, 10, "tablet por WiFi")
        if c.rasp or c.adq == "RASPBERRY":
            add(1, 10 if (c.rasp and c.raspCable is False) else 5, "Raspberry")
        elif c.adq:
            add(1, 5, (c.adqL or "equipo").lower())
    if X.decision == "RASPBERRY" and not any(c.rasp or c.adq == "RASPBERRY" for c in X.cajasInfo or []):
        add(1, 5, "Raspberry")
    p09c = a.get("P09c")
    if X.rub and X.rub != "RETAIL" and (X.rub not in MOZOS or (p09c and p09c.get("v") == "SI")):
        add(len([z for z in X.zonas if z["canal"] == "Mesa"]), 10, "tablet o celular de mozo por WiFi")
    zonas = len(uniq([z["z"] for z in X.zonas]))
    return Obj(min=total[0], det=det, zonas=zonas, rec=150 * zonas)


def rate(m: Dict[str, Any]) -> Dict[str, str]:
    s, p = m.get("dbm"), m.get("ping")
    rk = ["Excelente", "Buena", "Regular", "Mala"]
    rs = 0 if s >= -60 else 1 if s >= -67 else 2 if s >= -75 else 3
    rp = 0 if p < 50 else 1 if p <= 100 else 2 if p <= 200 else 3
    return {"cal": rk[max(rs, rp)], "rs": rk[rs], "rp": rk[rp]}


def evaluate(X: Obj, a: Dict[str, Any]) -> Obj:
    it: List[Obj] = []

    def add(o: Dict[str, Any]) -> None:
        it.append(Obj(o))

    if X.sunmi:
        add({"id": "A_SUNMI", "tipo": "REC", "t": "Sunmi con chip", "d": "La comanda sale solo en caja.", "eq": "Sunmi con chip"})
    if X.sinInt:
        add({"id": "SIN_INT", "tipo": "OBS", "t": "Sin internet",
             "d": "Conectividad 0 %. Por inaugurar: el proveedor de internet ya debe estar contratado y el router instalado antes del inicio." if X.inaug else "Conectividad 0 %."})
    if X.obra:
        sin_int = " y aún no tiene internet" if (X.sinInt or X.porContratar) else ""
        add({"id": "OBRA", "tipo": "REC", "t": "Segunda visita técnica",
             "d": f"El local se encuentra en obra{sin_int}. Cuando esté habitado, solicitar una segunda visita para levantar la información nueva y realizar las validaciones de conectividad.",
             "trabajo": "segunda visita cuando el local esté habitado"})
        add({"id": "OBRA_PUNTOS", "tipo": "REC", "t": "Puntos de red y de energía",
             "d": "El cliente debe realizar las conexiones de puntos de red y de energía donde irán el router, el equipo de caja y las impresoras.",
             "trabajo": "puntos de red y de energía"})
    if X.r56:
        plan = "plan superior (soporta las cámaras)" if X.camaras else "plan básico"
        chip = f"Chip {X.chipProv}" if X.chipProv else "Chip del proveedor con mejor señal"
        add({"id": "R56", "tipo": "REC", "t": f"TP-Link con entrada de chip + {chip}, {plan}",
             "d": f"El local {', '.join(X.motivos)}. Red independiente solo para las impresoras y el equipo del sistema de impresiones; reemplaza al internet del local para la impresión.",
             "eq": f"TP-Link con entrada de chip + {chip} ({'plan superior' if X.camaras else 'plan básico'})"})
    if X.chip == "SALTAR":
        add({"id": "CHIP_PEND", "tipo": "AVISO", "t": "Prueba del chip pendiente",
             "d": "No se hizo la prueba de señal del chip: queda pendiente por validar qué proveedor tiene señal para el TP-Link con chip."})
    if X.porContratar:
        add({"id": "CONTRATAR", "tipo": "REC", "t": "Contratar internet antes de implementar",
             "d": "El cliente va a contratar el internet antes de implementar el punto de venta. Cuando esté instalado, solicitar una segunda visita para validar la conectividad (speedtest, router y red de impresoras).",
             "trabajo": "contratar e instalar el internet"})
    if X.chip == "NINGUNO":
        add({"id": "SAT", "tipo": "OBS", "t": "Sin señal de chip", "d": "Evaluar internet satelital y programar una segunda visita.",
             "trabajo": "internet satelital"})
    V01: Optional[str] = None
    sp: Optional[Obj] = None
    e1 = a.get("E1")
    if X.hasInt and X.testDone:
        if X.cableTest and e1 and e1.get("v") == "OK":
            d = e1.get("data") or {}
            best = max(num(d.get("d1")), num(d.get("d2")))
            pct = best / X.plan if X.plan else 0
            mp = max(num(d.get("pd")), num(d.get("pu")))
            sp = Obj(best=best, pct=pct, mp=mp, d=d)
            V01 = "CUMPLE" if pct >= 0.7 else "OBSERVADO"
            if V01 == "OBSERVADO":
                add({"id": "R67 · V01", "tipo": "OBS", "t": "El internet no llega a lo contratado",
                     "d": f"Mejor prueba por cable: {fmt(best)} Mbps = {jsround(pct * 100)} % de {fmt(X.plan)} Mbps (mínimo 70 %). Revisar con el proveedor."})
            if 85 <= best <= 95 and X.plan and X.plan > 100:
                add({"id": "R65", "tipo": "AVISO", "t": "Velocidad limitada a 100 Mbps",
                     "d": "Repite la prueba directo al router principal, con cable Cat6 y en un puerto RJ45 gigabit (10/100/1000) en el router y en la PC o laptop."})
            if mp > 300:
                add({"id": "R66 · V02", "tipo": "AVISO", "t": "La red se satura con carga",
                     "d": f"Ping de hasta {fmt(mp)} ms. En horas de mucho uso las comandas pueden demorar. Separar el WiFi de clientes (R32), PC de caja por cable (R11) y prioridad al punto de venta."})
        elif X.cableTest and e1 and e1.get("v") == "SKIP":
            V01 = "SIN VERIFICAR"
            add({"id": "V01", "tipo": "AVISO", "t": "Plan sin verificar", "d": "Se saltó la captura del speedtest. Queda pendiente en la minuta."})
        elif not X.cableTest:
            V01 = "SIN VERIFICAR"
            add({"id": "V01", "tipo": "AVISO", "t": "Plan sin verificar", "d": "No hay prueba por cable junto al router. No se penaliza."})
    for c in X.cajasInfo or []:
        if c.pcWifi:
            add({"id": "V03 · R11", "tipo": "OBS", "t": f"{c.nm}: PC por WiFi", "d": "Conectar la PC de caja por cable de red.",
                 "trabajo": "punto de red para la PC de caja"})
        if c.eq == "TABLET":
            add({"id": "TABLET", "tipo": "REC", "t": f"{c.nm}: Raspberry obligatorio",
                 "d": "El dispositivo que usan en caja es una tablet; las impresoras deben ser de red.", "eq": "kit Raspberry"})
        if c.temporal:
            add({"id": "R60", "tipo": "REC", "t": f"{c.nm}: PC temporal",
                 "d": "La PC no se queda en el local: Raspberry para el sistema de impresiones.", "eq": "kit Raspberry"})
        if (c.rasp or c.adq == "RASPBERRY") and (c.raspEnergia is False or c.raspPunto is False):
            f = " y ".join(x for x in ["punto de red" if c.raspPunto is False else None, "toma de energía" if c.raspEnergia is False else None] if x)
            via = ""
            if c.raspViaL:
                via = " (" + re.sub(r"^a(l)? ", lambda m: "junto a" + (m.group(1) or "") + " ", c.raspViaL.lower()) + ")"
            add({"id": "RASP_PTO", "tipo": "OBS", "t": f"{c.nm}: falta {f} para el Raspberry",
                 "d": f"Implementar {f} donde irá el Raspberry{via}{'' if c.rasp else ', antes de que el cliente lo compre e instale'}.",
                 "trabajo": f"{f} para el Raspberry"})
        if c.eq in ("SUNMI", "IMIN") and X.anterior:
            add({"id": "PROV", "tipo": "AVISO", "t": f"{c.nm}: {'Sunmi' if c.eq == 'SUNMI' else 'iMin'} de otro proveedor",
                 "d": "Si el equipo no es de Desarrollo de Negocios, no se puede usar porque pertenece a otro proveedor. Tomarlo en cuenta."})
        if c.eq in ("NO_SE", "OTRO"):
            add({"id": "P22", "tipo": "AVISO", "t": f"{c.nm}: equipo por confirmar",
                 "d": f"Equipo indicado: {c.eqL}. Confirmar con el cliente." if c.eq == "OTRO" else "Confirmar el equipo de caja con el cliente."})
    D = {
        "PC_BASICA": ("A_IMP_PC_BASICA", "PC básica con USB", "Pre-cuentas y comprobantes; sin controlador.", "laptop o PC básica"),
        "PC_CONTROLADOR": ("A_IMP_PC_CONTROLADOR", "Laptop o PC con controlador", "La impresora de caja es USB; no funciona con Raspberry.", "laptop o PC"),
        "RASPBERRY": ("A_IMP_RASPBERRY", "Kit Raspberry", "Controlador de impresiones; impresoras de red. Se cotiza con Desarrollo de Negocios.", "kit Raspberry"),
    }
    if X.decision and not (X.decision == "RASPBERRY" and any(c.eq == "TABLET" for c in X.cajasInfo or [])):
        q = D[X.decision]
        add({"id": q[0], "tipo": "REC", "t": q[1], "d": q[2], "eq": q[3]})
    rasp_in_play = X.decision == "RASPBERRY" or X.hasRasp or any(c.eq == "TABLET" or c.temporal or c.adq == "RASPBERRY" for c in X.cajasInfo or [])
    X.raspInPlay = rasp_in_play
    if rasp_in_play and X.printersDone:
        add({"id": "R57", "tipo": "REC", "t": "Raspberry junto al router",
             "d": f"Ubicarlo junto al router{' (' + X.routerUbic + ')' if X.routerUbic else ''} o switch, con cable corto, ventilado y lejos del calor y la grasa."})
    for p in X.printers or []:
        if p.estado == "FALLAS":
            add({"id": "IMP-AV", "tipo": "OBS", "t": f"IMP. {p.name} con fallas", "d": "Reparar o reemplazar la impresora.",
                 "eq": "impresora de red", "trabajo": f"reparar o reemplazar IMP. {p.name}"})
        if p.estado == "MANT":
            add({"id": "IMP-MT", "tipo": "REC", "t": f"IMP. {p.name}: mantenimiento", "d": "Darle mantenimiento a la impresora antes del inicio.",
                 "trabajo": f"mantenimiento de IMP. {p.name}"})
        if p.con == "NONE":
            add({"id": "IMP-NC", "tipo": "OBS", "t": f"IMP. {p.name} sin conexión",
                 "d": "No se indicó cómo se conecta ni aparece en el escáner de IP. Verificar la conexión."})
        if p.con == "USB" and p.usbTo == "PC" and not p.prep:
            add({"id": "R16", "tipo": "REC", "t": f"IMP. {p.name}: USB conectada a la PC o laptop",
                 "d": "Mantener la impresora USB conectada a la PC o laptop de caja con el controlador de impresiones: así imprime comprobantes y comandas sin cambiarla por una de red."})
        if p.con == "USB" and p.usbTo and p.usbTo != "PC":
            host = any((c.eq == "SI" and not c.temporal) or c.adq in ("LAPTOP", "PC") for c in X.cajasInfo or []) or X.decision in ("PC_BASICA", "PC_CONTROLADOR")
            add({"id": "USB", "tipo": "OBS", "t": f"IMP. {p.name}: USB {'sin conectar' if p.usbTo == 'NINGUNO' else 'conectada a ' + str(p.usbToL)}",
                 "d": "Una impresora USB solo se conecta a una PC o laptop; no a tablet, Raspberry, Sunmi, iMin, router ni repetidor. "
                      + ("Conectarla a la PC o laptop." if host else "Cambiar a impresora de red o adquirir una PC o laptop."),
                 "eq": "impresora de red", "trabajo": "impresora de red"})
        if p.prep and p.con and p.con not in ("RED", "NONE"):
            add({"id": "R51", "tipo": "OBS", "t": f"IMP. {p.name}: debe ser de red por cable",
                 "d": "Aún no tiene impresora." if p.con == "NO" else f"Hoy es {'USB' if p.con == 'USB' else 'WiFi'}.",
                 "eq": "impresora de red", "trabajo": "impresora de red"})
        if not p.prep and p.con == "NO":
            add({"id": "IMP", "tipo": "OBS", "t": f"IMP. {p.name}: falta impresora", "d": "Adquirir la impresora de caja.",
                 "eq": "impresora de caja", "trabajo": "impresora de caja"})
        if p.con in ("RED", "WIFI") and p.ip and not p.ip.startswith(X.seg + "."):
            add({"id": "R55 · V04", "tipo": "OBS", "t": f"IMP. {p.name}: fuera del segmento del router",
                 "d": (f"IP {p.ip}; el router y las otras impresoras están en {X.seg}.x. Configurar la impresora en la misma red y segmento que las otras impresoras antes de iniciar con el punto de venta."
                       if X.anterior else f"IP {p.ip}; el router está en {X.seg}.x. Cambiar la IP de la impresora.")})
    pend = [] if X.simple else [k for k in a if re.match(r"^E", k) and a[k] and a[k].get("v") == "SKIP"]
    if pend:
        add({"id": "EVID", "tipo": "AVISO", "t": f"Evidencias pendientes ({len(pend)})",
             "d": "Sin lectura: " + ", ".join(k.replace("#", " · ") for k in pend) + ". Se completan en la vista previa o desde el chat."})
    if X.switchN:
        add({"id": "SWITCH", "tipo": "OBS", "t": "Faltan puertos en el router",
             "d": f"{X.eqCable} equipos por cable y {fmt(X.libres)} puertos libres: Switch x{X.switchN} y puntos de red.",
             "eq": f"switch de {X.switchN} puertos", "trabajo": "switch y puntos de red"})
    if X.tomas == "NO" and re.search(r"supresor|picos", X.apreciacion or "", re.I):
        add({"id": "SUPRESOR", "tipo": "REC", "t": "Supresor de picos", "d": "Instalar un supresor de picos (recomendado por el técnico).",
             "eq": "supresor de picos"})
    if X.tomas == "NO":
        add({"id": "ENERGIA", "tipo": "OBS", "t": "Faltan tomas de energía",
             "d": X.energiaTxt + (" Apreciación del técnico: " + X.apreciacion if X.apreciacion else ""),
             "trabajo": "tomas de energía" + (" para " + ", ".join(X.sinEnergia) if X.sinEnergia else "")})
    if X.cableElec:
        add({"id": "R_ELEC", "tipo": "REC", "t": "Cable cerca de electrodomésticos",
             "d": "Un cable de red pasa cerca de electrodomésticos (licuadoras, congeladoras u otros). Aislarlo de la estática y la interferencia: canaleta o tubo, separación del equipo y del cable de energía, o cable apantallado (FTP).",
             "eq": "canaleta o cable FTP", "trabajo": "aislar el cableado de red"})
    if X.rub in ("PARRILLA", "POLLERIA"):
        add({"id": "R10", "tipo": "REC", "t": "Calor y grasa",
             "d": f"Router, Raspberry e impresoras lejos del calor y la grasa de {'la parrilla' if X.rub == 'PARRILLA' else 'las brasas'}. También se pueden cubrir los equipos para evitar que se llenen de grasa o tengan sobretemperatura."})
    if X.rub == "RETAIL" and X.printersDone:
        add({"id": "R63", "tipo": "REC", "t": "Periféricos por caja",
             "d": "Probar los periféricos conectados a cada equipo de caja (balanza, escáner, gaveta, POS de pago); impresora USB con PC (R42)."})
    if X.sinSenal:
        add({"id": "R19", "tipo": "OBS", "t": "Zonas sin buena señal WiFi",
             "d": f"{', '.join(X.sinSenal)}.{' Se instalará: ' + X.solWifi.lower() + '.' if X.solWifi else ''}",
             "eq": X.solWifi.lower() if X.solWifi else "repetidor o access point", "trabajo": "repetidor o access point"})
    con: Optional[Obj] = None
    if X.sinInt:
        con = Obj(pct=0, steps=["Sin internet → 0 %"])
    elif X.porContratar:
        con = Obj(pct=0, steps=["Internet por contratar → 0 % hasta validarlo en la segunda visita"])
    elif X.plan:
        bw = bw_need(X, a)
        X.bw = bw
        steps: List[str] = []
        chip = X.con == "CHIP"
        p16, p17 = a.get("P16"), a.get("P17")
        crit = [
            Obj(k="Velocidad real frente a la contratada", w=30, r=min(1, sp.pct / 0.7) if sp else None,
                d=(f"{fmt(sp.best)} Mbps = {jsround(sp.pct * 100)} % de {fmt(X.plan)} Mbps (se cumple desde el 70 %, Ley 31207)" if sp else "sin prueba por cable")),
            Obj(k="Cobertura de la demanda", w=30, r=min(1, X.plan / bw.rec) if bw.rec else None,
                d=f"{fmt(X.plan)} Mbps frente a {fmt(bw.rec)} Mbps recomendados (150 × {bw.zonas} zona{'s' if bw.zonas != 1 else ''} de atención)"),
            Obj(k="Mínimo por equipo", w=20, r=1 if (chip or not bw.min) else min(1, X.plan / bw.min),
                d="internet por chip: cubre los equipos" if chip else f"{fmt(X.plan)} Mbps frente a {fmt(bw.min)} Mbps mínimos de los equipos"),
            Obj(k="Estabilidad con carga", w=10, r=(1 if sp.mp <= 300 else 0) if sp else None,
                d=f"ping con carga de {fmt(sp.mp)} ms (máximo 300)" if sp else "sin prueba por cable"),
            Obj(k="Continuidad del servicio", w=10,
                r=1 if (p16 and p16.get("v") == "SI") else ((1 if p17.get("v") == "NO" else 0) if p17 else None),
                d=("tiene internet de respaldo" if (p16 and p16.get("v") == "SI")
                   else (("sin caídas de internet" if p17.get("v") == "NO" else "tiene caídas y no tiene respaldo") if p17
                         else "no se preguntó (según el estado del local)"))),
        ]
        ap = [c for c in crit if c.r is not None]
        tot = jsum(c.w for c in ap)
        pct = jsround(100 * jsum(c.w * c.r for c in ap) / tot) if tot else None
        for c in crit:
            steps.append(f"{c.k}: no aplica ({c.d})" if c.r is None else f"{c.k}: {c.d} → {fmt(jsround(c.w * c.r * 10) / 10)} de {c.w}")
        con = Obj(pct=pct, steps=steps, crit=crit)
        if X.con != "CHIP" and X.plan < bw.min:
            add({"id": "R54", "tipo": "OBS", "t": "El plan no cubre el mínimo de los equipos",
                 "d": f"Mínimo por equipo: {fmt(bw.min)} Mbps ({', '.join(bw.det)}). Subir el plan."})
        elif X.plan < bw.rec:
            add({"id": "R54", "tipo": "REC", "t": f"Plan recomendado: {fmt(bw.rec)} Mbps",
                 "d": f"~150 Mbps por zona de atención × {bw.zonas} zona(s). Hoy tiene {fmt(X.plan)} Mbps: cubre el mínimo por equipo ({fmt(bw.min)} Mbps), pero se recomienda subir el plan a {fmt(bw.rec)} Mbps."})
    wired = X.hasInt and X.con != "CHIP"
    if wired and X.camGrab == "DVR":
        add({"id": "CAM_DVR", "tipo": "AVISO", "t": "Cámaras por DVR",
             "d": "En el escáner de IP las cámaras aparecen como un DVR con una sola IP (por ejemplo Hikvision). No se pide cambiar el plan por las cámaras."})
    if wired and X.camGrab == "NVR" and X.plan and X.plan < 1000:
        n = f"{fmt(X.camIps)} IP de cámaras" if X.camIps else "varias IP de cámaras"
        if X.plan < 500:
            add({"id": "CAM_NVR", "tipo": "OBS", "t": "Cámaras por NVR: independizar la red",
                 "d": f"En el escáner de IP aparece un NVR con {n}. Con un plan de {fmt(X.plan)} Mbps (menor a 500 Mbps), independizar la red de internet de las cámaras de la de los equipos de impresión, o ampliar el plan de internet a 1000 Mbps.",
                 "eq": "red independiente para las cámaras o plan de 1000 Mbps", "trabajo": "independizar la red de las cámaras"})
        else:
            add({"id": "CAM_NVR", "tipo": "REC", "t": "Cámaras por NVR: ampliar el plan",
                 "d": f"En el escáner de IP aparece un NVR con {n}. Ampliar el plan de internet de {fmt(X.plan)} Mbps a 1000 Mbps.",
                 "eq": "plan de internet de 1000 Mbps"})
    if X.camaras and not (wired and X.camGrab in ("DVR", "NVR")):
        n = f"{fmt(X.nCam)} cámara{'s' if X.nCam > 1 else ''}" if X.nCam else "Cámaras"
        if X.hasInt:
            add({"id": "R53", "tipo": "OBS" if (X.plan and X.plan < 1000) else "REC", "t": f"{n} en la red",
                 "d": "Si van a la misma red: subir el plan de internet a uno superior que soporte las cámaras (sugerido 1000 Mbps), o independizar la red de internet de las cámaras de la de los equipos de impresión."})
        else:
            add({"id": "R53", "tipo": "REC", "t": f"{n} en el TP-Link con chip",
                 "d": "El chip debe tener un plan superior que soporte las cámaras, o independizar la red de las cámaras de la de los equipos de impresión."})
    if X.obra and any(i.eq for i in it):
        add({"id": "OBRA_DN", "tipo": "REC", "t": "Cotizar los equipos por implementar",
             "d": "Como el local está en obra, se recomienda ir cotizando los equipos por implementar y coordinando con el área de Desarrollo de Negocios."})
    has_obs = any(i.tipo == "OBS" for i in it)
    p16 = a.get("P16")
    no_apto = V01 == "OBSERVADO" and p16 and p16.get("v") == "NO"
    estado = "NO APTO" if no_apto else "OBSERVADO" if has_obs else "APTO"
    return Obj(it=it, con=con, V01=V01, sp=sp, estado=estado)


def gen_pasos(X: Obj, R: Obj, a: Dict[str, Any]) -> List[Dict[str, str]]:
    eqs = uniq([i.eq for i in R.it if i.eq])
    trab = uniq([i.trabajo for i in R.it if i.trabajo])
    P: List[Dict[str, str]] = [{"p": "ID", "t": "Compartir la minuta de visita técnica."}, {"p": "Cliente", "t": "Confirmar la recepción de la minuta."}]
    if eqs:
        P.append({"p": "Cliente", "t": f"Solicitar la cotización de los equipos recomendados: {', '.join(eqs)}."})
    idv = [e for e in eqs if re.search(r"raspberry|sunmi", e, re.I)]
    if idv:
        P.append({"p": "ID", "t": f"Enviar la cotización de {' y '.join(idv)}. Raspberry y Sunmi se cotizan con Desarrollo de Negocios."})
    P.append({"p": "Cliente", "t": "Enviar el documento con la carta (maestra de productos) y la información del negocio: serie de facturación, IGV y usuarios."})
    if trab:
        P.append({"p": "Cliente", "t": f"Implementar {'; '.join(trab)} y avisar a ID cuando estén listos."})
        P.append({"p": "ID", "t": f"Realizar una segunda visita técnica cuando estén implementados: {'; '.join(trab)}."})
    f = a.get("P50b", {}).get("v") if a.get("P50b") else None
    if f:
        P.append({"p": "ID", "t": f"Dar inicio con IDPos el {fmt_date(f)}."})
    if X.decision == "RASPBERRY" or X.hasRasp:
        ctrl: Optional[str] = "Raspberry"
    elif X.decision:
        ctrl = "PC o laptop"
    elif any(c.adq for c in X.cajasInfo or []):
        first = next(c for c in X.cajasInfo if c.adq)
        ctrl = str(first.adqL or "equipo").lower()
    else:
        ctrl = None
    if ctrl:
        P.append({"p": "ID", "t": f"Configurar el sistema de impresiones en {ctrl}."})
    if X.estadoV in ("EN_OBRA", "POR_INAUGURAR"):
        P.append({"p": "ID", "t": "Dar seguimiento a la instalación hasta la fecha de inicio."})
    return P
