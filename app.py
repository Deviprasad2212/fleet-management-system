# app.py - Fleet Management System
import hmac
import logging
import math
import os
import secrets
from contextlib import contextmanager
from datetime import datetime
from functools import wraps

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import (Flask, flash, redirect, render_template, request, session,
                   url_for)
from psycopg2 import errors
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__)

# ── Configuration (all secrets come from the environment / .env) ──────────
_secret = os.getenv("SECRET_KEY")
if not _secret:
    _secret = secrets.token_hex(32)
    logging.warning("SECRET_KEY is not set - sessions will reset on every restart. "
                    "Copy .env.example to .env and set one.")
app.secret_key = _secret
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in ("1", "true", "yes")
DB_CONFIG = dict(
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "5432")),
    dbname=os.getenv("DB_NAME", "fleet_db"),
    user=os.getenv("DB_USER", "postgres"),
    password=os.getenv("DB_PASSWORD", ""),
)
GOODS_TYPES = {"Electronics", "Furniture", "Clothing", "Food & Beverages",
               "Machinery", "Documents", "Other"}


# ── Database helpers ─────────────────────────────────────────────────────
def get_db():
    return psycopg2.connect(**DB_CONFIG)


def query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    """Run one statement on its own connection (always closed, rolled back on error)."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, params)
            result = cur.fetchone() if fetchone else cur.fetchall() if fetchall else None
        if commit:
            conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def transaction():
    """Several statements, one atomic unit of work."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Passwords ────────────────────────────────────────────────────────────
_HASH_PREFIXES = ("pbkdf2:", "scrypt:")


def hash_pw(password):
    # PBKDF2 works on every Python/OpenSSL build (Werkzeug's scrypt default does not).
    return generate_password_hash(password, method="pbkdf2:sha256")


def check_pw(stored, supplied):
    if stored.startswith(_HASH_PREFIXES):
        return check_password_hash(stored, supplied)
    # Legacy plain-text row: compare safely, then upgrade it on successful login.
    return hmac.compare_digest(stored.encode(), supplied.encode())


# ── CSRF ─────────────────────────────────────────────────────────────────
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get("_csrf", "")
        if not token or not hmac.compare_digest(token, request.form.get("csrf_token", "")):
            flash("Your session expired. Please try again.", "error")
            return redirect(url_for("index"))


# ── Template helpers ─────────────────────────────────────────────────────
@app.template_filter("initials")
def f_initials(name):
    parts = (name or "?").split()
    return "".join(p[0] for p in parts[:2]).upper() or "?"


@app.template_filter("hue")
def f_hue(name):
    return sum(ord(c) for c in (name or "")) * 7 % 360


@app.template_filter("status_label")
def f_status_label(s):
    return (s or "").replace("_", " ").capitalize()


@app.template_filter("dmy")
def f_dmy(d):
    return d.strftime("%d %b %Y") if d else "—"


@app.template_filter("dmyt")
def f_dmyt(d):
    return d.strftime("%d %b, %I:%M %p") if d else "—"


@app.template_filter("inr")
def f_inr(value, decimals=2):
    """Format as rupees using Indian digit grouping, e.g. ₹12,34,567.50"""
    if value is None:
        return "—"
    v = float(value)
    neg, v = v < 0, abs(v)
    whole, _, frac = f"{v:.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail, groups = whole[:-3], whole[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return ("-" if neg else "") + "₹" + whole + ("." + frac if decimals else "")


@app.context_processor
def inject_globals():
    now = datetime.now()
    greet = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 17 else "Good evening"
    return {
        "today_date": now.strftime("%A, %d %B %Y"),
        "today_time": now.strftime("%I:%M %p"),
        "greet": greet,
        "demo_mode": DEMO_MODE,
    }


# ── Decorators ───────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to continue.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get("role") != role:
                flash("You don't have access to that page.", "error")
                return redirect(url_for("index"))
            return f(*args, **kwargs)
        return decorated
    return decorator


def home_for(role):
    return url_for(f"{role}_dashboard")


