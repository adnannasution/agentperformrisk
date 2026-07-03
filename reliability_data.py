"""
reliability_data.py — Data Aggregator untuk Reliability Performance & Risk Agent
Mengambil dan merangkum data dari semua tabel relevan di database.
"""

import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "")


# ─── koneksi (tidak duplikasi dari db.py agar tidak circular import) ─────────
def _get_conn():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode="require")


@contextmanager
def _cursor():
    conn = _get_conn()
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
# SCHEMA MIGRATION (dipanggil sekali saat startup)
# ─────────────────────────────────────────────────────────────────────────────

def ensure_reliability_schema():
    """
    Pastikan kolom & tipe yang dibutuhkan sudah ada.
    Aman dijalankan berulang (idempotent).
    """
    stmts = [
        # Perlebar kolom type agar muat 'monthly_reliability'
        "ALTER TABLE reports ALTER COLUMN type TYPE VARCHAR(50);",
        # Tambah kolom title jika belum ada
        "ALTER TABLE reports ADD COLUMN IF NOT EXISTS title VARCHAR(255);",
    ]
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            for sql in stmts:
                try:
                    cur.execute(sql)
                except Exception:
                    pass  # kolom sudah ada, lanjut
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def get_reliability_data() -> dict:
    """Agregasi semua data reliability dari database → 1 dict untuk agent."""
    return {
        "paf":                _get_paf(),
        "issue_paf":          _get_issue_paf(),
        "bad_actor":          _get_bad_actor(),
        "icu":                _get_icu(),
        "boc_mtbf":           _get_boc(),
        "rcps":               _get_rcps(),
        "rcps_rekomendasi":   _get_rcps_rekomendasi(),
        "irkap_summary":      _get_irkap_summary(),
        "critical_equipment": _get_critical_equipment(),
        "inspection_overdue": _get_inspection_overdue(),
        "sap":                _get_sap_data(),
        "laporan_bulanan":    _get_laporan_bulanan(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. PAF — Plant Availability Factor
# ─────────────────────────────────────────────────────────────────────────────

def _get_paf() -> dict:
    with _cursor() as cur:
        # Data terkini per RU
        cur.execute("""
            SELECT ru, type, target_realisasi, value, target,
                   plan_unplan, month_update
            FROM paf
            WHERE code_current = 1
            ORDER BY ru, type
        """)
        current = cur.fetchall()

        # Trend realisasi per RU (max 6 bulan terakhir)
        cur.execute("""
            SELECT ru, month_update,
                   ROUND(COALESCE(AVG(value), 0)::numeric, 2) AS avg_value
            FROM paf
            WHERE target_realisasi = 'Realisasi'
            GROUP BY ru, month_update
            ORDER BY month_update DESC
            LIMIT 36
        """)
        trend = cur.fetchall()

        return {
            "current": [dict(r) for r in current],
            "trend":   [dict(r) for r in trend],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 2. ISSUE PAF — Penyebab kehilangan availability
# ─────────────────────────────────────────────────────────────────────────────

def _get_issue_paf() -> list:
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, type, date, issue, month_update
            FROM issue_paf
            WHERE code_current = 1
            ORDER BY ru, date DESC
        """)
        return [dict(r) for r in cur.fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# 3. BAD ACTOR
# ─────────────────────────────────────────────────────────────────────────────

def _get_bad_actor() -> dict:
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, tag_number, status, problem,
                   action_plan, category_action_plan,
                   progress, target_date, periode
            FROM bad_actor_monitoring
            ORDER BY ru, periode DESC NULLS LAST
        """)
        all_actors = cur.fetchall()

        cur.execute("""
            SELECT ru,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status ILIKE '%open%'
                              OR status ILIKE '%progress%'
                              OR status ILIKE '%inprogress%' THEN 1 ELSE 0 END) AS open_count,
                   SUM(CASE WHEN status ILIKE '%close%'
                              OR status ILIKE '%done%'
                              OR status ILIKE '%selesai%' THEN 1 ELSE 0 END) AS closed_count
            FROM bad_actor_monitoring
            GROUP BY ru ORDER BY ru
        """)
        summary = cur.fetchall()

        return {
            "list":    [dict(r) for r in all_actors],
            "summary": [dict(r) for r in summary],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 4. ICU — Integrity Concern Unit (leading indicator utama)
# ─────────────────────────────────────────────────────────────────────────────

def _get_icu() -> dict:
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, tag_no, icu_status, issue,
                   mitigation, mitigasi_category,
                   permanent_solution, progress,
                   target_closed, report_date
            FROM icu_monitoring
            WHERE icu_status NOT ILIKE '%close%'
            ORDER BY ru, report_date DESC NULLS LAST
        """)
        open_icu = cur.fetchall()

        cur.execute("""
            SELECT ru,
                   COUNT(*) AS total,
                   SUM(CASE WHEN icu_status NOT ILIKE '%close%'
                             THEN 1 ELSE 0 END) AS open_count,
                   SUM(CASE WHEN icu_status ILIKE '%close%'
                             THEN 1 ELSE 0 END) AS closed_count
            FROM icu_monitoring
            GROUP BY ru ORDER BY open_count DESC
        """)
        summary = cur.fetchall()

        return {
            "open_list": [dict(r) for r in open_icu],
            "summary":   [dict(r) for r in summary],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 5. BOC — MTBF & MTTR
# ─────────────────────────────────────────────────────────────────────────────

def _get_boc() -> dict:
    with _cursor() as cur:
        # Equipment MTBF terendah (paling sering failure)
        cur.execute("""
            SELECT ru, equipment, grup_equipment,
                   status, frequency, running_hours,
                   mttr, mtbf, hasil
            FROM boc
            WHERE mtbf IS NOT NULL AND mtbf > 0
            ORDER BY mtbf ASC
            LIMIT 20
        """)
        low_mtbf = cur.fetchall()

        # Ringkasan per RU
        cur.execute("""
            SELECT ru,
                   COUNT(*) AS total_equipment,
                   ROUND(COALESCE(AVG(mtbf), 0)::numeric, 2) AS avg_mtbf,
                   ROUND(COALESCE(AVG(mttr), 0)::numeric, 2) AS avg_mttr,
                   COALESCE(SUM(frequency), 0) AS total_failures
            FROM boc
            WHERE mtbf IS NOT NULL
            GROUP BY ru
            ORDER BY avg_mtbf ASC
        """)
        summary = cur.fetchall()

        return {
            "low_mtbf_equipment": [dict(r) for r in low_mtbf],
            "summary_by_ru":      [dict(r) for r in summary],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 6. RCPS
# ─────────────────────────────────────────────────────────────────────────────

def _get_rcps() -> list:
    with _cursor() as cur:
        cur.execute("""
            SELECT kilang, rcps_no, judul_rcps, disiplin,
                   criticallity, traffic, sum_of_progress, date
            FROM rcps
            ORDER BY kilang,
                     CASE traffic
                       WHEN 'Red'    THEN 1
                       WHEN 'Yellow' THEN 2
                       WHEN 'Green'  THEN 3
                       ELSE 4 END,
                     date DESC
        """)
        return [dict(r) for r in cur.fetchall()]


def _get_rcps_rekomendasi() -> dict:
    with _cursor() as cur:
        # Rekomendasi belum selesai (non-green atau null)
        cur.execute("""
            SELECT kilang, rcps_no, judul_rcps,
                   rekomendasi, traffic, pic,
                   target, recommendation_category, remark
            FROM rcps_rekomendasi
            WHERE traffic NOT ILIKE '%green%'
               OR traffic IS NULL
            ORDER BY kilang,
                     CASE traffic
                       WHEN 'Red'    THEN 1
                       WHEN 'Yellow' THEN 2
                       ELSE 3 END,
                     target ASC NULLS LAST
        """)
        open_rekom = cur.fetchall()

        # Ringkasan traffic per kilang
        cur.execute("""
            SELECT kilang,
                   COALESCE(traffic, 'Tidak Ada') AS traffic,
                   COUNT(*) AS total
            FROM rcps_rekomendasi
            GROUP BY kilang, traffic
            ORDER BY kilang, total DESC
        """)
        traffic_summary = cur.fetchall()

        return {
            "open_recommendations": [dict(r) for r in open_rekom],
            "traffic_summary":      [dict(r) for r in traffic_summary],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 7. IRKAP — Program vs Aktual (PM compliance)
# ─────────────────────────────────────────────────────────────────────────────

def _get_irkap_summary() -> dict:
    with _cursor() as cur:
        # Status prognosa per RU dari irkap_program
        cur.execute("""
            SELECT refinery_unit,
                   COUNT(*) AS total_program,
                   SUM(CASE WHEN status_prognosa ILIKE '%on track%'
                              OR status_prognosa ILIKE '%ontrack%'
                             THEN 1 ELSE 0 END) AS on_track,
                   SUM(CASE WHEN status_prognosa ILIKE '%delay%'
                             THEN 1 ELSE 0 END) AS delay,
                   SUM(CASE WHEN status_prognosa ILIKE '%carry%'
                             THEN 1 ELSE 0 END) AS carry_over,
                   SUM(CASE WHEN top_risk IS NOT NULL
                             AND top_risk != ''
                             THEN 1 ELSE 0 END) AS has_top_risk
            FROM irkap_program
            GROUP BY refinery_unit
            ORDER BY refinery_unit
        """)
        program_summary = cur.fetchall()

        # Program berisiko tinggi
        cur.execute("""
            SELECT refinery_unit, no_program_kerja,
                   program_kerja, equipment_tag_no,
                   status_step, status_prognosa,
                   top_risk, asset_integrity, finish_plan
            FROM irkap_program
            WHERE (top_risk IS NOT NULL AND top_risk != '')
               OR (asset_integrity IS NOT NULL AND asset_integrity != '')
            ORDER BY refinery_unit, finish_plan ASC NULLS LAST
            LIMIT 30
        """)
        risk_programs = cur.fetchall()

        # Completion dari irkap_actual
        cur.execute("""
            SELECT refinery_unit,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status_step ILIKE '%done%'
                              OR status_step ILIKE '%close%'
                              OR status_step ILIKE '%selesai%'
                             THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN status_prognosa ILIKE '%delay%'
                             THEN 1 ELSE 0 END) AS delayed,
                   ROUND(COALESCE(AVG(
                       COALESCE(comp15, comp14, comp13, comp12, comp11,
                                comp10, comp9,  comp8,  comp7,  comp6,
                                comp5,  comp4,  comp3,  comp2,  comp1, 0)
                   ), 0)::numeric, 1) AS avg_completion_pct
            FROM irkap_actual
            GROUP BY refinery_unit
            ORDER BY refinery_unit
        """)
        actual_summary = cur.fetchall()

        return {
            "program_summary": [dict(r) for r in program_summary],
            "risk_programs":   [dict(r) for r in risk_programs],
            "actual_summary":  [dict(r) for r in actual_summary],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 8. CRITICAL EQUIPMENT
# ─────────────────────────────────────────────────────────────────────────────

def _get_critical_equipment() -> dict:
    with _cursor() as cur:
        # Critical prim/sec dengan issue — urutkan Red dulu
        cur.execute("""
            SELECT refinery_unit, unit_proses, equipment,
                   highlight_issue, corrective_action,
                   target_corrective, traffic_corrective,
                   mitigasi_action, target_mitigasi,
                   traffic_mitigasi, month_update
            FROM critical_eqp_prim_sec
            WHERE highlight_issue IS NOT NULL
              AND highlight_issue != ''
            ORDER BY refinery_unit,
                     CASE UPPER(traffic_corrective)
                       WHEN 'RED'    THEN 1
                       WHEN 'YELLOW' THEN 2
                       WHEN 'GREEN'  THEN 3
                       ELSE 4 END
        """)
        prim_sec = cur.fetchall()

        # Critical UTL dengan issue
        cur.execute("""
            SELECT refinery_unit, type_equipment,
                   highlight_issue, corrective_action,
                   target_corrective, traffic_corrective,
                   mitigasi_action, traffic_mitigasi,
                   month_update
            FROM critical_eqp_utl
            WHERE highlight_issue IS NOT NULL
              AND highlight_issue != ''
            ORDER BY refinery_unit,
                     CASE UPPER(traffic_corrective)
                       WHEN 'RED'    THEN 1
                       WHEN 'YELLOW' THEN 2
                       WHEN 'GREEN'  THEN 3
                       ELSE 4 END
        """)
        utl = cur.fetchall()

        # Traffic summary per RU
        cur.execute("""
            SELECT refinery_unit,
                   SUM(CASE WHEN UPPER(traffic_corrective) = 'RED'
                             THEN 1 ELSE 0 END) AS red_count,
                   SUM(CASE WHEN UPPER(traffic_corrective) = 'YELLOW'
                             THEN 1 ELSE 0 END) AS yellow_count,
                   SUM(CASE WHEN UPPER(traffic_corrective) = 'GREEN'
                             THEN 1 ELSE 0 END) AS green_count
            FROM critical_eqp_prim_sec
            GROUP BY refinery_unit
            ORDER BY red_count DESC
        """)
        traffic_summary = cur.fetchall()

        return {
            "primary_secondary": [dict(r) for r in prim_sec],
            "utility":           [dict(r) for r in utl],
            "traffic_summary":   [dict(r) for r in traffic_summary],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 9. INSPECTION OVERDUE
# due_date bertipe Text — gunakan cast aman ke DATE
# ─────────────────────────────────────────────────────────────────────────────

def _get_inspection_overdue() -> dict:
    with _cursor() as cur:
        # Inspeksi overdue: due_date lewat, belum ada actual_date
        # Pakai TRY_CAST aman via CASE + to_date
        cur.execute("""
            SELECT refinery_unit, area, unit, tag_no_ln,
                   type_equipment, type_inspection,
                   due_date, plan_date, actual_date,
                   result_remaining_life, grand_result
            FROM inspection_plan
            WHERE actual_date IS NULL
              AND due_date IS NOT NULL
              AND due_date != ''
              AND (
                  due_date ~ '^\d{4}-\d{2}-\d{2}$'
                  AND to_date(due_date, 'YYYY-MM-DD') < CURRENT_DATE
              )
            ORDER BY refinery_unit, due_date ASC
            LIMIT 50
        """)
        overdue = cur.fetchall()

        # Summary per RU
        cur.execute("""
            SELECT refinery_unit,
                   COUNT(*) AS total_plan,
                   SUM(CASE WHEN actual_date IS NOT NULL
                             AND actual_date != '' THEN 1 ELSE 0 END) AS done,
                   SUM(CASE WHEN (actual_date IS NULL OR actual_date = '')
                             AND due_date ~ '^\d{4}-\d{2}-\d{2}$'
                             AND to_date(due_date, 'YYYY-MM-DD') < CURRENT_DATE
                             THEN 1 ELSE 0 END) AS overdue,
                   SUM(CASE WHEN result_remaining_life IS NOT NULL
                             AND result_remaining_life < 2
                             THEN 1 ELSE 0 END) AS low_rem_life
            FROM inspection_plan
            GROUP BY refinery_unit
            ORDER BY overdue DESC
        """)
        summary = cur.fetchall()

        return {
            "overdue_list": [dict(r) for r in overdue],
            "summary":      [dict(r) for r in summary],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 10. SAP — WO & Notifikasi
# ─────────────────────────────────────────────────────────────────────────────

def _get_sap_data() -> dict:
    with _cursor() as cur:
        # Summary WO per order_type (PTO2/PTO3/PTO5/PTO8)
        cur.execute("""
            SELECT order_type,
                   COUNT(*) AS total,
                   SUM(CASE WHEN system_status ILIKE '%REL%'
                             AND actual_finish IS NULL
                             THEN 1 ELSE 0 END) AS stagnant,
                   SUM(CASE WHEN system_status ILIKE '%TECO%'
                              OR system_status ILIKE '%CLSD%'
                             THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN basic_fin_date < CURRENT_DATE
                             AND system_status NOT ILIKE '%TECO%'
                             AND system_status NOT ILIKE '%CLSD%'
                             THEN 1 ELSE 0 END) AS overdue
            FROM sap_work_orders
            GROUP BY order_type
            ORDER BY order_type
        """)
        wo_summary = cur.fetchall()

        # PM Compliance — PTO3 adalah Preventive Maintenance
        cur.execute("""
            SELECT
                COUNT(*) AS total_pm,
                SUM(CASE WHEN system_status ILIKE '%TECO%'
                           OR system_status ILIKE '%CLSD%'
                         THEN 1 ELSE 0 END) AS completed_pm,
                SUM(CASE WHEN basic_fin_date < CURRENT_DATE
                          AND system_status NOT ILIKE '%TECO%'
                          AND system_status NOT ILIKE '%CLSD%'
                         THEN 1 ELSE 0 END) AS overdue_pm
            FROM sap_work_orders
            WHERE order_type ILIKE '%PTO3%'
        """)
        pm_compliance = cur.fetchone()

        # Equipment dengan notifikasi berulang (> 2 notif)
        cur.execute("""
            SELECT equipment,
                   location,
                   COUNT(*) AS notif_count,
                   STRING_AGG(DISTINCT notif_type, ', ') AS notif_types,
                   MAX(notif_date) AS latest_notif,
                   STRING_AGG(DISTINCT criticality, ', ') AS criticality
            FROM sap_notifications
            WHERE equipment IS NOT NULL
              AND equipment != ''
            GROUP BY equipment, location
            HAVING COUNT(*) > 2
            ORDER BY notif_count DESC
            LIMIT 20
        """)
        repeated_eq = cur.fetchall()

        # Backlog notifikasi kritis tanpa WO
        cur.execute("""
            SELECT notif_type, notification, description,
                   equipment, functional_loc, location,
                   criticality, required_end, system_status
            FROM sap_notifications
            WHERE (order_no IS NULL OR order_no = '')
              AND UPPER(criticality) IN ('1', '2', 'H', 'VH', 'HIGH', 'VERY HIGH')
            ORDER BY required_end ASC NULLS LAST
            LIMIT 30
        """)
        critical_backlog = cur.fetchall()

        # WO stagnant (REL tapi belum selesai, sudah lewat fin date)
        cur.execute("""
            SELECT order_no, order_type, system_status,
                   basic_fin_date, description,
                   equipment, criticality, location, main_workctr
            FROM sap_work_orders
            WHERE system_status ILIKE '%REL%'
              AND actual_finish IS NULL
              AND basic_fin_date < CURRENT_DATE
            ORDER BY basic_fin_date ASC
            LIMIT 30
        """)
        stagnant_wo = cur.fetchall()

        return {
            "wo_summary_by_type": [dict(r) for r in wo_summary],
            "pm_compliance":      dict(pm_compliance) if pm_compliance else {},
            "repeated_equipment": [dict(r) for r in repeated_eq],
            "critical_backlog":   [dict(r) for r in critical_backlog],
            "stagnant_wo":        [dict(r) for r in stagnant_wo],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 11. LAPORAN BULANAN
# ─────────────────────────────────────────────────────────────────────────────

def _get_laporan_bulanan() -> dict:
    with _cursor() as cur:
        cur.execute("""
            SELECT id,
                   COALESCE(title, 'Laporan Bulanan') AS title,
                   content,
                   created_at
            FROM reports
            WHERE type = 'monthly_reliability'
            ORDER BY created_at DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        if row:
            return {
                "id":         row["id"],
                "title":      row["title"],
                "created_at": str(row["created_at"]),
                "content":    row["content"][:8000],
            }
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE DATA — untuk modal "Lihat Sumber Data" di frontend
# ─────────────────────────────────────────────────────────────────────────────

def get_source_rows(key: str) -> tuple:
    """Return (rows: list[dict], columns: list[str], title: str)."""
    _SOURCES = {
        "paf":          _src_paf,
        "issue_paf":    _src_issue_paf,
        "bad_actor":    _src_bad_actor,
        "icu":          _src_icu,
        "boc":          _src_boc,
        "rcps":         _src_rcps,
        "irkap":        _src_irkap,
        "critical_eqp": _src_critical_eqp,
        "inspection":   _src_inspection,
        "sap_wo":       _src_sap_wo,
        "sap_notif":    _src_sap_notif,
    }
    if key not in _SOURCES:
        raise ValueError(f"Source key '{key}' tidak dikenal.")
    return _SOURCES[key]()


def _src_paf():
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, type, target_realisasi,
                   ROUND(COALESCE(value, 0)::numeric, 2) AS value,
                   ROUND(COALESCE(target, 0)::numeric, 2) AS target,
                   plan_unplan, month_update
            FROM paf
            WHERE code_current = 1
            ORDER BY ru, type, target_realisasi
        """)
        rows = [dict(r) for r in cur.fetchall()]
    cols = ["ru", "type", "target_realisasi", "value", "target", "plan_unplan", "month_update"]
    return rows, cols, "PAF — Plant Availability Factor (Periode Aktif)"


def _src_issue_paf():
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, type, date, issue, month_update
            FROM issue_paf
            WHERE code_current = 1
            ORDER BY ru, date DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
    cols = ["ru", "type", "date", "issue", "month_update"]
    return rows, cols, "Issue PAF — Penyebab Kehilangan Availability"


def _src_bad_actor():
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, tag_number, status, problem,
                   action_plan, category_action_plan,
                   progress, target_date, periode
            FROM bad_actor_monitoring
            ORDER BY ru,
                     CASE WHEN status ILIKE '%open%' OR status ILIKE '%progress%' THEN 1 ELSE 2 END,
                     periode DESC NULLS LAST
            LIMIT 100
        """)
        rows = [dict(r) for r in cur.fetchall()]
    cols = ["ru", "tag_number", "status", "problem", "action_plan",
            "category_action_plan", "progress", "target_date", "periode"]
    return rows, cols, "Bad Actor Monitoring — Equipment dengan Failure Berulang"


def _src_icu():
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, tag_no, icu_status, issue,
                   mitigation, mitigasi_category,
                   permanent_solution, progress,
                   target_closed, report_date
            FROM icu_monitoring
            WHERE icu_status NOT ILIKE '%close%'
            ORDER BY ru, report_date DESC NULLS LAST
            LIMIT 100
        """)
        rows = [dict(r) for r in cur.fetchall()]
    cols = ["ru", "tag_no", "icu_status", "issue", "mitigation",
            "mitigasi_category", "progress", "target_closed", "report_date"]
    return rows, cols, "ICU Monitoring — Integrity Concern Unit (Open)"


def _src_boc():
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, equipment, grup_equipment, status, frequency,
                   running_hours,
                   ROUND(COALESCE(mttr, 0)::numeric, 2) AS mttr,
                   ROUND(COALESCE(mtbf, 0)::numeric, 2) AS mtbf,
                   hasil
            FROM boc
            WHERE mtbf IS NOT NULL
            ORDER BY mtbf ASC
            LIMIT 100
        """)
        rows = [dict(r) for r in cur.fetchall()]
    cols = ["ru", "equipment", "grup_equipment", "status",
            "frequency", "running_hours", "mttr", "mtbf", "hasil"]
    return rows, cols, "BOC — MTBF & MTTR Equipment (Diurutkan MTBF Terendah)"


