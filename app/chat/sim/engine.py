"""Motor del chat (estado, respuestas, evidencias, correcciones) sobre la lógica del simulador.

El servidor sigue sin estado propio: el cliente manda el `state` que recibió y la respuesta al nodo actual. El estado
es la lista de eventos (`order`) tal como en el simulador; todo (nodos, reglas, puntajes) se vuelve a calcular a partir
de ahí con `build()`, así que editar una respuesta anterior es simplemente quitar su evento.
"""
import copy
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from app.chat.sim import vision
from app.chat.sim.flow import CAT, PC, PERFIL, build, fmt_date, is_ev_step
from app.chat.sim.reading import field_specs, read_label
from app.chat.sim.rules import evaluate, gen_pasos
from app.chat.sim.scoring import resumen_ia, scores
from app.chat.sim.util import Obj, jsround, parse_int

BLOCKS: Dict[str, str] = CAT["BLOQUES"]
BLOCK_KEYS = list(BLOCKS)
RC_FIELDS = CAT["RC_FIELDS"]
ERR = CAT["ERR"]
EV_LIKE = CAT["EV_LIKE"]
EV_LIKE_N = CAT["EV_LIKE_N"]
STATE_VERSION = 2
# Qué lee la IA en las fotos que se muestran como "photo" (no tienen lectura propia en el chat)
AI_READ_BY_ID = {"E2": "ports", "E2e": "routerlabel"}

ESTADO_LOCAL = {
    "EN_OPERACION": "el local está en operación: puede verse con gente, desordenado, con poca luz o con equipos tapados",
    "EN_OBRA": "el local está EN OBRA: puede verse sin terminar, vacío, con equipos cubiertos o sin instalar",
    "POR_INAUGURAR": "el local está por inaugurar: puede verse con equipos nuevos sin instalar o embalados",
    "SISTEMA_ANTERIOR": "el local ya funciona con otro sistema: puede verse con equipos antiguos",
}


def place_desc(it: Dict[str, Any], estado: Optional[str]) -> str:
    """Qué lugar es la foto (para que la IA no rechace fotos buenas por un nombre de área que no conoce)."""
    t = it.get("t") or ""
    k = it.get("k") or ""
    if k.startswith("Frontis"):
        desc = "el frontis o fachada del local"
    elif "preparación" in t:
        desc = f"un lugar de preparación de alimentos o bebidas (cocina, barra, zona caliente o fría, despacho) llamado «{k}»"
    elif "Zona de atención" in t:
        desc = f"una zona de atención al público (salón, terraza, mostrador) llamada «{k}»"
    elif "caja" in t.lower():
        desc = f"la caja o punto de cobro «{k}»"
    else:
        desc = f"el lugar «{k}» del local"
    return f"{desc}; {ESTADO_LOCAL.get(estado or '', 'puede estar en cualquier estado')}"


SI_RE = re.compile(r"^(s[ií]\b|claro|tiene\b|hay\b|a veces|algun|de vez|ocasional|frecuent|seguido|todos|siempre)", re.I)
NO_RE = re.compile(r"^(no\b|nunca|ningun|jam[aá]s)", re.I)
NO_SE = re.compile(r"^(no\s*s[eé]|no\s*lo\s*s[eé]|no\s*(lo\s*)?tengo|no\s*sabe|no\s*hay|desconozco)(?=[\s.,!]|$)", re.I)
POR_CONFIRMAR = {"P01b", "P04"}
TOPE = {"P12": (1, 20), "P15": (1, 10000), "P47a": (0, 64)}


def _n(s: Any) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(s).lower()) if unicodedata.category(c) != "Mn").strip()


