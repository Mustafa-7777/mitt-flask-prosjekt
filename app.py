import os
import sqlite3

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")
app.config["DATABASE"] = os.path.join(app.instance_path, "oppgaver.db")
antall_besok = 0


def get_db():
    os.makedirs(app.instance_path, exist_ok=True)
    database = sqlite3.connect(app.config["DATABASE"])
    database.row_factory = sqlite3.Row
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