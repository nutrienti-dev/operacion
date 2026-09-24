"""Persistencia: Google Sheets (produccion) o memoria (modo demo / pruebas).

Hoja acumulativa "Nutrienti - Track Operacion" con 4 pestañas:
  - Registros : bitacora de eventos (cada pesada, inicio/fin, pausas...).
                Es la fuente de verdad; con ella se retoma un turno.
  - Lotes     : una fila por lote terminado, con pesos, tiempos y merma.
  - Sesiones  : una fila por turno (abierto / cerrado).
  - Resumen   : promedios por producto (se recalcula al cerrar cada turno).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import logic as L

TAB_REGISTROS = "Registros"
TAB_LOTES = "Lotes"
TAB_SESIONES = "Sesiones"
TAB_RESUMEN = "Resumen"

HEADERS = {
    TAB_REGISTROS: L.REGISTROS_HEADERS,
    TAB_LOTES: L.LOTES_HEADERS,
    TAB_SESIONES: L.SESIONES_HEADERS,
    TAB_RESUMEN: L.RESUMEN_HEADERS,
}


def _serial_a_fecha(v) -> str:
    """Numero de serie de Sheets (dias desde 1899-12-30) -> 'YYYY-MM-DD'."""
    if isinstance(v, (int, float)):
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).strftime("%Y-%m-%d")
    return str(v)


def _serial_a_ts(v) -> str:
    if isinstance(v, (int, float)):
        dt = datetime(1899, 12, 30) + timedelta(days=float(v))
        return L.fmt_ts(dt + timedelta(microseconds=500_000))  # redondeo
    return str(v)


class Storage:
    """Interfaz comun."""

    url: str = ""

    # --- eventos
    def append_eventos(self, eventos: list[L.Evento]) -> None: ...
    def leer_eventos(self, sesion_id: str) -> list[L.Evento]: ...
    # --- sesiones
    def crear_sesion(self, sesion_id: str, fecha: str, inicio: str) -> None: ...
    def sesiones_abiertas(self) -> list[dict]: ...
    def cerrar_sesion(self, sesion_id: str, fin: str, n_lotes: int,
                      ini_g: int, fin_g: int) -> None: ...
    # --- lotes
    def append_lote(self, fila: list) -> None: ...
    def lote_ids(self, sesion_id: str) -> set[str]: ...
    def leer_lotes(self) -> list[dict]: ...
    def marcar_lotes(self, sesion_id: str, estado: str) -> None: ...
    # --- resumen
    def escribir_resumen(self, filas: list[list]) -> None: ...


# ======================================================================
class MemoryStorage(Storage):
    def __init__(self):
        self.tabs = {k: [list(v)] for k, v in HEADERS.items()}
        self.url = ""

    def _rows(self, tab):
        return self.tabs[tab][1:]

    def _dicts(self, tab):
        h = self.tabs[tab][0]
        return [dict(zip(h, r)) for r in self._rows(tab)]

    def append_eventos(self, eventos):
        self.tabs[TAB_REGISTROS].extend(e.to_row() for e in eventos)

    def leer_eventos(self, sesion_id):
        return [L.Evento.from_row(r) for r in self._rows(TAB_REGISTROS) if r[3] == sesion_id]

    def crear_sesion(self, sesion_id, fecha, inicio):
        self.tabs[TAB_SESIONES].append([sesion_id, fecha, inicio, "", "Abierta", 0, 0, 0])

    def sesiones_abiertas(self):
        return [d for d in self._dicts(TAB_SESIONES) if d["Estado"] == "Abierta"]

    def cerrar_sesion(self, sesion_id, fin, n_lotes, ini_g, fin_g):
        for r in self._rows(TAB_SESIONES):
            if r[0] == sesion_id:
                r[3:8] = [fin, "Cerrada", n_lotes, ini_g, fin_g]

    def append_lote(self, fila):
        self.tabs[TAB_LOTES].append(list(fila))

    def lote_ids(self, sesion_id):
        return {r[0] for r in self._rows(TAB_LOTES) if r[1] == sesion_id}

    def leer_lotes(self):
        return self._dicts(TAB_LOTES)

    def marcar_lotes(self, sesion_id, estado):
        i = L.LOTES_HEADERS.index("Estado turno")
        for r in self._rows(TAB_LOTES):
            if r[1] == sesion_id:
                r[i] = estado

    def escribir_resumen(self, filas):
        self.tabs[TAB_RESUMEN] = [list(L.RESUMEN_HEADERS)] + [list(f) for f in filas]


# ======================================================================
class SheetsStorage(Storage):
    """Google Sheets via gspread.

    - Registros se escribe en RAW (texto tal cual) para que la reconstruccion
      del turno no dependa de la configuracion regional de la hoja.
    - Lotes / Sesiones / Resumen se escriben en USER_ENTERED para que fechas y
      horas queden como fechas reales (se pueden filtrar y graficar).
    """

    def __init__(self, gc, spreadsheet_id: str | None, titulo: str, folder_id: str | None):
        import gspread  # noqa: F401  (solo para dejar claro que se necesita)

        if spreadsheet_id:
            self.sh = gc.open_by_key(spreadsheet_id)
        else:
            try:
                self.sh = gc.open(titulo, folder_id=folder_id)
            except Exception:  # SpreadsheetNotFound
                self.sh = gc.create(titulo, folder_id=folder_id)
        self.url = self.sh.url
        self.ws = {}
        existentes = {w.title: w for w in self.sh.worksheets()}
        for tab, headers in HEADERS.items():
            ws = existentes.get(tab)
            if ws is None:
                ws = self.sh.add_worksheet(tab, rows=1000, cols=max(len(headers), 10))
            primera = ws.row_values(1)
            if primera[: len(headers)] != headers:
                ws.update([headers], "A1", value_input_option="RAW")
                ws.freeze(rows=1)
            self.ws[tab] = ws
        # quitar la "Hoja 1"/"Sheet1" vacia que trae una hoja nueva
        for t, w in existentes.items():
            if t in ("Sheet1", "Hoja 1", "Hoja1"):
                try:
                    if not any(any(c for c in r) for r in w.get_all_values()):
                        self.sh.del_worksheet(w)
                except Exception:
                    pass

    # --- eventos
    def append_eventos(self, eventos):
        self.ws[TAB_REGISTROS].append_rows(
            [e.to_row() for e in eventos], value_input_option="RAW",
            insert_data_option="INSERT_ROWS", table_range="A1",
        )

    def leer_eventos(self, sesion_id):
        filas = self.ws[TAB_REGISTROS].get_all_values()[1:]
        return [L.Evento.from_row(r) for r in filas if len(r) > 3 and r[3] == sesion_id]

    # --- sesiones
    def crear_sesion(self, sesion_id, fecha, inicio):
        self.ws[TAB_SESIONES].append_rows(
            [[sesion_id, fecha, inicio, "", "Abierta", 0, 0, 0]],
            value_input_option="USER_ENTERED", insert_data_option="INSERT_ROWS",
            table_range="A1",
        )

    def _sesiones(self):
        vals = self.ws[TAB_SESIONES].get_all_values(value_render_option="UNFORMATTED_VALUE")
        out = []
        for i, r in enumerate(vals[1:], start=2):
            d = dict(zip(L.SESIONES_HEADERS, list(r) + [""] * 8))
            d["Fecha turno"] = _serial_a_fecha(d["Fecha turno"])
            d["Inicio"] = _serial_a_ts(d["Inicio"])
            d["_row"] = i
            out.append(d)
        return out

    def sesiones_abiertas(self):
        return [d for d in self._sesiones() if d["Estado"] == "Abierta"]

    def cerrar_sesion(self, sesion_id, fin, n_lotes, ini_g, fin_g):
        for d in self._sesiones():
            if d["Sesion ID"] == sesion_id:
                self.ws[TAB_SESIONES].update(
                    [[fin, "Cerrada", n_lotes, ini_g, fin_g]], f"D{d['_row']}:H{d['_row']}",
                    value_input_option="USER_ENTERED",
                )

    # --- lotes
    def append_lote(self, fila):
        self.ws[TAB_LOTES].append_rows(
            [fila], value_input_option="USER_ENTERED",
            insert_data_option="INSERT_ROWS", table_range="A1",
        )

    def lote_ids(self, sesion_id):
        vals = self.ws[TAB_LOTES].get("A2:B")
        return {r[0] for r in vals if len(r) > 1 and r[1] == sesion_id}

    def leer_lotes(self):
        vals = self.ws[TAB_LOTES].get_all_values(value_render_option="UNFORMATTED_VALUE")
        out = []
        for r in vals[1:]:
            d = dict(zip(L.LOTES_HEADERS, list(r) + [""] * len(L.LOTES_HEADERS)))
            d["Fecha turno"] = _serial_a_fecha(d["Fecha turno"])
            out.append(d)
        return out

    def marcar_lotes(self, sesion_id, estado):
        ws = self.ws[TAB_LOTES]
        col = L.LOTES_HEADERS.index("Estado turno") + 1
        letra = chr(ord("A") + col - 1)
        ids = ws.col_values(2)
        updates = [
            {"range": f"{letra}{i}", "values": [[estado]]}
            for i, v in enumerate(ids, start=1) if i > 1 and v == sesion_id
        ]
        if updates:
            ws.batch_update(updates, value_input_option="RAW")

    # --- resumen
    def escribir_resumen(self, filas):
        ws = self.ws[TAB_RESUMEN]
        ws.clear()
        ws.update([L.RESUMEN_HEADERS] + filas, "A1", value_input_option="USER_ENTERED")
        ws.freeze(rows=1)
