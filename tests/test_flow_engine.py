"""Escenarios de aceptación del cliente (motor_referencia.py §14) corridos
contra el motor reanudable: cada paso serializa el state a JSON y lo
reconstruye, para probar que no depende de memoria entre requests."""
import json

from app.chat.flow_engine import FLOW, Session, StepError, new_state, validate_flow


def run(script, default_text="ok", max_steps=400):
    script = {"P05": "987654321", "P52": "Acuerdos de la visita", **script}
    state = new_state({"today": "31/05/2026", "technician": "Yomira Mora"})
    transcript = []
    for _ in range(max_steps):
        state = json.loads(json.dumps(state))  # sin memoria entre pasos
        s = Session(state)
        if state["done"]:
            return state, transcript
        p = s.prompt()
        nid, scope = p["nodeId"], p["scope"]
        raw = None
        for k in (f"{nid}@{scope}", nid):
            if k in script:
                v = script[k]
                raw = v(p) if callable(v) else v
                break
        if raw is None:
            t = p["inputType"]
            raw = {
                "YES_NO": "SI", "NUMBER": "1",
                "CHOICE": p["options"][0]["value"] if p["options"] else "",
                "MULTI_SELECT": p["options"][0]["value"] if p["options"] else "",
                "EVIDENCE": "", "ALERT": "", "SUMMARY": "GENERAR_MINUTA",
            }.get(t, default_text)
        if isinstance(raw, list):
            raw = ",".join(raw)
        evidence = {"count": 1, "extracted": {}} if p["kind"] == "evidence" else None
        s.advance(str(raw), evidence)
        transcript.append((nid, scope, raw, p["text"]))
    raise AssertionError("demasiados pasos")


ROCK = {
    "P10": 1, "P11": ["SALON_1", "CAJA", "COCINA", "BAR", "JUGOS"], "P12": 1,
    "P18": "CAJA", "P22": "SI", "P23": "CABLE_RED",
    "P25": ["CAJA", "COCINA", "BAR", "JUGOS"], "P26": 2,
    "P27@L_IMPRESORAS:1": ["CAJA"], "P27@L_IMPRESORAS:2": ["BAR", "JUGOS"],
    "P28@L_IMPRESORAS:2": "BAR",
    "P32": "NUEVA", "P32b": "COCINA", "P32c": "CABLE_RED",
    "U1": "NO", "U3": "Pared al costado de la plancha", "U5": "SI",
    "P35": "NO", "P36": "SI", "P36a": ["IMPRESORA"], "P43": "BAR",
    "P38": "SI", "P50": "SI", "P50a": "Falta instalar punto de red en Cocina",
}


def test_flow_is_statically_valid():
    assert validate_flow(FLOW) == []


def test_rock_and_burgers():
    state, t = run(ROCK)
    assert [p["label"] for p in state["printers"]] == [
        "IMP1 – Caja", "IMP2 – Bar + Jugos", "IMP3 – Cocina"]
    codes = [e["code"] for e in state["evidences"]]
    assert codes == ["E1", "E2", "E3", "E4", "E5", "E5", "EU-RN", "EU-E", "E6", "E7", "E8", "E9"]
    assert len(state["actions"]) == 5, state["actions"]
    assert any("impresora nueva" in a.lower() for a in state["actions"])
    assert any("UPS" in a for a in state["actions"])
    assert any("segunda visita" in a.lower() for a in state["actions"])