# ── Auth ─────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    if "user_id" in session and session.get("role") in ("admin", "user", "driver"):
        return redirect(home_for(session["role"]))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = query("SELECT id, name, role, password FROM users WHERE LOWER(email)=%s",
                     (email,), fetchone=True)
        if user and check_pw(user["password"], password):
            if not user["password"].startswith(_HASH_PREFIXES):
                query("UPDATE users SET password=%s WHERE id=%s",
                      (hash_pw(password), user["id"]), commit=True)
            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            return redirect(home_for(user["role"]))
        flash("That email and password don't match. Check them and try again.", "error")
    elif "user_id" in session:
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    form = {}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("name", "email", "phone")}
        password = request.form.get("password", "")
        form["email"] = form["email"].lower()
        if not form["name"] or "@" not in form["email"]:
            flash("Enter your name and a valid email address.", "error")
        elif len(password) < 6:
            flash("Choose a password with at least 6 characters.", "error")
        else:
            try:
                query("INSERT INTO users (name, email, password, role, phone) VALUES (%s,%s,%s,'user',%s)",
                      (form["name"], form["email"], hash_pw(password), form["phone"]),
                      commit=True)
                flash("Account created. Sign in to book your first pickup.", "success")
                return redirect(url_for("login"))
            except errors.UniqueViolation:
                flash("That email is already registered. Try signing in instead.", "error")
    return render_template("register.html", form=form)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── Admin dashboard ──────────────────────────────────────────────────────
def _month_back(now, back):
    y, m = now.year, now.month - back
    while m <= 0:
        m += 12
        y -= 1
    return y, m


def build_stats(vehicles, drivers, customers, reqs, trips):
    now = datetime.now()
    priced = [t for t in trips if t["price"] is not None]
    paid = sum(float(t["price"]) for t in priced if t["payment_status"] == "paid")
    unpaid = sum(float(t["price"]) for t in priced if t["payment_status"] != "paid")

    buckets = {}
    for i in range(5, -1, -1):
        y, m = _month_back(now, i)
        buckets[(y, m)] = {"label": datetime(y, m, 1).strftime("%b"), "paid": 0.0, "unpaid": 0.0}
    for t in priced:
        if t["created_at"]:
            b = buckets.get((t["created_at"].year, t["created_at"].month))
            if b:
                b["paid" if t["payment_status"] == "paid" else "unpaid"] += float(t["price"])

    count = lambda rows, key, val: sum(1 for r in rows if r[key] == val)
    vc = {s: count(vehicles, "status", s) for s in ("available", "assigned", "maintenance")}
    rc = {s: count(reqs, "status", s) for s in ("pending", "assigned", "completed")}
    return {
        "n_vehicles": len(vehicles), "n_drivers": len(drivers), "n_customers": len(customers),
        "pending": rc["pending"],
        "active_trips": sum(1 for t in trips if t["status"] != "completed"),
        "completed_trips": count(trips, "status", "completed"),
        "utilization": round(100 * vc["assigned"] / len(vehicles)) if vehicles else 0,
        "revenue_paid": paid, "outstanding": unpaid,
        "vehicle_counts": vc, "request_counts": rc,
        "monthly": list(buckets.values()),
    }


@app.route("/admin")
@login_required
@role_required("admin")
def admin_dashboard():
    vehicles = query("""
        SELECT v.id, v.vehicle_name, v.vehicle_number, v.status, v.created_at,
               (SELECT COUNT(*) FROM trips t WHERE t.vehicle_id=v.id) AS trip_count
        FROM vehicles v ORDER BY v.id""", fetchall=True)
    drivers = query("""
        SELECT d.id, d.name, d.phone, d.license_number, d.created_at, u.email,
               (SELECT COUNT(*) FROM trips t WHERE t.driver_id=d.id) AS total_trips,
               (SELECT COUNT(*) FROM trips t WHERE t.driver_id=d.id AND t.status<>'completed') AS active_trips
        FROM drivers d LEFT JOIN users u ON u.id=d.user_id ORDER BY d.id""", fetchall=True)
    customers = query("""
        SELECT u.id, u.name, u.email, u.phone, u.created_at,
               (SELECT COUNT(*) FROM requests r WHERE r.user_id=u.id) AS request_count
        FROM users u WHERE u.role='user' ORDER BY u.id""", fetchall=True)
    reqs = query("""
        SELECT r.id, u.name AS name, u.phone AS customer_phone, r.from_location, r.to_location,
               r.goods_type, r.status, r.created_at
        FROM requests r JOIN users u ON r.user_id=u.id
        ORDER BY r.id DESC""", fetchall=True)
    trips = query("""
        SELECT t.id, u.name AS name, u.phone AS customer_phone,
               r.from_location, r.to_location,
               d.name AS driver_name, v.vehicle_number,
               t.status, t.price, t.payment_status, t.created_at, t.updated_at
        FROM trips t
        JOIN requests r ON t.request_id=r.id
        JOIN users u ON r.user_id=u.id
        JOIN drivers d ON t.driver_id=d.id
        JOIN vehicles v ON t.vehicle_id=v.id
        ORDER BY t.id DESC""", fetchall=True)
    all_drivers = query("""
        SELECT d.id, d.name, d.phone,
               (SELECT COUNT(*) FROM trips t WHERE t.driver_id=d.id AND t.status<>'completed') AS active_trips
        FROM drivers d ORDER BY d.name""", fetchall=True)
    avail_vehicles = query("SELECT id, vehicle_name, vehicle_number FROM vehicles "
                           "WHERE status='available' ORDER BY vehicle_name", fetchall=True)

    return render_template("admin.html",
        vehicles=vehicles, drivers=drivers, customers=customers, reqs=reqs, trips=trips,
        all_drivers=all_drivers, avail_vehicles=avail_vehicles,
        stats=build_stats(vehicles, drivers, customers, reqs, trips))


