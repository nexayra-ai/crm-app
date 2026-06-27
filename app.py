import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, g

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "crm.db")
DIAS = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado', 'Domingo']
PAGOS = ['Otro', 'Fiado', 'M/P', 'Pago']

app = Flask(__name__)

# ---------- DB ----------
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
    cols = ", ".join([f'"{d}" TEXT DEFAULT "Otro"' for d in DIAS])
    db.executescript(f"""
    CREATE TABLE IF NOT EXISTS contactos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        notas TEXT,
        valor REAL DEFAULT 0,
        {cols},
        fecha_creacion TEXT DEFAULT (datetime('now','localtime')),
        fecha_actualizacion TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS meses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        anio INTEGER NOT NULL,
        mes INTEGER NOT NULL,
        contacto_id INTEGER NOT NULL,
        resumen TEXT,
        total REAL DEFAULT 0,
        fecha_cierre TEXT,
        UNIQUE(anio, mes, contacto_id),
        FOREIGN KEY (contacto_id) REFERENCES contactos(id) ON DELETE CASCADE
    );
    """)
    db.commit()
    db.close()

# ---------- Rutas ----------
@app.route("/")
def dashboard():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM contactos").fetchone()[0]
    hoy_idx = datetime.now().weekday()  # 0=Lunes
    dia_hoy = DIAS[hoy_idx]
    # Contar pagos del dia actual
    pagos_hoy = db.execute(
        f'SELECT "{dia_hoy}" as pago, COUNT(*) as n FROM contactos GROUP BY "{dia_hoy}"'
    ).fetchall()
    por_pago_general = {}
    for d in DIAS:
        rows = db.execute(f'SELECT "{d}", COUNT(*) FROM contactos GROUP BY "{d}"').fetchall()
        por_pago_general[d] = {r[0]: r[1] for r in rows}
    recientes = db.execute("SELECT * FROM contactos ORDER BY fecha_creacion DESC LIMIT 8").fetchall()
    return render_template("dashboard.html", total=total, dia_hoy=dia_hoy,
                           pagos_hoy=pagos_hoy, por_pago_general=por_pago_general,
                           recientes=recientes, DIAS=DIAS, PAGOS=PAGOS, now=datetime.now)

