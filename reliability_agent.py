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
    model="gpt-4o",
    api_key=DINOIKI_API_KEY,
    base_url="https://ai.dinoiki.com/v1",
    temperature=0.2,
)

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPTS
# ─────────────────────────────────────────────────────────────────────────────

_BASE_SYSTEM = """Anda adalah Reliability Performance & Risk Agent untuk operasi kilang minyak Pertamina.

Tugas Anda adalah membaca performa reliability secara periodik dari sisi KPI, trend, leading-lagging indicator, operational availability, maintenance spend, asset integrity, dan hotspot risk untuk menilai kondisi kesehatan reliability secara menyeluruh, baik pada level nasional/konsolidasi maupun per Refinery Unit (RU).

RU YANG DIANALISIS:
1. RU II Dumai & Sungai Pakning
2. RU III Plaju
3. RU IV Cilacap
4. RU V Balikpapan
5. RU VI Balongan
6. RU VII Kasim

PRINSIP ANALISIS:
- Gunakan kombinasi leading DAN lagging indicator — jangan bertumpu pada satu KPI
- Bedakan: KPI hijau & risiko rendah / KPI hijau tapi leading melemah / KPI kuning / KPI merah
- Soroti mismatch antara KPI resmi dan sinyal operasional lapangan
- Bedakan masalah isolated equipment, unit-specific, RU-level, cross-RU, atau national governance
- Jangan overreact terhadap 1 event tunggal tanpa tren
- Jangan menyamakan korelasi dengan kausalitas
- Jika data tidak cukup, nyatakan keterbatasan secara eksplisit

KONDISI YANG WAJIB DISOROT:
- Lagging KPI baik tapi leading KPI melemah
- OA menurun meskipun PAF masih baik (masking effect)
- PM compliance baik tapi failure tetap tinggi
- Backlog critical meningkat; WO overdue/stagnant meningkat
- Maintenance spend meningkat tapi reliability tidak membaik
- AIMS KeyPI tercapai tapi outstanding critical integrity masih besar
- Inspection overdue pada equipment critical
- ICU open terkonsentrasi di RU tertentu
- Bad Actor open tidak menunjukkan closure trend
- RCPS critical/Red tidak bergerak
- Satu RU menjadi kontributor dominan risiko nasional
- Corrective/emergency spend terlalu dominan vs preventive

GUARD RAILS — Agent TIDAK boleh:
- Menilai performa hanya dari satu KPI
- Menyimpulkan membaik hanya karena PAF/OA di atas target
- Menganggap spending tinggi selalu baik
- Menganggap AIMS achievement tinggi berarti risk sudah terkendali
- Mengabaikan RU kecil hanya karena kontribusi nasionalnya kecil
- Memberikan rekomendasi tanpa prioritas, owner, dan timeframe

BAHASA: Formal Indonesia, tajam, berbasis data, tidak lebih optimistis dari evidence.
PEMBACA: Reliability Manager, VP Reliability, Plant Manager.

FORMAT OUTPUT WAJIB — gunakan heading berikut persis:

## 1. Executive Reliability Health Summary
(Ringkasan kondisi nasional: overall status, KPI yang baik, sinyal risiko, RU dengan risiko tertinggi. Gunakan status: Green/Yellow/Orange/Red.)

## 2. National Performance Overview
(PAF, OA, downtime, MTBF/MTTR, PM compliance, critical backlog, Bad Actor, AIMS, spend, risk concentration. Sertakan angka.)

## 3. RU Performance Review
(Analisis per RU: status, PAF/OA, leading concern, lagging concern, spend, AIMS, hotspot, management implication.)

## 4. Trend Direction
(Improving / Stable / Stagnant / Deteriorating / Insufficient data — per indikator utama. Jelaskan driver utamanya.)

## 5. Leading Indicator Concern
(PM compliance, critical backlog, inspection overdue, ICU open, AIMS outstanding, Bad Actor open, repeated notification, RCPS overdue, spend imbalance, risk mitigation overdue.)

## 6. Lagging Indicator Concern
(PAF, OA, downtime, unplanned shutdown, MTBF, MTTR, failure frequency. Sertakan angka per RU.)

## 7. Maintenance Spend Effectiveness
(Budget vs actual, absorption, spend by RU, efektivitas: apakah spend menurunkan backlog/failure/AIMS outstanding? Mismatch RU mana?)

## 8. Asset Integrity Management Review
(AIMS KeyPI achievement, outstanding, inspection overdue, ICU open, critical integrity threat, RU dengan exposure tertinggi.)

## 9. Risk Hotspots
(Daftar: RU | Unit | Equipment | Failure mode | Risk driver | Leading signal | Severity | Urgency: Critical/High/Medium/Low | Recommended action.)

## 10. KPI vs Field Signal Mismatch
(PAF baik tapi OA melemah; PM compliance baik tapi failure tinggi; AIMS tercapai tapi outstanding besar; spend tinggi tapi outcome tidak membaik; dll.)

## 11. Management Implication
(Format per isu: Issue | Why it matters | RU impacted | Risk if no action | Recommended action | Suggested owner | Timeframe | Expected outcome.)

## 12. Data Quality and Limitation
(Keterbatasan data: tren kurang panjang, data tidak lengkap per RU, tidak ada baseline, dll. Nyatakan confidence level.)"""


