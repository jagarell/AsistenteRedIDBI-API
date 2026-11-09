"""Armado de los nodos del chat a partir de las respuestas (port de `build()` del simulador).

`build(answers)` es una función pura: recibe lo respondido hasta ahora y devuelve la
lista completa de nodos que corresponden (incluidos avisos) más `X`, el resumen de
lo levantado. El siguiente paso del chat es el primer nodo que aún no tiene respuesta.
"""
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.chat.sim.util import Obj, fmt, jsround, norm, num, parse_int, truthy, uniq

CAT: Dict[str, Any] = json.loads((Path(__file__).parent / "catalog.json").read_text(encoding="utf-8"))

CC_RE = re.compile(
    r"patio\s+(de\s+comidas?|gastron)|refugio|larcomar|real\s*plaza|jockey|plaza\s*norte|mega\s*plaza|"
    r"open\s*plaza|plaza\s*san\s*miguel|\bmall\b"
)
PERFIL: Dict[str, Dict[str, Any]] = CAT["PERFIL"]
YN = [{"v": "SI", "l": "Sí"}, {"v": "NO", "l": "No"}]
# P09c: equipo con el que los mozos toman pedidos (0.0.15). «Aún por confirmar» y «Otro (escribir)» los agrega pc_opts.
MOZ_OPTS = [{"v": "TABLET", "l": "Sí, con tablet"}, {"v": "CELULAR", "l": "Sí, con su celular"},
            {"v": "IMIN_MOVIL", "l": "Sí, con iMin móvil (toma el pedido e imprime)"},
            {"v": "NO", "l": "No, los mozos no toman pedidos con un equipo"}]
PROV = [
    {"v": "MOVISTAR", "l": "Movistar"}, {"v": "CLARO", "l": "Claro"}, {"v": "ENTEL", "l": "Entel"},
    {"v": "WIN", "l": "WIN"}, {"v": "BITEL", "l": "Bitel"}, {"v": "STARLINK", "l": "Starlink"}, {"v": "OTRO", "l": "Otro (escribir)", "otro": True},
]
# Preguntas que dependen del cliente: valor prudente cuando el técnico responde «No lo sé ahora»
PC = {"P12": 1, "P12b": "NO", "P15": "OTRO", "P16": "NS", "P17": "NS", "P09c": "PC", "P47": "NO", "P47a": 0,
      "P22g": "SI", "P22a": "NO", "P22b": "PEND", "P28h": "NO", "P33": "PC", "P28p": "PC"}
TEMA = {"P12": "el número de cajas", "P12b": "si saldrán comandas en caja", "P15": "la velocidad del plan de internet",
        "P16": "si tiene internet de respaldo", "P17": "si el local tiene caídas de internet",
        "P09c": "con qué equipo tomarán pedidos los mozos (tablet, celular o iMin móvil)", "P47": "si se conectarán cámaras a la red",
        "P47a": "cuántas cámaras irán conectadas a la red", "P22g": "si el equipo de caja se queda en el local",
        "P22a": "si ya cuenta con un Raspberry", "P22b": "qué equipo adquirirá para el sistema de impresiones",
        "P28h": "si ya tiene la impresora", "P33": "si hay tomas de energía cerca de los equipos",
        "P28p": "el estado del punto de red de la impresora"}