# ── Vehicles CRUD ────────────────────────────────────────────────────────
@app.route("/admin/vehicle/add", methods=["POST"])
@login_required
@role_required("admin")
def add_vehicle():
    status = request.form.get("status", "available")
    if status not in ("available", "maintenance"):
        status = "available"
    try:
        query("INSERT INTO vehicles (vehicle_name, vehicle_number, status) VALUES (%s,%s,%s)",
              (request.form["vehicle_name"].strip(), request.form["vehicle_number"].strip().upper(), status),
              commit=True)
        flash("Vehicle added to your fleet.", "success")
    except errors.UniqueViolation:
        flash("A vehicle with that number plate already exists.", "error")
    return redirect(url_for("admin_dashboard") + "#vehicles")


@app.route("/admin/vehicle/edit/<int:vid>", methods=["POST"])
@login_required
@role_required("admin")
def edit_vehicle(vid):
    status = request.form.get("status", "available")
    if status not in ("available", "assigned", "maintenance"):
        flash("Choose a valid vehicle status.", "error")
        return redirect(url_for("admin_dashboard") + "#vehicles")
    try:
        query("UPDATE vehicles SET vehicle_name=%s, vehicle_number=%s, status=%s WHERE id=%s",
              (request.form["vehicle_name"].strip(), request.form["vehicle_number"].strip().upper(), status, vid),
              commit=True)
        flash("Vehicle updated.", "success")
    except errors.UniqueViolation:
        flash("Another vehicle already uses that number plate.", "error")
    return redirect(url_for("admin_dashboard") + "#vehicles")


@app.route("/admin/vehicle/delete/<int:vid>", methods=["POST"])
@login_required
@role_required("admin")
def delete_vehicle(vid):
    row = query("SELECT (SELECT COUNT(*) FROM trips WHERE vehicle_id=%s) AS n FROM vehicles WHERE id=%s",
                (vid, vid), fetchone=True)
    if row and row["n"]:
        flash("This vehicle has trip history, so it can't be deleted. Set it to maintenance instead.", "error")
    else:
        query("DELETE FROM vehicles WHERE id=%s", (vid,), commit=True)
        flash("Vehicle deleted.", "success")
    return redirect(url_for("admin_dashboard") + "#vehicles")


# ── Drivers CRUD ─────────────────────────────────────────────────────────
@app.route("/admin/driver/add", methods=["POST"])
@login_required
@role_required("admin")
def add_driver():
    f = request.form
    if len(f.get("password", "")) < 6:
        flash("Give the driver a password with at least 6 characters.", "error")
        return redirect(url_for("admin_dashboard") + "#drivers")
    try:
        with transaction() as cur:
            cur.execute("INSERT INTO users (name, email, password, role, phone) "
                        "VALUES (%s,%s,%s,'driver',%s) RETURNING id",
                        (f["name"].strip(), f["email"].strip().lower(),
                         hash_pw(f["password"]), f["phone"].strip()))
            uid = cur.fetchone()[0]
            cur.execute("INSERT INTO drivers (name, phone, license_number, user_id) VALUES (%s,%s,%s,%s)",
                        (f["name"].strip(), f["phone"].strip(), f["license_number"].strip(), uid))
        flash("Driver added. They can sign in with the email and password you set.", "success")
    except errors.UniqueViolation:
        flash("That email or licence number is already in use.", "error")
    return redirect(url_for("admin_dashboard") + "#drivers")


