"""«Redacta una minuta nueva…»: lee lo que cuenta el técnico (texto o audio transcrito) y arma el borrador: datos del cliente,
conexiones de red, observaciones, recomendaciones, pasos y evidencias que faltan. Regex siempre; si hay OPENAI_API_KEY, ChatGPT
completa lo que las reglas no encontraron (nunca pisa un dato que ya salió)."""
import json
import os
import re
from typing import Any, Dict, List, Optional

from app.asistente.texto import sentences

EVIDENCIAS = ["Frontis del local", "Speedtest", "Ubicación del router", "Puertos del router", "Etiqueta del router",
              "AnyDesk de caja", "Selftest de impresora", "Lugar de preparación"]
RUBROS = [(r"poller", "Pollería"), (r"restobar|\bbar\b", "Restobar"), (r"fast ?food|comida r[aá]pida|patio de comidas", "Fast food"),
          (r"supermercado|minimarket|bodega|tienda|retail", "Retail"),
          (r"restaurante|sangucher|cevicher|chifa|pizzer|cafeter|juguer|picanter", "Restaurante")]
AREAS = [(r"cocina", "Cocina"), (r"bebida", "Bebidas"), (r"\bbarra\b", "Barra"), (r"jugo", "Jugos"), (r"cafeter[ií]a", "Cafetería"),
         (r"parrilla", "Parrilla"), (r"horno|pizza", "Horno"), (r"postre", "Postres")]
MEDIOS = {"cable": "Cable", "wifi": "WiFi", "wi-fi": "WiFi", "usb": "USB"}
CONEXION = re.compile(r"(.+?)\s+(?:est[aá]|queda|qued[oó]|va|se dej[oó]|se conect[oó])\s+(?:conectad[oa]s?\s+)?(?:por|con|v[ií]a|en)\s+(cable|wi-?fi|usb)"
                      r"(?:\s+(?:de red\s+)?(?:al?|a la|con el|con la|hacia el|hacia la|del?)\s+(.+))?$", re.I)
COLA = re.compile(r"\s+(?:y\s+(?:se|ahora|luego|despu[eé]s)\b.*|pero\b.*)$", re.I)


def _cap(s: str) -> str:
    s = s.strip().strip(".;,")
    return s[:1].upper() + s[1:]


def equipo(nombre: str) -> str:
    """«la impresora de cocina» → «IMP. Cocina»; «el repetidor del salón 2» → «Repetidor · Salón 2»."""
    n = re.sub(r"^(el|la|los|las)\s+", "", nombre.strip(), flags=re.I).strip(" .;,")
    m = re.match(r"impresora(?:s)?(?:\s+(?:del|de la|de|para)\b)?\s*(.*)$", n, re.I)
    if m:
        return "IMP. " + _cap(m.group(1)) if m.group(1).strip() else "Impresora"
    m = re.match(r"(?:pc|computadora|equipo)(?:\s+(?:del|de la|de)\b)?\s*(.*)$", n, re.I)
    if m and re.match(r"pc|computadora", n, re.I):
        return "PC " + _cap(m.group(1)) if m.group(1).strip() else "PC"
    m = re.match(r"(repetidor|extensor|mesh|access point|ap)(?:\s+(?:del|de la|de)\b)?\s*(.*)$", n, re.I)
    if m:
        return (_cap(m.group(1)) + (" · " + _cap(m.group(2)) if m.group(2).strip() else ""))
    if re.fullmatch(r"router|m[oó]dem|switch|servidor|gabinete", n, re.I):
        return _cap(n)
    return _cap(n)