_WEEKLY_SUFFIX = """

MODE: WEEKLY PERFORMANCE REVIEW
Fokus tambahan:
- Perubahan atau anomali signifikan dalam periode terkini
- Apakah ada event yang perlu eskalasi minggu depan
- Konsistensi tren minggu ini dengan tren bulan berjalan
- Flag isu baru yang belum ada di periode sebelumnya
- Scoring per RU: 5 dimensi (Reliability Performance, Leading Indicator Strength, Lagging Indicator Impact, Asset Integrity Exposure, Maintenance Spend Effectiveness) → Green/Yellow/Orange/Red/Grey"""


_MONTHLY_SUFFIX = """

MODE: MONTHLY RELIABILITY HEALTH REVIEW
Fokus tambahan:
- Penilaian kesehatan sistem satu bulan penuh vs target RKAP
- Perbandingan realisasi vs target: PAF, OA, PM compliance, spend, AIMS
- Program kerja yang carry-over dan dampak risiko ke bulan depan
- Tren yang berkembang month-over-month
- Rekomendasi prioritas program untuk bulan berikutnya
- Scoring per RU: 5 dimensi (Reliability Performance, Leading Indicator Strength, Lagging Indicator Impact, Asset Integrity Exposure, Maintenance Spend Effectiveness) → Green/Yellow/Orange/Red/Grey
- Top 3 RU requiring attention; Top 5 management issues nasional"""


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
                f"RU: {r.get('ru_name') or r.get('ru')} | Type: {r.get('type')} | "
                f"{r.get('target_realisasi')}: {r.get('value')} | "
                f"Target: {r.get('target')} | "
                f"Plan/Unplan: {r.get('plan_unplan')} | "
                f"Periode: {r.get('month_update')}"
            )
    if paf.get("trend"):
        parts.append("--- Trend PAF Realisasi ---")
        for r in paf["trend"][:12]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | "
                f"Bulan: {r.get('month_update')} | "
                f"Avg Realisasi: {r.get('avg_value')}"
            )

    # ── ISSUE PAF ─────────────────────────────────────────────────────────────
    issues = data.get("issue_paf", [])
    if issues:
        parts.append("\n=== Issue PAF (Penyebab Kehilangan Availability) ===")
        for r in issues[:25]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | Type: {r.get('type')} | "
                f"Tanggal: {r.get('date')} | Issue: {r.get('issue')}"
            )

    # ── BAD ACTOR ─────────────────────────────────────────────────────────────
    bad = data.get("bad_actor", {})
    if bad.get("summary"):
        parts.append("\n=== Bad Actor Summary per RU ===")
        for r in bad["summary"]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | Total: {r.get('total')} | "
                f"Open: {r.get('open_count')} | Closed: {r.get('closed_count')}"
            )
    if bad.get("list"):
        parts.append("--- Detail Bad Actor (Open) ---")
        open_ba = [r for r in bad["list"]
                   if any(k in str(r.get("status", "")).lower()
                          for k in ("open", "progress", "inprogress"))]
        for r in open_ba[:15]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | "
                f"Tag: {r.get('equipment_tag')} | "
                f"Problem: {r.get('problem')} | Status: {r.get('status')} | "
                f"Action: {r.get('action_plan')} | Target: {r.get('target_date')}"
            )

    # ── ICU ───────────────────────────────────────────────────────────────────
    icu = data.get("icu", {})
    if icu.get("summary"):
        parts.append("\n=== ICU (Integrity Concern Unit) — Summary ===")
        for r in icu["summary"]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | Total: {r.get('total')} | "
                f"Open: {r.get('open_count')} | Closed: {r.get('closed_count')}"
            )
    if icu.get("open_list"):
        parts.append("--- ICU Open ---")
        for r in icu["open_list"][:15]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | "
                f"Tag: {r.get('equipment_tag')} | "
                f"Status: {r.get('icu_status')} | Issue: {r.get('issue')} | "
                f"Mitigasi: {r.get('mitigation')} | Target: {r.get('target_closed')}"
            )

    # ── BOC / MTBF ────────────────────────────────────────────────────────────
    boc = data.get("boc_mtbf", {})
    if boc.get("summary_by_ru"):
        parts.append("\n=== MTBF & MTTR Summary per RU ===")
        for r in boc["summary_by_ru"]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | "
                f"Avg MTBF: {r.get('avg_mtbf')} jam | "
                f"Avg MTTR: {r.get('avg_mttr')} jam | "
                f"Total Failures: {r.get('total_failures')}"
            )
    if boc.get("low_mtbf_equipment"):
        parts.append("--- Equipment MTBF Terendah ---")
        for r in boc["low_mtbf_equipment"][:10]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | "
                f"Equipment: {r.get('equipment_tag')} | "
                f"MTBF: {r.get('mtbf')} | MTTR: {r.get('mttr')} | "
                f"Frekuensi Failure: {r.get('frequency')} | Hasil: {r.get('hasil')}"
            )

    # ── RCPS ──────────────────────────────────────────────────────────────────
    rcps_list = data.get("rcps", [])
    if rcps_list:
        parts.append("\n=== RCPS (Root Cause & Progress) ===")
        for r in rcps_list[:12]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('kilang')} | No: {r.get('rcps_no')} | "
                f"Judul: {r.get('judul_rcps')} | "
                f"Traffic: {r.get('traffic')} | "
                f"Progress: {r.get('sum_of_progress')}%"
            )

    rcps_rek = data.get("rcps_rekomendasi", {})
    if rcps_rek.get("traffic_summary"):
        parts.append("\n=== RCPS Rekomendasi — Traffic Summary ===")
        for r in rcps_rek["traffic_summary"]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('kilang')} | "
                f"Traffic: {r.get('traffic')} | "
                f"Total: {r.get('total')}"
            )
    if rcps_rek.get("open_recommendations"):
        parts.append("--- RCPS Rekomendasi Belum Selesai ---")
        for r in rcps_rek["open_recommendations"][:10]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('kilang')} | "
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
                f"RU: {r.get('ru_name') or r.get('refinery_unit')} | "
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
                f"RU: {r.get('ru_name') or r.get('refinery_unit')} | "
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
                f"RU: {r.get('ru_name') or r.get('refinery_unit')} | "
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
                f"RU: {r.get('ru_name') or r.get('refinery_unit')} | "
                f"Equipment: {r.get('equipment_tag')} | "
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
                f"RU: {r.get('ru_name') or r.get('refinery_unit')} | "
                f"Equipment: {r.get('equipment_tag')} | "
                f"Issue: {r.get('highlight_issue')}"
            )

    # ── INSPECTION ────────────────────────────────────────────────────────────
    insp = data.get("inspection_overdue", {})
    if insp.get("summary"):
        parts.append("\n=== Inspection Plan — Summary per RU ===")
        for r in insp["summary"]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('refinery_unit')} | "
                f"Total Plan: {r.get('total_plan')} | "
                f"Done: {r.get('done')} | "
                f"Overdue: {r.get('overdue')} | "
                f"Remaining Life < 2 thn: {r.get('low_rem_life')}"
            )
    if insp.get("overdue_list"):
        parts.append("--- Inspection Overdue (Top 10) ---")
        for r in insp["overdue_list"][:10]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('refinery_unit')} | "
                f"Tag: {r.get('equipment_tag')} | "
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
        total_pm   = int(pm.get("total_pm") or 0)
        completed  = int(pm.get("completed_pm") or 0)
        overdue_pm = int(pm.get("overdue_pm") or 0)
        rate       = round((completed / total_pm) * 100, 1) if total_pm > 0 else 0
        parts.append(
            f"\n=== PM Compliance (PTO3) ===\n"
            f"Total PM WO: {total_pm} | "
            f"Completed: {completed} | "
            f"Overdue: {overdue_pm} | "
            f"Completion Rate: {rate}%"
        )

    if sap.get("repeated_equipment"):
        parts.append("\n=== Equipment Notifikasi Berulang (Leading Indicator) ===")
        for r in sap["repeated_equipment"][:10]:
            parts.append(
                f"RU: {r.get('ru_name')} | "
                f"Equipment: {r.get('equipment_tag')} | "
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
                f"RU: {r.get('ru_name')} | "
                f"WO: {r.get('order_no')} | "
                f"Type: {r.get('order_type')} | "
                f"Equipment: {r.get('equipment_tag')} | "
                f"Fin Date: {r.get('basic_fin_date')} | "
                f"Criticality: {r.get('criticality')}"
            )

    if sap.get("critical_backlog"):
        parts.append("\n=== Notifikasi Kritis Tanpa WO (Backlog) ===")
        for r in sap["critical_backlog"][:10]:
            parts.append(
                f"RU: {r.get('ru_name')} | "
                f"Notif: {r.get('notification')} | "
                f"Type: {r.get('notif_type')} | "
                f"Equipment: {r.get('equipment_tag')} | "
                f"Criticality: {r.get('criticality')} | "
                f"Required End: {r.get('required_end')}"
            )

    # ── MAINTENANCE SPEND ────────────────────────────────────────────────────
    if sap.get("spend_summary"):
        parts.append("\n=== Maintenance Spend Summary per RU ===")
        for r in sap["spend_summary"]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('plant')} | "
                f"Total WO: {r.get('total_wo')} | "
                f"Plan Cost: {r.get('plan_cost'):,} | "
                f"Act Cost: {r.get('act_cost'):,} | "
                f"Absorption: {r.get('absorption_pct')}%"
            )

    if sap.get("spend_by_ru_type"):
        parts.append("--- Spend per RU per Order Type ---")
        for r in sap["spend_by_ru_type"]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('plant')} | "
                f"Type: {r.get('order_type')} | "
                f"WO: {r.get('total_wo')} | "
                f"Plan: {r.get('plan_cost'):,} | "
                f"Act: {r.get('act_cost'):,}"
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
# DASHBOARD HTML PROMPT
# ─────────────────────────────────────────────────────────────────────────────

