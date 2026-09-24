import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
from lib import logic as L
from lib.storage import SheetsStorage

class WS:
    def __init__(s, title): s.title=title; s.data=[]
    def row_values(s, i): return list(s.data[i-1]) if len(s.data)>=i else []
    def update(s, values, rng, value_input_option=None):
        col=ord(rng[0])-65; row=int(''.join(c for c in rng.split(':')[0] if c.isdigit()))
        for k,v in enumerate(values):
            while len(s.data)<row+k: s.data.append([])
            r=s.data[row+k-1]
            while len(r)<col+len(v): r.append('')
            r[col:col+len(v)]=v
    def freeze(s, rows=0): pass
    def append_rows(s, rows, **kw): s.data.extend([list(r) for r in rows])
    def get_all_values(s, **kw): return [list(r) for r in s.data]
    def get(s, rng): return [r[:2] for r in s.data[1:]]
    def col_values(s, c): return [r[c-1] if len(r)>=c else '' for r in s.data]
    def batch_update(s, ups, **kw):
        for u in ups: s.update(u["values"], u["range"])
    def clear(s): s.data=[]

class SH:
    url="https://x"
    def __init__(s): s.w=[WS("Hoja 1")]
    def worksheets(s): return list(s.w)
    def add_worksheet(s, t, rows, cols): w=WS(t); s.w.append(w); return w
    def del_worksheet(s, w): s.w.remove(w)

class GC:
    def open(s, t, folder_id=None): raise Exception("not found")
    def create(s, t, folder_id=None): s.sh=SH(); return s.sh

def test_sheets_storage_flow():
    gc=GC(); st=SheetsStorage(gc, None, "t", "f")
    assert [w.title for w in gc.sh.w]==["Registros","Lotes","Sesiones","Resumen"]
    st.crear_sesion("T1","2026-09-24","2026-09-24 08:00:00")
    assert st.sesiones_abiertas()[0]["Sesion ID"]=="T1"
    e=[L.Evento("a",L.now(),"2026-09-24","T1","L1","X",L.LOTE_INICIO),
       L.Evento("b",L.now(),"2026-09-24","T1","L1","X",L.PESO_INICIAL,1000)]
    st.append_eventos(e)
    assert [x.peso for x in st.leer_eventos("T1")]==[None,1000]
    st.append_lote(["L1","T1","2026-09-24","X"]+[0]*17+["Abierto"])
    assert st.lote_ids("T1")=={"L1"}
    st.marcar_lotes("T1","Cerrado")
    assert st.leer_lotes()[0]["Estado turno"]=="Cerrado"
    st.cerrar_sesion("T1","2026-09-24 12:00:00",1,1000,800)
    assert st.sesiones_abiertas()==[]
    st.escribir_resumen(L.calcular_resumen(st.leer_lotes()))
