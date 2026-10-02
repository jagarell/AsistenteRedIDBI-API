"""Mapa de red editable (el que se dibuja y edita en la app).

Es el documento que viaja entre la app, el gateway y el generador de la
minuta: nodos y enlaces con posición normalizada (0..1), cajas de texto y
fotos de evidencia. Se genera automáticamente a partir de la topología del
chat ("Generar mapa con IA") y el técnico lo ajusta a mano.
"""
import re
import uuid
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.chat.schemas import ConnectionType, LinkStatus, Topology

NODE_TYPES = ("internet", "router", "switch", "access_point", "repeater", "computer",
              "printer", "camera", "pos", "other")


def _id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


class MapNode(BaseModel):
    id: str
    label: str
    type: str = "other"
    x: float = 0.5
    y: float = 0.5
    pending: bool = False
    detail: Optional[str] = None
    color: Optional[str] = None


class MapLink(BaseModel):
    id: str
    source: str
    target: str
    style: str = "solid"          # solid (cable) | dashed (WiFi) | dotted (USB)
    observed: bool = False        # se dibuja en rojo ("debería ir por cable")


class MapText(BaseModel):
    id: str
    text: str
    x: float = 0.5
    y: float = 0.5
    size: str = "M"               # S | M | L
    color: str = "#FFF4CC"


class MapImage(BaseModel):
    id: str
    evidenceCode: str
    scope: str = ""
    label: str = ""
    x: float = 0.8
    y: float = 0.2
    size: str = "M"               # S | M | L


class MapDocument(BaseModel):
    nodes: List[MapNode] = Field(default_factory=list)
    links: List[MapLink] = Field(default_factory=list)
    texts: List[MapText] = Field(default_factory=list)
    images: List[MapImage] = Field(default_factory=list)


_STYLE = {
    ConnectionType.CABLE_RED: "solid",
    ConnectionType.WIFI: "dashed",
    ConnectionType.USB_BLUETOOTH: "dotted",
}


def _node_type(topology_type: str, label: str) -> str:
    if topology_type == "access_point" and "repetidor" in label.lower():
        return "repeater"
    return {"detected": "other"}.get(topology_type, topology_type if topology_type in NODE_TYPES else "other")


def from_topology(topology: Topology) -> MapDocument:
    """Mapa automático: árbol Internet → router → equipos, con posiciones calculadas."""
    children: Dict[str, List[str]] = {n.id: [] for n in topology.nodes}
    parent: Dict[str, str] = {}
    for l in topology.links:
        if l.target not in parent and l.source in children and l.target in children:
            parent[l.target] = l.source
            children[l.source].append(l.target)

    x_next = [0.0]
    pos: Dict[str, Tuple[float, int]] = {}

    def place(node_id: str, depth: int) -> float:
        kids = children[node_id]
        if not kids:
            x = x_next[0]
            x_next[0] += 1
        else:
            xs = [place(k, depth + 1) for k in kids]
            x = sum(xs) / len(xs)
        pos[node_id] = (x, depth)
        return x

    for root in [n.id for n in topology.nodes if n.id not in parent]:
        place(root, 0)
    max_depth = max((d for _, d in pos.values()), default=0) or 1
    cols = max(1.0, x_next[0] - 1)

    nodes = [
        MapNode(
            id=n.id, label=n.label, type=_node_type(n.type, n.label),
            x=round(0.5 if cols == 1 and x_next[0] <= 1 else pos[n.id][0] / cols, 4),
            y=round(0.1 + pos[n.id][1] / max_depth * 0.8, 4),
            pending=n.pending, detail=n.detail,
        )
        for n in topology.nodes if n.id in pos
    ]
    links = [
        MapLink(id=f"l{i}", source=l.source, target=l.target, style=_STYLE.get(l.connectionType, "solid"),
                observed=l.status == LinkStatus.CON_FALLA)
        for i, l in enumerate(topology.links)
    ]
    return MapDocument(nodes=nodes, links=links)


# ---- comandos en lenguaje natural ("Pide un cambio al mapa…") ----------------
_TYPE_WORDS = [
    ("repetidor", "repeater", "Repetidor"), ("access point", "access_point", "Access point"),
    ("impresora", "printer", "Impresora"), ("cámara", "camera", "Cámara"), ("camara", "camera", "Cámara"),
    ("switch", "switch", "Switch"), ("router", "router", "Router"), ("tablet", "pos", "Tablets"),
    ("pos", "pos", "POS"), ("laptop", "computer", "Laptop"), ("computadora", "computer", "Computadora"),
    ("pc", "computer", "PC"),
]


