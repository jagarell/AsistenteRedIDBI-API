"""Validación técnica automática: cruza lo que respondió el técnico con lo que
la IA leyó de las evidencias (sección 9 de la minuta) y arma los avisos que el
chat muestra justo después de subir cada foto.

Los umbrales son valores de ejemplo de la minuta del cliente (50 Mbps, 100 ms).
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

MIN_SPEED_MBPS = 50.0
MAX_LATENCY_MS = 100.0

# Estados de una regla (la minuta los dibuja con icono/color distinto).
CUMPLE, OBSERVADO, VERIFICADO, REVISAR, APLICADO, INCOMPLETO, SIN_DATO = (
    "CUMPLE", "OBSERVADO", "VERIFICADO", "REVISAR", "APLICADO", "INCOMPLETO", "SIN_DATO",
)


class Rule(BaseModel):
    rule: str
    result: str
    status: str
    # Frase corta para el resumen ejecutivo ("la latencia alta con la red en uso").
    short: str = ""


# ---- acceso al estado ------------------------------------------------------
def answer(state: Dict[str, Any], nid: str, scope: str = "") -> Any:
    return state["answers"].get(f"{nid}#{scope}" if scope else nid)


def evidences(state: Dict[str, Any], code: str) -> List[Dict[str, Any]]:
    return [e for e in state["evidences"] if e["code"] == code]


def first_extracted(state: Dict[str, Any], code: str) -> Dict[str, Any]:
    found = evidences(state, code)
    return found[0]["extracted"] if found else {}


def label(state: Dict[str, Any], value: Any) -> str:
    from app.chat.flow_engine import Session

    return Session(state).label_of(value)


def lax_match(a: Optional[str], b: Optional[str]) -> bool:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    return not a or not b or a in b or b in a


def num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def norm_mac(mac: Optional[str]) -> str:
    return "".join(c for c in (mac or "").lower() if c.isalnum())


def cajas(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Una entrada por caja: equipo, conexión y lo leído de su ipconfig."""
    out = []
    for i in range(1, int(answer(state, "P12") or 0) + 1):
        sc = f"L_CAJAS:{i}"
        ev = next((e for e in evidences(state, "E4") if e["scope"] == sc), None)
        out.append({
            "i": i,
            "equipo": answer(state, "P22", sc),
            "conexion": answer(state, "P23", sc),
            "ipconfig": ev["extracted"] if ev else {},
        })
    return out