def match_option(n: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
    """Busca la opción que corresponde a lo que el usuario escribió (sin tildes ni mayúsculas)."""
    t, opts = _n(text), [o for o in n["opts"] if not o.get("otro")]
    if NO_SE.match(text.strip()):
        return next((o for o in n["opts"] if re.search(r"no (lo )?s[eé]|saltar|omitir|a[uú]n no lo decide", o["l"], re.I)), None)
    hit = [o for o in opts if _n(o["l"]) == t or str(o["v"]).lower() == t]
    try:
        k = float(text.replace(",", "."))
        hit = hit or [o for o in opts if o["v"] == k or o["l"].split(" ")[0] == text]
    except ValueError:
        pass
    hit = hit or [o for o in opts if t and t in _n(o["l"])]
    return hit[0] if len(hit) == 1 else None


def norm_pc(id_: str, val: Dict[str, Any], unit: str = "") -> Dict[str, Any]:
    """«No lo sé ahora» y «Otro» de las preguntas que dependen del cliente."""
    base = id_.split("#")[0]
    if base not in PC:
        return val
    if val["v"] == "NS52":
        return {"v": PC[base], "label": "Por confirmar", "pc52": True}
    if val["v"] != "OTRO":
        return val
    t = str(val["label"]).strip()
    if base in TOPE:
        m = re.search(r"\d+", t)
        k = int(m.group()) if m else None
        ok = k is not None and TOPE[base][0] <= k <= TOPE[base][1]
        label = f"{k} {unit}".strip() if ok and re.fullmatch(r"\d+", t) else t
        return {"v": k if ok else PC[base], "label": label, "pc52": not ok}
    if base == "P09c":
        return {"v": "NO", "label": t} if NO_RE.match(t) else {"v": "OTRO", "label": t}
    if base == "P22b":
        m = "RASPBERRY" if re.search(r"rasp", t, re.I) else "LAPTOP" if re.search(r"laptop|port[aá]til", t, re.I) \
            else "PC" if re.search(r"\bpc\b|computador", t, re.I) else None
        return {"v": m or PC[base], "label": t, "pc52": m is None}
    m = "SI" if SI_RE.match(t) else "NO" if NO_RE.match(t) else None
    return {"v": m or PC[base], "label": t, "pc52": m is None}


class StepError(Exception):
    """La respuesta no es válida: el nodo no avanza y se muestra el mensaje."""


def new_state(ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {"v": STATE_VERSION, "ctx": ctx, "order": [], "pending": None}


def is_v2(state: Any) -> bool:
    return isinstance(state, dict) and state.get("v") == STATE_VERSION


def _tv(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {"r": x, "m": "tomar" if x == "il" else "subir"}


class Session:
    def __init__(self, state: Dict[str, Any]):
        self.state = state
        self.replay()

    # ---- estado ------------------------------------------------------------
    def replay(self) -> None:
        self.A: Dict[str, Any] = {}
        self.TRIES: Dict[str, List[Any]] = {}
        for e in self.state["order"]:
            if e["t"] == "ans":
                self.A[e["id"]] = e["val"]
            elif e["t"] == "try":
                self.TRIES.setdefault(e["id"], []).append(e["val"])
        # 0.0.15: descripción de cada evidencia («¿Qué muestra esta foto?»). Se guarda aparte, así sigue aunque se cambie la foto.
        descs: Dict[str, str] = {}
        for e in self.state["order"]:
            if e["t"] == "desc":
                descs[e["id"]] = str(e.get("val") or "").strip()
        for k, t in descs.items():
            if isinstance(self.A.get(k), dict):
                ans = {kk: vv for kk, vv in self.A[k].items() if kk != "desc"}
                self.A[k] = {**ans, "desc": t} if t else ans
        self.DESCS = {k: t for k, t in descs.items() if t}
        N, X = build(self.A, self.state["ctx"])
        self.N, self.X = N, X
        self._R: Optional[Obj] = None

    @property
    def R(self) -> Obj:
        if self._R is None:
            self._R = evaluate(self.X, self.A)
        return self._R

    def _push(self, entry: Dict[str, Any]) -> None:
        before = {n["id"]: n.get("text", "") for n in self.N} if self.state.get("edit") else {}
        self.state["order"].append(entry)
        self.replay()
        ed = self.state.get("edit")
        if ed and entry.get("t") == "ans" and entry.get("id") == ed.get("id"):
            # Se respondió la pregunta que se estaba editando: solo se borran las respuestas que dependían de ella.
            self.state.pop("edit", None)
            self.current()  # cierra la lista de fotos si ya está completa
            self.state["editReset"] = self.prune(before)

    # ---- edición: conservar lo que no depende ---------------------------------
    def _valid_ids(self, completo: bool = False) -> set:
        N = complete_nodes(self.A, self.state["ctx"]) if completo else self.N
        ids = {n["id"] for n in N}
        for n in N:
            if n["kind"] == "check":
                ids.update(f"{n['id']}#{it['k']}" for it in n.get("items", []))
        return ids

    @staticmethod
    def _choice_ok(n: Dict[str, Any], val: Any) -> bool:
        if not isinstance(val, dict) or val.get("pc52"):
            return True
        v = val.get("v")
        if any(o["v"] == v or str(o["v"]) == str(v) for o in n.get("opts", [])):
            return True
        otro = next((o for o in n.get("opts", []) if o.get("otro")), None)
        # con «Otro (escribir)» se guarda "OTRO" o el número escrito (cajas, Mbps…)
        return otro is not None and (v == "OTRO" or (isinstance(v, (int, float)) and not isinstance(v, bool)))

    def prune(self, before: Optional[Dict[str, str]] = None) -> List[str]:
        """Borra las respuestas cuya pregunta ya no existe o cuya opción ya no se ofrece
        (dependían de la respuesta editada). Devuelve el texto de esas preguntas."""
        texts: Dict[str, str] = {**{n["id"]: n.get("text", "") for n in self.N}, **(before or {})}
        reset: List[str] = []
        for _ in range(20):
            # con lo que falta respondido con lo sugerido: lo que aún no se preguntó (por ejemplo, la impresora de un área nueva)
            # no esconde las respuestas que vienen después
            full = complete_nodes(self.A, self.state["ctx"])
            valid = self._valid_ids(completo=True)
            byid = {n["id"]: n for n in full}
            bad = set()
            for e in self.state["order"]:
                if e["t"] != "ans":
                    continue
                i = e["id"]
                if i not in valid:
                    bad.add(i)
                    continue
                n = byid.get(i)
                if n and n["kind"] == "choice" and not self._choice_ok(n, self.A.get(i)):
                    bad.add(i)
                elif n and n["id"] == "P33a" and isinstance((self.A.get(i) or {}).get("v"), list) \
                        and any(x not in n.get("opts", []) for x in self.A[i]["v"]):
                    bad.add(i)
            if not bad:
                break
            for i in bad:
                t = texts.get(i) or ("Foto: " + i.split("#", 1)[1] if "#" in i else "")
                if t and t not in reset:
                    reset.append(t)
            self.state["order"] = [e for e in self.state["order"] if e["id"] not in bad]
            self.replay()
            texts.update({n["id"]: n.get("text", "") for n in self.N})
        return reset

    def _commit(self, id_: str, val: Dict[str, Any]) -> None:
        self.state["pending"] = None
        self._push({"t": "ans", "id": id_, "val": val})

    # ---- nodo actual -------------------------------------------------------
    def node_index(self, id_: str) -> int:
        return next((i for i, n in enumerate(self.N) if n["id"] == id_), -1)

    def current(self) -> Optional[Dict[str, Any]]:
        """Nodo a responder ahora. Las listas de fotos (`check`) se presentan de a una foto."""
        for _ in range(60):
            cur = None
            for n in self.N:
                if n["kind"] == "alert":
                    continue
                if n["kind"] == "fin":
                    return n
                if self.A.get(n["id"]) is None:
                    cur = n
                    break
            if cur is None:
                return None
            if cur["kind"] != "check":
                return cur
            item = self._next_item(cur)
            if item is not None:
                return item
            # todas las fotos de la lista están listas: se cierra la lista
            self._push({"t": "ans", "id": cur["id"], "val": {"v": "OK", "label": ""}})
        return None

    def _item(self, check: Dict[str, Any], it: Dict[str, Any]) -> Dict[str, Any]:
        """Una foto de la lista (frontis, lugar de preparación, zona, caja) como nodo de evidencia."""
        return {"id": f"{check['id']}#{it['k']}", "kind": "ev", "b": check.get("b"), "read": "photo", "name": it["k"], "item": it,
                "text": f"{it['k']}: {it['t']}. Toma o sube la foto." if it.get("t") else f"{it['k']}: toma o sube la foto.",
                "optional": bool(it.get("opt")), "def": {"data": {}}, "parent": check["id"],
                "placeDesc": place_desc(it, getattr(self.X, "estadoV", None))}

    def _next_item(self, check: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for it in check["items"]:
            if self.A.get(f"{check['id']}#{it['k']}") is None:
                return self._item(check, it)
        return None

    def item_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Nodo de una foto de la lista aunque ya no sea la actual (para subir las de «Subir después»)."""
        cid, _, k = node_id.partition("#")
        check = next((x for x in self.N if x["id"] == cid and x["kind"] == "check"), None)
        it = next((i for i in (check or {}).get("items", []) if i["k"] == k), None)
        return self._item(check, it) if check and it else None

    def set_desc(self, node_id: str, text: Optional[str]) -> None:
        """Agrega, cambia o borra (texto vacío) la descripción de una evidencia ya subida o la que se está subiendo."""
        valid = self._valid_ids()
        if node_id not in valid:
            raise StepError("No encontré esa evidencia.")
        n = next((x for x in self.N if x["id"] == node_id), None)
        if n is not None and n["kind"] not in ("ev", "check"):
            raise StepError("Solo las evidencias llevan descripción.")
        t = (text or "").strip()[:500]
        if t == (self.DESCS.get(node_id) or ""):
            return
        self._push({"t": "desc", "id": node_id, "val": t})

    def evidence_notes(self) -> Dict[str, str]:
        return dict(self.DESCS)

    def pending_later(self) -> List[str]:
        """Fotos obligatorias dejadas para después: se piden antes de generar la minuta."""
        return [k for k, v in self.A.items() if isinstance(v, dict) and v.get("v") == "LATER"]

    # ---- respuestas --------------------------------------------------------
    def answer(self, text: str) -> None:
        n = self.current()
        if n is None or n["kind"] == "fin":
            raise StepError("La evaluación ya terminó.")
        kind = n["kind"]
        text = (text or "").strip()
        if kind == "ev":
            return self._answer_evidence(n, text)
        val = self._parse(n, text)
        self._commit(n["id"], val)

    def _opt_label(self, o: Dict[str, Any]) -> str:
        return str(o["l"]).replace(" (lo más común)", "").replace(" (se ve en la foto)", "")

    def _parse(self, n: Dict[str, Any], text: str) -> Dict[str, Any]:
        kind = n["kind"]
        if kind == "choice":
            if text.startswith("OTRO:"):
                other = text[5:].strip()
                opt = next((o for o in n["opts"] if o.get("otro")), None)
                if opt is None or not other:
                    raise StepError("Escribe cuál es.")
                if opt.get("num"):
                    try:
                        k = float(other.replace(",", "."))
                    except ValueError:
                        raise StepError("Escribe un número.") from None
                    if not k > 0:
                        raise StepError("Escribe un número mayor que 0.")
                    k = int(k) if k.is_integer() else k
                    unit = n.get("unit") or ""
                    return {"v": k, "label": f"{k} {unit}".strip()}
                return norm_pc(n["id"], {"v": "OTRO", "label": other}, n.get("unit") or "")
            for o in n["opts"]:
                if str(o["v"]) == text:
                    if o.get("otro"):
                        raise StepError("Escribe cuál es.")
                    return norm_pc(n["id"], {"v": o["v"], "label": self._opt_label(o)}, n.get("unit") or "")
            o = match_option(n, text)
            if o is not None and not o.get("otro"):
                return norm_pc(n["id"], {"v": o["v"], "label": self._opt_label(o)}, n.get("unit") or "")
            raise StepError("Elige una de las opciones.")
        if kind == "multi":
            if text == "@NONE":
                return {"v": [], "label": n.get("none") or "Ninguno"}
            try:
                arr = json.loads(text) if text else []
            except ValueError:
                arr = [t.strip() for t in text.split("|") if t.strip()]
            if not isinstance(arr, list):
                raise StepError("Respuesta no válida.")
            arr = [str(x).strip() for x in arr if str(x).strip()]
            if n.get("min") and not arr:
                raise StepError("Elige al menos una opción.")
            if n["id"] == "P33a" and any(x not in n.get("opts", []) for x in arr):
                # «Equipos sin tomas cerca» guardaba textos como «Si» como si fueran equipos (minuta AMAT ROOFTOP)
                raise StepError("Elige los equipos de la lista o toca «Ninguno».")
            return {"v": arr, "label": ", ".join(arr) if arr else "Ninguno"}
        if kind == "text":
            if n["id"] in POR_CONFIRMAR and (text in ("No lo tengo ahora", "No está en el local") or NO_SE.match(text)):
                return {"v": "", "label": "Por confirmar"}
            if text in n.get("sug", []) and text in ("Saltar", "Continuar sin enlace"):
                return {"v": "", "label": text}
            t = re.sub(r"\s+", "", text) if n.get("num") else text
            if not t:
                raise StepError("Escribe la respuesta.")
            err = n["valid"](t) if n.get("valid") else ""
            if err:
                raise StepError(err)
            return {"v": t, "label": t}
        if kind == "longtext":
            return {"v": text, "label": text or "(sin texto)"}
        if kind == "date":
            if not text:
                if n.get("req"):
                    raise StepError("Elige una fecha.")
                return {"v": "", "label": "Sin fecha"}
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                raise StepError("La fecha debe ser AAAA-MM-DD.")
            return {"v": text, "label": fmt_date(text)}
        if kind == "wifi":
            data = self._json(text, dict)
            out = {}
            for z in n["zones"]:
                m = data.get(z)
                if m is not None:
                    out[z] = {"dbm": _num(m.get("dbm")), "ping": _num(m.get("ping"))}
            return {"v": out, "label": ""}
        if kind == "rcard":
            d = self._json(text, dict)
            out = {k: d.get(k) for k in ("ip", "proveedor", "marca", "modelo", "sn")}
            for k in ("ssid", "clave"):  # red WiFi del router y su contraseña (van a la minuta)
                if k in d:
                    out[k] = str(d.get(k) or "")
            for k in ("puertos", "libres", "ocupados"):
                v = d.get(k)
                out[k] = None if v in (None, "") else _num(v)
            return {"v": out, "label": ""}
        if kind == "links":
            arr = self._json(text, list) if text else []
            clean = [{"d": str(x.get("d") or "").strip(), "u": str(x.get("u") or "").strip()} for x in arr if isinstance(x, dict) and str(x.get("u") or "").strip()]
            return {"v": clean, "label": f"{len(clean)} enlace{'s' if len(clean) > 1 else ''}" if clean else "Continuar sin enlaces"}
        if kind == "pasos":
            arr = self._json(text, list)
            clean = [{"p": "Cliente" if str(x.get("p")) == "Cliente" else "ID", "t": str(x.get("t") or "").strip()} for x in arr if isinstance(x, dict) and str(x.get("t") or "").strip()]
            return {"v": clean, "label": ""}
        if kind == "summary":
            return {"v": "OK", "label": "Continuar al diagnóstico"}
        raise StepError("Tipo de pregunta no admitido.")

    @staticmethod
    def _json(text: str, typ: type) -> Any:
        try:
            v = json.loads(text)
        except ValueError:
            raise StepError("Respuesta no válida.") from None
        if not isinstance(v, typ):
            raise StepError("Respuesta no válida.")
        return v

    # ---- evidencias ---------------------------------------------------------
    def last_try(self, id_: str) -> Optional[str]:
        t = self.TRIES.get(id_) or []
        return _tv(t[-1])["r"] if t else None

    def evidence_skippable(self, n: Dict[str, Any]) -> bool:
        if n.get("parent"):
            return bool(n.get("optional"))
        return True

    def _answer_evidence(self, n: Dict[str, Any], text: str) -> None:
        id_ = n["id"]
        pending = self.state.get("pending")
        if text == "@LATER":
            if not n.get("parent") or n.get("optional"):
                raise StepError("«Subir después» es solo para las fotos obligatorias del local.")
            self.state["pending"] = None
            self._commit(id_, {"v": "LATER", "label": "Subir después"})
            return
        if text == "@SKIP":
            if not self.evidence_skippable(n):
                raise StepError("Esta foto es obligatoria: no se puede saltar.")
            wrong = self.last_try(id_) == "wrong"
            self._commit(id_, {"v": "SKIP", "label": "Continuar sin esta lectura" if wrong else "Saltar evidencia"})
            return
        if text == "@WRONG":
            m = (pending or {}).get("m", "subir")
            self.state["pending"] = None
            self._push({"t": "try", "id": id_, "val": {"r": "wrong", "m": m}})
            return
        if not text.startswith("{"):
            raise StepError("Sube o toma la foto.")
        if not pending or pending.get("id") != id_:
            raise StepError("Primero sube la foto.")
        data = self._json(text, dict)
        fields = field_specs(n["read"])
        clean: Dict[str, Any] = {}
        for f in fields:
            k = f["key"]
            if k not in data:
                continue
            v = data[k]
            if f["type"] in ("text", "sel"):
                clean[k] = "" if v is None else str(v).strip()
            else:
                clean[k] = None if v in (None, "") else _num(v)
        if isinstance(data.get("_del"), list):
            clean["_del"] = [k for k in data["_del"] if any(f["key"] == k for f in fields)]
            for k in clean["_del"]:
                clean.pop(k, None)
        if pending.get("extra"):
            clean["_ai"] = pending["extra"]  # datos extra que leyó la IA (proveedor, servidor, dispositivos del escáner...)
        self._commit(id_, {"v": "OK", "data": clean, "label": "", "m": pending.get("m", "subir")})

    def upload(self, images: List[str], mode: str = "subir", nota: Optional[str] = None,
               node_id: Optional[str] = None, descripcion: Optional[str] = None) -> Dict[str, Any]:
        """Revisa las fotos del nodo actual (o de una foto pendiente de «Subir después», con `node_id`).

        mode "forzar": el usuario confirma que la foto que la IA observó es la correcta («Guardar como correcta»):
        se guarda sin volver a rechazarla, con su nota opcional (la minuta muestra solo la nota)."""
        if node_id:
            if (self.A.get(node_id) or {}).get("v") != "LATER":
                raise StepError("Esa foto no está pendiente.")
            n = self.item_node(node_id)
        else:
            n = self.current()
        if n is None or n["kind"] != "ev":
            raise StepError("Ahora no se pide ninguna foto.")
        id_ = n["id"]
        base = id_.split("#")[0]
        read = AI_READ_BY_ID.get(base) or (n["read"] if n["read"] != "photo" else ("place" if n.get("placeDesc") else "photo"))
        desc = n.get("placeDesc") or n.get("name") or ""
        # lo que el técnico escribió de la foto ayuda a la IA a leerla (se verifica igual con la imagen)
        nueva = (descripcion or "").strip()[:500]
        if nueva and nueva != self.DESCS.get(id_):
            self._push({"t": "desc", "id": id_, "val": nueva})
        tec = nueva or self.DESCS.get(id_, "")
        if tec:
            desc = f"{desc}. El técnico describe la foto así: «{tec[:300]}»" if desc else f"El técnico describe la foto así: «{tec[:300]}»"
        if mode == "forzar":
            if self.last_try(id_) not in ("nc", "il"):
                raise StepError("Solo se puede guardar como correcta una foto que la IA observó.")
            res = vision.VisionResult(corresponde=True, legible=True) if os.getenv("VISION_MOCK") else vision.analyze(read, desc, images)
            data = {**(res.data or {}), "_forzada": True, "_nota": (nota or "").strip(), "_iaVio": res.queMuestra}
            self._commit(id_, {"v": "OK", "data": data, "label": "Guardada como correcta", "m": "subir",
                               "count": len(images), "forzada": True})
            return {"nodeId": id_, "count": len(images), "status": "OK", "extracted": data,
                    "processedImages": res.processedImages}
        if os.getenv("VISION_MOCK"):
            # Solo para pruebas locales sin IA: devuelve la lectura de ejemplo del nodo.
            mock = {"ports": {"puertos": 4, "libres": 2, "ocupados": 2},
                    "routerlabel": {"marca": "Huawei", "modelo": "HG8145V5", "sn": "48575443A1B2C3D4"}}.get(read) \
                or dict((n.get("def") or {}).get("data") or {})
            res = vision.VisionResult(corresponde=True, legible=True, data=mock)
        else:
            res = vision.analyze(read, desc, images)
        info: Dict[str, Any] = {"nodeId": id_, "count": len(images), "processedImages": res.processedImages}
        if res.corresponde is False:
            self._push({"t": "try", "id": id_, "val": {"r": "nc", "m": mode, "like": res.queMuestra}})
            info["status"] = "NC"
            return info
        if res.legible is False:
            self._push({"t": "try", "id": id_, "val": {"r": "il", "m": mode}})
            info["status"] = "IL"
            return info
        has_review = bool(field_specs(n["read"])) and n["read"] != "photo"
        if has_review:
            defaults = (n.get("def") or {}).get("data") or {}
            data = {k: res.data.get(k) for k in [f["key"] for f in field_specs(n["read"])] if res.data.get(k) is not None}
            extras = {k: v for k, v in res.data.items() if k not in data}
            self.state["pending"] = {"id": id_, "m": mode, "data": {**data}, "extra": extras, "unavailable": res.unavailable,
                                     "count": len(images)}
            info["status"] = "REVIEW"
            info["unavailable"] = res.unavailable
            info["extracted"] = {**data, **extras}
            return info
        self._commit(id_, {"v": "OK", "data": {**res.data}, "label": "", "m": mode, "count": len(images)})
        info["status"] = "OK"
        info["extracted"] = dict(res.data)
        return info

    def amend_reading(self, node_id: str, fields: Dict[str, Any], deleted: Optional[List[str]] = None, restore: bool = False) -> None:
        """Corrige o elimina lecturas de una evidencia ya respondida."""
        cur = self.A.get(node_id)
        if not cur or cur.get("v") != "OK":
            raise StepError("Esa evidencia no tiene lectura para corregir.")
        data = dict(cur.get("data") or {})
        if restore:
            data.pop("_del", None)
        for k, v in fields.items():
            data[k] = None if v in (None, "") else v
        if deleted is not None:
            dels = [k for k in deleted]
            for k in dels:
                data.pop(k, None)
            data["_del"] = dels
        self._push({"t": "ans", "id": node_id, "val": {**cur, "data": data}})

    # ---- edición de respuestas anteriores -----------------------------------
    def rewind(self, node_id: str) -> None:
        """Vuelve a esa pregunta: se borra ella y todo lo que se respondió después."""
        order = self.state["order"]
        if node_id == "EV":
            idx = next((i for i, e in enumerate(order) if e["id"] == "EV" or str(e["id"]).startswith("EV#")), -1)
        else:
            idx = next((i for i, e in enumerate(order) if e["id"] == node_id or str(e["id"]).startswith(node_id + "#") and node_id in ("EV", "EVQ")), -1)
        if idx < 0:
            raise StepError("No encontré esa respuesta.")
        self.state["order"] = order[:idx]
        self.state["pending"] = None
        self.replay()

    def reopen(self, node_id: str) -> None:
        """Editar una respuesta (en curso o terminada): solo esa pregunta se vuelve a hacer, con la respuesta
        anterior ya marcada. Las demás respuestas se conservan; al responder se borran solo las que dependían de ella."""
        keep = []
        prefix = node_id + "#"
        prev = self.A.get(node_id)
        if prev is not None and node_id not in ("EV", "EVQ"):
            self.state["edit"] = {"id": node_id, "prev": prev}
        else:
            self.state.pop("edit", None)
        self.state.pop("editReset", None)
        # una foto de una lista (EV#Frontis del local…): también se reabre la lista para que la vuelva a pedir
        parent = node_id.split("#")[0] if "#" in node_id and any(n["id"] == node_id.split("#")[0] and n["kind"] == "check"
                                                                   for n in self.N) else None
        for e in self.state["order"]:
            eid = str(e["id"])
            if e["t"] == "desc":
                keep.append(e)  # la descripción de la foto se conserva aunque se cambie la foto
                continue
            if eid == node_id or (node_id in ("EV", "EVQ") and eid.startswith(prefix)) or (parent and eid == parent and e["t"] == "ans"):
                continue
            keep.append(e)
        if len(keep) == len(self.state["order"]):
            raise StepError("No encontré esa respuesta.")
        self.state["order"] = keep
        self.state["pending"] = None
        self.replay()

    # ---- avisos (alertas) ----------------------------------------------------
    def alerts_between(self, after_id: Optional[str], before: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Avisos que quedan entre el nodo recién respondido y el nodo actual."""
        start = 0
        if after_id:
            idx = self.node_index(after_id)
            if idx < 0 and "#" in after_id:
                idx = self.node_index(after_id.split("#")[0])
            start = idx + 1
        end = self.node_index(before["id"]) if before and self.node_index(before["id"]) >= 0 else len(self.N)
        if before and before.get("parent"):
            end = self.node_index(before["parent"])
        return [{"id": n["id"], "tone": n.get("tone", "info"), "tag": n.get("tag"), "text": n["text"]}
                for n in self.N[start:end] if n["kind"] == "alert"]

    # ---- contadores -----------------------------------------------------------
    def counts(self) -> Dict[str, Any]:
        q = qa = e = ea = 0
        for n in self.N:
            if n["kind"] in ("alert", "fin"):
                continue
            done = self.A.get(n["id"]) is not None
            if n["kind"] == "check":
                for it in n["items"]:
                    e += 1
                    if (self.A.get(f"{n['id']}#{it['k']}") or {}).get("v") not in (None, "LATER"):
                        ea += 1
                continue
            if is_ev_step(n):
                e += 1
                ea += 1 if done else 0
            else:
                q += 1
                qa += 1 if done else 0
        est = estimate(self.A, self.state["ctx"])
        return {"q": max(q, est["q"]), "qa": qa, "e": max(e, est["e"]), "ea": ea}

    def percent(self) -> int:
        """Avance sobre el total estimado (preguntas + evidencias), igual que el contador «Pregunta N de ~T»."""
        c = self.counts()
        return min(99, jsround(100 * (c["qa"] + c["ea"]) / max(c["q"] + c["e"], 1)))

    # ---- respuestas que vienen de un adjunto ----------------------------------------
    def apply_prefill(self) -> List[str]:
        """Responde en orden las preguntas que ya tienen dato del adjunto. Se detiene en la primera que no valida."""
        pre = self.state.setdefault("pre", {})
        used: List[str] = []
        for _ in range(40):
            n = self.current()
            if not n or n["id"] not in pre:
                break
            c = pre.pop(n["id"])
            if self.A.get(n["id"]) is not None:
                continue
            try:
                val = self._parse(n, str(c["v"]))
            except StepError:
                break
            val["src"] = "adjunto"
            self.state["order"].append({"t": "ans", "id": n["id"], "val": val})
            self.replay()
            used.append(n["id"])
        return used

    def por_confirmar(self) -> List[str]:
        """Lo que quedó «Por confirmar» (RUC, encargado y preguntas del cliente), en palabras."""
        from app.chat.sim.flow import TEMA
        out = [t for k, t in (("P01b", "el RUC"), ("P04", "el nombre y cargo del encargado del local"))
               if (self.A.get(k) or {}).get("label") == "Por confirmar"]
        for k, e in self.A.items():
            b = k.split("#")[0]
            if b in TEMA and (e or {}).get("pc52"):
                out.append(TEMA[b] + (f" ({k.split('#')[1]})" if "#" in k else ""))
        return out

    # ---- salidas ----------------------------------------------------------------
    def scores(self) -> Obj:
        return scores(self.X, self.R, self.A)


def _num(v: Any) -> Any:
    try:
        f = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        raise StepError("Escribe un número válido.") from None
    return int(f) if f.is_integer() else f


def estimate(a: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, int]:
    """Total estimado de preguntas y evidencias: completa lo que falta con las respuestas sugeridas."""
    N = complete_nodes(a, ctx)
    q = e = 0
    for n in N:
        if n["kind"] in ("alert", "fin"):
            continue
        if n["kind"] == "check":
            e += len(n["items"])
        elif is_ev_step(n):
            e += 1
        else:
            q += 1
    return {"q": q, "e": e}


def complete_nodes(a: Dict[str, Any], ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Todos los nodos del flujo si lo que falta se respondiera con lo sugerido (no guarda nada).
    Sirve para el total estimado y, al editar, para saber qué respuestas siguen teniendo pregunta."""
    a2 = copy.deepcopy(a)
    N: List[Dict[str, Any]] = []
    for _ in range(400):
        N, _x = build(a2, ctx)
        n = next((x for x in N if x["kind"] not in ("alert", "fin") and a2.get(x["id"]) is None), None)
        if n is None:
            break
        d = n.get("def")
        k = n["kind"]
        if k == "ev":
            v = {"v": "OK", "data": dict((d or {}).get("data") or {})}
        elif k in ("check", "summary"):
            v = {"v": "OK", "label": ""}
        elif k == "multi":
            v = {"v": d if isinstance(d, list) else [], "label": ""}
        elif k == "choice":
            o = next((o for o in n["opts"] if o["v"] == d), None) or (n["opts"][0] if n["opts"] else {"v": d, "l": ""})
            v = {"v": o["v"], "label": o["l"]}
        elif k == "rcard":
            v = {"v": dict(d or {}), "label": ""}
        elif k in ("links", "pasos"):
            v = {"v": [], "label": ""}
        elif k == "wifi":
            v = {"v": {}, "label": ""}
        else:
            v = {"v": "" if d is None else d, "label": "" if d is None else str(d)}
        a2[n["id"]] = v
    return N
