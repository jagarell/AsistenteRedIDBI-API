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
from app.chat.sim.flow import CAT, PERFIL, build, fmt_date, is_ev_step
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
        N, X = build(self.A, self.state["ctx"])
        self.N, self.X = N, X
        self._R: Optional[Obj] = None

    @property
    def R(self) -> Obj:
        if self._R is None:
            self._R = evaluate(self.X, self.A)
        return self._R

    def _push(self, entry: Dict[str, Any]) -> None:
        self.state["order"].append(entry)
        self.replay()

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

    def _next_item(self, check: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for it in check["items"]:
            iid = f"{check['id']}#{it['k']}"
            if self.A.get(iid) is None:
                return {"id": iid, "kind": "ev", "b": check.get("b"), "read": "photo", "name": it["k"], "item": it,
                        "text": f"{it['k']}: {it['t']}. Toma o sube la foto." if it.get("t") else f"{it['k']}: toma o sube la foto.",
                        "optional": bool(it.get("opt")), "def": {"data": {}}, "parent": check["id"]}
        return None

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
                return {"v": "OTRO", "label": other}
            for o in n["opts"]:
                if str(o["v"]) == text:
                    if o.get("otro"):
                        raise StepError("Escribe cuál es.")
                    return {"v": o["v"], "label": self._opt_label(o)}
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
            return {"v": arr, "label": ", ".join(arr) if arr else "Ninguno"}
        if kind == "text":
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

    def upload(self, images: List[str], mode: str = "subir") -> Dict[str, Any]:
        """Revisa las fotos del nodo actual. Devuelve {status, ...} y deja el estado listo para responder."""
        n = self.current()
        if n is None or n["kind"] != "ev":
            raise StepError("Ahora no se pide ninguna foto.")
        id_ = n["id"]
        base = id_.split("#")[0]
        read = AI_READ_BY_ID.get(base) or (n["read"] if n["read"] != "photo" else "photo")
        if os.getenv("VISION_MOCK"):
            # Solo para pruebas locales sin IA: devuelve la lectura de ejemplo del nodo.
            mock = {"ports": {"puertos": 4, "libres": 2, "ocupados": 2},
                    "routerlabel": {"marca": "Huawei", "modelo": "HG8145V5", "sn": "48575443A1B2C3D4"}}.get(read) \
                or dict((n.get("def") or {}).get("data") or {})
            res = vision.VisionResult(corresponde=True, legible=True, data=mock)
        else:
            res = vision.analyze(read, n.get("name") or "", images)
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
        """Modo edición (evaluación terminada): solo esa pregunta se vuelve a hacer."""
        keep = []
        prefix = node_id + "#"
        for e in self.state["order"]:
            eid = str(e["id"])
            if eid == node_id or (node_id in ("EV", "EVQ") and eid.startswith(prefix)):
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
                    if self.A.get(f"{n['id']}#{it['k']}") is not None:
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
        total = answered = 0
        for n in self.N:
            if n["kind"] in ("alert", "fin"):
                continue
            total += 1
            if self.A.get(n["id"]) is not None:
                answered += 1
        return jsround(100 * answered / max(total, 1))

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
