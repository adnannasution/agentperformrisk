"""
reliability_agent.py — Reliability Performance & Risk Agent
Membaca KPI, trend, leading-lagging indicator, dan hotspot risk
untuk menilai health reliability secara menyeluruh.
"""

import os
from langchain_openai import ChatOpenAI
from reliability_data import get_reliability_data

DINOIKI_API_KEY = os.getenv("DINOIKI_API_KEY", "")

llm = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=DINOIKI_API_KEY,
    base_url="https://ai.dinoiki.com/v1",
    temperature=0.2,
)

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPTS
# ─────────────────────────────────────────────────────────────────────────────

_BASE_SYSTEM = """Anda adalah Reliability Performance & Risk Agent untuk operasi kilang minyak Pertamina.

Tugas Anda adalah membaca KPI, trend, leading-lagging indicator, dan hotspot risk
untuk menilai health reliability sistem secara menyeluruh dan periodik.

FOKUS ANALISIS:
- Apakah performa sistem membaik, stagnan, atau memburuk?
- Apa sinyal dini (leading indicator) yang perlu diwaspadai?
- Di area atau equipment mana risiko terkonsentrasi?
- Apakah KPI resmi mencerminkan kondisi nyata di lapangan?

ATURAN ANALISIS:
- Gunakan kombinasi leading DAN lagging indicator — jangan bertumpu pada satu KPI
- Soroti mismatch antara angka resmi dan sinyal operasional
- Jangan overreact terhadap 1 event tunggal tanpa melihat tren
- Jangan menutup warning hanya karena lagging KPI masih baik
- Bila data tren kurang panjang, nyatakan keterbatasan secara eksplisit
- Jangan menyamakan korelasi dengan kausalitas

KONDISI YANG HARUS DISOROT:
- Lagging KPI baik tapi leading KPI melemah
- Repeated event pada hotspot yang sama
- PM compliance baik tapi failure tetap tinggi
- Backlog critical meningkat
- Risk hotspot terkonsentrasi di RU atau equipment tertentu
- Gap antara KPI official dan sinyal operasional (ICU, Bad Actor, notifikasi SAP berulang)
- Equipment dengan MTBF rendah dan MTTR tinggi
- Inspection overdue pada equipment kritis
- RCPS rekomendasi traffic Red yang belum dieksekusi

BAHASA: Formal Indonesia, tajam, berbasis data, tidak lebih optimistis dari evidence.
PEMBACA: Reliability Manager, VP Reliability, Plant Manager.

FORMAT OUTPUT WAJIB — gunakan heading ini persis, jangan diubah:

## 1. Reliability Performance Overview
(Satu paragraf: status keseluruhan sistem saat ini — membaik / stagnan / memburuk dan mengapa. Sebutkan angka kunci.)

## 2. Trend Direction
(Arah tren 3 indikator utama: PAF, failure frequency, backlog WO. Sebutkan apakah naik, turun, atau flat dan apa artinya.)

## 3. Leading Indicator Concern
(Sinyal dini yang perlu diwaspadai: ICU open, repeated notification SAP, inspection overdue, RCPS Red, Bad Actor open. Urutkan dari paling kritis.)

## 4. Lagging Indicator Status
(Status KPI hasil: PAF aktual vs target per RU, MTBF/MTTR, PM completion rate, WO overdue. Sertakan angka.)

## 5. Risk Hotspots
(Daftar RU / equipment / area dengan konsentrasi risiko tertinggi. Format: nama → alasan → tingkat urgensi.)

## 6. Management Implication
(Keputusan atau tindakan konkret yang dibutuhkan manajemen dalam 1-2 minggu ke depan. Sertakan PIC yang disarankan jika relevan.)"""


_WEEKLY_SUFFIX = """

MODE: WEEKLY PERFORMANCE REVIEW
Fokus tambahan:
- Perubahan atau anomali signifikan dalam periode terkini
- Apakah ada event yang perlu eskalasi minggu depan
- Konsistensi tren minggu ini dengan tren bulan berjalan
- Flag isu baru yang belum ada di bulan lalu"""


_MONTHLY_SUFFIX = """

MODE: MONTHLY RELIABILITY HEALTH REVIEW
Fokus tambahan:
- Penilaian kesehatan sistem satu bulan penuh vs target RKAP
- Perbandingan realisasi vs target: PAF, PM compliance, anggaran
- Program kerja yang carry-over dan dampak risiko ke bulan depan
- Tren yang berkembang month-over-month
- Rekomendasi prioritas program untuk bulan berikutnya"""


