from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_catalogo_lista_las_preguntas_por_seccion_en_orden():
    r = client.get("/chat/flujo/catalogo")
    assert r.status_code == 200
    data = r.json()
    ids = [s["id"] for s in data["secciones"]]
    assert ids[0] == "A" and ids == sorted(ids)
    a = data["secciones"][0]["preguntas"]
    assert [p["id"] for p in a[:3]] == ["P01", "P01b", "P01c"]
    assert [p["orden"] for p in a] == list(range(1, len(a) + 1))
    assert data["total"] == sum(len(s["preguntas"]) for s in data["secciones"]) > 40


def test_catalogo_sin_repetidos_por_caja_o_impresora():
    todas = [p["id"] for s in client.get("/chat/flujo/catalogo").json()["secciones"] for p in s["preguntas"]]
    assert len(todas) == len(set(todas))
    assert not any("#" in i for i in todas)
