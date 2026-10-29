
from flask import Flask, render_template, request, redirect, session
import mysql.connector
import os
import uuid
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash


def send_whatsapp_message(message, recipient=None):
    try:
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        whatsapp_from = os.environ.get("TWILIO_WHATSAPP_FROM")
        admin_whatsapp = os.environ.get("ADMIN_WHATSAPP")

        if not all([account_sid, auth_token, whatsapp_from]):
            print("Twilio settings missing in .env")
            return False

        to_number = recipient or admin_whatsapp

        if not to_number:
            print("Recipient number missing.")
            return False

        if not to_number.startswith("whatsapp:"):
            to_number = "whatsapp:" + to_number

        client = Client(account_sid, auth_token)

        client.messages.create(
            body=message,
            from_=whatsapp_from,
            to=to_number
        )

        print("WhatsApp message request sent to:", to_number)
        return True

    except Exception as e:
        print("WhatsApp notification failed:", str(e))
        return False


app = Flask(__name__)
UPLOAD_FOLDER = os.path.join("static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.secret_key = "change-this-to-a-long-random-secret"

from functools import wraps

def user_login_required(route_function):
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect("/user/login")
        return route_function(*args, **kwargs)
    return wrapper


@app.route("/user/register", methods=["GET", "POST"])
def user_register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        if not name or not phone.isdigit() or len(phone) != 10 or len(password) < 8:
            return "Enter a name, valid 10-digit phone number, and password of at least 8 characters.", 400

        db = get_db_connection()
        cursor = db.cursor()

        try:
            cursor.execute(
                "INSERT INTO users (name, phone, password_hash) VALUES (%s, %s, %s)",
                (name, phone, generate_password_hash(password))
            )
            db.commit()
            return redirect("/user/login")

        except mysql.connector.IntegrityError:
            return "This phone number is already registered. Please log in.", 409

        finally:
            cursor.close()
            db.close()

    return render_template("register_user.html")

def get_db_connection():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        database=os.environ.get("DB_NAME", "defaultdb"),
        ssl_disabled=False
    )


@app.route("/")
def home():
    if not session.get("user_id"):
        return redirect("/user/login")

    return render_template(
        "index.html",
        user_name=session.get("user_name")
    )



@app.route("/register", methods=["GET", "POST"])
@user_login_required
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        category = request.form.get("category", "").strip()
        location = request.form.get("location", "").strip()
        complaint = request.form.get("complaint", "").strip()

        if not all([name, phone, category, location, complaint]):
            return "Please fill in all required fields.", 400

        # Optional photo upload
        photo = request.files.get("photo")
        photo_filename = None

        if photo and photo.filename:
            allowed_extensions = {"jpg", "jpeg", "png", "webp"}
            original_name = secure_filename(photo.filename)

            if "." not in original_name:
                return "Invalid photo file.", 400

            extension = original_name.rsplit(".", 1)[1].lower()

            if extension not in allowed_extensions:
                return "Only JPG, JPEG, PNG and WEBP photos are allowed.", 400

            photo_filename = f"{uuid.uuid4().hex}.{extension}"
            photo_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                photo_filename
            )
            photo.save(photo_path)

        db = get_db_connection()
        cursor = db.cursor()

        try:
            sql = """
                INSERT INTO complaints
                (name, phone, category, location, complaint, photo_filename)
                VALUES (%s, %s, %s, %s, %s, %s)
            """

            cursor.execute(sql, (
                name,
                phone,
                category,
                location,
                complaint,
                photo_filename
            ))

        
            

            db.commit()
            complaint_id = cursor.lastrowid

            send_whatsapp_message(
                f"New Complaint Registered!\n"
                f"Complaint ID: {complaint_id}\n"
                f"Name: {name}\n"
                f"Category: {category}\n"
                f"Location: {location}\n"
                f"Complaint: {complaint}"
            )

            return render_template(
                "success.html",
                complaint_id=complaint_id
            )

        finally:
            cursor.close()
            db.close()

    return render_template("register.html")


