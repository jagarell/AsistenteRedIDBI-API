"""Documento estructurado de la minuta técnica (lo que el gateway convierte a PDF).

Estructura calcada de la minuta de ejemplo del cliente: KPIs, secciones 1-8
con tablas Campo | Valor | Fuente (filas "Pendiente" en ámbar), tabla de
impresoras, validación técnica automática, recomendaciones, mapa de red,
resumen ejecutivo y anexos. Todo se arma a partir del `state` del flujo; nada
se inventa: lo que no se capturó queda como pendiente.
"""
import base64
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.chat import checks
from app.chat.checks import Rule
from app.chat.flow_engine import FLOW, Session
from app.chat.map_render import render_topology_png
from app.chat.topology import build_state_topology

SRC_CHAT = "Chat del técnico"


class Row(BaseModel):
    label: str
    value: str = ""
    source: str = ""
    pending: bool = False
    pendingNote: str = ""
    # "image" si el dato salió de una evidencia leída por IA, "chat" si lo
    # respondió el técnico — alimenta los KPIs de la cabecera.
    origin: str = "chat"


class Section(BaseModel):
    number: int
    title: str
    rows: List[Row]


class PrinterRow(BaseModel):
    nombre: str
    ubicacion: str
    modelo: str
    modeloPending: bool = False
    ip: str
    red: str
    redOk: bool = False


class AnnexItem(BaseModel):
    code: str
    scope: str
    title: str
    lines: List[str]


class PendingItem(BaseModel):
    node: str
    question: str
    type: str
    field: str


class MinutaDocument(BaseModel):
    title: str = "MINUTA TÉCNICA DE RED"
    subtitle: str
    intro: str
    date: str
    technician: str
    kpis: Dict[str, int]
    sections: List[Section]
    printers: List[PrinterRow]
    printersSource: str
    rules: List[Rule]
    recommendations: List[str]
    mapPngBase64: str
    mapCaption: str
    finalStatus: str
    executiveSummary: str
    annexA: List[AnnexItem]
    annexB: List[PendingItem]
    actionsId: List[str]
    actionsClient: List[str]


def _v(session: Session, value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, list):
        return ", ".join(session.label_of(x) for x in value)
    if value in ("SI", "NO"):
        return "Sí" if value == "SI" else "No"
    return session.label_of(value) if isinstance(value, str) else str(value)


def _row(label: str, value: Any, source: str, *, ask: Optional[str] = None, origin: str = "chat",
         session: Optional[Session] = None) -> Row:
    text = _v(session, value) if session else (str(value) if value not in (None, "") else "")
    if not text:
        return Row(label=label, pending=True, pendingNote=ask or "no se capturó", origin=origin)
    return Row(label=label, value=text, source=source, origin=origin)


def _city(address: str) -> str:
    parts = [p.strip() for p in address.split(",") if p.strip()]
    return parts[-1] if len(parts) > 1 else ""


