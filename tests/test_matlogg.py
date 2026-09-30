import io
import json
import os
import sqlite3
import tempfile
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

import app as flask_app


class MatloggTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database = flask_app.app.config["DATABASE"]
        flask_app.app.config["DATABASE"] = os.path.join(
            self.temp_dir.name, "test.db"
        )
        flask_app.app.config["TESTING"] = True
        flask_app.init_db()
        self.client = flask_app.app.test_client()

    def tearDown(self):
        flask_app.app.config["DATABASE"] = self.original_database
        flask_app.app.config["TESTING"] = False
        self.temp_dir.cleanup()

    def add_food(self, **overrides):
        data = {
            "name": "Test-havregryn",
            "dato": "2026-09-30",
            "kcal": "370",
            "protein": "13",
            "carbs": "60",
            "fat": "7",
            "saturated_fat": "1.2",
            "fiber": "10",
            "sugar": "1",
            "salt": "0.01",
        }
        data.update(overrides)
        return self.client.post("/matlogg/mat", data=data, follow_redirects=True)

    def food_id(self, name):
        database = flask_app.get_db()
        food_id = database.execute(
            "SELECT id FROM foods WHERE name = ?", (name,)
        ).fetchone()["id"]
        database.close()
        return food_id

    def profile_data(self, **overrides):
        data = {
            "age": "30",
            "biological_sex": "male",
            "weight_kg": "80",
            "height_cm": "180",
            "activity_level": "moderate",
            "goal": "lose",
            "goal_weight_kg": "75",
            "water_goal_ml": "2000",
        }
        data.update(overrides)
        return data

    def test_first_visit_shows_profile_setup(self):
        response = self.client.get("/matlogg")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Sett opp profilen din".encode(), response.data)
        self.assertNotIn("Anbefalt per dag".encode(), response.data)

    def test_saves_profile_and_shows_daily_and_weekly_targets(self):
        response = self.client.post(
            "/profil",
            data=self.profile_data(),
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Anbefalt per dag".encode(), response.data)
        self.assertIn("2460 kcal".encode(), response.data)
        self.assertIn("17220 kcal".encode(), response.data)
        self.assertIn("Beregnet vedlikehold".encode(), response.data)

    def test_profile_can_be_updated(self):
        self.client.post("/profil", data=self.profile_data())

        response = self.client.post(
            "/profil",
            data=self.profile_data(goal="maintain"),
            follow_redirects=True,
        )

        self.assertIn("Holde vekten".encode(), response.data)
        database = flask_app.get_db()
        profile = database.execute(
            "SELECT goal FROM nutrition_profile WHERE id = 1"
        ).fetchone()
        database.close()
        self.assertEqual(profile["goal"], "maintain")

    def test_profile_saves_custom_water_goal(self):
        response = self.client.post(
            "/profil",
            data=self.profile_data(water_goal_ml="2750"),
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("2750 ml".encode(), response.data)
        database = flask_app.get_db()
        profile = database.execute(
            "SELECT water_goal_ml FROM nutrition_profile WHERE id = 1"
        ).fetchone()
        database.close()
        self.assertEqual(profile["water_goal_ml"], 2750)

    def test_profile_rejects_out_of_range_water_goal(self):
        response = self.client.post(
            "/profil",
            data=self.profile_data(water_goal_ml="100"),
            follow_redirects=True,
        )

        self.assertIn(
            "Vannmålet må være mellom 250 og 10 000 ml per dag".encode(),
            response.data,
        )

    def test_rejects_profile_for_people_under_18(self):
        response = self.client.post(
            "/profil",
            data=self.profile_data(age="17"),
            follow_redirects=True,
        )

        self.assertIn("bare tilgjengelig for voksne fra 18 år".encode(), response.data)
        database = flask_app.get_db()
        profile = database.execute(
            "SELECT id FROM nutrition_profile WHERE id = 1"
        ).fetchone()
        database.close()
        self.assertIsNone(profile)

    def test_calorie_targets_use_goal_and_weekly_total(self):
        profile = {
            "age": 30,
            "biological_sex": "male",
            "weight_kg": 80,
            "height_cm": 180,
            "activity_level": "moderate",
            "goal": "maintain",
        }

        targets = flask_app.calculate_calorie_targets(profile)

        self.assertEqual(targets["maintenance"], 2760)
        self.assertEqual(targets["daily"], 2760)
        self.assertEqual(targets["weekly"], 19320)

    def test_nutrient_targets_include_adult_macro_and_limit_estimates(self):
        profile = {
            "age": 30,
            "biological_sex": "male",
            "weight_kg": 80,
            "height_cm": 180,
            "activity_level": "moderate",
            "goal": "maintain",
        }
        calorie_targets = flask_app.calculate_calorie_targets(profile)

        targets = flask_app.calculate_nutrient_targets(profile, calorie_targets)

        self.assertEqual(
            [(target["daily"], target["weekly"]) for target in targets],
            [
                ("≥ 64 g", "≥ 448 g"),
                ("310–448 g", "2170–3136 g"),
                ("61–107 g", "427–749 g"),
                ("≤ 31 g", "≤ 217 g"),
                ("≥ 39 g", "≥ 273 g"),
                ("≤ 69 g", "≤ 483 g"),
                ("≤ 5 g", "≤ 35 g"),
            ],
        )

    def test_muscle_gain_protein_range_uses_current_weight_not_goal_weight(self):
        profile = {
            "age": 30,
            "biological_sex": "male",
            "weight_kg": 50,
            "height_cm": 165,
            "activity_level": "moderate",
            "goal": "gain",
            "goal_weight_kg": 75,
        }
        calorie_targets = flask_app.calculate_calorie_targets(profile)

        targets = flask_app.calculate_nutrient_targets(profile, calorie_targets)
        protein = targets[0]

        self.assertEqual(protein["label"], "Protein (muskelbygging)")
        self.assertEqual(protein["daily"], "70–100 g")
        self.assertEqual(protein["weekly"], "490–700 g")
        self.assertEqual((protein["low"], protein["high"]), (70, 100))

    def test_muscle_gain_protein_ring_tracks_range_towards_upper_target(self):
        profile = {
            "age": 30,
            "biological_sex": "male",
            "weight_kg": 50,
            "height_cm": 165,
            "activity_level": "moderate",
            "goal": "gain",
        }
        calories = flask_app.calculate_calorie_targets(profile)
        nutrients = flask_app.calculate_nutrient_targets(profile, calories)
        rings = flask_app.calculate_progress_rings(
            {
                "kcal": 1000,
                "protein": 85,
                "carbs": 200,
                "fat": 50,
                "saturated_fat": 5,
                "fiber": 15,
                "sugar": 10,
                "salt": 1,
            },
            calories,
            nutrients,
        )
        protein_ring = next(ring for ring in rings if ring["key"] == "protein")

        self.assertEqual(protein_ring["status"], "Innenfor anbefalt intervall")
        self.assertEqual(protein_ring["progress"], 85)

    def test_progress_rings_compare_daily_intake_with_targets(self):
        profile = {
            "age": 30,
            "biological_sex": "male",
            "weight_kg": 80,
            "height_cm": 180,
            "activity_level": "moderate",
            "goal": "maintain",
        }
        calories = flask_app.calculate_calorie_targets(profile)
        nutrients = flask_app.calculate_nutrient_targets(profile, calories)
        rings = flask_app.calculate_progress_rings(
            {
                "kcal": 1000,
                "protein": 40,
                "carbs": 300,
                "fat": 120,
                "saturated_fat": 32,
                "fiber": 10,
                "sugar": 20,
                "salt": 1,
            },
            calories,
            nutrients,
        )
        by_key = {ring["key"]: ring for ring in rings}

        self.assertEqual(len(rings), 8)
        self.assertEqual(by_key["protein"]["status"], "24.0 g til minimum")
        self.assertEqual(by_key["carbs"]["status"], "Under intervallet 310–448 g")
        self.assertTrue(by_key["fat"]["over"])
        self.assertEqual(by_key["saturated_fat"]["status"], "1.0 g over anbefalt maks")
        self.assertEqual(by_key["fiber"]["status"], "29.0 g til minimum")
        self.assertEqual(by_key["salt"]["progress"], 20)

    def test_progress_rings_update_after_food_is_logged(self):
        self.client.post("/profil", data=self.profile_data(goal="maintain"))
        food_id = self.food_id("Egg")

        response = self.client.post(
            "/matlogg/registrer",
            data={
                "dato": "2026-09-30",
                "food_id": str(food_id),
                "grams": "50",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'aria-label="Kalorier: 71.5 kcal av 2760 kcal"'.encode(),
            response.data,
        )
        self.assertIn(
            'aria-label="Protein (min.): 6.3 g av ≥ 64 g"'.encode(),
            response.data,
        )
        self.assertIn("DAG OG UKE".encode(), response.data)
        self.assertIn('data-progress-period-button="week"'.encode(), response.data)
        self.assertIn(
            'aria-label="Kalorier: 71.5 kcal av 2760 kcal"'.encode(),
            response.data,
        )
        self.assertIn(
            'aria-label="Kalorier: 71.5 kcal av 19320 kcal"'.encode(),
            response.data,
        )

    def test_weekly_progress_rings_sum_selected_calendar_week(self):
        self.client.post("/profil", data=self.profile_data(goal="maintain"))
        food_id = self.food_id("Egg")
        database = flask_app.get_db()
        for eaten_on, milliliters in (
            ("2026-09-28", 2500),
            ("2026-09-30", 1000),
        ):
            database.execute(
                "INSERT INTO food_entries (food_id, eaten_on, grams) VALUES (?, ?, ?)",
                (food_id, eaten_on, 50),
            )
            database.execute(
                "INSERT INTO water_entries (consumed_on, milliliters) VALUES (?, ?)",
                (eaten_on, milliliters),
            )
        database.commit()
        database.close()

        response = self.client.get("/matlogg?dato=2026-09-30")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'aria-label="Kalorier: 143.0 kcal av 19320 kcal"'.encode(),
            response.data,
        )
        self.assertIn(
            'aria-label="Vann: 3500.0 ml av 14000 ml"'.encode(),
            response.data,
        )
        self.assertIn("Uken 2026-09-28–2026-10-04".encode(), response.data)
        self.assertIn("static/js/nutrition-progress.js".encode(), response.data)

    def test_water_entries_update_daily_total_and_progress(self):
        self.client.post(
            "/profil",
            data=self.profile_data(water_goal_ml="2000"),
        )

        response = self.client.post(
            "/matlogg/vann",
            data={"dato": "2026-09-30", "milliliters": "500"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"500 ml", response.data)
        self.assertIn(
            'aria-label="Vann: 500.0 ml av 2000 ml"'.encode(),
            response.data,
        )
        self.assertIn("1500 ml igjen til eget mål".encode(), response.data)
        self.assertIn("2000 ml".encode(), response.data)

        other_day = self.client.get("/matlogg?dato=2026-10-01")
        self.assertIn("0 ml".encode(), other_day.data)

    def test_water_entry_can_be_deleted(self):
        self.client.post(
            "/matlogg/vann",
            data={"dato": "2026-09-30", "milliliters": "350"},
        )
        database = flask_app.get_db()
        entry_id = database.execute(
            "SELECT id FROM water_entries WHERE consumed_on = ?",
            ("2026-09-30",),
        ).fetchone()["id"]
        database.close()

        response = self.client.post(
            f"/matlogg/vann/{entry_id}/slett",
            data={"dato": "2026-09-30"},
            follow_redirects=True,
        )

        self.assertIn("Vannregistreringen ble slettet".encode(), response.data)
        self.assertIn("0 ml".encode(), response.data)

    def test_water_entry_rejects_invalid_amount(self):
        response = self.client.post(
            "/matlogg/vann",
            data={"dato": "2026-09-30", "milliliters": "10001"},
            follow_redirects=True,
        )

        self.assertIn("mellom 1 og 10 000 ml".encode(), response.data)
        database = flask_app.get_db()
        count = database.execute("SELECT COUNT(*) FROM water_entries").fetchone()[0]
        database.close()
        self.assertEqual(count, 0)

    def test_profile_page_displays_all_nutrient_target_rows(self):
        self.client.post("/profil", data=self.profile_data(goal="maintain"))

        response = self.client.get("/matlogg")

        for nutrient in (
            "Protein (min.)",
            "Karbohydrater",
            "Fett",
            "Mettet fett (maks.)",
            "Fiber (min.)",
            "Fritt sukker (maks.)",
            "Salt (maks.)",
            "Per uke",
        ):
            self.assertIn(nutrient.encode(), response.data)

    def test_weekly_report_summarizes_intake_and_compares_full_week(self):
        self.client.post("/profil", data=self.profile_data(goal="maintain"))
        food_id = self.food_id("Egg")
        database = flask_app.get_db()
        for day in range(28, 35):
            eaten_on = f"2026-09-{day:02d}" if day <= 30 else f"2026-10-{day - 30:02d}"
            database.execute(
                "INSERT INTO food_entries (food_id, eaten_on, grams) VALUES (?, ?, ?)",
                (food_id, eaten_on, 50),
            )
            database.execute(
                "INSERT INTO water_entries (consumed_on, milliliters) VALUES (?, ?)",
                (eaten_on, 2000),
            )
        database.commit()
        database.close()

        response = self.client.get("/ukesrapport?dato=2026-09-30")

        self.assertEqual(response.status_code, 200)
        self.assertIn("2026-09-28 til 2026-10-04".encode(), response.data)
        self.assertIn("mat 7/7 dager".encode(), response.data)
        self.assertIn("500.5 kcal".encode(), response.data)
        self.assertIn("Under ukesmålet".encode(), response.data)
        self.assertIn("14000.0 ml".encode(), response.data)
        self.assertIn("vann 7/7 dager".encode(), response.data)
        self.assertIn(
            "Kan ikke vurderes: loggen skiller ikke ut fritt sukker".encode(),
            response.data,
        )

    def test_weekly_report_marks_partial_week_without_goal_verdict(self):
        self.client.post("/profil", data=self.profile_data())
        self.client.post(
            "/matlogg/registrer",
            data={
                "dato": "2026-09-30",
                "food_id": str(self.food_id("Egg")),
                "grams": "50",
            },
        )

        response = self.client.get("/ukesrapport?dato=2026-10-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("mat 1/7 dager".encode(), response.data)
        self.assertIn("Logg alle dager".encode(), response.data)
        self.assertIn("Ufullstendig uke – logg alle 7 dager".encode(), response.data)
        self.assertIn("vann 0/7 dager".encode(), response.data)
        self.assertIn("Ufullstendig vannlogg".encode(), response.data)
        self.assertIn("2026-09-28 til 2026-10-04".encode(), response.data)

    def test_weekly_report_without_profile_explains_setup(self):
        response = self.client.get("/ukesrapport?dato=2026-09-30")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Opprett profilen din".encode(), response.data)
        self.assertNotIn("Innenfor 10 % av ukesmålet".encode(), response.data)

    def test_starter_foods_are_available_and_not_duplicated(self):
        flask_app.init_db()
        database = flask_app.get_db()
        count = database.execute(
            "SELECT COUNT(*) FROM foods WHERE name IN (?, ?, ?, ?, ?)",
            ("Egg", "Banan", "Eple", "Havregryn", "Melk (1,5 % fett)"),
        ).fetchone()[0]
        database.close()

        self.assertEqual(count, 5)

    def test_starter_food_serving_sizes_calculate_nutrients(self):
        for name, grams in (("Egg", "50"), ("Banan", "120")):
            response = self.client.post(
                "/matlogg/registrer",
                data={
                    "dato": "2026-09-30",
                    "food_id": str(self.food_id(name)),
                    "grams": grams,
                },
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)

        self.assertIn(b"71.5 kcal", response.data)
        self.assertIn(b"106.8 kcal", response.data)

    @patch("app.urlopen")
    def test_product_search_returns_mapped_open_food_facts_data(self, urlopen):
        payload = {
            "products": [
                {
                    "product_name": "Yoghurt naturell",
                    "brands": "Eksempel",
                    "quantity": "500 g",
                    "code": "12345",
                    "nutriments": {
                        "energy-kcal_100g": 62,
                        "proteins_100g": 4.2,
                        "carbohydrates_100g": 5.1,
                        "fat_100g": 2.3,
                        "saturated-fat_100g": 1.5,
                        "sugars_100g": 5,
                        "salt_100g": 0.1,
                    },
                }
            ]
        }
        urlopen.return_value = io.BytesIO(json.dumps(payload).encode())

        response = self.client.get("/matlogg/sok-produkter?q=yoghurt")

        self.assertEqual(response.status_code, 200)
        product = response.json["products"][0]
        self.assertEqual(product["name"], "Yoghurt naturell")
        self.assertEqual(product["nutrients"]["kcal"], 62)
        self.assertEqual(product["nutrients"]["protein"], 4.2)
        self.assertIsNone(product["nutrients"]["fiber"])
        self.assertEqual(
            product["url"], "https://world.openfoodfacts.org/product/12345"
        )
        request = urlopen.call_args.args[0]
        self.assertIn("yoghurt", request.full_url)
        self.assertEqual(
            request.get_header("User-agent"),
            "mitt-flask-prosjekt/1.0 (food product search)",
        )

    @patch("app.urlopen")
    def test_product_search_reports_provider_failure(self, urlopen):
        urlopen.side_effect = URLError("offline")

        response = self.client.get("/matlogg/sok-produkter?q=yoghurt")

        self.assertEqual(response.status_code, 502)
        self.assertIn("Fikk ikke kontakt".encode(), response.data)

    @patch("app.urlopen")
    def test_product_search_explains_provider_rate_limit(self, urlopen):
        error = HTTPError(
            "https://world.openfoodfacts.org",
            503,
            "Service Unavailable",
            {},
            None,
        )
        urlopen.side_effect = error

        response = self.client.get("/matlogg/sok-produkter?q=yoghurt")

        self.assertEqual(response.status_code, 502)
        self.assertIn("begrenser søk akkurat nå", response.json["error"])
        error.close()

    @patch("app.urlopen")
    def test_product_search_rejects_short_query_without_calling_provider(self, urlopen):
        response = self.client.get("/matlogg/sok-produkter?q=a")

        self.assertEqual(response.status_code, 400)
        urlopen.assert_not_called()

    def test_records_food_and_calculates_daily_totals(self):
        response = self.add_food(description="Økologiske, lettkokte havregryn")
        self.assertIn("Test-havregryn ble lagt til".encode(), response.data)

        response = self.client.post(
            "/matlogg/registrer",
            data={
                "dato": "2026-09-30",
                "food_id": str(self.food_id("Test-havregryn")),
                "grams": "150",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"555.0 kcal", response.data)
        self.assertIn(b"19.5 g", response.data)
        self.assertIn("Økologiske, lettkokte havregryn".encode(), response.data)

    def test_edits_food_details_and_updates_logged_nutrition(self):
        self.add_food()
        food_id = self.food_id("Test-havregryn")
        self.client.post(
            "/matlogg/registrer",
            data={
                "dato": "2026-09-30",
                "food_id": str(food_id),
                "grams": "100",
            },
        )

        response = self.client.get(
            f"/matlogg/mat/{food_id}/endre?dato=2026-09-30"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"370.0", response.data)

        response = self.client.post(
            f"/matlogg/mat/{food_id}/endre",
            data={
                "dato": "2026-09-30",
                "name": "Oppdatert havregryn",
                "description": "Ny beskrivelse",
                "kcal": "400",
                "protein": "15",
                "carbs": "65",
                "fat": "8",
                "saturated_fat": "1.5",
                "fiber": "11",
                "sugar": "2",
                "salt": "0.02",
            },
            follow_redirects=True,
        )

        self.assertIn("Oppdatert havregryn ble oppdatert".encode(), response.data)
        self.assertIn(b"400.0 kcal", response.data)
        self.assertIn("Ny beskrivelse".encode(), response.data)

    def test_rejects_invalid_food_edit(self):
        self.add_food()
        food_id = self.food_id("Test-havregryn")
        response = self.client.post(
            f"/matlogg/mat/{food_id}/endre",
            data={
                "dato": "2026-09-30",
                "name": "Oppdatert havregryn",
                "description": "",
                "kcal": "-1",
                "protein": "13",
                "carbs": "60",
                "fat": "7",
                "saturated_fat": "1.2",
                "fiber": "10",
                "sugar": "1",
                "salt": "0.01",
            },
            follow_redirects=True,
        )

        self.assertIn("Næringsverdiene må være gyldige tall".encode(), response.data)
        database = flask_app.get_db()
        food = database.execute(
            "SELECT name, kcal FROM foods WHERE id = ?", (food_id,)
        ).fetchone()
        database.close()
        self.assertEqual(food["name"], "Test-havregryn")
        self.assertEqual(food["kcal"], 370)

    def test_adds_description_column_to_existing_food_database(self):
        legacy_database = os.path.join(self.temp_dir.name, "legacy.db")
        original_database = flask_app.app.config["DATABASE"]
        flask_app.app.config["DATABASE"] = legacy_database
        database = sqlite3.connect(legacy_database)
        database.execute(
            """
            CREATE TABLE foods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kcal REAL NOT NULL,
                protein REAL NOT NULL,
                carbs REAL NOT NULL,
                fat REAL NOT NULL,
                saturated_fat REAL NOT NULL,
                fiber REAL NOT NULL,
                sugar REAL NOT NULL,
                salt REAL NOT NULL
            )
            """
        )
        database.commit()
        database.close()

        try:
            flask_app.init_db()
        finally:
            flask_app.app.config["DATABASE"] = original_database

        database = sqlite3.connect(legacy_database)
        columns = {
            column[1] for column in database.execute("PRAGMA table_info(foods)")
        }
        database.close()

        self.assertIn("description", columns)

    def test_adds_water_goal_and_entry_table_to_existing_database(self):
        legacy_database = os.path.join(self.temp_dir.name, "legacy_profile.db")
        original_database = flask_app.app.config["DATABASE"]
        flask_app.app.config["DATABASE"] = legacy_database
        database = sqlite3.connect(legacy_database)
        database.execute(
            """
            CREATE TABLE nutrition_profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                age INTEGER NOT NULL,
                biological_sex TEXT NOT NULL,
                weight_kg REAL NOT NULL,
                height_cm REAL NOT NULL,
                activity_level TEXT NOT NULL,
                goal TEXT NOT NULL,
                goal_weight_kg REAL
            )
            """
        )
        database.execute(
            """
            INSERT INTO nutrition_profile
            VALUES (1, 30, 'male', 80, 180, 'moderate', 'maintain', NULL)
            """
        )
        database.commit()
        database.close()

        try:
            flask_app.init_db()
        finally:
            flask_app.app.config["DATABASE"] = original_database

        database = sqlite3.connect(legacy_database)
        columns = {
            column[1]
            for column in database.execute("PRAGMA table_info(nutrition_profile)")
        }
        water_entries = database.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'water_entries'"
        ).fetchone()
        profile_water_goal = database.execute(
            "SELECT water_goal_ml FROM nutrition_profile WHERE id = 1"
        ).fetchone()[0]
        database.close()

        self.assertIn("water_goal_ml", columns)
        self.assertIsNotNone(water_entries)
        self.assertIsNone(profile_water_goal)

    def test_rejects_negative_nutrition_values(self):
        response = self.add_food(kcal="-1")

        self.assertIn("Næringsverdiene må være gyldige tall".encode(), response.data)
        database = flask_app.get_db()
        count = database.execute(
            "SELECT COUNT(*) FROM foods WHERE name = ?", ("Test-havregryn",)
        ).fetchone()[0]
        database.close()
        self.assertEqual(count, 0)

    def test_food_entries_are_filtered_by_date(self):
        self.add_food()
        self.client.post(
            "/matlogg/registrer",
            data={
                "dato": "2026-09-30",
                "food_id": str(self.food_id("Test-havregryn")),
                "grams": "100",
            },
        )

        response = self.client.get("/matlogg?dato=2026-10-01")

        self.assertIn("Ingen matvarer er registrert denne dagen".encode(), response.data)
        self.assertIn(b"0.0 kcal", response.data)

    def test_deleting_entry_updates_daily_totals(self):
        self.add_food()
        self.client.post(
            "/matlogg/registrer",
            data={
                "dato": "2026-09-30",
                "food_id": str(self.food_id("Test-havregryn")),
                "grams": "100",
            },
        )
        database = flask_app.get_db()
        entry_id = database.execute(
            "SELECT id FROM food_entries"
        ).fetchone()["id"]
        database.close()

        response = self.client.post(
            f"/matlogg/oppforing/{entry_id}/slett",
            data={"dato": "2026-09-30"},
            follow_redirects=True,
        )

        self.assertIn(b"0.0 kcal", response.data)
        self.assertIn("Matregistreringen ble slettet".encode(), response.data)


if __name__ == "__main__":
    unittest.main()