def test_sin_pc_en_caja_dos_pisos():
    script = {
        "P10": 2, "P11": ["CAJA", "BAR", "JUGOS"], "P12": 1, "P18": "CAJA",
        "P22": "NO", "P22a": "NO", "P22b": "RASPBERRY",
        "P25": ["BAR", "JUGOS"], "P26": 0,
        "P32@L_AREAS_SIN_IMP:1": "NUEVA", "P32b": "BAR", "P32c": "WIFI",
        "P32@L_AREAS_SIN_IMP:2": "COMPARTIR",
        "P32a": lambda p: p["options"][-1]["value"],
        "U1": "NO", "U5": "NO", "U3": "x", "U7": "y",
        "P33": "NO", "P36": "NO", "P38": "NO", "P38a": ["BAR"], "P50": "NO",
    }
    state, t = run(script)
    assert [p["label"] for p in state["printers"]] == ["IMP1 – Bar + Jugos"]
    nodes = [x[0] for x in t]
    assert "P11a" in nodes and "P39a" in nodes      # varios pisos
    assert "P23" not in nodes and "P24" not in nodes  # se salta ipconfig
    texts = " ".join(x[3] for x in t)
    assert "Raspberry" in texts and "no tienen impresora" in texts.lower() or "sin impresora" in texts.lower() or "no tienen impresora asignada" in texts
    # impresora WiFi: no se pregunta por punto de red (solo energía)
    ub = [x for x in t if x[0] == "U1" and "Impresora nueva" in x[3]]
    assert ub == []


def test_sin_cajas_salta_bloque_d():
    state, t = run({"P11": ["SALON_1", "COCINA"], "P12": 0, "P18": "SALON_1",
                    "P25": ["COCINA"], "P26": 1, "P27": ["COCINA"], "P36": "NO",
                    "P38": "SI", "P50": "NO"})
    assert not any(x[0] in ("P22", "P23", "P24") for x in t)


def test_validaciones():
    state = new_state({})
    s = Session(state)
    import pytest
    with pytest.raises(StepError):
        s.advance("")                      # P01 obligatorio
    s.advance("Rock & Burgers")
    for raw in ["Local", "Calle 1", "Ana, jefa"]:
        s.advance(raw)
    with pytest.raises(StepError):
        s.advance("abc")                   # teléfono: regex
    s.advance("987654321")


def test_area_personalizada():
    state, _ = run({"P11": "SALON_1,OTRO:Sala VIP", "P10": 1, "P12": 0, "P18": "SALON_1", "P50": "NO"})
    assert "X_SALA_VIP" in state["answers"]["P11"]
    assert state["areaLabels"]["X_SALA_VIP"] == "Sala VIP"


def test_omitir_evidencia():
    state = new_state({})
    s = Session(state)
    for raw in ["Cliente", "Local", "Calle 1", "Ana, jefa", "987654321", "31/05/2026", "Yo", "IMPLEMENTACION",
                "FAST_FOOD", "1", "SALON_1", "1", "NO", "CLARO", "FIBRA", "100", "NO", "NO", "SALON_1"]:
        s.advance(raw)
    assert s.prompt()["evidenceCode"] == "E1"
    s.advance("OMITIR")
    assert state["skipped"][0]["code"] == "E1"
    assert s.prompt()["evidenceCode"] == "E2"


def test_contexto_teclado_y_pistas():
    state = new_state({"today": "01/06/2026", "technician": "Yo"})
    s = Session(state)
    for raw in ["Cliente", "Local", "Calle 1", "Ana, jefa"]:
        s.advance(raw)
    p = s.prompt()
    assert p["nodeId"] == "P05" and p["keyboard"] == "phone"
    s.advance("987654321")
    assert s.prompt()["keyboard"] == "date" and s.prompt()["defaultValue"] == "01/06/2026"
    # dentro de un loop de cajas el contexto dice "Caja 1 de 2"
    run_state, _ = run({"P10": 1, "P11": ["CAJA"], "P12": 2, "P18": "CAJA", "P50": "NO"})
    state2 = new_state({})
    s2 = Session(state2)
    for raw in ["C", "L", "D", "N", "987654321", "01/06/2026", "Yo", "IMPLEMENTACION", "FAST_FOOD", "1", "CAJA", "2", "NO",
                "CLARO", "FIBRA", "100", "NO", "NO", "CAJA"]:
        s2.advance(raw)
    for _ in range(3):
        s2.advance("", {"count": 1, "extracted": {}})
    assert s2.prompt()["context"] == "Caja 1 de 2"


