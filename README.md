# Nutrienti — Track de Operación

App web (Streamlit) para que los operarios registren desde el celular, por
lote, **peso de entrada, tiempo de proceso y peso de salida**. El resultado es
una base de datos acumulativa de tiempos y mermas por producto en Google
Sheets.

## Flujo del operario

1. **Iniciar turno** (fecha de hoy por defecto).
2. Elegir el **producto** (botones grandes, con buscador).
3. **Iniciar lote** → empieza a contar el tiempo.
4. **Paso 1 – Pesar crudo**: registra cada pesada en gramos (por tandas).
   "Deshacer última" corrige errores. Al terminar: *Terminé de pesar*.
5. **Paso 2 – Procesar** (deshojar, cortar…). Al terminar: *Terminé de procesar*.
6. **Paso 3 – Pesar procesado**: registra las pesadas de salida.
   **Terminar lote** → el lote queda guardado en la hoja y vuelve a la lista.
7. Al final: **Terminar turno** → revisa la tabla y **Confirmar y cerrar turno**.

En cualquier paso hay **Pausa / Reanudar** (almuerzo, descanso): el tiempo en
pausa no cuenta. Si se equivocó de producto, en el paso 1 puede **descartar el
lote**.

### A prueba de caídas
Cada acción se guarda en el momento en la pestaña `Registros`. Si el celular
se recarga, se apaga la pantalla o se cae el internet, al volver a abrir la
app el turno sigue donde iba (el ID del turno viaja en la URL, `?turno=…`). Si
se abrió en otro celular, la pantalla de inicio muestra **Turnos sin
terminar** para retomarlos.

## Hoja de Google: "registro operacion" (carpeta Integracion AI)

ID `1KeIRNsTJY_7q07jnEo8VijIiYsti7JA7c84Ue9GngBM` (fijo en `app.py`, se puede cambiar con `[app] sheet_id` en secrets). La app crea sola las pestañas y encabezados la primera vez. Pestañas:

| Pestaña | Contenido |
|---|---|
| **Lotes** | Una fila por lote: fecha, producto, código(s), hora inicio/fin, minutos de pesaje inicial / proceso / pesaje final / pausa / total neto, # pesadas y peso inicial y final (g), **rendimiento %**, **merma (g y %)**, kg/hora, min por kg, estado del turno (Abierto/Cerrado). **Esta es la base para análisis.** |
| **Resumen** | Por producto: # lotes, kg entrada/salida, rendimiento y merma ponderados, horas, kg/hora, min/kg, min de proceso promedio. Se recalcula cada vez que se cierra un turno. |
| **Sesiones** | Una fila por turno (inicio, fin, estado, totales). |
| **Registros** | Bitácora de cada evento con hora exacta (cada pesada, pausas, anulaciones). Es la fuente de verdad para retomar turnos; no editar a mano. |

Definiciones:
- **Rendimiento %** = peso final / peso inicial × 100.
- **Merma %** = (inicial − final) / inicial × 100.
- **Min total neto** = de *Iniciar lote* a *Terminar lote*, menos pausas.
- **Kg/hora** = kg de entrada / horas netas.

Todas las horas están en hora de Bogotá (la app lo fuerza aunque el servidor
esté en UTC).

## Productos

Se leen en vivo (cache 10 min) de la columna `descripcion` de
"Nutrienti - Precios por Cliente (World Office)"
(`1HMNBT9Qqogz3WgZIenm-jB9wTUP7Ta_NP1BhUhoB3-s`, pestaña gid `1797058694`).
Se quita la unidad de venta ("x Kilo", "x Unidad", "por Kilo") y se agrupan
duplicados, porque para la operación "Lechuga Romana x Kilo" y "x Unidad" son
la misma lechuga (la columna `Codigo(s)` guarda los códigos, ej.
`LRH026/LRH027`). Si la hoja no se puede leer se usa `productos_respaldo.csv`.
También hay un botón "Otro producto" para escribir uno que no esté.

## Instalación / despliegue

1. Crear el repo `nutrienti-dev/track_operacion` en GitHub y subir estos
   archivos (**sin** `.streamlit/secrets.toml`).
2. En Streamlit Community Cloud: *New app* → repo `track_operacion`, rama
   `main`, archivo `app.py`.
3. *Advanced settings → Secrets*: pegar el contenido de
   `.streamlit/secrets.toml` (mismas credenciales `[gcp_oauth]` que la app de
   pedidos).
4. Abrir la URL en el celular y "Agregar a pantalla de inicio".

Local: `pip install -r requirements.txt` y `streamlit run app.py`. Sin
credenciales la app corre en **modo demo** (datos en memoria).

Pruebas: `pip install pytest && pytest -q tests`.

## Estructura

- `app.py` — pantallas (inicio, productos, lote en 3 pasos, cierre).
- `lib/logic.py` — lógica pura: eventos, reconstrucción del turno, métricas,
  catálogo de productos, hora de Bogotá.
- `lib/storage.py` — Google Sheets (gspread) y almacenamiento en memoria.
- `productos_respaldo.csv` — lista de productos de respaldo.
- `tests/` — pruebas de lógica, de la hoja (con un gspread falso) y de la app
  completa (Streamlit AppTest).
