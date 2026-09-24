"""Nutrienti — Track de Operacion.

App movil para que los operarios registren, por lote y por tandas:
peso de entrada (crudo), tiempo de proceso y peso de salida (procesado).
Cada accion se guarda de inmediato en Google Sheets, asi que si el celular
se recarga o se cae el internet, el turno se retoma donde iba.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import streamlit as st

from lib import logic as L
from lib.storage import MemoryStorage, SheetsStorage

# ------------------------------------------------------------ configuracion
PRODUCTOS_SHEET_ID = "1HMNBT9Qqogz3WgZIenm-jB9wTUP7Ta_NP1BhUhoB3-s"  # Precios por Cliente (World Office)
PRODUCTOS_GID = 1797058694
INTEGRACION_AI_FOLDER = "1I84GZo517GSPCmUQZVThxqdTODckhrmZ"
SHEET_ID = "1KeIRNsTJY_7q07jnEo8VijIiYsti7JA7c84Ue9GngBM"  # "registro operacion" (Integracion AI)
TITULO_HOJA = "Nutrienti - Track Operacion"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
RESPALDO_CSV = Path(__file__).parent / "productos_respaldo.csv"
PESO_MAX_G = 200_000  # 200 kg por pesada: mas que eso es casi seguro un error

st.set_page_config(page_title="Track Operación", page_icon="🥬", layout="centered",
                   initial_sidebar_state="collapsed")

st.markdown(
    """
