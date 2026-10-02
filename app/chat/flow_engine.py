"""Motor reanudable del flujo de la minuta técnica (76 nodos).

La fuente de verdad es `flow/flujo_asistente_red.json` (ver FLUJO_NODOS.md del
cliente). Este módulo es el port de `motor_referencia.py`, pero en vez de
correr de punta a punta con un callback de respuestas, avanza UN paso por
llamada: el cliente manda el `state` (opaco) + la respuesta al nodo actual, y
recibe el `state` nuevo + el siguiente nodo a mostrar. No hay estado de
servidor — igual que el motor lineal anterior, el cliente es quien persiste.

Estado (JSON puro, sirve para viajar por HTTP y guardarse en la evaluación):
  answers   {clave con alcance: valor}      ej. "P22#L_CAJAS:1": "PC"
  loops     pila de loops activos
  calls     pila de subflujos activos
  printers  registro de impresoras (existentes y nuevas)
  actions   siguientes acciones generadas por los efectos
  alerts    alertas generadas por los efectos
  evidences evidencias subidas (código, alcance, lo que leyó la IA)
  areaLabels etiquetas de áreas personalizadas ("Otro: ...")
"""
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

FLOW_PATH = Path(__file__).parent / "flow" / "flujo_asistente_red.json"
SPECIAL = {"@loop.next", "@return", "END"}

BLOCK_LABELS = {
    "A": "Datos de la visita",
    "B": "Negocio",
    "C": "Internet",
    "D": "Cajas",
    "E": "Impresoras",
    "F": "Energía",
    "G": "Cableado",
    "H": "Red inalámbrica y dispositivos",
    "I": "Cierre",
}
BLOCK_ORDER = list(BLOCK_LABELS.keys())

_YES = {"si", "sí", "yes", "true", "1", "s"}
_NO = {"no", "false", "0", "n"}


class Flow:
    """Definición estática del flujo, cargada una sola vez."""

    def __init__(self, path: Path = FLOW_PATH):
        self.data = json.loads(path.read_text(encoding="utf-8"))
        self.nodes: Dict[str, dict] = {n["id"]: n for n in self.data["nodes"]}
        self.sub: Dict[str, Dict[str, dict]] = {
            name: {n["id"]: n for n in s["nodes"]} for name, s in self.data["subflows"].items()
        }
        self.area_label: Dict[str, str] = {a["value"]: a["label"] for a in self.data["areas"]}
        # Etiquetas de todas las opciones fijas (Cable de red, Raspberry, ...).
        for space in [self.nodes, *self.sub.values()]:
            for n in space.values():
                opts = n.get("options")
                if isinstance(opts, list):
                    for o in opts:
                        self.area_label.setdefault(o["value"], o["label"])
                elif isinstance(opts, dict):
                    for o in opts.get("plus", []):
                        self.area_label.setdefault(o["value"], o["label"])

    def find(self, nid: str, call_name: Optional[str]) -> dict:
        if call_name and nid in self.sub[call_name]:
            return self.sub[call_name][nid]
        return self.nodes[nid]


FLOW = Flow()


def _targets(next_: Any) -> List[str]:
    if isinstance(next_, str):
        return [next_]
    return [r["goto"] for r in next_["rules"]] + [next_["default"]]


def validate_flow(flow: Flow = FLOW) -> List[str]:
    """Validación estática: todos los goto existen y todo nodo es alcanzable."""
    errs: List[str] = []

    def check(space: Dict[str, dict], name: str) -> None:
        for nid, n in space.items():
            outs = [n["body"], n["exit"]] if n["kind"] == "loop" else _targets(n["next"])
            for t in outs:
                if t not in space and t not in SPECIAL:
                    errs.append(f"[{name}] {nid} → destino inexistente {t}")
            if n["kind"] == "subflow_call" and n["subflow"] not in flow.sub:
                errs.append(f"{nid}: subflujo {n['subflow']} no existe")
            if n.get("inputType") in ("CHOICE", "MULTI_SELECT") and "options" not in n:
                errs.append(f"{nid}: CHOICE/MULTI_SELECT sin opciones")

    check(flow.nodes, "main")
    for name, sp in flow.sub.items():
        check(sp, f"sub:{name}")

    def reach(space: Dict[str, dict], start: str) -> set:
        seen, stack = set(), [start]
        while stack:
            nid = stack.pop()
            if nid in seen or nid in SPECIAL:
                continue
            seen.add(nid)
            n = space[nid]
            stack += [n["body"], n["exit"]] if n["kind"] == "loop" else _targets(n["next"])
            if n["kind"] == "subflow_call":
                stack.append(n["next"])
        return seen

    unreachable = set(flow.nodes) - reach(flow.nodes, flow.data["start"])
    if unreachable:
        errs.append(f"Nodos inalcanzables: {sorted(unreachable)}")
    for name, sp in flow.sub.items():
        un = set(sp) - reach(sp, flow.data["subflows"][name]["start"])
        if un:
            errs.append(f"[sub:{name}] nodos inalcanzables: {sorted(un)}")
    return errs


