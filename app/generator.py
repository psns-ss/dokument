# app/generator.py
# ----------------
# Flask app: HTTP routing and coordination.
from __future__ import annotations

import os
import secrets

from routes.debug import debug_bp
from routes.generate import generate_bp
from routes.init import init_bp
from routes.inflection import inflection_bp
from routes.select import select_bp

from flask import Flask
from flask_session import Session
from cachelib import FileSystemCache

app = Flask(__name__)
# Flask safety net, NOT a session key: flask-session's backends do not sign the
# session cookie (SESSION_USE_SIGNER defaults to False — the sid is an unsigned
# 256-bit random token), so this key does not protect sessions in this app. It's
# set for any future client-side need (CSRF, flask-login, a signed cookie) and is
# shared across gunicorn workers via the Dockerfile's per-boot SECRET_KEY.
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

# Server-side sessions (cachelib filesystem) — avoids 4 KB cookie limit.
# /tmp survives for the container lifetime, which covers the single-session workflow.
# SESSION_TYPE='cachelib' + an explicit FileSystemCache replaces the deprecated
# SESSION_FILE_DIR / FileSystemSessionInterface (deprecated in flask-session 0.7; removal
# planned for 1.0, which does not exist yet — latest is 0.8).
app.config['SESSION_TYPE'] = 'cachelib'
app.config['SESSION_CACHELIB'] = FileSystemCache(
    cache_dir='/tmp/flask_sessions', threshold=500, mode=384
)
Session(app)

# Flask 3.1 / Werkzeug 3.1 cap each non-file form field at 500 kB by default (was
# unlimited on Werkzeug 2.2). File uploads are unaffected — they stream to disk and are
# capped by nginx's client_max_body_size. No field in this app approaches 500 kB (the
# largest is the matching-flow ui_hash, a short hash), so 1 MB gives generous, defensive
# headroom while keeping a hostile oversized text field well under nginx's 100M.
app.config['MAX_FORM_MEMORY_SIZE'] = 1024 * 1024

# Register route blueprints
app.register_blueprint(select_bp)
app.register_blueprint(debug_bp)
app.register_blueprint(generate_bp)
app.register_blueprint(init_bp)
app.register_blueprint(inflection_bp)


# ------------------------------------------------------------------
# Start the server
# ------------------------------------------------------------------
if __name__ == '__main__':
    # Host dev only — the container runs gunicorn (see Dockerfile CMD).
    # debug=True enables the Werkzeug interactive debugger + auto-reloader. Off by
    # default (security on 0.0.0.0); opt in per-host with APP_DEBUG=1.
    debug = os.environ.get('APP_DEBUG', '').lower() in ('1', 'true', 'yes', 'on')
    app.run(debug=debug, host='0.0.0.0')
