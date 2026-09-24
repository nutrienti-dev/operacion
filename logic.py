"""Logica pura (sin Streamlit ni Google): tiempos, eventos, metricas, productos.

Todo el estado de un turno se reconstruye "reproduciendo" la lista de eventos
guardados en la pestaña `Registros`. Asi, si el celular se recarga o la app se
reinicia, basta con volver a leer los eventos para retomar donde se iba.
"""
from __future__ import annotations

import re
import secrets
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, date
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Bogota")
TS_FMT = "%Y-%m-%d %H:%M:%S"

# ---------------------------------------------------------------- eventos
SESION_INICIO = "SESION_INICIO"
SESION_FIN = "SESION_FIN"
LOTE_INICIO = "LOTE_INICIO"
PESO_INICIAL = "PESO_INICIAL"
FIN_PESAJE_INICIAL = "FIN_PESAJE_INICIAL"
FIN_PROCESO = "FIN_PROCESO"
PESO_FINAL = "PESO_FINAL"
LOTE_FIN = "LOTE_FIN"
LOTE_DESCARTADO = "LOTE_DESCARTADO"
PAUSA = "PAUSA"
REANUDA = "REANUDA"
ANULAR = "ANULAR"

# Fases de un lote (por tandas: se pesa todo crudo, se procesa, se pesa todo)
FASE_PESAJE_INICIAL = "pesaje_inicial"
FASE_PROCESO = "proceso"
FASE_PESAJE_FINAL = "pesaje_final"

REGISTROS_HEADERS = [
    "Registro ID", "Timestamp", "Fecha turno", "Sesion ID", "Lote ID",
    "Producto", "Evento", "Peso (g)", "Ref",
]

LOTES_HEADERS = [
    "Lote ID", "Sesion ID", "Fecha turno", "Producto", "Codigo(s)",
    "Hora inicio", "Hora fin",
    "Min pesaje inicial", "Min proceso", "Min pesaje final", "Min pausa",
    "Min total neto",
    "N pesadas inicial", "Peso inicial (g)", "N pesadas final", "Peso final (g)",
    "Rendimiento %", "Merma (g)", "Merma %", "Kg/hora (entrada)",
    "Min por kg (entrada)", "Estado turno",
]

SESIONES_HEADERS = [
    "Sesion ID", "Fecha turno", "Inicio", "Fin", "Estado", "N lotes",
    "Peso inicial total (g)", "Peso final total (g)",
]

RESUMEN_HEADERS = [
    "Producto", "N lotes", "Kg entrada", "Kg salida", "Rendimiento % (ponderado)",
    "Merma % (ponderada)", "Horas netas", "Kg/hora (entrada)",
    "Min por kg (entrada)", "Min proceso promedio por lote",
    "Primer turno", "Ultimo turno",
]


def now() -> datetime:
    """Hora actual de Bogota, sin tzinfo (para guardar/restar facilmente)."""
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


def today() -> date:
    return now().date()


def fmt_ts(dt: datetime) -> str:
    return dt.strftime(TS_FMT)


def parse_ts(s: str) -> datetime:
    return datetime.strptime(s.strip(), TS_FMT)


def new_id(prefix: str, dt: datetime | None = None) -> str:
    dt = dt or now()
    return f"{prefix}-{dt:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def short_id() -> str:
    return secrets.token_hex(4)


@dataclass
class Evento:
    registro_id: str
    ts: datetime
    fecha_turno: str
    sesion_id: str
    lote_id: str
    producto: str
    evento: str
    peso: int | None = None
    ref: str = ""

    def to_row(self) -> list:
        return [
            self.registro_id, fmt_ts(self.ts), self.fecha_turno, self.sesion_id,
            self.lote_id, self.producto, self.evento,
            "" if self.peso is None else int(self.peso), self.ref,
        ]

    @classmethod
    def from_row(cls, row: list) -> "Evento":
        row = list(row) + [""] * (len(REGISTROS_HEADERS) - len(row))
        peso = str(row[7]).strip()
        return cls(
            registro_id=str(row[0]), ts=parse_ts(str(row[1])),
            fecha_turno=str(row[2]), sesion_id=str(row[3]), lote_id=str(row[4]),
            producto=str(row[5]), evento=str(row[6]),
            peso=int(float(peso)) if peso else None, ref=str(row[8]),
        )


# ---------------------------------------------------------------- estado
@dataclass
class Pesada:
    registro_id: str
    ts: datetime
    gramos: int


@dataclass
class Lote:
    lote_id: str
    producto: str
    codigos: str
    t_inicio: datetime
    t_fin_pesaje_inicial: datetime | None = None
    t_fin_proceso: datetime | None = None
    t_fin: datetime | None = None
    pesos_inicial: list[Pesada] = field(default_factory=list)
    pesos_final: list[Pesada] = field(default_factory=list)
    pausas: list[list] = field(default_factory=list)  # [[inicio, fin|None], ...]

    @property
    def fase(self) -> str:
        if self.t_fin_pesaje_inicial is None:
            return FASE_PESAJE_INICIAL
        if self.t_fin_proceso is None:
            return FASE_PROCESO
        return FASE_PESAJE_FINAL

    @property
    def en_pausa(self) -> bool:
        return bool(self.pausas) and self.pausas[-1][1] is None

    @property
    def total_inicial(self) -> int:
        return sum(p.gramos for p in self.pesos_inicial)

    @property
    def total_final(self) -> int:
        return sum(p.gramos for p in self.pesos_final)

    def pesadas_fase_actual(self) -> list[Pesada]:
        if self.fase == FASE_PESAJE_INICIAL:
            return self.pesos_inicial
        if self.fase == FASE_PESAJE_FINAL:
            return self.pesos_final
        return []


