"""Actualizar desde el Asistente IA cualquier dato de una minuta ya generada (0.0.7 · Parte 6).

El técnico escribe los cambios como los diría («En áreas de preparación donde dice Panaderia colocar …», «Proveedor: Starlink»,
«en el cuadro de impresoras …», «quita la imagen del gabinete»). `leer()` los convierte en operaciones sobre el documento de la
minuta; la app muestra cada operación en «Cambios que haré» y, al aplicar, el gateway las guarda en la minuta (nueva versión,
historial y vuelve a validación). `aplicar()` las ejecuta sobre los bloques del documento cada vez que se arma el PDF.

Operaciones:
  set       {sec, label, value}            fila de una tabla de datos (dat, neg, net, caj, wifi, ene); si no existe se agrega
  listRep   {sec, label, from, to}         reemplaza un elemento de una lista («Panaderia» → «Panaderia Mesón / Panaderia Amat»)
  rename    {from, to}                     renombra un equipo en todo el documento (tablas, reglas, recomendaciones, anexo)
  prn       {name, col, value}             celda de la tabla de impresoras
  prnWhere  {col, eq, value, except[]}     todas las impresoras cuya celda dice `eq`
  prnAdd    {cells[6]}                     impresora nueva
  eq        {name, col, value}             celda de Equipos varios
  photoDel  {title, group?}                quita una foto del anexo (group = bloque, por ejemplo «IMP. Panaderia»)
  tomas     {items[{eq, det}]}             «Equipos sin tomas cerca» (también corrige la recomendación y el paso)
  routerEnc {enc}                          si el router queda en un espacio cerrado (MUEBLE / CUARTO) o no (None)
"""
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

SEC_LABEL = {"dat": "Datos generales", "neg": "Negocio", "net": "Internet", "caj": "Equipos de caja", "wifi": "WiFi y cámaras",
             "ene": "Energía eléctrica"}
PRN_COLS = ["Nombre", "Ubicación", "Marca y modelo · SN", "IP · MAC", "Conexión", "Estado"]
EQ_COLS = ["Equipo", "Tipo", "Ubicación", "Detalle", "Estado"]
CANALES = ["Mesa", "Recojo", "Para llevar", "Delivery", "Backoffice", "Habitaciones"]


def norm(s: Any) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(s or "").lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def _cap(s: str) -> str:
    s = s.strip().strip(".;,").strip()
    return s[:1].upper() + s[1:] if s else s


def _acentos(s: str) -> str:
    """Tildes de palabras comunes que el técnico escribe sin tilde (no toca nombres propios)."""
    for a, b in (("aun ", "aún "), ("energia", "energía"), ("conexion", "conexión"), ("ubicacion", "ubicación"),
                 ("habilitado", "habilitado"), ("esta ", "está "), ("area ", "área "), ("electrica", "eléctrica")):
        s = re.sub(rf"\b{a}", b, s)
    return s


def imp_name(s: str) -> str:
    """«imp.panaderia en Amat» → «IMP. Panaderia Amat» · «Imp.Panaderia Mesón» → «IMP. Panaderia Mesón»."""
    s = re.sub(r"^\s*(la\s+|el\s+)?imp(resora)?\.?\s*", "", s.strip(), flags=re.I)
    s = re.sub(r"\s+en\s+", " ", s)
    s = s.strip(" .,;")
    return "IMP. " + " ".join(w[:1].upper() + w[1:] for w in s.split())