def _until_evidence(code):
    """Corre el flujo hasta quedar parado en la evidencia `code` (sin subirla)."""
    state = new_state({"today": "31/05/2026", "technician": "Yomira Mora"})
    script = {"P05": "987654321"}
    for _ in range(400):
        s = Session(state)
        p = s.prompt()
        if p["kind"] == "evidence" and p["evidenceCode"] == code:
            return state, s, p
        t = p["inputType"]
        raw = script.get(p["nodeId"]) or {
            "YES_NO": "SI", "NUMBER": "1",
            "CHOICE": p["options"][0]["value"] if p["options"] else "",
            "MULTI_SELECT": p["options"][0]["value"] if p["options"] else "",
            "EVIDENCE": "", "ALERT": "", "SUMMARY": "GENERAR_MINUTA",
        }.get(t, "ok")
        s.advance(str(raw), {"count": 1, "extracted": {}} if p["kind"] == "evidence" else None)
    raise AssertionError("no llegó a la evidencia")


def test_foto_del_local_es_obligatoria():
    import pytest

    state, s, p = _until_evidence("E9")
    assert p["skippable"] is False
    with pytest.raises(StepError, match="obligatoria"):
        s.advance("OMITIR", {"count": 0, "extracted": {}})
    # Con una foto avanza.
    s.advance("", {"count": 1, "extracted": {}})


def test_las_demas_evidencias_se_pueden_omitir():
    state, s, p = _until_evidence("E1")
    assert p["skippable"] is True
    s.advance("OMITIR", {"count": 0, "extracted": {}})


def test_el_documento_avisa_si_falta_la_foto_del_local():
    from app.chat.minuta_doc import _missing_mandatory

    assert _missing_mandatory({"evidences": []}) == ["Foto general del local (E9)"]
    assert _missing_mandatory({"evidences": [{"code": "E9", "count": 2}]}) == []


# ---- cambios del 2026-10: P12b, P14, P22 y regla de impresoras de preparación -----------------
BASE = {"P10": 1, "P11": ["CAJA", "COCINA"], "P12": 1, "P18": "CAJA", "P25": ["CAJA"], "P26": 0,
        "P32@L_AREAS_SIN_IMP:1": "NUEVA", "P32b": "CAJA", "P32c": "CABLE_RED", "U1": "SI", "U5": "SI",
        "P33": "SI", "P36": "NO", "P38": "SI", "P50": "NO"}


def _nodes(t):
    return [x[0] for x in t]


def test_p22_sin_pc_en_caja_pide_raspberry_y_marca_pendiente():
    for answer, confirm in (("NO", False), ("NO_SE", True)):
        state, t = run({**BASE, "P22": answer, "P22a": "NO", "P22b": "RASPBERRY"})
        assert "A_RASPBERRY" in _nodes(t) and "P23" not in _nodes(t)
        assert any("confirmar con el cliente" in a for a in state["actions"]) is confirm


def test_p22_tablet_exige_raspberry_obligatorio():
    state, t = run({**BASE, "P22": "TABLET", "P22a": "NO", "P22b": "RASPBERRY"})
    assert _nodes(t).index("A_RASPBERRY_TABLET") < _nodes(t).index("P22a")
    assert any("obligatorio por usar tablet" in a for a in state["actions"])


def test_p22_otro_pregunta_que_equipo_es():
    state, t = run({**BASE, "P22": "OTRO", "P22f": "Terminal POS Sunmi", "P22a": "NO", "P22b": "RASPBERRY"})
    nodes = _nodes(t)
    assert nodes.index("P22f") == nodes.index("P22") + 1 and "A_RASPBERRY" in nodes
    assert state["answers"]["P22f#L_CAJAS:1"] == "Terminal POS Sunmi"
    assert any("Terminal POS Sunmi" in a for a in state["actions"])


def test_p22_opciones():
    state, s, p = _until_evidence("E1")  # solo para tener un Session; las opciones se leen del nodo
    node = FLOW.nodes["P22"]
    assert [o["value"] for o in node["options"]] == ["SI", "NO", "TABLET", "NO_SE", "OTRO"]


def test_comanda_en_caja_es_pregunta_fija_para_todos_los_negocios():
    # Sin cajas también se pregunta.
    _, t = run({**BASE, "P12": 0})
    assert "P12b" in _nodes(t)
    assert FLOW.nodes["P12"]["next"] == "P12b"