def conexiones(texto: str) -> List[Dict[str, str]]:
    """Enlaces `{desde, hacia, medio}`. Si el mismo enlace se menciona dos veces, gana el último medio («estaba por WiFi y se dejó por cable»)."""
    out: Dict[tuple, Dict[str, str]] = {}
    orden: List[tuple] = []
    for s in sentences(texto):
        for parte in re.split(r"\s+y\s+(?=(?:se|ahora)\s)", s):
            m = CONEXION.match(COLA.sub("", parte.strip().rstrip(".;")) if not re.search(r"estaba", parte, re.I) else parte.strip().rstrip(".;"))
            if not m:
                continue
            desde, medio, hacia = m.group(1), m.group(2).lower(), (m.group(3) or "")
            if re.search(r"estaba", desde, re.I):
                desde = re.split(r"\s+estaba\b", desde, flags=re.I)[0]
            if not hacia.strip():
                continue
            k = (equipo(desde), equipo(hacia))
            if k not in out:
                orden.append(k)
            out[k] = {"desde": k[0], "hacia": k[1], "medio": MEDIOS[medio]}
    # «estaba por WiFi y se dejó por cable al switch»: el último medio gana
    for s in sentences(texto):
        m = re.search(r"(.+?)\s+estaba\s+(?:conectad[oa]\s+)?por\s+(?:cable|wi-?fi|usb).*?(?:se dej[oó]|qued[oó]|ahora|pas[oó])\s+(?:conectad[oa]\s+)?por\s+(cable|wi-?fi|usb)\s+(?:al?|a la|con el|con la)\s+(.+?)[.;]?$", s, re.I)
        if m:
            k = (equipo(m.group(1)), equipo(m.group(3)))
            if k not in out:
                orden.append(k)
            out[k] = {"desde": k[0], "hacia": k[1], "medio": MEDIOS[m.group(2).lower()]}
    return [out[k] for k in orden]


def _cmd_split(texto: str) -> List[str]:
    """Quita la orden («Redacta una minuta nueva.») y deja el contexto."""
    ss = sentences(texto)
    return [s for s in ss if not re.match(r"^\s*(redact|gener|cre[ae]|arm[ae]|haz|hacer|elabor)\w*\b[^.]*\bminuta\b[^.]*\.?$", s, re.I)]


def datos(texto: str) -> Dict[str, Any]:
    t = " ".join(_cmd_split(texto)) if _cmd_split(texto) else texto
    d: Dict[str, Any] = {}

    def g(pat: str, flags: int = re.I) -> Optional[str]:
        m = re.search(pat, t, flags)
        return _cap(m.group(1)) if m else None
    d["local"] = g(r"(?:se llama|nombre del local(?: es)?:?|el local es|local:)\s+(.+?)(?=\s*(?:[;]|,\s|\.\s|\.$|$|\s+con\s+ruc|\s+raz[oó]n social))")
    d["razon"] = g(r"raz[oó]n social\s*(?:es|:)?\s+(.+?)(?=\s+con\s+ruc|\s*[;,]|\.\s|\.$|$)")
    ruc = re.search(r"\b(?:ruc\s*(?:es|:)?\s*)?((?:10|15|17|20)\d{9})\b", t, re.I)
    d["ruc"] = ruc.group(1) if ruc else None
    d["direccion"] = g(r"direcci[oó]n\s*(?:es|:)?\s+(.+?)(?=\s*[;]|\.\s+[A-ZÁÉÍÓÚ]|\.$|$)", re.I)
    enc = re.search(r"encargad[oa]\s*(?:es|:)?\s+(.+?)(?=\s*[,;]|\.\s|\.$|$|\s+(?:su|con)\s+(?:celular|tel|correo))", t, re.I)
    d["encargado"] = _cap(enc.group(1)) if enc else None
    cel = re.search(r"\b(9\d{8})\b", t)
    d["celular"] = cel.group(1) if cel else None
    mail = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", t)
    d["correo"] = mail.group(0) if mail else None
    d["rubro"] = next((r for p, r in RUBROS if re.search(p, t, re.I)), None)
    d["estado"] = ("En obra" if re.search(r"en obra", t, re.I) else "Con sistema anterior" if re.search(r"sistema anterior", t, re.I)
                   else "En operación")
    areas_txt = " ".join(s for s in sentences(t) if re.search(r"[aá]rea|preparaci|impresora", s, re.I))
    d["areas"] = [a for p, a in AREAS if re.search(p, areas_txt, re.I)]
    mb = re.search(r"(\d{2,4})\s*mbps", t, re.I)
    d["internet"] = f"{mb.group(1)} Mbps" if mb else None
    return {k: v for k, v in d.items() if v not in (None, [], "")}


