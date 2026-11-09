"""Reglas de la visita (port de `evaluate()`, `bwNeed()`, `rate()` y `genPasos()` del simulador)."""
import re
from typing import Any, Dict, List, Optional

from app.chat.sim.flow import CAT, PUNTO_ALERT, PUNTO_TRABAJO, PUNTO_TXT, fmt_date, sys_imp_n
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
    if X.rub and X.rub != "RETAIL" and (not X.mozosQ or (p09c and p09c.get("v") != "NO")):
        add(len([z for z in X.zonas if z["canal"] == "Mesa"]), 10, "tablet o celular de mozo por WiFi")
    zonas = len(uniq([z["z"] for z in X.zonas]))
    return Obj(min=total[0], det=det, zonas=zonas, rec=150 * zonas)


def rate(m: Dict[str, Any]) -> Dict[str, str]:
    s, p = m.get("dbm"), m.get("ping")
    rk = ["Excelente", "Buena", "Regular", "Mala"]
    rs = 0 if s >= -60 else 1 if s >= -67 else 2 if s >= -75 else 3
    rp = 0 if p < 50 else 1 if p <= 100 else 2 if p <= 200 else 3
    return {"cal": rk[max(rs, rp)], "rs": rk[rs], "rp": rk[rp]}


# Reglas de la empresa (Preguntas y reglas del administrador): [id, nombre, tipo, activa, texto, cuándo aplica]
DEFAULT_RULES: List[List[Any]] = [
    ["SISIMP", "Sistema de impresiones", "Aviso", True, "", ""],
    ["OBRA", "Segunda visita técnica", "Recomendación", True, "Recomienda una segunda visita técnica cuando el local esté terminado.", "El local está en obra o remodelación"],
    ["SIN_INT", "Sin internet", "Observación", True, "Observación: sin internet no se puede iniciar la operación.", "El local no tiene internet"],
    ["CONTRATAR", "Contratar internet antes de implementar", "Recomendación", True, "Recomienda contratar internet antes de implementar.", "No hay internet contratado"],
    ["R56", "TP-Link con entrada de chip", "Recomendación", True, "Recomienda usar el chip como respaldo de internet.", "El router es TP-Link con entrada de chip"],
    ["CHIP_PEND", "Prueba del chip pendiente", "Aviso", True, "Aviso: la prueba del chip queda pendiente.", "Hay chip pero no se probó"],
    ["R67", "El internet no llega a lo contratado", "Observación", True, "Observación: el internet no llega a lo contratado.", "El test de velocidad da menos de lo contratado"],
    ["R60", "PC temporal", "Recomendación", False, "Recomienda reemplazarla por un equipo definitivo.", "La PC de caja es temporal"],
    ["R_RESERVA_IP", "Reservar las IP de las impresoras", "Recomendación", True, "Pedir al proveedor de internet que reserve en el router las IP de las impresoras.", "Hay varios equipos conectados o 3 o más impresoras por red"],
    ["R_UPS", "UPS para los equipos de red", "Recomendación", True, "Conectar el router, el switch y el equipo de caja a un UPS.", "El cliente indica intermitencias de energía"],
    ["R_ROUTER_ENC", "Router en un espacio cerrado", "Aviso", True, "El local es apto, pero el equipo técnico debe darle seguimiento para que no tenga intermitencias de internet.",
     "El router está en un cuarto pequeño con puertas cerca al piso o dentro de un mueble cerrado con puertas (se ve en la foto o se indica)"],
]
ENERG19 = re.compile(r"intermitencia(s)? de (la )?(energ|luz|corriente)|cortes? de (luz|energ)|se va la luz|bajones? de (luz|energ|tension)|apagones?", re.I)
ENC29 = re.compile(r"cuarto (peque|chico|reducido)|cl[oó]set|armario|mueble cerrado|gabinete cerrado|dentro (de |del )?(un |una |el |la )?(mueble|gabinete|armario|cl[oó]set)|caja cerrada|con puertas", re.I)


