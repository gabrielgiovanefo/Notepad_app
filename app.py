import mariadb
import os
import json
import pytz
import time
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, session, url_for, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

#load translations.jason
with open(os.path.join(os.path.dirname(__file__), "static/translations.json"), "r", encoding="utf-8") as f:
    TRANSLATIONS = json.load(f)

def convert_to_utc(datetime_str):
    if not datetime_str:
        return None
    dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def get_db():
    return mariadb.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("notes"))
    return redirect(url_for("login"))

#----------------
# login/register
#----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()
        db.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            return redirect(url_for("notes"))
        return "incorect"
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = generate_password_hash(request.form["password"])

        db = get_db()
        cursor = db.cursor()
        try:
            cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, password))
            db.commit()
        except:
            return "Username already exists"
        db.close()
        return redirect(url_for("login"))
    return render_template("register.html")

#-------
# pages
#-------

@app.route("/notes")
def notes():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM notes WHERE user_id=%s AND completed=FALSE", (session["user_id"],))
    notes = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("notes.html", notes=notes)

@app.route("/completed_notes")
def completed_notes():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM notes WHERE user_id=%s AND completed=TRUE", (session["user_id"],))
    notes = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("completed_notes.html", notes=notes)

@app.route("/credits")
def credits():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("credits.html")

#----------
# funcions
#----------

#add note
@app.route("/notes", methods=["POST"])
def add_note():
    if "user_id" not in session:
        return redirect(url_for("login"))

    title = request.form.get("title", "Untitled")
    content = request.form["content"]
    reminder_at = request.form.get("reminder_at")
    if reminder_at:
        reminder_at = reminder_at.replace("T", " ")
        if len(reminder_at) == 16:
            reminder_at = reminder_at + ":00"

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO notes (user_id, title, content, completed, reminder_at) VALUES (%s, %s, %s, FALSE, %s)",
        (session["user_id"], title, content, reminder_at)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("notes"))

#delete note
@app.route("/delete/<int:note_id>", methods=["POST"])
def delete_note(note_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM notes WHERE id=%s AND user_id=%s AND completed=TRUE", (note_id, session["user_id"]))
    conn.commit()
    cursor.close()
    return redirect(url_for("completed_notes"))

#edit note
@app.route("/edit/<int:note_id>", methods=["POST"])
def edit_note(note_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    title = request.form.get("title", "Untitled")
    content = request.form["content"]
    reminder_at = request.form.get("reminder_at")
    if reminder_at:
        reminder_at = reminder_at.replace("T", " ")
        if len(reminder_at) == 16:
            reminder_at = reminder_at + ":00"
    else:
        reminder_at = None

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE notes SET title=%s, content=%s, reminder_at=%s WHERE id=%s AND user_id=%s AND completed=FALSE",
        (title, content, reminder_at, note_id, session["user_id"])
    )
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("notes"))

#complete note
@app.route("/done/<int:note_id>", methods=["POST"])
def mark_done(note_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE notes SET completed=TRUE WHERE id=%s AND user_id=%s", (note_id, session["user_id"]))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("notes"))

#search note
@app.route("/search_notes")
def search_notes():
    if "user_id" not in session:
        return "Unauthorized", 401

    db = get_db()
    cursor = db.cursor(dictionary=True)

    search = request.args.get("q", "")
    completed = request.args.get("completed", "false").lower() == "true"

    if search:
        cursor.execute(
            """
            SELECT * FROM notes
            WHERE user_id=%s AND (content LIKE %s OR title LIKE %s) AND completed=%s
            ORDER BY created_at DESC
            """,
            (session["user_id"], f"%{search}%", f"%{search}%", completed)
        )
    else:
        cursor.execute(
            """
            SELECT * FROM notes
            WHERE user_id=%s AND completed=%s
            ORDER BY created_at DESC
            """,
            (session["user_id"], completed)
        )

    notes_list = cursor.fetchall()
    db.close()

    template = "partials/notes_completed.html" if completed else "partials/notes_list.html"
    return render_template(template, notes=notes_list)

#remided note
@app.route("/reminded/<int:note_id>", methods=["POST"])
def mark_reminded(note_id):
    if "user_id" not in session:
        return "Unauthorized", 401

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE notes SET reminder_sent=TRUE WHERE id=%s AND user_id=%s",
        (note_id, session["user_id"])
    )
    conn.commit()
    cursor.close()
    conn.close()
    return "", 204

#------
# misc
#------

#notifications
@app.route('/notifications')
def notifications():
    user_id = session.get("user_id")
    
    if not user_id:
        return "Unauthorized", 401

    # Capture timezone offset from session while still in request context
    timezone_offset = session.get('timezone_offset')

    def generate():
        # Send initial connection message
        yield f"data: {json.dumps({'type': 'connected', 'message': 'Connection established'})}\n\n"
        
        while True:
            try:
                # Use the captured timezone_offset instead of accessing session
                if timezone_offset is None:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                    time.sleep(30)
                    continue

                # Calculate current time in user's timezone
                now_utc = datetime.now(pytz.UTC)
                user_tz = pytz.FixedOffset(timezone_offset * -1)
                now_user_local = now_utc.astimezone(user_tz)
                now_user_local_str = now_user_local.strftime("%Y-%m-%d %H:%M:%S")
                
                # Get reminders from database
                conn = None
                try:
                    conn = get_db()
                    cursor = conn.cursor(dictionary=True)
                    cursor.execute(
                        """
                        SELECT id, title, content 
                        FROM notes 
                        WHERE user_id=%s AND reminder_at <= %s AND reminder_sent=FALSE AND completed=FALSE
                        """,
                        (user_id, now_user_local_str)
                    )
                    due_reminders = cursor.fetchall()
                    cursor.close()
                except Exception as e:
                    print(f"Database error in notifications: {e}")
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Database error'})}\n\n"
                    time.sleep(30)
                    continue
                finally:
                    if conn:
                        conn.close()
                
                # Send reminders if any
                if due_reminders:
                    try:
                        yield f"data: {json.dumps({'type': 'reminders', 'data': due_reminders})}\n\n"
                    except (OSError, BrokenPipeError, ConnectionResetError):
                        return
                
                # Send heartbeat even if no reminders
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                time.sleep(30)
                
            except Exception as e:
                print(f"Error in notification stream: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                time.sleep(30)

    return Response(generate(), mimetype="text/event-stream")

#load translations
@app.route("/static/translations.json")
def get_translations():
    return jsonify(TRANSLATIONS)

def inject_translations():
    lang = session.get("lang", "pt")
    return dict(t=TRANSLATIONS.get(lang, TRANSLATIONS["pt"]), current_lang=lang)
app.context_processor(inject_translations)

#set language
@app.route("/set_language", methods=["POST"])
def set_language():
    # Accept JSON or form value 'lang'
    lang = None
    if request.is_json:
        lang = request.json.get("lang")
    else:
        lang = request.form.get("lang")
    if lang not in TRANSLATIONS:
        return jsonify({"error": "invalid language"}), 400
    session["lang"] = lang
    return jsonify({"ok": True})

#logout
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

#set timezone
@app.route('/set_timezone', methods=['POST'])
def set_timezone():
    if "user_id" not in session:
        return jsonify({"error": "unauthorized"}), 401
    
    data = request.get_json()
    if data and 'offset' in data:
        session['timezone_offset'] = data['offset']
        return jsonify({"status": "success"})
    
    return jsonify({"error": "invalid data"}), 400

@app.route('/partials/popup_partial.html')
def popup_partial():
    return render_template('partials/popup_partial.html')

if __name__ == "__main__":
    app.run()