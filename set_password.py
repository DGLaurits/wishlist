"""Run once (and again whenever you want a new password): python set_password.py"""
from getpass import getpass
from pathlib import Path
from werkzeug.security import generate_password_hash

pw = getpass("New admin password (min. 10 characters): ")
if len(pw) < 10 or pw != getpass("Repeat: "):
    raise SystemExit("Too short or not matching. Nothing changed.")
f = Path(__file__).resolve().parent / "data" / "password_hash.txt"
f.parent.mkdir(exist_ok=True)
f.write_text(generate_password_hash(pw))
f.chmod(0o600)
print("Saved.")