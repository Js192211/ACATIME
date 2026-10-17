import sqlite3
from functools import wraps

from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, jsonify, g)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "cambia-esta-clave-secreta"
DATABASE = "acadtime.db"


# ---------------------------------------------------------------
# Base de datos (SQLite)
# ---------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        correo TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        rol TEXT NOT NULL CHECK (rol IN ('docente', 'estudiante'))
    );
    CREATE TABLE IF NOT EXISTS materias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT NOT NULL UNIQUE,
        nombre TEXT NOT NULL,
        docente_id INTEGER,
        FOREIGN KEY (docente_id) REFERENCES usuarios(id)
    );
    CREATE TABLE IF NOT EXISTS horarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        materia_id INTEGER NOT NULL,
        dia TEXT NOT NULL,
        hora_inicio TEXT NOT NULL,
        hora_fin TEXT NOT NULL,
        aula TEXT NOT NULL,
        FOREIGN KEY (materia_id) REFERENCES materias(id)
    );
    CREATE TABLE IF NOT EXISTS inscripciones (
        estudiante_id INTEGER NOT NULL,
        materia_id INTEGER NOT NULL,
        PRIMARY KEY (estudiante_id, materia_id)
    );
    """)
    db.commit()
    db.close()


# ---------------------------------------------------------------
# Decoradores de acceso
# ---------------------------------------------------------------
def login_requerido(rol=None):
    def decorador(f):
        @wraps(f)
        def envoltura(*args, **kwargs):
            if "usuario_id" not in session:
                flash("Debes iniciar sesión.")
                return redirect(url_for("iniciar_sesion"))
            if rol and session.get("rol") != rol:
                flash("No tienes permiso para ver esa página.")
                return redirect(url_for("index"))
            return f(*args, **kwargs)
        return envoltura
    return decorador


# ---------------------------------------------------------------
# Funciones auxiliares
# ---------------------------------------------------------------
def hay_cruce_de_horario(aula, dia, inicio, fin, ignorar_id=None):
    """True si el aula ya está ocupada en ese día y rango de horas."""
    db = get_db()
    consulta = """
        SELECT id FROM horarios
        WHERE aula = ? AND dia = ?
          AND hora_inicio < ? AND hora_fin > ?
    """
    params = [aula, dia, fin, inicio]
    if ignorar_id:
        consulta += " AND id != ?"
        params.append(ignorar_id)
    return db.execute(consulta, params).fetchone() is not None


def redirigir_a_interfaz():
    if session.get("rol") == "docente":
        return redirect(url_for("interfaz_docente"))
    return redirect(url_for("interfaz_estudiante"))


# ---------------------------------------------------------------
# Páginas públicas
# ---------------------------------------------------------------
@app.route("/")
def index():
    return render_template("Index.html")


@app.route("/registro", methods=["GET", "POST"])
def registro_usuario():
    if request.method == "POST":
        nombre = request.form["nombre"].strip()
        correo = request.form["correo"].strip().lower()
        password = request.form["password"]
        rol = request.form.get("rol", "estudiante")

        if not nombre or not correo or not password:
            flash("Completa todos los campos.")
            return render_template("RegistroUsuario.html")

        db = get_db()
        try:
            db.execute(
                "INSERT INTO usuarios (nombre, correo, password, rol) "
                "VALUES (?, ?, ?, ?)",
                (nombre, correo, generate_password_hash(password), rol),
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash("Ese correo ya está registrado.")
            return render_template("RegistroUsuario.html")

        flash("Registro exitoso. Ahora inicia sesión.")
        return redirect(url_for("iniciar_sesion"))

    return render_template("RegistroUsuario.html")


@app.route("/iniciar-sesion", methods=["GET", "POST"])
def iniciar_sesion():
    if request.method == "POST":
        correo = request.form["correo"].strip().lower()
        password = request.form["password"]

        usuario = get_db().execute(
            "SELECT * FROM usuarios WHERE correo = ?", (correo,)
        ).fetchone()

        if usuario and check_password_hash(usuario["password"], password):
            session.clear()
            session["usuario_id"] = usuario["id"]
            session["nombre"] = usuario["nombre"]
            session["rol"] = usuario["rol"]
            return redirigir_a_interfaz()

        flash("Correo o contraseña incorrectos.")

    return render_template("IniciarSesion.html")


@app.route("/cerrar-sesion")
def cerrar_sesion():
    session.clear()
    return redirect(url_for("index"))


# ---------------------------------------------------------------
# Docente
# ---------------------------------------------------------------
@app.route("/interfaz-docente")
@login_requerido("docente")
def interfaz_docente():
    materias = get_db().execute(
        "SELECT * FROM materias WHERE docente_id = ?",
        (session["usuario_id"],),
    ).fetchall()
    return render_template("InterfazDocente.html", materias=materias)


@app.route("/horarios-docente")
@login_requerido("docente")
def horarios_docente():
    horarios = get_db().execute("""
        SELECT h.id, m.nombre AS materia, h.dia,
               h.hora_inicio, h.hora_fin, h.aula
        FROM horarios h
        JOIN materias m ON m.id = h.materia_id
        WHERE m.docente_id = ?
        ORDER BY h.dia, h.hora_inicio
    """, (session["usuario_id"],)).fetchall()
    return render_template("HorariosDocente.html", horarios=horarios)


@app.route("/horarios/agregar", methods=["POST"])
@login_requerido("docente")
def agregar_horario():
    materia_id = request.form["materia_id"]
    dia = request.form["dia"]
    inicio = request.form["hora_inicio"]
    fin = request.form["hora_fin"]
    aula = request.form["aula"].strip()

    if inicio >= fin:
        flash("La hora de inicio debe ser menor que la hora de fin.")
        return redirect(url_for("horarios_docente"))

    if hay_cruce_de_horario(aula, dia, inicio, fin):
        flash("Cruce de horario: el aula ya está ocupada en ese horario.")
        return redirect(url_for("horarios_docente"))

    db = get_db()
    db.execute(
        "INSERT INTO horarios (materia_id, dia, hora_inicio, hora_fin, aula) "
        "VALUES (?, ?, ?, ?, ?)",
        (materia_id, dia, inicio, fin, aula),
    )
    db.commit()
    flash("Horario agregado correctamente.")
    return redirect(url_for("horarios_docente"))


@app.route("/horarios/eliminar/<int:horario_id>", methods=["POST"])
@login_requerido("docente")
def eliminar_horario(horario_id):
    db = get_db()
    db.execute("DELETE FROM horarios WHERE id = ?", (horario_id,))
    db.commit()
    flash("Horario eliminado.")
    return redirect(url_for("horarios_docente"))


# ---------------------------------------------------------------
# Estudiante
# ---------------------------------------------------------------
@app.route("/interfaz-estudiante")
@login_requerido("estudiante")
def interfaz_estudiante():
    materias = get_db().execute("""
        SELECT m.* FROM materias m
        JOIN inscripciones i ON i.materia_id = m.id
        WHERE i.estudiante_id = ?
    """, (session["usuario_id"],)).fetchall()
    return render_template("InterfazEstudiante.html", materias=materias)


@app.route("/horarios-estudiante")
@login_requerido("estudiante")
def horarios_estudiante():
    horarios = get_db().execute("""
        SELECT m.nombre AS materia, h.dia,
               h.hora_inicio, h.hora_fin, h.aula
        FROM horarios h
        JOIN materias m ON m.id = h.materia_id
        JOIN inscripciones i ON i.materia_id = m.id
        WHERE i.estudiante_id = ?
        ORDER BY h.dia, h.hora_inicio
    """, (session["usuario_id"],)).fetchall()
    return render_template("HorariosEstudiante.html", horarios=horarios)


@app.route("/materias/inscribir/<int:materia_id>", methods=["POST"])
@login_requerido("estudiante")
def inscribir_materia(materia_id):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO inscripciones (estudiante_id, materia_id) VALUES (?, ?)",
            (session["usuario_id"], materia_id),
        )
        db.commit()
        flash("Te inscribiste en la materia.")
    except sqlite3.IntegrityError:
        flash("Ya estás inscrito en esa materia.")
    return redirect(url_for("interfaz_estudiante"))


# ---------------------------------------------------------------
# Materias (CRUD)
# ---------------------------------------------------------------
@app.route("/materias")
@login_requerido()
def materias():
    lista = get_db().execute("""
        SELECT m.id, m.codigo, m.nombre, u.nombre AS docente
        FROM materias m
        LEFT JOIN usuarios u ON u.id = m.docente_id
        ORDER BY m.nombre
    """).fetchall()
    return render_template("materia.html", materias=lista)


@app.route("/materias/agregar", methods=["POST"])
@login_requerido("docente")
def agregar_materia():
    codigo = request.form["codigo"].strip().upper()
    nombre = request.form["nombre"].strip()

    db = get_db()
    try:
        db.execute(
            "INSERT INTO materias (codigo, nombre, docente_id) VALUES (?, ?, ?)",
            (codigo, nombre, session["usuario_id"]),
        )
        db.commit()
        flash("Materia creada.")
    except sqlite3.IntegrityError:
        flash("Ya existe una materia con ese código.")
    return redirect(url_for("materias"))


@app.route("/materias/editar/<int:materia_id>", methods=["POST"])
@login_requerido("docente")
def editar_materia(materia_id):
    db = get_db()
    db.execute(
        "UPDATE materias SET codigo = ?, nombre = ? WHERE id = ?",
        (request.form["codigo"].strip().upper(),
         request.form["nombre"].strip(), materia_id),
    )
    db.commit()
    flash("Materia actualizada.")
    return redirect(url_for("materias"))


@app.route("/materias/eliminar/<int:materia_id>", methods=["POST"])
@login_requerido("docente")
def eliminar_materia(materia_id):
    db = get_db()
    db.execute("DELETE FROM horarios WHERE materia_id = ?", (materia_id,))
    db.execute("DELETE FROM inscripciones WHERE materia_id = ?", (materia_id,))
    db.execute("DELETE FROM materias WHERE id = ?", (materia_id,))
    db.commit()
    flash("Materia eliminada.")
    return redirect(url_for("materias"))


# ---------------------------------------------------------------
# API JSON opcional (por si usas fetch/JS en los HTML)
# ---------------------------------------------------------------
@app.route("/api/horarios")
@login_requerido()
def api_horarios():
    filas = get_db().execute("""
        SELECT m.nombre AS materia, h.dia, h.hora_inicio, h.hora_fin, h.aula
        FROM horarios h JOIN materias m ON m.id = h.materia_id
        ORDER BY h.dia, h.hora_inicio
    """).fetchall()
    return jsonify([dict(f) for f in filas])


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