@app.route("/admin/driver/edit/<int:did>", methods=["POST"])
@login_required
@role_required("admin")
def edit_driver(did):
    f = request.form
    try:
        with transaction() as cur:
            cur.execute("UPDATE drivers SET name=%s, phone=%s, license_number=%s WHERE id=%s RETURNING user_id",
                        (f["name"].strip(), f["phone"].strip(), f["license_number"].strip(), did))
            row = cur.fetchone()
            if row and row["user_id"]:
                cur.execute("UPDATE users SET name=%s, phone=%s WHERE id=%s",
                            (f["name"].strip(), f["phone"].strip(), row["user_id"]))
        flash("Driver updated.", "success")
    except errors.UniqueViolation:
        flash("Another driver already has that licence number.", "error")
    return redirect(url_for("admin_dashboard") + "#drivers")


@app.route("/admin/driver/delete/<int:did>", methods=["POST"])
@login_required
@role_required("admin")
def delete_driver(did):
    with transaction() as cur:
        cur.execute("SELECT user_id, (SELECT COUNT(*) FROM trips WHERE driver_id=%s) AS n "
                    "FROM drivers WHERE id=%s", (did, did))
        row = cur.fetchone()
        if not row:
            flash("That driver no longer exists.", "error")
        elif row["n"]:
            flash("This driver has trip history, so they can't be deleted.", "error")
        else:
            cur.execute("DELETE FROM drivers WHERE id=%s", (did,))
            if row["user_id"]:
                cur.execute("DELETE FROM users WHERE id=%s", (row["user_id"],))
            flash("Driver deleted.", "success")
    return redirect(url_for("admin_dashboard") + "#drivers")


# ── Assign trip ──────────────────────────────────────────────────────────
@app.route("/admin/assign/<int:req_id>", methods=["POST"])
@login_required
@role_required("admin")
def assign_trip(req_id):
    try:
        driver_id = int(request.form["driver_id"])
        vehicle_id = int(request.form["vehicle_id"])
    except (KeyError, ValueError):
        flash("Choose both a driver and a vehicle.", "error")
        return redirect(url_for("admin_dashboard") + "#requests")

    with transaction() as cur:
        # Lock the rows so two admins can't assign the same request or vehicle at once.
        cur.execute("SELECT status FROM requests WHERE id=%s FOR UPDATE", (req_id,))
        req = cur.fetchone()
        cur.execute("SELECT status FROM vehicles WHERE id=%s FOR UPDATE", (vehicle_id,))
        veh = cur.fetchone()
        cur.execute("SELECT 1 FROM drivers WHERE id=%s", (driver_id,))
        drv = cur.fetchone()
        if not req or req["status"] != "pending":
            flash("That request has already been assigned.", "error")
        elif not veh or veh["status"] != "available":
            flash("That vehicle is no longer available. Pick another one.", "error")
        elif not drv:
            flash("That driver no longer exists.", "error")
        else:
            cur.execute("INSERT INTO trips (request_id, driver_id, vehicle_id, status) VALUES (%s,%s,%s,'assigned')",
                        (req_id, driver_id, vehicle_id))
            cur.execute("UPDATE requests SET status='assigned' WHERE id=%s", (req_id,))
            cur.execute("UPDATE vehicles SET status='assigned' WHERE id=%s", (vehicle_id,))
            flash("Trip assigned. The driver can see it in their portal now.", "success")
    return redirect(url_for("admin_dashboard") + "#requests")


# ── Trip price & payment ─────────────────────────────────────────────────
@app.route("/admin/trip/price/<int:trip_id>", methods=["POST"])
@login_required
@role_required("admin")
def update_trip_price(trip_id):
    raw = request.form.get("price", "").strip()
    try:
        price = float(raw) if raw else None
        if price is not None and (not math.isfinite(price) or price < 0 or price > 99999999.99):
            raise ValueError
        query("UPDATE trips SET price=%s WHERE id=%s", (price, trip_id), commit=True)
        flash("Price saved." if price is not None else "Price cleared.", "success")
    except ValueError:
        flash("Enter a price of zero or more.", "error")
    return redirect(url_for("admin_dashboard") + "#reports")


@app.route("/admin/trip/payment/<int:trip_id>", methods=["POST"])
@login_required
@role_required("admin")
def update_payment_status(trip_id):
    status = request.form.get("payment_status", "unpaid")
    if status not in ("paid", "unpaid"):
        status = "unpaid"
    query("UPDATE trips SET payment_status=%s WHERE id=%s", (status, trip_id), commit=True)
    flash("Marked as paid." if status == "paid" else "Marked as unpaid.", "success")
    return redirect(url_for("admin_dashboard") + "#reports")


