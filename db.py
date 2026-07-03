"""
db.py — Koneksi PostgreSQL + Migrasi Tabel
Reliability Performance & Risk Agent
"""

import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_conn():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode="require")


@contextmanager
def db_cursor():
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# MIGRATIONS
# ─────────────────────────────────────────────────────────────────────────────

def run_migrations():
    migrations = [
        # Tabel untuk menyimpan laporan bulanan yang diupload
        """
        CREATE TABLE IF NOT EXISTS reports (
            id         SERIAL PRIMARY KEY,
            type       VARCHAR(50)  NOT NULL,
            title      VARCHAR(255),
            content    TEXT         NOT NULL,
            created_at TIMESTAMP    DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_reports_type ON reports(type);",

        # Tabel untuk menyimpan output hasil agent
        """
        CREATE TABLE IF NOT EXISTS reliability_outputs (
            id          SERIAL PRIMARY KEY,
            output_type VARCHAR(50)  NOT NULL,
            title       VARCHAR(255),
            content     TEXT         NOT NULL,
            batch_ref   VARCHAR(50),
            created_at  TIMESTAMP    DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_rel_outputs_type ON reliability_outputs(output_type);",
        "CREATE INDEX IF NOT EXISTS idx_rel_outputs_created ON reliability_outputs(created_at DESC);",
    ]

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for sql in migrations:
                cur.execute(sql)
        conn.commit()
        print("[DB] ✅ Migrasi selesai.")
    except Exception as e:
        conn.rollback()
        print(f"[DB] ❌ Migrasi gagal: {e}")
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# REPORTS — Laporan bulanan
# ─────────────────────────────────────────────────────────────────────────────

def save_report(report_type: str, title: str, content: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO reports (type, title, content) VALUES (%s, %s, %s) RETURNING id",
            (report_type, title, content)
        )
        return cur.fetchone()["id"]


def fetch_reports(report_type: str = None, limit: int = 20):
    with db_cursor() as cur:
        if report_type:
            cur.execute(
                """SELECT id, type, title,
                          LEFT(content, 200) AS preview, created_at
                   FROM reports
                   WHERE type = %s
                   ORDER BY created_at DESC LIMIT %s""",
                (report_type, limit)
            )
        else:
            cur.execute(
                """SELECT id, type, title,
                          LEFT(content, 200) AS preview, created_at
                   FROM reports
                   ORDER BY created_at DESC LIMIT %s""",
                (limit,)
            )
        return cur.fetchall()


def fetch_report_detail(report_id: int):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM reports WHERE id = %s", (report_id,))
        return cur.fetchone()


# ─────────────────────────────────────────────────────────────────────────────
# RELIABILITY OUTPUTS — Hasil agent
# ─────────────────────────────────────────────────────────────────────────────

def save_reliability_output(output_type: str, title: str,
                             content: str, batch_ref: str = "",
                             dashboard_html: str = "") -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO reliability_outputs
               (output_type, title, content, batch_ref, dashboard_html)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (output_type, title, content, batch_ref, dashboard_html or None)
        )
        return cur.fetchone()["id"]


def fetch_reliability_outputs(output_type: str = None, limit: int = 20):
    with db_cursor() as cur:
        if output_type:
            cur.execute(
                """SELECT id, output_type, title,
                          LEFT(content, 200) AS preview, created_at
                   FROM reliability_outputs
                   WHERE output_type = %s
                   ORDER BY created_at DESC LIMIT %s""",
                (output_type, limit)
            )
        else:
            cur.execute(
                """SELECT id, output_type, title,
                          LEFT(content, 200) AS preview, created_at
                   FROM reliability_outputs
                   ORDER BY created_at DESC LIMIT %s""",
                (limit,)
            )
        return cur.fetchall()


def fetch_reliability_output_detail(output_id: int):
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM reliability_outputs WHERE id = %s", (output_id,)
        )
        return cur.fetchone()