_DASHBOARD_SYSTEM = """Anda adalah dashboard HTML generator profesional untuk Reliability Performance & Risk kilang minyak Pertamina.

Berdasarkan hasil analisis yang diberikan, buat sebuah halaman HTML dashboard yang menyajikan informasi secara visual dan ringkas.

ATURAN WAJIB:
1. Output HANYA berupa kode HTML mentah, mulai dari <!DOCTYPE html> hingga </html>
2. JANGAN gunakan markdown code fence (``` atau ```html)
3. Semua CSS harus inline dalam <style> di dalam <head>
4. TIDAK BOLEH menggunakan library atau file eksternal (tidak ada CDN, tidak ada @import font)
5. Sertakan angka dan fakta AKTUAL dari analisis — bukan placeholder

STRUKTUR HALAMAN:
- <header>: Judul "Reliability Dashboard", badge mode (Weekly/Monthly), timestamp, overall health status badge (Green/Yellow/Orange/Red)
- <section id="kpi">: Row KPI cards (4–6 kolom)
- <section id="ru-status">: Row RU health status cards (1 per RU, 6 RU)
- <section id="sections">: Grid 2 kolom untuk section cards (## 1 s.d. ## 12)
- <footer>: Data Quality & Limitation note

KPI CARDS — ekstrak angka dari analisis:
- Tampilkan 4–6 KPI paling relevan (ICU Open, PM Compliance %, Inspection Overdue, WO Stagnant, Bad Actor Open, Critical Backlog)
- Tiap card: angka besar (30px bold), label, sub-keterangan
- Warna status:
  - Baik      → bg #dcfce7, border #bbf7d0, nilai #15803d
  - Perhatian → bg #fef3c7, border #fde68a, nilai #b45309
  - Kritis    → bg #fee2e2, border #fecaca, nilai #dc2626

RU STATUS CARDS — satu card per RU:
- Tampilkan 6 RU: RU II Dumai, RU III Plaju, RU IV Cilacap, RU V Balikpapan, RU VI Balongan, RU VII Kasim
- Tiap card: nama RU, overall status badge (Green/Yellow/Orange/Red), 2–3 poin singkat kondisi utama
- Warna card border sesuai status RU

SECTION CARDS (## 1 s.d. ## 12):
- Header: nomor + judul section + badge 🔴 Kritis / 🟡 Perhatian / 🟢 Baik / ⚪ Data Kurang
- Badge ditentukan dari kandungan section
- Isi: 3–5 bullet poin temuan terpenting; sertakan angka aktual; cetak tebal nilai kritis
- Section ## 1 (Executive Summary) dan ## 9 (Risk Hotspots) → grid-column: span 2
- Section ## 11 (Management Implication) → grid-column: span 2

DESAIN CSS:
- Background: #f1f5f9; Container max-width: 1200px; margin: auto; padding: 20px 16px
- Card: background #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px 20px; box-shadow: 0 1px 4px rgba(0,0,0,.05)
- Font: system-ui, -apple-system, Arial, sans-serif; base 13px; line-height 1.55
- Header accent (teal): #0d9488; teks gelap: #1e293b; teks muted: #64748b
- Section grid: grid-template-columns: 1fr 1fr; gap: 14px
- KPI grid: grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px
- RU grid: grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px
- Responsive: @media (max-width:640px) ubah semua grid menjadi 1 kolom
- Bullet poin padat, tidak perlu banyak whitespace

BAHASA: Indonesia.
Segera outputkan HANYA kode HTML, tanpa penjelasan lainnya."""


