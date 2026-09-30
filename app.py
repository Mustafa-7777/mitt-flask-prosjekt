import math
import os
import sqlite3
from datetime import date

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")
app.config["DATABASE"] = os.path.join(app.instance_path, "oppgaver.db")
antall_besok = 0
NUTRIENTS = (
    ("kcal", "Kalorier", "kcal"),
    ("protein", "Protein", "g"),
    ("carbs", "Karbohydrater", "g"),
    ("fat", "Fett", "g"),
    ("saturated_fat", "Mettet fett", "g"),
    ("fiber", "Fiber", "g"),
    ("sugar", "Sukker", "g"),
    ("salt", "Salt", "g"),
)
STARTER_FOODS = (
    (
        "Egg",
        "Omtrent 50 g per egg. Næringsverdiene er omtrentlige og oppgitt per 100 g.",
        (143, 12.6, 0.7, 9.5, 3.1, 0, 0.4, 0.36),
    ),
    (
        "Banan",
        "Omtrent 120 g spiselig del per middels banan. Næringsverdiene er omtrentlige og oppgitt per 100 g.",
        (89, 1.1, 22.8, 0.3, 0.1, 2.6, 12.2, 0.001),
    ),
    (
        "Eple",
        "Omtrent 180 g spiselig del per middels eple. Næringsverdiene er omtrentlige og oppgitt per 100 g.",
        (52, 0.3, 13.8, 0.2, 0, 2.4, 10.4, 0.001),
    ),
    (
        "Havregryn",
        "Tørre havregryn. Næringsverdiene er omtrentlige og oppgitt per 100 g.",
        (389, 16.9, 66.3, 6.9, 1.2, 10.6, 0.9, 0.002),
    ),
    (
        "Melk (1,5 % fett)",
        "Næringsverdiene er omtrentlige og oppgitt per 100 g.",
        (46, 3.4, 4.8, 1.5, 1.0, 0, 4.8, 0.1),
    ),
)


def get_db():
    os.makedirs(app.instance_path, exist_ok=True)
    database = sqlite3.connect(app.config["DATABASE"])
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys = ON")
    return database


def init_db():
    database = get_db()
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS oppgaver (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tekst TEXT NOT NULL
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS foods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            kcal REAL NOT NULL CHECK (kcal >= 0),
            protein REAL NOT NULL CHECK (protein >= 0),
            carbs REAL NOT NULL CHECK (carbs >= 0),
            fat REAL NOT NULL CHECK (fat >= 0),
            saturated_fat REAL NOT NULL CHECK (saturated_fat >= 0),
            fiber REAL NOT NULL CHECK (fiber >= 0),
            sugar REAL NOT NULL CHECK (sugar >= 0),
            salt REAL NOT NULL CHECK (salt >= 0)
        )
        """
    )
    food_columns = {
        column["name"]
        for column in database.execute("PRAGMA table_info(foods)").fetchall()
    }
    if "description" not in food_columns:
        database.execute(
            "ALTER TABLE foods ADD COLUMN description TEXT NOT NULL DEFAULT ''"
        )
    nutrient_columns = ", ".join(
        nutrient for nutrient, _label, _unit in NUTRIENTS
    )
    placeholders = ", ".join("?" for _ in range(len(NUTRIENTS) + 2))
    for name, description, values in STARTER_FOODS:
        exists = database.execute(
            "SELECT 1 FROM foods WHERE name = ? LIMIT 1", (name,)
        ).fetchone()
        if not exists:
            database.execute(
                f"INSERT INTO foods (name, description, {nutrient_columns}) "
                f"VALUES ({placeholders})",
                (name, description, *values),
            )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS food_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            food_id INTEGER NOT NULL REFERENCES foods (id),
            eaten_on TEXT NOT NULL,
            grams REAL NOT NULL CHECK (grams > 0)
        )
        """
    )
    database.commit()
    database.close()


def hent_oppgaver():
    database = get_db()
    oppgaver = database.execute(
        "SELECT id, tekst FROM oppgaver ORDER BY id"
    ).fetchall()
    database.close()
    return oppgaver


def hent_oppgave(oppgave_id):
    database = get_db()
    oppgave = database.execute(
        "SELECT id, tekst FROM oppgaver WHERE id = ?", (oppgave_id,)
    ).fetchone()
    database.close()
    return oppgave


def lagre_oppgave(tekst):
    database = get_db()
    cursor = database.execute("INSERT INTO oppgaver (tekst) VALUES (?)", (tekst,))
    database.commit()
    oppgave_id = cursor.lastrowid
    database.close()
    return hent_oppgave(oppgave_id)


def oppdater_oppgave(oppgave_id, tekst):
    database = get_db()
    database.execute(
        "UPDATE oppgaver SET tekst = ? WHERE id = ?", (tekst, oppgave_id)
    )
    database.commit()
    database.close()