REUB45 = ("Sacar el router del mueble o del espacio cerrado y fijarlo a 1–1.5 m del suelo, en una pared despejada y lo más central posible del local, "
          "sin objetos delante. Si la fibra no alcanza, dejar el router en su lugar a esa altura y conectar por cable un equipo WiFi (Deco o repetidor) "
          "a la misma altura en el área de atención.")
SEG45 = ("Dar seguimiento al router: si se presentan intermitencias o lentitud en los puntos de red, revisar su ubicación y, si se confirma que es "
         "necesario, indicar al cliente que lo reubique según la recomendación.")


def bott45(R: Obj) -> Optional[Dict[str, Any]]:
    """Cuello de botella con carga: el ping sube mucho con carga (80–300 ms y 4 veces el ping sin carga)."""
    if not R or not R.sp or not R.sp.get("d"):
        return None
    p = num(R.sp["d"].get("p")) or 0
    mp = R.sp.get("mp") or 0
    return {"p": p, "mp": mp} if (80 <= mp <= 300 and (not p or mp >= p * 4)) else None


def _key_of(i: Obj) -> str:
    return f"{i.id}|{i.t}"


def evaluate(X: Obj, a: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Obj:
    """Reglas de la visita. `ctx` (opcional) trae lo de la minuta y de la empresa:
    obs (observación del técnico), res (observaciones resueltas en la visita), rules (reglas de la empresa),
    rdel (reglas eliminadas), routerEncF (router en espacio cerrado indicado al actualizar) y sysImp."""
    ctx = ctx or {}
    if ctx.get("routerEncF") and not X.routerEnc:
        X.routerEnc = "Dentro de un mueble cerrado con puertas" if ctx["routerEncF"] == "MUEBLE" else "En un cuarto pequeño con puertas (cerca al piso)"
        X.routerInst = X.routerInst or X.routerEnc
    R = _evaluate_base(X, a, ctx)
    it = R.it
    # observaciones resueltas en la visita: dejan de contar
    res = ctx.get("res") or []
    keys = {r.get("key") for r in res}
    R.res = list(res)
    if keys:
        R.it = it = [i for i in it if not (i.tipo == "OBS" and _key_of(i) in keys)]
        if R.estado != "NO APTO":
            R.estado = "OBSERVADO" if any(i.tipo == "OBS" for i in it) else "APTO"
    # reserva de IP de las impresoras y UPS
    pr_ip = [p for p in (X.printers or []) if p.ip and p.con in ("RED", "WIFI")]
    e1d = a.get("E1d")
    eqs = int(num((e1d.get("data") or {}).get("equipos")) or 0) if (e1d and e1d.get("v") == "OK" and e1d.get("data")) else 0
    if pr_ip and (eqs >= 5 or len(pr_ip) >= 3) and not any(i.id == "R_RESERVA_IP" for i in it):
        it.append(Obj(id="R_RESERVA_IP", tipo="REC", t="Reservar las IP de las impresoras",
                      d=f"Hay varios equipos conectados al router{f' ({eqs} en el escáner de IP)' if eqs else ''}. Contactar a su proveedor de internet para que, con autorización del cliente, reserve en el router las IP de las impresoras ({', '.join(p.ip for p in pr_ip)}) y no cambien."))
    txt = " ".join([ctx.get("obs") or "", X.apreciacion or ""])
    if ENERG19.search(txt) and not any(i.id == "R_UPS" for i in it):
        it.append(Obj(id="R_UPS", tipo="REC", t="UPS para los equipos de red y de impresión",
                      d="El cliente indicó intermitencias de energía. Conectar a un UPS el router, el switch y el equipo con el sistema de impresiones para que la operación no se corte.", eq="UPS"))
    # evidencias pendientes (el AnyDesk no cuenta) e iMin o Sunmi sin impresora integrada
    for i in it:
        if i.id == "EVID":
            m = re.search(r"Sin lectura: (.*)\. Se completan", i.d or "")
            if m:
                L = [x for x in m.group(1).split(", ") if not x.startswith("E7 · ")]
                i.d = "Sin lectura: " + ", ".join(L) + ". Se completan en la vista previa o desde el chat."
                i.t = f"Evidencias pendientes ({len(L)})"
                i._empty = not L
    R.it = it = [i for i in it if not i._empty]
    for i in it:
        i.pop("_empty", None)
    for c in X.cajasInfo or []:
        if c.impInt is False:
            it.append(Obj(id="IMIN_SIN_IMP", tipo="REC", t=f"{c.nm}: {'Sunmi' if c.eq == 'SUNMI' else 'iMin'} sin impresora integrada",
                          d="Es solo pantalla: se necesita una impresora de caja (de red, o USB conectada a una PC o laptop con el sistema de impresiones).", eq="impresora de caja"))
    # reglas desactivadas o eliminadas por la empresa; las editadas usan su texto
    rules = ctx.get("rules") or DEFAULT_RULES
    off = {r[0] for r in rules if not r[3]} | set(ctx.get("rdel") or [])
    R.it = it = [i for i in it if i.id not in off]
    for r in rules:
        if len(r) > 6 and r[6]:
            for i in it:
                if i.id == r[0]:
                    i.t = r[1]
                    if r[4]:
                        i.d = r[4]
    # router en un espacio cerrado: apto, con seguimiento
    rl = next((r for r in rules if r[0] == "R_ROUTER_ENC"), None)
    if not (rl and not rl[3]):
        t2 = " ".join([X.routerUbic or "", ctx.get("obs") or "", X.apreciacion or ""])
        enc = X.routerEnc
        if not enc and ENC29.search(t2) and re.search(r"router|m[oó]dem", t2 + " router", re.I):
            enc = ENC29.search(t2).group(0)
        if enc and not any(i.id == "R_ROUTER_ENC" for i in it):
            dd = enc[0].lower() + enc[1:] if re.match(r"^dentro|^en ", enc, re.I) else "en " + enc.lower()
            it.append(Obj(id="R_ROUTER_ENC", tipo="AVISO", t="Router en un espacio cerrado: dar seguimiento",
                          d=f"El router está {dd}. {'Además, por' if R.estado == 'NO APTO' else 'El local es apto, pero por'} esta observación el equipo técnico debe darle seguimiento para que no tenga intermitencias de internet (el espacio cerrado y las puertas bajan la señal y calientan el equipo)."))
    # la regla del router: recomendación breve (el detalle va en Internet)
    for i in it:
        if i.id == "R_ROUTER_ENC":
            i.t, i.d, i.tipo = "Reubicación del router", REUB45, "AVISO"
    # puertos del switch: calidad del punto de red y rotulado
    S = X.sw46
    if S:
        for r in S.map:
            if r.port and (r.loss > 2 or r.lat > 50):
                it.append(Obj(id="R_SW46Q_" + r.name, tipo="OBS", t=f"Punto de red de IMP. {r.name} (puerto {r.port})",
                              d=f"{r.loss} % de pérdida y {r.lat} ms dentro de la red local: revisar el cableado del punto y su extremo en el switch."))
        if S.rot and S.rot in ("No", "Parcial"):
            it.append(Obj(id="R_SW46R", tipo="REC", t="Rotular los puntos de red en el switch",
                          d="Colocar en cada puerto del switch la etiqueta con el nombre de la impresora o la zona, igual que en la topología."))
    R.it = it
    return R


def _evaluate_base(X: Obj, a: Dict[str, Any], ctx: Dict[str, Any]) -> Obj:
    it: List[Obj] = []
    sysn = sys_imp_n(ctx)

    def add(o: Dict[str, Any]) -> None:
        it.append(Obj(o))

    if X.sunmi:
        add({"id": "A_SUNMI", "tipo": "REC", "t": "Sunmi con chip", "d": "La comanda sale solo en caja.", "eq": "Sunmi con chip"})
    p09c = a.get("P09c") or {}
    if X.mozosQ and (p09c.get("v") == "IMIN_MOVIL" or p09c.get("pc52")):
        add({"id": "R_IMIN_MOVIL", "tipo": "REC", "t": "iMin móvil para los mozos",
             "d": ("Los mozos usarán iMin móvil: toma el pedido e imprime en el mismo equipo. Debe tener buena señal WiFi en las zonas de atención."
                   if p09c.get("v") == "IMIN_MOVIL" else
                   "Aún no se define con qué equipo tomarán pedidos los mozos. Sugerir iMin móvil: toma el pedido e imprime en el mismo equipo. Se cotiza con Desarrollo de Negocios."),
             "eq": "iMin móvil"})
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
            if not X.plan:
                V01 = None
                add({"id": "PLAN_PC", "tipo": "AVISO", "t": "Plan de internet por confirmar",
                     "d": f"Mejor prueba por cable: {fmt(best)} Mbps. Falta el plan contratado para compararla (se cumple desde el 70 %, Ley 31207)."})
            else:
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
        if c.pcWifi and c.sysImp is not False:
            add({"id": "V03 · R11", "tipo": "OBS", "t": f"{c.nm}: PC con {sysn} por WiFi",
                 "d": f"Es el equipo con el sistema de impresiones ({sysn}): conectarlo por cable de red.",
                 "trabajo": "punto de red para la PC de caja"})
        elif c.pcWifi:
            add({"id": "V03b", "tipo": "REC", "t": f"{c.nm}: PC por WiFi",
                 "d": f"No tiene el sistema de impresiones ({sysn}), así que no impide iniciar la operación. Si se puede, conectarla por cable de red."})
        if c.rasp and c.raspCable is False:
            add({"id": "RASP_WIFI", "tipo": "OBS", "t": f"{c.nm}: Raspberry con {sysn} por WiFi",
                 "d": f"El Raspberry tiene el sistema de impresiones ({sysn}): conectarlo por cable de red.",
                 "trabajo": "punto de red para el Raspberry"})
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
        if p.punto in PUNTO_TRABAJO:
            add({"id": "IMP-PTO", "tipo": "OBS", "t": f"IMP. {p.name}: punto de red {PUNTO_TXT[p.punto]}",
                 "d": f"{PUNTO_ALERT[p.punto][0].upper()}{PUNTO_ALERT[p.punto][1:]}", "trabajo": f"{PUNTO_TRABAJO[p.punto]} para IMP. {p.name}"})
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
            lugar = f"de {p.name}" if p.extra else "de caja"
            add({"id": "IMP", "tipo": "OBS", "t": f"IMP. {p.name}: falta impresora", "d": f"Adquirir la impresora {lugar}.",
                 "eq": f"impresora {lugar}", "trabajo": f"impresora {lugar}"})
        if p.con in ("RED", "WIFI") and p.ip and not p.ip.startswith(X.seg + "."):
            add({"id": "R55 · V04", "tipo": "OBS", "t": f"IMP. {p.name}: fuera del segmento del router",
                 "d": (f"IP {p.ip}; el router y las otras impresoras están en {X.seg}.x. Configurar la impresora en la misma red y segmento que las otras impresoras antes de iniciar con el punto de venta."
                       if X.anterior else f"IP {p.ip}; el router está en {X.seg}.x. Cambiar la IP de la impresora.")})
    # En obra, la foto saltada de una impresora que el cliente aún no tiene no queda pendiente (0.0.19 · C3).
    sin_imp = {"E5a#" + p.name for p in X.printers or [] if X.obra and p.con == "NO"}
    pend = [] if X.simple else [k for k in a if re.match(r"^E", k) and a[k] and a[k].get("v") == "SKIP" and k not in sin_imp]
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
             "d": X.energiaTxt,
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
    pc = [t for k, t in (("P01b", "el RUC"), ("P04", "el nombre y cargo del encargado del local"))
          if (a.get(k) or {}).get("label") == "Por confirmar"]
    if pc:
        P.append({"p": "Cliente", "t": f"Enviar {' y '.join(pc)} para completar la minuta."})
    from app.chat.sim.flow import TEMA
    pend = [TEMA[k.split("#")[0]] + (f" ({k.split('#')[1]})" if "#" in k else "") for k, e in a.items()
            if k.split("#")[0] in TEMA and (e or {}).get("pc52")]
    if pend:
        P.append({"p": "Cliente", "t": f"Confirmar con ID: {'; '.join(pend)}."})
    return P
