"""Recorrido HTTP completo (start → answer… → completed) con la lectura de IA
simulada, para probar el contrato que consume el gateway."""
import json

from fastapi.testclient import TestClient

from app.chat import engine as engine_module
from app.chat.evidence import EvidenceResult
from app.main import app

client = TestClient(app)

FAKE = {
    "E1": {"bajadaMbps": 91.5, "subidaMbps": 92.49, "pingMs": 8, "latenciaBajadaMs": 171,
           "latenciaSubidaMs": 295, "proveedor": "Google", "descripcion": "speedtest"},
    "E3": {"marca": "Huawei", "modelo": "OptiXstar HG8145X6-10", "mac": "F8:95:22:93:F3:D6",
           "ipGestion": "192.168.100.1", "descripcion": "etiqueta"},
    "E4": {"ipv4": "192.168.100.13", "puertaEnlace": "192.168.100.1", "adaptador": "WiFi",
           "ethernetDesconectado": True, "descripcion": "ipconfig"},
    "E5": {"marca": "CBX", "modelo": "CBX-POS89E", "ip": "192.168.100.20", "puertaEnlace": "192.168.100.1",
           "dhcp": False, "mac": "28:0E:8B:B4:FE:F1", "descripcion": "ticket"},
    "E8": {"dispositivos": [{"ip": "192.168.100.20", "mac": "28:0E:8B:B4:FE:F1", "fabricante": "Beijing Spirit",
                             "nombre": None},
                            {"ip": "192.168.100.54", "mac": "AA:BB:CC:DD:EE:FF", "fabricante": "x",
                             "nombre": "DESKTOP-3J10MSV"}], "descripcion": "scan"},
}


def fake_analyze(code, images):
    return EvidenceResult(code=code, extracted=FAKE.get(code, {"descripcion": "foto"}),
                          processedImages=["BLUR"] if code == "E3" else None)


ANSWERS = {
    "P01": "Rock & Burgers", "P02": "Rock & Burgers – Huaral", "P03": "C. Luis Colán 242, Huaral",
    "P04": "Gianfranco, gerente", "P05": "987654321", "P06": "31/05/2026", "P07": "Yomira Mora",
    "P08": "IMPLEMENTACION", "P09": "FAST_FOOD", "P10": "1",
    "P11": "SALON_1,CAJA,COCINA,BAR", "P12": "1", "P13": "CLARO", "P14": "FIBRA", "P15": "100",
    "P16": "NO", "P17": "NO", "P18": "CAJA", "P22": "PC", "P23": "WIFI",
    "P25": "CAJA,COCINA", "P26": "2", "P29": "EPSON", "P30": "USB",
    "U1": "NO", "U3": "Pared de la plancha", "U5": "SI",
    "P33": "SI", "P34": "NO", "P35": "NO", "P36": "NO", "P37": "5", "P38": "SI", "P39": "CAT6_INT",
    "P40": "ORDENADO", "P41": "SI", "P45": "SI", "P46": "NINGUNA", "P47": "NO", "P50": "NO",
    "P51": "Gianfranco", "P52": "Capacitación el 01 de junio", "P53": "",
}


def test_full_walk(monkeypatch):
    monkeypatch.setattr(engine_module, "analyze_evidence", fake_analyze)
    monkeypatch.setattr(engine_module, "geocode", lambda *_: "-11.49,-77.2")

    r = client.post("/chat/start", json={"evaluationId": "1", "technicianName": "Yomira Mora",
                                           "today": "31/05/2026"}).json()
    assert r["currentQuestionKey"] == "P01" and r["node"]["blockLabel"] == "Datos de la visita"
    seen_cross, p27_options = [], None
    for _ in range(200):
        if r["completed"]:
            break
        node = r["node"]
        nid, kind = node["nodeId"], node["kind"]
        body = {"evaluationId": "1", "state": r["state"], "answer": ANSWERS.get(nid, "")}
        if nid in ("P27", "P28"):
            body["answer"] = node["options"][0]["value"]
        if kind == "evidence":
            body["photosBase64"] = ["QUJD"]
        if kind == "summary":
            body["answer"] = "GENERAR_MINUTA"
        r = client.post("/chat/answer", json=body).json()
        assert not r.get("validationError"), (nid, r["validationError"])
        seen_cross += r["crossChecks"] + [f["text"] for f in r["followUps"]]

    assert r["completed"]
    assert r["answers"]["establishment_name"] == "Rock & Burgers – Huaral"
    assert r["answers"]["internet_provider"] == "Claro"
    assert r["answers"]["visita.local"] == "Rock & Burgers – Huaral"
    state = json.loads(r["answers"]["__state"])
    assert [p["label"] for p in state["printers"]] == ["IMP1 – Caja", "IMP2 – Cocina"]
    # avisos: proveedor distinto en E1 y adaptador WiFi vs. cable no aplica (P23=WIFI coincide)
    assert any("Google" in m for m in seen_cross)
    assert r["proposal"]["topology"]["nodes"]
    labels = [n["label"] for n in r["proposal"]["topology"]["nodes"]]
    assert any("Huawei" in l for l in labels) and any("Cocina" in l for l in labels)