@app.route("/contactos")
def contactos():
    db = get_db()
    q = request.args.get("q", "")
    if q:
        like = f"%{q}%"
        rows = db.execute("SELECT * FROM contactos WHERE nombre LIKE ? ORDER BY nombre", (like,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM contactos ORDER BY nombre").fetchall()
    return render_template("contactos.html", contactos=rows, q=q, DIAS=DIAS, PAGOS=PAGOS)

@app.route("/contactos/nuevo", methods=["GET", "POST"])
def nuevo_contacto():
    if request.method == "POST":
        db = get_db()
        dias_vals = [request.form.get(d, "Otro") for d in DIAS]
        cols = ", ".join(['"' + d + '"' for d in DIAS])
        placeholders = ", ".join(["?"] * 7)
        db.execute(
            f'INSERT INTO contactos (nombre, notas, valor, {cols}) VALUES (?,?,?,{placeholders})',
            [request.form["nombre"], request.form.get("notas", ""), float(request.form.get("valor", 0) or 0)] + dias_vals
        )
        db.commit()
        return redirect(url_for("contactos"))
    return render_template("form_contacto.html", c=None, DIAS=DIAS, PAGOS=PAGOS)

@app.route("/contactos/<int:id>/editar", methods=["GET", "POST"])
def editar_contacto(id):
    db = get_db()
    if request.method == "POST":
        dias_vals = [request.form.get(d, "Otro") for d in DIAS]
        set_dias = ", ".join([f'"{d}"=?' for d in DIAS])
        db.execute(
            f'UPDATE contactos SET nombre=?, notas=?, valor=?, {set_dias}, fecha_actualizacion=datetime("now","localtime") WHERE id=?',
            [request.form["nombre"], request.form.get("notas", ""), float(request.form.get("valor", 0) or 0)] + dias_vals + [id]
        )
        db.commit()
        return redirect(url_for("contactos"))
    c = db.execute("SELECT * FROM contactos WHERE id=?", (id,)).fetchone()
    return render_template("form_contacto.html", c=c, DIAS=DIAS, PAGOS=PAGOS)

@app.route("/contactos/<int:id>/eliminar", methods=["POST"])
def eliminar_contacto(id):
    db = get_db()
    db.execute("DELETE FROM contactos WHERE id=?", (id,))
    db.commit()
    return redirect(url_for("contactos"))

@app.route("/contactos/<int:id>")
def detalle_contacto(id):
    db = get_db()
    c = db.execute("SELECT * FROM contactos WHERE id=?", (id,)).fetchone()
    return render_template("detalle.html", c=c, DIAS=DIAS, PAGOS=PAGOS)

# API: actualizar pago de un dia especifico (AJAX)
@app.route("/api/contactos/<int:id>/pago", methods=["POST"])
def update_pago(id):
    db = get_db()
    dia = request.json.get("dia")
    pago = request.json.get("pago")
    if dia not in DIAS or pago not in PAGOS:
        return jsonify({"error": "Valores invalidos"}), 400
    db.execute(f'UPDATE contactos SET "{dia}"=?, fecha_actualizacion=datetime("now","localtime") WHERE id=?', (pago, id))
    db.commit()
    return jsonify({"ok": True, "dia": dia, "pago": pago})

# ---------- Resumen Mensual ----------
@app.route("/resumen")
def resumen():
    db = get_db()
    ahora = datetime.now()
    anio = request.args.get("anio", ahora.year, type=int)
    mes = request.args.get("mes", ahora.month, type=int)
    contactos = db.execute("SELECT * FROM contactos ORDER BY nombre").fetchall()
    # Resumen por contacto: contar cada tipo de pago en la semana
    resumen_data = []
    for c in contactos:
        counts = {p: 0 for p in PAGOS}
        for d in DIAS:
            val = c[d] if c[d] else "Otro"
            if val in counts:
                counts[val] += 1
        total_valor = c["valor"] * 4  # estimacion semanal x4 semanas
        resumen_data.append({"contacto": c, "counts": counts, "total_estimado": total_valor})
    # Totales generales
    totales = {p: 0 for p in PAGOS}
    for r in resumen_data:
        for p in PAGOS:
            totales[p] += r["counts"][p]
    # Verificar si ya existe cierre de mes
    cierres = db.execute("SELECT * FROM meses WHERE anio=? AND mes=?", (anio, mes)).fetchall()
    ya_cerrado = len(cierres) > 0
    return render_template("resumen.html", resumen_data=resumen_data, totales=totales,
                           anio=anio, mes=mes, DIAS=DIAS, PAGOS=PAGOS,
                           ya_cerrado=ya_cerrado, now=datetime.now)

@app.route("/resumen/cerrar", methods=["POST"])
def cerrar_mes():
    db = get_db()
    anio = request.form.get("anio", type=int)
    mes = request.form.get("mes", type=int)
    contactos = db.execute("SELECT * FROM contactos ORDER BY nombre").fetchall()
    for c in contactos:
        counts = {p: 0 for p in PAGOS}
        for d in DIAS:
            val = c[d] if c[d] else "Otro"
            if val in counts:
                counts[val] += 1
        resumen_text = " | ".join([f"{p}: {counts[p]}" for p in PAGOS])
        total = c["valor"] * 4
        db.execute("""INSERT INTO meses (anio, mes, contacto_id, resumen, total, fecha_cierre)
            VALUES (?,?,?,?,?,datetime('now','localtime'))
            ON CONFLICT(anio, mes, contacto_id) DO UPDATE SET resumen=excluded.resumen, total=excluded.total, fecha_cierre=datetime('now','localtime')""",
            (anio, mes, c["id"], resumen_text, total))
    db.commit()
    return redirect(url_for("resumen", anio=anio, mes=mes))

@app.route("/reportes")
def reportes():
    db = get_db()
    anio = request.args.get("anio", datetime.now().year, type=int)
    mes = request.args.get("mes", datetime.now().month, type=int)
    cierres = db.execute(
        "SELECT m.*, c.nombre FROM meses m JOIN contactos c ON m.contacto_id=c.id WHERE m.anio=? AND m.mes=? ORDER BY c.nombre",
        (anio, mes)
    ).fetchall()
    return render_template("reportes.html", cierres=cierres, anio=anio, mes=mes, PAGOS=PAGOS)

@app.route("/api/stats")
def api_stats():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM contactos").fetchone()[0]
    hoy_idx = datetime.now().weekday()
    dia_hoy = DIAS[hoy_idx]
    pagos_hoy = dict(db.execute(f'SELECT "{dia_hoy}", COUNT(*) FROM contactos GROUP BY "{dia_hoy}"').fetchall())
    return jsonify({"total": total, "dia_hoy": dia_hoy, "pagos_hoy": pagos_hoy,
                    "timestamp": datetime.now().isoformat()})

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)