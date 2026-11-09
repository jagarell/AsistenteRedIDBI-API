"""Las notas y fotos colocadas en el mapa (app o web) salen en el mapa impreso de la minuta."""
import io

from PIL import Image

from app.chat.sim.map_print import render_print_png

NODOS = [
    {"id": "i", "label": "Internet", "type": "internet", "x": 0.5, "y": 0.08},
    {"id": "r", "label": "Router", "type": "router", "x": 0.5, "y": 0.4, "ip": "192.168.1.1"},
]
ENLACES = [{"id": "l1", "source": "i", "target": "r", "style": "main", "observed": False}]


def _doc(**extra):
    d = {"nodes": NODOS, "links": ENLACES, "texts": [], "images": []}
    d.update(extra)
    return d


def _foto(color):
    b = io.BytesIO()
    Image.new("RGB", (200, 150), color).save(b, format="JPEG")
    return b.getvalue()


def _png(doc, imgs=None):
    return Image.open(io.BytesIO(render_print_png({"nodes": [], "links": []}, doc, imgs or {}))).convert("RGB")


def _cuenta(img, rgb, tol=12):
    px = img.load()
    n = 0
    for y in range(0, img.height, 3):
        for x in range(0, img.width, 3):
            r, g, b = px[x, y]
            if abs(r - rgb[0]) <= tol and abs(g - rgb[1]) <= tol and abs(b - rgb[2]) <= tol:
                n += 1
    return n


def test_la_foto_colocada_aparece_en_el_mapa_impreso():
    sin = _png(_doc())
    con = _png(_doc(images=[{"id": "im", "evidenceCode": "E1", "scope": "", "label": "Router", "x": 0.85, "y": 0.2, "size": "L"}]),
               {"im": _foto((255, 105, 180))})
    assert _cuenta(sin, (255, 105, 180)) == 0
    assert _cuenta(con, (255, 105, 180)) > 500


def test_la_nota_colocada_aparece_y_una_foto_ilegible_se_omite():
    sin = _png(_doc())
    con = _png(_doc(texts=[{"id": "t", "text": "Caja principal", "x": 0.2, "y": 0.5, "size": "L", "color": "#FFF4CC"}],
                    images=[{"id": "x", "evidenceCode": "E9", "scope": "", "label": "", "x": 0.8, "y": 0.5, "size": "M"}]),
               {"x": b"no es una imagen"})
    assert _cuenta(sin, (255, 244, 204)) == 0
    assert _cuenta(con, (255, 244, 204)) > 300


def test_sin_notas_ni_fotos_el_mapa_no_cambia():
    a = render_print_png({"nodes": [], "links": []}, _doc(), {})
    b = render_print_png({"nodes": [], "links": []}, _doc(texts=[], images=[]), {})
    assert a == b