def build_minuta_document(state: Dict[str, Any]) -> MinutaDocument:
    s = Session(state)
    a = state["answers"]
    ans = lambda nid, scope="": checks.answer(state, nid, scope)  # noqa: E731
    e1, e3 = checks.first_extracted(state, "E1"), checks.first_extracted(state, "E3")
    cajas = checks.cajas(state)
    printers = checks.printers_detail(state)
    devices = checks.scanner_devices(state)

    # ---- 1. Datos generales ------------------------------------------------
    address = str(ans("P03") or "")
    sec1 = Section(number=1, title="Datos generales del cliente", rows=[
        _row("Nombre del cliente", ans("P01"), f"{SRC_CHAT} (P01)", session=s),
        _row("Razón social", None, "", ask="se completa al editar la minuta"),
        _row("RUC", None, "", ask="se completa al editar la minuta"),
        _row("Nombre del local", ans("P02"), f"{SRC_CHAT} (P02)", session=s),
        _row("Dirección", address, f"{SRC_CHAT} (P03)", session=s),
        _row("Ciudad", _city(address), "Derivado de la dirección", ask="no se pudo derivar de la dirección",
             session=s),
        _row("Fecha de evaluación", ans("P06"), f"{SRC_CHAT} (P06)", session=s),
        _row("Responsable", ans("P04"), f"{SRC_CHAT} (P04)", session=s),
        _row("Teléfono", ans("P05"), f"{SRC_CHAT} (P05)", session=s),
        _row("Correo", None, "", ask="se completa al editar la minuta"),
    ])

    # ---- 2. Negocio ----------------------------------------------------------
    areas = ans("P11") or []
    sec2 = Section(number=2, title="Información del negocio", rows=[
        _row("Tipo de negocio", ans("P09"), f"{SRC_CHAT} (P09)", session=s),
        _row("Cantidad de pisos", ans("P10"), f"{SRC_CHAT} (P10)", session=s),
        _row("Cantidad de cajas", ans("P12"), f"{SRC_CHAT} (P12)", session=s),
        _row("Áreas del local", areas, f"{SRC_CHAT} (P11)", session=s),
    ])
    if int(ans("P10") or 1) > 1:
        by_floor: Dict[int, List[str]] = {}
        for i, ar in enumerate(areas, start=1):
            fl = a.get(f"P11a#L_PISOS:{i}")
            if fl:
                by_floor.setdefault(int(fl), []).append(s.label_of(ar))
        sec2.rows.append(_row("Áreas por piso", "; ".join(f"Piso {f}: {', '.join(v)}" for f, v in sorted(by_floor.items())),
                              f"{SRC_CHAT} (P11a)", session=s))

    # ---- 3. Internet -----------------------------------------------------------
    measured = ""
    if e1.get("bajadaMbps") is not None:
        measured = f"{e1['bajadaMbps']:g} Mbps de bajada"
        if e1.get("subidaMbps") is not None:
            measured += f" · {e1['subidaMbps']:g} Mbps de subida"
        if e1.get("pingMs") is not None:
            measured += f" · ping {e1['pingMs']:g} ms"
        if e1.get("latenciaBajadaMs") is not None and e1.get("latenciaSubidaMs") is not None:
            measured += f" ({e1['latenciaBajadaMs']:g} y {e1['latenciaSubidaMs']:g} ms con carga)"
    seg = ""
    e4 = cajas[0]["ipconfig"] if cajas else {}
    if e4.get("puertaEnlace"):
        seg = f"{'.'.join(e4['puertaEnlace'].split('.')[:3])}.0/24 · gateway {e4['puertaEnlace']}"
    sec3 = Section(number=3, title="Información de internet", rows=[
        _row("Proveedor de internet", ans("P13"), f"{SRC_CHAT} (P13)", session=s),
        _row("Velocidad contratada", f"{ans('P15')} Mbps" if ans("P15") else "", f"{SRC_CHAT} (P15)", session=s),
        _row("Velocidad medida", measured, "Captura del speedtest (E1)", origin="image",
             ask="falta una captura legible del speedtest", session=s),
        _row("Tipo de conexión", ans("P14"), f"{SRC_CHAT} (P14)", session=s),
        _row("Línea de respaldo", ans("P16"), f"{SRC_CHAT} (P16)", session=s),
        _row("Caídas en el último mes", ans("P17"), f"{SRC_CHAT} (P17)", session=s),
        _row("Ubicación del router", ans("P18"), f"{SRC_CHAT} (P18)", session=s),
        _row("Segmento y gateway", seg, "ipconfig (E4)", origin="image",
             ask="falta la captura de ipconfig", session=s),
    ])

    # ---- 4. Equipamiento de red --------------------------------------------------
    router = " ".join(x for x in (e3.get("marca"), e3.get("modelo")) if x)
    if router:
        extra = [f"MAC {e3['mac']}" if e3.get("mac") else None, f"SN {e3['numeroSerie']}" if e3.get("numeroSerie") else None]
        router = " · ".join([router] + [x for x in extra if x])
    sec4 = Section(number=4, title="Equipamiento de red", rows=[
        _row("Router (marca/modelo)", router, "Etiqueta del router (E3)", origin="image",
             ask="la etiqueta no se leyó con claridad", session=s),
        _row("Cantidad de puertos LAN", None, "", ask="foto del panel trasero del router"),
        _row("Switch (marca/modelo)", None, "", ask="¿hay switch? foto de su etiqueta"),
        _row("Número de puertos del switch", None, "", ask="depende de la respuesta anterior"),
        _row("Access Point / Repetidor", "Sí, hay access points o repetidores" if ans("P45") == "SI"
             else "No hay" if ans("P45") == "NO" else "", f"{SRC_CHAT} (P45)", session=s),
        _row("Zonas sin señal WiFi", ans("P46"), f"{SRC_CHAT} (P46)", session=s),
        _row("Cámaras en la red", ans("P47"), f"{SRC_CHAT} (P47)", session=s),
    ])

    # ---- 5. Infraestructura ----------------------------------------------------------
    cabling = []
    if ans("P38"):
        cabling.append("Los puntos de red llegan a todas las áreas." if ans("P38") == "SI"
                       else f"Sin punto de red en: {_v(s, ans('P38a'))}.")
    if ans("P39"):
        cabling.append(f"Cable {_v(s, ans('P39'))}.")
    if ans("P39a"):
        cabling.append(f"Entre pisos: {_v(s, ans('P39a'))}.")
    if ans("P40"):
        cabling.append(f"Gabinete: {_v(s, ans('P40')).lower()}.")
    if ans("P41") == "SI":
        cabling.append("Hay equipos expuestos a calor o grasa.")
    e6 = checks.first_extracted(state, "E6")
    if e6.get("observaciones"):
        cabling.append(str(e6["observaciones"]))
    sec5 = Section(number=5, title="Infraestructura de red", rows=[
        _row("Puntos de red existentes", ans("P37"), f"{SRC_CHAT} (P37)", session=s),
        _row("Observaciones de cableado", " ".join(cabling), f"{SRC_CHAT} (P38-P41) + fotos (E6)", session=s),
    ])

    # ---- 6. Equipos POS ------------------------------------------------------------------
    pos_rows: List[Row] = []
    for c in cajas:
        label = f"PC Caja {c['i']}" if len(cajas) > 1 else "PC Caja"
        sc = f"L_CAJAS:{c['i']}"
        if c["equipo"] in ("PC", "LAPTOP"):
            ip = c["ipconfig"]
            via = "WiFi" if c["conexion"] == "WIFI" else "cable de red"
            pieces = [x for x in (ip.get("nombreEquipo"), f"IP {ip['ipv4']}" if ip.get("ipv4") else None,
                                  f"conectada por {via}") if x]
            pos_rows.append(Row(label=label, value=" · ".join(pieces), source="ipconfig (E4)", origin="image"))
        elif a.get(f"P22a#{sc}") == "SI":
            pos_rows.append(_row(f"Raspberry Caja {c['i']}", f"Conexión: {_v(s, a.get(f'P22c#{sc}'))}",
                                 f"{SRC_CHAT} (P22c)", session=s))
        else:
            pos_rows.append(Row(label=f"Equipo Caja {c['i']}",
                                value=f"Sin equipo; el cliente adquirirá {_v(s, a.get(f'P22b#{sc}'))}",
                                source=f"{SRC_CHAT} (P22b)"))
    if not pos_rows:
        pos_rows.append(Row(label="Equipos POS", pending=True, pendingNote="el local no tiene cajas"))
    sec6 = Section(number=6, title="Equipos POS", rows=pos_rows)

    # ---- 7. Impresoras (tabla propia) ----------------------------------------------------
    scanned = {checks.norm_mac(d.get("mac")) for d in devices if d.get("mac")}
    prows: List[PrinterRow] = []
    for p in printers:
        t = p["ticket"]
        brand = s.label_of(p["marca"]) if p.get("marca") else ""
        model_bits = [x for x in (t.get("marca") or brand, t.get("modelo"),
                                  f"SN {t['numeroSerie']}" if t.get("numeroSerie") else None,
                                  f"papel {t['papel']}" if t.get("papel") else None) if x]
        model = " ".join(model_bits[:2]) + (" · " + " · ".join(model_bits[2:]) if len(model_bits) > 2 else "")
        legible = bool(t.get("modelo"))
        conn = p["conexion"]
        if conn == "USB":
            ip, red = "No aplica (USB)", "USB conectada a la PC de caja"
        elif t.get("ip"):
            ip = f"{t['ip']} {'fija (DHCP desactivado)' if t.get('dhcp') is False else 'por DHCP'}"
            if t.get("puerto"):
                ip += f", puerto {t['puerto']}"
            red = f"{s.label_of(conn)}" if conn else "Red"
            if t.get("mac"):
                red += f". MAC {t['mac']} " + ("verificada en el escáner" if checks.norm_mac(t["mac"]) in scanned
                                               else "no aparece en el escáner")
        else:
            ip, red = "Sin dato", s.label_of(conn) if conn else "Sin dato"
        prows.append(PrinterRow(
            nombre=f"Impresora {', '.join(s.label_of(x) for x in p['areas'])}".strip(),
            ubicacion=s.label_of(p["ubicacion"]) if p.get("ubicacion") else "",
            modelo=model or (brand or "Sin dato") + (" · modelo no legible" if not legible else ""),
            modeloPending=not legible,
            ip=ip, red=red,
            redOk=bool(t.get("mac")) and checks.norm_mac(t["mac"]) in scanned,
        ))

    # ---- 8. Energía -----------------------------------------------------------------------
    power_ext = ""
    if ans("P36") == "SI":
        power_ext = f"Sí: {_v(s, ans('P36a'))}" + (f" en {_v(s, ans('P43'))}" if ans("P43") else "")
    elif ans("P36") == "NO":
        power_ext = "No"
    sec8 = Section(number=8, title="Energía eléctrica", rows=[
        _row("Tomas cerca de los equipos de red", ans("P33"), f"{SRC_CHAT} (P33)", session=s),
        _row("Equipos que comparten toma", ans("P34"), f"{SRC_CHAT} (P34)", session=s),
        _row("UPS / energía de respaldo", ans("P35"), f"{SRC_CHAT} (P35)", session=s),
        _row("Extensiones", power_ext, f"{SRC_CHAT} (P36)", session=s),
    ])

    sections = [sec1, sec2, sec3, sec4, sec5, sec6]
    rows_all = [r for sec in sections + [sec8] for r in sec.rows]
    pending_rows = [r for r in rows_all if r.pending]

    # ---- 9-12 ---------------------------------------------------------------------------------
    skipped = state.get("skipped", [])
    rules = checks.evaluate_rules(state, pending_count=len(pending_rows) + len(skipped))
    status = checks.overall_status(rules)
    topo = build_state_topology(state)
    png = render_topology_png(topo)

    name = str(ans("P02") or ans("P01") or "el local")
    technician = str(ans("P07") or "")
    date = str(ans("P06") or "")
    doc = MinutaDocument(
        subtitle=name,
        intro="Minuta generada por el Asistente Virtual de Red a partir de las respuestas del técnico y de las "
              f"evidencias fotográficas de la visita del {date}. Cada dato indica de qué evidencia sale; lo "
              "marcado como pendiente lo pedirá el asistente durante la conversación.",
        date=date,
        technician=technician,
        kpis={
            "fields": len(rows_all),
            "fromImages": sum(1 for r in rows_all if not r.pending and r.origin == "image"),
            "fromChat": sum(1 for r in rows_all if not r.pending and r.origin == "chat"),
            "pending": len(pending_rows) + len(skipped),
        },
        sections=sections + [sec8],
        printers=prows,
        printersSource="Fuente: respuestas del técnico, tickets de autoprueba de las impresoras (E5) y escáner de IP (E8).",
        rules=rules,
        recommendations=_recommendations(state, s, rules, printers, cajas),
        mapPngBase64=base64.b64encode(png).decode() if png else "",
        mapCaption="Generado a partir del escáner de IP, el ipconfig de la PC de caja y el ticket de autoprueba. "
                   "El escáner no indica a qué repetidor se conecta cada equipo inalámbrico; esas conexiones las "
                   "confirma el técnico en el editor del mapa.",
        finalStatus=status,
        executiveSummary=_executive(status, rules, len(pending_rows) + len(skipped)),
        annexA=_annex_a(state),
        annexB=[PendingItem(node="—", question=f"Completar: {r.label}", type="TEXT", field=r.label)
                for r in pending_rows]
               + [PendingItem(node=x["nodeId"], question=x["text"], type="EVIDENCE", field=f"Evidencia {x['code']}")
                  for x in skipped],
        actionsId=[], actionsClient=[],
    )
    doc.actionsId, doc.actionsClient = _next_actions(state)
    # `sections` agrupa 1-6 y 8; el número 7 es la tabla de impresoras.
    return doc