@dataclass
class EstadoTurno:
    sesion_id: str
    fecha_turno: str
    t_inicio: datetime | None
    cerrado: bool
    lotes_terminados: list[Lote]
    lote_actual: Lote | None


def reproducir(eventos: list[Evento]) -> EstadoTurno:
    """Reconstruye el estado de un turno a partir de sus eventos."""
    eventos = sorted(eventos, key=lambda e: e.ts)  # sort estable
    anulados = {e.ref for e in eventos if e.evento == ANULAR}
    sesion_id = eventos[0].sesion_id if eventos else ""
    fecha = eventos[0].fecha_turno if eventos else ""
    t_inicio = None
    cerrado = False
    terminados: list[Lote] = []
    actual: Lote | None = None

    for e in eventos:
        if e.registro_id in anulados:
            continue
        ev = e.evento
        if ev == SESION_INICIO:
            t_inicio = e.ts
        elif ev == SESION_FIN:
            cerrado = True
        elif ev == LOTE_INICIO:
            actual = Lote(e.lote_id, e.producto, e.ref, e.ts)
        elif actual is None or e.lote_id != actual.lote_id:
            continue
        elif ev == PESO_INICIAL:
            actual.pesos_inicial.append(Pesada(e.registro_id, e.ts, e.peso or 0))
        elif ev == PESO_FINAL:
            actual.pesos_final.append(Pesada(e.registro_id, e.ts, e.peso or 0))
        elif ev == FIN_PESAJE_INICIAL:
            actual.t_fin_pesaje_inicial = e.ts
        elif ev == FIN_PROCESO:
            actual.t_fin_proceso = e.ts
        elif ev == PAUSA:
            if not actual.en_pausa:
                actual.pausas.append([e.ts, None])
        elif ev == REANUDA:
            if actual.en_pausa:
                actual.pausas[-1][1] = e.ts
        elif ev == LOTE_FIN:
            if actual.en_pausa:
                actual.pausas[-1][1] = e.ts
            actual.t_fin = e.ts
            terminados.append(actual)
            actual = None
        elif ev == LOTE_DESCARTADO:
            actual = None

    return EstadoTurno(sesion_id, fecha, t_inicio, cerrado, terminados, actual)


# ---------------------------------------------------------------- metricas
def _overlap_s(a0, a1, b0, b1) -> float:
    if a0 is None or a1 is None or b0 is None or b1 is None:
        return 0.0
    return max(0.0, (min(a1, b1) - max(a0, b0)).total_seconds())


def _min_neto(t0, t1, pausas) -> float:
    if t0 is None or t1 is None:
        return 0.0
    bruto = (t1 - t0).total_seconds()
    pausa = sum(_overlap_s(t0, t1, p0, p1) for p0, p1 in pausas)
    return max(0.0, bruto - pausa) / 60


def metricas_lote(l: Lote) -> dict:
    fin = l.t_fin or now()
    pausas = [(p0, p1 or fin) for p0, p1 in l.pausas]
    min_pi = _min_neto(l.t_inicio, l.t_fin_pesaje_inicial, pausas)
    min_pr = _min_neto(l.t_fin_pesaje_inicial, l.t_fin_proceso, pausas)
    min_pf = _min_neto(l.t_fin_proceso, fin, pausas) if l.t_fin_proceso else 0.0
    min_pausa = sum(_overlap_s(l.t_inicio, fin, p0, p1) for p0, p1 in pausas) / 60
    min_neto = _min_neto(l.t_inicio, fin, pausas)
    ini, fi = l.total_inicial, l.total_final
    rend = (fi / ini * 100) if ini else None
    merma = ini - fi
    merma_pct = (merma / ini * 100) if ini else None
    kg_h = (ini / 1000) / (min_neto / 60) if min_neto > 0 else None
    min_kg = min_neto / (ini / 1000) if ini else None
    return {
        "min_pesaje_inicial": round(min_pi, 2),
        "min_proceso": round(min_pr, 2),
        "min_pesaje_final": round(min_pf, 2),
        "min_pausa": round(min_pausa, 2),
        "min_neto": round(min_neto, 2),
        "n_inicial": len(l.pesos_inicial),
        "peso_inicial": ini,
        "n_final": len(l.pesos_final),
        "peso_final": fi,
        "rendimiento": None if rend is None else round(rend, 2),
        "merma": merma,
        "merma_pct": None if merma_pct is None else round(merma_pct, 2),
        "kg_h": None if kg_h is None else round(kg_h, 2),
        "min_kg": None if min_kg is None else round(min_kg, 2),
    }


