import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
from streamlit.testing.v1 import AppTest

def btn(at, texto):
    for b in at.button:
        if texto in b.label:
            return b
    raise AssertionError(f"no hay boton '{texto}': {[b.label for b in at.button]}")

def test_turno_completo_demo():
    at = AppTest.from_file("../app.py", default_timeout=30).run()
    assert not at.exception
    btn(at, "Iniciar turno").click().run()
    sid = at.session_state.sid
    at.text_input[0].input("romana").run()
    btn(at, "Lechuga Romana").click().run()
    btn(at, "Iniciar lote").click().run()
    assert "Paso 1 de 3" in at.markdown[-3].value or any("Paso 1" in m.value for m in at.markdown)
    for g in (1200, 1300, 999):
        at.number_input[0].set_value(g); btn(at, "Registrar peso").click().run()
    btn(at, "Deshacer").click().run()
    btn(at, "empezar a procesar").click().run()
    btn(at, "Pausa").click().run(); btn(at, "Reanudar").click().run()
    btn(at, "pesar producto final").click().run()
    at.number_input[0].set_value(1800); btn(at, "Registrar peso").click().run()
    btn(at, "Terminar lote").click().run()
    assert not at.exception, at.exception
    # simulamos recarga del celular: sesion nueva con ?turno=
    at2 = AppTest.from_file("../app.py", default_timeout=30)
    at2.query_params["turno"] = sid
    at2.run()
    assert at2.session_state.sid == sid
    assert any("1 lote terminado" in c.value for c in at2.caption)
    btn(at2, "Terminar turno").click().run()
    btn(at2, "Confirmar y cerrar").click().run()
    assert any("cerrado" in s.value for s in at2.success)
    df = at2.dataframe[0].value
    print(df)
    assert df.iloc[0]["Entrada"] == "2.500 g" and df.iloc[0]["Salida"] == "1.800 g"
    assert df.iloc[0]["Rend."] == "72.0 %"