def printers_detail(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Impresoras registradas con lo respondido (ubicación, marca, conexión) y
    lo leído de su ticket (E5)."""
    out = []
    for p in state["printers"]:
        sc = p["scope"]
        if p["existing"]:
            ubic = answer(state, "P28", sc)
            marca = answer(state, "P29", sc)
            conexion = answer(state, "P30", sc)
            ev = next((e for e in evidences(state, "E5") if e["scope"] == sc), None)
        else:
            ubic = answer(state, "P32b", sc)
            marca = None
            conexion = answer(state, "P32c", sc)
            ev = None
        out.append({**p, "ubicacion": ubic, "marca": marca, "conexion": conexion,
                    "ticket": ev["extracted"] if ev else {}})
    return out


def scanner_devices(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    devices: List[Dict[str, Any]] = []
    for e in evidences(state, "E8"):
        devices.extend(e["extracted"].get("dispositivos") or [])
    return devices


# ---- avisos inmediatos tras subir una evidencia -------------------------------
def upload_warnings(state: Dict[str, Any], code: str, scope: str, extracted: Dict[str, Any]) -> List[str]:
    """Mensajes de validación cruzada para mostrar en el chat (efectos
    crossCheck del flujo). `state` ya incluye la evidencia recién subida."""
    msgs: List[str] = []
    if code == "E1":
        provider = label(state, answer(state, "P13"))
        seen = extracted.get("proveedor")
        if seen and not lax_match(seen, provider):
            msgs.append(f'La captura muestra "{seen}" como proveedor, pero indicaste "{provider}". '
                        "Proveedor del speedtest distinto al indicado: confirmar.")
        down, contracted = num(extracted.get("bajadaMbps")), num(answer(state, "P15"))
        if down is not None and contracted and down < 0.5 * contracted:
            msgs.append(f"Velocidad medida ({down:g} Mbps) menor al 50% de la contratada ({contracted:g} Mbps).")
    elif code == "E4":
        wired = answer(state, "P23", scope)
        seen = (extracted.get("adaptador") or "").lower()
        if seen and wired:
            is_wifi = "wifi" in seen or "wi-fi" in seen or "inal" in seen
            if (wired == "CABLE_RED" and is_wifi) or (wired == "WIFI" and not is_wifi):
                msgs.append("El ipconfig muestra otro tipo de adaptador que el indicado.")
    elif code == "E8":
        missing = missing_printer_macs(state)
        if missing:
            msgs.append("Alguna impresora no aparece en el escáner de IP: " + ", ".join(missing) + ".")
    return msgs


def clarification(state: Dict[str, Any], key: str) -> Optional[str]:
    return (state.get("clarifications") or {}).get(key)


def is_documented(state: Dict[str, Any], device: Dict[str, Any], known: set) -> bool:
    ip = device.get("ip")
    return ip in known or clarification(state, f"device:{ip}") == "PC de administración"


def follow_ups(state: Dict[str, Any], code: str, extracted: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Preguntas de confirmación que el chat hace tras leer una evidencia."""
    out: List[Dict[str, Any]] = []
    if code == "E1":
        provider = label(state, answer(state, "P13")) if answer(state, "P13") else ""
        seen = extracted.get("proveedor")
        if seen and provider and not lax_match(seen, provider):
            out.append({
                "key": "provider",
                "text": f'La captura muestra "{seen}" como proveedor, pero me dijiste {provider}. ¿Cuál es el correcto?',
                "options": [provider, str(seen), "No sé"],
            })
    elif code == "E8":
        known = known_ips(state)
        for d in extracted.get("dispositivos") or []:
            if d.get("ip") and d.get("nombre") and not is_documented(state, d, known):
                out.append({
                    "key": f"device:{d['ip']}",
                    "text": f"No tengo documentado {d['nombre']} (.{d['ip'].split('.')[-1]}). ¿Qué equipo es?",
                    "options": ["PC de administración", "No es del local", "No sé"],
                })
                break
    return out


def missing_printer_macs(state: Dict[str, Any]) -> List[str]:
    scanned = {norm_mac(d.get("mac")) for d in scanner_devices(state) if d.get("mac")}
    missing = []
    for p in printers_detail(state):
        mac = norm_mac(p["ticket"].get("mac"))
        if mac and scanned and mac not in scanned:
            missing.append(p["label"])
    return missing


# ---- sección 9: reglas ---------------------------------------------------------
def same_subnet(ip: Optional[str], gateway: Optional[str]) -> Optional[bool]:
    if not ip or not gateway:
        return None
    a, b = ip.split("."), gateway.split(".")
    if len(a) != 4 or len(b) != 4:
        return None
    return a[:3] == b[:3]


def known_ips(state: Dict[str, Any]) -> set:
    ips = set()
    for e in evidences(state, "E4"):
        if e["extracted"].get("ipv4"):
            ips.add(e["extracted"]["ipv4"])
        if e["extracted"].get("puertaEnlace"):
            ips.add(e["extracted"]["puertaEnlace"])
    for p in printers_detail(state):
        if p["ticket"].get("ip"):
            ips.add(p["ticket"]["ip"])
    ips.add(first_extracted(state, "E3").get("ipGestion") or "")
    return ips


def known_labels(state: Dict[str, Any]) -> Dict[str, str]:
    """IP → nombre legible de lo que ya está documentado (router, PC de caja, impresoras)."""
    labels: Dict[str, str] = {}
    router = first_extracted(state, "E3")
    router_name = " ".join(x for x in (router.get("marca"),) if x)
    for e in evidences(state, "E4"):
        x = e["extracted"]
        place = e.get("area") or ""
        kind = x.get("adaptador")
        name = "PC" + (f" {place}" if place else "") + (f" · {kind}" if kind else "")
        if x.get("ipv4"):
            labels[x["ipv4"]] = name
        if x.get("puertaEnlace"):
            labels.setdefault(x["puertaEnlace"], "Router" + (f" {router_name}" if router_name else ""))
    if router.get("ipGestion"):
        labels[router["ipGestion"]] = "Router" + (f" {router_name}" if router_name else "")
    for p in printers_detail(state):
        ip = p["ticket"].get("ip")
        if ip:
            labels[ip] = f"Impresora {p.get('label') or ''}".strip()
    return labels


def evaluate_rules(state: Dict[str, Any], pending_count: int = 0) -> List[Rule]:
    rules: List[Rule] = []

    # 1-2 velocidad y latencia
    speed = first_extracted(state, "E1")
    down, up = num(speed.get("bajadaMbps")), num(speed.get("subidaMbps"))
    if down is None:
        rules.append(Rule(rule=f"Velocidad medida ≥ {MIN_SPEED_MBPS:g} Mbps para POS y tablets",
                          result="Sin captura legible del speedtest", status=SIN_DATO))
    else:
        rules.append(Rule(rule=f"Velocidad medida ≥ {MIN_SPEED_MBPS:g} Mbps para POS y tablets",
                          result=f"{down:g} / {up:g} Mbps" if up is not None else f"{down:g} Mbps",
                          status=CUMPLE if down >= MIN_SPEED_MBPS else OBSERVADO))
    lat_d, lat_u = num(speed.get("latenciaBajadaMs")), num(speed.get("latenciaSubidaMs"))
    if lat_d is not None or lat_u is not None:
        worst = max(x for x in (lat_d, lat_u) if x is not None)
        parts = []
        if lat_d is not None:
            parts.append(f"{lat_d:g} ms en bajada")
        if lat_u is not None:
            parts.append(f"{lat_u:g} ms en subida")
        rules.append(Rule(rule=f"Latencia con la red en uso < {MAX_LATENCY_MS:g} ms",
                          result=" · ".join(parts),
                          status=CUMPLE if worst < MAX_LATENCY_MS else OBSERVADO,
                          short="la latencia alta con la red en uso"))

    # 3 PC de caja por cable
    for c in cajas(state):
        if c["equipo"] in ("PC", "LAPTOP"):
            adapter = (c["ipconfig"].get("adaptador") or "").lower()
            wifi = c["conexion"] == "WIFI" or "wifi" in adapter or "wi-fi" in adapter
            result = "Conectada por WiFi" if wifi else "Conectada por cable"
            if wifi and c["ipconfig"].get("ethernetDesconectado") is not None:
                result += "; el puerto Ethernet está libre" if c["ipconfig"]["ethernetDesconectado"] else ""
            rules.append(Rule(rule="PC de caja conectada por cable" if len(cajas(state)) == 1
                              else f"PC de caja {c['i']} conectada por cable",
                              result=result, status=OBSERVADO if wifi else CUMPLE,
                              short="la PC de caja conectada por WiFi"))

    # 4-5 impresoras de red: IP fija dentro del segmento y MAC en el escáner
    scanned = {norm_mac(d.get("mac")) for d in scanner_devices(state) if d.get("mac")}
    for p in printers_detail(state):
        t = p["ticket"]
        if t.get("ip") and p["conexion"] != "USB":
            inside = same_subnet(t["ip"], t.get("puertaEnlace"))
            fixed = t.get("dhcp") is False
            ok = inside is not False and fixed
            rules.append(Rule(
                rule="Impresora de red con IP fija dentro del segmento",
                result=f"{t['ip']} {'fija' if fixed else 'por DHCP'}"
                       + (", gateway correcto" if inside else ""),
                status=CUMPLE if ok else OBSERVADO,
                short="la impresora de red sin IP fija en el segmento"))
        if t.get("mac") and scanned and p["conexion"] != "USB":
            hit = norm_mac(t["mac"]) in scanned
            rules.append(Rule(
                rule="MAC de la impresora coincide con el escáner",
                result=f"{t['mac']} en el ticket y en el escáner" if hit else f"{t['mac']} no aparece en el escáner",
                status=VERIFICADO if hit else OBSERVADO,
                short="una impresora que no aparece en el escáner"))

    # 6 equipos documentados
    devices = scanner_devices(state)
    if devices:
        known = known_ips(state)
        undocumented = [d for d in devices if d.get("ip") and not is_documented(state, d, known)]
        if undocumented:
            named = [f"{d.get('nombre') or d.get('fabricante') or 'equipo'} ({d['ip']})" for d in undocumented[:3]]
            rules.append(Rule(rule="Todos los equipos de la red documentados",
                              result=f"{len(undocumented)} sin documentar: " + ", ".join(named)
                                     + ("…" if len(undocumented) > 3 else ""),
                              status=OBSERVADO, short="equipos sin documentar"))
        else:
            rules.append(Rule(rule="Todos los equipos de la red documentados",
                              result="Todos los dispositivos del escáner están documentados", status=CUMPLE))

    # 7 proveedor consistente
    provider = label(state, answer(state, "P13")) if answer(state, "P13") else None
    seen = speed.get("proveedor")
    if provider and seen:
        ok = lax_match(seen, provider)
        chosen = clarification(state, "provider")
        note = f' Confirmado por el técnico: se usa {chosen}.' if chosen and chosen != "No sé" else ""
        rules.append(Rule(rule="Proveedor consistente entre evidencias",
                          result=(f'Indicaste "{provider}"; el speedtest muestra "{seen}".' if not ok
                                  else f'"{seen}" coincide con "{provider}".') + note,
                          status=CUMPLE if ok else REVISAR,
                          short="el proveedor distinto entre evidencias"))

    # 8 impresión sin punto único de falla
    for p in printers_detail(state):
        if p["conexion"] == "USB":
            rules.append(Rule(rule="Impresión sin punto único de falla",
                              result=f"{p['label']} es USB: depende de que la PC esté encendida",
                              status=OBSERVADO, short="la dependencia de la impresora USB"))
            break

    # 9 credenciales fuera del documento
    if evidences(state, "E3"):
        rules.append(Rule(rule="Credenciales fuera del documento",
                          result="Usuario, contraseña, SSID y clave WiFi de la etiqueta ocultos",
                          status=APLICADO))

    # 10 datos obligatorios
    rules.append(Rule(rule="Datos obligatorios completos",
                      result="Todos los datos fueron capturados" if not pending_count
                      else f"{pending_count} campos pendientes",
                      status=CUMPLE if not pending_count else INCOMPLETO))
    return rules


def overall_status(rules: List[Rule]) -> str:
    speed_fail = any(r.rule.startswith("Velocidad") and r.status == OBSERVADO for r in rules)
    if speed_fail:
        return "NO APTO"
    if any(r.status in (OBSERVADO, REVISAR, INCOMPLETO) for r in rules):
        return "OBSERVADO"
    return "APTO"