def min_proceso_hasta_ahora(l: Lote) -> float:
    """Minutos netos (sin pausas) desde que empezo el proceso hasta ahora."""
    t = now()
    pausas = [(p0, p1 or t) for p0, p1 in l.pausas]
    return _min_neto(l.t_fin_pesaje_inicial, l.t_fin_proceso or t, pausas)


def _blank(v):
    return "" if v is None else v


def fila_lote(l: Lote, sesion_id: str, fecha_turno: str, estado: str = "Abierto") -> list:
    m = metricas_lote(l)
    return [
        l.lote_id, sesion_id, fecha_turno, l.producto, l.codigos,
        fmt_ts(l.t_inicio), fmt_ts(l.t_fin) if l.t_fin else "",
        m["min_pesaje_inicial"], m["min_proceso"], m["min_pesaje_final"],
        m["min_pausa"], m["min_neto"],
        m["n_inicial"], m["peso_inicial"], m["n_final"], m["peso_final"],
        _blank(m["rendimiento"]), m["merma"], _blank(m["merma_pct"]),
        _blank(m["kg_h"]), _blank(m["min_kg"]), estado,
    ]


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def calcular_resumen(lotes_rows: list[dict]) -> list[list]:
    """Resumen por producto a partir de las filas de la pestaña Lotes."""
    grupos: dict[str, list[dict]] = {}
    for r in lotes_rows:
        p = str(r.get("Producto", "")).strip()
        if p:
            grupos.setdefault(p, []).append(r)
    out = []
    for prod in sorted(grupos, key=str.casefold):
        rs = grupos[prod]
        ini = sum(_num(r.get("Peso inicial (g)")) for r in rs)
        fin = sum(_num(r.get("Peso final (g)")) for r in rs)
        min_neto = sum(_num(r.get("Min total neto")) for r in rs)
        min_proc = sum(_num(r.get("Min proceso")) for r in rs)
        fechas = sorted(str(r.get("Fecha turno", "")) for r in rs if r.get("Fecha turno"))
        horas = min_neto / 60
        out.append([
            prod, len(rs), round(ini / 1000, 3), round(fin / 1000, 3),
            round(fin / ini * 100, 2) if ini else "",
            round((ini - fin) / ini * 100, 2) if ini else "",
            round(horas, 2),
            round((ini / 1000) / horas, 2) if horas else "",
            round(min_neto / (ini / 1000), 2) if ini else "",
            round(min_proc / len(rs), 2),
            fechas[0] if fechas else "", fechas[-1] if fechas else "",
        ])
    return out


# ---------------------------------------------------------------- productos
_SUFIJO_UNIDAD = re.compile(
    r"\s+(x|por)\s+(kilo|kilos|kg|unidad|unidades|und|un)\.?\s*$", re.IGNORECASE
)


def _clave(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().casefold()
    s = re.sub(r"\b(de|del)\b", " ", s)  # "Verde de Tierra" == "Verde Tierra"
    return re.sub(r"\s+", " ", s).strip()


def nombre_operativo(descripcion: str) -> str:
    """'Lechuga Romana x Kilo' -> 'Lechuga Romana' (la unidad de venta no
    importa para la operacion: se procesa la misma lechuga)."""
    d = re.sub(r"\s+", " ", str(descripcion)).strip()
    return _SUFIJO_UNIDAD.sub("", d).strip()


def construir_catalogo(filas: list[dict]) -> list[dict]:
    """filas con 'codigo' y 'descripcion' -> [{'producto','codigos'}] unicos.

    Agrupa variantes por unidad y mayusculas/tildes; conserva la escritura
    mas frecuente como nombre visible.
    """
    nombres: dict[str, Counter] = {}
    codigos: dict[str, set] = {}
    for f in filas:
        desc = str(f.get("descripcion", "")).strip()
        if not desc:
            continue
        nom = nombre_operativo(desc)
        k = _clave(nom)
        nombres.setdefault(k, Counter())[nom] += 1
        cod = str(f.get("codigo", "")).strip()
        if cod:
            codigos.setdefault(k, set()).add(cod)
    cat = []
    for k, cnt in nombres.items():
        visible = cnt.most_common(1)[0][0]
        visible = visible[0].upper() + visible[1:]
        cat.append({"producto": visible,
                    "codigos": "/".join(sorted(codigos.get(k, set())))})
    return sorted(cat, key=lambda c: _clave(c["producto"]))


def filtrar(catalogo: list[dict], texto: str) -> list[dict]:
    t = _clave(texto or "")
    if not t:
        return catalogo
    partes = t.split()
    return [c for c in catalogo if all(p in _clave(c["producto"]) for p in partes)]


def fmt_g(g: float) -> str:
    """1234 -> '1.234 g' (formato colombiano)."""
    return f"{int(round(g)):,} g".replace(",", ".")


def fmt_min(m: float) -> str:
    m = max(0, m)
    h, r = divmod(int(round(m)), 60)
    return f"{h} h {r:02d} min" if h else f"{r} min"