def new_state(context: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Estado inicial. `context` trae prefills: today, technician."""
    s: Dict[str, Any] = {
        "current": FLOW.data["start"],
        "answers": {},
        "loops": [],
        "calls": [],
        "printers": [],
        "actions": [],
        "alerts": [],
        "evidences": [],
        "areaLabels": {},
        "block": "A",
        "done": False,
        "context": context or {},
    }
    Session(s).settle()
    return s


class StepError(Exception):
    """Respuesta inválida para el nodo actual (se le muestra al técnico)."""


class Session:
    """Opera sobre un `state` (se muta in-place)."""

    def __init__(self, state: Dict[str, Any]):
        self.s = state

    # ---- alcance y lectura de respuestas ---------------------------------
    def scope(self) -> str:
        parts = [f"{l['id']}:{l['idx'] + 1}" for l in self.s["loops"]]
        if self.s["calls"]:
            parts.append("U:" + self.s["calls"][-1]["ctx"]["key"])
        return "/".join(parts)

    def key(self, nid: str) -> str:
        sc = self.scope()
        return f"{nid}#{sc}" if sc else nid

    def get(self, ref: str) -> Any:
        """$P22 → respuesta en el alcance más cercano; $ctx.x; $derived.x; $registry.x"""
        name = ref[1:]
        if name.startswith("ctx."):
            return self.s["calls"][-1]["ctx"].get(name[4:])
        if name.startswith("derived."):
            return getattr(self, "derived_" + name[8:])()
        if name.startswith("registry."):
            return {"printers": [p["id"] for p in self.s["printers"]]}[name[9:]]
        sc = self.scope().split("/") if self.scope() else []
        for i in range(len(sc), -1, -1):
            k = f"{name}#{'/'.join(sc[:i])}" if i else name
            if k in self.s["answers"]:
                return self.s["answers"][k]
        return None

    def derived_areasSinImpresora(self) -> List[str]:
        need = self.get("$P25") or []
        used = {a for p in self.s["printers"] for a in p["areas"]}
        return [a for a in need if a not in used]

    # ---- etiquetas ----------------------------------------------------
    def label_of(self, value: Any) -> str:
        v = str(value)
        for p in self.s["printers"]:
            if p["id"] == v:
                return p["label"]
        if v in self.s["areaLabels"]:
            return self.s["areaLabels"][v]
        return FLOW.area_label.get(v, v)

    # ---- condiciones y ruteo ------------------------------------------
    def val(self, x: Any) -> Any:
        return self.get(x) if isinstance(x, str) and x.startswith("$") else x

    def cond(self, c: dict) -> bool:
        op, arg = next(iter(c.items()))
        if op == "and":
            return all(self.cond(x) for x in arg)
        if op == "or":
            return any(self.cond(x) for x in arg)
        if op == "notEmpty":
            return bool(self.val(arg))
        a, b = self.val(arg[0]), self.val(arg[1])
        if op == "eq":
            return a == b
        if op == "ne":
            return a != b
        if op == "gt":
            return (a or 0) > b
        if op == "lt":
            return (a or 0) < b
        if op == "in":
            return a in (b or [])
        if op == "includes":
            return b in (a or [])
        raise ValueError(f"Operador desconocido: {op}")

    def route(self, next_: Any) -> str:
        if isinstance(next_, str):
            return next_
        for r in next_["rules"]:
            if self.cond(r["if"]):
                return r["goto"]
        return next_["default"]

    # ---- plantillas y opciones ----------------------------------------
    def cur_item(self) -> Any:
        l = self.s["loops"][-1]
        return l["items"][l["idx"]]

    def render(self, text: str, answer: Any = None) -> str:
        def rep(m: "re.Match[str]") -> str:
            k = m.group(1)
            if k == "i":
                return str(self.s["loops"][-1]["idx"] + 1)
            if k == "item.label":
                return self.label_of(self.cur_item())
            if k == "item.value":
                return str(self.cur_item())
            if k == "answer":
                return str(answer)
            if k == "answer.label":
                return self.label_of(answer)
            if k.startswith("ctx."):
                v = self.s["calls"][-1]["ctx"].get(k[4:].replace(".label", ""), "")
                return self.label_of(v) if k.endswith(".label") else str(v)
            if k.startswith("derived."):
                v = self.get("$" + k.rsplit(".", 1)[0]) or []
                return ", ".join(self.label_of(x) for x in v)
            if k.endswith(".label") or k.endswith(".labels"):
                v = self.get("$" + k.split(".")[0])
                v = v if isinstance(v, list) else [v]
                return " + ".join(self.label_of(x) for x in v)
            return m.group(0)

        return re.sub(r"\{([^{}]+)\}", rep, text)

    def options(self, n: dict) -> List[Tuple[str, str]]:
        o = n.get("options")
        if o is None:
            return []
        if isinstance(o, list):
            return [(x["value"], x["label"]) for x in o]
        if "from" in o:
            ref = o["from"]
            if ref == "$registry.printers":
                base = [(p["id"], p["label"]) for p in self.s["printers"]]
            else:
                values = self.val(ref) or []
                if ref == "$derived.areasSinImpresora" and not values:
                    # Más impresoras que áreas pendientes: ofrecer todas las
                    # áreas que imprimen para no dejar al técnico sin opciones.
                    values = self.get("$P25") or []
                base = [(v, self.label_of(v)) for v in values]
            return base + [(x["value"], x["label"]) for x in o.get("plus", [])]
        if "range" in o:
            r = o["range"]
            top = int(self.val(r["to"]) or 1)
            return [(str(i), r["label"].replace("{n}", str(i))) for i in range(int(r["from"]), top + 1)]
        return []

    # ---- efectos ------------------------------------------------------
    def _printer_label(self, p: dict) -> str:
        return f"{p['id']} – " + " + ".join(self.label_of(a) for a in p["areas"])

    def effects(self, n: dict, answer: Any) -> None:
        for e in n.get("effects", []):
            if "if" in e and not self.cond(e["if"]):
                continue
            if "addAction" in e:
                a = self.render(e["addAction"], answer)
                if a not in self.s["actions"]:
                    self.s["actions"].append(a)
            if "addAlert" in e:
                self.s["alerts"].append(self.render(e["addAlert"], answer))
            if "registerPrinter" in e:
                r = e["registerPrinter"]
                areas = self.val(r["areas"]) if isinstance(r["areas"], str) else [self.render(x) for x in r["areas"]]
                pid = f"IMP{len(self.s['printers']) + 1}"
                printer = {
                    "id": pid, "areas": list(areas), "existing": r["existing"],
                    "scope": self.scope().split("/")[0] if self.scope() else "",
                }
                printer["label"] = self._printer_label(printer)
                self.s["printers"].append(printer)
            if "addAreaToPrinter" in e:
                target = self.val(e["addAreaToPrinter"]["printer"])
                p = next(p for p in self.s["printers"] if p["id"] == target)
                p["areas"].append(self.render(e["addAreaToPrinter"]["area"]))
                p["label"] = self._printer_label(p)

    # ---- avance por nodos no interactivos --------------------------------
    def node(self, nid: str) -> dict:
        calls = self.s["calls"]
        return FLOW.find(nid, calls[-1]["name"] if calls else None)

    def settle(self, max_steps: int = 500) -> None:
        """Avanza desde `current` hasta el próximo nodo interactivo (pregunta,
        evidencia, aviso o resumen) o hasta el final del flujo."""
        s = self.s
        nid = s["current"]
        for _ in range(max_steps):
            if nid == "END":
                s["current"], s["done"] = "END", True
                return
            if nid == "@loop.next":
                l = s["loops"][-1]
                l["idx"] += 1
                if l["idx"] < len(l["items"]):
                    nid = l["body"]
                else:
                    s["loops"].pop()
                    nid = l["exit"]
                continue
            if nid == "@return":
                c = s["calls"].pop()
                nid = c["next"]
                continue
            n = self.node(nid)
            k = n["kind"]
            if k == "router":
                nid = self.route(n["next"])
                continue
            if k == "loop":
                ov = n["over"]
                if "count" in ov:
                    items = list(range(1, int(self.val(ov["count"]) or 0) + 1))
                else:
                    items = list(self.val(ov["list"]) or [])
                if not items:
                    nid = n["exit"]
                    continue
                s["loops"].append({"id": nid, "items": items, "idx": 0, "body": n["body"], "exit": n["exit"]})
                nid = n["body"]
                continue
            if k == "subflow_call":
                ctx: Dict[str, Any] = {}
                for p, v in n["params"].items():
                    if isinstance(v, dict):
                        ctx[p] = self.cond(v)
                    elif isinstance(v, str) and v.startswith("$"):
                        ctx[p] = self.val(v)
                    elif isinstance(v, str):
                        ctx[p] = self.render(v)
                    else:
                        ctx[p] = v
                ctx.setdefault("skipNearQuestion", False)
                ctx["key"] = f"{ctx['area']}|{ctx['equipo']}"
                s["calls"].append({"name": n["subflow"], "ctx": ctx, "next": n["next"]})
                nid = FLOW.data["subflows"][n["subflow"]]["start"]
                continue
            # question / evidence / alert / summary: hay que mostrarlo
            s["current"] = nid
            if n.get("block") and n["block"] != "U":
                s["block"] = n["block"]
            return
        raise RuntimeError("Demasiados pasos: posible ciclo en el flujo")

    # ---- prompt del nodo actual -------------------------------------------
    def prompt(self) -> Dict[str, Any]:
        s = self.s
        if s["done"]:
            return {}
        n = self.node(s["current"])
        kind = n["kind"]
        itype = n.get("inputType") or ("ALERT" if kind == "alert" else "SUMMARY")
        options = self.options(n) if itype in ("CHOICE", "MULTI_SELECT") else []
        block = s["block"]
        p: Dict[str, Any] = {
            "nodeId": s["current"],
            "scope": self.scope(),
            "kind": kind,
            "inputType": itype,
            "text": self.render(n.get("text", "")),
            "options": [{"value": v, "label": l} for v, l in options],
            "required": bool(n.get("required", True)),
            "validation": n.get("validation") or {},
            "block": block,
            "blockLabel": BLOCK_LABELS.get(block, block),
            "blockIndex": BLOCK_ORDER.index(block) + 1 if block in BLOCK_ORDER else 0,
            "blockCount": len(BLOCK_ORDER),
            "defaultValue": self._default(n, options),
        }
        if kind == "evidence":
            p.update({
                "evidenceCode": n["evidenceCode"],
                "maxFiles": n.get("maxFiles", 3),
                "accept": n.get("accept", []),
                "aiExtract": n.get("aiExtract", []),
            })
        if kind == "alert":
            p["severity"] = n.get("severity", "warning")
        if s["calls"]:
            ctx = s["calls"][-1]["ctx"]
            p["ctx"] = {"area": ctx.get("area"), "equipo": ctx.get("equipo")}
        return p

    def _default(self, n: dict, options: List[Tuple[str, str]]) -> Optional[str]:
        ctx = self.s.get("context", {})
        if n["id"] == "P06":
            return ctx.get("today")
        if n["id"] == "P07":
            return ctx.get("technician")
        if n["id"] == "P32b" and self.s["loops"]:
            item = str(self.cur_item())
            return item if any(v == item for v, _ in options) else None
        return None

    # ---- parseo y validación de la respuesta -----------------------------
    def parse(self, n: dict, raw: str) -> Any:
        raw = (raw or "").strip()
        itype = n["inputType"]
        required = bool(n.get("required", True))
        v = n.get("validation") or {}

        if not raw:
            if required:
                raise StepError("Esta respuesta es obligatoria.")
            return "" if itype != "MULTI_SELECT" else []

        if itype == "TEXT":
            if "minLength" in v and len(raw) < v["minLength"]:
                raise StepError(f"Escribe al menos {v['minLength']} caracteres.")
            if "regex" in v and not re.match(v["regex"], raw):
                raise StepError("El formato no es válido.")
            return raw

        if itype == "NUMBER":
            m = re.search(r"-?\d+(?:[.,]\d+)?", raw)
            if not m:
                raise StepError("Ingresa un número.")
            num = float(m.group(0).replace(",", "."))
            num = int(num) if num == int(num) else num
            if "min" in v and num < v["min"]:
                raise StepError(f"El valor mínimo es {v['min']}.")
            if "max" in v and num > v["max"]:
                raise StepError(f"El valor máximo es {v['max']}.")
            return num

        if itype == "YES_NO":
            low = raw.lower()
            if low in _YES:
                return "SI"
            if low in _NO:
                return "NO"
            raise StepError("Responde Sí o No.")

        options = self.options(n)
        by_value = {val: val for val, _ in options}
        by_label = {lab.lower(): val for val, lab in options}

        def match(token: str) -> Optional[str]:
            t = token.strip()
            if t in by_value:
                return t
            return by_label.get(t.lower()) or next((val for val in by_value if val.lower() == t.lower()), None)

        if itype == "CHOICE":
            hit = match(raw)
            if hit is None:
                raise StepError("Elige una de las opciones.")
            return hit

        if itype == "MULTI_SELECT":
            result: List[str] = []
            for token in [t for t in raw.split(",") if t.strip()]:
                token = token.strip()
                if token.upper().startswith("OTRO:") and "OTRO" in by_value:
                    name = token.split(":", 1)[1].strip()
                    if not name:
                        continue
                    result.append(self._register_custom_area(name))
                    continue
                hit = match(token)
                if hit is None:
                    raise StepError("Una de las opciones elegidas no es válida.")
                if hit not in result:
                    result.append(hit)
            if "minSelected" in v and len(result) < v["minSelected"]:
                raise StepError(f"Elige al menos {v['minSelected']}.")
            return result

        raise StepError("Tipo de respuesta no soportado.")

    def _register_custom_area(self, name: str) -> str:
        slug = "X_" + re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
        self.s["areaLabels"][slug] = name
        return slug

    # ---- avance ------------------------------------------------------------
    def advance(self, raw: str, evidence: Optional[Dict[str, Any]] = None) -> Any:
        """Aplica la respuesta al nodo actual y avanza. Devuelve el valor
        guardado (o None). Lanza StepError si la respuesta no es válida."""
        s = self.s
        if s["done"]:
            return None
        n = self.node(s["current"])
        kind = n["kind"]

        if kind == "alert":
            self.effects(n, None)
            s["current"] = self.route(n["next"])
            self.settle()
            return None

        if kind == "summary":
            s["summaryAction"] = (raw or "GENERAR_MINUTA").strip()
            s["current"], s["done"] = "END", True
            return None

        if kind == "evidence":
            count = int((evidence or {}).get("count", 0))
            if count == 0:
                # "Omitir por ahora": se anota como pendiente y la minuta lo
                # lista entre los datos que faltan; solo opcional si el nodo lo es.
                if not (raw or "").strip().upper() == "OMITIR" and n.get("required", True):
                    raise StepError("Sube al menos una foto.")
                value: Any = "OMITIDO"
                s.setdefault("skipped", []).append({
                    "code": n["evidenceCode"], "nodeId": n["id"], "scope": self.scope(),
                    "area": self._ctx_value("area"), "equipo": self._ctx_value("equipo"),
                    "text": self.render(n["text"]),
                })
            else:
                value = f"{count} foto(s)"
                s["evidences"].append({
                    "code": n["evidenceCode"],
                    "nodeId": n["id"],
                    "scope": self.scope(),
                    "area": self._ctx_value("area"),
                    "equipo": self._ctx_value("equipo"),
                    "count": count,
                    "extracted": (evidence or {}).get("extracted") or {},
                })
        else:
            value = self.parse(n, raw)

        s["answers"][self.key(n["id"])] = value
        self.effects(n, value)
        s["current"] = self.route(n["next"])
        self.settle()
        return value

    def _ctx_value(self, name: str) -> Optional[str]:
        if not self.s["calls"]:
            return None
        v = self.s["calls"][-1]["ctx"].get(name)
        return self.label_of(v) if name == "area" and v is not None else v


def clone_state(state: Dict[str, Any]) -> Dict[str, Any]:
    return deepcopy(state)
