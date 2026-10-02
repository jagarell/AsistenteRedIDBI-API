"""Caso Rock & Burgers de la minuta de ejemplo del cliente: recorre el chat
completo con lecturas de IA simuladas (valores de la minuta de ejemplo) y
valida que el documento reproduzca sus hallazgos."""
import json
import os

from fastapi.testclient import TestClient

from app.chat import engine as engine_module
from app.chat.evidence import EvidenceResult
from app.main import app

client = TestClient(app)

E5_BY_SCOPE = {
    "L_IMPRESORAS:1": {"marca": "Epson", "modelo": None, "descripcion": "Epson conectada por USB. La foto está lejos."},
    "L_IMPRESORAS:2": {"marca": "CBX", "modelo": "CBX-POS89E", "numeroSerie": "11101800002",
                       "ip": "192.168.100.20", "mascara": "255.255.255.0", "puertaEnlace": "192.168.100.1",
                       "dhcp": False, "mac": "28:0E:8B:B4:FE:F1", "puerto": "9100", "papel": "72 mm",
                       "interfaz": "Ethernet y USB", "descripcion": "Ticket de autoprueba."},
}
SCAN = [
    {"ip": "192.168.100.1", "mac": "F8:95:22:93:F3:D6", "fabricante": "HUAWEI TECHNOLOGIES", "nombre": None},
    {"ip": "192.168.100.13", "mac": "00:11:22:33:44:55", "fabricante": "Intel", "nombre": "DESKTOP-C85EDPG"},
    {"ip": "192.168.100.20", "mac": "28:0E:8B:B4:FE:F1", "fabricante": "Beijing Spirit", "nombre": None},
    {"ip": "192.168.100.22", "mac": "AA:00:00:00:00:22", "fabricante": "HUAWEI TECHNOLOGIES", "nombre": None},
    {"ip": "192.168.100.50", "mac": "AA:00:00:00:00:50", "fabricante": "HUAWEI TECHNOLOGIES", "nombre": None},
    {"ip": "192.168.100.12", "mac": "AA:00:00:00:00:12", "fabricante": "Samsung", "nombre": None},
    {"ip": "192.168.100.54", "mac": "AA:00:00:00:00:54", "fabricante": "Microsoft", "nombre": "DESKTOP-3J10MSV"},
]


def fake_analyze(code, images, scope=""):
    data = {
        "E1": {"bajadaMbps": 91.5, "subidaMbps": 92.49, "pingMs": 8, "latenciaBajadaMs": 171,
               "latenciaSubidaMs": 295, "proveedor": "Google", "servidor": "Servitronic (Ancón)",
               "descripcion": "Captura de speedtest."},
        "E2": {"marca": "Huawei", "descripcion": "Sticker de Claro con su línea de atención: confirma el proveedor. "
                                                  "Repetidor junto al router y cables rotulados."},
        "E3": {"marca": "Huawei", "modelo": "OptiXstar HG8145X6-10", "numeroSerie": "485754437863FFB3",
               "mac": "F8:95:22:93:F3:D6", "ipGestion": "192.168.100.1", "descripcion": "Etiqueta del router."},
        "E4": {"ipv4": "192.168.100.13", "mascara": "255.255.255.0", "puertaEnlace": "192.168.100.1",
               "adaptador": "WiFi", "nombreEquipo": "DESKTOP-C85EDPG", "ethernetDesconectado": True,
               "descripcion": "ipconfig."},
        "E8": {"dispositivos": SCAN, "descripcion": "23 dispositivos en 192.168.100.1–254."},
    }.get(code, {"descripcion": "Foto."})
    return EvidenceResult(code=code, extracted=data, processedImages=["QUJD"] if code == "E3" else None)


def test_rock_burgers_sample(monkeypatch):
    # El motor llama analyze_evidence(code, photos); el scope del E5 se deduce del nodo.
    scope_holder = {}

    def analyze(code, images):
        if code == "E5":
            return EvidenceResult(code=code, extracted=E5_BY_SCOPE[scope_holder["scope"]])
        return fake_analyze(code, images)

    monkeypatch.setattr(engine_module, "analyze_evidence", analyze)
    monkeypatch.setattr(engine_module, "geocode", lambda *_: "-11.49,-77.2")

    answers = {
        "P01": "Rock & Burgers", "P02": "Rock & Burgers – Huaral", "P03": "C. Luis Colán 242, Huaral 15201, Huaral",
        "P04": "Gianfranco (equipo operativo)", "P05": "987654321", "P06": "31/05/2026", "P07": "Yomira Mora",
        "P08": "IMPLEMENTACION", "P09": "FAST_FOOD", "P10": "3",
        "P11": "CAJA,COCINA,SALON_1,SALON_2", "P12": "1", "P13": "CLARO", "P14": "FIBRA", "P15": "100",
        "P16": "NO", "P17": "NO", "P18": "CAJA", "P22": "PC", "P23": "WIFI",
        "P25": "CAJA,COCINA", "P26": "2", "P29": "EPSON", "P30": "USB",
        "P33": "SI", "P34": "NO", "P35": "NO", "P36": "NO", "P37": "5", "P38": "SI", "P39": "CAT6_INT",
        "P39a": "DUCTO", "P40": "ORDENADO_ROTULADO", "P41": "NO", "P45": "SI", "P46": "NINGUNA", "P47": "NO",
        "P50": "NO", "P51": "Gianfranco", "P52": "Capacitación e inicio con el sistema el 01 de junio.\n"
                                              "Pruebas de comandos con la impresora USB.\n"
                                              "Compartir la minuta técnica.\n"
                                              "Enviar la lista de usuarios que tendrán acceso como meseros.",
    }
    floors = iter(["2", "1", "2", "3"])
    r = client.post("/chat/start", json={"evaluationId": "1"}).json()
    for _ in range(300):
        if r["completed"]:
            break
        node = r["node"]
        nid = node["nodeId"]
        scope_holder["scope"] = node["scope"]
        body = {"evaluationId": "1", "state": r["state"], "answer": answers.get(nid, "")}
        if nid == "P11a":
            body["answer"] = next(floors)
        if nid == "P27":
            body["answer"] = node["options"][0]["value"]
        if nid == "P28":
            body["answer"] = node["options"][0]["value"]
        if nid == "P30" and node["scope"].endswith(":2"):
            body["answer"] = "CABLE_RED"
        if nid == "P29" and node["scope"].endswith(":2"):
            body["answer"] = "OTRO"
        if node["kind"] == "evidence":
            body["photosBase64"] = ["QUJD"]
        r = client.post("/chat/answer", json=body).json()
        assert not r.get("validationError"), (nid, r["validationError"])
    assert r["completed"]
    doc = client.post("/chat/minuta-document", json={"state": r["answers"]["__state"]}).json()
    status = {x["rule"]: x["status"] for x in doc["rules"]}
    assert status["Latencia con la red en uso < 100 ms"] == "OBSERVADO"
    assert status["Proveedor consistente entre evidencias"] == "REVISAR"
    assert status["MAC de la impresora coincide con el escáner"] == "VERIFICADO"
    assert status["Credenciales fuera del documento"] == "APLICADO"
    assert doc["finalStatus"] == "OBSERVADO"
    assert [p["nombre"] for p in doc["printers"]] == ["Impresora Caja", "Impresora Cocina"]
    if os.environ.get("KEEP_ARTIFACTS"):
        with open("/tmp/minuta_rock_doc.json", "w") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