def test_validation_error_does_not_advance():
    r = client.post("/chat/start", json={"evaluationId": "1"}).json()
    bad = client.post("/chat/answer", json={"evaluationId": "1", "state": r["state"], "answer": ""}).json()
    assert bad["validationError"] and bad["currentQuestionKey"] == "P01"
    assert bad["state"] == r["state"]


def test_minuta_document(monkeypatch, tmp_path):
    import base64
    monkeypatch.setattr(engine_module, "analyze_evidence", fake_analyze)
    monkeypatch.setattr(engine_module, "geocode", lambda *_: "-11.49,-77.2")
    r = client.post("/chat/start", json={"evaluationId": "1"}).json()
    for _ in range(200):
        if r["completed"]:
            break
        node = r["node"]
        body = {"evaluationId": "1", "state": r["state"], "answer": ANSWERS.get(node["nodeId"], "")}
        if node["nodeId"] in ("P27", "P28"):
            body["answer"] = node["options"][0]["value"]
        if node["kind"] == "evidence":
            body["photosBase64"] = ["QUJD"]
        r = client.post("/chat/answer", json=body).json()
    doc = client.post("/chat/minuta-document", json={"state": r["answers"]["__state"]}).json()
    assert doc["kpis"]["fields"] > 20 and doc["kpis"]["pending"] >= 3
    assert doc["finalStatus"] in ("APTO", "OBSERVADO", "NO APTO")
    assert any(rule["status"] == "OBSERVADO" for rule in doc["rules"])
    assert doc["printers"] and doc["annexA"] and doc["mapPngBase64"]
    out = tmp_path / "map.png"
    out.write_bytes(base64.b64decode(doc["mapPngBase64"]))
    import os, shutil
    if os.environ.get("KEEP_ARTIFACTS"):
        shutil.copy(out, "/tmp/minuta_map.png")
        open("/tmp/minuta_doc.json", "w").write(json.dumps(doc, ensure_ascii=False, indent=1))


def test_followups_and_amend(monkeypatch):
    monkeypatch.setattr(engine_module, "analyze_evidence", fake_analyze)
    monkeypatch.setattr(engine_module, "geocode", lambda *_: "-11.49,-77.2")
    r = client.post("/chat/start", json={"evaluationId": "1"}).json()
    e1 = None
    for _ in range(100):
        node = r["node"]
        body = {"evaluationId": "1", "state": r["state"], "answer": ANSWERS.get(node["nodeId"], "")}
        if node["kind"] == "evidence":
            body["photosBase64"] = ["QUJD"]
        r = client.post("/chat/answer", json=body).json()
        if r.get("lastEvidence") and r["lastEvidence"]["code"] == "E1":
            e1 = r
            break
    assert e1 and e1["followUps"][0]["key"] == "provider"
    assert e1["followUps"][0]["options"] == ["Claro", "Google", "No sé"]

    # Corregir: el proveedor leído pasa a "Claro" -> ya no hay aviso de proveedor distinto
    fixed = client.post("/chat/amend", json={
        "evaluationId": "1", "state": e1["state"], "evidenceCode": "E1",
        "evidenceScope": e1["lastEvidence"]["scope"], "fields": {"proveedor": "Claro"}}).json()
    assert fixed["lastEvidence"]["extracted"]["proveedor"] == "Claro"
    assert not any("proveedor" in m.lower() for m in fixed["crossChecks"])

    # Confirmación del proveedor queda registrada en el estado
    answered = client.post("/chat/amend", json={
        "evaluationId": "1", "state": e1["state"], "clarificationKey": "provider",
        "clarificationAnswer": "Claro"}).json()
    assert json.loads(answered["state"])["clarifications"]["provider"] == "Claro"
