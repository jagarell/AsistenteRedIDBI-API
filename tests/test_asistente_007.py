"""Asistente IA 0.0.7: plan de cambios, minuta de soporte, aprendizaje del día y fichas; minuta con contraseñas."""
import base64

from fastapi.testclient import TestClient

from app.asistente import soporte
from app.asistente.texto import credencial, puertos_switch, ubicacion_router
from app.main import app

c = TestClient(app)
HECHOS = ["IMP. Caja con IP fija 192.168.1.23 por red, respaldo por USB. Se dejó un solo sistema de impresiones activo.",
          "IMP. Piscina con IP fija 192.168.1.149 por cable; IMP. Piscina Wifi con IP fija 192.168.1.45 como respaldo; portal web de la IMP. Piscina: usuario admin contraseña 123.",
          "Se validó el controlador y la prueba de impresión salió en caja, cocina y piscina. La cocina tiene su impresora asignada."]
PUNTOS = ["Habilitar la impresora de caja en red con respaldo USB", "Cambiar la IP de la impresora de piscina y dejar su respaldo por WiFi",
          "Validar el controlador y la prueba de impresión"]


def test_credenciales_y_textos():
    assert credencial("la contraseña del wifi MOVISTAR_F653 es vyp2k5XYJXfMQabBY79a") == {"eq": "Red WiFi", "usr": "MOVISTAR_F653", "pw": "vyp2k5XYJXfMQabBY79a"}
    assert credencial("portal web de la IMP. Caja: usuario admin contraseña 123") == {"eq": "IMP. Caja · portal web", "usr": "admin", "pw": "123"}
    assert credencial("la clave del repetidor es piscina2026")["eq"] == "Repetidor WiFi"
    assert credencial("el router está en el almacén") is None
    sp = puertos_switch("la IMP. Barra 1 va al puerto 3 del switch de 8 puertos", [{"name": "Barra 1", "con": "RED"}])
    assert sp == {"ports": [{"name": "Barra 1", "port": 3}], "n": 8}
    u = ubicacion_router("el router está a ras del suelo dentro de un mueble de melamina")
    assert u["enc"] == "MUEBLE" and "casi al ras del suelo" in u["detalle"]


def test_plan_de_cambios_y_criterio():
    r = c.post("/minutas/cambios/plan", json={"texto": "La contraseña del WiFi MOVISTAR_F653 es abc123. El cliente debe reservar las IP."}).json()
    assert [i["k"] for i in r["items"]] == ["cred", "pasoC"]
    r = c.post("/minutas/cambios/plan", json={"texto": "de ahora en adelante todas las minutas deben ser más breves"}).json()
    assert r["criterio"] is True and r["items"] == []


def test_soporte_reglas_y_minuta():
    ev = c.post("/asistente/soporte/evaluar", json={"motivo": "La impresora de la piscina dejó de imprimir.", "hechos": HECHOS,
                                                   "evidencias": ["selftest_imp_piscina_wifi.jpg"]}).json()
    assert ev["reglas"] == {"S1": "ok", "S2": "ok", "S3": "ok", "S4": "ok"} and ev["estadoSugerido"] == "OP"
    assert ev["evidencias"][0]["lectura"].startswith("IMP. Piscina Wifi · IP 192.168.1.45")
    doc = c.post("/asistente/soporte/minuta", json={"cliente": "Muna Cocina Palestina", "local": "Muna Cocina Palestina", "fecha": "05/11/2026",
                                                   "tecnico": "Técnico de prueba", "motivo": "Incidencia.", "puntos": PUNTOS, "hechos": HECHOS,
                                                   "reglas": {"S3": "bad"}, "pasos": [{"p": "Cliente", "t": "Avisar si falla el 12/11/2026"}]}).json()
    assert doc["estado"] == "Observado" and doc["reglas"]["S3"] == "bad"
    txt = str(doc["blocks"])
    assert "Accesos y contraseñas" in txt and "'123'" in txt                    # la contraseña va en su tabla
    assert "contraseña 123" not in txt                                         # y no se repite en el desarrollo
    assert "Por parte del cliente:" in txt and "12/11/2026" not in txt         # pasos sin fechas
    assert "Cliente" not in [r.get("label") for b in doc["blocks"] if b["t"] == "kv" for r in b["rows"]]  # sin redundancia
    r = c.post("/asistente/soporte/minuta", json={"puntos": PUNTOS, "hechos": HECHOS[:1]})
    assert r.status_code == 422