# ---- secciones del texto ----------------------------------------------------------------------------------------
ANCLAS: List[Tuple[str, str]] = [
    ("areas", r"(?:en\s+)?(?:las\s+)?[aá]reas?\s+de\s+preparaci[oó]n"),
    ("zonas", r"(?:en\s+)?(?:los\s+)?canales\s+y\s+zonas(?:\s+de\s+atenci[oó]n)?|(?:en\s+)?zonas\s+de\s+atenci[oó]n"),
    ("conex", r"(?:en\s+)?(?:el\s+)?tipo\s+de\s+conexi[oó]n"),
    ("prov", r"(?:en\s+)?(?:el\s+)?proveedor(?:\s+de\s+internet)?"),
    ("plan", r"(?:en\s+)?(?:el\s+)?plan(?:\s+contratado|\s+de\s+internet)"),
    ("router", r"d[oó]nde\s+(?:ir[aá]|est[aá]|queda)\s+el\s+router|(?:en\s+)?(?:la\s+)?ubicaci[oó]n\s+del\s+router|\bel\s+router\s+(?:ir[aá]|est[aá]|queda)"),
    ("caja", r"(?:en\s+)?(?:el\s+)?equipo(?:\s+de\s+caja)?\s+es\b|(?:en\s+)?(?:el\s+)?equipo\s+de\s+caja"),
    ("prn", r"(?:en\s+)?(?:el\s+)?(?:cuadro|tabla)\s+de\s+impresoras"),
    ("eqv", r"(?:en\s+)?equipos\s+varios"),
    ("wifi", r"wifi\s+y\s+c[aá]m(?:ar)?as"),
    ("tomas", r"(?:en\s+)?equipos\s+sin\s+tomas(?:\s+cerca)?"),
    ("evid", r"(?:en\s+)?(?:las\s+)?evidencias|(?:en\s+)?el\s+anexo"),
    ("cajas", r"(?:en\s+)?(?:la\s+)?cantidad\s+de\s+cajas"),
    ("comandas", r"(?:en\s+)?comandas\s+en\s+caja"),
    ("camaras", r"(?:en\s+)?c[aá]maras\s+en\s+la\s+red"),
]
DATOS = [("razon", "Razón social", r"raz[oó]n\s+social"), ("ruc", "RUC", r"\bruc\b"), ("nombre", "Nombre del local", r"nombre\s+del\s+local"),
         ("dir", "Dirección", r"direcci[oó]n"), ("enc", "Encargado del local", r"encargad[oa](?:\s+del\s+local)?"),
         ("cel", "Celular", r"celular"), ("correo", "Correo", r"correo")]


def _secciones(t: str) -> List[Tuple[str, str]]:
    marks = []
    for k, rx in ANCLAS:
        for m in re.finditer(rx, t, re.I):
            marks.append((m.start(), m.end(), k))
    for k, _, rx in DATOS:
        for m in re.finditer(rf"(?:^|[.\n]\s*|\b(?:en|la|el)\s+){rx}\s*(?::|ser[ií]a|es\b|colocar|poner)", t, re.I):
            s = re.search(rx, t[m.start():m.end()], re.I)
            marks.append((m.start() + s.start(), m.start() + s.end(), "dato:" + k))
    marks.sort()
    out, used = [], -1
    for i, (s, e, k) in enumerate(marks):
        if s < used:
            continue
        nxt = next((x[0] for x in marks[i + 1:] if x[0] >= e), len(t))
        out.append((k, t[e:nxt]))
        used = e
    pre = t[: marks[0][0]] if marks else t
    if pre.strip():
        out.insert(0, ("libre", pre))
    return out


def _valor(sl: str) -> str:
    """Lo que viene después de «sería:», «:», «es», «colocar»…"""
    s = re.sub(r"^\s*(?:ser[ií]a|es|ser[aá]|debe\s+decir|colocar|poner|cambiar\s+a|a)?\s*[:\-]?\s*", "", sl, flags=re.I)
    return s


def _corta(s: str) -> str:
    """Primera oración (hasta un punto seguido de espacio y mayúscula o fin)."""
    m = re.match(r"(.+?)(?:\.\s+(?=[A-ZÁÉÍÓÚ])|\.\s*$|$)", s.strip(), re.S)
    return (m.group(1) if m else s).strip()


