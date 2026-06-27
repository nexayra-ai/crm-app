import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, g

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "crm.db")

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
    db.executescript("""
    CREATE TABLE IF NOT EXISTS contactos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        email TEXT,
        telefono TEXT,
        empresa TEXT,
        categoria TEXT DEFAULT 'Lead',
        estado TEXT DEFAULT 'Activo',
        notas TEXT,
        valor REAL DEFAULT 0,
        fecha_creacion TEXT DEFAULT (datetime('now','localtime')),
        fecha_actualizacion TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS interacciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contacto_id INTEGER NOT NULL,
        tipo TEXT,
        descripcion TEXT,
        fecha TEXT DEFAULT (datetime('now','localtime')),
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
    activos = db.execute("SELECT COUNT(*) FROM contactos WHERE estado='Activo'").fetchone()[0]
    valor_total = db.execute("SELECT COALESCE(SUM(valor),0) FROM contactos").fetchone()[0]
    por_categoria = db.execute(
        "SELECT categoria, COUNT(*) as n FROM contactos GROUP BY categoria"
    ).fetchall()
    por_estado = db.execute(
        "SELECT estado, COUNT(*) as n FROM contactos GROUP BY estado"
    ).fetchall()
    recientes = db.execute(
        "SELECT * FROM contactos ORDER BY fecha_creacion DESC LIMIT 5"
    ).fetchall()
    return render_template("dashboard.html", total=total, activos=activos,
                           valor_total=valor_total, por_categoria=por_categoria,
                           por_estado=por_estado, recientes=recientes, now=datetime.now)

@app.route("/contactos")
def contactos():
    db = get_db()
    q = request.args.get("q", "")
    if q:
        like = f"%{q}%"
        rows = db.execute(
            "SELECT * FROM contactos WHERE nombre LIKE ? OR email LIKE ? OR empresa LIKE ? ORDER BY nombre",
            (like, like, like)
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM contactos ORDER BY nombre").fetchall()
    return render_template("contactos.html", contactos=rows, q=q)

@app.route("/contactos/nuevo", methods=["GET", "POST"])
def nuevo_contacto():
    if request.method == "POST":
        db = get_db()
        db.execute("""INSERT INTO contactos (nombre,email,telefono,empresa,categoria,estado,notas,valor)
            VALUES (?,?,?,?,?,?,?,?)""",
            (request.form["nombre"], request.form.get("email",""),
             request.form.get("telefono",""), request.form.get("empresa",""),
             request.form.get("categoria","Lead"), request.form.get("estado","Activo"),
             request.form.get("notas",""), float(request.form.get("valor",0) or 0)))
        db.commit()
        return redirect(url_for("contactos"))
    return render_template("form_contacto.html", c=None)

@app.route("/contactos/<int:id>/editar", methods=["GET", "POST"])
def editar_contacto(id):
    db = get_db()
    if request.method == "POST":
        db.execute("""UPDATE contactos SET nombre=?,email=?,telefono=?,empresa=?,
            categoria=?,estado=?,notas=?,valor=?,fecha_actualizacion=datetime('now','localtime')
            WHERE id=?""",
            (request.form["nombre"], request.form.get("email",""),
             request.form.get("telefono",""), request.form.get("empresa",""),
             request.form.get("categoria","Lead"), request.form.get("estado","Activo"),
             request.form.get("notas",""), float(request.form.get("valor",0) or 0), id))
        db.commit()
        return redirect(url_for("contactos"))
    c = db.execute("SELECT * FROM contactos WHERE id=?", (id,)).fetchone()
    return render_template("form_contacto.html", c=c)

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
    inter = db.execute(
        "SELECT * FROM interacciones WHERE contacto_id=? ORDER BY fecha DESC", (id,)
    ).fetchall()
    return render_template("detalle.html", c=c, interacciones=inter)

@app.route("/contactos/<int:id>/interaccion", methods=["POST"])
def add_interaccion(id):
    db = get_db()
    db.execute("INSERT INTO interacciones (contacto_id,tipo,descripcion) VALUES (?,?,?)",
               (id, request.form.get("tipo","Nota"), request.form.get("descripcion","")))
    db.commit()
    return redirect(url_for("detalle_contacto", id=id))

@app.route("/reportes")
def reportes():
    db = get_db()
    por_categoria = db.execute(
        "SELECT categoria, COUNT(*) as n, COALESCE(SUM(valor),0) as total FROM contactos GROUP BY categoria"
    ).fetchall()
    por_estado = db.execute(
        "SELECT estado, COUNT(*) as n, COALESCE(SUM(valor),0) as total FROM contactos GROUP BY estado"
    ).fetchall()
    por_empresa = db.execute(
        "SELECT empresa, COUNT(*) as n, COALESCE(SUM(valor),0) as total FROM contactos WHERE empresa!='' GROUP BY empresa ORDER BY n DESC LIMIT 10"
    ).fetchall()
    return render_template("reportes.html", por_categoria=por_categoria,
                           por_estado=por_estado, por_empresa=por_empresa)

# API para datos en vivo (chart.js)
@app.route("/api/stats")
def api_stats():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM contactos").fetchone()[0]
    activos = db.execute("SELECT COUNT(*) FROM contactos WHERE estado='Activo'").fetchone()[0]
    valor_total = db.execute("SELECT COALESCE(SUM(valor),0) FROM contactos").fetchone()[0]
    por_categoria = dict(db.execute(
        "SELECT categoria, COUNT(*) FROM contactos GROUP BY categoria"
    ).fetchall())
    por_estado = dict(db.execute(
        "SELECT estado, COUNT(*) FROM contactos GROUP BY estado"
    ).fetchall())
    return jsonify({
        "total": total, "activos": activos, "valor_total": valor_total,
        "por_categoria": por_categoria, "por_estado": por_estado,
        "timestamp": datetime.now().isoformat()
    })

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)