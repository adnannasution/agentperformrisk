"""
app.py — Main Flask Application
Reliability Performance & Risk Agent
"""

import os
from flask import Flask, jsonify
from dotenv import load_dotenv
from db import run_migrations

load_dotenv()

app = Flask(__name__, static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", "reliability-agent-secret")

# ── Register Blueprints ───────────────────────────────────────────────────────
from reliability_routes import reliability_bp
app.register_blueprint(reliability_bp)

# ── Health Check ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    from flask import redirect
    return redirect("/reliability")

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "reliability-agent"})

# ── Run Migrations on Startup ─────────────────────────────────────────────────
with app.app_context():
    try:
        run_migrations()
    except Exception as e:
        print(f"[App] Migration warning: {e}")

# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