def test_aprendizaje_fichas_y_permisos():
    v = [{"id": "s1", "tipo": "soporte", "local": "Muna", "tecnico": "Técnico de prueba",
          "texto": "La impresora de la piscina dejó de imprimir: al reiniciar el router cambió su IP (DHCP). Zona de piscina solo en verano."}]
    assert c.post("/aprendizaje/hoy", json={"rol": "tec", "visitas": v}).status_code == 403
    r = c.post("/aprendizaje/hoy", json={"rol": "adm", "visitas": v}).json()
    assert [x["clave"] for x in r["casos"]] == ["ip_fija", "zona_temporada"] and r["visitas"]["soporte"] == 1
    ap = c.post("/aprendizaje/aplicar", json={"casos": r["casos"]}).json()
    assert [x["id"] for x in ap["reglas"]] == ["R_IP_FIJA", "R_ZONA_TEMP"] and [x["id"] for x in ap["preguntas"]] == ["P28f", "P11t"]
    fx = c.post("/conocimiento/fichas", json={"casos": r["casos"], "admin": "Administrador de prueba"}).json()
    pdf = base64.b64decode(fx["pdfBase64"])
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF") and pdf.count(b"/Type /Page ") == 2
    assert fx["fichas"][0]["codigo"].startswith("FA-")


def test_mensaje_intenciones():
    assert c.post("/asistente/mensaje", json={"rol": "adm", "texto": "¿Qué aprendiste hoy?"}).json()["tipo"] == "aprendizaje"
    assert "administrador" in c.post("/asistente/mensaje", json={"rol": "tec", "texto": "qué aprendiste hoy"}).json()["texto"]
    assert c.post("/asistente/mensaje", json={"texto": "Redacta una minuta nueva"}).json()["tipo"] == "tipo_minuta"
    assert c.post("/asistente/mensaje", json={"texto": "redacta una minuta de soporte"}).json()["tipo"] == "soporte"


def test_estado_sugerido():
    assert soporte.estado_sugerido({"S1": "ok"}, ["queda pendiente la reserva"]) == "OPP"
    assert soporte.estado_sugerido({"S1": "bad"}, []) == "OBS"


def test_minuta_implementacion_007():
    import json
    from pathlib import Path

    from app.chat.sim.minuta import build_document
    G = json.loads((Path(__file__).parent / "golden" / "sim_golden.json").read_text(encoding="utf-8"))
    case = next(g for g in G if g["A"].get("RCARD"))
    d = build_document(case["A"], {"technician": "Técnico de prueba", "empresa": "IDBI"},
                       {"cred": [{"eq": "IMP. Caja · portal web", "usr": "admin", "pw": "123"}]})
    txt = str(d["blocks"])
    assert "Accesos y contraseñas" in txt and "MOVISTAR_7A21" in txt and "'123'" in txt
    assert "Por parte del cliente:" in txt and "Por parte del equipo técnico de IDBI:" in txt


def test_soporte_reglas_sin_impresora_nombrada():
    """S2/S3 se deciden por el texto aunque no diga «IMP. X» (antes salían «No aplica»)."""
    r = soporte.reglas_sugeridas("Cambio de router", ["Se dejó IP fija en las impresoras.", "Cada impresora tiene respaldo por USB."])["reglas"]
    assert r["S2"] == "ok" and r["S3"] == "ok"
    r = soporte.reglas_sugeridas("Falla", ["Las impresoras quedaron con IP automática.", "Sin respaldo en la barra."])["reglas"]
    assert r["S2"] == "bad" and r["S3"] == "bad"
    r = soporte.reglas_sugeridas("Falla", ["Se reinició el equipo."])["reglas"]
    assert r["S2"] == "na" and r["S3"] == "na"
    r = soporte.reglas_sugeridas("Falla", ["La impresora no tenía IP fija."])["reglas"]
    assert r["S2"] == "bad"