def test_comanda_solo_en_caja_recomienda_sunmi():
    # Sin áreas de preparación y con comanda en caja → Sunmi
    state, t = run({**BASE, "P11": ["CAJA", "SALON_1"], "P12b": "SI", "P22": "SI", "P23": "CABLE_RED"})
    assert "A_SUNMI" in _nodes(t)
    assert any("Sunmi" in a for a in state["actions"])
    # Con un área de preparación no hace falta
    _, t = run({**BASE, "P11": ["CAJA", "COCINA"], "P12b": "SI", "P22": "SI", "P23": "CABLE_RED"})
    assert "A_SUNMI" not in _nodes(t)


def test_p14_opciones_nuevas():
    values = [o["value"] for o in FLOW.nodes["P14"]["options"]]
    labels = [o["label"] for o in FLOW.nodes["P14"]["options"]]
    assert values == ["FIBRA", "COAXIAL", "NO_SE", "NO_TIENE", "CHIP"]
    assert labels == ["Fibra óptica", "Cable coaxial", "No sé", "No tiene", "Internet con chip"]


def test_sin_internet_salta_velocidad_y_speedtest():
    for answer in ("NO_TIENE", "NO_SE"):
        state, t = run({**BASE, "P14": answer, "P22": "SI", "P23": "CABLE_RED"})
        nodes = _nodes(t)
        assert "P15" not in nodes and "P19" not in nodes
        assert any("señal del chip" in a for a in state["actions"])
    # Con internet sí se pregunta
    _, t = run({**BASE, "P14": "COAXIAL", "P22": "SI", "P23": "CABLE_RED"})
    assert "P15" in _nodes(t) and "P19" in _nodes(t)


def test_impresora_de_preparacion_debe_ser_de_red_por_cable():
    script = {**BASE, "P25": ["COCINA"], "P26": 1, "P22": "SI", "P23": "CABLE_RED",
              "P27": ["COCINA"], "P28": "COCINA"}
    state, _ = run({**script, "P30": "USB"})
    assert any("deben ser de red, por cable" in a for a in state["alerts"])
    assert any("cambiarla por una impresora de red" in a for a in state["actions"])
    state, _ = run({**script, "P30": "CABLE_RED"})
    assert not any("deben ser de red" in a for a in state["alerts"])


def test_impresora_nueva_de_preparacion_por_wifi_genera_aviso():
    script = {**BASE, "P11": ["CAJA", "BAR"], "P25": ["BAR"], "P26": 0, "P22": "SI", "P23": "CABLE_RED",
              "P32@L_AREAS_SIN_IMP:1": "NUEVA", "P32b": "BAR", "P32c": "WIFI"}
    state, _ = run(script)
    assert any("debe ser de red, por cable" in a for a in state["alerts"])


def test_regla_r51_en_la_validacion_de_la_minuta():
    from app.chat import checks

    script = {**BASE, "P25": ["COCINA"], "P26": 1, "P22": "SI", "P23": "CABLE_RED", "P27": ["COCINA"],
              "P28": "COCINA"}
    for conn, status in (("USB", checks.OBSERVADO), ("CABLE_RED", checks.CUMPLE)):
        state, _ = run({**script, "P30": conn})
        rules = [r for r in checks.evaluate_rules(state) if r.rule.startswith("Impresoras de áreas de preparación")]
        assert rules and rules[0].status == status


def test_la_minuta_refleja_equipo_de_caja_y_comandas():
    from app.chat.minuta_doc import build_minuta_document

    state, _ = run({**BASE, "P22": "TABLET", "P22a": "NO", "P22b": "RASPBERRY", "P12b": "SI"})
    doc = build_minuta_document(state)
    rows = {r.label: r.value for sec in doc.sections for r in sec.rows}
    assert rows["Comandas en caja"] == "Sí"
    assert "Tablet en caja" in rows["Equipo Caja 1"] and "Raspberry" in rows["Equipo Caja 1"]
    state, _ = run({**BASE, "P22": "OTRO", "P22f": "Terminal propia", "P22a": "NO", "P22b": "LAPTOP"})
    rows = {r.label: r.value for sec in build_minuta_document(state).sections for r in sec.rows}
    assert "Terminal propia" in rows["Equipo Caja 1"]
