import json
import math
import os
import sqlite3
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

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
ACTIVITY_LEVELS = {
    "sedentary": ("Lite aktiv – mest stillesittende", 1.2),
    "light": ("Lett aktiv – lett trening 1–3 dager i uken", 1.375),
    "moderate": ("Moderat aktiv – trening 3–5 dager i uken", 1.55),
    "high": ("Svært aktiv – hard trening 6–7 dager i uken", 1.725),
    "very_high": ("Ekstra aktiv – svært hard trening eller fysisk arbeid", 1.9),
}
GOALS = {
    "lose": "Gå ned i vekt",
    "maintain": "Holde vekten",
    "gain": "Gå opp i vekt",
}


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
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS nutrition_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            age INTEGER NOT NULL CHECK (age BETWEEN 18 AND 100),
            biological_sex TEXT NOT NULL CHECK (biological_sex IN ('female', 'male')),
            weight_kg REAL NOT NULL CHECK (weight_kg BETWEEN 35 AND 300),
            height_cm REAL NOT NULL CHECK (height_cm BETWEEN 120 AND 230),
            activity_level TEXT NOT NULL,
            goal TEXT NOT NULL CHECK (goal IN ('lose', 'maintain', 'gain')),
            goal_weight_kg REAL CHECK (goal_weight_kg BETWEEN 30 AND 300),
            water_goal_ml INTEGER CHECK (water_goal_ml BETWEEN 250 AND 10000)
        )
        """
    )
    profile_columns = {
        column["name"]
        for column in database.execute(
            "PRAGMA table_info(nutrition_profile)"
        ).fetchall()
    }
    if "water_goal_ml" not in profile_columns:
        database.execute(
            "ALTER TABLE nutrition_profile "
            "ADD COLUMN water_goal_ml INTEGER "
            "CHECK (water_goal_ml BETWEEN 250 AND 10000)"
        )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS water_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            consumed_on TEXT NOT NULL,
            milliliters INTEGER NOT NULL CHECK (milliliters BETWEEN 1 AND 10000)
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


def calculate_calorie_targets(profile):
    weight = profile["weight_kg"]
    height = profile["height_cm"]
    age = profile["age"]
    sex_adjustment = 5 if profile["biological_sex"] == "male" else -161
    bmr = 10 * weight + 6.25 * height - 5 * age + sex_adjustment
    maintenance = bmr * ACTIVITY_LEVELS[profile["activity_level"]][1]
    adjustment = {"lose": -300, "maintain": 0, "gain": 200}[profile["goal"]]
    daily = max(0, round((maintenance + adjustment) / 10) * 10)
    return {
        "bmr": round(bmr),
        "maintenance": round(maintenance / 10) * 10,
        "daily": daily,
        "weekly": daily * 7,
        "goal_label": GOALS[profile["goal"]],
    }


def calculate_nutrient_targets(profile, calorie_targets):
    daily_calories = calorie_targets["daily"]
    muscle_gain = profile["goal"] == "gain"
    protein_low = round(profile["weight_kg"] * (1.4 if muscle_gain else 0.8))
    protein_high = round(profile["weight_kg"] * 2.0) if muscle_gain else None
    carbs_low = round(daily_calories * 0.45 / 4)
    carbs_high = round(daily_calories * 0.65 / 4)
    fat_low = round(daily_calories * 0.20 / 9)
    fat_high = round(daily_calories * 0.35 / 9)
    saturated_fat = round(daily_calories * 0.10 / 9)
    fiber = round(daily_calories * 0.014)
    free_sugar = round(daily_calories * 0.10 / 4)

    def amount(value, unit, marker=""):
        return f"{marker}{value} {unit}"

    def range_amount(low, high):
        return f"{low}–{high} g"

    protein_target = (
        {
            "key": "protein",
            "label": "Protein (muskelbygging)",
            "daily": range_amount(protein_low, protein_high),
            "weekly": range_amount(protein_low * 7, protein_high * 7),
            "mode": "range",
            "low": protein_low,
            "high": protein_high,
            "progress_target": protein_high,
        }
        if muscle_gain
        else {
            "key": "protein",
            "label": "Protein (min.)",
            "daily": amount(protein_low, "g", "≥ "),
            "weekly": amount(protein_low * 7, "g", "≥ "),
            "mode": "minimum",
            "low": protein_low,
            "high": None,
            "progress_target": protein_low,
        }
    )

    return (
        protein_target,
        {
            "key": "carbs",
            "label": "Karbohydrater",
            "daily": range_amount(carbs_low, carbs_high),
            "weekly": range_amount(carbs_low * 7, carbs_high * 7),
            "mode": "range",
            "low": carbs_low,
            "high": carbs_high,
            "progress_target": carbs_high,
        },
        {
            "key": "fat",
            "label": "Fett",
            "daily": range_amount(fat_low, fat_high),
            "weekly": range_amount(fat_low * 7, fat_high * 7),
            "mode": "range",
            "low": fat_low,
            "high": fat_high,
            "progress_target": fat_high,
        },
        {
            "key": "saturated_fat",
            "label": "Mettet fett (maks.)",
            "daily": amount(saturated_fat, "g", "≤ "),
            "weekly": amount(saturated_fat * 7, "g", "≤ "),
            "mode": "maximum",
            "low": None,
            "high": saturated_fat,
            "progress_target": saturated_fat,
        },
        {
            "key": "fiber",
            "label": "Fiber (min.)",
            "daily": amount(fiber, "g", "≥ "),
            "weekly": amount(fiber * 7, "g", "≥ "),
            "mode": "minimum",
            "low": fiber,
            "high": None,
            "progress_target": fiber,
        },
        {
            "key": "sugar",
            "label": "Fritt sukker (maks.)",
            "daily": amount(free_sugar, "g", "≤ "),
            "weekly": amount(free_sugar * 7, "g", "≤ "),
            "mode": "maximum",
            "low": None,
            "high": free_sugar,
            "progress_target": free_sugar,
        },
        {
            "key": "salt",
            "label": "Salt (maks.)",
            "daily": amount(5, "g", "≤ "),
            "weekly": amount(35, "g", "≤ "),
            "mode": "maximum",
            "low": None,
            "high": 5,
            "progress_target": 5,
        },
    )


def calculate_progress_rings(
    totals, calorie_targets, nutrient_targets, period_days=1
):
    targets = [
        {
            "key": "kcal",
            "label": "Kalorier",
            "unit": "kcal",
            "consumed": totals["kcal"],
            "target": calorie_targets["daily"] * period_days,
            "target_label": (
                f"{calorie_targets['daily'] * period_days} kcal"
            ),
            "mode": "maximum",
            "low": None,
            "high": calorie_targets["daily"] * period_days,
        },
        *[
            {
                **target,
                "unit": "g",
                "consumed": totals[target["key"]],
                "target": target["progress_target"] * period_days,
                "target_label": (
                    target["daily"] if period_days == 1 else target["weekly"]
                ),
                "low": (
                    target["low"] * period_days
                    if target["low"] is not None
                    else None
                ),
                "high": (
                    target["high"] * period_days
                    if target["high"] is not None
                    else None
                ),
            }
            for target in nutrient_targets
        ],
    ]
    for target in targets:
        consumed = target["consumed"]
        progress_target = target["target"]
        target["progress"] = min(100, consumed / progress_target * 100)
        if target["key"] == "sugar":
            target["status"] = "Sukkerloggen skiller ikke ut fritt sukker"
            target["over"] = False
        elif target["mode"] == "minimum":
            if consumed >= target["low"]:
                target["status"] = (
                    "Minimum nådd" if period_days == 1 else "Ukemålet nådd"
                )
            else:
                target["status"] = (
                    f"{target['low'] - consumed:.1f} g til minimum"
                    if period_days == 1
                    else f"{target['low'] - consumed:.1f} g til ukesmålet"
                )
            target["over"] = False
        elif target["mode"] == "range":
            if consumed < target["low"]:
                target["status"] = f"Under intervallet {target['target_label']}"
            elif consumed > target["high"]:
                target["status"] = f"Over intervallet {target['target_label']}"
            else:
                target["status"] = "Innenfor anbefalt intervall"
            target["over"] = consumed > target["high"]
        else:
            target["over"] = consumed > target["high"]
            target["status"] = (
                (
                    f"{consumed - target['high']:.1f} {target['unit']} "
                    f"{'over anbefalt maks' if period_days == 1 else 'over ukemaks'}"
                )
                if target["over"]
                else f"{target['high'] - consumed:.1f} {target['unit']} igjen til maks"
            )
    return targets


def calculate_water_ring(consumed_ml, target_ml, period_days=1):
    period_target = target_ml * period_days
    period = "dagsmålet" if period_days == 1 else "ukesmålet"
    progress = min(100, consumed_ml / period_target * 100)
    reached = consumed_ml >= period_target
    status = (
        f"{period.capitalize()} nådd"
        if reached
        else f"{period_target - consumed_ml} ml igjen til eget mål"
    )
    return {
        "key": "water",
        "label": "Vann",
        "unit": "ml",
        "consumed": consumed_ml,
        "target": period_target,
        "target_label": f"{period_target} ml",
        "progress": progress,
        "status": status,
        "over": False,
    }


def evaluate_weekly_water(consumed_ml, target_ml, is_complete):
    if not is_complete:
        return "Ufullstendig vannlogg – logg alle 7 dager", None
    if consumed_ml < target_ml * 7:
        return "Under ditt ukesmål", False
    return "Eget ukesmål nådd", True


def evaluate_target(consumed, target, is_complete):
    if not is_complete:
        return "Ufullstendig uke – logg alle 7 dager", None
    if target["key"] == "sugar":
        return "Kan ikke vurderes: loggen skiller ikke ut fritt sukker", None
    if target["mode"] == "minimum":
        met = consumed >= target["low"] * 7
        return ("Mål nådd" if met else "Under ukesmålet"), met
    if target["mode"] == "range":
        if consumed < target["low"] * 7:
            return "Under anbefalt område", False
        if consumed > target["high"] * 7:
            return "Over anbefalt område", False
        return "Innenfor anbefalt område", True
    met = consumed <= target["high"] * 7
    return ("Innenfor anbefalt maks" if met else "Over anbefalt maks"), met


def evaluate_weekly_calories(consumed, calorie_targets, is_complete):
    if not is_complete:
        return "Ufullstendig uke – logg alle 7 dager", None
    target = calorie_targets["weekly"]
    lower_bound = target * 0.9
    upper_bound = target * 1.1
    if consumed < lower_bound:
        return "Under ukesmålet", False
    if consumed > upper_bound:
        return "Over ukesmålet", False
    return "Innenfor 10 % av ukesmålet", True


def open_food_facts_number(nutriments, key):
    value = nutriments.get(f"{key}_100g")
    if value is None and key == "energy-kcal":
        energy_kj = nutriments.get("energy_100g")
        if energy_kj is not None:
            try:
                value = float(energy_kj) / 4.184
            except (TypeError, ValueError):
                return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


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


def hent_profil(database=None):
    should_close = database is None
    if database is None:
        database = get_db()
    row = database.execute(
        "SELECT * FROM nutrition_profile WHERE id = 1"
    ).fetchone()
    if should_close:
        database.close()
    return dict(row) if row else None


def render_profile_form(profile=None):
    return render_template(
        "profil.html",
        profile=profile or {},
        activity_levels={
            key: label for key, (label, _factor) in ACTIVITY_LEVELS.items()
        },
        goals=GOALS,
    )


@app.route("/profil", methods=["GET", "POST"])
def profil():
    if request.method == "GET":
        return render_profile_form(hent_profil())

    values = request.form
    try:
        age = int(values.get("age", ""))
        weight = parse_positive_number(values.get("weight_kg", ""))
        height = parse_positive_number(values.get("height_cm", ""))
        water_goal_ml = int(values.get("water_goal_ml", ""))
        goal_weight_value = values.get("goal_weight_kg", "").strip()
        goal_weight = (
            parse_positive_number(goal_weight_value) if goal_weight_value else None
        )
    except (TypeError, ValueError):
        flash("Fyll inn gyldig alder, høyde, vekt og vannmål.")
        return render_profile_form(values), 400

    sex = values.get("biological_sex", "")
    activity = values.get("activity_level", "")
    goal = values.get("goal", "")
    if not 18 <= age <= 100:
        flash("Kaloriberegningen er bare tilgjengelig for voksne fra 18 år.")
        return render_profile_form(values), 400
    if not 35 <= weight <= 300 or not 120 <= height <= 230:
        flash("Kontroller at høyde og vekt er innenfor gyldige verdier.")
        return render_profile_form(values), 400
    if not 250 <= water_goal_ml <= 10000:
        flash("Vannmålet må være mellom 250 og 10 000 ml per dag.")
        return render_profile_form(values), 400
    if goal_weight is not None and not 30 <= goal_weight <= 300:
        flash("Målvekten må være mellom 30 og 300 kg.")
        return render_profile_form(values), 400
    if sex not in ("female", "male") or activity not in ACTIVITY_LEVELS or goal not in GOALS:
        flash("Velg kjønn, aktivitetsnivå og mål fra listene.")
        return render_profile_form(values), 400
    if goal_weight is not None and (
        (goal == "lose" and goal_weight >= weight)
        or (goal == "gain" and goal_weight <= weight)
    ):
        flash("Målvekten må passe med om du vil gå ned eller opp i vekt.")
        return render_profile_form(values), 400

    database = get_db()
    database.execute(
        """
        INSERT INTO nutrition_profile
            (id, age, biological_sex, weight_kg, height_cm,
             activity_level, goal, goal_weight_kg, water_goal_ml)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            age = excluded.age,
            biological_sex = excluded.biological_sex,
            weight_kg = excluded.weight_kg,
            height_cm = excluded.height_cm,
            activity_level = excluded.activity_level,
            goal = excluded.goal,
            goal_weight_kg = excluded.goal_weight_kg,
            water_goal_ml = excluded.water_goal_ml
        """,
        (age, sex, weight, height, activity, goal, goal_weight, water_goal_ml),
    )
    database.commit()
    database.close()
    flash("Profilen din ble lagret.")
    return redirect(url_for("matlogg"))


@app.get("/matlogg")
def matlogg():
    valgt_dato = get_selected_date()
    valgt_dag = date.fromisoformat(valgt_dato)
    uke_start = valgt_dag - timedelta(days=valgt_dag.weekday())
    uke_slutt = uke_start + timedelta(days=6)
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
    water_entries = database.execute(
        """
        SELECT id, milliliters FROM water_entries
        WHERE consumed_on = ?
        ORDER BY id DESC
        """,
        (valgt_dato,),
    ).fetchall()
    water_total_ml = sum(entry["milliliters"] for entry in water_entries)
    totals = {
        nutrient: sum(entry[nutrient] for entry in oppforinger)
        for nutrient, _label, _unit in NUTRIENTS
    }
    weekly_nutrient_select = ", ".join(
        f"COALESCE(SUM(f.{nutrient} * e.grams / 100.0), 0) AS {nutrient}"
        for nutrient, _label, _unit in NUTRIENTS
    )
    weekly_totals_row = database.execute(
        f"""
        SELECT {weekly_nutrient_select}
        FROM food_entries AS e
        JOIN foods AS f ON f.id = e.food_id
        WHERE e.eaten_on BETWEEN ? AND ?
        """,
        (uke_start.isoformat(), uke_slutt.isoformat()),
    ).fetchone()
    weekly_totals = {
        nutrient: weekly_totals_row[nutrient]
        for nutrient, _label, _unit in NUTRIENTS
    }
    weekly_water_total_ml = database.execute(
        """
        SELECT COALESCE(SUM(milliliters), 0)
        FROM water_entries
        WHERE consumed_on BETWEEN ? AND ?
        """,
        (uke_start.isoformat(), uke_slutt.isoformat()),
    ).fetchone()[0]
    profile = hent_profil(database)
    calorie_targets = calculate_calorie_targets(profile) if profile else None
    nutrient_targets = (
        calculate_nutrient_targets(profile, calorie_targets) if profile else ()
    )
    daily_progress_rings = (
        calculate_progress_rings(totals, calorie_targets, nutrient_targets)
        if profile
        else ()
    )
    weekly_progress_rings = (
        calculate_progress_rings(
            weekly_totals, calorie_targets, nutrient_targets, period_days=7
        )
        if profile
        else ()
    )
    if profile and profile["water_goal_ml"]:
        daily_progress_rings.append(
            calculate_water_ring(water_total_ml, profile["water_goal_ml"])
        )
        weekly_progress_rings.append(
            calculate_water_ring(
                weekly_water_total_ml, profile["water_goal_ml"], period_days=7
            )
        )
    database.close()
    return render_template(
        "matlogg.html",
        valgt_dato=valgt_dato,
        matvarer=matvarer,
        oppforinger=oppforinger,
        totals=totals,
        nutrients=NUTRIENTS,
        profile=profile or {},
        calorie_targets=calorie_targets,
        nutrient_targets=nutrient_targets,
        daily_progress_rings=daily_progress_rings,
        weekly_progress_rings=weekly_progress_rings,
        week_start=uke_start.isoformat(),
        week_end=uke_slutt.isoformat(),
        water_entries=water_entries,
        water_total_ml=water_total_ml,
        activity_levels=ACTIVITY_LEVELS,
        goals=GOALS,
    )


@app.post("/matlogg/vann")
def registrer_vann():
    valgt_dato = request.form.get("dato", "")
    try:
        valgt_dato = date.fromisoformat(valgt_dato).isoformat()
        milliliters = int(request.form.get("milliliters", ""))
    except (TypeError, ValueError):
        flash("Velg en gyldig dato og oppgi vannmengden i hele milliliter.")
        return redirect(url_for("matlogg"))
    if not 1 <= milliliters <= 10000:
        flash("Vannmengden må være mellom 1 og 10 000 ml.")
        return redirect(url_for("matlogg", dato=valgt_dato))

    database = get_db()
    database.execute(
        "INSERT INTO water_entries (consumed_on, milliliters) VALUES (?, ?)",
        (valgt_dato, milliliters),
    )
    database.commit()
    database.close()
    flash(f"{milliliters} ml vann ble registrert.")
    return redirect(url_for("matlogg", dato=valgt_dato))


@app.post("/matlogg/vann/<int:entry_id>/slett")
def slett_vannregistrering(entry_id):
    valgt_dato = request.form.get("dato", date.today().isoformat())
    try:
        valgt_dato = date.fromisoformat(valgt_dato).isoformat()
    except (TypeError, ValueError):
        flash("Velg en gyldig dato.")
        return redirect(url_for("matlogg"))

    database = get_db()
    cursor = database.execute(
        "DELETE FROM water_entries WHERE id = ? AND consumed_on = ?",
        (entry_id, valgt_dato),
    )
    database.commit()
    database.close()
    if cursor.rowcount:
        flash("Vannregistreringen ble slettet.")
    else:
        flash("Vannregistreringen ble ikke funnet.")
    return redirect(url_for("matlogg", dato=valgt_dato))


@app.get("/ukesrapport")
def ukesrapport():
    valgt_dato = date.fromisoformat(get_selected_date())
    uke_start = valgt_dato - timedelta(days=valgt_dato.weekday())
    uke_slutt = uke_start + timedelta(days=6)
    database = get_db()
    summary = database.execute(
        """
        SELECT COUNT(DISTINCT e.eaten_on) AS logged_days,
               COUNT(e.id) AS entries,
               COALESCE(SUM(f.kcal * e.grams / 100.0), 0) AS kcal,
               COALESCE(SUM(f.protein * e.grams / 100.0), 0) AS protein,
               COALESCE(SUM(f.carbs * e.grams / 100.0), 0) AS carbs,
               COALESCE(SUM(f.fat * e.grams / 100.0), 0) AS fat,
               COALESCE(SUM(f.saturated_fat * e.grams / 100.0), 0) AS saturated_fat,
               COALESCE(SUM(f.fiber * e.grams / 100.0), 0) AS fiber,
               COALESCE(SUM(f.sugar * e.grams / 100.0), 0) AS sugar,
               COALESCE(SUM(f.salt * e.grams / 100.0), 0) AS salt
        FROM food_entries AS e
        JOIN foods AS f ON f.id = e.food_id
        WHERE e.eaten_on BETWEEN ? AND ?
        """,
        (uke_start.isoformat(), uke_slutt.isoformat()),
    ).fetchone()
    water_summary = database.execute(
        """
        SELECT COUNT(DISTINCT consumed_on) AS logged_days,
               COALESCE(SUM(milliliters), 0) AS milliliters
        FROM water_entries
        WHERE consumed_on BETWEEN ? AND ?
        """,
        (uke_start.isoformat(), uke_slutt.isoformat()),
    ).fetchone()
    profile = hent_profil(database)
    database.close()

    totals = {nutrient: summary[nutrient] for nutrient, _label, _unit in NUTRIENTS}
    logged_days = summary["logged_days"]
    complete = logged_days == 7
    calorie_targets = calculate_calorie_targets(profile) if profile else None
    nutrient_targets = (
        calculate_nutrient_targets(profile, calorie_targets) if profile else ()
    )
    report_rows = []
    outcomes = []
    if profile:
        calorie_status, calorie_met = evaluate_weekly_calories(
            totals["kcal"], calorie_targets, complete
        )
        outcomes.append(calorie_met)
        report_rows.append(
            {
                "label": "Kalorier",
                "unit": "kcal",
                "total": totals["kcal"],
                "average": totals["kcal"] / logged_days if logged_days else 0,
                "target": f"{calorie_targets['weekly']} kcal",
                "status": calorie_status,
            }
        )
        for target in nutrient_targets:
            status, met = evaluate_target(
                totals[target["key"]], target, complete
            )
            if met is not None:
                outcomes.append(met)
            report_rows.append(
                {
                    "label": target["label"],
                    "unit": "g",
                    "total": totals[target["key"]],
                    "average": (
                        totals[target["key"]] / logged_days if logged_days else 0
                    ),
                    "target": target["weekly"],
                    "status": status,
                }
            )
        if profile["water_goal_ml"]:
            water_status, water_met = evaluate_weekly_water(
                water_summary["milliliters"],
                profile["water_goal_ml"],
                water_summary["logged_days"] == 7,
            )
            if water_met is not None:
                outcomes.append(water_met)
            water_target = f"{profile['water_goal_ml'] * 7} ml"
        else:
            water_status = "Sett ditt eget vannmål i profilen"
            water_target = "Ikke satt"
        report_rows.append(
            {
                "label": "Vann",
                "unit": "ml",
                "total": water_summary["milliliters"],
                "average": (
                    water_summary["milliliters"] / water_summary["logged_days"]
                    if water_summary["logged_days"]
                    else 0
                ),
                "target": water_target,
                "status": water_status,
            }
        )

    if not profile:
        report_status = "Opprett profilen din for å sammenligne med ukesmål."
        report_status_kind = "incomplete"
    elif not complete:
        report_status = (
            f"Foreløpig rapport: du har registrert mat {logged_days} av 7 dager. "
            "Logg alle dager for en fullstendig sammenligning med ukesmålene."
        )
        report_status_kind = "incomplete"
    elif (
        profile["water_goal_ml"]
        and water_summary["logged_days"] != 7
    ):
        report_status = (
            "Matloggen er fullstendig, men vann er registrert "
            f"{water_summary['logged_days']} av 7 dager. "
            "Logg vann alle dager for en fullstendig vurdering av vannmålet."
        )
        report_status_kind = "incomplete"
    elif outcomes and all(outcomes):
        reached_targets = (
            "mat- og vannmålene"
            if profile["water_goal_ml"]
            else "matmålene"
        )
        report_status = (
            f"Du nådde de vurderbare {reached_targets}. Sukker kan ikke vurderes fordi "
            "matloggen ikke skiller mellom fritt og naturlig sukker."
        )
        report_status_kind = "success"
    else:
        report_status = (
            "Noen vurderbare næringsmål var utenfor anbefalingen. Se radene under "
            "for detaljer. Rapporten vurderer matinntak, ikke vektendring."
        )
        report_status_kind = "notice"

    return render_template(
        "ukesrapport.html",
        valgt_dato=valgt_dato.isoformat(),
        uke_start=uke_start.isoformat(),
        uke_slutt=uke_slutt.isoformat(),
        uke_forrige=(uke_start - timedelta(days=7)).isoformat(),
        uke_neste=(uke_start + timedelta(days=7)).isoformat(),
        logged_days=logged_days,
        water_logged_days=water_summary["logged_days"],
        water_total_ml=water_summary["milliliters"],
        entries=summary["entries"],
        report_rows=report_rows,
        report_status=report_status,
        report_status_kind=report_status_kind,
        has_profile=bool(profile),
    )


@app.get("/matlogg/sok-produkter")
def sok_produkter():
    query = request.args.get("q", "").strip()
    if len(query) < 2 or len(query) > 100:
        return jsonify(error="Skriv inn mellom 2 og 100 tegn for å søke."), 400

    parameters = urlencode(
        {
            "search_terms": query,
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "page_size": 10,
            "fields": "product_name,brands,quantity,code,nutriments",
        }
    )
    api_request = Request(
        f"https://world.openfoodfacts.org/cgi/search.pl?{parameters}",
        headers={"User-Agent": "mitt-flask-prosjekt/1.0 (food product search)"},
    )
    try:
        with urlopen(api_request, timeout=8) as response:
            payload = response.read()
        data = json.loads(payload)
    except HTTPError as error:
        app.logger.warning("Open Food Facts returned HTTP %s", error.code)
        if error.code in (429, 503):
            return jsonify(
                error="Open Food Facts begrenser søk akkurat nå. Vent litt og prøv igjen."
            ), 502
        return jsonify(error="Produktsøket er midlertidig utilgjengelig."), 502
    except (URLError, TimeoutError) as error:
        app.logger.warning("Open Food Facts request failed: %s", error)
        return jsonify(error="Fikk ikke kontakt med produktsøket. Prøv igjen senere."), 502
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        app.logger.warning("Open Food Facts returned invalid JSON: %s", error)
        return jsonify(error="Produktsøket returnerte ugyldige data."), 502

    if not isinstance(data, dict) or not isinstance(data.get("products"), list):
        app.logger.warning("Open Food Facts response is missing a product list")
        return jsonify(error="Produktsøket returnerte et ugyldig svar."), 502

    products = []
    nutrient_keys = {
        "kcal": "energy-kcal",
        "protein": "proteins",
        "carbs": "carbohydrates",
        "fat": "fat",
        "saturated_fat": "saturated-fat",
        "fiber": "fiber",
        "sugar": "sugars",
        "salt": "salt",
    }
    for product in data.get("products", []):
        if not isinstance(product, dict):
            continue
        name = product.get("product_name", "").strip()
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        code = str(product.get("code") or "").strip()
        nutriments = product.get("nutriments") or {}
        if not isinstance(nutriments, dict):
            nutriments = {}
        products.append(
            {
                "name": name[:100],
                "brands": str(product.get("brands") or "").strip()[:200],
                "quantity": str(product.get("quantity") or "").strip()[:100],
                "url": (
                    f"https://world.openfoodfacts.org/product/{quote(code, safe='')}"
                    if code
                    else "https://world.openfoodfacts.org"
                ),
                "nutrients": {
                    nutrient: open_food_facts_number(nutriments, key)
                    for nutrient, key in nutrient_keys.items()
                },
            }
        )
    return jsonify(products=products)


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


@app.route("/matlogg/mat/<int:matvare_id>/endre", methods=["GET", "POST"])
def endre_matvare(matvare_id):
    valgt_dato = request.values.get("dato", date.today().isoformat())
    try:
        valgt_dato = date.fromisoformat(valgt_dato).isoformat()
    except (TypeError, ValueError):
        flash("Velg en gyldig dato.")
        return redirect(url_for("matlogg"))

    database = get_db()
    matvare = database.execute(
        "SELECT * FROM foods WHERE id = ?", (matvare_id,)
    ).fetchone()
    if not matvare:
        database.close()
        abort(404)

    if request.method == "GET":
        database.close()
        return render_template(
            "endre_matvare.html",
            matvare=matvare,
            valgt_dato=valgt_dato,
            nutrients=NUTRIENTS,
        )

    navn = request.form.get("name", "").strip()
    beskrivelse = request.form.get("description", "").strip()
    if not navn or len(navn) > 100:
        database.close()
        flash("Skriv inn et navn på matvaren (maks 100 tegn).")
        return redirect(
            url_for("endre_matvare", matvare_id=matvare_id, dato=valgt_dato)
        )
    if len(beskrivelse) > 500:
        database.close()
        flash("Beskrivelsen kan ikke være lengre enn 500 tegn.")
        return redirect(
            url_for("endre_matvare", matvare_id=matvare_id, dato=valgt_dato)
        )

    try:
        verdier = {
            nutrient: parse_non_negative_number(request.form.get(nutrient, ""))
            for nutrient, _label, _unit in NUTRIENTS
        }
    except ValueError:
        database.close()
        flash("Næringsverdiene må være gyldige tall som er null eller større.")
        return redirect(
            url_for("endre_matvare", matvare_id=matvare_id, dato=valgt_dato)
        )

    updates = ", ".join(
        f"{nutrient} = ?" for nutrient, _label, _unit in NUTRIENTS
    )
    database.execute(
        f"UPDATE foods SET name = ?, description = ?, {updates} WHERE id = ?",
        (
            navn,
            beskrivelse,
            *(verdier[nutrient] for nutrient, _label, _unit in NUTRIENTS),
            matvare_id,
        ),
    )
    database.commit()
    database.close()
    flash(f"{navn} ble oppdatert.")
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