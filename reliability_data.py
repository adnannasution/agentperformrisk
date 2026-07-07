"""
reliability_data.py — Data Aggregator untuk Reliability Performance & Risk Agent
Mengambil dan merangkum data dari semua tabel relevan di database.
"""

import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Mapping SAP plant codes → nama RU kanonik
_RU_NORMALIZE = {
    "6201": "RU II Dumai",
    "6202": "RU II Pakning",
    "6301": "RU III Plaju",
    "6401": "RU IV Cilacap",
    "6501": "RU V Balikpapan",
    "6601": "RU VI Balongan",
    "6701": "RU VII Kasim",
}


def _normalize_ru(value) -> str:
    if value is None:
        return None
    return _RU_NORMALIZE.get(str(value).strip(), str(value).strip())


def _enrich_row(d: dict) -> dict:
    """Tambahkan ru_name dan equipment_tag ke setiap row dict."""
    raw_ru = d.get("ru") or d.get("refinery_unit") or d.get("kilang") \
             or d.get("plant") or d.get("maint_plant")
    d["ru_name"] = _normalize_ru(raw_ru)
    d["equipment_tag"] = d.get("equipment")
    return d


# backward-compat alias
_add_ru_name = _enrich_row


# ─── koneksi ─────────────────────────────────────────────────────────────────
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
    """Pastikan kolom & tipe yang dibutuhkan sudah ada. Aman dijalankan berulang."""
    stmts = [
        "ALTER TABLE reports ALTER COLUMN type TYPE VARCHAR(50);",
        "ALTER TABLE reports ADD COLUMN IF NOT EXISTS title VARCHAR(255);",
        "ALTER TABLE reliability_outputs ADD COLUMN IF NOT EXISTS dashboard_html TEXT;",
    ]
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            for sql in stmts:
                try:
                    cur.execute(sql)
                except Exception:
                    pass
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
        "oa":                 _get_oa(),
        "plo":                _get_plo(),
        "rcps":               _get_rcps(),
        "rcps_rekomendasi":   _get_rcps_rekomendasi(),
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
        cur.execute("""
            SELECT ru, type, target_realisasi, value, target,
                   plan_unplan, periode
            FROM paf
            WHERE code_current = 1
            ORDER BY ru, type
        """)
        current = cur.fetchall()

        cur.execute("""
            SELECT ru, periode,
                   ROUND(COALESCE(AVG(value), 0)::numeric, 2) AS avg_value
            FROM paf
            WHERE target_realisasi = 'Realisasi'
            GROUP BY ru, periode
            ORDER BY periode DESC
            LIMIT 36
        """)
        trend = cur.fetchall()

        return {
            "current": [_enrich_row(dict(r)) for r in current],
            "trend":   [_enrich_row(dict(r)) for r in trend],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 2. ISSUE PAF
# ─────────────────────────────────────────────────────────────────────────────

def _get_issue_paf() -> list:
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, type, issue, periode
            FROM issue_paf
            WHERE code_current = 1
            ORDER BY ru, periode DESC
        """)
        return [_enrich_row(dict(r)) for r in cur.fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# 3. BAD ACTOR
# ─────────────────────────────────────────────────────────────────────────────

def _get_bad_actor() -> dict:
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, equipment, status, problem,
                   action_plan, category_action_plan,
                   progress, periode
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
            "list":    [_enrich_row(dict(r)) for r in all_actors],
            "summary": [_enrich_row(dict(r)) for r in summary],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 4. ICU — Integrity Concern Unit
# ─────────────────────────────────────────────────────────────────────────────

def _get_icu() -> dict:
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, equipment, icu_status, issue,
                   mitigation, mitigasi_category,
                   permanent_solution, progress,
                   target_closed, periode
            FROM icu_monitoring
            WHERE icu_status NOT ILIKE '%close%'
            ORDER BY ru, periode DESC NULLS LAST
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
            "open_list": [_enrich_row(dict(r)) for r in open_icu],
            "summary":   [_enrich_row(dict(r)) for r in summary],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 5. BOC — MTBF & MTTR
# ─────────────────────────────────────────────────────────────────────────────

def _get_boc() -> dict:
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, equipment, grup_equipment,
                   status, frequency, running_hours,
                   mttr, mtbf, hasil, periode
            FROM boc
            WHERE mtbf IS NOT NULL AND mtbf > 0
            ORDER BY mtbf ASC
            LIMIT 20
        """)
        low_mtbf = cur.fetchall()

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
            "low_mtbf_equipment": [_enrich_row(dict(r)) for r in low_mtbf],
            "summary_by_ru":      [_enrich_row(dict(r)) for r in summary],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 6a. OA Monitoring
