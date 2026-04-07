from flask import Flask, render_template, request, redirect, session
import sqlite3
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import requests
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
import random

# ================= LOAD ENV =================
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallback_secret")

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_PATH = "photography.db"

# ================= DATABASE =================
def get_db():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            phone TEXT,
            service TEXT,
            event_date TEXT,
            status TEXT DEFAULT 'Pending'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gallery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contact (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            message TEXT
        )
    """)

    # Default admin
    cursor.execute("SELECT * FROM admin WHERE username=?", ("admin",))
    if not cursor.fetchone():
        hashed = generate_password_hash("1234")
        cursor.execute("INSERT INTO admin (username, password) VALUES (?, ?)", ("admin", hashed))

    conn.commit()
    conn.close()

init_db()

# ================= AI CONFIG =================
API_URL = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-2"

HEADERS = {
    "Authorization": f"Bearer {os.getenv('HF_TOKEN')}"
}

def generate_image(prompt):
    try:
        response = requests.post(API_URL, headers=HEADERS, json={"inputs": prompt})
        if response.status_code == 200:
            return response.content
        else:
            print("AI ERROR:", response.text)
            return None
    except Exception as e:
        print("AI EXCEPTION:", e)
        return None

# ================= ROUTES =================

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/services")
def services():
    return render_template("services.html")

# ================= AI GENERATOR =================
@app.route("/ai-generate", methods=["GET", "POST"])
def ai_generate():
    image_url = None

    if request.method == "POST":
        category = request.form["category"]
        mood = request.form["mood"]

        prompt = f"{category} photography pose, {mood}, professional, high quality"

        img_data = generate_image(prompt)

        if img_data:
            filename = f"ai_{category}_{random.randint(1,9999)}.png"
            path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

            with open(path, "wb") as f:
                f.write(img_data)

            image_url = "/" + path

    return render_template("ai.html", image=image_url)

# ================= BOOKING =================
@app.route("/booking", methods=["GET", "POST"])
def booking():
    if request.method == "POST":
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO bookings (name, email, phone, service, event_date)
            VALUES (?, ?, ?, ?, ?)
        """, (
            request.form["name"],
            request.form["email"],
            request.form["phone"],
            request.form["service"],
            request.form["event_date"]
        ))

        conn.commit()
        conn.close()

        return render_template("booking.html", success=True)

    return render_template("booking.html")

# ================= LOGIN =================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM admin WHERE username=?", (request.form["username"],))
        admin = cursor.fetchone()
        conn.close()

        if admin and check_password_hash(admin[2], request.form["password"]):
            session["admin"] = True
            return redirect("/admin")

        return render_template("login.html", error="Invalid Credentials")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect("/login")

# ================= ADMIN =================
@app.route("/admin")
def admin():
    if "admin" not in session:
        return redirect("/login")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bookings")
    bookings = cursor.fetchall()
    conn.close()

    return render_template("admin.html", bookings=bookings)

@app.route("/update-status/<int:id>")
def update_status(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE bookings SET status='Confirmed' WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect("/admin")

@app.route("/delete/<int:id>")
def delete(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bookings WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect("/admin")

# ================= UPLOAD =================
@app.route("/upload", methods=["GET", "POST"])
def upload():
    if "admin" not in session:
        return redirect("/login")

    if request.method == "POST":
        file = request.files.get("image")

        if file and file.filename != "":
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO gallery (image) VALUES (?)", (filename,))
            conn.commit()
            conn.close()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM gallery")
    images = cursor.fetchall()
    conn.close()

    return render_template("upload.html", images=images)

# ================= GALLERY =================
@app.route("/gallery")
def gallery():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM gallery")
    images = cursor.fetchall()
    conn.close()

    return render_template("gallery.html", images=images)

# ================= CONTACT (EMAIL SAFE) =================
@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        message = request.form["message"]

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO contact (name, email, message) VALUES (?, ?, ?)",
                       (name, email, message))
        conn.commit()
        conn.close()

        try:
            msg = MIMEText(f"Name: {name}\nEmail: {email}\n\n{message}")
            msg["Subject"] = "Contact Form"
            msg["From"] = os.getenv("EMAIL_USER")
            msg["To"] = os.getenv("EMAIL_USER")

            server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
            server.login(os.getenv("gaurav202pawar@gmail.com"), os.getenv("tiwltvxcjmdhtpwp"))
            server.send_message(msg)
            server.quit()

            return render_template("contact.html", success="Message sent!")

        except Exception as e:
            print("EMAIL ERROR:", e)
            return render_template("contact.html", success="Saved but email failed")

    return render_template("contact.html")

# ================= AI POSES =================
@app.route("/poses/<category>")
def poses(category):
    keywords = {
        "wedding": ["wedding", "bride", "groom"],
        "birthday": ["birthday", "cake"],
        "cinematic": ["cinematic", "photoshoot"]
    }

    images = []

    if category in keywords:
        for i in range(8):
            keyword = random.choice(keywords[category])
            url = f"https://picsum.photos/seed/{keyword}{random.randint(1,1000)}/600/400"
            images.append(url)

    return render_template("poses.html", images=images, category=category)

# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)
    