# ── Client dashboard ─────────────────────────────────────────────────────
@app.route("/user")
@login_required
@role_required("user")
def user_dashboard():
    my_requests = query("""
        SELECT r.id, r.from_location, r.to_location, r.goods_type,
               r.status, r.created_at,
               t.status AS trip_status, d.name AS driver_name,
               v.vehicle_number, t.price, t.payment_status
        FROM requests r
        LEFT JOIN trips t ON t.request_id=r.id
        LEFT JOIN drivers d ON t.driver_id=d.id
        LEFT JOIN vehicles v ON t.vehicle_id=v.id
        WHERE r.user_id=%s ORDER BY r.id DESC""", (session["user_id"],), fetchall=True)
    return render_template("user.html", my_requests=my_requests)


@app.route("/user/request", methods=["POST"])
@login_required
@role_required("user")
def submit_request():
    origin = request.form.get("from_location", "").strip()
    dest = request.form.get("to_location", "").strip()
    goods = request.form.get("goods_type", "")
    if not origin or not dest or goods not in GOODS_TYPES:
        flash("Fill in the pickup, delivery and goods type to send a request.", "error")
        return redirect(url_for("user_dashboard") + "#new")
    query("INSERT INTO requests (user_id, from_location, to_location, goods_type) VALUES (%s,%s,%s,%s)",
          (session["user_id"], origin[:200], dest[:200], goods), commit=True)
    flash("Request sent. We'll assign a driver shortly.", "success")
    return redirect(url_for("user_dashboard") + "#shipments")


# ── Driver dashboard ─────────────────────────────────────────────────────
@app.route("/driver")
@login_required
@role_required("driver")
def driver_dashboard():
    row = query("SELECT id FROM drivers WHERE user_id=%s", (session["user_id"],), fetchone=True)
    trips = []
    if row:
        trips = query("""
            SELECT t.id, r.from_location, r.to_location, r.goods_type,
                   v.vehicle_name, v.vehicle_number, t.status,
                   u.name AS client_name, u.phone AS client_phone,
                   t.created_at, t.updated_at
            FROM trips t
            JOIN requests r ON t.request_id=r.id
            JOIN vehicles v ON t.vehicle_id=v.id
            JOIN users u ON r.user_id=u.id
            WHERE t.driver_id=%s ORDER BY t.id DESC""", (row["id"],), fetchall=True)
    return render_template("driver.html", trips=trips)


# A trip can only move forward: assigned -> in_progress -> completed.
_NEXT = {"assigned": {"in_progress", "completed"}, "in_progress": {"completed"}}


@app.route("/driver/update/<int:trip_id>", methods=["POST"])
@login_required
@role_required("driver")
def update_trip(trip_id):
    new_status = request.form.get("status", "")
    with transaction() as cur:
        # Only the driver this trip belongs to may change it.
        cur.execute("""SELECT t.status, t.request_id, t.vehicle_id
                       FROM trips t JOIN drivers d ON d.id=t.driver_id
                       WHERE t.id=%s AND d.user_id=%s FOR UPDATE OF t""",
                    (trip_id, session["user_id"]))
        trip = cur.fetchone()
        if not trip:
            flash("That trip isn't assigned to you.", "error")
        elif new_status not in _NEXT.get(trip["status"], set()):
            flash("That trip can't be moved to that status.", "error")
        else:
            cur.execute("UPDATE trips SET status=%s, updated_at=%s WHERE id=%s",
                        (new_status, datetime.now(), trip_id))
            if new_status == "completed":
                cur.execute("UPDATE requests SET status='completed' WHERE id=%s", (trip["request_id"],))
                cur.execute("UPDATE vehicles SET status='available' WHERE id=%s", (trip["vehicle_id"],))
            flash("Trip started. Drive safe." if new_status == "in_progress" else "Trip marked as delivered.",
                  "success")
    return redirect(url_for("driver_dashboard") + "#trips")


# ── Error pages ──────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, title="Page not found",
                           text="The page you're looking for doesn't exist or has moved."), 404


@app.errorhandler(psycopg2.OperationalError)
def db_down(_e):
    app.logger.exception("Database connection failed")
    return render_template("error.html", code=503, title="Can't reach the database",
                           text="Check that PostgreSQL is running and that the DB_* values in your .env file are correct."), 503


@app.errorhandler(500)
def server_error(_e):
    return render_template("error.html", code=500, title="Something went wrong",
                           text="The error has been logged. Please try again in a moment."), 500


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes"),
            port=int(os.getenv("FLASK_PORT", "5000")))
