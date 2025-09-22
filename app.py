from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_TYPE'] = "filesystem"

DB_PATH = "fee.db"

# -------------------- Database --------------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    with get_db_connection() as conn:
        cur = conn.cursor()
        # Branches table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS branches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """)
        # Sections table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                branch_id INTEGER,
                name TEXT,
                UNIQUE(branch_id, name),
                FOREIGN KEY(branch_id) REFERENCES branches(id) ON DELETE CASCADE
            )
        """)
        # Students table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS students (
                sid TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                total REAL NOT NULL,
                balance REAL NOT NULL,
                password TEXT NOT NULL,
                branch_id INTEGER,
                section_id INTEGER,
                admin_request INTEGER DEFAULT 0,
                FOREIGN KEY(branch_id) REFERENCES branches(id) ON DELETE SET NULL,
                FOREIGN KEY(section_id) REFERENCES sections(id) ON DELETE SET NULL
            )
        """)
        # Insert default branches if not exist
        for branch in ["CSE", "ECE", "EEE", "MECH"]:
            cur.execute("INSERT OR IGNORE INTO branches (name) VALUES (?)", (branch,))
        conn.commit()

init_db()

# -------------------- Admin --------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = generate_password_hash("admin123")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["admin"] = True
            flash("Admin login successful ✅", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid admin credentials ❌", "danger")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    flash("Logged out successfully ✅", "success")
    return redirect(url_for("home"))

@app.route("/admin/logout_redirect")
def admin_logout_redirect():
    # Remove admin session
    session.pop("admin", None)
    flash("Logged out successfully ✅", "success")
    # Redirect to admin_dashboard after logout
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/dashboard")
def admin_dashboard():
    if "admin" not in session:
        return redirect(url_for("admin_login"))
    with get_db_connection() as conn:
        branches = conn.execute("SELECT * FROM branches").fetchall()
        requested_students = conn.execute("SELECT * FROM students WHERE admin_request=1").fetchall()
    return render_template("admin_dashboard.html", branches=branches, requested_students=requested_students)

# -------------------- Admin Fee Payment --------------------
@app.route("/admin/pay_fee/<sid>", methods=["POST"])
def admin_pay_fee(sid):
    if "admin" not in session:
        return redirect(url_for("admin_login"))
    amount = float(request.form.get("amount", 0))
    with get_db_connection() as conn:
        student = conn.execute("SELECT * FROM students WHERE sid=?", (sid,)).fetchone()
        if not student:
            flash("Student not found ❌", "danger")
            return redirect(url_for("admin_dashboard"))
        new_balance = max(0, student['balance'] - amount)
        conn.execute("UPDATE students SET balance=?, admin_request=0 WHERE sid=?", (new_balance, sid))
        conn.commit()
        flash(f"₹{amount} has been paid for {student['name']} ✅", "success")
    return redirect(url_for("admin_dashboard"))

# -------------------- Sections --------------------
@app.route("/admin/add_section/<int:branch_id>", methods=["GET", "POST"])
def add_section(branch_id):
    if "admin" not in session:
        return redirect(url_for("admin_login"))
    with get_db_connection() as conn:
        branch = conn.execute("SELECT * FROM branches WHERE id=?", (branch_id,)).fetchone()
        if not branch:
            flash("Branch not found ❌", "danger")
            return redirect(url_for("admin_dashboard"))
        sections = conn.execute("SELECT * FROM sections WHERE branch_id=?", (branch_id,)).fetchall()
        if request.method == "POST":
            section_name = request.form.get("section_name", "").strip()
            if not section_name:
                flash("Section name cannot be empty ❌", "danger")
                return redirect(url_for("add_section", branch_id=branch_id))
            try:
                conn.execute("INSERT INTO sections (branch_id, name) VALUES (?, ?)", (branch_id, section_name))
                conn.commit()
                flash(f"Section '{section_name}' added to {branch['name']} ✅", "success")
            except sqlite3.IntegrityError:
                flash("Section already exists ❌", "danger")
            return redirect(url_for("add_section", branch_id=branch_id))
    return render_template("add_section.html", branch=branch, sections=sections)

# -------------------- Students --------------------
@app.route("/admin/add_student/<int:branch_id>/<int:section_id>", methods=["GET", "POST"])
def admin_add_student(branch_id, section_id):
    if "admin" not in session:
        return redirect(url_for("admin_login"))
    with get_db_connection() as conn:
        branch = conn.execute("SELECT * FROM branches WHERE id=?", (branch_id,)).fetchone()
        section = conn.execute("SELECT * FROM sections WHERE id=?", (section_id,)).fetchone()
        branches = conn.execute("SELECT * FROM branches").fetchall()
        if not branch or not section:
            flash("Invalid branch or section ❌", "danger")
            return redirect(url_for("admin_dashboard"))
        if request.method == "POST":
            sid = request.form.get("sid", "").strip()
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()
            phone = request.form.get("phone", "").strip()
            total = float(request.form.get("total", 0))
            paid = float(request.form.get("paid", 0))
            balance = total - paid
            password = request.form.get("password", "")
            if not sid or not name or not password:
                flash("Student ID, Name, and Password are required ❌", "danger")
                return redirect(url_for("admin_add_student", branch_id=branch_id, section_id=section_id))
            hashed_password = generate_password_hash(password)
            try:
                conn.execute(
                    "INSERT INTO students (sid,name,email,phone,total,balance,branch_id,section_id,password) VALUES (?,?,?,?,?,?,?,?,?)",
                    (sid, name, email, phone, total, balance, branch_id, section_id, hashed_password)
                )
                conn.commit()
                flash("Student added successfully ✅", "success")
            except sqlite3.IntegrityError:
                conn.execute(
                    "UPDATE students SET name=?, email=?, phone=?, total=?, balance=?, password=?, branch_id=?, section_id=? WHERE sid=?",
                    (name, email, phone, total, balance, hashed_password, branch_id, section_id, sid)
                )
                conn.commit()
                flash("Student updated successfully 🔄", "info")
            return redirect(url_for("admin_add_student", branch_id=branch_id, section_id=section_id))
    return render_template("admin_add_student.html", branch=branch, section=section, branches=branches)

@app.route("/admin/view_students/<int:branch_id>/<int:section_id>")
def view_students(branch_id, section_id):
    if "admin" not in session:
        return redirect(url_for("admin_login"))
    with get_db_connection() as conn:
        students = conn.execute("SELECT * FROM students WHERE branch_id=? AND section_id=?", (branch_id, section_id)).fetchall()
        branch = conn.execute("SELECT * FROM branches WHERE id=?", (branch_id,)).fetchone()
        section = conn.execute("SELECT * FROM sections WHERE id=?", (section_id,)).fetchone()
    return render_template("view_students.html", students=students, branch=branch, section=section)

@app.route("/admin/delete_student/<sid>")
def delete_student(sid):
    if "admin" not in session:
        return redirect(url_for("admin_login"))
    with get_db_connection() as conn:
        conn.execute("DELETE FROM students WHERE sid=?", (sid,))
        conn.commit()
    flash("Student deleted successfully 🗑️", "warning")
    return redirect(url_for("admin_dashboard"))

# -------------------- Student Login --------------------
@app.route("/student/login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        sid = request.form.get("sid", "").strip()
        password = request.form.get("password", "")
        with get_db_connection() as conn:
            student = conn.execute("SELECT * FROM students WHERE sid=?", (sid,)).fetchone()
        if student and check_password_hash(student['password'], password):
            session["student_id"] = student['sid']
            return redirect(url_for("student_dashboard"))
        flash("Invalid Student ID or Password ❌", "danger")
    return render_template("student_login.html")

@app.route("/student/dashboard")
def student_dashboard():
    if "student_id" not in session:
        return redirect(url_for("student_login"))
    sid = session["student_id"]
    with get_db_connection() as conn:
        student = conn.execute("SELECT * FROM students WHERE sid=?", (sid,)).fetchone()
    if not student:
        session.pop("student_id", None)
        flash("Student not found ❌", "danger")
        return redirect(url_for("student_login"))
    student_dict = dict(student)
    student_dict['paid_amount'] = student_dict['total'] - student_dict['balance']
    student_dict['due_amount'] = student_dict['balance']
    return render_template("student_dashboard.html", student=student_dict)

@app.route("/student/pay")
def student_pay():
    if "student_id" not in session:
        return redirect(url_for("student_login"))
    sid = session["student_id"]
    with get_db_connection() as conn:
        student = conn.execute("SELECT * FROM students WHERE sid=?", (sid,)).fetchone()
    return render_template("pay.html", student=student)

@app.route("/payment_success", methods=["POST"])
def payment_success():
    sid = session.get("student_id")
    if sid:
        with get_db_connection() as conn:
            conn.execute("UPDATE students SET balance=0, admin_request=0 WHERE sid=?", (sid,))
            conn.commit()
            student = conn.execute("SELECT * FROM students WHERE sid=?", (sid,)).fetchone()
        student_dict = dict(student)
        student_dict['paid_amount'] = student_dict['total'] - student_dict['balance']
        student_dict['due_amount'] = student_dict['balance']
        flash("Payment Successful ✅", "success")
        return render_template("student_dashboard.html", student=student_dict)
    flash("Session expired. Please log in again ❌", "danger")
    return redirect(url_for("student_login"))

@app.route("/student/request_admin_payment", methods=["POST"])
def request_admin_payment():
    if "student_id" not in session:
        return redirect(url_for("student_login"))
    sid = session["student_id"]
    with get_db_connection() as conn:
        conn.execute("UPDATE students SET admin_request=1 WHERE sid=?", (sid,))
        conn.commit()
    flash("Admin payment request sent ✅", "success")
    return redirect(url_for("student_dashboard"))

@app.route("/student/logout")
def student_logout():
    session.pop("student_id", None)
    flash("Logged out ✅", "success")
    return redirect(url_for("home"))

# -------------------- Home --------------------
@app.route("/")
def home():
    return render_template("home.html")

# -------------------- Run App --------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