def pc_opts(id_: str, opts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """«Otro (escribir)» con texto libre (también en P12, P15 y P47a) + «No lo sé ahora»."""
    out = [dict(o, num=False, l="Otro (escribir)") if o.get("otro") else o for o in opts]
    if not any(o.get("otro") for o in out):
        out.append({"v": "OTRO", "l": "Otro (escribir)", "otro": True})
    out.append({"v": "NS52", "l": "Aún no lo decide" if id_ == "P22b" else
                "Aún por confirmar (sugerir iMin móvil)" if id_ == "P09c" else "No lo sé ahora"})
    return out


# Punto de red de una impresora por cable que no va directo al router (0.0.19). «Otro» y «No lo sé ahora» los agrega pc_opts.
PUNTO_OPTS = [{"v": "HAB", "l": "Habilitado (con cable y jack, listo para conectar)"}, {"v": "SINJACK", "l": "Hay cable pero sin jack"},
              {"v": "SINCABLE", "l": "No hay cable hasta ese lugar"}, {"v": "AVERIADO", "l": "Averiado (no da red)"}]
PUNTO_ALERT = {"SINJACK": "el punto de red tiene cable pero no jack: colocar el jack antes del inicio.",
               "SINCABLE": "no hay cable de red hasta la impresora: tender el cable y colocar el punto de red.",
               "AVERIADO": "el punto de red está averiado: repararlo o cambiarlo."}
# Descripción de la foto de una impresora (0.0.19 · C1/C2): la IA deduce sin preguntar si es de otro lugar o si aún no existe.
AJENA_RE = re.compile(r"otro local|otro negocio|ajen[ao]|no es del local|no pertenece|del t[eé]cnico|de la competencia", re.I)
IMPL_RE = re.compile(r"por implementar|a[uú]n no (hay|tiene|existe|est[aá]|se instal)|todav[ií]a no (hay|tiene|existe|est[aá]|se instal)|no existe|falta instalar|no hay impresora", re.I)
PUNTO_TXT = {"SINJACK": "sin jack", "SINCABLE": "sin cable", "AVERIADO": "averiado"}
PUNTO_TRABAJO = {"SINJACK": "colocar el jack del punto de red", "SINCABLE": "tender el cable y colocar el punto de red",
                 "AVERIADO": "reparar el punto de red"}
EV_KINDS = ["ev", "check", "rcard", "links", "summary"]
SYS_IMP_DEFAULT = "Wrapper"  # nombre del sistema de impresiones de la empresa (Preguntas y reglas del administrador)


def sys_imp_n(ctx: Optional[Dict[str, Any]] = None) -> str:
    return ((ctx or {}).get("sysImp") or SYS_IMP_DEFAULT).strip() or SYS_IMP_DEFAULT


INST47 = {"VISTA": "A la vista, a 1–1.5 m del suelo", "PISO": "A la vista, cerca al piso",
          "MUEBLE": "Dentro de un mueble cerrado con puertas", "CUARTO": "En un cuarto pequeño con puertas"}
_W45 = {"uno": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5"}


def det45(t: str) -> List[str]:
    """Detalle de la ubicación del router escrito por el técnico (altura, mueble, cuarto, paredes, medidas)."""
    s = str(t or "").lower()
    out: List[str] = []
    if re.search(r"ras del (suelo|piso)|cerca (al|del) (piso|suelo)|en el piso|en el suelo", s):
        out.append("casi al ras del suelo")
    if re.search(r"mueble|gabinete|armario|cl[oó]set", s):
        out.append("dentro de un mueble cerrado" + (" con puertas de melamina" if "melamin" in s else ""))
    if re.search(r"cuarto (peque|chico|reducido)", s):
        out.append("en un cuarto pequeño")
    if re.search(r"paredes? gruesas?", s):
        out.append("entre paredes gruesas")
    dims: List[str] = []
    rx = r"(\d+(?:[.,]\d+)?|uno|dos|tres|cuatro|cinco)\s*(?:metros?|m)\s*(y medio\s*)?(?:de\s*)?(profundidad|altura|altitud|alto|ancho)"
    for m in re.finditer(rx, s):
        v = _W45.get(m.group(1)) or m.group(1).replace(",", ".")
        if m.group(2):
            v = fmt(float(v) + 0.5)
        k = "alto" if m.group(3) in ("altitud", "altura") else m.group(3)
        dims.append(f"{v} m de {k}")
    if dims:
        if "en un cuarto pequeño" in out:
            out[out.index("en un cuarto pequeño")] = "en un cuarto pequeño (" + ", ".join(dims) + ")"
        else:
            out.append("cuarto de " + ", ".join(dims))
    return out


def q46(name: str) -> Dict[str, int]:
    """Resultado de los pings a una impresora (en la app lo mide el celular; aquí es determinístico)."""
    h = 0
    for c in str(name):
        h = (h * 31 + ord(c)) % 997
    return {"lat": 1 + h % 7, "loss": 4 if h % 7 == 3 else 0}


def fmt_date(s: Any) -> Any:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else s


def is_ev_step(n: Dict[str, Any]) -> bool:
    return n["kind"] in EV_KINDS or n["id"] == "EVO" or re.match(r"^P28[bcup]?#", n["id"]) is not None


def ch(id_: str, b: str, text: str, opts: List[Dict[str, Any]], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    node = {"id": id_, "b": b, "kind": "choice", "text": text, "opts": opts}
    node.update(extra or {})
    return node


def _valid_ruc(t: str) -> str:
    return "" if re.fullmatch(r"(10|15|17|20)\d{9}", t) else "El RUC debe tener 11 dígitos y empezar con 10, 15, 17 o 20."


def _valid_cel(t: str) -> str:
    return "" if re.fullmatch(r"(\+?51)?9\d{8}", t) else "El celular debe tener 9 dígitos y empezar con 9."


def _valid_mail(t: str) -> str:
    return "" if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", t) else "Ingresa un correo válido."


P18I = ch("P18i", "C", "En la foto de ubicación, ¿cómo está instalado el router?",
          [{"v": "VISTA", "l": INST47["VISTA"]}, {"v": "PISO", "l": INST47["PISO"]}, {"v": "MUEBLE", "l": INST47["MUEBLE"]},
           {"v": "CUARTO", "l": INST47["CUARTO"]}, {"v": "OTRO", "l": "Otro (describir: altura, mueble, paredes, medidas)", "otro": True}],
          {"def": "VISTA"})


def build(a: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], Obj]:
    ctx = ctx or {}
    N: List[Dict[str, Any]] = []
    X = Obj()

    def v(id_: str) -> Any:
        e = a.get(id_)
        return e.get("v") if e else None

    def push(n: Dict[str, Any]) -> Dict[str, Any]:
        if n.get("kind") == "choice" and str(n["id"]).split("#")[0] in PC and not n.get("pc_done"):
            n = dict(n, opts=pc_opts(str(n["id"]).split("#")[0], n["opts"]), pc_done=True)
        N.append(n)
        return n

    def lab(id_: str) -> Any:
        e = a.get(id_)
        return e.get("label") if e else None

    tecnico = ctx.get("technician") or "Técnico de prueba"
    today_iso = ctx.get("todayIso") or "2026-10-11"

    push({"id": "P01", "b": "A", "kind": "text", "text": "¿Cuál es el nombre de la razón social?", "sug": [],
          "ph": "Escribe la razón social", "def": "Inversiones Ejemplo S.A.C."})
    X.razon = lab("P01")
    if a.get("P01"):
        push({"id": "P01b", "b": "A", "kind": "text", "text": "¿Cuál es el RUC?", "sug": ["No lo tengo ahora"], "ph": "RUC de 11 dígitos",
              "num": True, "valid": _valid_ruc, "def": "20601234567"})
    X.ruc = lab("P01b")
    if a.get("P01b"):
        push({"id": "P01c", "b": "A", "kind": "text", "text": "¿Cuál es el nombre del local?", "sug": [],
              "ph": "Escribe el nombre del local", "def": "Restaurante Demo"})
    X.nombre = lab("P01c")
    if a.get("P01c"):
        push({"id": "P03", "b": "A", "kind": "text",
              "text": "¿Cuál es la dirección del local? Si está en un centro comercial, escribe su nombre.",
              "sug": CAT["DIR_SUG"], "ph": "Escribe la dirección", "def": "Av. Benavides 1520, Miraflores"})
    dir_ = v("P03")
    X.dir = dir_
    X.cc = dir_ is not None and bool(CC_RE.search(norm(dir_)))
    if X.cc:
        push({"id": "I_PATIO", "kind": "alert", "tone": "info", "tag": "PATIO",
              "text": "La dirección está en el patio de comidas de un centro comercial grande. Se suma el modificador de patio sin preguntar."})
    if dir_ is not None:
        push({"id": "P04", "b": "A", "kind": "text", "text": "¿Quién es el encargado del local? (nombre y cargo)", "sug": ["No está en el local"],
              "ph": "Nombre y cargo del encargado", "def": "Carlos Pérez, administrador"})
    X.encargado = lab("P04")
    if a.get("P04"):
        push({"id": "P05", "b": "A", "kind": "text",
              "text": "¿Cuál es el número de celular del encargado? Sirve para compartirle la minuta por WhatsApp.",
              "sug": ["Saltar"], "ph": "Celular (9 dígitos)", "num": True, "valid": _valid_cel, "def": "987654321"})
    X.celular = a["P05"]["v"] if a.get("P05") and a["P05"].get("v") else None
    if a.get("P05"):
        push({"id": "P05b", "b": "A", "kind": "text", "text": "¿Cuál es el correo del encargado? Sirve para enviarle la minuta.",
              "sug": ["Saltar"], "ph": "correo@cliente.com", "valid": _valid_mail, "def": "encargado@cliente.com"})
    X.correo = a["P05b"]["v"] if a.get("P05b") and a["P05b"].get("v") else None
    if a.get("P05b"):
        push({"id": "P06", "b": "A", "kind": "date", "req": True, "text": "Fecha de la visita", "def": today_iso})
    X.fechaVisita = fmt_date(a["P06"]["v"]) if a.get("P06") and a["P06"].get("v") else None
    if a.get("P06"):
        push({"id": "P07", "b": "A", "kind": "text", "text": "Técnico responsable", "sug": [tecnico],
              "ph": "Nombre del técnico", "def": tecnico})
    X.tecnico = lab("P07")
    if a.get("P07"):
        push(ch("P08", "A", "¿Cuál es el estado del local?", CAT["ESTADOS"], {"def": "EN_OPERACION"}))
    X.estadoV = v("P08")
    X.estadoL = lab("P08")
    if a.get("P08"):
        push(ch("P09", "B", "¿Qué tipo de negocio es?",
                [{"v": k, "l": l, "otro": k == "OTRO"} for k, l in CAT["RUBROS"]], {"def": "RESTAURANTE"}))
    rub = v("P09")
    X.rub = rub
    X.rubL = lab("P09")
    P = PERFIL.get(rub) or PERFIL["OTRO"]
    X.P = P
    # «Otro» rubro: flujo completo, como un restaurante o una discoteca, pero sin opciones marcadas de antemano.
    X.simple = rub == "RETAIL"
    X.otroRub = rub == "OTRO"
    est = X.estadoV
    X.obra = est == "EN_OBRA"
    X.inaug = est == "POR_INAUGURAR"
    X.anterior = est == "SISTEMA_ANTERIOR"
    X.mozosQ = rub in CAT["MOZOS"] or rub == "OTRO"
    # P09c (mozos con tablet) se pregunta al final, justo antes del WiFi por zona
    moz_ready = True
    prep: List[str] = []
    if rub and moz_ready:
        if X.simple:
            retail = rub == "RETAIL"
            push({"id": "I_RETAIL", "kind": "alert", "tone": "info", "tag": "RETAIL" if retail else "OTRO",
                  "text": f"En {'retail' if retail else 'este rubro'} los lugares de preparación no tienen impresora asignada. "
                          "Indícalos solo como referencia (por ejemplo, almacén). No se piden evidencias de ellos."})
            o = ["Almacén", "Trastienda", "Panadería", "Carnicería"] if retail else ["Almacén", "Cocina", "Barra", "Trastienda", "Taller"]
            push({"id": "P11r", "b": "B", "kind": "multi",
                  "text": "¿Qué lugares de preparación tiene el local? (solo referencia, por ejemplo almacén)",
                  "opts": o, "sel": ["Almacén"] if retail else [], "none": "Ninguno", "def": ["Almacén"], "min": 1})
            X.prepRef = a["P11r"]["v"] if a.get("P11r") and isinstance(a["P11r"].get("v"), list) else []
        else:
            pre = P["prep"]
            un = re.sub(r"^(Un|Una) ", "", P["un"])
            un = "el local" if un == "El local" else un
            push({"id": "P11e", "b": "B", "kind": "multi",
                  "text": (f"¿Qué áreas de preparación tiene el local? Ya marqué las más comunes en {un}; puedes quitarlas o agregar otras."
                           if pre else "¿Qué áreas de preparación tiene el local? Márcalas o escríbelas con Otro."),
                  "opts": uniq([*pre, *CAT["PREP_ALL"]]), "sel": pre, "def": pre if pre else ["Cocina"],
                  **({"none": "Ninguna: no prepara productos", "min": 0} if X.otroRub else {"min": 1})})
            prep = v("P11e") or []
    X.prep = prep
    X.prepRef = X.prepRef or []
    prep_ready = bool(rub and moz_ready and (bool(a.get("P11r")) if X.simple else bool(a.get("P11e"))))
    if prep_ready:
        push({"id": "P11f", "b": "B", "kind": "multi",
              "text": ("¿Qué canales de atención tiene el local? Ya marqué los más comunes para este rubro; puedes quitarlos o agregar otros."
                       if P["canales"] else "¿Qué canales de atención tiene el local? Puedes elegir varios."),
              "opts": CAT["CANALES"], "sel": P["canales"], "def": P["canales"] if P["canales"] else ["Mesa"], "min": 1})
    canales = v("P11f") or []
    X.canales = canales
    zonas: List[Dict[str, str]] = []
    for c in canales:
        id_ = "P11g#" + c
        base = uniq([*P["mesa"], *CAT["MESA_ALL"]]) if c == "Mesa" else CAT["ZONAS_CANAL"].get(c, [])
        push({"id": id_, "b": "B", "kind": "multi",
              "text": f"¿Qué zonas de atención tiene {c}?{'' if base else ' Escríbelas con Otro.'}",
              "opts": base, "sel": P["mesa"] if c == "Mesa" else [],
              "def": (P["mesa"] if P["mesa"] else ["Salón 1"]) if c == "Mesa" else ([base[0]] if base else ["Zona " + c]),
              "min": 1})
        for z in (v(id_) or []):
            zonas.append({"z": z, "canal": c})
    X.zonas = zonas
    zonas_ready = bool(canales) and all(a.get("P11g#" + c) for c in canales)
    if zonas_ready:
        push({"id": "P12", "b": "B", "kind": "choice", "text": "¿Cuántas cajas hay o va a haber?", "unit": "cajas",
              "opts": [{"v": n, "l": str(n)} for n in (1, 2, 3, 4, 5, 6)] + [{"v": "OTRO", "l": "Otro (escribir)", "otro": True, "num": True}],
              "def": 1})
    p12 = v("P12")
    if isinstance(p12, (int, float)) and not isinstance(p12, bool):
        cajas: Optional[int] = p12
    elif a.get("P12"):
        cajas = max(1, parse_int(lab("P12")) or 1)
    else:
        cajas = None
    X.cajas = cajas or 0
    prep_prn = [] if X.simple else prep
    if cajas and cajas > 0 and prep_prn:
        sug = P.get("caja") if P.get("caja") and P["caja"] in prep_prn else None
        push(ch("P12e", "B", "¿La caja comparte impresora con alguna área de preparación?",
                [{"v": "NO", "l": "No, la caja tiene su propia impresora"},
                 *[{"v": p, "l": p + (" (lo más común)" if p == sug else "")} for p in prep_prn],
                 {"v": "OTRO", "l": "Otro (escribir)", "otro": True}], {"def": sug or "NO"}))
    X.comparte = v("P12e") if v("P12e") in prep_prn else None
    p12e_ready = cajas is not None and (not (cajas > 0 and prep_prn) or bool(a.get("P12e")))
    if p12e_ready and not X.simple:
        push(ch("P12b", "B", "¿En caja saldrán comandas?", YN, {"def": "NO"}))
    X.sunmi = bool(rub) and not X.simple and not prep and v("P12b") == "SI"
    if X.sunmi:
        push({"id": "A_SUNMI", "kind": "alert", "tone": "info", "tag": "A_SUNMI",
              "text": "La comanda sale solo en caja. Recomienda un Sunmi con chip (comprobantes, pre-cuentas y comandas). Se cotiza con Desarrollo de Negocios."})
    b_ready = p12e_ready and (X.simple or bool(a.get("P12b")))

    printers: List[Obj] = [Obj(name=p, prep=True, shared=p == X.comparte) for p in prep_prn]
    for i in range(1, X.cajas + 1):
        if i == 1 and X.comparte:
            continue
        printers.append(Obj(name=f"Caja {i}" if X.cajas > 1 else "Caja", prep=False))
    X.printers = printers
    X.seg = "192.168.1"

    def eq_caja_name(i: int) -> str:
        return f"Equipo de caja {i}" if X.cajas > 1 else "Equipo de caja"

    # F · energía (antes de las fotos)
    X.devices = []
    f_ready = b_ready
    if b_ready and not X.simple:
        X.devices = ["Router", *[eq_caja_name(i + 1) for i in range(X.cajas)], *[f"IMP. {p.name}" for p in printers]]
        push(ch("P33", "F",
                "¿Ya hay tomas de energía (instaladas o por instalar) donde irán el router, el equipo de caja y las impresoras?"
                if X.obra else "¿Hay tomas de energía cerca del router, el equipo de caja y las impresoras?", YN, {"def": "SI"}))
        if v("P33") == "NO":
            push({"id": "P33a", "b": "F", "kind": "multi", "text": "¿Qué equipos no tienen tomas de energía cerca? Puedes marcar varios.",
                  "opts": X.devices, "sel": [], "none": "Ninguno: ningún equipo tiene tomas cerca", "def": X.devices[:1], "min": 1})
        if a.get("P33a"):
            push({"id": "P33b", "b": "F", "kind": "longtext",
                  "text": "¿Recomendarías un supresor de picos? ¿El cliente va a implementar tomas cerca? Dame tus apreciaciones para tenerlas en cuenta.",
                  "ph": "Escribe tus apreciaciones (por ejemplo: recomiendo supresor de picos para la caja; el cliente instalará las tomas la próxima semana)",
                  "def": "Recomiendo un supresor de picos para la caja. El cliente instalará las tomas antes del inicio."})
        f0 = v("P33") in ("SI", "PC") or (v("P33") == "NO" and bool(a.get("P33b")))
        if f0:
            push(ch("P34c", "F",
                    "¿Algún cable de red pasa cerca o por detrás de electrodomésticos (licuadoras, congeladoras, refrigeradoras, microondas u otros)?",
                    YN, {"def": "NO"}))
        f_ready = f0 and bool(a.get("P34c"))
    X.tomas = v("P33")
    X.ningunaToma = bool(a.get("P33a") and a["P33a"].get("label") and re.match(r"^Ninguno", a["P33a"]["label"]))
    X.sinEnergia = list(X.devices) if X.ningunaToma else (a["P33a"]["v"] if a.get("P33a") else [])
    X.apreciacion = a["P33b"]["v"] if a.get("P33b") else ""
    if X.tomas == "NO":
        X.energiaTxt = ("Ningún equipo tiene tomas de energía cerca." if X.ningunaToma
                        else f"No hay tomas de energía cerca de: {', '.join(X.sinEnergia)}.")
    else:
        X.energiaTxt = ""
    X.cableElec = v("P34c") == "SI"
    if X.cableElec:
        push({"id": "A_ELEC", "kind": "alert", "tone": "warn", "tag": "ESTÁTICA",
              "text": "Aísla el cable de red de la estática y la interferencia de los electrodomésticos: pásalo por canaleta o tubo, sepáralo del equipo y del cable de energía, y usa cable apantallado (FTP) si no se puede desviar."})

    def toma(name: str) -> bool:
        return (not X.obra) and (not X.simple) and X.tomas in ("SI", "NO") and name not in X.sinEnergia

    def con_toma(name: str, txt: str) -> str:
        return txt + " Toma la foto mostrando también la toma de energía cercana a la que está conectado." if toma(name) else txt

    # C · internet
    PLAN = {"b": "C", "kind": "choice", "text": "¿De cuánto es su plan de internet? (Mbps)", "unit": "Mbps",
            "opts": [{"v": n, "l": f"{n} Mbps"} for n in (300, 500, 1000)] + [{"v": "OTRO", "l": "Otro (escribir)", "otro": True, "num": True}],
            "def": 500}
    con: Optional[str] = None
    ready = False
    if f_ready:
        if X.simple:
            push({"id": "P15", **PLAN})
            con = "PLAN" if a.get("P15") else None
            ready = bool(a.get("P15"))
        else:
            push(ch("P14", "C", "¿El cliente ya tiene internet contratado? ¿Qué tipo de conexión tendrá?" if X.obra
                    else "¿Qué tipo de conexión tiene?", CAT["CONEX"], {"def": "POR_CONTRATAR" if X.obra else "FIBRA"}))
            con = v("P14")
            if con and con not in ("NO_TIENE", "POR_CONTRATAR"):
                push(ch("P13", "C", "¿Qué proveedor de internet tiene contratado?" if X.inaug else "¿Quién es el proveedor de internet?",
                        PROV, {"def": "MOVISTAR"}))
                if a.get("P13"):
                    push({"id": "P15", **PLAN})
                ask_hist = not X.obra and not X.inaug and not X.anterior
                if a.get("P15") and ask_hist:
                    push(ch("P16", "C", "¿Tiene un internet de respaldo?", YN, {"def": "NO"}))
                if a.get("P16") and ask_hist:
                    push(ch("P17", "C", "¿El local tiene caídas de internet?", YN, {"def": "NO"}))
                ready = bool(a.get("P15")) and (not ask_hist or v("P17") is not None)
            elif con == "POR_CONTRATAR":
                # 0.0.16 (C4): aunque el cliente va a contratar, se anota qué tipo de conexión y con qué proveedor (Starlink, otro)
                push(ch("P14t", "C", "¿Qué tipo de conexión va a contratar?",
                        [o for o in CAT["CONEX"] if o["v"] not in ("NO_SE", "NO_TIENE", "POR_CONTRATAR")], {"def": "FIBRA"}))
                if a.get("P14t"):
                    push(ch("P13", "C", "¿Con qué proveedor va a contratar?", PROV, {"def": "MOVISTAR"}))
                ready = bool(a.get("P14t")) and bool(a.get("P13"))
            else:
                ready = con == "NO_TIENE"
    X.con = None if X.simple else con
    X.conL = (("Por contratar · " + lab("P14t")) if a.get("P14t") else lab("P14")) if a.get("P14") else ("Internet del local" if X.simple and a.get("P15") else None)
    X.sinInt = con == "NO_TIENE"
    X.porContratar = con == "POR_CONTRATAR"
    X.hasInt = bool(con) and not X.sinInt and not X.porContratar
    X.proveedor = lab("P13")
    p15 = v("P15")
    if isinstance(p15, (int, float)) and not isinstance(p15, bool):
        X.plan = p15
    elif a.get("P15") and a["P15"].get("v") == "OTRO":
        X.plan = parse_int(a["P15"].get("label")) or None
    else:
        X.plan = None
    X.motivos = []
    if ready:
        if v("P17") == "SI":
            X.motivos.append("tiene caídas de internet")
        if X.sinInt:
            X.motivos.append("no tiene proveedor de internet")
        if X.cc:
            X.motivos.append("está en el patio de comidas de un centro comercial grande")
    X.r56 = ready and len(X.motivos) > 0
    if ready and X.sinInt:
        push({"id": "A_SININT", "kind": "alert", "tone": "bad", "tag": "0 %",
              "text": "El local no tiene internet: Conectividad 0 %. Haz la prueba de señal del chip (o sáltala y queda pendiente por validar); luego seguimos con las cajas."})
    if ready and X.porContratar:
        push({"id": "A_PORCONT", "kind": "alert", "tone": "info", "tag": "POR CONTRATAR",
              "text": "El cliente va a contratar internet antes de implementar. No se recomienda TP-Link con chip: se pide contratar el internet y una segunda visita para validar la conectividad. Seguimos con las cajas."})
    if X.r56:
        push({"id": "A_R56", "kind": "alert", "tone": "warn", "tag": "R56",
              "text": f"El local {', '.join(X.motivos)}. Recomienda independizar la red con un TP-Link con entrada de chip + chip del proveedor con mejor señal, plan básico (plan superior si se conectan cámaras), solo para las impresoras y el equipo del sistema de impresiones. Reemplaza al internet del local para la impresión."})
    chip_q = ready and (X.sinInt or (X.hasInt and not X.obra and (X.r56 or X.sunmi)))
    if chip_q:
        push(ch("P14b", "C", "Pon el chip en un celular dentro del local. ¿Qué chip tiene señal?",
                [{"v": "ENTEL", "l": "Entel"}, {"v": "CLARO", "l": "Claro"}, {"v": "AMBOS", "l": "Ambos"}, {"v": "NINGUNO", "l": "Ninguno"},
                 {"v": "SALTAR", "l": "Saltar prueba (queda pendiente por validar)"}], {"def": "AMBOS"}))
        if v("P14b") == "SALTAR":
            push({"id": "A_CHIPPEND", "kind": "alert", "tone": "warn", "tag": "PENDIENTE",
                  "text": "La prueba de señal del chip queda pendiente por validar. Seguimos con las cajas."})
        if v("P14b") and v("P14b") not in ("NINGUNO", "SALTAR"):
            push({"id": "E1b", "b": "C", "kind": "ev", "read": "chip", "name": "el speedtest del chip",
                  "text": "Sube la captura del speedtest hecho desde el celular con el chip.", "def": {"data": {"d": 25, "u": 8, "p": 40}}})
        if v("P14b") == "NINGUNO":
            push({"id": "A_SINCHIP", "kind": "alert", "tone": "bad", "tag": "CHIP",
                  "text": "Ningún chip tiene señal. Evaluar internet satelital y programar una segunda visita."})
    X.chip = v("P14b")
    X.chipL = lab("P14b")
    X.chipProv = CAT["CHIP_PROV"].get(X.chip) if X.chip else None
    chip_ready = (not chip_q) or (X.chip in ("NINGUNO", "SALTAR") or bool(a.get("E1b")))
    c_block_ready = ready and chip_ready and not X.hasInt
    if X.hasInt and ready and chip_ready:
        areas_local = uniq([*(["Caja"] if X.cajas > 0 else []), *prep, *[z["z"] for z in zonas]])
        pisos = [{"v": p, "l": p} for p in ("Piso 1", "Piso 2", "Piso 3") if p not in areas_local]
        router_opts = [*[{"v": z, "l": z} for z in areas_local], *pisos, {"v": "OTRO", "l": "Otro (escribir)", "otro": True}]
        if X.obra and X.simple:
            c_block_ready = True
            X.testDone = False
        elif X.obra:
            push(ch("P18", "C", "¿Dónde irá ubicado el router?", router_opts, {"def": areas_local[0] if areas_local else "OTRO"}))
            if a.get("P18"):
                push({"id": "E2u", "b": "C", "kind": "ev", "read": "photo", "name": "dónde irá el router",
                      "text": "Sube una foto del lugar donde irá el router.", "def": {"data": {}}})
            if a.get("E2u") and not X.obra:
                push(P18I)
            c_block_ready = bool(a.get("E2u"))
            X.testDone = False
        else:
            if X.simple:
                eq = "PC_CAJA_CABLE"
            else:
                push(ch("P19a", "C",
                        "Speedtest del plan: conecta una PC o laptop por cable de red (Cat6) a un puerto RJ45 gigabit del router principal y haz 2 pruebas. ¿Desde qué equipo hiciste la prueba?",
                        [{"v": "PC_CAJA_CABLE", "l": "Equipo de caja conectado por cable de red directo al router"},
                         {"v": "LAPTOP_CABLE", "l": "Laptop del técnico conectada directo al router"},
                         {"v": "WIFI", "l": "Por WiFi"},
                         {"v": "OTRO_EQ", "l": "Otro equipo del local conectado directo al router"}], {"def": "PC_CAJA_CABLE"}))
                eq = v("P19a")
                if eq == "WIFI":
                    push(ch("P19w", "C", "La prueba de internet debe hacerse por cable de red directo al router.",
                            [{"v": "PC_CAJA_CABLE", "l": "He repetido la prueba con el equipo de caja por cable directo al router"},
                             {"v": "LAPTOP_CABLE", "l": "He repetido con mi laptop conectada por cable directo al router"},
                             {"v": "SKIP", "l": "Saltar: plan sin verificar"}], {"def": "SKIP"}))
                    eq = v("P19w")
            X.cableTest = eq in ("PC_CAJA_CABLE", "LAPTOP_CABLE", "OTRO_EQ")
            X.testDone = eq is not None
            if X.cableTest:
                push({"id": "E1", "b": "C", "kind": "ev", "read": "speed", "name": "el speedtest",
                      "text": "Sube la captura de las 2 pruebas con la descarga, la subida y el ping.",
                      "def": {"data": {"d1": 520, "d2": 540, "u": 300, "p": 6, "pd": 40, "pu": 35}}})
            sp_done = X.testDone and (not X.cableTest or bool(a.get("E1")))
            if sp_done:
                push({"id": "E1c", "b": "C", "kind": "ev", "read": "ipconfig", "name": "el ipconfig",
                      "text": "En la PC o laptop conectada a la red abre la consola (cmd), escribe ipconfig y sube la foto donde se vean la IP, la máscara y la puerta de enlace.",
                      "def": {"data": {"ip": "192.168.1.35", "mascara": "255.255.255.0", "gw": "192.168.1.1"}}})
            if a.get("E1c"):
                push({"id": "E1d", "b": "C", "kind": "ev", "read": "scanner", "name": "el escáner de IP",
                      "text": "Abre el IP scanner (Advanced IP Scanner u otro), escanea la red y sube la captura con la lista de equipos encontrados.",
                      "def": {"data": {"equipos": 8, "impresoras": "192.168.1.40, 192.168.1.41, 192.168.1.42",
                                       "otros": "Router 192.168.1.1, PC 192.168.1.35", "cam": "", "camIps": 0}}})
            ip_done = bool(a.get("E1d"))
            if ip_done and not X.simple:
                push(ch("P18", "C", "¿En dónde se encuentra ubicado el router?", router_opts, {"def": areas_local[0] if areas_local else "OTRO"}))
                if a.get("P18"):
                    push({"id": "E2u", "b": "C", "kind": "ev", "read": "photo", "name": "la ubicación del router",
                          "text": con_toma("Router", "Sube una foto de dónde está ubicado el router (que se vea el lugar y cómo está instalado)."),
                          "def": {"data": {}}})
                if a.get("E2u") and not X.obra:
                    push(P18I)
                if a.get("E2u"):
                    push({"id": "E2", "b": "C", "kind": "ev", "read": "photo", "name": "los puertos del router",
                          "text": "Sube una foto del router donde se vean todos sus puertos.", "def": {"data": {}}})
                if a.get("E2"):
                    push({"id": "E2e", "b": "C", "kind": "ev", "read": "photo", "name": "la etiqueta del router",
                          "text": "Sube una foto de la etiqueta del router donde se vean la marca, el modelo y el número de serie (SN).",
                          "def": {"data": {}}})
                if a.get("E2e"):
                    e1c = a.get("E1c")
                    gw = (e1c.get("data") or {}).get("gw") if e1c and e1c.get("data") else None
                    push({"id": "RCARD", "b": "C", "kind": "rcard",
                          "text": "Con las 3 fotos del router leí estos datos. Valídalos; si algo no se lee o no es correcto, toca Corregir.",
                          "def": {"ip": gw or "192.168.1.1", "proveedor": X.proveedor or "", "marca": "Huawei", "modelo": "HG8145V5",
                                  "sn": "48575443A1B2C3D4", "puertos": 4, "libres": 2, "ocupados": 2,
                                  "ssid": "MOVISTAR_7A21", "clave": "K7pQ2mR9tL4x"}})
                c_block_ready = bool(a.get("RCARD"))
            elif ip_done:
                c_block_ready = True
    e1c = a.get("E1c")
    ipc = e1c.get("data") if e1c and e1c.get("v") == "OK" else None
    if ipc and ipc.get("gw"):
        X.seg = ".".join(str(ipc["gw"]).split(".")[:3])
    X.ipconfig = ipc
    e1d = a.get("E1d")
    X.scanner = e1d.get("data") if e1d and e1d.get("v") == "OK" else None
    X.camGrab = (X.scanner.get("cam") or None) if X.scanner else None
    X.camIps = (num(X.scanner.get("camIps")) if X.scanner else 0)
    X.routerUbic = lab("P18")
    X.routerInst = None
    X.routerEnc = None
    x18 = a.get("P18i")
    if x18 and a.get("E2u") and not X.obra:
        lbl = x18.get("label") or ""
        if x18.get("v") == "OTRO":
            d = det45(lbl)
            X.routerInst = " · ".join(d) if d else lbl
            if re.search(r"mueble|gabinete|armario|cl[oó]set|cuarto|ras del|piso|suelo", lbl, re.I):
                X.routerEnc = X.routerInst
        else:
            X.routerInst = INST47.get(x18.get("v")) or lbl
            if x18.get("v") != "VISTA":
                X.routerEnc = X.routerInst
    X.router = a["RCARD"]["v"] if a.get("RCARD") else None
    libres = X.router.get("libres") if X.router else None
    X.libres = num(libres) if X.router and libres is not None and libres != "" else None
    X.routerEtq = ({"marca": X.router.get("marca"), "modelo": X.router.get("modelo"), "sn": X.router.get("sn")} if X.router else None)

    # D · cajas
    X.cajasInfo = []
    rub_ = rub
    if c_block_ready:
        for i in range(1, X.cajas + 1):
            k = "#" + str(i)
            nm = f"Caja {i}" if X.cajas > 1 else "Caja"
            sfx = f" (caja {i})" if X.cajas > 1 else ""
            eqn = eq_caja_name(i)
            if i > 1 and not X.cajasInfo[i - 2].done:
                break
            push(ch("P22" + k, "D", f"¿Cuál es el equipo de caja{sfx}?",
                    [{"v": "SI", "l": "PC o laptop"}, {"v": "TABLET", "l": "Tablet"}, {"v": "SUNMI", "l": "Sunmi"}, {"v": "IMIN", "l": "iMin"},
                     {"v": "NO", "l": "No tiene"}, {"v": "NO_SE", "l": "No sé"}, {"v": "OTRO", "l": "Otro (escribir)", "otro": True}], {"def": "SI"}))
            e = v("P22" + k)
            info = Obj(i=i, nm=nm, eqName=eqn, eq=e, eqL=lab("P22" + k))
            if e == "SI":
                if rub_ == "DISCOTECA_BAR":
                    push(ch("P22g" + k, "D", f"¿El equipo de caja{sfx} se queda en el local de forma permanente?", YN, {"def": "SI"}))
                if rub_ != "DISCOTECA_BAR" or v("P22g" + k) is not None:
                    push(ch("P23" + k, "D", f"¿Cómo se conecta el equipo de caja{sfx} a la red?",
                            [{"v": "CABLE", "l": "Cable de red"}, {"v": "WIFI", "l": "WiFi"}], {"def": "CABLE"}))
                if v("P23" + k) == "WIFI":
                    push(ch("P23w" + k, "D", f"¿En el equipo de caja{sfx} está el sistema de impresiones ({sys_imp_n(ctx)})?", YN, {"def": "SI"}))
                info.sysImp = (v("P23w" + k) != "NO") if v("P23" + k) == "WIFI" else True
                info.pcCable = v("P23" + k) == "CABLE"
                info.pcWifi = v("P23" + k) == "WIFI"
                info.temporal = v("P22g" + k) == "NO"
                if info.temporal and v("P23" + k) is not None:
                    push({"id": "A_R60" + k, "kind": "alert", "tone": "warn", "tag": "R60",
                          "text": f"El equipo de caja{sfx} no se queda en el local. Recomienda un Raspberry para el sistema de impresiones."})
            if e == "TABLET":
                push({"id": "A_TAB" + k, "kind": "alert", "tone": "warn", "tag": "TABLET",
                      "text": f"El equipo de caja{sfx} es una tablet. Es obligatorio un kit Raspberry para el controlador de impresiones y las impresoras deben ser de red."})
            if e in ("SUNMI", "IMIN") and X.anterior:
                push({"id": "A_PROV" + k, "kind": "alert", "tone": "warn", "tag": "PROVEEDOR",
                      "text": f"El equipo de caja{sfx} es un {'Sunmi' if e == 'SUNMI' else 'iMin'}. Si no es de Desarrollo de Negocios, no se puede usar porque pertenece a otro proveedor. Tómalo en cuenta."})
            solo_caja = (not prep) or (len(prep) == 1 and X.comparte == prep[0])
            if e in ("SUNMI", "IMIN"):
                push(ch("P22i" + k, "D", f"¿El {'Sunmi' if e == 'SUNMI' else 'iMin'}{sfx} tiene impresora integrada?",
                        [{"v": "SI", "l": "Sí, tiene impresora"}, {"v": "NO", "l": "No, solo es pantalla"},
                         {"v": "FOTO", "l": "No sé el modelo (enviar foto)"}], {"def": "SI"}))
                info.impInt = v("P22i" + k) != "NO"
            info.posPropio = e in ("SUNMI", "IMIN") and info.impInt is not False and (X.simple or solo_caja)
            sin_pc = (not info.posPropio) and (e in ("TABLET", "SUNMI", "IMIN", "NO", "NO_SE", "OTRO") or (bool(info.temporal) and v("P23" + k) is not None))
            if sin_pc and not X.simple:
                push(ch("P22a" + k, "D", f"¿El cliente ya cuenta con un Raspberry{sfx}?", YN, {"def": "NO"}))
                if v("P22a" + k) == "SI":
                    push(ch("P22c" + k, "D", "¿Cómo se conecta el Raspberry a la red?",
                            [{"v": "CABLE", "l": "Cable de red"}, {"v": "WIFI", "l": "WiFi"}], {"def": "CABLE"}))
                adq_r = v("P22b" + k) == "RASPBERRY"
                if a.get("P22c" + k) or adq_r:
                    push(ch("P22d" + k, "D",
                            "¿A qué equipo de red principal irá conectado el Raspberry cuando se implemente?" if adq_r
                            else "¿A qué equipo de red principal va conectado el Raspberry?",
                            [{"v": "ROUTER", "l": "Al router"}, {"v": "SWITCH", "l": "A un switch"}, {"v": "REPETIDOR", "l": "A un repetidor"},
                             {"v": "AP", "l": "A un access point"}, {"v": "OTRO", "l": "Otro (escribir)", "otro": True}], {"def": "ROUTER"}))
                if a.get("P22d" + k):
                    if v("P22c" + k) == "CABLE" or adq_r:
                        push(ch("P22e" + k, "D",
                                "¿Hay toma de energía y punto de red disponibles para cuando se implemente el Raspberry?" if adq_r
                                else "¿Hay toma de energía y punto de red disponibles para el Raspberry?",
                                [{"v": "AMBOS", "l": "Sí, ambos"}, {"v": "ENERGIA", "l": "Solo toma de energía"},
                                 {"v": "RED", "l": "Solo punto de red"}, {"v": "NINGUNO", "l": "Ninguno"}], {"def": "AMBOS"}))
                    else:
                        push(ch("P22e" + k, "D", "¿Hay toma de energía disponible para el Raspberry?", YN, {"def": "SI"}))
                if v("P22a" + k) == "NO":
                    push(ch("P22b" + k, "D", "¿Qué adquirirá el cliente para el sistema de impresiones?",
                            [{"v": "RASPBERRY", "l": "Raspberry"}, {"v": "LAPTOP", "l": "Laptop"}, {"v": "PC", "l": "PC"}], {"def": "RASPBERRY"}))
                info.rasp = v("P22a" + k) == "SI"
                info.raspCable = v("P22c" + k) == "CABLE" or v("P22b" + k) == "RASPBERRY"
                info.raspVia = v("P22d" + k)
                info.raspViaL = lab("P22d" + k)
                e2 = v("P22e" + k)
                info.raspEnergia = None if e2 is None else e2 in ("AMBOS", "ENERGIA", "SI")
                info.raspPunto = (e2 in ("AMBOS", "RED")) if (info.raspCable and e2 is not None) else None
                info.adq = v("P22b" + k)
                info.adqL = lab("P22b" + k)
            dev_ok = e in ("SI", "TABLET", "SUNMI", "IMIN")
            if (not sin_pc) or X.simple:
                sin_done = True
            elif info.rasp or info.adq == "RASPBERRY":
                sin_done = bool(a.get("P22e" + k))
            else:
                sin_done = bool(info.adq)
            pc_done = e != "SI" or bool(a.get("P23" + k))
            if rub_ == "RETAIL" and e is not None and pc_done and sin_done:
                push({"id": "P22h" + k, "b": "D", "kind": "multi",
                      "text": f"¿Qué periféricos están conectados al equipo de caja{sfx}?",
                      "opts": ["Balanza", "Escáner de códigos", "Gaveta", "Impresora de etiquetas", "POS de pago (Niubiz, Izipay…)"],
                      "sel": [], "none": "Ninguno", "def": ["Escáner de códigos", "Gaveta"], "min": 1})
            per_done = rub_ != "RETAIL" or bool(a.get("P22h" + k))
            any_q = e is not None and pc_done and sin_done and per_done and not X.obra and (dev_ok or bool(info.rasp) or info.adq == "RASPBERRY")
            if any_q:
                eq_txt = f"{'PC o laptop' if e == 'SI' else info.eqL} de caja{sfx}" if dev_ok else f"Raspberry{sfx}"
                push({"id": "E7" + k, "b": "D", "kind": "ev", "read": "anydesk", "name": f"el AnyDesk del equipo de caja{sfx}",
                      "text": (f"Abre AnyDesk en el equipo de caja{sfx} y sube una foto de la pantalla donde se vea el código de AnyDesk." if dev_ok
                               else f"Abre AnyDesk en el equipo desde donde se accederá al Raspberry{sfx} y sube una foto donde se vea el código de AnyDesk."),
                      "def": {"data": {"codigo": f"1 23{i} 456 789", "equipo": eq_txt}}})
            e7 = a.get("E7" + k)
            info.anydesk = e7.get("data") if e7 and e7.get("v") == "OK" else None
            info.done = bool(a.get("P22" + k)) and pc_done and sin_done and per_done and (not any_q or bool(a.get("E7" + k)))
            X.cajasInfo.append(info)
    cajas_done = c_block_ready and len(X.cajasInfo) == X.cajas and all(c.done for c in X.cajasInfo)

    # E · impresoras
    prev_done = cajas_done

    def usb_host_ok() -> bool:
        return any((c.eq == "SI" and not c.temporal) or c.adq in ("LAPTOP", "PC") for c in X.cajasInfo)

    for ix, pr in enumerate(printers):
        if not prev_done:
            pr.skip = True
            continue
        nm = f"IMP. {pr.name}"
        K = "#" + pr.name
        tiene = True
        push({"id": "E5a" + K, "b": "E", "kind": "ev", "read": "label", "name": f"la etiqueta de {nm}",
              "text": f"{nm}: sube la foto de la etiqueta de la impresora donde se vean el número de serie (SN) y el modelo.",
              "def": {"data": {"marca": "Epson", "modelo": "TM-T20III", "sn": "X5RF0" + str(12345 + ix)}}})
        dtxt = " ".join(str((a.get(k + K) or {}).get("desc") or "") for k in ("E5a", "E5b", "E5"))
        if AJENA_RE.search(dtxt):
            # C2: equipo que no es del local (impresora de otro lugar): no se cuenta
            pr.ajena = True
            prev_done = True
            continue
        impl_desc = bool(IMPL_RE.search(dtxt))
        if impl_desc:
            tiene = False  # C1: la descripción dice que aún no existe
        if X.obra and not impl_desc:
            # En obra la impresora empieza «Por implementar» y pasa a «Existente» si la foto o su descripción lo muestran (0.0.19 · C3);
            # solo si no hay ninguna de las dos se pregunta si el cliente ya la tiene.
            e0 = a.get("E5a" + K)
            if not e0:
                prev_done = False
                continue
            if not (e0.get("v") == "OK" or str(e0.get("desc") or "").strip()):
                push(ch("P28h" + K, "E", f"¿El cliente ya tiene la impresora de {pr.name}?", YN, {"def": "NO"}))
                tiene = v("P28h" + K) == "SI"
                if not a.get("P28h" + K):
                    prev_done = False
                    continue
        if not tiene:
            pr.con = "NO"
            pr.estado = None
            pr.marca = ""
            pr.modelo = ""
            pr.sn = ""
            prev_done = True
            continue
        e5a = a.get("E5a" + K)
        lab_d = e5a.get("data") if e5a and e5a.get("v") == "OK" else None
        if a.get("E5a" + K):
            push({"id": "E5b" + K, "b": "E", "kind": "ev", "read": "conn", "name": f"las conexiones de {nm}",
                  "text": con_toma(nm, f"{nm}: sube la foto de la parte de atrás de la impresora donde se vean sus conexiones."),
                  "def": {"data": {"ver": "RED"}}})
        e5b = a.get("E5b" + K)
        conn = e5b["data"].get("ver") if e5b and e5b.get("v") == "OK" else None
        if a.get("E5b" + K):
            usb = conn == "USB"
            if usb:
                dd = {"marca": lab_d.get("marca") if lab_d else "", "modelo": lab_d.get("modelo") if lab_d else ""}
            else:
                dd = {"marca": lab_d.get("marca") if lab_d else "", "modelo": lab_d.get("modelo") if lab_d else "",
                      "ip": f"{X.seg}.{40 + ix}", "mac": f"00:26:AB:5F:{format(16 + ix, 'X')}:2C", "gw": f"{X.seg}.1"}
            push({"id": "E5" + K, "b": "E", "kind": "ev", "read": "selftestUsb" if usb else "selftest", "name": f"el selftest de {nm}",
                  "text": f"{nm}: imprime el selftest (hoja de prueba) y sube la foto.", "def": {"data": dd}})
        e5 = a.get("E5" + K)
        st = e5.get("data") if e5 and e5.get("v") == "OK" else None
        pr.etq = lab_d
        pr.st = st
        pr.conn = conn
        pr.marca = (st.get("marca") if st else None) or (lab_d.get("marca") if lab_d else None) or ""
        pr.modelo = (st.get("modelo") if st else None) or (lab_d.get("modelo") if lab_d else None) or ""
        pr.sn = lab_d.get("sn") if lab_d else ""
        pr.ip = st.get("ip") if st and st.get("ip") else None
        pr.mac = st.get("mac") if st and st.get("mac") else None
        pr.gw = st.get("gw") if st and st.get("gw") else None
        auto = None
        if a.get("E5" + K):
            if st and st.get("ip") and conn in ("RED", "WIFI"):
                auto = conn
            elif st and not st.get("ip") and conn == "USB" and (st.get("marca") or st.get("modelo")):
                auto = "USB"
        if auto:
            how = "por red (cable)" if auto == "RED" else "por WiFi" if auto == "WIFI" else "por USB"
            push({"id": "I_AUTO" + pr.name, "kind": "alert", "tone": "info", "tag": "AUTO",
                  "text": f"{nm}: se completó que se conecta {how}{(' · IP ' + pr.ip) if pr.ip else ''}."})
        id_ = "P28" + K
        if a.get("E5" + K) and not auto:
            push(ch(id_, "E", f"{nm}{' (también imprime la caja)' if pr.shared else ''}: no se pudo confirmar en las fotos cómo se conecta. ¿Cómo se conecta?",
                    [{"v": "RED", "l": "Red por cable"}, {"v": "WIFI", "l": "WiFi"}, {"v": "USB", "l": "USB"},
                     {"v": "NONE", "l": "Sin conexión (no se ve en el escáner)"}, {"v": "NO", "l": "Aún no tiene impresora"}],
                    {"def": "USB" if conn == "USB" else "RED"}))
        pr.con = auto or v(id_)
        pr.auto = bool(auto)
        if pr.con == "USB":
            has_pcl = usb_host_ok()
            tab = any(c.eq == "TABLET" for c in X.cajasInfo)
            ras = any(c.rasp for c in X.cajasInfo)
            o = ([{"v": "PC", "l": "PC o laptop"}] if has_pcl else []) + [
                {"v": "TABLET", "l": "Tablet"}, {"v": "RASPBERRY", "l": "Raspberry"}, {"v": "SUNMI", "l": "Sunmi"}, {"v": "IMIN", "l": "iMin"},
                {"v": "ROUTER", "l": "Router o repetidor"}, {"v": "OTRO", "l": "Otro equipo"}, {"v": "NINGUNO", "l": "No está conectada a ningún equipo"}]
            push(ch("P28u" + K, "E", f"{nm}: ¿a qué equipo está conectada por USB?", o,
                    {"def": "PC" if has_pcl else "TABLET" if tab else "RASPBERRY" if ras else "NINGUNO"}))
        pr.usbTo = v("P28u" + K) if pr.con == "USB" else None
        pr.usbToL = lab("P28u" + K) if pr.usbTo and a.get("P28u" + K) else None
        has_est = pr.con in ("RED", "WIFI", "USB")
        if has_est and (pr.con != "USB" or pr.usbTo):
            push(ch("P28b" + K, "E", f"{nm}: ¿Cuál es el estado de la impresora?",
                    [{"v": "NUEVA", "l": "Nueva"}, {"v": "VIABLE", "l": "Viable"}, {"v": "MANT", "l": "Necesita mantenimiento"},
                     {"v": "FALLAS", "l": "Con fallas"}, {"v": "OTRO", "l": "Otro (escribir)", "otro": True}],
                    {"def": "NUEVA" if X.inaug else "VIABLE"}))
        pr.estado = v("P28b" + K)
        pr.estadoL = lab("P28b" + K)
        via_q = pr.con in ("RED", "WIFI") and bool(pr.estado)
        if via_q:
            push(ch("P28c" + K, "E", f"{nm}: ¿La impresora está conectada directamente al router, a un switch, a un repetidor, por WiFi o a un socket de pared?",
                    [{"v": "ROUTER", "l": "Directo al router"}, {"v": "SWITCH", "l": "A un switch"}, {"v": "REPETIDOR", "l": "A un repetidor"},
                     {"v": "WIFI", "l": "Por WiFi"}, {"v": "SOCKET", "l": "A un socket de pared"}, {"v": "OTRO", "l": "Otro (escribir)", "otro": True}],
                    {"def": "WIFI" if pr.con == "WIFI" else "ROUTER"}))
        pr.via = v("P28c" + K)
        pr.viaL = lab("P28c" + K)
        # Punto de red de la impresora (0.0.19): solo si el cable no va directo al router ni es WiFi.
        pto_q = pr.con == "RED" and bool(pr.via) and pr.via not in ("ROUTER", "WIFI")
        if pto_q:
            push(ch("P28p" + K, "E", f"{nm}: ¿cómo está el punto de red donde se conecta la impresora?", PUNTO_OPTS, {"def": "HAB"}))
        pr.ptoQ = pto_q
        pr.punto = v("P28p" + K) if pto_q else None
        pr.puntoL = lab("P28p" + K) if pto_q and a.get("P28p" + K) else None
        if pr.punto in PUNTO_ALERT:
            push({"id": "A_PTO" + pr.name, "kind": "alert", "tone": "warn", "tag": "PUNTO DE RED",
                  "text": f"{nm}: {PUNTO_ALERT[pr.punto]}"})
        if pr.estado == "FALLAS":
            push({"id": "A_AV" + pr.name, "kind": "alert", "tone": "warn", "tag": "CON FALLAS",
                  "text": f"{nm} tiene fallas: reparar o reemplazar la impresora."})
        if pr.estado == "MANT":
            push({"id": "A_MT" + pr.name, "kind": "alert", "tone": "info", "tag": "MANTENIMIENTO",
                  "text": f"{nm}: darle mantenimiento antes del inicio."})
        if pr.con == "NONE":
            push({"id": "A_NC" + pr.name, "kind": "alert", "tone": "warn", "tag": "SIN CONEXIÓN",
                  "text": f"{nm}: no se indicó cómo se conecta ni aparece en el escáner. En el mapa queda sola, sin conexión."})
        if pr.usbTo and pr.usbTo != "PC":
            if pr.usbTo == "NINGUNO":
                txt = (f"{nm} es USB y no está conectada a ningún equipo. Una impresora USB solo se conecta a una PC o laptop"
                       f"{'' if usb_host_ok() else '; en el local no hay PC ni laptop fija: cambiar a impresora de red o adquirir una PC o laptop'}.")
            else:
                txt = (f"{nm} está conectada por USB a: {pr.usbToL}. Una impresora USB solo se conecta a una PC o laptop "
                       f"(nunca a tablet, Raspberry, Sunmi, iMin, router ni repetidor). En el mapa la impresora queda sin flecha USB. "
                       f"{'Conéctala a la PC o laptop.' if usb_host_ok() else 'Cambiar a impresora de red o adquirir una PC o laptop.'}")
            push({"id": "A_USB" + pr.name, "kind": "alert", "tone": "warn", "tag": "USB", "text": txt})
        if pr.prep and pr.con and pr.con not in ("RED", "NONE"):
            push({"id": "A_R51" + pr.name, "kind": "alert", "tone": "warn", "tag": "R51",
                  "text": f"{nm}: las impresoras de preparación deben ser de red por cable. {'Debe adquirir una impresora de red.' if pr.con == 'NO' else 'Cambiar a una impresora de red por cable.'}"})
        if pr.con in ("RED", "WIFI") and pr.ip and not pr.ip.startswith(X.seg + "."):
            push({"id": "A_R55" + pr.name, "kind": "alert", "tone": "warn", "tag": "R55",
                  "text": f"{nm} está en {'.'.join(pr.ip.split('.')[:3])}.x y el router en {X.seg}.x. "
                          + ("Configúrala en la misma red y segmento que las otras impresoras antes de iniciar con el punto de venta." if X.anterior
                             else "Cambia su IP a una del segmento del router y vuelve a subir el selftest.")})
        prev_done = bool(pr.con) and (pr.con != "USB" or bool(pr.usbTo)) and (not has_est or bool(pr.estado)) and (not via_q or bool(pr.via)) and (not pto_q or bool(pr.punto))

    printers[:] = [p for p in printers if not p.ajena]  # C2: las impresoras de otro lugar no se cuentan
    printers_done = cajas_done and all(
        p.con is not None and (p.con != "USB" or p.usbTo) and (p.con not in ("RED", "WIFI", "USB") or p.estado) and (p.con not in ("RED", "WIFI") or p.via) and (not p.ptoQ or p.punto)
        for p in printers)
    X.printersDone = printers_done

    if printers_done and not X.simple and X.cajas > 0 and not X.sunmi:
        X.hasPC = any((c.eq == "SI" and not c.temporal) or c.adq in ("LAPTOP", "PC") for c in X.cajasInfo)
        X.hasRasp = any(c.rasp for c in X.cajasInfo)
        comandas = len(prep) > 0 or v("P12b") == "SI"
        caja_usb = any((not p.prep or p.shared) and p.con == "USB" for p in printers)
        X.posPropio = len(X.cajasInfo) > 0 and all(c.posPropio for c in X.cajasInfo)
        d = None
        if not X.hasPC and not X.hasRasp and not X.posPropio:
            d = "PC_BASICA" if not comandas else "PC_CONTROLADOR" if caja_usb else "RASPBERRY"
        X.decision = d
        T = {
            "PC_BASICA": ("A_IMP_PC_BASICA", "info", "No hay áreas de preparación ni comanda. Recomienda una laptop o PC básica con USB para pre-cuentas y comprobantes; sin controlador."),
            "PC_CONTROLADOR": ("A_IMP_PC_CONTROLADOR", "warn", "La impresora de caja es USB y solo funciona con laptop o PC, no con Raspberry. Recomienda una laptop o PC para el controlador de impresiones."),
            "RASPBERRY": ("A_IMP_RASPBERRY", "warn", "No hay PC ni laptop en caja y las impresoras son de red. Recomienda un kit Raspberry para el controlador de impresiones. Cotízalo con Desarrollo de Negocios."),
        }
        if d:
            push({"id": T[d][0], "kind": "alert", "tone": T[d][1], "tag": "G_IMPRESION", "text": T[d][2]})

    # puertos
    if printers_done and X.hasInt and X.libres is not None:
        n = len([p for p in printers if p.con == "RED" and (not p.via or p.via in ("ROUTER", "SOCKET"))])
        for c in X.cajasInfo:
            if c.pcCable:
                n += 1
            elif c.rasp and c.raspCable and (not c.raspVia or c.raspVia == "ROUTER"):
                n += 1
            elif c.adq:
                n += 1
        X.eqCable = n
        if n > X.libres:
            X.switchN = next((s for s in (5, 8, 16, 24, 48) if s - 1 >= n), None)
            push({"id": "A_FALTAN_PUERTOS", "kind": "alert", "tone": "warn", "tag": "SWITCH",
                  "text": f"El router tiene {fmt(X.libres)} puertos libres y hay {n} equipos por cable. Recomienda un Switch x{X.switchN} e implementar los puntos de red que falten."})

    # H · WiFi y cámaras
    moz_ask = printers_done and X.mozosQ and not X.simple and not X.obra
    if moz_ask:
        push(ch("P09c", "H", "¿Los mozos toman pedidos con algún equipo? Puede ser tablet, su celular o un iMin móvil.", MOZ_OPTS,
                {"def": "NO" if rub in CAT["MOZOS_RARO"] else "TABLET"}))
    moz_ok = (not moz_ask) or bool(a.get("P09c"))
    X.wifiSkip = X.simple or X.obra or (X.mozosQ and v("P09c") == "NO")
    all_z = uniq([*[z["z"] for z in zonas], *prep])
    X.allZ = [] if X.simple else all_z
    X.sinSenal = []
    X.wz = []
    wifi_done = False
    if printers_done and moz_ok:
        if X.simple:
            wifi_done = True
        elif X.wifiSkip:
            push({"id": "I_NOWIFI", "kind": "alert", "tone": "info", "tag": "PERFIL",
                  "text": "Local en obra: no se revisa el WiFi por zona." if X.obra else "Los mozos no toman pedidos con un equipo: no se revisa el WiFi por zona."})
            wifi_done = True
        elif all_z:
            push({"id": "P46", "b": "H", "kind": "multi", "text": "¿Hay zonas o lugares de preparación sin señal WiFi?",
                  "opts": all_z, "sel": [], "none": "Ninguna", "def": [], "min": 1})
            if a.get("P46"):
                push(ch("WZ", "H", "Revisar WiFi por zona (opcional). Estás conectado a la red del local. ¿Quieres medir la señal en cada zona?",
                        [{"v": "REVISAR", "l": "Revisar WiFi por zona"}, {"v": "OMITIR", "l": "Omitir"}], {"def": "OMITIR"}))
            if v("WZ") == "REVISAR":
                push({"id": "WZM", "b": "H", "kind": "wifi",
                      "text": 'Toca "Medir aquí" en cada zona. Puedes cambiar los valores para probar casos.', "zones": all_z, "def": None})
            med = a["WZM"]["v"] if a.get("WZM") else {}
            from app.chat.sim.rules import rate  # import diferido: rules importa este módulo
            X.wz = [Obj({"z": z, **med[z], **rate(med[z])}) for z in med]
            bad = [r["z"] for r in X.wz if r["cal"] in ("Regular", "Mala")]
            X.sinSenal = uniq([*(v("P46") or []), *bad])
            w_done = bool(a.get("P46")) and (v("WZ") == "OMITIR" or bool(a.get("WZM")))
            if w_done and X.sinSenal:
                push(ch("P46a", "H", f"Zonas sin buena señal: {', '.join(X.sinSenal)}. Sugerencia: {'access point' if len(X.sinSenal) > 1 else 'repetidor'}. ¿Qué se instalará?",
                        [{"v": "REPETIDOR", "l": "Repetidor"}, {"v": "AP", "l": "Access point"}, {"v": "AMBOS", "l": "Ambos"}],
                        {"def": "AP" if len(X.sinSenal) > 1 else "REPETIDOR"}))
            wifi_done = bool(a.get("P46")) and (v("WZ") == "OMITIR" or bool(a.get("WZM"))) and (not X.sinSenal or bool(a.get("P46a")))
        else:
            wifi_done = True
        if wifi_done and not X.simple:
            push(ch("P47", "H", f"¿Hay cámaras de seguridad conectadas a la red o se van a conectar{' (por ejemplo, al TP-Link con chip)' if X.r56 else ''}?",
                    YN, {"def": "NO"}))
            if v("P47") == "SI":
                push({"id": "P47a", "b": "H", "kind": "choice", "text": "¿Cuántas cámaras irán conectadas a la red?", "unit": "cámaras",
                      "opts": [{"v": n, "l": str(n)} for n in (1, 2, 3, 4)] + [{"v": "OTRO", "l": "Otro (escribir)", "otro": True, "num": True}],
                      "def": 2})
    X.solWifi = lab("P46a")
    X.camaras = v("P47") == "SI"
    p47a = v("P47a")
    X.nCam = p47a if isinstance(p47a, (int, float)) and not isinstance(p47a, bool) else 0
    h_ready = wifi_done and (X.simple or v("P47") == "NO" or bool(a.get("P47a")))

    # I · evidencias obligatorias y cierre
    if h_ready:
        W = "Dónde irá: " if X.obra else ""
        items: List[Dict[str, Any]] = [{"k": "Frontis del local", "t": "Frontis"}]
        if not X.simple:
            for p in prep:
                items.append({"k": p, "t": W + "Lugar de preparación"})
        zona_names = uniq([z["z"] for z in zonas])
        for z in zona_names:
            if z in prep:
                continue
            if z == "Caja" and X.cajas > 0:
                continue
            if rub == "RETAIL":
                continue
            items.append({"k": z, "t": W + "Zona de atención · " + ", ".join(q["canal"] for q in zonas if q["z"] == z), "opt": not X.simple})
        for i in range(1, X.cajas + 1):
            nm = f"Caja {i}" if X.cajas > 1 else "Caja"
            items.append({"k": nm, "t": ("Dónde irá la caja" if X.obra else "Equipo de caja")
                          + (" (sirve también para la zona Caja)" if "Caja" in zona_names else "")
                          + (" · que se vea la toma de energía cercana" if toma(eq_caja_name(i)) else "")})
        X.evItems = items
        push({"id": "EV", "b": "I", "kind": "check",
              "text": "Fotos obligatorias. Sin ellas no se pasa al análisis." if X.simple
              else "Fotos del local. El frontis, los lugares de preparación y la caja son obligatorias; las zonas de atención se pueden saltar.",
              "items": items})
        router_ph = bool(a.get("E2u") or a.get("E2") or a.get("E2e"))
        if a.get("EV"):
            tomas_txt = ", mostrando también la toma de energía cercana" if X.tomas == "SI" and not X.obra and not X.simple else ""
            push({"id": "EVO", "b": "I", "kind": "multi",
                  "text": f"¿Qué otros equipos hay en el local? Por ejemplo {'' if router_ph else 'router principal, '}router secundario o de otro piso, gabinete, servidor, extensión, switch, repetidor o mesh. Márcalos para subir una foto de cada uno{tomas_txt}.",
                  "opts": [*([] if router_ph else ["Router principal"]), "Router secundario", "Router del piso 2", "Router del piso 3", "Gabinete",
                           "Servidor", "Extensión (regleta)", "Switch", "Repetidor", "Mesh", "Access point"],
                  "sel": [], "none": "Ninguno", "def": [], "min": 1})
        X.otrosEq = [x for x in a["EVO"]["v"] if not re.match(r"^Ninguno", x)] if a.get("EVO") and isinstance(a["EVO"].get("v"), list) else []
        if a.get("EVO") and X.otrosEq:
            suf = " · que se vea la toma de energía" if X.tomas == "SI" and not X.obra and not X.simple else ""
            push({"id": "EVQ", "b": "I", "kind": "check", "text": "Fotos de los otros equipos del local (una por equipo).",
                  "items": [{"k": k, "t": "Equipo existente en el local" + suf} for k in X.otrosEq]})
        if a.get("EV") and a.get("EVO") and (not X.otrosEq or a.get("EVQ")):
            push({"id": "P49a", "b": "I", "kind": "links",
                  "text": "Anexo B: agrega los enlaces de los videos del local y de los equipos (recorrido del local, equipos de red, gabinete, dónde iría el sistema de impresiones…). Drive, OneDrive, YouTube u otro. Puedes agregar varios o continuar sin enlaces.",
                  "def": []})
            if a.get("P49a"):
                push({"id": "P50b", "b": "I", "kind": "date", "text": "¿Hay una fecha de inicio acordada con el cliente? (opcional)", "def": ""})
            if a.get("P50b"):
                push({"id": "P52a", "b": "I", "kind": "pasos",
                      "text": "Estos son los pasos a seguir. Puedes quitar, editar o agregar. Toca un paso para leerlo completo en la caja de texto del chat."})
            if a.get("P52a"):
                push({"id": "SUM", "b": "I", "kind": "summary", "text": "Evidencias de la visita"})
            if a.get("SUM"):
                push({"id": "FIN", "kind": "fin", "text": "Evaluación completada. He procesado tus respuestas y generado la minuta técnica."})
    _switch_ports(N, X, a)
    return N, X


def _switch_ports(N: List[Dict[str, Any]], X: Obj, a: Dict[str, Any]) -> None:
    """Paso opcional «Ubicar puerto»: la app hace ping a cada impresora de red conectada a un switch."""
    X.sw46 = None
    prn = [p for p in (X.printers or []) if p.con == "RED" and p.via == "SWITCH" and p.ip]
    if not X.printersDone or not prn:
        return
    v = lambda id_: (a.get(id_) or {}).get("v") if a.get(id_) else None
    nodes: List[Dict[str, Any]] = []
    nodes.append(ch("PSW", "E", "Paso opcional: ¿quieres ubicar en qué puerto del switch está cada impresora ("
                    + ", ".join("IMP. " + p.name for p in prn)
                    + ")? La app envía pings a la IP de cada una y tú miras qué luz del switch parpadea. Si prefieres, puedes saltarlo.",
                    [{"v": "SI", "l": "Sí, ubicar los puertos"}, {"v": "NO", "l": "Saltar este paso"}], {"def": "NO"}))
    if v("PSW") == "SI":
        nodes.append(ch("PSWn", "E", "¿Cuántos puertos tiene el switch?", [{"v": n, "l": str(n)} for n in (5, 8, 16, 24, 48)],
                        {"unit": "puertos", "def": X.switchN or 8}))
        n = int(num(v("PSWn")) or 0)
        if n:
            nodes.append(ch("PSWu", "E", "¿Qué puerto va al router (puerto de subida)? Se descarta al ubicar las impresoras.",
                            [{"v": n, "l": f"El último ({n})"}, {"v": 1, "l": "El 1"}, {"v": "OTRO", "l": "Otro (escribir)", "otro": True, "num": True}],
                            {"unit": "", "def": n}))
        up = int(num(v("PSWu")) or 0)
        S = Obj(n=n, up=up, map=[], rot=None)
        prev = bool(up)
        used: set = set()
        for p in prn:
            if not prev:
                break
            id_ = "PSWp#" + p.name
            ports = [{"v": k, "l": f"Puerto {k}"} for k in range(1, min(n, 16) + 1) if k != up and k not in used]
            extra = [{"v": "OTRO", "l": "Otro puerto (escribir)", "otro": True, "num": True}] if n > 16 else []
            nodes.append(ch(id_, "E", f"IMP. {p.name} (IP {p.ip}): la app está enviando pings a su IP durante 20 s, 2 s sí y 2 s no. ¿Qué luz del switch parpadea a ese ritmo?",
                            ports + extra + [{"v": "NINGUNA", "l": "Ninguna luz sigue el ritmo"}, {"v": "SALTAR", "l": "Saltar esta impresora"}],
                            {"def": "SALTAR", "sw46": 1}))
            x = v(id_)
            if x is None:
                prev = False
                break
            row = Obj(name=p.name, ip=p.ip, port=None, st="skip" if x == "SALTAR" else "none" if x == "NINGUNA" else "ok")
            if isinstance(x, (int, float)) and not isinstance(x, bool):
                row.port = x
                used.add(x)
                row.update(q46(p.name))
            if row.st == "none":
                nodes.append({"id": "A_SW46N" + p.name, "kind": "alert", "tone": "info", "tag": "SWITCH",
                              "text": f"IMP. {p.name} no está en este switch: puede ir a un repetidor, a otro switch o directo al router. Revisa su cable."})
            if row.port and (row.loss > 2 or row.lat > 50):
                nodes.append({"id": "A_SW46Q" + p.name, "kind": "alert", "tone": "warn", "tag": "PUNTO DE RED",
                              "text": f"Punto de red de IMP. {p.name} (puerto {row.port}) con {row.loss} % de pérdida: queda en observación. Revisa el cableado del punto y su extremo en el switch."})
            S.map.append(row)
        if prev and any(r.port for r in S.map):
            nodes.append(ch("PSWr", "E", "¿Se rotularon los puntos de red en el switch?", [{"v": "SI", "l": "Sí"}, {"v": "PARCIAL", "l": "Parcial"}, {"v": "NO", "l": "No"}], {"def": "SI"}))
            S.rot = a["PSWr"].get("label") if a.get("PSWr") else None
        X.sw46 = S
    at = -1
    for i, x in enumerate(N):
        if re.match(r"^(P28|A_(AV|MT|NC|USB|R51|R55|PTO))", x.get("id") or ""):
            at = i
    if at < 0:
        fi = next((i for i, x in enumerate(N) if x.get("kind") == "fin"), -1)
        at = fi if fi >= 0 else len(N)
    else:
        at += 1
    N[at:at] = nodes


def current_node(N: List[Dict[str, Any]], a: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Primer nodo sin respuesta (o el FIN)."""
    for n in N:
        if n["kind"] == "alert":
            continue
        if n["kind"] == "fin":
            return n
        if a.get(n["id"]) is None:
            return n
    return None