# ─────────────────────────────────────────────────────────────────────────────
# CONTEXT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _build_context(data: dict) -> str:
    parts = []

    # ── PAF ──────────────────────────────────────────────────────────────────
    paf = data.get("paf", {})
    if paf.get("current"):
        parts.append("=== PAF (Plant Availability Factor) — Data Terkini ===")
        for r in paf["current"]:
            parts.append(
                f"RU: {r.get('ru')} | Type: {r.get('type')} | "
                f"{r.get('target_realisasi')}: {r.get('value')} | "
                f"Target: {r.get('target')} | "
                f"Plan/Unplan: {r.get('plan_unplan')} | "
                f"Periode: {r.get('month_update')}"
            )
    if paf.get("trend"):
        parts.append("--- Trend PAF Realisasi ---")
        for r in paf["trend"][:12]:
            parts.append(
                f"RU: {r.get('ru')} | Bulan: {r.get('month_update')} | "
                f"Avg Realisasi: {r.get('avg_value')}"
            )

    # ── ISSUE PAF ─────────────────────────────────────────────────────────────
    issues = data.get("issue_paf", [])
    if issues:
        parts.append("\n=== Issue PAF (Penyebab Kehilangan Availability) ===")
        for r in issues[:25]:
            parts.append(
                f"RU: {r.get('ru')} | Type: {r.get('type')} | "
                f"Tanggal: {r.get('date')} | Issue: {r.get('issue')}"
            )

    # ── BAD ACTOR ─────────────────────────────────────────────────────────────
    bad = data.get("bad_actor", {})
    if bad.get("summary"):
        parts.append("\n=== Bad Actor Summary per RU ===")
        for r in bad["summary"]:
            parts.append(
                f"RU: {r.get('ru')} | Total: {r.get('total')} | "
                f"Open: {r.get('open_count')} | Closed: {r.get('closed_count')}"
            )
    if bad.get("list"):
        parts.append("--- Detail Bad Actor (Open) ---")
        open_ba = [r for r in bad["list"]
                   if any(k in str(r.get("status", "")).lower()
                          for k in ("open", "progress", "inprogress"))]
        for r in open_ba[:15]:
            parts.append(
                f"RU: {r.get('ru')} | Tag: {r.get('tag_number')} | "
                f"Problem: {r.get('problem')} | Status: {r.get('status')} | "
                f"Action: {r.get('action_plan')} | Target: {r.get('target_date')}"
            )

    # ── ICU ───────────────────────────────────────────────────────────────────
    icu = data.get("icu", {})
    if icu.get("summary"):
        parts.append("\n=== ICU (Integrity Concern Unit) — Summary ===")
        for r in icu["summary"]:
            parts.append(
                f"RU: {r.get('ru')} | Total: {r.get('total')} | "
                f"Open: {r.get('open_count')} | Closed: {r.get('closed_count')}"
            )
    if icu.get("open_list"):
        parts.append("--- ICU Open ---")
        for r in icu["open_list"][:15]:
            parts.append(
                f"RU: {r.get('ru')} | Tag: {r.get('tag_no')} | "
                f"Status: {r.get('icu_status')} | Issue: {r.get('issue')} | "
                f"Mitigasi: {r.get('mitigation')} | Target: {r.get('target_closed')}"
            )

    # ── BOC / MTBF ────────────────────────────────────────────────────────────
    boc = data.get("boc_mtbf", {})
    if boc.get("summary_by_ru"):
        parts.append("\n=== MTBF & MTTR Summary per RU ===")
        for r in boc["summary_by_ru"]:
            parts.append(
                f"RU: {r.get('ru')} | "
                f"Avg MTBF: {r.get('avg_mtbf')} jam | "
                f"Avg MTTR: {r.get('avg_mttr')} jam | "
                f"Total Failures: {r.get('total_failures')}"
            )
    if boc.get("low_mtbf_equipment"):
        parts.append("--- Equipment MTBF Terendah ---")
        for r in boc["low_mtbf_equipment"][:10]:
            parts.append(
                f"RU: {r.get('ru')} | Equipment: {r.get('equipment')} | "
                f"MTBF: {r.get('mtbf')} | MTTR: {r.get('mttr')} | "
                f"Frekuensi Failure: {r.get('frequency')} | Hasil: {r.get('hasil')}"
            )

    # ── RCPS ──────────────────────────────────────────────────────────────────
    rcps_list = data.get("rcps", [])
    if rcps_list:
        parts.append("\n=== RCPS (Root Cause & Progress) ===")
        for r in rcps_list[:12]:
            parts.append(
                f"Kilang: {r.get('kilang')} | No: {r.get('rcps_no')} | "
                f"Judul: {r.get('judul_rcps')} | "
                f"Traffic: {r.get('traffic')} | "
                f"Progress: {r.get('sum_of_progress')}%"
            )

    rcps_rek = data.get("rcps_rekomendasi", {})
    if rcps_rek.get("traffic_summary"):
        parts.append("\n=== RCPS Rekomendasi — Traffic Summary ===")
        for r in rcps_rek["traffic_summary"]:
            parts.append(
                f"Kilang: {r.get('kilang')} | "
                f"Traffic: {r.get('traffic')} | "
                f"Total: {r.get('total')}"
            )
    if rcps_rek.get("open_recommendations"):
        parts.append("--- RCPS Rekomendasi Belum Selesai ---")
        for r in rcps_rek["open_recommendations"][:10]:
            parts.append(
                f"Kilang: {r.get('kilang')} | "
                f"Rekomendasi: {r.get('rekomendasi')} | "
                f"Traffic: {r.get('traffic')} | "
                f"PIC: {r.get('pic')} | Target: {r.get('target')}"
            )

    # ── IRKAP ─────────────────────────────────────────────────────────────────
    irkap = data.get("irkap_summary", {})
    if irkap.get("program_summary"):
        parts.append("\n=== IRKAP Program Summary per RU ===")
        for r in irkap["program_summary"]:
            parts.append(
                f"RU: {r.get('refinery_unit')} | "
                f"Total: {r.get('total_program')} | "
                f"On Track: {r.get('on_track')} | "
                f"Delay: {r.get('delay')} | "
                f"Carry Over: {r.get('carry_over')} | "
                f"Has Top Risk: {r.get('has_top_risk')}"
            )
    if irkap.get("actual_summary"):
        parts.append("--- IRKAP Actual Completion ---")
        for r in irkap["actual_summary"]:
            parts.append(
                f"RU: {r.get('refinery_unit')} | "
                f"Total: {r.get('total')} | "
                f"Completed: {r.get('completed')} | "
                f"Delayed: {r.get('delayed')} | "
                f"Avg Completion: {r.get('avg_completion_pct')}%"
            )

    # ── CRITICAL EQUIPMENT ────────────────────────────────────────────────────
    crit = data.get("critical_equipment", {})
    if crit.get("traffic_summary"):
        parts.append("\n=== Critical Equipment — Traffic Summary ===")
        for r in crit["traffic_summary"]:
            parts.append(
                f"RU: {r.get('refinery_unit')} | "
                f"Red: {r.get('red_count')} | "
                f"Yellow: {r.get('yellow_count')} | "
                f"Green: {r.get('green_count')}"
            )

    red_items = [r for r in crit.get("primary_secondary", [])
                 if str(r.get("traffic_corrective", "")).upper() == "RED"]
    if red_items:
        parts.append("--- Critical Equipment Status RED ---")
        for r in red_items[:10]:
            parts.append(
                f"RU: {r.get('refinery_unit')} | "
                f"Equipment: {r.get('equipment')} | "
                f"Issue: {r.get('highlight_issue')} | "
                f"Action: {r.get('corrective_action')} | "
                f"Target: {r.get('target_corrective')}"
            )

    yellow_items = [r for r in crit.get("primary_secondary", [])
                    if str(r.get("traffic_corrective", "")).upper() == "YELLOW"]
    if yellow_items:
        parts.append("--- Critical Equipment Status YELLOW ---")
        for r in yellow_items[:8]:
            parts.append(
                f"RU: {r.get('refinery_unit')} | "
                f"Equipment: {r.get('equipment')} | "
                f"Issue: {r.get('highlight_issue')}"
            )

    # ── INSPECTION ────────────────────────────────────────────────────────────
    insp = data.get("inspection_overdue", {})
    if insp.get("summary"):
        parts.append("\n=== Inspection Plan — Summary per RU ===")
        for r in insp["summary"]:
            parts.append(
                f"RU: {r.get('refinery_unit')} | "
                f"Total Plan: {r.get('total_plan')} | "
                f"Done: {r.get('done')} | "
                f"Overdue: {r.get('overdue')} | "
                f"Remaining Life < 2 thn: {r.get('low_rem_life')}"
            )
    if insp.get("overdue_list"):
        parts.append("--- Inspection Overdue (Top 10) ---")
        for r in insp["overdue_list"][:10]:
            parts.append(
                f"RU: {r.get('refinery_unit')} | "
                f"Tag: {r.get('tag_no_ln')} | "
                f"Type: {r.get('type_inspection')} | "
                f"Due: {r.get('due_date')} | "
                f"Rem Life: {r.get('result_remaining_life')} thn"
            )

    # ── SAP ───────────────────────────────────────────────────────────────────
    sap = data.get("sap", {})
    if sap.get("wo_summary_by_type"):
        parts.append("\n=== SAP Work Order — Summary per Type ===")
        for r in sap["wo_summary_by_type"]:
            parts.append(
                f"Type: {r.get('order_type')} | "
                f"Total: {r.get('total')} | "
                f"Stagnant: {r.get('stagnant')} | "
                f"Completed: {r.get('completed')} | "
                f"Overdue: {r.get('overdue')}"
            )

    pm = sap.get("pm_compliance", {})
    if pm:
        total = pm.get("total_pm") or 1
        rate  = round((pm.get("completed_pm", 0) / total) * 100, 1)
        parts.append(
            f"\n=== PM Compliance (PTO3) ===\n"
            f"Total PM WO: {pm.get('total_pm')} | "
            f"Completed: {pm.get('completed_pm')} | "
            f"Overdue: {pm.get('overdue_pm')} | "
            f"Completion Rate: {rate}%"
        )

    if sap.get("repeated_equipment"):
        parts.append("\n=== Equipment Notifikasi Berulang (Leading Indicator) ===")
        for r in sap["repeated_equipment"][:10]:
            parts.append(
                f"Equipment: {r.get('equipment')} | "
                f"Location: {r.get('location')} | "
                f"Notif Count: {r.get('notif_count')} | "
                f"Types: {r.get('notif_types')} | "
                f"Latest: {r.get('latest_notif')} | "
                f"Criticality: {r.get('criticality')}"
            )

    if sap.get("stagnant_wo"):
        parts.append("\n=== WO Stagnant (REL, Overdue, Belum Selesai) ===")
        for r in sap["stagnant_wo"][:10]:
            parts.append(
                f"WO: {r.get('order_no')} | "
                f"Type: {r.get('order_type')} | "
                f"Equipment: {r.get('equipment')} | "
                f"Fin Date: {r.get('basic_fin_date')} | "
                f"Criticality: {r.get('criticality')}"
            )

    if sap.get("critical_backlog"):
        parts.append("\n=== Notifikasi Kritis Tanpa WO (Backlog) ===")
        for r in sap["critical_backlog"][:10]:
            parts.append(
                f"Notif: {r.get('notification')} | "
                f"Type: {r.get('notif_type')} | "
                f"Equipment: {r.get('equipment')} | "
                f"Criticality: {r.get('criticality')} | "
                f"Required End: {r.get('required_end')}"
            )

    # ── LAPORAN BULANAN ───────────────────────────────────────────────────────
    lap = data.get("laporan_bulanan", {})
    if lap.get("content"):
        parts.append(
            f"\n=== Laporan Bulanan Reliability "
            f"({lap.get('title', '')} — {lap.get('created_at', '')}) ==="
        )
        parts.append(lap["content"])

    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# RUN AGENT