def _clasificar(s: str) -> str:
    if re.match(r"^\s*(se )?recomiend|^\s*recomendaci[oó]n|^\s*se sugiere", s, re.I):
        return "rec"
    if re.search(r"\b(el cliente|la cliente|el encargado)\b[^.]*\b(debe|deber[aá]|tiene que|necesita)\b", s, re.I):
        return "pasoC"
    if re.search(r"\b(el t[eé]cnico|el equipo t[eé]cnico)\b[^.]*\b(debe|deber[aá]|tiene que|realizar[aá])\b", s, re.I):
        return "pasoT"
    return "obs"


def borrador(texto: str, adjuntos: Optional[List[str]] = None) -> Dict[str, Any]:
    ctx = _cmd_split(texto)
    d = datos(texto)
    con = conexiones(texto)
    obs: List[str] = []
    recs: List[str] = []
    pasos: List[Dict[str, str]] = []
    for s in ctx:
        s0 = s.strip()
        if re.search(r"raz[oó]n social|\bruc\b|se llama|encargad|celular|@|direcci[oó]n\s+(es|:)", s0, re.I):
            continue
        if CONEXION.match(s0.rstrip(".;")) and re.search(r"conectad|por (cable|wi-?fi|usb)", s0, re.I):
            continue
        k = _clasificar(s0)
        txt = _cap(s0) + ("" if s0.endswith(".") else ".")
        if k == "rec":
            recs.append(txt)
        elif k == "pasoC":
            pasos.append({"p": "Cliente", "t": txt})
        elif k == "pasoT":
            pasos.append({"p": "ID", "t": txt})
        else:
            obs.append(txt)
    adj = list(adjuntos or [])
    faltan = [e for e in EVIDENCIAS if e not in adj]
    out = {"datos": d, "conexiones": con, "observaciones": obs, "recomendaciones": recs, "pasos": pasos,
           "evidencias": adj, "faltan": faltan, "pideConexiones": not con, "fuente": "reglas"}
    return _completar_con_ia(texto, out)


def _completar_con_ia(texto: str, out: Dict[str, Any]) -> Dict[str, Any]:
    """Con OPENAI_API_KEY, ChatGPT completa los campos que las reglas no encontraron. No envía contraseñas ni claves."""
    key = os.getenv("OPENAI_API_KEY")
    if not key or os.getenv("ASISTENTE_SIN_IA"):
        return out
    campos = ["local", "razon", "ruc", "direccion", "encargado", "celular", "correo", "rubro", "internet"]
    faltan = [c for c in campos if c not in out["datos"]]
    if not faltan and out["conexiones"]:
        return out
    try:
        from openai import OpenAI
        limpio = re.sub(r"(contrase[ñn]a|clave|password)\s*(es|:)?\s*\S+", r"\1 [oculta]", texto, flags=re.I)
        r = OpenAI(api_key=key, timeout=float(os.getenv("ASISTENTE_TIMEOUT_S", "12"))).chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": (
                "Extraes datos de una visita técnica de red para una minuta. Responde SOLO JSON con las claves: "
                f"datos (objeto con solo estas claves si aparecen en el texto: {', '.join(faltan)}), "
                "conexiones (lista de {desde, hacia, medio: Cable|WiFi|USB}; nombres cortos: «IMP. Cocina», «PC Caja», «Router», «Switch», «Repetidor · Salón 2»; "
                "si un enlace cambia, deja el último medio). No inventes: si no está en el texto, omítelo.")},
                {"role": "user", "content": limpio}])
        j = json.loads(r.choices[0].message.content or "{}")
        for k, v in (j.get("datos") or {}).items():
            if k in faltan and v:
                out["datos"][k] = str(v)
        if not out["conexiones"]:
            vistos = set()
            for c in j.get("conexiones") or []:
                if c.get("desde") and c.get("hacia") and c.get("medio") in ("Cable", "WiFi", "USB") and (c["desde"], c["hacia"]) not in vistos:
                    vistos.add((c["desde"], c["hacia"]))
                    out["conexiones"].append({"desde": c["desde"], "hacia": c["hacia"], "medio": c["medio"]})
            out["pideConexiones"] = not out["conexiones"]
        out["fuente"] = "chatgpt"
    except Exception:  # noqa: BLE001 — sin conexión con OpenAI queda lo que leyeron las reglas
        pass
    return out