def leer(texto: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Texto del técnico → (operaciones, frases que no son datos de la minuta)."""
    t = re.sub(r"\s+", " ", texto or "").strip()
    ops: List[Dict[str, Any]] = []
    resto: List[str] = []
    for k, sl in _secciones(t):
        sl = sl.strip(" ,;")
        if k == "libre":
            resto.append(sl)
        elif k == "areas":
            m = re.search(r"donde\s+dice\s+(.+?)\s+(?:colocar|poner|cambiar\s+(?:a|por)|reemplazar\s+por|por)\s+(.+?)(?:\.\s|\.$|$)", sl, re.I)
            if m:
                ops.append({"op": "listRep", "sec": "neg", "label": "Áreas de preparación", "from": m.group(1).strip(),
                            "to": re.sub(r"\s*/\s*", " / ", m.group(2).strip(" .")),
                            "t": f"Áreas de preparación: «{m.group(1).strip()}» pasa a «{re.sub(r'\s*/\s*', ' / ', m.group(2).strip(' .'))}»"})
            else:
                v = _cap(_corta(_valor(sl)))
                if v:
                    ops.append({"op": "set", "sec": "neg", "label": "Áreas de preparación", "value": v, "t": f"Áreas de preparación: {v}"})
        elif k == "zonas":
            partes = []
            for c in CANALES:
                m = re.search(rf"\b{c}\s*:\s*(.+?)(?=\b(?:{'|'.join(CANALES)})\s*:|$)", sl, re.I)
                if m:
                    zs = [z.strip(" .") for z in re.split(r"\s*,\s*", m.group(1).strip(" .")) if z.strip(" .")]
                    partes.append((sl.lower().find(c.lower()), f"{c}: {', '.join(zs)}"))
            if partes:
                v = " · ".join(p for _, p in sorted(partes))
                ops.append({"op": "set", "sec": "neg", "label": "Canales y zonas de atención", "value": v, "t": f"Canales y zonas de atención: {v}"})
            else:
                v = _cap(_corta(_valor(sl)))
                if v:
                    ops.append({"op": "set", "sec": "neg", "label": "Canales y zonas de atención", "value": v, "t": f"Canales y zonas de atención: {v}"})
        elif k in ("conex", "prov", "plan", "cajas", "comandas", "camaras"):
            lab = {"conex": ("net", "Tipo de conexión"), "prov": ("net", "Proveedor"), "plan": ("net", "Plan contratado"),
                   "cajas": ("neg", "Cantidad de cajas"), "comandas": ("neg", "Comandas en caja"), "camaras": ("wifi", "Cámaras en la red")}[k]
            v = _cap(_acentos(_corta(_valor(sl))))
            if v:
                ops.append({"op": "set", "sec": lab[0], "label": lab[1], "value": v, "t": f"{lab[1]}: {v}"})
        elif k == "router":
            v = _cap(_acentos(_corta(_valor(sl))))
            if v:
                low = norm(v)
                enc = "MUEBLE" if re.search(r"mueble|gabinete|armario|closet", low) else "CUARTO" if re.search(r"\bcuarto\b", low) else None
                ops.append({"op": "set", "sec": "net", "label": "Dónde irá el router", "value": v, "t": f"Dónde irá el router: {v}"})
                ops.append({"op": "routerEnc", "enc": enc, "t": "Ubicación del router: " + ("en espacio cerrado (queda en observación)" if enc else "sin observación por espacio cerrado")})
        elif k == "caja":
            v = _cap(_acentos(_corta(_valor(sl))))
            if v:
                ops.append({"op": "set", "sec": "caj", "label": "Equipo de Caja", "value": v, "t": f"Equipo de caja: {v}"})
        elif k == "prn":
            ops += _impresoras(_valor(sl))
        elif k == "eqv":
            ops += _equipos(_valor(sl))
        elif k == "wifi":
            v = _cap(_acentos(_corta(_valor(re.sub(r"^\s*(?:est[aá]n?|queda[n]?)\s+", "", sl, flags=re.I)))))
            if v:
                ops.append({"op": "set", "sec": "wifi", "label": "WiFi", "value": v, "t": f"WiFi: {v}"})
                ops.append({"op": "set", "sec": "wifi", "label": "Cámaras en la red", "value": v, "t": f"Cámaras en la red: {v}"})
        elif k == "tomas":
            ops += _tomas(_valor(sl))
        elif k == "evid":
            ops += _evidencias(_valor(sl))
        elif k.startswith("dato:"):
            key = k.split(":")[1]
            lab = next(l for kk, l, _ in DATOS if kk == key)
            v = _corta(_valor(sl)).strip(" .")
            if v:
                ops.append({"op": "set", "sec": "dat", "label": lab, "value": v, "t": f"{lab}: {v}"})
    # renombres primero: así el resto de operaciones ya usa el nombre nuevo
    ren = [o for o in ops if o["op"] == "rename"]
    uniq_ren, seen = [], set()
    for o in ren:
        if (o["from"], o["to"]) not in seen:
            seen.add((o["from"], o["to"]))
            uniq_ren.append(o)
    ops = uniq_ren + [o for o in ops if o["op"] != "rename"]
    return ops, [r for r in resto if r.strip()]


def _renombres(s: str) -> List[Dict[str, Any]]:
    out = []
    for m in re.finditer(r"(?:donde\s+dice\s+|(?:en\s+)?(?:la\s+)?impresora\s+)?(imp\.?\s*[\wáéíóúñ]+(?:\s+[\wáéíóúñ]+)?)\s*,?\s*(?:renombr\w*|cambi\w*\s+(?:el\s+)?nombre)\s+(?:a|por|como)\s+(imp\.?\s*[\wáéíóúñ]+(?:\s+[\wáéíóúñ]+){0,3}?)(?=\s+y\b|\s*[.,;]|$)", s, re.I):
            a, b = imp_name(m.group(1)), imp_name(m.group(2))
            out.append({"op": "rename", "from": a, "to": b, "t": f"Renombrar la impresora {a[5:]} → {b[5:]}"})
    for m in re.finditer(r"(?:en\s+)?impresora\s+([\wáéíóúñ]+)\s+renombr\w*\s+a\s+(imp\.?\s*[\wáéíóúñ]+(?:\s+[\wáéíóúñ]+){0,3}?)(?=\s+y\b|\s*[.,;]|$)", s, re.I):
        a, b = imp_name(m.group(1)), imp_name(m.group(2))
        out.append({"op": "rename", "from": a, "to": b, "t": f"Renombrar la impresora {a[5:]} → {b[5:]}"})
    return out


def _impresoras(s: str) -> List[Dict[str, Any]]:
    ops: List[Dict[str, Any]] = []
    m = re.search(r"en\s+conexi[oó]n\s+los\s+que\s+dice[n]?\s+(.+?)\s+(?:colocar|poner)\s+(.+?)(?:\.\s*y\b|\.\s|\s+y\s+solo|$)", s, re.I)
    exc: List[str] = []
    solo = re.search(r"solo\s+para\s+(?:la\s+)?(?:imp\.?\s*)?([\wáéíóúñ]+)\s+(?:colocar|poner)\s+(.+?)(?:\.\s*(?=[a-záéíóú]*\s*donde|\w)|\.$|$)", s, re.I)
    if solo:
        exc.append(imp_name(solo.group(1)))
    if m:
        v = _cap(re.sub(r"\s*-\s*", " - ", m.group(2).strip(" .")))
        ops.append({"op": "prnWhere", "col": "Conexión", "eq": m.group(1).strip(), "value": v, "except": exc,
                    "t": f"Impresoras con conexión «{m.group(1).strip()}»{(' (menos ' + ', '.join(exc) + ')') if exc else ''}: {v}"})
    if solo:
        v = _cap(re.sub(r"\s*-\s*", " - ", _corta(solo.group(2))))
        v = re.sub(r"No Habilitado", "No habilitado", v)
        ops.append({"op": "prn", "name": exc[0], "col": "Conexión", "value": v, "t": f"{exc[0]} · conexión: {v}"})
    ops += _renombres(s)
    for m in re.finditer(r"agreg\w*\s+(?:una\s+)?impresora\s+(?:nueva\s+)?(?:que\s+(?:diga|se\s+llame)\s+|llamada\s+)(imp\.?\s*[\wáéíóúñ]+(?:\s+[\wáéíóúñ]+){0,2}?)(?=\s+y\b|\s*[.,;]|$)(.*?)(?=agreg\w*\s+(?:una\s+)?impresora|$)", s, re.I):
        name = imp_name(m.group(1))
        rest = m.group(2)

        KEYS = [("ubic", r"ubicaci[oó]n"), ("marca", r"marca(?:\s+y\s+modelo)?"), ("ip", r"\bip\b"), ("con", r"conexi[oó]n"), ("est", r"estado")]
        pos = sorted((mm.start(), mm.end(), k) for k, rx in KEYS for mm in re.finditer(rx, rest, re.I))
        vals: Dict[str, str] = {}
        for i, (a0, a1, k) in enumerate(pos):
            if k in vals:
                continue
            end = pos[i + 1][0] if i + 1 < len(pos) else len(rest)
            v = re.sub(r"^\s*(?:colocar|poner|ser[ií]a|es)?\s*:?\s*", "", rest[a1:end], flags=re.I)
            v = re.sub(r"[\s.,;]*(?:y\s+(?:en\s+)?)?$", "", v.strip())
            vals[k] = _cap(v)

        def campo(key: str, default: str) -> str:
            v = vals.get(key) or ""
            return default if not v else ("Sin dato" if norm(v) == "sin dato" else v)

        ubic = campo("ubic", "Por definir")
        marca = campo("marca", "Sin dato")
        ip = campo("ip", "Sin dato")
        con = campo("con", "Sin dato")
        con = re.sub(r"\s*-\s*", " - ", con).replace("No Habilitado", "No habilitado")
        est = campo("est", "Por confirmar")
        cells = [name, ubic, marca.replace("Sin dato", "Sin dato"), ip, con, est]
        ops.append({"op": "prnAdd", "cells": cells, "t": f"Impresora nueva {name}: ubicación {ubic} · marca y modelo {marca} · IP {ip} · conexión {con}"})
    return ops


def _equipos(s: str) -> List[Dict[str, Any]]:
    ops = []
    s = re.sub(r"^\s*(?:coloca[r]?|poner|pon)\s+", "", s, flags=re.I)
    for m in re.finditer(r"(?:la|el|los|las)\s+([\wáéíóúñ ]+?)\s+(?:est[aá]n?|queda[n]?|es)\s+(por\s+implementar|existente|con\s+falla|observado|por\s+adquirir|por\s+confirmar|instalad[oa]|operativ[oa])", s, re.I):
        nm, st = m.group(1).strip(), _cap(m.group(2).lower())
        if re.search(r"wifi|c[aá]m", nm, re.I):
            continue
        ops.append({"op": "eq", "name": nm, "col": "Estado", "value": st, "t": f"Equipos varios · {nm}: {st}"})
    return ops


def _tomas(s: str) -> List[Dict[str, Any]]:
    parts = re.split(r"\s*,\s*(?=(?:y\s+)?(?:para\s+)?(?:la\s+)?imp)|\s+y\s+(?:para\s+)?(?=(?:la\s+)?imp)", s.strip(" ."), flags=re.I)
    items = []
    for p in parts:
        p = re.sub(r"^(?:y\s+)?(?:para\s+)?", "", p.strip(), flags=re.I)
        m = re.match(r"(?:la\s+)?(imp\.?\s*[\wáéíóúñ]+(?:\s+en\s+[\wáéíóúñ]+)?)\s+(.*)$", p, re.I)
        if m:
            items.append({"eq": imp_name(m.group(1)), "det": _acentos(m.group(2).strip(" ."))})
    if not items:
        return []
    return [{"op": "tomas", "items": items, "t": "Equipos sin tomas cerca: " + "; ".join(f"{i['eq']}: {i['det']}" for i in items)}]


FOTO = [(r"hoja\s+de\s+(?:impresi[oó]n|prueba)|selftest", "Selftest (hoja de prueba)"), (r"etiqueta", "Etiqueta (SN y modelo)"),
        (r"conexiones|parte\s+de\s+atr[aá]s", "Conexiones")]


def _evidencias(s: str) -> List[Dict[str, Any]]:
    ops: List[Dict[str, Any]] = []
    for m in re.finditer(r"quit\w*\s+(?:la\s+)?(?:imagen|foto)\s+(?:del?\s+|de\s+la\s+)?([\wáéíóúñ ]+?)(?=\s+y\b|\s*[.,;]|$)", s, re.I):
        nm = m.group(1).strip()
        ops.append({"op": "photoDel", "title": _cap(nm), "t": f"Anexo: quitar la foto de {_cap(nm)}"})
    ops += _renombres(s)
    m = re.search(r"(?:de\s+la\s+)?impresora\s+([\wáéíóúñ]+).*?quit\w*\s+la\s+de\s+(?:la\s+)?(.+?)(?:\.|$)", s, re.I)
    if m:
        grupo = imp_name(m.group(1))
        cual = next((v for rx, v in FOTO if re.search(rx, m.group(2), re.I)), _cap(m.group(2)))
        ops.append({"op": "photoDel", "title": cual, "group": grupo, "t": f"Anexo: quitar la foto «{cual}» de {grupo}"})
    return ops


# ---- aplicar sobre el documento ------------------------------------------------------------------------------------
def _kv_tables(blocks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Tablas de datos por sección: dat (Datos generales), neg, net, caj, wifi, ene (por el h3 que las precede)."""
    out: Dict[str, Dict[str, Any]] = {}
    last = None
    for b in blocks:
        if b.get("t") in ("h2", "h3"):
            last = b.get("text")
        elif b.get("t") == "kv":
            key = next((k for k, v in SEC_LABEL.items() if v == last), None)
            if key and key not in out:
                out[key] = b
    return out


def _table_after(blocks: List[Dict[str, Any]], title: str) -> Optional[Dict[str, Any]]:
    for i, b in enumerate(blocks):
        if b.get("t") == "h3" and b.get("text") == title:
            for nb in blocks[i + 1:]:
                if nb.get("t") == "table":
                    return nb
                if nb.get("t") in ("h2", "h3"):
                    return None
    return None


def _walk_text(o: Any, fn) -> Any:
    """Aplica `fn` a todos los textos del documento (no a los tipos de bloque ni a estilos)."""
    if isinstance(o, str):
        return fn(o)
    if isinstance(o, list):
        return [_walk_text(x, fn) for x in o]
    if isinstance(o, dict):
        return {k: v if k in ("t", "cls", "color", "lastCls", "level") else _walk_text(v, fn) for k, v in o.items()}
    return o


def _rename_fn(a: str, b: str):
    suf = b[len(a):] if b.startswith(a) else ""
    rx = re.compile(re.escape(a) + (r"(?!" + re.escape(suf) + ")" if suf else "") + r"(?![\wáéíóúñ])")
    return lambda s: rx.sub(b, s)


def aplicar(doc: Dict[str, Any], ops: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Ejecuta las operaciones sobre `doc["blocks"]` (el documento que dibuja el gateway). No falla si algo no está."""
    blocks = doc.get("blocks") or []
    for o in [x for x in ops if x.get("op") == "rename"]:
        fn = _rename_fn(o["from"], o["to"])
        blocks = _walk_text(blocks, fn)
    doc["blocks"] = blocks
    kv = _kv_tables(blocks)
    prn = _table_after(blocks, "Impresoras")
    eqv = _table_after(blocks, "Equipos varios")
    rules = next((b for b in blocks if b.get("t") == "rules"), None)

    def kv_set(sec: str, label: str, value: str) -> None:
        tb = kv.get(sec)
        if tb is None:
            return
        row = next((r for r in tb["rows"] if norm(r.get("label")) == norm(label)), None)
        if row is None and sec == "caj" and tb["rows"]:
            row = tb["rows"][0]
        if row is None:
            tb["rows"].append({"label": label, "value": value, "bad": False})
        else:
            row.pop("pending", None)
            row.pop("note", None)
            row["value"], row["bad"] = value, False

    def prn_row(name: str) -> Optional[Dict[str, Any]]:
        if prn is None:
            return None
        n = norm(name).replace("imp. ", "")
        return next((r for r in prn["rows"] if norm(r["cells"][0]).replace("imp. ", "") == n), None)

    def rule_con(name: str, value: str) -> None:
        if not rules:
            return
        ok = bool(re.search(r"\bhabilitad", value, re.I)) and not re.search(r"no\s+habilitad|no\s+tiene", value, re.I)
        for r in rules["rows"]:
            if norm(r.get("rule", "")).startswith(norm(name) + " de red por cable"):
                r["result"], r["ok"] = value, ok
                r["status"] = "Cumple" if ok else "Observado"

    for o in ops:
        op = o.get("op")
        if op == "set":
            kv_set(o["sec"], o["label"], o["value"])
        elif op == "listRep":
            tb = kv.get(o["sec"])
            row = next((r for r in (tb or {}).get("rows", []) if norm(r.get("label")) == norm(o["label"])), None)
            if row is not None and row.get("value"):
                items = [x.strip() for x in row["value"].split(",")]
                items = [o["to"] if norm(x) == norm(o["from"]) else x for x in items]
                row["value"] = ", ".join(items)
        elif op == "prn":
            r = prn_row(o["name"])
            if r is not None and o["col"] in PRN_COLS:
                r["cells"][PRN_COLS.index(o["col"])] = o["value"]
                if o["col"] == "Conexión":
                    rule_con(r["cells"][0], o["value"])
        elif op == "prnWhere" and prn is not None:
            ci = PRN_COLS.index(o["col"])
            exc = {norm(x).replace("imp. ", "") for x in o.get("except") or []}
            for r in prn["rows"]:
                if norm(r["cells"][ci]) == norm(o["eq"]) and norm(r["cells"][0]).replace("imp. ", "") not in exc:
                    r["cells"][ci] = o["value"]
                    if o["col"] == "Conexión":
                        rule_con(r["cells"][0], o["value"])
        elif op == "prnAdd" and prn is not None:
            prn["rows"].append({"cells": list(o["cells"])[:6] + [""] * (6 - len(o["cells"])), "badLast": False})
        elif op == "eq" and eqv is not None:
            n = norm(o["name"])
            for r in eqv["rows"]:
                c = norm(r["cells"][0])
                if c == n or c.replace(" ", "") == n.replace(" de ", " ").replace(" ", "") or (n in c or c in n):
                    r["cells"][EQ_COLS.index(o["col"])] = o["value"]
                    if o["col"] == "Estado":
                        r["lastCls"] = "ok" if o["value"] == "Existente" else "" if o["value"].startswith("Por ") else "bad"
                    break
            else:
                # el equipo no estaba en la tabla: se agrega
                nm = _cap(o["name"])
                cells = [nm, nm.split()[0], "—", "—", "—"]
                cells[EQ_COLS.index(o["col"])] = o["value"]
                eqv["rows"].append({"cells": cells, "lastCls": "" if o["value"].startswith("Por ") else "ok"})
        elif op == "tomas":
            for i in o["items"]:
                r = prn_row(i["eq"])
                if r is not None:
                    i["eq"] = r["cells"][0]
            txt = "; ".join(f"{i['eq']}: {i['det']}" for i in o["items"])
            kv_set("ene", "Equipos sin tomas cerca", txt)
            kv_set("ene", "Tomas cerca de los equipos", "No (ver equipos sin tomas cerca)")
            names = ", ".join(i["eq"] for i in o["items"])
            for b in blocks:
                if b.get("t") == "ul":
                    for it in b.get("items") or []:
                        if it.get("b", "").startswith("Faltan tomas de energía"):
                            it["text"] = f"No hay tomas de energía cerca de: {txt}."
                        if "tomas de energía para" in (it.get("text") or ""):
                            it["text"] = re.sub(r"tomas de energía para [^;.]*", f"tomas de energía para {names}", it["text"])
        elif op == "photoDel":
            title, group = norm(o["title"]), norm(o.get("group") or "")
            kw = re.match(r"(selftest|etiqueta|conexiones)", title)
            for b in blocks:
                if b.get("t") in ("grid", "block"):
                    if group and not norm(b.get("heading", "")).startswith(group):
                        continue
                    b["cells"] = [c for c in b.get("cells") or []
                                  if not (norm(c.get("title")) == title or (kw and norm(c.get("title")).startswith(kw.group(1))))]
            doc["blocks"] = blocks = [b for b in blocks if not (b.get("t") in ("grid", "block") and not b.get("cells"))]
    return doc