# ─────────────────────────────────────────────────────────────────────────────

def run_reliability_agent(mode: str = "weekly") -> dict:
    """
    Jalankan Reliability Performance & Risk Agent.

    Args:
        mode: 'weekly' atau 'monthly'

    Returns:
        dict dengan keys: content, mode, status
    """
    if mode not in ("weekly", "monthly"):
        raise ValueError(f"mode harus 'weekly' atau 'monthly', bukan '{mode}'")

    # 1. Ambil semua data dari DB
    data = get_reliability_data()

    # 2. Build konteks
    context = _build_context(data)

    # 3. Pilih system prompt
    suffix = _WEEKLY_SUFFIX if mode == "weekly" else _MONTHLY_SUFFIX
    system = _BASE_SYSTEM + suffix

    # 4. Build user message
    label = "Weekly Performance Review" if mode == "weekly" else "Monthly Reliability Health Review"
    user_msg = (
        f"Berikut adalah data reliability kilang yang perlu dianalisis:\n\n"
        f"{context}\n\n"
        f"Berikan analisis reliability lengkap sesuai format yang ditentukan.\n"
        f"Mode: {label}"
    )

    # 5. Call LLM
    response = llm.invoke([
        {"role": "system", "content": system},
        {"role": "user",   "content": user_msg},
    ])

    return {
        "content": response.content,
        "mode":    mode,
        "status":  "success",
    }