# ─────────────────────────────────────────────────────────────────────────────

def _get_oa() -> list:
    with _cursor() as cur:
        cur.execute("""
            SELECT refinery_unit, actual_target, value_perc, periode, color
            FROM oa_monitoring
            ORDER BY refinery_unit, actual_target
        """)
        return [_enrich_row(dict(r)) for r in cur.fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# 6b. PLO Monitoring
# ─────────────────────────────────────────────────────────────────────────────

def _get_plo() -> dict:
    with _cursor() as cur:
        cur.execute("""
            SELECT refinery_unit, nomor_ijin, nama_plo,
                   cakupan_unit_plant_kapasitas, date_expired,
                   sum_of_days_expired, status_plo, remarks
            FROM plo_monitoring
            ORDER BY refinery_unit, sum_of_days_expired DESC
        """)
        rows = [_enrich_row(dict(r)) for r in cur.fetchall()]

        expired     = [r for r in rows if str(r.get("status_plo","")).strip().lower() == "expired"]
        not_expired = [r for r in rows if str(r.get("status_plo","")).strip().lower() != "expired"]
        return {
            "all":         rows,
            "expired":     expired,
            "not_expired": not_expired,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 7. RCPS
# ─────────────────────────────────────────────────────────────────────────────

def _get_rcps() -> list:
    with _cursor() as cur:
        cur.execute("""
            SELECT kilang, rcps_no, judul_rcps, disiplin,
                   criticallity, traffic, sum_of_progress, periode
            FROM rcps
            ORDER BY kilang,
                     CASE traffic
                       WHEN 'Red'    THEN 1
                       WHEN 'Yellow' THEN 2
                       WHEN 'Green'  THEN 3
                       ELSE 4 END,
                     periode DESC
        """)
        return [_enrich_row(dict(r)) for r in cur.fetchall()]


def _get_rcps_rekomendasi() -> dict:
    with _cursor() as cur:
        cur.execute("""
            SELECT kilang, rcps_no, judul_rcps,
                   rekomendasi, traffic, pic,
                   target, recommendation_category, remark, periode
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
            "open_recommendations": [_enrich_row(dict(r)) for r in open_rekom],
            "traffic_summary":      [_enrich_row(dict(r)) for r in traffic_summary],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 8. CRITICAL EQUIPMENT
# ─────────────────────────────────────────────────────────────────────────────

def _get_critical_equipment() -> dict:
    with _cursor() as cur:
        cur.execute("""
            SELECT refinery_unit, unit_proses, equipment,
                   highlight_issue, corrective_action,
                   target_corrective, traffic_corrective,
                   mitigasi_action, target_mitigasi,
                   traffic_mitigasi, periode
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

        cur.execute("""
            SELECT refinery_unit, type_equipment,
                   equipment, highlight_issue, corrective_action,
                   target_corrective, traffic_corrective,
                   mitigasi_action, traffic_mitigasi, periode
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
            "primary_secondary": [_enrich_row(dict(r)) for r in prim_sec],
            "utility":           [_enrich_row(dict(r)) for r in utl],
            "traffic_summary":   [_enrich_row(dict(r)) for r in traffic_summary],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 9. INSPECTION OVERDUE
# ─────────────────────────────────────────────────────────────────────────────

def _get_inspection_overdue() -> dict:
    with _cursor() as cur:
        cur.execute("""
            SELECT refinery_unit, area, unit, equipment,
                   type_equipment, type_inspection,
                   due_date, plan_date, actual_date,
                   result_remaining_life, grand_result, periode
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
            "overdue_list": [_enrich_row(dict(r)) for r in overdue],
            "summary":      [_enrich_row(dict(r)) for r in summary],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 10. SAP — WO & Notifikasi
# ─────────────────────────────────────────────────────────────────────────────

def _get_sap_data() -> dict:
    with _cursor() as cur:
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

        cur.execute("""
            SELECT equipment,
                   location,
                   maint_plant,
                   COUNT(*) AS notif_count,
                   STRING_AGG(DISTINCT notif_type, ', ') AS notif_types,
                   MAX(required_end) AS latest_notif,
                   STRING_AGG(DISTINCT criticality, ', ') AS criticality
            FROM sap_notifications
            WHERE equipment IS NOT NULL
              AND equipment != ''
            GROUP BY equipment, location, maint_plant
            HAVING COUNT(*) > 2
            ORDER BY notif_count DESC
            LIMIT 20
        """)
        repeated_eq = cur.fetchall()

        cur.execute("""
            SELECT notif_type, notification, description,
                   equipment, functional_loc, location,
                   maint_plant, criticality, required_end, system_status
            FROM sap_notifications
            WHERE (order_no IS NULL OR order_no = '')
              AND UPPER(criticality) IN ('1', '2', 'H', 'VH', 'HIGH', 'VERY HIGH')
            ORDER BY required_end ASC NULLS LAST
            LIMIT 30
        """)
        critical_backlog = cur.fetchall()

        cur.execute("""
            SELECT order_no, order_type, system_status,
                   basic_fin_date, description,
                   equipment, criticality, location, main_workctr, plant
            FROM sap_work_orders
            WHERE system_status ILIKE '%REL%'
              AND actual_finish IS NULL
              AND basic_fin_date < CURRENT_DATE
            ORDER BY basic_fin_date ASC
            LIMIT 30
        """)
        stagnant_wo = cur.fetchall()

        # Anggaran per RU & order_type
        cur.execute("""
            SELECT plant,
                   order_type,
                   COUNT(*) AS total_wo,
                   ROUND(COALESCE(SUM(total_plan_cost), 0)::numeric, 0) AS plan_cost,
                   ROUND(COALESCE(SUM(total_act_cost),  0)::numeric, 0) AS act_cost
            FROM sap_work_orders
            WHERE plant IS NOT NULL AND plant != ''
            GROUP BY plant, order_type
            ORDER BY plant, order_type
        """)
        spend_by_ru_type = cur.fetchall()

        # Anggaran summary per RU
        cur.execute("""
            SELECT plant,
                   COUNT(*) AS total_wo,
                   ROUND(COALESCE(SUM(total_plan_cost), 0)::numeric, 0) AS plan_cost,
                   ROUND(COALESCE(SUM(total_act_cost),  0)::numeric, 0) AS act_cost,
                   ROUND(
                       CASE WHEN COALESCE(SUM(total_plan_cost), 0) > 0
                            THEN SUM(total_act_cost) / SUM(total_plan_cost) * 100
                            ELSE 0 END::numeric, 1
                   ) AS absorption_pct
            FROM sap_work_orders
            WHERE plant IS NOT NULL AND plant != ''
            GROUP BY plant
            ORDER BY act_cost DESC
        """)
        spend_summary = cur.fetchall()

        return {
            "wo_summary_by_type": [dict(r) for r in wo_summary],
            "pm_compliance":      dict(pm_compliance) if pm_compliance else {},
            "repeated_equipment": [_enrich_row(dict(r)) for r in repeated_eq],
            "critical_backlog":   [_enrich_row(dict(r)) for r in critical_backlog],
            "stagnant_wo":        [_enrich_row(dict(r)) for r in stagnant_wo],
            "spend_by_ru_type":   [_enrich_row(dict(r)) for r in spend_by_ru_type],
            "spend_summary":      [_enrich_row(dict(r)) for r in spend_summary],
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

def get_source_rows(key: str, ru: str = None) -> tuple:
    """Return (rows: list[dict], columns: list[str], title: str)."""
    _SOURCES = {
        "paf":          _src_paf,
        "issue_paf":    _src_issue_paf,
        "bad_actor":    _src_bad_actor,
        "icu":          _src_icu,
        "boc":          _src_boc,
        "rcps":         _src_rcps,
        "critical_eqp": _src_critical_eqp,
        "inspection":   _src_inspection,
        "sap_wo":       _src_sap_wo,
        "sap_notif":    _src_sap_notif,
        "oa":           _src_oa,
        "plo":          _src_plo,
    }
    if key not in _SOURCES:
        raise ValueError(f"Source key '{key}' tidak dikenal.")
    rows, columns, title = _SOURCES[key]()
    if ru:
        rows = [r for r in rows if (r.get("ru_name") or "").strip() == ru.strip()]
        title = f"{title} — {ru}"
    return rows, columns, title


def _src_paf():
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, type, target_realisasi,
                   ROUND(COALESCE(value, 0)::numeric, 2) AS value,
                   ROUND(COALESCE(target, 0)::numeric, 2) AS target,
                   plan_unplan, periode
            FROM paf
            WHERE code_current = 1
            ORDER BY ru, type, target_realisasi
        """)
        rows = [_enrich_row(dict(r)) for r in cur.fetchall()]
    cols = ["ru_name", "ru", "type", "target_realisasi", "value", "target", "plan_unplan", "periode"]
    return rows, cols, "PAF — Plant Availability Factor (Periode Aktif)"


def _src_issue_paf():
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, type, issue, periode
            FROM issue_paf
            WHERE code_current = 1
            ORDER BY ru, periode DESC
        """)
        rows = [_enrich_row(dict(r)) for r in cur.fetchall()]
    cols = ["ru_name", "ru", "type", "issue", "periode"]
    return rows, cols, "Issue PAF — Penyebab Kehilangan Availability"


def _src_bad_actor():
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, equipment, status, problem,
                   action_plan, category_action_plan,
                   progress, periode
            FROM bad_actor_monitoring
            ORDER BY ru,
                     CASE WHEN status ILIKE '%open%' OR status ILIKE '%progress%' THEN 1 ELSE 2 END,
                     periode DESC NULLS LAST
        """)
        rows = [_enrich_row(dict(r)) for r in cur.fetchall()]
    cols = ["ru_name", "ru", "equipment", "status", "problem", "action_plan",
            "category_action_plan", "progress", "periode"]
    return rows, cols, "Bad Actor Monitoring — Equipment dengan Failure Berulang"


def _src_icu():
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, equipment, icu_status, issue,
                   mitigation, mitigasi_category,
                   permanent_solution, progress,
                   target_closed, periode
            FROM icu_monitoring
            WHERE icu_status NOT ILIKE '%close%'
            ORDER BY ru, periode DESC NULLS LAST
        """)
        rows = [_enrich_row(dict(r)) for r in cur.fetchall()]
    cols = ["ru_name", "ru", "equipment", "icu_status", "issue", "mitigation",
            "mitigasi_category", "progress", "target_closed", "periode"]
    return rows, cols, "ICU Monitoring — Integrity Concern Unit (Open)"


def _src_boc():
    with _cursor() as cur:
        cur.execute("""
            SELECT ru, equipment, grup_equipment, status, frequency,
                   running_hours,
                   ROUND(COALESCE(mttr, 0)::numeric, 2) AS mttr,
                   ROUND(COALESCE(mtbf, 0)::numeric, 2) AS mtbf,
                   hasil, periode
            FROM boc
            WHERE mtbf IS NOT NULL
            ORDER BY mtbf ASC
        """)
        rows = [_enrich_row(dict(r)) for r in cur.fetchall()]
    cols = ["ru_name", "ru", "equipment", "grup_equipment", "status",
            "frequency", "running_hours", "mttr", "mtbf", "hasil", "periode"]
    return rows, cols, "BOC — MTBF & MTTR Equipment (Diurutkan MTBF Terendah)"


def _src_rcps():
    with _cursor() as cur:
        cur.execute("""
            SELECT kilang, rcps_no, judul_rcps, disiplin,
                   criticallity, traffic,
                   ROUND(COALESCE(sum_of_progress, 0)::numeric, 1) AS sum_of_progress,
                   periode
            FROM rcps
            ORDER BY kilang,
                     CASE traffic WHEN 'Red' THEN 1 WHEN 'Yellow' THEN 2 WHEN 'Green' THEN 3 ELSE 4 END,
                     periode DESC
        """)
        rows = [_enrich_row(dict(r)) for r in cur.fetchall()]
    cols = ["ru_name", "kilang", "rcps_no", "judul_rcps", "disiplin",
            "criticallity", "traffic", "sum_of_progress", "periode"]
    return rows, cols, "RCPS — Root Cause Problem Solving"


def _src_critical_eqp():
    with _cursor() as cur:
        cur.execute("""
            SELECT refinery_unit, unit_proses, equipment,
                   highlight_issue, corrective_action,
                   target_corrective, traffic_corrective,
                   mitigasi_action, target_mitigasi,
                   traffic_mitigasi, periode
            FROM critical_eqp_prim_sec
            WHERE highlight_issue IS NOT NULL AND highlight_issue != ''
            ORDER BY refinery_unit,
                     CASE UPPER(traffic_corrective)
                       WHEN 'RED' THEN 1 WHEN 'YELLOW' THEN 2 WHEN 'GREEN' THEN 3 ELSE 4 END
        """)
        prim = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT refinery_unit,
                   type_equipment AS unit_proses,
                   equipment,
                   highlight_issue, corrective_action,
                   target_corrective, traffic_corrective,
                   mitigasi_action,
                   NULL AS target_mitigasi,
                   traffic_mitigasi, periode
            FROM critical_eqp_utl
            WHERE highlight_issue IS NOT NULL AND highlight_issue != ''
            ORDER BY refinery_unit,
                     CASE UPPER(traffic_corrective)
                       WHEN 'RED' THEN 1 WHEN 'YELLOW' THEN 2 WHEN 'GREEN' THEN 3 ELSE 4 END
        """)
        utl = [dict(r) for r in cur.fetchall()]

    rows = [_enrich_row(r) for r in prim + utl]
    cols = ["ru_name", "refinery_unit", "unit_proses", "equipment", "highlight_issue",
            "corrective_action", "target_corrective", "traffic_corrective", "periode"]
    return rows, cols, "Critical Equipment — Primary/Secondary & UTL dengan Issue"


def _src_inspection():
    with _cursor() as cur:
        cur.execute("""
            SELECT refinery_unit, area, unit, equipment,
                   type_equipment, type_inspection,
                   due_date, plan_date, actual_date,
                   result_remaining_life, grand_result, periode
            FROM inspection_plan
            WHERE actual_date IS NULL
              AND due_date IS NOT NULL AND due_date != ''
              AND due_date ~ '^\d{4}-\d{2}-\d{2}$'
              AND to_date(due_date, 'YYYY-MM-DD') < CURRENT_DATE
            ORDER BY refinery_unit, due_date ASC
        """)
        rows = [_enrich_row(dict(r)) for r in cur.fetchall()]
    cols = ["ru_name", "refinery_unit", "area", "unit", "equipment", "type_equipment",
            "type_inspection", "due_date", "plan_date", "result_remaining_life", "grand_result", "periode"]
    return rows, cols, "Inspection Plan — Overdue (Belum Ada Realisasi)"


def _src_sap_wo():
    with _cursor() as cur:
        cur.execute("""
            SELECT order_no, order_type, system_status,
                   basic_fin_date, description,
                   equipment, criticality, location, main_workctr, plant
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
        """)
        rows = [_enrich_row(dict(r)) for r in cur.fetchall()]
    cols = ["ru_name", "plant", "order_no", "order_type", "system_status",
            "basic_fin_date", "description", "equipment", "criticality", "location"]
    return rows, cols, "SAP Work Orders — Stagnant & Overdue"


def _src_sap_notif():
    with _cursor() as cur:
        cur.execute("""
            SELECT notif_type, notification, description,
                   equipment, functional_loc, location,
                   maint_plant, criticality, required_end, system_status
            FROM sap_notifications
            WHERE (order_no IS NULL OR order_no = '')
              AND UPPER(criticality) IN ('1', '2', 'H', 'VH', 'HIGH', 'VERY HIGH')
            ORDER BY required_end ASC NULLS LAST
        """)
        rows = [_enrich_row(dict(r)) for r in cur.fetchall()]
    cols = ["ru_name", "maint_plant", "notif_type", "notification", "description",
            "equipment", "functional_loc", "location", "criticality", "required_end"]
    return rows, cols, "SAP Notifications — Critical Backlog (Belum Ada WO)"


def _src_oa():
    with _cursor() as cur:
        cur.execute("""
            SELECT refinery_unit, actual_target, value_perc, periode, color
            FROM oa_monitoring ORDER BY refinery_unit, actual_target
        """)
        rows = [_enrich_row(dict(r)) for r in cur.fetchall()]
    cols = ["ru_name", "refinery_unit", "actual_target", "value_perc", "periode", "color"]
    return rows, cols, "OA Monitoring — Overall Availability"


def _src_plo():
    with _cursor() as cur:
        cur.execute("""
            SELECT refinery_unit, nomor_ijin, nama_plo,
                   cakupan_unit_plant_kapasitas, date_expired,
                   sum_of_days_expired, status_plo, remarks
            FROM plo_monitoring ORDER BY refinery_unit, sum_of_days_expired DESC
        """)
        rows = [_enrich_row(dict(r)) for r in cur.fetchall()]
    cols = ["ru_name", "refinery_unit", "nomor_ijin", "nama_plo",
            "cakupan_unit_plant_kapasitas", "date_expired", "sum_of_days_expired", "status_plo", "remarks"]
    return rows, cols, "PLO Monitoring — Perizinan Legalitas Operasional"


def get_dashboard_data() -> dict:
    """Aggregasi ringkas dari semua tabel untuk chart dashboard."""
    with _cursor() as cur:
        cur.execute("""
            SELECT ru,
                   ROUND(COALESCE(MAX(CASE WHEN target_realisasi='Realisasi' THEN value END), 0)::numeric, 2) AS realisasi,
                   ROUND(COALESCE(MAX(CASE WHEN target_realisasi='Target'    THEN value END), 0)::numeric, 2) AS target
            FROM paf
            WHERE code_current = 1
            GROUP BY ru ORDER BY ru
        """)
        paf_per_ru = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT ru,
                   COUNT(*) FILTER (WHERE icu_status NOT ILIKE '%close%') AS open_count,
                   COUNT(*) AS total
            FROM icu_monitoring
            GROUP BY ru ORDER BY ru
        """)
        icu_per_ru = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT COALESCE(traffic, 'Unknown') AS traffic, COUNT(*) AS count
            FROM rcps
            GROUP BY traffic
            ORDER BY CASE traffic WHEN 'Red' THEN 1 WHEN 'Yellow' THEN 2 WHEN 'Green' THEN 3 ELSE 4 END
        """)
        rcps_traffic = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT
                SUM(CASE WHEN status ILIKE '%open%'
                           OR status ILIKE '%progress%'
                           OR status ILIKE '%inprog%'  THEN 1 ELSE 0 END) AS open_count,
                SUM(CASE WHEN status ILIKE '%close%'
                           OR status ILIKE '%done%'
                           OR status ILIKE '%selesai%' THEN 1 ELSE 0 END) AS closed_count,
                COUNT(*) AS total
            FROM bad_actor_monitoring
        """)
        bad_actor_summary = dict(cur.fetchone() or {})

        cur.execute("""
            SELECT ru,
                   ROUND(COALESCE(AVG(mtbf), 0)::numeric, 1) AS avg_mtbf,
                   ROUND(COALESCE(AVG(mttr), 0)::numeric, 1) AS avg_mttr,
                   COALESCE(SUM(frequency), 0)               AS total_failures
            FROM boc
            WHERE mtbf IS NOT NULL
            GROUP BY ru ORDER BY ru
        """)
        boc_per_ru = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT
                COUNT(*) AS total_pm,
                SUM(CASE WHEN system_status ILIKE '%TECO%'
                           OR system_status ILIKE '%CLSD%' THEN 1 ELSE 0 END) AS completed_pm,
                SUM(CASE WHEN basic_fin_date < CURRENT_DATE
                          AND system_status NOT ILIKE '%TECO%'
                          AND system_status NOT ILIKE '%CLSD%' THEN 1 ELSE 0 END) AS overdue_pm
            FROM sap_work_orders
            WHERE order_type ILIKE '%PTO3%'
        """)
        pm = dict(cur.fetchone() or {})

        cur.execute("""
            SELECT refinery_unit AS ru,
                   SUM(CASE WHEN (actual_date IS NULL OR actual_date = '')
                             AND due_date ~ '^\d{4}-\d{2}-\d{2}$'
                             AND to_date(due_date, 'YYYY-MM-DD') < CURRENT_DATE
                             THEN 1 ELSE 0 END) AS overdue,
                   COUNT(*) AS total
            FROM inspection_plan
            GROUP BY refinery_unit ORDER BY refinery_unit
        """)
        inspection_per_ru = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT COUNT(*) AS stagnant_count
            FROM sap_work_orders
            WHERE system_status ILIKE '%REL%'
              AND actual_finish IS NULL
              AND basic_fin_date < CURRENT_DATE
        """)
        stagnant = dict(cur.fetchone() or {})

        cur.execute("""
            SELECT refinery_unit AS ru, actual_target,
                   ROUND((value_perc * 100)::numeric, 2) AS value_pct,
                   periode, color
            FROM oa_monitoring
            ORDER BY refinery_unit, actual_target
        """)
        oa_per_ru = [_enrich_row(dict(r)) for r in cur.fetchall()]

        cur.execute("""
            SELECT refinery_unit AS ru,
                   COUNT(*) FILTER (WHERE LOWER(status_plo) = 'expired') AS expired_count,
                   COUNT(*) AS total
            FROM plo_monitoring
            GROUP BY refinery_unit ORDER BY refinery_unit
        """)
        plo_per_ru = [_enrich_row(dict(r)) for r in cur.fetchall()]

        plo_expired_total = sum(int(r.get('expired_count') or 0) for r in plo_per_ru)

        # Anggaran per RU dari SAP WO
        cur.execute("""
            SELECT plant,
                   ROUND(COALESCE(SUM(total_plan_cost), 0)::numeric, 0) AS plan_cost,
                   ROUND(COALESCE(SUM(total_act_cost),  0)::numeric, 0) AS act_cost,
                   ROUND(
                       CASE WHEN COALESCE(SUM(total_plan_cost), 0) > 0
                            THEN SUM(total_act_cost) / SUM(total_plan_cost) * 100
                            ELSE 0 END::numeric, 1
                   ) AS absorption_pct
            FROM sap_work_orders
            WHERE plant IS NOT NULL AND plant != ''
            GROUP BY plant
            ORDER BY act_cost DESC
        """)
        anggaran_per_ru = [_enrich_row(dict(r)) for r in cur.fetchall()]

    icu_open   = sum(int(r.get('open_count') or 0) for r in icu_per_ru)
    ins_over   = sum(int(r.get('overdue')    or 0) for r in inspection_per_ru)
    rcps_red   = next((int(r['count']) for r in rcps_traffic if r['traffic'] == 'Red'), 0)
    total_pm   = int(pm.get('total_pm') or 0)
    comp_pm    = int(pm.get('completed_pm') or 0)
    pm_pct     = round(comp_pm / total_pm * 100, 1) if total_pm else 0

    return {
        "kpi": {
            "icu_open":            icu_open,
            "bad_actor_open":      int(bad_actor_summary.get('open_count')  or 0),
            "inspection_overdue":  ins_over,
            "pm_compliance_pct":   pm_pct,
            "rcps_red":            rcps_red,
            "stagnant_wo":         int(stagnant.get('stagnant_count') or 0),
            "plo_expired":         plo_expired_total,
        },
        "paf_per_ru":        paf_per_ru,
        "icu_per_ru":        icu_per_ru,
        "rcps_traffic":      rcps_traffic,
        "bad_actor_summary": bad_actor_summary,
        "boc_per_ru":        [_enrich_row(r) for r in boc_per_ru],
        "pm_compliance":     pm,
        "inspection_per_ru": inspection_per_ru,
        "oa_per_ru":         oa_per_ru,
        "plo_per_ru":        plo_per_ru,
        "anggaran_per_ru":   anggaran_per_ru,
    }


def save_laporan_bulanan(title: str, content: str) -> int:
    """Simpan laporan bulanan ke tabel reports."""
    with _cursor() as cur:
        cur.execute("""
            INSERT INTO reports (type, title, content)
            VALUES ('monthly_reliability', %s, %s)
            RETURNING id
        """, (title, content))
        return cur.fetchone()["id"]