@app.route("/track", methods=["GET", "POST"])
@user_login_required
def track():
    complaint = None
    
    error = None

    if request.method == "POST":
        complaint_id = request.form.get("complaint_id", "").strip()

        if complaint_id.isdigit():
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)

            try:
                cursor.execute(
                    """
                    SELECT id, name, category, location,
                           complaint, status, created_at
                    FROM complaints
                    WHERE id = %s
                    """,
                    (int(complaint_id),)
                )
                complaint = cursor.fetchone()
            finally:
                cursor.close()
                db.close()

            if complaint is None:
                error = "Complaint ID not found. Please check your ID."
        else:
            error = "Please enter a valid Complaint ID."

    return render_template(
        "track.html",
        complaint=complaint,
        error=error
    )


@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == "admin" and password == "admin123":
            session["admin_logged_in"] = True
            return redirect("/admin/dashboard")

        error = "Invalid username or password."

    return render_template("admin_login.html", error=error)



@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect("/admin")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                id,
                name,
                phone,
                category,
                location,
                complaint,
                photo_filename,
                status
            FROM complaints
            ORDER BY id DESC
        """)
        complaints = cursor.fetchall()
    finally:
        cursor.close()
        db.close()

    return render_template(
        "admin_dashboard.html",
        complaints=complaints
    )



@app.route("/admin/update/<int:complaint_id>", methods=["POST"])
def update_complaint(complaint_id):
    if not session.get("admin_logged_in"):
        return redirect("/admin")

    status = request.form.get("status", "")
    if status not in ["Pending", "In Progress", "Resolved"]:
        return "Invalid complaint status.", 400

   
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT phone, name FROM complaints WHERE id = %s",
            (complaint_id,)
        )
        user = cursor.fetchone()

        cursor.execute(
            "UPDATE complaints SET status = %s WHERE id = %s",
            (status, complaint_id)
        )
        db.commit()

        if user:
            phone = str(user["phone"]).strip()
            if not phone.startswith("+"):
                phone = "+91" + phone

     
        send_whatsapp_message(
            f"Hello {user['name']}, your complaint "
            f"ID {complaint_id} status is now: {status}.",
            recipient=phone
        )



    finally:
        cursor.close()
        db.close()

    return redirect("/admin/dashboard")
    

    

@app.route("/admin/delete/<int:complaint_id>", methods=["POST"])
def delete_complaint(complaint_id):
    if not session.get("admin_logged_in"):
        return redirect("/admin")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT photo_filename FROM complaints WHERE id = %s",
            (complaint_id,)
        )
        complaint = cursor.fetchone()

        if complaint is None:
            return "Complaint not found.", 404

        photo_filename = complaint.get("photo_filename")

        cursor.execute(
            "DELETE FROM complaints WHERE id = %s",
            (complaint_id,)
        )
        db.commit()

        # Delete the associated photo file, if present
        if photo_filename:
            photo_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                os.path.basename(photo_filename)
            )
            if os.path.isfile(photo_path):
                os.remove(photo_path)

    finally:
        cursor.close()
        db.close()

    return redirect("/admin/dashboard")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect("/admin")


@app.route("/user/login", methods=["GET", "POST"])
def user_login():
    error = None

    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        try:
            cursor.execute(
                "SELECT id, name, phone, password_hash FROM users WHERE phone = %s",
                (phone,)
            )
            user = cursor.fetchone()
        finally:
            cursor.close()
            db.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect("/")

        error = "Invalid phone number or password."

    return render_template("user_login.html", error=error)


@app.route("/user/logout")
def user_logout():
    session.pop("user_id", None)
    session.pop("user_name", None)
    return redirect("/user/login")
@app.route("/schemes")
def schemes():
    return render_template("schemes.html")

if __name__ == "__main__":
    app.run(debug=True)
