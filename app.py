"""Family wishlist: a small Flask app with JSON storage (no database)."""
import hmac
import json
import os
import secrets
import threading
import time
from datetime import timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import (Blueprint, Flask, abort, flash, redirect, render_template,
                   request, send_from_directory, session, url_for)
from PIL import Image, ImageOps
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

# ---- Settings (edit here or override with environment variables) -----------
MAX_UPLOAD_MB = 8
# -----------------------------------------------------------------------------

BASE = Path(__file__).resolve().parent
DATA, UPLOADS = BASE / "data", BASE / "uploads"
WISHES_FILE, HASH_FILE, KEY_FILE = DATA / "wishes.json", DATA / "password_hash.txt", DATA / "secret_key"
DATA.mkdir(exist_ok=True)
UPLOADS.mkdir(exist_ok=True)

if not KEY_FILE.exists():
    KEY_FILE.write_text(secrets.token_hex(32))
    KEY_FILE.chmod(0o600)

Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse decompression bombs
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config.update(
    SECRET_KEY=KEY_FILE.read_text().strip(),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("WISHLIST_INSECURE_COOKIES") != "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

LOCK = threading.Lock()  # run gunicorn with ONE worker (see deploy/wishlist.service)
FAILS = {}               # ip -> timestamps of failed logins


# ---- Storage ---------------------------------------------------------------
def load_wishes():
    try:
        return json.loads(WISHES_FILE.read_text("utf-8"))
    except FileNotFoundError:
        return []


def sort_wishes(wishes):
    return sorted(wishes, key=lambda w: (
        w["reserved"], not w.get("store"), w.get("store", "").casefold()))


def save(wishes):
    tmp = WISHES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(wishes, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, WISHES_FILE)  # atomic: never leaves a half-written file


def delete_image(name):
    if name:
        (UPLOADS / Path(name).name).unlink(missing_ok=True)


def save_image(file):
    """Accept only real JPEG/PNG/WebP images; re-encode to a clean WebP."""
    try:
        img = Image.open(file.stream)
        if img.format not in ALLOWED_FORMATS:
            raise ValueError
        img = ImageOps.exif_transpose(img)
        img.load()
    except Exception:
        raise ValueError("That file is not a valid JPG, PNG or WebP image.")
    img.thumbnail((900, 900))
    img = img.convert("RGBA" if "A" in img.mode or "transparency" in img.info else "RGB")
    name = secrets.token_hex(12) + ".webp"  # random name; original name is discarded
    img.save(UPLOADS / name, "WEBP", quality=85)
    return name


def read_form(require_image):
    f = request.form
    title, price, link, note, store = (
        f.get(k, "").strip() for k in ("title", "price", "link", "note", "store"))
    if not title or len(title) > 80:
        return None, "Title is required (max 80 characters)."
    if len(price) > 30:
        return None, "Price is too long (max 30 characters)."
    if len(store) > 80:
        return None, "Store is too long (max 80 characters)."
    u = urlparse(link)
    if u.scheme not in ("http", "https") or not u.netloc or len(link) > 800:
        return None, "Link must be a full address starting with http:// or https://"
    if len(note) > 200:
        return None, "Text is too long (max 200 characters)."
    file = request.files.get("image")
    has_file = bool(file and file.filename)
    if require_image and not has_file:
        return None, "Please choose a cover image."
    image = None
    if has_file:
        try:
            image = save_image(file)
        except ValueError as e:
            return None, str(e)
    return dict(title=title, price=price, link=link, note=note, store=store, image=image), None


# ---- Security helpers --------------------------------------------------------
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@app.before_request
def check_csrf():
    if request.method == "POST":
        expected = session.get("csrf", "")
        sent = request.form.get("csrf", "")
        if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
            abort(400)


@app.after_request
def headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; form-action 'self'; frame-ancestors 'none'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


@app.context_processor
def inject():
    return dict(csrf_token=csrf_token)


@app.errorhandler(413)
def too_big(_):
    return f"Image too large (max {MAX_UPLOAD_MB} MB).", 413


def password_ok(pw):
    try:
        return check_password_hash(HASH_FILE.read_text().strip(), pw)
    except FileNotFoundError:
        return False


def too_many(ip):
    now = time.time()
    FAILS[ip] = [t for t in FAILS.get(ip, []) if now - t < 900]
    return len(FAILS[ip]) >= 5


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("admin.login"))
        return fn(*a, **kw)
    return wrapper


