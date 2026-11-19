import os
import sqlite3
import tempfile
import unittest

from app import app, init_db


class AttendanceAppTests(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        app.config.update(
            TESTING=True,
            DATABASE=self.db_file.name,
            SECRET_KEY="test-secret",
        )
        with app.app_context():
            init_db()
        self.client = app.test_client()

    def tearDown(self):
        os.unlink(self.db_file.name)

    def sign_in(self, username, password):
        return self.client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=True,
        )

    def test_demo_student_can_view_attendance(self):
        response = self.sign_in("student1", "student123")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Subject breakdown", response.data)
        self.assertIn(b"Recent classes", response.data)

    def test_teacher_can_update_attendance_and_view_report(self):
        self.sign_in("teacher1", "teacher123")
        response = self.client.get("/teacher")
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            db = sqlite3.connect(app.config["DATABASE"])
            subject_id = db.execute("SELECT id FROM subjects LIMIT 1").fetchone()[0]
            students = db.execute(
                "SELECT student_id FROM enrollments WHERE subject_id = ?",
                (subject_id,),
            ).fetchall()
            db.close()
        day = "2024-01-15"
        response = self.client.post(
            f"/teacher/subject/{subject_id}",
            data={
                "date": day,
                **{f"status_{row[0]}": "present" for row in students},
            },
        )
        self.assertEqual(response.status_code, 302)
        report = self.client.get(f"/teacher/subject/{subject_id}/report")
        self.assertEqual(report.status_code, 200)
        self.assertIn(b"Attendance by student", report.data)

    def test_role_restrictions_and_invalid_login(self):
        response = self.sign_in("unknown", "wrong")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"do not match", response.data)
        self.sign_in("student1", "student123")
        self.assertEqual(self.client.get("/teacher").status_code, 403)


if __name__ == "__main__":
    unittest.main()
