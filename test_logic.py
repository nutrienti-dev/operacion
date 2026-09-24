import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
from datetime import datetime, timedelta
from lib import logic as L
from lib.storage import MemoryStorage

T0 = datetime(2026, 9, 24, 8, 0, 0)

def ev(mins, evento, lote="L1", peso=None, ref="", rid=None):
    return L.Evento(rid or L.short_id(), T0 + timedelta(minutes=mins), "2026-09-24", "T1",
                    lote if evento not in (L.SESION_INICIO, L.SESION_FIN) else "",
                    "Lechuga Romana", evento, peso, ref)

def test_flujo_completo_con_pausa_y_anulacion():
    evs = [ev(0, L.SESION_INICIO), ev(1, L.LOTE_INICIO, ref="LRH026"),
           ev(2, L.PESO_INICIAL, peso=1000), ev(3, L.PESO_INICIAL, peso=9999, rid="malo"),
           ev(3.5, L.ANULAR, ref="malo"), ev(4, L.PESO_INICIAL, peso=1500),
           ev(6, L.FIN_PESAJE_INICIAL), ev(10, L.PAUSA), ev(20, L.REANUDA),
           ev(36, L.FIN_PROCESO), ev(37, L.PESO_FINAL, peso=1800), ev(41, L.LOTE_FIN)]
    est = L.reproducir(evs)
    assert est.lote_actual is None and len(est.lotes_terminados) == 1
    m = L.metricas_lote(est.lotes_terminados[0])
    assert m["peso_inicial"] == 2500 and m["peso_final"] == 1800
    assert m["rendimiento"] == 72.0 and m["merma"] == 700 and m["merma_pct"] == 28.0
    assert m["min_pesaje_inicial"] == 5 and m["min_proceso"] == 20 and m["min_pesaje_final"] == 5
    assert m["min_pausa"] == 10 and m["min_neto"] == 30
    assert m["kg_h"] == 5.0 and m["min_kg"] == 12.0
    fila = L.fila_lote(est.lotes_terminados[0], "T1", "2026-09-24")
    assert len(fila) == len(L.LOTES_HEADERS)

def test_roundtrip_filas_y_resumen():
    evs = [ev(0, L.SESION_INICIO), ev(1, L.LOTE_INICIO), ev(2, L.PESO_INICIAL, peso=2000),
           ev(3, L.FIN_PESAJE_INICIAL), ev(13, L.FIN_PROCESO), ev(14, L.PESO_FINAL, peso=1500),
           ev(15, L.LOTE_FIN), ev(16, L.LOTE_INICIO, lote="L2"), ev(17, L.PESO_INICIAL, lote="L2", peso=500)]
    s = MemoryStorage(); s.append_eventos(evs)
    est = L.reproducir(s.leer_eventos("T1"))
    assert est.lote_actual.lote_id == "L2" and est.lote_actual.fase == L.FASE_PESAJE_INICIAL
    s.append_lote(L.fila_lote(est.lotes_terminados[0], "T1", "2026-09-24"))
    res = L.calcular_resumen(s.leer_lotes())
    assert res[0][:6] == ["Lechuga Romana", 1, 2.0, 1.5, 75.0, 25.0]

def test_catalogo():
    cat = L.construir_catalogo([
        {"codigo": "LRH026", "descripcion": "Lechuga Romana x Unidad"},
        {"codigo": "LRH027", "descripcion": "Lechuga Romana x Kilo"},
        {"codigo": "LCVT022", "descripcion": "Lechuga Crespa Verde Tierra x Unidad"},
        {"codigo": "LCVT023", "descripcion": "Lechuga Crespa Verde de Tierra x Kilo"},
        {"codigo": "CEB07", "descripcion": "Cebollin por Kilo"}])
    assert [c["producto"] for c in cat] == ["Cebollin", "Lechuga Crespa Verde Tierra", "Lechuga Romana"] \
        or len(cat) == 3
    assert {c["codigos"] for c in cat} >= {"LRH026/LRH027", "LCVT022/LCVT023"}
    assert [c["producto"] for c in L.filtrar(cat, "romana")] == ["Lechuga Romana"]
