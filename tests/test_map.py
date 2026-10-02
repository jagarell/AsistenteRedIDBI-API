import base64
import io

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.chat.map_model import MapDocument, MapImage, MapLink, MapNode, MapText
from app.chat.map_render import render_map_png

client = TestClient(app)


def sample() -> MapDocument:
    return MapDocument(
        nodes=[MapNode(id="i", label="Internet · Claro", type="internet", x=0.5, y=0.1),
               MapNode(id="r", label="Router Huawei", type="router", x=0.5, y=0.4, detail="192.168.100.1"),
               MapNode(id="pc", label="PC Caja", type="computer", x=0.2, y=0.8),
               MapNode(id="t", label="Tablet rush", type="pos", x=0.8, y=0.8, pending=True)],
        links=[MapLink(id="l1", source="i", target="r"),
               MapLink(id="l2", source="r", target="pc", style="dashed", observed=True),
               MapLink(id="l3", source="r", target="t", style="dashed")],
        texts=[MapText(id="x", text="Pasar PC de caja a cable Cat6", x=0.25, y=0.55)],
        images=[MapImage(id="im", evidenceCode="E2", label="Router en caja", x=0.85, y=0.15)],
    )


def test_render_with_text_and_image(tmp_path):
    photo = io.BytesIO()
    Image.new("RGB", (200, 120), (200, 80, 80)).save(photo, format="JPEG")
    png = render_map_png(sample(), {"im": photo.getvalue()})
    assert png[:4] == b"\x89PNG"
    (tmp_path / "map.png").write_bytes(png)
    import os, shutil
    if os.environ.get("KEEP_ARTIFACTS"):
        shutil.copy(tmp_path / "map.png", "/tmp/map_editor.png")


def test_command_endpoint():
    doc = sample().model_dump()
    r = client.post("/chat/map/command", json={"map": doc, "command": "agrega red de invitados"}).json()
    assert any(n["label"] == "Red de invitados" for n in r["map"]["nodes"])
    r = client.post("/chat/map/command", json={"map": r["map"], "command": "PC de caja por cable"}).json()
    link = next(l for l in r["map"]["links"] if l["target"] == "pc")
    assert link["style"] == "solid" and not link["observed"]
    r = client.post("/chat/map/command", json={"map": r["map"], "command": "no sé qué hacer"}).json()
    assert "No entendí" in r["reply"]


def test_cable_command_targets_the_pc_not_the_printer():
    from app.chat.map_model import apply_command
    doc = sample()
    doc.nodes.append(MapNode(id="pr", label="Impresora Caja", type="printer", x=0.2, y=0.95))
    doc.links.append(MapLink(id="l4", source="pc", target="pr", style="dotted"))
    doc, reply = apply_command(doc, "PC de caja por cable")
    assert "PC Caja" in reply
    assert next(l for l in doc.links if l.target == "pc").style == "solid"
    assert next(l for l in doc.links if l.target == "pr").style == "dotted"
