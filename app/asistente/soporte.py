"""Minuta de Soporte / incidencia (0.0.7). Reglas de soporte S1–S4, lectura de lo realizado y documento de la minuta
con el mismo modelo de bloques que la minuta de implementación (el gateway la dibuja con su plantilla)."""
import re
from typing import Any, Dict, List, Optional

from app.asistente.texto import credencial, sentences

REGLAS = [("S1", "Un solo sistema de impresiones activo"), ("S2", "IP fijas y sin conflictos"),
          ("S3", "Respaldo de cada impresora"), ("S4", "Lugares de preparación con su impresora asignada")]
ESTADOS = {"OP": "Operativo", "OPP": "Operativo con pendiente", "OBS": "Observado"}
# si no cumple: recomendación (título, texto) · paso del equipo técnico · paso del cliente
REC = {
    "S1": ("Un solo sistema de impresiones", "Dejar activo un solo sistema de impresiones para que las comandas no se dupliquen ni se pierdan.",
           "Desactivar el sistema de impresiones duplicado y probar la impresión desde el sistema.", None),
    "S2": ("IP fija y reservada en cada impresora", "Configurar la IP fija en cada impresora, sin repetirlas, y reservarlas en el router.",
           "Fijar la IP de cada impresora y registrarla en el sistema de impresiones.", "Solicitar a su proveedor de internet la reserva de las IP de las impresoras."),
    "S3": ("Respaldo de cada impresora", "Definir un respaldo (USB o WiFi) para cada impresora, con su propia IP registrada.",
           "Configurar el respaldo de las impresoras que no lo tienen.", None),
    "S4": ("Impresora en cada lugar de preparación", "Asignar en el sistema una impresora a cada lugar de preparación.",
           "Asignar la impresora del lugar de preparación en el sistema y probar la comanda.", "Indicar qué impresora usará cada lugar de preparación."),
}
_NAME = re.compile(r"IMP\.?\s+([A-Za-zÁÉÍÓÚáéíóúñÑ]+(?:\s+(?!con\b|por\b|en\b|de\b|ip\b|IP\b|y\b)[A-Za-zÁÉÍÓÚáéíóúñÑ]+)?)")


def leer(textos: List[str]) -> Dict[str, Any]:
    """Impresoras (IP, MAC, fija o automática, conexión, respaldo), sistema de impresiones, lugares de preparación y contraseñas."""
    P: Dict[str, Dict[str, Any]] = {}
    sys_dup = sys_one = prep_ok = False
    prep_miss: List[str] = []
    creds: List[Dict[str, str]] = []
    for t in textos:
        for s in sentences(t):
            if re.search(r"dos sistemas|m[aá]s de un sistema|sistema(s)? duplicad|ambos sistemas", s, re.I):
                sys_dup = True
            if re.search(r"un solo sistema|[uú]nico sistema", s, re.I):
                sys_one = True
            pm = re.search(r"(cocina|barra|bebidas|horno|parrilla)\s+(no tiene|sin)\s+impresora", s, re.I)
            if pm:
                prep_miss.append(pm.group(1))
            if re.search(r"tiene su impresora|con su impresora asignada|impresora asignada", s, re.I):
                prep_ok = True
            c = credencial(s)
            if c:
                creds.append(c)
            nm = _NAME.search(s)
            if not nm:
                continue
            n = nm.group(1).strip()
            p = P.setdefault(n, {"name": n, "ip": "", "mac": "", "con": "", "fija": None, "resp": "", "esResp": False})
            ip = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", s)
            if ip:
                p["ip"] = ip.group(1)
            mac = re.search(r"([0-9A-F]{2}(?:[-:][0-9A-F]{2}){5})", s, re.I)
            if mac:
                p["mac"] = mac.group(1).upper()
            if re.search(r"fija|est[aá]tica", s, re.I):
                p["fija"] = True
            if re.search(r"dhcp|autom[aá]tica|la asigna", s, re.I):
                p["fija"] = False
            if re.search(r"\busb\b", s, re.I) and not re.search(r"respaldo (por )?usb", s, re.I):
                p["con"] = "USB"
            elif re.search(r"wi-?fi", s, re.I) and not re.search(r"respaldo (por )?wi-?fi", s, re.I):
                p["con"] = "WiFi"
            elif re.search(r"red|cable|ethernet", s, re.I):
                p["con"] = "Red por cable"
            r = re.search(r"respaldo\s+(por\s+)?(usb|wi-?fi|red)", s, re.I)
            if r:
                p["resp"] = {"USB": "USB", "RED": "Red"}.get(r.group(2).upper(), "WiFi")
            if re.search(r"como respaldo", s, re.I):
                p["esResp"] = True
    L = list(P.values())
    for p in L:
        if p["esResp"]:
            base = next((q for q in L if q is not p and p["name"].startswith(q["name"].split(" ")[0])), None)
            if base and not base["resp"]:
                base["resp"] = p["con"] or "WiFi"
    return {"impresoras": L, "sysDup": sys_dup, "sysOne": sys_one, "prepMiss": prep_miss, "prepOk": prep_ok, "credenciales": creds}