<style>
  .block-container {padding-top: 1.2rem; padding-bottom: 4rem; max-width: 640px;}
  div[data-testid="stElementContainer"]:has(> div.stButton),
  div[data-testid="stElementContainer"]:has(> div.stFormSubmitButton),
  div[data-testid="stElementContainer"]:has(> div.stLinkButton) {width: 100% !important;}
  div.stButton button, div.stFormSubmitButton button, div.stLinkButton a {
      width: 100%; min-height: 3.8rem; border-radius: 14px;
  }
  div.stButton button p, div.stFormSubmitButton button p, div.stLinkButton a p {
      font-size: 1.25rem !important; font-weight: 600;
  }
  div[data-testid="stNumberInput"] input {
      font-size: 2.2rem !important; height: 4rem; text-align: center; font-weight: 700;
  }
  div[data-testid="stTextInput"] input {font-size: 1.2rem !important; height: 3rem;}
  div[data-testid="stHorizontalBlock"] {flex-wrap: nowrap !important; gap: .6rem;}
  div[data-testid="stColumn"] {min-width: 0 !important; flex: 1 1 0 !important;}
  div[data-testid="stMetricValue"] div {font-size: 1.8rem !important;}
  div[data-testid="stMarkdownContainer"] p.fase {font-size: 1.05rem; font-weight: 700;
      color: #2E7D32; margin: 0 0 .2rem 0;}
  div[data-testid="stMarkdownContainer"] p.prod {font-size: 1.7rem !important; font-weight: 800;
      line-height: 1.2; margin: 0 0 .4rem 0;}
  .pausa {background:#FFF3E0; border-radius:14px; padding:1rem; text-align:center;
          font-size:1.3rem; font-weight:700; color:#E65100; margin-bottom:.8rem;}
</style>
""",
    unsafe_allow_html=True,
)

ss = st.session_state


# ------------------------------------------------------------ conexiones
def _gspread_client():
    import gspread
    from google.auth.transport.requests import Request

    if "gcp_oauth" in st.secrets:
        from google.oauth2.credentials import Credentials

        o = st.secrets["gcp_oauth"]
        creds = Credentials(
            token=None, refresh_token=o["refresh_token"],
            token_uri=o.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=o["client_id"], client_secret=o["client_secret"], scopes=SCOPES,
        )
        creds.refresh(Request())
        return gspread.authorize(creds)
    if "gcp_service_account" in st.secrets:
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]),
                                                      scopes=SCOPES)
        return gspread.authorize(creds)
    return None


def _tiene_credenciales() -> bool:
    try:
        return "gcp_oauth" in st.secrets or "gcp_service_account" in st.secrets
    except Exception:  # no hay secrets.toml
        return False


def _cfg(clave: str, defecto=None):
    try:
        return st.secrets.get("app", {}).get(clave, defecto)
    except Exception:
        return defecto


@st.cache_resource(show_spinner="Conectando con Google Sheets…")
def get_storage():
    if not _tiene_credenciales():
        return MemoryStorage()
    return SheetsStorage(
        _gspread_client(), _cfg("sheet_id", SHEET_ID), _cfg("titulo_hoja", TITULO_HOJA),
        _cfg("folder_id", INTEGRACION_AI_FOLDER),
    )


@st.cache_data(ttl=600, show_spinner=False)
def get_catalogo() -> tuple[list[dict], str]:
    """Productos = columna 'descripcion' de la hoja de precios World Office."""
    if _tiene_credenciales():
        try:
            gc = _gspread_client()
            sh = gc.open_by_key(_cfg("productos_sheet_id", PRODUCTOS_SHEET_ID))
            ws = sh.get_worksheet_by_id(int(_cfg("productos_gid", PRODUCTOS_GID)))
            filas = ws.get_all_records()
            filas = [{str(k).strip().lower(): v for k, v in f.items()} for f in filas]
            cat = L.construir_catalogo(filas)
            if cat:
                return cat, "google"
        except Exception as e:  # sigue con el respaldo
            print("No se pudo leer el catalogo de productos:", e)
    with open(RESPALDO_CSV, encoding="utf-8") as f:
        return L.construir_catalogo(list(csv.DictReader(f))), "respaldo"


# ------------------------------------------------------------ estado / eventos
def estado() -> L.EstadoTurno:
    return L.reproducir(ss.get("eventos", []))


def registrar(evento: str, lote_id: str = "", producto: str = "",
              peso: int | None = None, ref: str = "") -> bool:
    """Guarda un evento en la hoja. Solo si se guardo, lo agrega al estado local."""
    e = L.Evento(L.short_id(), L.now(), ss.fecha, ss.sid, lote_id, producto, evento, peso, ref)
    try:
        get_storage().append_eventos([e])
    except Exception as ex:
        st.error("⚠️ No se pudo guardar. Revise el internet y vuelva a intentar.\n\n"
                 f"Detalle: {ex}")
        return False
    ss.eventos.append(e)
    return True


def cargar_turno(sid: str) -> bool:
    eventos = get_storage().leer_eventos(sid)
    if not eventos:
        return False
    ss.sid = sid
    ss.fecha = eventos[0].fecha_turno
    ss.eventos = eventos
    st.query_params["turno"] = sid
    sincronizar_lotes()
    return True


def sincronizar_lotes():
    """Si algun lote terminado no quedo en la pestaña Lotes (p.ej. se cayo el
    internet justo al terminar), se escribe ahora."""
    est = estado()
    if not est.lotes_terminados:
        return
    try:
        stg = get_storage()
        ya = stg.lote_ids(ss.sid)
        for lote in est.lotes_terminados:
            if lote.lote_id not in ya:
                stg.append_lote(L.fila_lote(lote, ss.sid, ss.fecha))
    except Exception as ex:
        st.warning(f"No se pudieron sincronizar los lotes (se reintentará): {ex}")


def salir_del_turno():
    for k in ("sid", "fecha", "eventos", "producto_sel", "cerrando", "confirmar_fin"):
        ss.pop(k, None)
    st.query_params.clear()


# ------------------------------------------------------------ PIN opcional
pin = _cfg("pin")
if pin and not ss.get("pin_ok"):
    st.title("🥬 Track Operación")
    with st.form("pin"):
        v = st.text_input("PIN", type="password")
        if st.form_submit_button("Entrar", type="primary", width="stretch"):
            if str(v).strip() == str(pin):
                ss.pin_ok = True
                st.rerun()
            st.error("PIN incorrecto")
    st.stop()

# Retomar el turno que venga en la URL (?turno=...) tras una recarga
qp_turno = st.query_params.get("turno")
if qp_turno and ss.get("sid") != qp_turno:
    with st.spinner("Recuperando turno…"):
        if not cargar_turno(qp_turno):
            st.query_params.clear()

if not _tiene_credenciales():
    st.info("🧪 **Modo demo**: no hay credenciales de Google configuradas; los datos "
            "no se guardan en Drive.", icon="ℹ️")


# ============================================================ PANTALLAS
def pantalla_inicio():
    st.title("🥬 Track Operación")
    st.subheader("Nuevo turno")
    fecha = st.date_input("Fecha del turno", value=L.today(), format="DD/MM/YYYY")
    if st.button("▶  Iniciar turno", type="primary", width="stretch"):
        t = L.now()
        ss.sid = L.new_id("T", t)
        ss.fecha = fecha.isoformat()
        ss.eventos = []
        try:
            get_storage().crear_sesion(ss.sid, ss.fecha, L.fmt_ts(t))
        except Exception as ex:
            st.error(f"⚠️ No se pudo crear el turno. Revise el internet.\n\n{ex}")
            salir_del_turno()
            return
        if registrar(L.SESION_INICIO):
            st.query_params["turno"] = ss.sid
            st.rerun()

    try:
        abiertas = get_storage().sesiones_abiertas()
    except Exception as ex:
        abiertas = []
        st.warning(f"No se pudieron leer los turnos abiertos: {ex}")
    if abiertas:
        st.divider()
        st.subheader("Turnos sin terminar")
        st.caption("Si se cerró la app o se cambió de celular, retome aquí.")
        for s in sorted(abiertas, key=lambda d: str(d["Inicio"]), reverse=True):
            hora = str(s["Inicio"])[11:16]
            if st.button(f"↩  Retomar turno {s['Fecha turno']} (inició {hora})",
                         key=f"ret_{s['Sesion ID']}", width="stretch"):
                with st.spinner("Recuperando turno…"):
                    ok = cargar_turno(s["Sesion ID"])
                if ok:
                    st.rerun()
                st.error("Ese turno no tiene registros; inicie uno nuevo.")


def encabezado_turno(est: L.EstadoTurno):
    n = len(est.lotes_terminados)
    st.caption(f"Turno {ss.fecha} · {n} lote{'s' if n != 1 else ''} terminado{'s' if n != 1 else ''}")


def tabla_lotes(lotes: list[L.Lote]):
    filas = []
    for l in lotes:
        m = L.metricas_lote(l)
        filas.append({
            "Producto": l.producto,
            "Entrada": L.fmt_g(m["peso_inicial"]),
            "Salida": L.fmt_g(m["peso_final"]),
            "Rend.": f"{m['rendimiento']:.1f} %" if m["rendimiento"] is not None else "–",
            "Tiempo": L.fmt_min(m["min_neto"]),
        })
    st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")


def pantalla_productos(est: L.EstadoTurno):
    encabezado_turno(est)
    sel = ss.get("producto_sel")
    if sel:
        st.markdown('<p class="fase">Producto elegido</p>', unsafe_allow_html=True)
        st.markdown(f'<p class="prod">{sel["producto"]}</p>', unsafe_allow_html=True)
        st.write("Cuando tenga el lote listo para pesar, oprima **Iniciar lote**. "
                 "Desde ese momento empieza a contar el tiempo.")
        if st.button("▶  Iniciar lote", type="primary", width="stretch"):
            lote_id = L.new_id("L")
            if registrar(L.LOTE_INICIO, lote_id, sel["producto"], ref=sel["codigos"]):
                ss.pop("producto_sel", None)
                st.rerun()
        if st.button("←  Cambiar producto", width="stretch"):
            ss.pop("producto_sel", None)
            st.rerun()
        return

    st.header("¿Qué producto va a procesar?")
    catalogo, fuente = get_catalogo()
    if fuente == "respaldo" and _tiene_credenciales():
        st.warning("No se pudo leer la lista de productos de Google; se usa la lista guardada.")
    texto = st.text_input("Buscar", placeholder="Escriba parte del nombre, ej: romana")
    lista = L.filtrar(catalogo, texto)

    # los productos ya usados en este turno van primero
    usados = []
    for l in reversed(est.lotes_terminados):
        if l.producto not in usados:
            usados.append(l.producto)
    if usados and not texto:
        st.caption("Usados en este turno")
        por_nombre = {c["producto"]: c for c in catalogo}
        for p in usados[:4]:
            c = por_nombre.get(p, {"producto": p, "codigos": ""})
            if st.button(f"🔁  {p}", key=f"u_{p}", width="stretch"):
                ss.producto_sel = c
                st.rerun()
        st.caption("Todos los productos")

    for c in lista:
        if st.button(c["producto"], key=f"p_{c['producto']}", width="stretch"):
            ss.producto_sel = c
            st.rerun()
    if not lista:
        st.info("No hay productos con ese nombre.")

    with st.expander("➕ Otro producto (no está en la lista)"):
        otro = st.text_input("Nombre del producto", key="otro_prod")
        if st.button("Usar este producto", disabled=not otro.strip(), width="stretch"):
            ss.producto_sel = {"producto": otro.strip(), "codigos": ""}
            st.rerun()

    st.divider()
    if est.lotes_terminados:
        st.subheader("Lotes de este turno")
        tabla_lotes(est.lotes_terminados)
    if st.button("🏁  Terminar turno", width="stretch"):
        ss.cerrando = True
        st.rerun()


def lista_pesadas(pesadas: list[L.Pesada], fase: str, lote: L.Lote):
    total = sum(p.gramos for p in pesadas)
    c1, c2 = st.columns(2)
    c1.metric("Pesadas", len(pesadas))
    c2.metric("Total", L.fmt_g(total))
    if pesadas:
        ultimas = list(reversed(pesadas))[:6]
        st.caption("Últimas: " + " · ".join(
            f"{p.ts:%H:%M} → {L.fmt_g(p.gramos)}" for p in ultimas))
        if st.button(f"↩  Deshacer última ({L.fmt_g(pesadas[-1].gramos)})", key=f"undo_{fase}", width="stretch"):
            if registrar(L.ANULAR, lote.lote_id, lote.producto, ref=pesadas[-1].registro_id):
                st.rerun()


def form_peso(evento: str, lote: L.Lote, n: int):
    with st.form(f"peso_{evento}_{n}", clear_on_submit=True):
        g = st.number_input("Peso en gramos", min_value=0, max_value=PESO_MAX_G,
                            value=None, step=1, format="%d", placeholder="0")
        if st.form_submit_button("➕  Registrar peso", type="primary", width="stretch"):
            if not g or g <= 0:
                st.error("Escriba el peso en gramos.")
            elif registrar(evento, lote.lote_id, lote.producto, peso=int(g)):
                st.toast(f"✅ {L.fmt_g(g)} registrado")
                st.rerun()


def pantalla_lote(est: L.EstadoTurno):
    lote = est.lote_actual
    encabezado_turno(est)
    fase = lote.fase
    pasos = {L.FASE_PESAJE_INICIAL: "Paso 1 de 3 · Pesar producto crudo (entrada)",
             L.FASE_PROCESO: "Paso 2 de 3 · Procesar (deshojar, cortar…)",
             L.FASE_PESAJE_FINAL: "Paso 3 de 3 · Pesar producto procesado (salida)"}
    st.markdown(f'<p class="fase">{pasos[fase]}</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="prod">{lote.producto}</p>', unsafe_allow_html=True)
    st.caption(f"Lote iniciado a las {lote.t_inicio:%H:%M}")

    if lote.en_pausa:
        st.markdown(f'<div class="pausa">⏸ En pausa desde las {lote.pausas[-1][0]:%H:%M}<br>'
                    '<small>El tiempo de pausa no cuenta</small></div>', unsafe_allow_html=True)
        if st.button("▶  Reanudar", type="primary", width="stretch"):
            if registrar(L.REANUDA, lote.lote_id, lote.producto):
                st.rerun()
        return

    if fase == L.FASE_PESAJE_INICIAL:
        form_peso(L.PESO_INICIAL, lote, len(lote.pesos_inicial))
        lista_pesadas(lote.pesos_inicial, fase, lote)
        st.divider()
        if st.button("✅  Terminé de pesar: empezar a procesar",
                     disabled=not lote.pesos_inicial, width="stretch"):
            if registrar(L.FIN_PESAJE_INICIAL, lote.lote_id, lote.producto):
                st.rerun()

    elif fase == L.FASE_PROCESO:
        c1, c2 = st.columns(2)
        c1.metric("Entrada", L.fmt_g(lote.total_inicial))
        c2.metric("Procesando desde", f"{lote.t_fin_pesaje_inicial:%H:%M}")
        st.caption(f"Tiempo de proceso hasta ahora: {L.fmt_min(L.min_proceso_hasta_ahora(lote))} "
                   "(se actualiza al tocar un botón)")
        if st.button("✅  Terminé de procesar: pesar producto final", type="primary", width="stretch"):
            if registrar(L.FIN_PROCESO, lote.lote_id, lote.producto):
                st.rerun()
        if st.button("🔄  Actualizar tiempo", width="stretch"):
            st.rerun()

    else:  # pesaje final
        form_peso(L.PESO_FINAL, lote, len(lote.pesos_final))
        lista_pesadas(lote.pesos_final, fase, lote)
        ini, fin = lote.total_inicial, lote.total_final
        if lote.pesos_final and ini:
            st.caption(f"Entrada {L.fmt_g(ini)} → salida {L.fmt_g(fin)} · "
                       f"rendimiento {fin / ini * 100:.1f} %")
        st.divider()
        if fin > ini and not ss.get("confirmar_fin"):
            if st.button("🏁  Terminar lote", disabled=not lote.pesos_final, width="stretch"):
                ss.confirmar_fin = True
                st.rerun()
        else:
            if ss.get("confirmar_fin"):
                st.warning(f"⚠️ La salida ({L.fmt_g(fin)}) pesa MÁS que la entrada "
                           f"({L.fmt_g(ini)}). Revise los pesos. ¿Terminar de todas formas?")
            if st.button("🏁  Terminar lote", type="primary", disabled=not lote.pesos_final, width="stretch"):
                if registrar(L.LOTE_FIN, lote.lote_id, lote.producto):
                    ss.pop("confirmar_fin", None)
                    terminado = estado().lotes_terminados[-1]
                    try:
                        get_storage().append_lote(L.fila_lote(terminado, ss.sid, ss.fecha))
                    except Exception as ex:
                        st.warning(f"El lote quedó registrado; el resumen se sincronizará luego ({ex}).")
                    m = L.metricas_lote(terminado)
                    st.toast(f"✅ Lote guardado · rendimiento {m['rendimiento']:.1f} % · "
                             f"{L.fmt_min(m['min_neto'])}")
                    st.rerun()

    st.divider()
    if st.button("⏸  Pausa (almuerzo, descanso…)", width="stretch"):
        if registrar(L.PAUSA, lote.lote_id, lote.producto):
            st.rerun()
    if fase == L.FASE_PESAJE_INICIAL:
        with st.expander("🗑  Descartar este lote (me equivoqué de producto)"):
            st.write("Se borra el lote actual y vuelve a la lista de productos.")
            if st.button("Sí, descartar lote", width="stretch"):
                if registrar(L.LOTE_DESCARTADO, lote.lote_id, lote.producto):
                    st.rerun()


def pantalla_cierre(est: L.EstadoTurno):
    st.header("🏁 Terminar turno")
    if not est.lotes_terminados:
        st.info("Este turno no tiene lotes terminados.")
    else:
        tabla_lotes(est.lotes_terminados)
        ini = sum(l.total_inicial for l in est.lotes_terminados)
        fin = sum(l.total_final for l in est.lotes_terminados)
        c1, c2 = st.columns(2)
        c1.metric("Entrada total", L.fmt_g(ini))
        c2.metric("Salida total", L.fmt_g(fin))
    st.write("Revise los datos. Al confirmar, el turno queda cerrado en la hoja de Google.")
    if st.button("✅  Confirmar y cerrar turno", type="primary", width="stretch"):
        with st.spinner("Enviando a Google Sheets…"):
            sincronizar_lotes()
            if registrar(L.SESION_FIN):
                stg = get_storage()
                try:
                    stg.marcar_lotes(ss.sid, "Cerrado")
                    stg.cerrar_sesion(
                        ss.sid, L.fmt_ts(L.now()), len(est.lotes_terminados),
                        sum(l.total_inicial for l in est.lotes_terminados),
                        sum(l.total_final for l in est.lotes_terminados))
                    stg.escribir_resumen(L.calcular_resumen(stg.leer_lotes()))
                except Exception as ex:
                    st.warning(f"El turno se cerró pero no se actualizó el resumen: {ex}")
                ss.pop("cerrando", None)
                st.rerun()
    if st.button("←  Volver", width="stretch"):
        ss.pop("cerrando", None)
        st.rerun()


def pantalla_cerrado(est: L.EstadoTurno):
    st.success(f"✅ Turno {ss.fecha} cerrado y guardado.")
    if est.lotes_terminados:
        tabla_lotes(est.lotes_terminados)
    url = get_storage().url
    if url:
        st.link_button("📊  Ver hoja en Google Drive", url, width="stretch")
    if st.button("▶  Empezar un turno nuevo", type="primary", width="stretch"):
        salir_del_turno()
        st.rerun()


# ============================================================ router
if not ss.get("sid"):
    pantalla_inicio()
else:
    est = estado()
    if est.cerrado:
        pantalla_cerrado(est)
    elif est.lote_actual is not None:
        pantalla_lote(est)
    elif ss.get("cerrando"):
        pantalla_cierre(est)
    else:
        pantalla_productos(est)