def _type_hint(text: str) -> Optional[str]:
    """Tipo de equipo al que se refiere la frase ("PC de caja" -> computer)."""
    for word, ntype, _ in _TYPE_WORDS:
        if re.search(rf"\b{re.escape(word)}s?\b", text):
            return ntype
    return None


def _find(doc: MapDocument, text: str) -> Optional[MapNode]:
    """Equipo mencionado en la frase: primero por tipo (PC, impresora...), luego por palabras del nombre."""
    text = text.lower()
    hint = _type_hint(text)
    pool = [n for n in doc.nodes if hint is None or n.type == hint] or doc.nodes
    best, best_score = None, 0
    for n in pool:
        words = [w for w in re.split(r"\W+", n.label.lower()) if len(w) > 2]
        score = sum(1 for w in words if w in text) + (2 if n.label.lower() in text else 0)
        if score > best_score:
            best, best_score = n, score
    if best is None and hint is not None and pool:
        return pool[0]
    return best


def _router(doc: MapDocument) -> Optional[MapNode]:
    return next((n for n in doc.nodes if n.type == "router"), None)


def _free_spot(doc: MapDocument, near: MapNode) -> Tuple[float, float]:
    x, y = min(0.92, near.x + 0.22), min(0.9, near.y + 0.2)
    while any(abs(n.x - x) < 0.14 and abs(n.y - y) < 0.1 for n in doc.nodes):
        x = x - 0.16 if x > 0.5 else x + 0.16
        x = max(0.08, min(0.92, x))
        y = min(0.92, y + 0.08)
    return round(x, 3), round(y, 3)


def apply_command(doc: MapDocument, command: str) -> Tuple[MapDocument, str]:
    """Cambios simples sobre el mapa a partir de una frase. Devuelve (mapa, respuesta)."""
    low = command.lower().strip()
    router = _router(doc)

    # "PC de caja por cable": el enlace de esa PC al router pasa a cable y deja de estar observado
    if "cable" in low and router is not None:
        target = _find(doc, low.replace("cable", "")) or next(
            (n for n in doc.nodes if n.type == "computer" and "caja" in n.label.lower()), None)
        if target is not None:
            for l in doc.links:
                if {l.source, l.target} == {router.id, target.id}:
                    l.style, l.observed = "solid", False
                    return doc, f"Listo: {target.label} ahora va por cable al router."
            doc.links.append(MapLink(id=_id("l"), source=router.id, target=target.id))
            return doc, f"Listo: conecté {target.label} al router por cable."

    if any(w in low for w in ("elimina", "quita", "borra")):
        target = _find(doc, low)
        if target is not None and target.type not in ("internet",):
            doc.nodes = [n for n in doc.nodes if n.id != target.id]
            doc.links = [l for l in doc.links if target.id not in (l.source, l.target)]
            return doc, f"Listo: quité {target.label} del mapa."

    if "invitados" in low and router is not None:
        x, y = _free_spot(doc, router)
        node = MapNode(id=_id("n"), label="Red de invitados", type="access_point", x=x, y=y)
        doc.nodes.append(node)
        doc.links.append(MapLink(id=_id("l"), source=router.id, target=node.id, style="dashed"))
        return doc, "Listo: agregué una red de invitados separada, conectada por WiFi al router."

    if any(w in low for w in ("agrega", "agregar", "añade", "añadir", "pon ", "suma")):
        for word, ntype, label in _TYPE_WORDS:
            if re.search(rf"\b{re.escape(word)}s?\b", low):
                anchor = next((n for n in doc.nodes if n.type in ("access_point", "repeater")), router)
                if anchor is None:
                    break
                x, y = _free_spot(doc, anchor)
                node = MapNode(id=_id("n"), label=label, type=ntype, x=x, y=y)
                doc.nodes.append(node)
                style = "solid" if ntype in ("switch", "printer", "pos") and "tablet" not in low else "dashed"
                doc.links.append(MapLink(id=_id("l"), source=anchor.id, target=node.id, style=style))
                return doc, f"Listo: agregué {label} al mapa."

    return doc, ("No entendí el cambio. Prueba con: \"PC de caja por cable\", \"agrega red de invitados\", "
                 "\"agrega tablets\" o \"quita Repetidor .50\".")
