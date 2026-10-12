"""El port a Python de la lógica del simulador debe dar lo mismo que el simulador."""
import json
import math
from pathlib import Path

import pytest

from app.chat.sim.flow import build
from app.chat.sim.rules import evaluate, gen_pasos
from app.chat.sim.scoring import ref_data, resumen_ia, scores

GOLDEN = json.loads((Path(__file__).parent / "golden" / "sim_golden.json").read_text(encoding="utf-8"))


def _plain(o):
    return json.loads(json.dumps(o, default=lambda v: None, ensure_ascii=False))


def _close(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, abs_tol=1e-9)
    return a == b


def _assert_same(path, py, js):
    if isinstance(js, dict) and isinstance(py, dict):
        for k, v in js.items():
            if k not in py:
                assert v in (None, [], {}, False, ""), f"{path}.{k}: falta en Python (simulador={v!r})"
            else:
                _assert_same(f"{path}.{k}", py[k], v)
    elif isinstance(js, list) and isinstance(py, list):
        assert len(py) == len(js), f"{path}: largo Python={len(py)} simulador={len(js)}"
        for i, (x, y) in enumerate(zip(py, js)):
            _assert_same(f"{path}[{i}]", x, y)
    else:
        assert _close(py, js), f"{path}: Python={py!r} simulador={js!r}"


@pytest.mark.parametrize("case", GOLDEN, ids=[c["name"] for c in GOLDEN])
def test_port_igual_al_simulador(case):
    a = case["A"]
    N, X = build(a, {"technician": "Técnico de prueba"})
    R = evaluate(X, a)
    S = scores(X, R, a)

    keys = ("id", "kind", "text", "opts", "items", "zones")
    py_nodes = _plain([{k: n.get(k) for k in keys} for n in N])
    js_nodes = [{k: n.get(k) for k in keys} for n in case["N"]]
    assert [n["id"] for n in py_nodes] == [n["id"] for n in js_nodes]
    _assert_same("N", py_nodes, _plain(js_nodes))

    x = _plain(X)
    x.pop("P", None)
    _assert_same("X", x, case["X"])

    fields = ("id", "tipo", "t", "d", "eq", "trabajo")
    _assert_same("R.it", _plain([{k: i.get(k) for k in fields} for i in R.it]), case["it"])
    if case["con"] is None:
        assert R.con is None
    else:
        _assert_same("R.con", _plain(R.con), case["con"])
    assert R.estado == case["estado"]
    assert R.V01 == case["V01"]
    if case["sp"]:
        _assert_same("R.sp", _plain(R.sp), case["sp"])

    _assert_same("scores", {"g": S.g, "att": S.att, "areas": S.areas,
                            "cards": [{"k": c.k, "v": c.v, "why": c.why} for c in S.cards]}, case["scores"])
    _assert_same("pasos", gen_pasos(X, R, a), case["pasos"])
    refs = ref_data(X, R)
    _assert_same("refs", _plain({"top": [{"n": t["n"], "pct": t["pct"]} for t in refs["top"]], "recs": refs["recs"], "sug": refs["sug"]}),
                 case["refs"])
    assert resumen_ia(X, R) == case["resumen"]