def reglas_sugeridas(motivo: str, hechos: List[str]) -> Dict[str, Any]:
    A = leer([motivo] + list(hechos))
    pr = A["impresoras"]
    ips = [p["ip"] for p in pr if p["ip"]]
    dup = sorted({x for x in ips if ips.count(x) > 1})
    main = [p for p in pr if not p["esResp"]]
    R = {
        "S1": "bad" if A["sysDup"] else "ok",
        "S2": "na" if not pr else ("bad" if (dup or any(p["fija"] is False for p in pr)) else "ok"),
        "S3": "na" if not main else ("ok" if all(p["resp"] for p in main) else "bad"),
        "S4": "bad" if A["prepMiss"] else ("ok" if (A["prepOk"] or pr) else "na"),
    }
    return {"reglas": R, "lectura": A, "ipRepetidas": dup}


def resultado(k: str, v: str, L: Dict[str, Any]) -> str:
    A = L["lectura"]
    pr = A["impresoras"]
    main = [p for p in pr if not p["esResp"]]
    if v == "na":
        return "No aplica"
    if k == "S1":
        return "Un solo sistema activo" if v == "ok" else "Más de un sistema de impresiones activo"
    if k == "S2":
        if v == "ok":
            return f"{len(pr)} {'impresora' if len(pr) == 1 else 'impresoras'} con IP fija · sin IP repetidas" if pr else "IP fijas y sin conflictos"
        if L["ipRepetidas"]:
            return "IP repetida: " + ", ".join(L["ipRepetidas"])
        return " · ".join(f"IMP. {p['name']} con IP automática" for p in pr if p["fija"] is False) or "IP sin fijar o en conflicto"
    if k == "S3":
        if v == "ok":
            return " · ".join(f"IMP. {p['name']}: {p['resp'] or 'con respaldo'}" for p in main) or "Cada impresora tiene respaldo"
        return " · ".join(f"IMP. {p['name']} sin respaldo" for p in main if not p["resp"]) or "Falta el respaldo de una impresora"
    if k == "S4":
        if v == "ok":
            return "Cada lugar de preparación tiene su impresora"
        return "Sin impresora: " + ", ".join(A["prepMiss"]) if A["prepMiss"] else "Falta asignar la impresora de un lugar de preparación"
    return ""


def estado_sugerido(reglas: Dict[str, str], hechos: List[str]) -> str:
    if "bad" in reglas.values():
        return "OBS"
    if any(re.search(r"pendiente|falta|queda por|por confirmar", h, re.I) for h in hechos):
        return "OPP"
    return "OP"


def _sin_credenciales(t: str) -> str:
    return " ".join(x for x in sentences(t) if not credencial(x)).rstrip(";").strip()


def _sin_fechas(t: str) -> str:
    t = re.sub(r"\s*(el|hasta el|para el|antes del)\s+\d{1,2}/\d{1,2}(/\d{2,4})?", "", t, flags=re.I)
    return re.sub(r"\s*\d{1,2}/\d{1,2}/\d{2,4}", "", t)