def _src_rcps():
    with _cursor() as cur:
        cur.execute("""
            SELECT kilang, rcps_no, judul_rcps, disiplin,
                   criticallity, traffic,
                   ROUND(COALESCE(sum_of_progress, 0)::numeric, 1) AS sum_of_progress,
                   date
            FROM rcps
            ORDER BY kilang,
                     CASE traffic WHEN 'Red' THEN 1 WHEN 'Yellow' THEN 2 WHEN 'Green' THEN 3 ELSE 4 END,
                     date DESC
            LIMIT 100
        """)
        rows = [dict(r) for r in cur.fetchall()]
    cols = ["kilang", "rcps_no", "judul_rcps", "disiplin",
            "criticallity", "traffic", "sum_of_progress", "date"]
    return rows, cols, "RCPS — Root Cause Problem Solving"


def _src_irkap():
    with _cursor() as cur:
        cur.execute("""
            SELECT refinery_unit, no_program_kerja, program_kerja,
                   equipment_tag_no, status_step, status_prognosa,
                   top_risk, asset_integrity, finish_plan
            FROM irkap_program
            ORDER BY refinery_unit,
                     CASE status_prognosa
                       WHEN 'Delay'      THEN 1
                       WHEN 'Carry Over' THEN 2
                       ELSE 3 END,
                     finish_plan ASC NULLS LAST
            LIMIT 100
        """)
        rows = [dict(r) for r in cur.fetchall()]
    cols = ["refinery_unit", "no_program_kerja", "program_kerja",
            "equipment_tag_no", "status_step", "status_prognosa", "top_risk", "finish_plan"]
    return rows, cols, "IRKAP — Program Kerja (Diurutkan Status Delay)"


