import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, g

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "crm.db")

DIAS = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
DIAS_DISPLAY = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
TIPOS = ["otros", "fiado", "mp", "pago"]

# Clientes iniciales del comercio
CLIENTES_INICIALES = [
    "Viviana", "Pato", "Silvio", "Carmen", "Sandra", "Gille", "Saavedra",
    "Coco", "Suipacha", "Gabi", "M.Paz", "Julio"
]

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            orden INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            dia_semana TEXT NOT NULL,
            tipo TEXT NOT NULL,
            valor TEXT DEFAULT '',
            UNIQUE(cliente_id, fecha, tipo),
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );

        CREATE TABLE IF NOT EXISTS cierres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anio INTEGER NOT NULL,
            mes INTEGER NOT NULL,
            cliente_id INTEGER NOT NULL,
            resumen TEXT DEFAULT '',
            fecha_cierre TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );
    """)

    # Insertar clientes iniciales si no existen
    for i, nombre in enumerate(CLIENTES_INICIALES):
        db.execute(
            "INSERT OR IGNORE INTO clientes (nombre, orden) VALUES (?, ?)",
            (nombre, i)
        )
    db.commit()
    db.close()


def dia_semana_actual():
    """Retorna el nombre del dia actual."""
    dias_py = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
    return dias_py[datetime.now().weekday()]


def fecha_semana_actual():
    """Retorna fecha del lunes de la semana actual en formato YYYY-MM-DD."""
    hoy = datetime.now()
    lunes = hoy - timedelta(days=hoy.weekday())
    return lunes.strftime("%Y-%m-%d")


from datetime import timedelta


@app.route("/")
def index():
    return render_template("planilla.html",
                           dias=DIAS,
                           dias_display=DIAS_DISPLAY,
                           tipos=TIPOS,
                           dia_hoy=dia_semana_actual())


@app.route("/api/clientes")
def api_clientes():
    db = get_db()
    rows = db.execute("SELECT id, nombre, orden FROM clientes ORDER BY orden, id").fetchall()
    return jsonify([{"id": r["id"], "nombre": r["nombre"]} for r in rows])


@app.route("/api/clientes", methods=["POST"])
def api_cliente_crear():
    db = get_db()
    nombre = request.json.get("nombre", "").strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    try:
        max_orden = db.execute("SELECT MAX(orden) FROM clientes").fetchone()[0] or 0
        cur = db.execute(
            "INSERT INTO clientes (nombre, orden) VALUES (?, ?)",
            (nombre, max_orden + 1)
        )
        db.commit()
        return jsonify({"id": cur.lastrowid, "nombre": nombre}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Cliente ya existe"}), 409


@app.route("/api/clientes/<int:cid>", methods=["DELETE"])
def api_cliente_borrar(cid):
    db = get_db()
    db.execute("DELETE FROM registros WHERE cliente_id=?", (cid,))
    db.execute("DELETE FROM clientes WHERE id=?", (cid,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/clientes/<int:cid>/orden", methods=["PUT"])
def api_cliente_orden(cid):
    db = get_db()
    nuevo_orden = request.json.get("orden", 0)
    db.execute("UPDATE clientes SET orden=? WHERE id=?", (nuevo_orden, cid))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/registros")
def api_registros():
    """Obtiene todos los registros de una semana (7 dias desde fecha_lunes)."""
    db = get_db()
    fecha_lunes = request.args.get("fecha")
    offset = request.args.get("offset", type=int)
    if offset is not None:
        hoy = datetime.now()
        lunes = hoy - timedelta(days=hoy.weekday()) + timedelta(weeks=offset)
        fecha_lunes = lunes.strftime("%Y-%m-%d")
    elif not fecha_lunes:
        fecha_lunes = fecha_semana_actual()

    # Calcular las 7 fechas
    lunes = datetime.strptime(fecha_lunes, "%Y-%m-%d")
    fechas = [(lunes + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

    placeholders = ",".join("?" * 7)
    rows = db.execute(
        f"""SELECT cliente_id, fecha, dia_semana, tipo, valor
            FROM registros
            WHERE fecha IN ({placeholders})""",
        fechas
    ).fetchall()

    # Estructurar: {cliente_id: {fecha: {tipo: valor}}}
    data = {}
    for r in rows:
        cid = r["cliente_id"]
        if cid not in data:
            data[cid] = {}
        fecha = r["fecha"]
        if fecha not in data[cid]:
            data[cid][fecha] = {}
        data[cid][fecha][r["tipo"]] = r["valor"]

    return jsonify({
        "fechas": fechas,
        "dias": DIAS,
        "registros": data
    })


@app.route("/api/registros", methods=["POST"])
def api_registro_guardar():
    """Guarda o actualiza una sola celda."""
    db = get_db()
    body = request.json
    cliente_id = body.get("cliente_id")
    fecha = body.get("fecha")
    dia_semana = body.get("dia_semana")
    tipo = body.get("tipo")
    valor = body.get("valor", "")

    if not all([cliente_id, fecha, dia_semana, tipo]):
        return jsonify({"error": "Faltan datos"}), 400

    if tipo not in TIPOS:
        return jsonify({"error": "Tipo invalido"}), 400

    # Upsert: si valor vacio, borrar registro
    if not valor.strip():
        db.execute(
            "DELETE FROM registros WHERE cliente_id=? AND fecha=? AND tipo=?",
            (cliente_id, fecha, tipo)
        )
    else:
        db.execute("""
            INSERT INTO registros (cliente_id, fecha, dia_semana, tipo, valor)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id, fecha, tipo)
            DO UPDATE SET valor=excluded.valor
        """, (cliente_id, fecha, dia_semana, tipo, valor))

    db.commit()
    return jsonify({"ok": True})


# ---- Resumen semanal ----
@app.route("/api/resumen/semana")
def api_resumen_semana():
    """Resumen de la semana: por cliente, totales de fiado y pago."""
    db = get_db()
    fecha_lunes = request.args.get("fecha", fecha_semana_actual())
    lunes = datetime.strptime(fecha_lunes, "%Y-%m-%d")
    fechas = [(lunes + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    placeholders = ",".join("?" * 7)

    rows = db.execute(f"""
        SELECT c.id, c.nombre, r.tipo, r.valor
        FROM clientes c
        LEFT JOIN registros r ON c.id = r.cliente_id AND r.fecha IN ({placeholders})
        WHERE r.id IS NOT NULL
        ORDER BY c.orden, c.id
    """, fechas).fetchall()

    resumen = {}
    for r in rows:
        cid = r["id"]
        if cid not in resumen:
            resumen[cid] = {"nombre": r["nombre"], "otros": [], "fiado": [], "mp": [], "pago": []}
        if r["valor"]:
            resumen[cid][r["tipo"]].append(r["valor"])

    return jsonify(resumen)


# ---- Resumen mensual ----
@app.route("/api/resumen/mes/<int:anio>/<int:mes>")
def api_resumen_mes(anio, mes):
    """Resumen mensual: todos los registros de un mes."""
    db = get_db()
    fecha_ini = f"{anio:04d}-{mes:02d}-01"
    mes_sig = mes + 1
    anio_sig = anio
    if mes == 12:
        mes_sig = 1
        anio_sig = anio + 1
    fecha_fin = f"{anio_sig:04d}-{mes_sig:02d}-01"

    rows = db.execute("""
        SELECT c.id, c.nombre, r.fecha, r.dia_semana, r.tipo, r.valor
        FROM clientes c
        JOIN registros r ON c.id = r.cliente_id
        WHERE r.fecha >= ? AND r.fecha < ?
        ORDER BY c.orden, c.id, r.fecha
    """, (fecha_ini, fecha_fin)).fetchall()

    return jsonify([dict(r) for r in rows])


# ---- Cierre de mes ----
@app.route("/api/cierre/mes/<int:anio>/<int:mes>", methods=["POST"])
def api_cierre_mes(anio, mes):
    """Guarda un cierre de mes."""
    db = get_db()
    fecha_ini = f"{anio:04d}-{mes:02d}-01"
    mes_sig = mes + 1
    anio_sig = anio
    if mes == 12:
        mes_sig = 1
        anio_sig = anio + 1
    fecha_fin = f"{anio_sig:04d}-{mes_sig:02d}-01"

    rows = db.execute("""
        SELECT c.id, c.nombre, r.tipo, r.valor
        FROM clientes c
        LEFT JOIN registros r ON c.id = r.cliente_id AND r.fecha >= ? AND r.fecha < ?
        ORDER BY c.orden, c.id
    """, (fecha_ini, fecha_fin)).fetchall()

    resumen_data = {}
    for r in rows:
        cid = r["id"]
        if cid not in resumen_data:
            resumen_data[cid] = {"nombre": r["nombre"], "otros": [], "fiado": [], "mp": [], "pago": []}
        if r["valor"]:
            resumen_data[cid][r["tipo"]].append(r["valor"])

    for cid, data in resumen_data.items():
        resumen_str = f"Otros: {len(data['otros'])} | Fiado: {len(data['fiado'])} | M/P: {len(data['mp'])} | Pago: {len(data['pago'])}"
        db.execute("""
            INSERT INTO cierres (anio, mes, cliente_id, resumen)
            VALUES (?, ?, ?, ?)
            ON CONFLICT DO NOTHING
        """, (anio, mes, cid, resumen_str))

    db.commit()
    return jsonify({"ok": True, "clientes": len(resumen_data)})


@app.route("/api/cierres")
def api_cierres():
    """Lista todos los cierres."""
    db = get_db()
    anio = request.args.get("anio")
    mes = request.args.get("mes")
    q = "SELECT * FROM cierres"
    params = []
    if anio and mes:
        q += " WHERE anio=? AND mes=?"
        params = [int(anio), int(mes)]
    q += " ORDER BY fecha_cierre DESC"
    rows = db.execute(q, params).fetchall()
    return jsonify([dict(r) for r in rows])


# ---- Reportes (pagina) ----
@app.route("/reportes")
def reportes():
    return render_template("reportes.html")


# ---- Health check ----
@app.route("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
else:
    init_db()