def documento(d: Dict[str, Any]) -> Dict[str, Any]:
    """d: cliente, local, direccion, fecha, tecnico, empresa, antecedentes[], motivo, puntos[], hechos[], evidencias[],
    reglas{S1..S4: ok|bad|na} (opcional), estado (OP|OPP|OBS, opcional), recs[], pasos[], notas[], credenciales[]."""
    hechos = list(d.get("hechos") or [])
    L = reglas_sugeridas(d.get("motivo") or "", hechos)
    reglas = {**L["reglas"], **(d.get("reglas") or {})}
    estado = d.get("estado") or estado_sugerido(reglas, hechos)
    pr = L["lectura"]["impresoras"]
    creds = (d.get("credenciales") or []) + [c for c in L["lectura"]["credenciales"] if not any(x.get("eq") == c["eq"] for x in (d.get("credenciales") or []))]
    empresa = d.get("empresa") or "IDBI"
    local = d.get("local") or d.get("cliente") or "el local"
    blocks: List[Dict[str, Any]] = []
    n = [0]

    def h2(t: str, cls: str = "") -> None:
        n[0] += 1
        blocks.append({"t": "h2", "n": f"{n[0]}.", "text": t, "cls": cls})

    h2("Datos generales")
    rows = []
    if d.get("cliente") and d.get("cliente", "").lower() != local.lower():
        rows.append({"label": "Cliente", "value": d["cliente"]})
    rows += [{"label": "Nombre del local", "value": local}, {"label": "Dirección", "value": d.get("direccion") or ""},
             {"label": "Tipo de visita", "value": "Soporte / incidencia"}, {"label": "Fecha de la visita", "value": d.get("fecha") or ""},
             {"label": "Técnico responsable", "value": d.get("tecnico") or ""}]
    if d.get("validadaPor"):
        rows.append({"label": "Validada por", "value": d["validadaPor"]})
    blocks.append({"t": "kv", "rows": [r for r in rows if r["value"]]})
    h2("Antecedentes")
    ant = d.get("antecedentes") or []
    frases = []
    for x in ant:
        q = {"implementacion": "se realizó la visita técnica de implementación", "soporte": "se atendió una visita de soporte"}.get(str(x.get("tipo", "")).lower(), "se reportó una incidencia")
        txt = str(x.get("texto") or "").rstrip(".")
        frases.append(f"El {x.get('fecha')} {q}{': ' + txt[0].lower() + txt[1:] if txt else ''}.")
    blocks.append({"t": "para", "text": " ".join(frases) or "No hay visitas ni incidencias anteriores registradas del cliente."})
    blocks.append({"t": "para", "b": "Motivo de la visita:", "text": d.get("motivo") or ""})
    h2("Objetivo y alcance")
    blocks.append({"t": "para", "text": "Atender la incidencia reportada y dejar operativos los equipos de impresión y de red. La visita abarca:"})
    blocks.append({"t": "ul", "items": [{"text": p.rstrip(".") + "."} for p in d.get("puntos") or []]})
    h2("Desarrollo técnico")
    for j, p in enumerate(d.get("puntos") or []):
        blocks.append({"t": "h3", "text": f"{j + 1}. {p}"})
        blocks.append({"t": "para", "text": _sin_credenciales(hechos[j]) if j < len(hechos) else ""})
    if d.get("notas"):
        blocks.append({"t": "h3", "text": "Actualización"})
        blocks += [{"t": "para", "text": t} for t in d["notas"]]
    if pr or creds:
        h2("Impresoras y red")
        if pr:
            blocks.append({"t": "table", "head": ["Impresora", "IP", "Conexión", "Respaldo", "Estado"], "firstBold": True, "rows": [
                {"cells": [f"IMP. {p['name']}", (p["ip"] or "—") + (" (automática)" if p["fija"] is False else " fija" if p["ip"] else "") + (f" · MAC {p['mac']}" if p["mac"] else ""),
                           p["con"] or "—", "Es respaldo" if p["esResp"] else (p["resp"] or "—"),
                           "Respaldo · operativa" if p["esResp"] else "Observado" if p["fija"] is False else "Operativa"],
                 "badLast": p["fija"] is False} for p in pr]})
        if creds:
            blocks.append({"t": "h3", "text": "Accesos y contraseñas"})
            blocks.append({"t": "table", "head": ["Equipo", "Red o usuario", "Contraseña"], "firstBold": True,
                           "rows": [{"cells": [c.get("eq") or "", c.get("usr") or "—", c.get("pw") or ""]} for c in creds]})
    h2("Validación técnica")
    st_txt = {"ok": "Cumple", "bad": "No cumple", "na": "No aplica"}
    blocks.append({"t": "rules", "rows": [{"rule": l, "result": resultado(k, reglas.get(k, "na"), L), "ok": reglas.get(k) != "bad",
                                           "status": st_txt[reglas.get(k, "na")]} for k, l in REGLAS]})
    bads = [k for k, _ in REGLAS if reglas.get(k) == "bad"]
    recs = [{"t": REC[k][0], "d": REC[k][1]} for k in bads] + list(d.get("recs") or [])
    if recs:
        h2("Recomendaciones")
        blocks.append({"t": "ul", "items": [{"b": r["t"] + ".", "text": r.get("d") or ""} for r in recs]})
    h2("Resumen ejecutivo")
    if estado == "OBS":
        res = "El local queda observado: falta cumplir " + " y ".join(dict(REGLAS)[k].lower() for k in bads) + "."
    elif estado == "OPP":
        res = "El local queda operativo con un pendiente: se atendieron los puntos de la visita y queda un punto por cerrar en los pasos a seguir."
    else:
        res = f"El local queda operativo: se atendieron los {len(d.get('puntos') or [])} puntos de la visita y se cumplen las reglas de soporte."
    blocks.append({"t": "exec", "status": ESTADOS[estado].upper(), "ok": estado == "OP", "text": res})
    h2("Pasos a seguir")
    extra = d.get("pasos") or []
    pt = ["Compartir la minuta de visita técnica de soporte."] + [REC[k][2] for k in bads] + [p["t"] for p in extra if p.get("p") != "Cliente"]
    pc = ["Confirmar la recepción de la minuta."] + [REC[k][3] for k in bads if REC[k][3]] + [p["t"] for p in extra if p.get("p") == "Cliente"]
    uniq = lambda L: list(dict.fromkeys(_sin_fechas(x) for x in L))  # noqa: E731
    blocks.append({"t": "h3", "text": f"Por parte del equipo técnico de {empresa}:"})
    blocks.append({"t": "ul", "items": [{"text": x} for x in uniq(pt)]})
    blocks.append({"t": "h3", "text": "Por parte del cliente:"})
    blocks.append({"t": "ul", "items": [{"text": x} for x in uniq(pc)]})
    ev = d.get("evidencias") or []
    if ev:
        blocks.append({"t": "h2", "n": "Anexo A.", "text": "Evidencias", "cls": "annex"})
        blocks.append({"t": "grid", "cols": 3, "cells": [{"caption": e.get("archivo") or "", "title": e.get("tipo") or "Evidencia",
                                                         "lines": [e.get("lectura") or ""], "evidence": []} for e in ev]})
    fecha = d.get("fecha") or ""
    return {"title": "MINUTA DE VISITA TÉCNICA · SOPORTE", "subtitle": local, "date": fecha, "header": f"Minuta de soporte · {local} · {fecha}",
            "estado": ESTADOS[estado], "estadoCodigo": estado, "reglas": reglas, "blocks": blocks, "kpis": [], "mapPngBase64": "",
            "porcentaje": 92 if estado == "OP" else 76 if estado == "OPP" else 55}


