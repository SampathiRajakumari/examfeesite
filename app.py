from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import razorpay
import os

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_TYPE'] = "filesystem"

DB_PATH = "fee.db"

# -------------------- Razorpay Config --------------------
RAZORPAY_KEY_ID = "rzp_test_xxxxxxxx"     # 🔹 Replace with your Key ID
RAZORPAY_KEY_SECRET = "xxxxxxxxxxxxxxx"   # 🔹 Replace with your Key Secret
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# -------------------- Database --------------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        cur = conn.cursor()

        # Branch table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS branches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """)

        # Section table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                branch_id INTEGER,
                name TEXT,
                UNIQUE(branch_id, name),
                FOREIGN KEY(branch_id) REFERENCES branches(id)
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
                admin_request INTEGER DEFAULT 0
            )
        """)

        # Enforce foreign keys
        cur.execute("PRAGMA foreign_keys=ON")

        # Insert default branches
        branches = ["CSE", "ECE", "Civil", "EEE"]
        for b in branches:
            cur.execute("INSERT OR IGNORE INTO branches (name) VALUES (?)", (b,))

        conn.commit()

init_db()

# -------------------- Admin --------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = generate_password_hash("admin123")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid admin credentials", "danger")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    flash("Logged out successfully", "success")
    return redirect(url_for("home"))

@app.route("/admin/dashboard")
def admin_dashboard():
    if "admin" not in session:
        return redirect(url_for("admin_login"))
    with get_db_connection() as conn:
        branches = conn.execute("SELECT * FROM branches").fetchall()
        requested_students = conn.execute("SELECT * FROM students WHERE admin_request=1").fetchall()
    return render_template("admin_dashboard.html", branches=branches, requested_students=requested_students)

# -------------------- Admin Pay Fee --------------------
@app.route("/admin/pay_fee/<sid>", methods=["POST"])
def admin_pay_fee(sid):
    if "admin" not in session:
        return redirect(url_for("admin_login"))
    
    amount = float(request.form["amount"])
    
    with get_db_connection() as conn:
        student = conn.execute("SELECT balance FROM students WHERE sid=?", (sid,)).fetchone()
        if student:
            new_balance = student["balance"] - amount
            if new_balance <= 0:
                new_balance = 0
                admin_request = 0
            else:
                admin_request = 1
            conn.execute(
                "UPDATE students SET balance=?, admin_request=? WHERE sid=?",
                (new_balance, admin_request, sid)
            )
            conn.commit()
    flash(f"Paid ₹{amount} successfully ✅", "success")
    return redirect(url_for("admin_dashboard"))

# -------------------- Sections --------------------
@app.route("/admin/add_section/<int:branch_id>", methods=["GET", "POST"])
def add_section(branch_id):
    if "admin" not in session:
        return redirect(url_for("admin_login"))
    with get_db_connection() as conn:
        branch = conn.execute("SELECT * FROM branches WHERE id=?", (branch_id,)).fetchone()
        sections = conn.execute("SELECT * FROM sections WHERE branch_id=?", (branch_id,)).fetchall()
        if request.method == "POST":
            section_name = request.form["section_name"]
            try:
                conn.execute("INSERT INTO sections (branch_id,name) VALUES (?,?)", (branch_id, section_name))
                conn.commit()
                flash(f"Section {section_name} added to {branch['name']}", "success")
            except sqlite3.IntegrityError:
                flash("Section already exists!", "danger")
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
        if request.method == "POST":
            sid = request.form["sid"]
            name = request.form["name"]
            email = request.form["email"]
            phone = request.form["phone"]
            total = float(request.form["total"])
            paid = float(request.form.get("paid", 0))
            balance = total - paid
            raw_password = request.form["password"]
            hashed_password = generate_password_hash(raw_password)
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
    return render_template("admin_add_student.html", branch=branch, section=section)

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
    flash("Student deleted successfully", "warning")
    return redirect(url_for("admin_dashboard"))

# -------------------- Student Login --------------------
@app.route("/student/login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        sid = request.form["sid"]
        password = request.form["password"]
        with get_db_connection() as conn:
            student = conn.execute("SELECT * FROM students WHERE sid=?", (sid,)).fetchone()
        if student and check_password_hash(student['password'], password):
            session["student_id"] = student['sid']
            return redirect(url_for("student_dashboard"))
        else:
            flash("Invalid Student ID or Password", "danger")
    return render_template("student_login.html")

@app.route("/student/dashboard")
def student_dashboard():
    if "student_id" not in session:
        return redirect(url_for("student_login"))
    sid = session["student_id"]
    with get_db_connection() as conn:
        student = conn.execute("SELECT * FROM students WHERE sid=?", (sid,)).fetchone()
    if not student:
        flash("Student not found", "danger")
        return redirect(url_for("student_login"))
    student_dict = dict(student)
    student_dict['paid_amount'] = student_dict['total'] - student_dict['balance']
    student_dict['due_amount'] = student_dict['balance']
    return render_template("student_dashboard.html", student=student_dict, razorpay_key=RAZORPAY_KEY_ID)

@app.route("/student/request_admin_payment", methods=["POST"])
def request_admin_payment():
    if "student_id" not in session:
        return redirect(url_for("student_login"))
    sid = session["student_id"]
    with get_db_connection() as conn:
        conn.execute("UPDATE students SET admin_request=1 WHERE sid=?", (sid,))
        conn.commit()
    flash("Admin payment requested ✅", "success")
    return redirect(url_for("student_dashboard"))

@app.route("/student/logout")
def student_logout():
    session.pop("student_id", None)
    return redirect(url_for("home"))

# -------------------- Online Payment --------------------
@app.route("/student/pay", methods=["GET", "POST"])
def student_pay():
    if "student_id" not in session:
        return redirect(url_for("student_login"))

    sid = session["student_id"]
    with get_db_connection() as conn:
        student = conn.execute("SELECT * FROM students WHERE sid=?", (sid,)).fetchone()

    if not student:
        flash("Student not found", "danger")
        return redirect(url_for("student_login"))

    amount = int(student["balance"] * 100)  # Razorpay takes paise

    # Create Razorpay Order
    order = razorpay_client.order.create(dict(
        amount=amount,
        currency="INR",
        payment_capture="1"
    ))

    return render_template("pay.html",
                           student=student,
                           amount=amount,
                           razorpay_key=RAZORPAY_KEY_ID,
                           order=order)

@app.route("/payment/success", methods=["POST"])
def payment_success():
    data = request.form
    # Verify signature
    try:
        razorpay_client.utility.verify_payment_signature(data)
    except razorpay.errors.SignatureVerificationError:
        flash("Payment verification failed ❌", "danger")
        return redirect(url_for("student_dashboard"))

    payment_id = data["razorpay_payment_id"]
    sid = session.get("student_id")
    if sid:
        with get_db_connection() as conn:
            student = conn.execute("SELECT * FROM students WHERE sid=?", (sid,)).fetchone()
            if student:
                conn.execute("UPDATE students SET balance=? WHERE sid=?", (0, sid))
                conn.commit()

    flash(f"Payment Successful ✅ Payment ID: {payment_id}", "success")
    return redirect(url_for("student_dashboard"))

# -------------------- Home --------------------
@app.route("/")
def home():
    return render_template("home.html")

# -------------------- Run App --------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # use Render's port or default 5000
    app.run(host="0.0.0.0", port=port, debug=True)