def slett_oppgave(oppgave_id):
    database = get_db()
    cursor = database.execute("DELETE FROM oppgaver WHERE id = ?", (oppgave_id,))
    database.commit()
    database.close()
    return cursor.rowcount > 0


init_db()


def get_selected_date():
    selected_date = request.args.get("dato", date.today().isoformat())
    try:
        return date.fromisoformat(selected_date).isoformat()
    except (TypeError, ValueError):
        abort(400, description="Datoet må være på formatet ÅÅÅÅ-MM-DD.")


def parse_non_negative_number(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError
    return number


def parse_positive_number(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError
    return number


@app.route("/")
def home():
    navn = "Mustafa"
    global antall_besok
    antall_besok += 1

    return render_template(
        "index.html",
        navn=navn,
        antall_besok=antall_besok
    )


@app.route("/om")
def om():
    return render_template("om.html")


@app.route("/kontakt", methods=["GET", "POST"])
def kontakt():
    innsendt = None

    if request.method == "POST":
        innsendt = {
            "navn": request.form.get("navn", "").strip(),
            "epost": request.form.get("epost", "").strip(),
            "melding": request.form.get("melding", "").strip(),
        }

    return render_template("kontakt.html", innsendt=innsendt)


@app.route("/skjema", methods=["GET", "POST"])
def skjema():
    if request.method == "POST":
        navn = request.form.get("navn", "").strip()
        epost = request.form.get("epost", "").strip()
        melding = request.form.get("melding", "").strip()

        if not navn or not epost or not melding:
            return render_template(
                "skjema.html",
                navn=navn,
                epost=epost,
                melding=melding,
                 feil="Vennligst fyll ut alle feltene."
            )

        flash(f"Takk for meldingen, {navn}! Jeg svarer til {epost}.")
        return redirect(url_for("skjema"))

    return render_template("skjema.html")


@app.route("/api/status")
def api_status():
    return jsonify({
        "status": "ok",
        "melding": "API-et kjører som det skal"
    })


@app.route("/api/oppgaver", methods=["GET", "POST"])
def api_oppgaver_liste():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        tekst = str(data.get("tekst", "")).strip()

        if not tekst:
            return jsonify({"feil": "Feltet 'tekst' er påkrevd"}), 400

        ny_oppgave = lagre_oppgave(tekst)
        return jsonify(dict(ny_oppgave)), 201

    return jsonify([dict(oppgave) for oppgave in hent_oppgaver()])


@app.route("/api/oppgaver/<int:oppgave_id>", methods=["PUT", "DELETE"])
def api_slett_oppgave(oppgave_id):
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        tekst = str(data.get("tekst", "")).strip()
        if not tekst:
            return jsonify({"feil": "Feltet 'tekst' er påkrevd"}), 400
        if not hent_oppgave(oppgave_id):
            return jsonify({"feil": "Oppgaven ble ikke funnet"}), 404
        oppdater_oppgave(oppgave_id, tekst)
        return jsonify(dict(hent_oppgave(oppgave_id)))

    if slett_oppgave(oppgave_id):
            return jsonify({"melding": "Oppgaven ble slettet"})

    return jsonify({"feil": "Oppgaven ble ikke funnet"}), 404


@app.route("/oppgaver", methods=["GET", "POST"])
def oppgaver():
    if request.method == "POST":
        tekst = request.form.get("tekst", "").strip()
        if not tekst:
            flash("Skriv inn en oppgave før du lagrer.")
        else:
            lagre_oppgave(tekst)
            flash("Oppgaven ble lagt til.")
        return redirect(url_for("oppgaver"))

    return render_template("oppgaver.html", oppgaver=hent_oppgaver())


@app.get("/matlogg")
def matlogg():
    valgt_dato = get_selected_date()
    database = get_db()
    matvarer = database.execute(
        "SELECT id, name, description FROM foods ORDER BY name COLLATE NOCASE"
    ).fetchall()
    oppforinger = database.execute(
        """
        SELECT e.id, f.name, f.description, e.grams,
               f.kcal * e.grams / 100.0 AS kcal,
               f.protein * e.grams / 100.0 AS protein,
               f.carbs * e.grams / 100.0 AS carbs,
               f.fat * e.grams / 100.0 AS fat,
               f.saturated_fat * e.grams / 100.0 AS saturated_fat,
               f.fiber * e.grams / 100.0 AS fiber,
               f.sugar * e.grams / 100.0 AS sugar,
               f.salt * e.grams / 100.0 AS salt
        FROM food_entries AS e
        JOIN foods AS f ON f.id = e.food_id
        WHERE e.eaten_on = ?
        ORDER BY e.id DESC
        """,
        (valgt_dato,),
    ).fetchall()
    totals = {
        nutrient: sum(entry[nutrient] for entry in oppforinger)
        for nutrient, _label, _unit in NUTRIENTS
    }
    database.close()
    return render_template(
        "matlogg.html",
        valgt_dato=valgt_dato,
        matvarer=matvarer,
        oppforinger=oppforinger,
        totals=totals,
        nutrients=NUTRIENTS,
    )


@app.post("/matlogg/mat")
def legg_til_mat():
    valgt_dato = request.form.get("dato", date.today().isoformat())
    navn = request.form.get("name", "").strip()
    beskrivelse = request.form.get("description", "").strip()

    try:
        valgt_dato = date.fromisoformat(valgt_dato).isoformat()
    except (TypeError, ValueError):
        flash("Velg en gyldig dato.")
        return redirect(url_for("matlogg"))

    if not navn or len(navn) > 100:
        flash("Skriv inn et navn på matvaren (maks 100 tegn).")
        return redirect(url_for("matlogg", dato=valgt_dato))
    if len(beskrivelse) > 500:
        flash("Beskrivelsen kan ikke være lengre enn 500 tegn.")
        return redirect(url_for("matlogg", dato=valgt_dato))

    try:
        verdier = {
            nutrient: parse_non_negative_number(request.form.get(nutrient, ""))
            for nutrient, _label, _unit in NUTRIENTS
        }
    except ValueError:
        flash("Næringsverdiene må være gyldige tall som er null eller større.")
        return redirect(url_for("matlogg", dato=valgt_dato))

    database = get_db()
    placeholders = ", ".join("?" for _ in range(len(NUTRIENTS) + 2))
    columns = ", ".join(
        ("name", "description", *(nutrient for nutrient, _label, _unit in NUTRIENTS))
    )
    database.execute(
        f"INSERT INTO foods ({columns}) VALUES ({placeholders})",
        (
            navn,
            beskrivelse,
            *(verdier[nutrient] for nutrient, _label, _unit in NUTRIENTS),
        ),
    )
    database.commit()
    database.close()
    flash(f"{navn} ble lagt til i matvarelisten.")
    return redirect(url_for("matlogg", dato=valgt_dato))


@app.post("/matlogg/registrer")
def registrer_mat():
    valgt_dato = request.form.get("dato", "")
    try:
        valgt_dato = date.fromisoformat(valgt_dato).isoformat()
        matvare_id = int(request.form.get("food_id", ""))
        gram = parse_positive_number(request.form.get("grams", ""))
    except (ValueError, TypeError):
        flash("Velg en gyldig dato og matvare, og oppgi en mengde større enn 0 gram.")
        return redirect(url_for("matlogg"))

    database = get_db()
    matvare = database.execute(
        "SELECT name FROM foods WHERE id = ?", (matvare_id,)
    ).fetchone()
    if not matvare:
        database.close()
        flash("Matvaren ble ikke funnet. Velg en matvare fra listen.")
        return redirect(url_for("matlogg", dato=valgt_dato))

    database.execute(
        "INSERT INTO food_entries (food_id, eaten_on, grams) VALUES (?, ?, ?)",
        (matvare_id, valgt_dato, gram),
    )
    database.commit()
    database.close()
    flash(f"{matvare['name']} ble registrert.")
    return redirect(url_for("matlogg", dato=valgt_dato))


@app.post("/matlogg/oppforing/<int:oppforing_id>/slett")
def slett_matoppforing(oppforing_id):
    valgt_dato = request.form.get("dato", date.today().isoformat())
    try:
        valgt_dato = date.fromisoformat(valgt_dato).isoformat()
    except (TypeError, ValueError):
        flash("Velg en gyldig dato.")
        return redirect(url_for("matlogg"))

    database = get_db()
    cursor = database.execute(
        "DELETE FROM food_entries WHERE id = ?", (oppforing_id,)
    )
    database.commit()
    database.close()
    if cursor.rowcount:
        flash("Matregistreringen ble slettet.")
    else:
        flash("Matregistreringen ble ikke funnet.")
    return redirect(url_for("matlogg", dato=valgt_dato))


@app.route("/oppgaver/<int:oppgave_id>/endre", methods=["GET", "POST"])
def endre_oppgave(oppgave_id):
    oppgave = hent_oppgave(oppgave_id)
    if not oppgave:
        return "Oppgaven ble ikke funnet", 404

    if request.method == "POST":
        tekst = request.form.get("tekst", "").strip()
        if not tekst:
            return render_template("endre_oppgave.html", oppgave=oppgave, feil="Skriv inn en oppgave."), 400
        oppdater_oppgave(oppgave_id, tekst)
        flash("Oppgaven ble oppdatert.")
        return redirect(url_for("oppgaver"))

    return render_template("endre_oppgave.html", oppgave=oppgave)


@app.post("/oppgaver/<int:oppgave_id>/slett")
def slett_oppgave_side(oppgave_id):
    if slett_oppgave(oppgave_id):
        flash("Oppgaven ble slettet.")
    else:
        flash("Oppgaven ble ikke funnet.")
    return redirect(url_for("oppgaver"))


if __name__ == "__main__":
    app.run(debug=True)