def leer_evidencia(nombre: str, impresoras: List[Dict[str, Any]]) -> Dict[str, str]:
    """Qué leyó el asistente de cada evidencia (en la app lo hace la visión de ChatGPT sobre la foto)."""
    s = nombre.lower()
    pr = next((p for p in sorted(impresoras, key=lambda p: -len(p["name"])) if p["name"].lower().replace(" ", "_") in s), None)
    if "selftest" in s:
        r = f"IMP. {pr['name']} · IP {pr['ip']}{' · MAC ' + pr['mac'] if pr['mac'] else ''} · {'IP automática (DHCP)' if pr['fija'] is False else 'IP fija'}" if pr and pr["ip"] \
            else "IP, MAC y modo de IP de la impresora (fija o automática)"
        return {"tipo": "Selftest de impresora", "lectura": r}
    if re.search(r"repetidor|wifi", s):
        return {"tipo": "Repetidor WiFi", "lectura": "Red y zona que cubre; se usa para la impresora de respaldo por WiFi"}
    if re.search(r"smartaplink|config", s):
        return {"tipo": "Configuración WiFi de la impresora", "lectura": "Red WiFi configurada en la impresora de respaldo"}
    if "router" in s:
        return {"tipo": "Router", "lectura": "Marca, modelo y puertos del router"}
    if re.search(r"driver|controlador|lan_port", s):
        return {"tipo": "Controlador", "lectura": "Controlador de la impresora validado"}
    return {"tipo": "Foto de la visita", "lectura": "Imagen guardada como evidencia"}
