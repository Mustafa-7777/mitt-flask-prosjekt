import os
import sqlite3
import tempfile
import unittest

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