def _extract_html(raw: str) -> str:
    """Bersihkan output LLM — hapus code fence jika ada."""
    s = raw.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        # hapus baris pertama (```html atau ```) dan baris terakhir (```)
        inner = lines[1:] if lines[-1].strip() == "```" else lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        s = "\n".join(inner).strip()
    return s


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
    try:
        data = get_reliability_data()
    except Exception as e:
        raise RuntimeError(f"Gagal mengambil data dari database: {e}")

    # 2. Build konteks
    try:
        context = _build_context(data)
    except Exception as e:
        raise RuntimeError(f"Gagal membangun konteks: {e}")

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

    # 5. Call LLM — analisis
    response = llm.invoke([
        {"role": "system", "content": system},
        {"role": "user",   "content": user_msg},
    ])
    analysis_content = response.content

    # 6. Call LLM — generate HTML dashboard dari hasil analisis
    label = "Weekly" if mode == "weekly" else "Monthly"
    dashboard_user_msg = (
        f"Buat HTML dashboard dari hasil analisis reliability {label} berikut:\n\n"
        f"{analysis_content}"
    )
    try:
        dashboard_response = llm.invoke([
            {"role": "system", "content": _DASHBOARD_SYSTEM},
            {"role": "user",   "content": dashboard_user_msg},
        ])
        dashboard_html = _extract_html(dashboard_response.content)
    except Exception:
        dashboard_html = ""

    return {
        "content":        analysis_content,
        "dashboard_html": dashboard_html,
        "mode":           mode,
        "status":         "success",
    }