def _src_critical_eqp():
    with _cursor() as cur:
        cur.execute("""
            SELECT refinery_unit, unit_proses, equipment,
                   highlight_issue, corrective_action,
                   target_corrective, traffic_corrective,
                   mitigasi_action, target_mitigasi,
                   traffic_mitigasi, month_update
            FROM critical_eqp_prim_sec
            WHERE highlight_issue IS NOT NULL AND highlight_issue != ''
            ORDER BY refinery_unit,
                     CASE UPPER(traffic_corrective)
                       WHEN 'RED' THEN 1 WHEN 'YELLOW' THEN 2 WHEN 'GREEN' THEN 3 ELSE 4 END
            LIMIT 80
        """)
        prim = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT refinery_unit,
                   type_equipment AS unit_proses,
                   NULL            AS equipment,
                   highlight_issue, corrective_action,
                   target_corrective, traffic_corrective,
                   mitigasi_action,
                   NULL            AS target_mitigasi,
                   traffic_mitigasi, month_update
            FROM critical_eqp_utl
            WHERE highlight_issue IS NOT NULL AND highlight_issue != ''
            ORDER BY refinery_unit,
                     CASE UPPER(traffic_corrective)
                       WHEN 'RED' THEN 1 WHEN 'YELLOW' THEN 2 WHEN 'GREEN' THEN 3 ELSE 4 END
            LIMIT 40
        """)
        utl = [dict(r) for r in cur.fetchall()]

    rows = prim + utl
    cols = ["refinery_unit", "unit_proses", "equipment", "highlight_issue",
            "corrective_action", "target_corrective", "traffic_corrective", "month_update"]
    return rows, cols, "Critical Equipment — Primary/Secondary & UTL dengan Issue"


def _src_inspection():
    with _cursor() as cur:
        cur.execute("""
            SELECT refinery_unit, area, unit, tag_no_ln,
                   type_equipment, type_inspection,
                   due_date, plan_date, actual_date,
                   result_remaining_life, grand_result
            FROM inspection_plan
            WHERE actual_date IS NULL
              AND due_date IS NOT NULL AND due_date != ''
              AND due_date ~ '^\d{4}-\d{2}-\d{2}$'
              AND to_date(due_date, 'YYYY-MM-DD') < CURRENT_DATE
            ORDER BY refinery_unit, due_date ASC
            LIMIT 100
        """)
        rows = [dict(r) for r in cur.fetchall()]
    cols = ["refinery_unit", "area", "unit", "tag_no_ln", "type_equipment",
            "type_inspection", "due_date", "plan_date", "result_remaining_life", "grand_result"]
    return rows, cols, "Inspection Plan — Overdue (Belum Ada Realisasi)"


def _src_sap_wo():
    with _cursor() as cur:
        cur.execute("""
            SELECT order_no, order_type, system_status,
                   basic_fin_date, description,
                   equipment, criticality, location, main_workctr
            FROM sap_work_orders
            WHERE (
                (system_status ILIKE '%REL%' AND actual_finish IS NULL
                 AND basic_fin_date < CURRENT_DATE)
                OR
                (basic_fin_date < CURRENT_DATE
                 AND system_status NOT ILIKE '%TECO%'
                 AND system_status NOT ILIKE '%CLSD%')
            )
            ORDER BY basic_fin_date ASC
            LIMIT 100
        """)
        rows = [dict(r) for r in cur.fetchall()]
    cols = ["order_no", "order_type", "system_status", "basic_fin_date",
            "description", "equipment", "criticality", "location"]
    return rows, cols, "SAP Work Orders — Stagnant & Overdue"


def _src_sap_notif():
    with _cursor() as cur:
        cur.execute("""
            SELECT notif_type, notification, description,
                   equipment, functional_loc, location,
                   criticality, required_end, system_status
            FROM sap_notifications
            WHERE (order_no IS NULL OR order_no = '')
              AND UPPER(criticality) IN ('1', '2', 'H', 'VH', 'HIGH', 'VERY HIGH')
            ORDER BY required_end ASC NULLS LAST
            LIMIT 100
        """)
        rows = [dict(r) for r in cur.fetchall()]
    cols = ["notif_type", "notification", "description", "equipment",
            "functional_loc", "location", "criticality", "required_end"]
    return rows, cols, "SAP Notifications — Critical Backlog (Belum Ada WO)"


def save_laporan_bulanan(title: str, content: str) -> int:
    """Simpan laporan bulanan — wrapper ke db.save_report."""
    """Simpan teks laporan bulanan ke tabel reports."""
    with _cursor() as cur:
        cur.execute("""
            INSERT INTO reports (type, title, content)
            VALUES ('monthly_reliability', %s, %s)
            RETURNING id
        """, (title, content))
        return cur.fetchone()["id"]