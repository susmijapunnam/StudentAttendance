# Attendly — Student Attendance Management

A small Flask and SQLite project for tracking class attendance. Teachers can
mark or update daily attendance and view class reports. Students can see their
overall attendance, subject breakdown, and class history.

## Run locally

```bash
cd student-attendance-system
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The SQLite database is
created at `instance/attendance.db` on first run and populated with demo data.

## Demo accounts

| Role | Username | Password |
| --- | --- | --- |
| Teacher | `teacher1` | `teacher123` |
| Student | `student1` | `student123` |

Other seeded students use `student2`, `student3`, or `student4`, each with the
password `student123`.

## Run tests

```bash
python -m unittest discover -s tests -v
```

Set `ATTENDANCE_SECRET_KEY` to a unique secret before deploying. The built-in
key and demo credentials are intended only for local development.
