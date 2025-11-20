import mysql.connector
import os
import json
import io
from datetime import datetime
from functools import wraps
from contextlib import contextmanager
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, session, url_for, jsonify, Response, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# Load environment variables and translations
load_dotenv()

with open(os.path.join(os.path.dirname(__file__), "static/translations.json"), "r", encoding="utf-8") as f:
    TRANSLATIONS = json.load(f)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# Configure session
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=3600  # 1 hour
)

# Google Drive configuration
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

CLIENT_CONFIG = {
    "web": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [
            os.getenv("GOOGLE_OAUTH_REDIRECT", "http://localhost:5000/oauth2callback")
        ],
    }
}

# Database context manager
@contextmanager
def get_db_cursor(dictionary=False):
    """Context manager for database connections and cursors"""
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
        )
        cursor = conn.cursor(dictionary=dictionary)
        yield conn, cursor
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# Helper functions to reduce redundancy
def get_current_user_id():
    """Get current user ID from session"""
    return session.get("user_id")

def get_google_service():
    """Initialize Google Drive service with user credentials"""
    user_id = get_current_user_id()
    if not user_id:
        return None

    creds = load_credentials_for_user(user_id)
    if not creds:
        return None

    return build("drive", "v3", credentials=creds)

def verify_note_ownership(note_id):
    """Verify if the current user owns the note"""
    user_id = get_current_user_id()
    if not user_id:
        return False

    with get_db_cursor(dictionary=True) as (conn, cursor):
        cursor.execute("SELECT id FROM notes WHERE id=%s AND user_id=%s",
                      (note_id, user_id))
        return cursor.fetchone() is not None

def get_user_drive_folder_id():
    """Get or create user's Drive folder ID"""
    user_id = get_current_user_id()
    if not user_id:
        return None

    with get_db_cursor(dictionary=True) as (conn, cursor):
        cursor.execute("SELECT drive_folder_id FROM users WHERE id=%s",
                      (user_id,))
        row = cursor.fetchone()
        folder_id = row["drive_folder_id"] if row and row.get("drive_folder_id") else None

    if not folder_id:
        service = get_google_service()
        if service:
            folder_id = ensure_notepad_folder(service, user_id)

    return folder_id

def get_notes_with_files(completed=False, search_term=None):
    """Get notes with associated files for the current user, optionally filtered by search"""
    user_id = get_current_user_id()
    if not user_id:
        return [], False

    with get_db_cursor(dictionary=True) as (conn, cursor):
        # Check if Google Drive is connected
        cursor.execute("SELECT google_credentials FROM users WHERE id=%s", (user_id,))
        user = cursor.fetchone()
        google_connected = bool(user and user.get("google_credentials"))

        # Build query based on parameters
        if search_term:
            query = """
                SELECT * FROM notes
                WHERE user_id=%s AND (content LIKE %s OR title LIKE %s) AND completed=%s
                ORDER BY created_at DESC
            """
            params = (user_id, f"%{search_term}%", f"%{search_term}%", completed)
        else:
            query = """
                SELECT * FROM notes
                WHERE user_id=%s AND completed=%s
                ORDER BY created_at DESC
            """
            params = (user_id, completed)

        cursor.execute(query, params)
        notes = cursor.fetchall()

        # Get note IDs for batch file query
        note_ids = [note["id"] for note in notes]

        if note_ids:
            # Fetch all files for these notes in a single query
            format_strings = ','.join(['%s'] * len(note_ids))
            cursor.execute(
                f"SELECT id, filename, note_id FROM note_files WHERE note_id IN ({format_strings}) ORDER BY created_at DESC",
                note_ids
            )
            files = cursor.fetchall()

            # Organize files by note_id
            files_by_note = {}
            for file in files:
                note_id = file["note_id"]
                if note_id not in files_by_note:
                    files_by_note[note_id] = []
                files_by_note[note_id].append(file)

            # Attach files to notes
            for note in notes:
                note["files"] = files_by_note.get(note["id"], [])

    return notes, google_connected