def _recommendations(state, s: Session, rules: List[Rule], printers, cajas) -> List[str]:
    out: List[str] = []
    for c in cajas:
        wifi = c["conexion"] == "WIFI"
        if wifi:
            ip = c["ipconfig"].get("ipv4")
            out.append(f"Conectar la PC de caja {c['i']} al router por cable Ethernet"
                       + (f" y reservar su IP {ip} en el DHCP." if ip else "."))
    unknown = [r for r in rules if r.rule.startswith("Todos los equipos") and r.status == checks.OBSERVADO]
    if unknown:
        out.append("Identificar los equipos sin documentar del escáner. Si no son del negocio, moverlos a una red "
                   "WiFi de invitados separada de la red operativa (POS, impresoras y tablets).")
    if any(r.rule.startswith("Latencia") and r.status == checks.OBSERVADO for r in rules):
        out.append("Medir la latencia en hora punta. Si se confirma, priorizar el tráfico del POS (QoS) o colocar "
                   "un router propio con control de colas detrás del terminal del proveedor.")
    if checks.evidences(state, "E3"):
        out.append("Cambiar la contraseña de gestión del router si es la de fábrica impresa en la etiqueta.")
    if any(p["conexion"] == "USB" for p in printers):
        out.append("Completar la prueba de comandas con la impresora USB y evaluar pasarla a red para que no "
                   "dependa de la PC de caja.")
    if checks.answer(state, "P35") == "NO":
        out.append("Verificar la energía de router, PC de caja e impresoras, y considerar supresor de picos o UPS.")
    for action in state["actions"]:
        if action not in out:
            out.append(action)
    return out