# ---- Public pages --------------------------------------------------------------
@app.route("/")
def index():
    wishes = sort_wishes(load_wishes())
    return render_template("index.html", wishes=wishes)


@app.post("/reserve/<wish_id>")
def reserve(wish_id):
    want = request.form.get("action") == "reserve"
    with LOCK:
        wishes = load_wishes()
        wish = next((w for w in wishes if w["id"] == wish_id), None)
        if not wish:
            abort(404)
        wish["reserved"] = want
        save(wishes)
    return redirect(url_for("index") + f"#w-{wish_id}")


@app.route("/uploads/<path:filename>")
def uploads(filename):  # nginx serves this in production; this is the fallback
    return send_from_directory(UPLOADS, filename)


# ---- Hidden admin area -----------------------------------------------------------
admin = Blueprint("admin", __name__, url_prefix="/" + 'add')


@admin.route("/", methods=["GET", "POST"])
def login():
    if session.get("admin"):
        return redirect(url_for("admin.panel"))
    if request.method == "POST":
        ip = request.remote_addr or "?"
        if too_many(ip):
            flash("Too many attempts. Try again in 15 minutes.")
            return render_template("login.html"), 429
        if password_ok(request.form.get("password", "")):
            FAILS.pop(ip, None)
            session.clear()
            session["admin"] = True
            session.permanent = True
            return redirect(url_for("admin.panel"))
        FAILS.setdefault(ip, []).append(time.time())
        flash("Wrong password.")
    return render_template("login.html")


@admin.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@admin.route("/panel")
@login_required
def panel():
    return render_template("admin.html", wishes=sort_wishes(load_wishes()), wish=None, form={})


@admin.post("/add")
@login_required
def add():
    data, err = read_form(require_image=True)
    if err:
        flash(err)
        return render_template("admin.html", wishes=sort_wishes(load_wishes()), wish=None, form=request.form), 400
    with LOCK:
        wishes = load_wishes()
        wishes.insert(0, dict(id=secrets.token_hex(6), reserved=False, **data))
        save(wishes)
    flash("Wish added.")
    return redirect(url_for("admin.panel"))


@admin.route("/edit/<wish_id>", methods=["GET", "POST"])
@login_required
def edit(wish_id):
    wishes = load_wishes()
    wish = next((w for w in wishes if w["id"] == wish_id), None)
    if not wish:
        abort(404)
    if request.method == "GET":
        return render_template("admin.html", wishes=sort_wishes(wishes), wish=wish, form=wish)
    data, err = read_form(require_image=False)
    if err:
        flash(err)
        return render_template("admin.html", wishes=sort_wishes(wishes), wish=wish, form=request.form), 400
    with LOCK:
        wishes = load_wishes()
        wish = next(w for w in wishes if w["id"] == wish_id)
        new_image = data.pop("image")
        if new_image:
            delete_image(wish["image"])
            wish["image"] = new_image
        wish.update(data)
        save(wishes)
    flash("Wish saved.")
    return redirect(url_for("admin.panel"))


@admin.post("/delete/<wish_id>")
@login_required
def delete(wish_id):
    with LOCK:
        wishes = load_wishes()
        wish = next((w for w in wishes if w["id"] == wish_id), None)
        if wish:
            delete_image(wish["image"])
            save([w for w in wishes if w["id"] != wish_id])
    flash("Wish deleted.")
    return redirect(url_for("admin.panel"))


app.register_blueprint(admin)

if __name__ == "__main__":
    app.run(debug=False, port=8000)