# Google Drive helper functions
def credentials_dict_from_object(creds):
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }

def load_credentials_for_user(user_id):
    with get_db_cursor(dictionary=True) as (conn, cursor):
        cursor.execute("SELECT google_credentials FROM users WHERE id=%s", (user_id,))
        row = cursor.fetchone()
        if not row or not row.get("google_credentials"):
            return None
        return Credentials(**json.loads(row["google_credentials"]))

def save_credentials_for_user(user_id, creds):
    data = json.dumps(credentials_dict_from_object(creds))
    with get_db_cursor() as (conn, cursor):
        cursor.execute(
            "UPDATE users SET google_credentials=%s WHERE id=%s",
            (data, user_id)
        )

def ensure_notepad_folder(service, user_id):
    q = (
        "name='Notepad files' and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    res = service.files().list(q=q, spaces='drive', fields="files(id,name)").execute()
    files = res.get("files", [])

    if files:
        folder_id = files[0]["id"]
    else:
        metadata = {
            "name": "Notepad files",
            "mimeType": "application/vnd.google-apps.folder",
        }
        folder = service.files().create(body=metadata, fields="id").execute()
        folder_id = folder["id"]

    with get_db_cursor() as (conn, cursor):
        cursor.execute(
            "UPDATE users SET drive_folder_id=%s WHERE id=%s",
            (folder_id, user_id)
        )

    return folder_id

# Template helpers
def inject_translations():
    lang = session.get("lang", "pt")
    return dict(t=TRANSLATIONS.get(lang, TRANSLATIONS["pt"]), current_lang=lang)

app.context_processor(inject_translations)

# Authentication routes
@app.route("/")
def index():
    if get_current_user_id():
        return redirect(url_for("notes"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        with get_db_cursor(dictionary=True) as (conn, cursor):
            cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
            user = cursor.fetchone()

            if user and check_password_hash(user["password"], password):
                session["user_id"] = user["id"]
                return redirect(url_for("notes"))
            return "incorrect"
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = generate_password_hash(request.form["password"])

        try:
            with get_db_cursor() as (conn, cursor):
                cursor.execute(
                    "INSERT INTO users (username, password) VALUES (%s, %s)",
                    (username, password)
                )
            return redirect(url_for("login"))
        except mysql.connector.IntegrityError:
            return "Username already exists"
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# Google Drive routes
@app.route("/google_connect")
@login_required
def google_connect():
    if "oauth_state" in session:
        session.pop("oauth_state", None)

    flow = Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri=CLIENT_CONFIG["web"]["redirect_uris"][0],
    )

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["oauth_state"] = state
    session.permanent = True

    return redirect(auth_url)

@app.route("/oauth2callback")
@login_required
def oauth2callback():
    if "oauth_state" not in session or request.args.get("state") != session.get("oauth_state"):
        return "Invalid state parameter. Possible CSRF attack.", 400

    try:
        flow = Flow.from_client_config(
            CLIENT_CONFIG,
            scopes=SCOPES,
            redirect_uri=CLIENT_CONFIG["web"]["redirect_uris"][0],
        )

        session.pop("oauth_state", None)
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials

        save_credentials_for_user(get_current_user_id(), creds)
        service = build("drive", "v3", credentials=creds)
        ensure_notepad_folder(service, get_current_user_id())

        return redirect(url_for("notes"))
    except Exception as e:
        return f"Authentication failed: {str(e)}", 500

@app.route("/disconnect_google", methods=["POST"])
@login_required
def disconnect_google():
    with get_db_cursor() as (conn, cursor):
        cursor.execute(
            "UPDATE users SET google_credentials=NULL, drive_folder_id=NULL WHERE id=%s",
            (get_current_user_id(),)
        )
    return redirect(url_for("notes"))

# Notes routes
@app.route("/notes")
@login_required
def notes():
    active_notes, google_connected = get_notes_with_files(completed=False)
    completed_notes, _ = get_notes_with_files(completed=True)
    
    return render_template(
        "notes.html", 
        active_notes=active_notes, 
        completed_notes=completed_notes, 
        google_connected=google_connected
    )

@app.route("/completed_notes")
@login_required
def completed_notes():
    notes, google_connected = get_notes_with_files(completed=True)
    return render_template("completed_notes.html", notes=notes, google_connected=google_connected)

@app.route("/notes", methods=["POST"])
@login_required
def add_note():
    title = request.form.get("title", "Untitled")
    content = request.form["content"]
    reminder_at = request.form.get("reminder_at")

    if reminder_at:
        reminder_at = reminder_at.replace("T", " ")
        if len(reminder_at) == 16:
            reminder_at += ":00"

    with get_db_cursor() as (conn, cursor):
        cursor.execute(
            "INSERT INTO notes (user_id, title, content, completed, reminder_at) "
            "VALUES (%s, %s, %s, FALSE, %s)",
            (get_current_user_id(), title, content, reminder_at),
        )

    return redirect(url_for("notes"))

@app.route("/edit/<int:note_id>", methods=["POST"])
@login_required
def edit_note(note_id):
    if not verify_note_ownership(note_id):
        return "Note not found or access denied", 404

    title = request.form.get("title", "Untitled")
    content = request.form["content"]
    reminder_at = request.form.get("reminder_at")

    if reminder_at:
        reminder_at = reminder_at.replace("T", " ")
        if len(reminder_at) == 16:
            reminder_at += ":00"
    else:
        reminder_at = None

    with get_db_cursor() as (conn, cursor):
        cursor.execute(
            "UPDATE notes SET title=%s, content=%s, reminder_at=%s "
            "WHERE id=%s AND user_id=%s AND completed=FALSE",
            (title, content, reminder_at, note_id, get_current_user_id()),
        )

    return redirect(url_for("notes"))

@app.route("/done/<int:note_id>", methods=["POST"])
@login_required
def mark_done(note_id):
    if not verify_note_ownership(note_id):
        return "Note not found or access denied", 404

    with get_db_cursor() as (conn, cursor):
        cursor.execute(
            "UPDATE notes SET completed=TRUE WHERE id=%s AND user_id=%s",
            (note_id, get_current_user_id())
        )

    return redirect(url_for("notes"))

@app.route("/delete/<int:note_id>", methods=["POST"])
@login_required
def delete_note(note_id):
    if not verify_note_ownership(note_id):
        return "Note not found or access denied", 404
        
    service = get_google_service()
    
    with get_db_cursor(dictionary=True) as (conn, cursor):
        cursor.execute(
            "SELECT id, drive_file_id FROM note_files WHERE note_id=%s",
            (note_id,)
        )
        files = cursor.fetchall()
    
    if service and files:
        for file in files:
            try:
                if file["drive_file_id"]:
                    service.files().delete(fileId=file["drive_file_id"]).execute()
            except Exception as e:
                print(f"Error deleting file from Google Drive: {e}")
    
    with get_db_cursor() as (conn, cursor):
        cursor.execute(
            "DELETE FROM note_files WHERE note_id=%s",
            (note_id,)
        )
        cursor.execute(
            "DELETE FROM notes WHERE id=%s AND user_id=%s AND completed=TRUE",
            (note_id, get_current_user_id()),
        )

    return redirect(url_for("notes"))

# File handling routes
@app.route("/upload_file/<int:note_id>", methods=["POST"])
@login_required
def upload_file(note_id):
    if not verify_note_ownership(note_id):
        return jsonify({"error": "note_not_found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "no_file"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "empty_filename"}), 400

    service = get_google_service()
    if not service:
        return jsonify({"error": "google_not_connected"}), 400

    folder_id = get_user_drive_folder_id()
    if not folder_id:
        return jsonify({"error": "folder_creation_failed"}), 500

    media = MediaIoBaseUpload(file.stream, mimetype=file.mimetype or "application/octet-stream", resumable=False)
    metadata = {"name": file.filename, "parents": [folder_id]}

    try:
        gfile = service.files().create(body=metadata, media_body=media, fields="id, mimeType, name").execute()
    except Exception as e:
        return jsonify({"error": "drive_upload_failed", "detail": str(e)}), 500

    with get_db_cursor() as (conn, cursor):
        cursor.execute(
            "INSERT INTO note_files (note_id, filename, drive_file_id, mime_type) VALUES (%s, %s, %s, %s)",
            (note_id, file.filename, gfile["id"], gfile.get("mimeType"))
        )
        inserted_id = cursor.lastrowid

    return jsonify({
        "ok": True,
        "filename": file.filename,
        "file_id": inserted_id,
        "drive_file_id": gfile["id"]
    })

@app.route("/download_file/<int:file_id>")
@login_required
def download_file(file_id):
    user_id = get_current_user_id()
    if not user_id:
        return "Not authorized", 401

    with get_db_cursor(dictionary=True) as (conn, cursor):
        cursor.execute(
            "SELECT nf.filename, nf.drive_file_id, n.user_id "
            "FROM note_files nf JOIN notes n ON nf.note_id = n.id "
            "WHERE nf.id=%s",
            (file_id,)
        )
        row = cursor.fetchone()

    if not row:
        return "File not found", 404
    if row["user_id"] != user_id:
        return "Not authorized", 403

    service = get_google_service()
    if not service:
        return "Google account not connected", 400

    drive_file_id = row["drive_file_id"]
    fh = io.BytesIO()

    try:
        request_drive = service.files().get_media(fileId=drive_file_id)
        downloader = MediaIoBaseDownload(fh, request_drive)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        fh.seek(0)
        return send_file(
            io.BytesIO(fh.read()),
            download_name=row["filename"],
            as_attachment=True
        )
    except Exception as e:
        return f"Download failed: {e}", 500

# Utility routes
@app.route("/search_notes")
@login_required
def search_notes():
    search = request.args.get("q", "")
    completed = request.args.get("completed", "false").lower() == "true"

    notes, _ = get_notes_with_files(completed=completed, search_term=search)

    template = "partials/notes_completed.html" if completed else "partials/notes_list.html"
    return render_template(template, notes=notes)

@app.route("/reminded/<int:note_id>", methods=["POST"])
@login_required
def mark_reminded(note_id):
    """Called by the client to mark a notification as shown."""
    if not verify_note_ownership(note_id):
        return jsonify({"error": "Note not found or access denied"}), 404

    with get_db_cursor() as (conn, cursor):
        cursor.execute(
            "UPDATE notes SET reminder_sent=TRUE WHERE id=%s AND user_id=%s",
            (note_id, get_current_user_id())
        )
    return jsonify({"status": "success"})


### NEW SIMPLIFIED NOTIFICATION ENDPOINT ###

@app.route("/get_reminders")
@login_required
def get_reminders():
    """Get all due reminders for the current user"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401

    with get_db_cursor(dictionary=True) as (conn, cursor):
        cursor.execute(
            """
            SELECT id, title, content
            FROM notes
            WHERE user_id=%s AND reminder_at <= NOW() AND reminder_sent=FALSE AND completed=FALSE
            ORDER BY reminder_at ASC
            """,
            (user_id,)
        )
        reminders = cursor.fetchall()

    return jsonify(reminders)


### END OF NEW SECTION ###


@app.route("/static/translations.json")
def get_translations():
    return jsonify(TRANSLATIONS)

@app.route("/set_language", methods=["POST"])
def set_language():
    lang = request.json.get("lang") if request.is_json else request.form.get("lang")

    if lang not in TRANSLATIONS:
        return jsonify({"error": "invalid language"}), 400

    session["lang"] = lang
    return jsonify({"ok": True})

@app.route("/credits")
@login_required
def credits():
    return render_template("credits.html")

@app.route('/partials/popup_partial.html')
def popup_partial():
    return render_template('partials/popup_partial.html')

if __name__ == "__main__":
    app.run()