def _executive(status: str, rules: List[Rule], pending: int) -> str:
    speed = next((r for r in rules if r.rule.startswith("Velocidad")), None)
    obs = [r for r in rules if r.status in (checks.OBSERVADO, checks.REVISAR) and not r.rule.startswith("Velocidad")]
    if status == "NO APTO":
        base = "La red todavía no es apta para implementar el sistema: la velocidad medida es insuficiente."
    else:
        base = "La red es apta para implementar el sistema"
        base += ": la velocidad es suficiente." if speed and speed.status == checks.CUMPLE else "."
    if obs:
        shorts = [r.short or r.rule.lower() for r in obs]
        joined = shorts[0] if len(shorts) == 1 else ", ".join(shorts[:-1]) + " y " + shorts[-1]
        base += f" Hay observaciones por corregir: {joined}."
    if pending:
        base += f" Quedan {pending} datos del cliente y de infraestructura que el asistente pedirá durante la conversación."
    return base


def _annex_a(state) -> List[AnnexItem]:
    s = Session(state)
    out: List[AnnexItem] = []
    for e in state["evidences"]:
        x, code = e["extracted"], e["code"]
        lines: List[str] = []
        title = {
            "E1": "Captura del speedtest", "E2": "Foto del router", "E3": "Etiqueta del router",
            "E4": "ipconfig de la PC de caja", "E5": "Ticket de autoprueba de la impresora",
            "E6": "Puntos de red y tomas", "E7": "Extensión de energía", "E8": "Escáner de IP",
            "E9": "Fotos generales del local", "EU-R": "Punto de red cercano", "EU-RN": "Lugar del nuevo punto de red",
            "EU-E": "Toma cercana", "EU-EN": "Lugar de la nueva toma",
        }.get(code, code)
        if e.get("area"):
            title += f" · {e['area']}"
        if code == "E1":
            if x.get("bajadaMbps") is not None:
                lines.append(f"Bajada {x['bajadaMbps']:g} Mbps, subida {x.get('subidaMbps', '—')} Mbps.")
            if x.get("pingMs") is not None:
                lines.append(f"Ping {x['pingMs']:g} ms en reposo"
                             + (f"; {x['latenciaBajadaMs']:g} y {x['latenciaSubidaMs']:g} ms con carga."
                                if x.get("latenciaBajadaMs") is not None and x.get("latenciaSubidaMs") is not None else "."))
            if x.get("servidor"):
                lines.append(f"Servidor {x['servidor']}." + (f" Proveedor mostrado: \"{x['proveedor']}\"."
                                                              if x.get("proveedor") else ""))
        elif code == "E3":
            device = " ".join(v for v in (x.get("marca"), x.get("modelo")) if v)
            if device:
                lines.append(device + ".")
            bits = [f"IP de gestión {x['ipGestion']}" if x.get("ipGestion") else None,
                    f"MAC {x['mac']}" if x.get("mac") else None, f"SN {x['numeroSerie']}" if x.get("numeroSerie") else None]
            if any(bits):
                lines.append(", ".join(b for b in bits if b) + ".")
            lines.append("Usuario, contraseña, SSID, clave WiFi y código QR ocultos automáticamente.")
        elif code == "E4":
            if x.get("ipv4"):
                lines.append(f"Adaptador {x.get('adaptador') or ''} con IPv4 {x['ipv4']}.".replace("  ", " "))
            if x.get("ethernetDesconectado"):
                lines.append('Adaptador Ethernet: "medios desconectados".')
        elif code == "E5":
            lines.append(" ".join(v for v in (x.get("marca"), x.get("modelo")) if v) or "Modelo no legible")
            net = [f"IP {x['ip']}" if x.get("ip") else None, f"gateway {x['puertaEnlace']}" if x.get("puertaEnlace") else None,
                   f"MAC {x['mac']}" if x.get("mac") else None, f"SN {x['numeroSerie']}" if x.get("numeroSerie") else None]
            if any(net):
                lines.append(", ".join(n for n in net if n) + ".")
        elif code == "E8":
            n = len(x.get("dispositivos") or [])
            lines.append(f"{n} dispositivos con fabricante y MAC.")
        if x.get("descripcion"):
            lines.append(str(x["descripcion"]))
        out.append(AnnexItem(code=code, scope=e["scope"], title=f"{title} · {code}", lines=lines))
    return out


def _next_actions(state):
    ours, client = [], []
    for action in state["actions"]:
        (client if "cliente" in action.lower() and "adquirir" in action.lower() else ours).append(action)
    agreements = checks.answer(state, "P52") or ""
    for line in [l.strip(" -•\t") for l in str(agreements).splitlines() if l.strip()]:
        (client if "cliente" in line.lower() or "enviar" in line.lower() else ours).append(line)
    return ours, client
