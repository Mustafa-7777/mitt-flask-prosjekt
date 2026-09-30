import os
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
            "name": "Havregryn",
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

    def test_records_food_and_calculates_daily_totals(self):
        response = self.add_food()
        self.assertIn("Havregryn ble lagt til".encode(), response.data)

        response = self.client.post(
            "/matlogg/registrer",
            data={"dato": "2026-09-30", "food_id": "1", "grams": "150"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"555.0 kcal", response.data)
        self.assertIn(b"19.5 g", response.data)

    def test_rejects_negative_nutrition_values(self):
        response = self.add_food(kcal="-1")

        self.assertIn("Næringsverdiene må være gyldige tall".encode(), response.data)
        database = flask_app.get_db()
        count = database.execute("SELECT COUNT(*) FROM foods").fetchone()[0]
        database.close()
        self.assertEqual(count, 0)

    def test_food_entries_are_filtered_by_date(self):
        self.add_food()
        self.client.post(
            "/matlogg/registrer",
            data={"dato": "2026-09-30", "food_id": "1", "grams": "100"},
        )

        response = self.client.get("/matlogg?dato=2026-10-01")

        self.assertIn("Ingen matvarer er registrert denne dagen".encode(), response.data)
        self.assertIn(b"0.0 kcal", response.data)

    def test_deleting_entry_updates_daily_totals(self):
        self.add_food()
        self.client.post(
            "/matlogg/registrer",
            data={"dato": "2026-09-30", "food_id": "1", "grams": "100"},
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
