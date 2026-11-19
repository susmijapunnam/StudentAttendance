import os
import sqlite3
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


ROOT = Path(__file__).resolve().parent
INSTANCE = ROOT / "instance"
INSTANCE.mkdir(exist_ok=True)

app = Flask(__name__, instance_path=str(INSTANCE))
app.config.update(
    SECRET_KEY=os.environ.get("ATTENDANCE_SECRET_KEY", "local-development-key"),
    DATABASE=str(INSTANCE / "attendance.db"),
)


@app.context_processor
def template_dates():
    today = date.today()
    return {
        "today_iso": today.isoformat(),
        "today_label": f"{today.strftime('%A, %B')} {today.day}",
    }


@app.template_filter("pretty_date")
def pretty_date(value):
    parsed = date.fromisoformat(value)
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    database = current_app.config["DATABASE"]
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(database)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('student', 'teacher'))
        );
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            teacher_id INTEGER NOT NULL REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS enrollments (
            student_id INTEGER NOT NULL REFERENCES users(id),
            subject_id INTEGER NOT NULL REFERENCES subjects(id),
            PRIMARY KEY (student_id, subject_id)
        );
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id),
            subject_id INTEGER NOT NULL REFERENCES subjects(id),
            date TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('present', 'absent')),
            UNIQUE (student_id, subject_id, date)
        );
        """
    )

    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        def add_user(name, username, password, role):
            cursor = db.execute(
                "INSERT INTO users (name, username, password_hash, role) VALUES (?, ?, ?, ?)",
                (
                    name,
                    username,
                    generate_password_hash(password, method="pbkdf2:sha256"),
                    role,
                ),
            )
            return cursor.lastrowid

        teacher_id = add_user("Priya Sharma", "teacher1", "teacher123", "teacher")
        students = [
            add_user("Anita Reddy", "student1", "student123", "student"),
            add_user("Kiran Rao", "student2", "student123", "student"),
            add_user("Ravi Kumar", "student3", "student123", "student"),
            add_user("Sara Thomas", "student4", "student123", "student"),
        ]
        for subject_name in ("Mathematics", "Physics", "Computer Science"):
            subject_id = db.execute(
                "INSERT INTO subjects (name, teacher_id) VALUES (?, ?)",
                (subject_name, teacher_id),
            ).lastrowid
            db.executemany(
                "INSERT INTO enrollments (student_id, subject_id) VALUES (?, ?)",
                [(student_id, subject_id) for student_id in students],
            )
            for class_offset in range(1, 6):
                class_date = (date.today() - timedelta(days=class_offset)).isoformat()
                for student_index, student_id in enumerate(students):
                    is_present = (class_offset + student_index) % 4 != 0
                    db.execute(
                        """INSERT INTO attendance (student_id, subject_id, date, status)
                           VALUES (?, ?, ?, ?)""",
                        (
                            student_id,
                            subject_id,
                            class_date,
                            "present" if is_present else "absent",
                        ),
                    )
    db.commit()
    db.close()


def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def owned_subject(subject_id):
    subject = get_db().execute(
        "SELECT * FROM subjects WHERE id = ? AND teacher_id = ?",
        (subject_id, session["user_id"]),
    ).fetchone()
    if subject is None:
        abort(404)
    return subject


@app.route("/")
def index():
    if session.get("role") == "teacher":
        return redirect(url_for("teacher_dashboard"))
    if session.get("role") == "student":
        return redirect(url_for("student_dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.update(user_id=user["id"], name=user["name"], role=user["role"])
            return redirect(url_for("index"))
        flash("That username and password do not match.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/teacher")
@login_required("teacher")
def teacher_dashboard():
    db = get_db()
    teacher_id = session["user_id"]
    subjects = db.execute(
        """SELECT s.id, s.name, COUNT(DISTINCT e.student_id) AS students,
                  COUNT(DISTINCT CASE WHEN a.date = ? THEN a.student_id END) AS marked_today
           FROM subjects s
           LEFT JOIN enrollments e ON e.subject_id = s.id
           LEFT JOIN attendance a ON a.subject_id = s.id AND a.student_id = e.student_id
           WHERE s.teacher_id = ?
           GROUP BY s.id ORDER BY s.name""",
        (date.today().isoformat(), teacher_id),
    ).fetchall()
    total_students = db.execute(
        """SELECT COUNT(DISTINCT e.student_id)
           FROM subjects s JOIN enrollments e ON e.subject_id = s.id
           WHERE s.teacher_id = ?""",
        (teacher_id,),
    ).fetchone()[0]
    return render_template(
        "teacher_dashboard.html", subjects=subjects, total_students=total_students
    )


@app.route("/teacher/subject/<int:subject_id>", methods=["GET", "POST"])
@login_required("teacher")
def mark_attendance(subject_id):
    db = get_db()
    subject = owned_subject(subject_id)
    students = db.execute(
        """SELECT u.id, u.name FROM users u
           JOIN enrollments e ON e.student_id = u.id
           WHERE e.subject_id = ? ORDER BY u.name""",
        (subject_id,),
    ).fetchall()

    day = request.values.get("date", date.today().isoformat())
    try:
        selected_day = date.fromisoformat(day)
        if selected_day.isoformat() != day or selected_day > date.today():
            raise ValueError
    except ValueError:
        flash("Choose a valid date no later than today.", "error")
        return redirect(url_for("mark_attendance", subject_id=subject_id))

    if request.method == "POST":
        attendance_rows = []
        for student in students:
            status = request.form.get(f"status_{student['id']}")
            if status not in ("present", "absent"):
                flash("Choose present or absent for every student.", "error")
                break
            attendance_rows.append((student["id"], subject_id, day, status))
        else:
            db.executemany(
                """INSERT INTO attendance (student_id, subject_id, date, status)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT (student_id, subject_id, date)
                   DO UPDATE SET status = excluded.status""",
                attendance_rows,
            )
            db.commit()
            flash(
                f"Attendance saved for {selected_day.strftime('%B')} {selected_day.day}, "
                f"{selected_day.year}.",
                "success",
            )
            return redirect(
                url_for("mark_attendance", subject_id=subject_id, date=day)
            )

    existing = {
        row["student_id"]: row["status"]
        for row in db.execute(
            "SELECT student_id, status FROM attendance WHERE subject_id = ? AND date = ?",
            (subject_id, day),
        )
    }
    return render_template(
        "mark_attendance.html",
        subject=subject,
        students=students,
        existing=existing,
        day=day,
    )


@app.route("/teacher/subject/<int:subject_id>/report")
@login_required("teacher")
def report(subject_id):
    subject = owned_subject(subject_id)
    rows = get_db().execute(
        """SELECT u.name,
                  COALESCE(SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END), 0)
                    AS present,
                  COUNT(a.id) AS total
           FROM users u
           JOIN enrollments e ON e.student_id = u.id
           LEFT JOIN attendance a
             ON a.student_id = u.id AND a.subject_id = e.subject_id
           WHERE e.subject_id = ?
           GROUP BY u.id ORDER BY u.name""",
        (subject_id,),
    ).fetchall()
    return render_template("report.html", subject=subject, rows=rows)


@app.route("/student")
@login_required("student")
def student_dashboard():
    db = get_db()
    student_id = session["user_id"]
    summary = db.execute(
        """SELECT s.id, s.name,
                  COALESCE(SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END), 0)
                    AS present,
                  COUNT(a.id) AS total
           FROM enrollments e JOIN subjects s ON s.id = e.subject_id
           LEFT JOIN attendance a
             ON a.subject_id = s.id AND a.student_id = e.student_id
           WHERE e.student_id = ? GROUP BY s.id ORDER BY s.name""",
        (student_id,),
    ).fetchall()
    records = db.execute(
        """SELECT a.date, a.status, s.name AS subject
           FROM attendance a JOIN subjects s ON s.id = a.subject_id
           WHERE a.student_id = ?
           ORDER BY a.date DESC, s.name""",
        (student_id,),
    ).fetchall()
    total_present = sum(row["present"] for row in summary)
    total_classes = sum(row["total"] for row in summary)
    overall_percentage = round(total_present / total_classes * 100) if total_classes else 0
    return render_template(
        "student_dashboard.html",
        summary=summary,
        records=records,
        overall_percentage=overall_percentage,
        total_classes=total_classes,
        total_present=total_present,
    )


@app.errorhandler(403)
def forbidden(_error):
    return (
        render_template(
            "error.html", code=403, message="You don't have access to this page."
        ),
        403,
    )


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="We couldn't find that page."), 404


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
