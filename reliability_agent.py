"""
reliability_agent.py — Reliability Performance & Risk Agent
Membaca KPI, trend, leading-lagging indicator, dan hotspot risk
untuk menilai health reliability secara menyeluruh.
"""

import os
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from reliability_data import get_reliability_data

DINOIKI_API_KEY   = os.getenv("DINOIKI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

llm = ChatOpenAI(
    model="gpt-4o",
    api_key=DINOIKI_API_KEY,
    base_url="https://ai.dinoiki.com/v1",
    temperature=0.2,
)

llm_dashboard = ChatAnthropic(
    model="claude-sonnet-4-6",
    api_key=ANTHROPIC_API_KEY,
    temperature=0.7,
    max_tokens=16000,
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

def _filter_ru(rows: list, ru: str) -> list:
    """Filter list of row dicts to a specific RU name. Pass-through if ru is None."""
    if not ru:
        return rows
    return [r for r in rows if (r.get("ru_name") or "").strip() == ru.strip()]


def _count_by_ru(rows: list, ru: str, key_name: str = "ru_name") -> str:
    """Return per-RU count string, e.g. 'RU II: 34, RU IV: 87'"""
    from collections import Counter
    filtered = _filter_ru(rows, ru) if ru else rows
    counts = Counter((r.get(key_name) or r.get("ru") or "Unknown") for r in filtered)
    return ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))


def _build_context(data: dict, ru: str = None) -> str:
    """Build LLM context string. If ru is set, filter rows to that RU only."""
    parts = []
    if ru:
        parts.append(f"[SCOPE: Analisis terfokus pada {ru} saja]\n")

    # ── OA (Overall Availability) ────────────────────────────────────────────
    oa_rows = data.get("oa", [])
    if oa_rows:
        filtered_oa = _filter_ru(oa_rows, ru)
        parts.append("=== OA (Overall Availability) ===")
        parts.append(f"[STATS] Total OA rows: {len(filtered_oa)} | Per RU: {_count_by_ru(filtered_oa, None)}")
        for r in filtered_oa[:20]:
            pct_val = float(r.get('value_perc') or 0) * 100
            parts.append(
                f"RU: {r.get('ru_name') or r.get('refinery_unit')} | "
                f"{r.get('actual_target')}: {pct_val:.2f}% | "
                f"Bulan: {r.get('month_update')} | Warna: {r.get('color')}"
            )

    # ── PLO (Perizinan Legalitas Operasional) ────────────────────────────────
    plo = data.get("plo", {})
    if plo.get("all"):
        plo_filtered = _filter_ru(plo["all"], ru)
        plo_expired  = [r for r in plo_filtered if str(r.get("status_plo","")).lower() == "expired"]
        parts.append("\n=== PLO Monitoring (Perizinan Legalitas Operasional) ===")
        parts.append(f"[STATS] Total PLO: {len(plo_filtered)} | Expired: {len(plo_expired)} | Per RU: {_count_by_ru(plo_filtered, None)}")
        for r in plo_expired[:15]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('refinery_unit')} | "
                f"Nomor: {r.get('nomor_ijin')} | Nama: {r.get('nama_plo')} | "
                f"Expired: {r.get('date_expired')} | Hari: {r.get('sum_of_days_expired')} | "
                f"Status: {r.get('status_plo')}"
            )

    # ── PAF ──────────────────────────────────────────────────────────────────
    paf = data.get("paf", {})
    if paf.get("current"):
        parts.append("=== PAF (Plant Availability Factor) — Data Terkini ===")
        for r in _filter_ru(paf["current"], ru):
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | Type: {r.get('type')} | "
                f"{r.get('target_realisasi')}: {r.get('value')} | "
                f"Target: {r.get('target')} | "
                f"Plan/Unplan: {r.get('plan_unplan')} | "
                f"Periode: {r.get('month_update')}"
            )
    if paf.get("trend"):
        parts.append("--- Trend PAF Realisasi ---")
        for r in _filter_ru(paf["trend"], ru)[:12]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | "
                f"Bulan: {r.get('month_update')} | "
                f"Avg Realisasi: {r.get('avg_value')}"
            )

    # ── ISSUE PAF ─────────────────────────────────────────────────────────────
    issues = data.get("issue_paf", [])
    if issues:
        filtered_issues = _filter_ru(issues, ru)
        parts.append(f"\n=== Issue PAF (Penyebab Kehilangan Availability) ===")
        parts.append(f"[STATS] Total Issue PAF: {len(filtered_issues)} | Per RU: {_count_by_ru(issues, ru)}")
        for r in filtered_issues[:25]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | Type: {r.get('type')} | "
                f"Tanggal: {r.get('date')} | Issue: {r.get('issue')}"
            )

    # ── BAD ACTOR ─────────────────────────────────────────────────────────────
    bad = data.get("bad_actor", {})
    if bad.get("summary"):
        parts.append("\n=== Bad Actor Summary per RU ===")
        for r in _filter_ru(bad["summary"], ru):
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | Total: {r.get('total')} | "
                f"Open: {r.get('open_count')} | Closed: {r.get('closed_count')}"
            )
    if bad.get("list"):
        all_ba    = _filter_ru(bad["list"], ru)
        open_ba   = [r for r in all_ba if any(k in str(r.get("status", "")).lower()
                     for k in ("open", "progress", "inprogress"))]
        parts.append(f"[STATS] Bad Actor — Total: {len(all_ba)} | Open: {len(open_ba)} | Per RU (open): {_count_by_ru(open_ba, None)}")
        parts.append("--- Detail Bad Actor (Open) ---")
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
        for r in _filter_ru(icu["summary"], ru):
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | Total: {r.get('total')} | "
                f"Open: {r.get('open_count')} | Closed: {r.get('closed_count')}"
            )
    if icu.get("open_list"):
        open_icu = _filter_ru(icu["open_list"], ru)
        parts.append(f"[STATS] ICU Open: {len(open_icu)} | Per RU: {_count_by_ru(open_icu, None)}")
        parts.append("--- ICU Open ---")
        for r in open_icu[:15]:
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
        for r in _filter_ru(boc["summary_by_ru"], ru):
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | "
                f"Avg MTBF: {r.get('avg_mtbf')} jam | "
                f"Avg MTTR: {r.get('avg_mttr')} jam | "
                f"Total Failures: {r.get('total_failures')}"
            )
    if boc.get("low_mtbf_equipment"):
        parts.append("--- Equipment MTBF Terendah ---")
        for r in _filter_ru(boc["low_mtbf_equipment"], ru)[:10]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | "
                f"Equipment: {r.get('equipment_tag')} | "
                f"MTBF: {r.get('mtbf')} | MTTR: {r.get('mttr')} | "
                f"Frekuensi Failure: {r.get('frequency')} | Hasil: {r.get('hasil')}"
            )

    # ── RCPS ──────────────────────────────────────────────────────────────────
    rcps_list = data.get("rcps", [])
    if rcps_list:
        filtered_rcps = _filter_ru(rcps_list, ru)
        red_rcps = [r for r in filtered_rcps if str(r.get("traffic","")).upper() == "RED"]
        parts.append(f"\n=== RCPS (Root Cause & Progress) ===")
        parts.append(f"[STATS] Total RCPS: {len(filtered_rcps)} | Traffic RED: {len(red_rcps)} | Per RU: {_count_by_ru(filtered_rcps, None, 'kilang')}")
        for r in filtered_rcps[:12]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('kilang')} | No: {r.get('rcps_no')} | "
                f"Judul: {r.get('judul_rcps')} | "
                f"Traffic: {r.get('traffic')} | "
                f"Progress: {r.get('sum_of_progress')}%"
            )

    rcps_rek = data.get("rcps_rekomendasi", {})
    if rcps_rek.get("traffic_summary"):
        parts.append("\n=== RCPS Rekomendasi — Traffic Summary ===")
        for r in _filter_ru(rcps_rek["traffic_summary"], ru):
            parts.append(
                f"RU: {r.get('ru_name') or r.get('kilang')} | "
                f"Traffic: {r.get('traffic')} | "
                f"Total: {r.get('total')}"
            )
    if rcps_rek.get("open_recommendations"):
        open_rek = _filter_ru(rcps_rek["open_recommendations"], ru)
        parts.append(f"[STATS] RCPS Rekomendasi Belum Selesai: {len(open_rek)}")
        parts.append("--- RCPS Rekomendasi Belum Selesai ---")
        for r in open_rek[:10]:
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
        for r in _filter_ru(irkap["program_summary"], ru):
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
        for r in _filter_ru(irkap["actual_summary"], ru):
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
        for r in _filter_ru(crit["traffic_summary"], ru):
            parts.append(
                f"RU: {r.get('ru_name') or r.get('refinery_unit')} | "
                f"Red: {r.get('red_count')} | "
                f"Yellow: {r.get('yellow_count')} | "
                f"Green: {r.get('green_count')}"
            )

    all_crit = _filter_ru(crit.get("primary_secondary", []), ru)
    red_items    = [r for r in all_crit if str(r.get("traffic_corrective", "")).upper() == "RED"]
    yellow_items = [r for r in all_crit if str(r.get("traffic_corrective", "")).upper() == "YELLOW"]
    if all_crit:
        parts.append(f"[STATS] Critical Equipment — RED: {len(red_items)} | YELLOW: {len(yellow_items)}")
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
        total_overdue = sum(int(r.get("overdue") or 0) for r in _filter_ru(insp["summary"], ru))
        total_plan    = sum(int(r.get("total_plan") or 0) for r in _filter_ru(insp["summary"], ru))
        parts.append(f"[STATS] Total Plan: {total_plan} | Total Overdue: {total_overdue} | Per RU overdue: " +
                     ", ".join(f"{r.get('ru_name') or r.get('refinery_unit')}: {r.get('overdue')}"
                               for r in _filter_ru(insp["summary"], ru)))
        for r in _filter_ru(insp["summary"], ru):
            parts.append(
                f"RU: {r.get('ru_name') or r.get('refinery_unit')} | "
                f"Total Plan: {r.get('total_plan')} | "
                f"Done: {r.get('done')} | "
                f"Overdue: {r.get('overdue')} | "
                f"Remaining Life < 2 thn: {r.get('low_rem_life')}"
            )
    if insp.get("overdue_list"):
        parts.append("--- Inspection Overdue (Top 10) ---")
        for r in _filter_ru(insp["overdue_list"], ru)[:10]:
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
        total_wo       = sum(int(r.get("total") or 0) for r in sap["wo_summary_by_type"])
        total_stagnant = sum(int(r.get("stagnant") or 0) for r in sap["wo_summary_by_type"])
        total_overdue_wo = sum(int(r.get("overdue") or 0) for r in sap["wo_summary_by_type"])
        parts.append(f"\n=== SAP Work Order — Summary per Type ===")
        parts.append(f"[STATS] Total WO: {total_wo} | Stagnant: {total_stagnant} | Overdue: {total_overdue_wo}")
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
            f"[STATS] Total PM WO: {total_pm} | Completed: {completed} | "
            f"Overdue: {overdue_pm} | Completion Rate: {rate}%"
        )

    if sap.get("repeated_equipment"):
        rep_eq = _filter_ru(sap["repeated_equipment"], ru)
        parts.append(f"\n=== Equipment Notifikasi Berulang (Leading Indicator) ===")
        parts.append(f"[STATS] Total equipment dengan notifikasi berulang: {len(rep_eq)}")
        for r in rep_eq[:10]:
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
        stag = _filter_ru(sap["stagnant_wo"], ru)
        parts.append(f"\n=== WO Stagnant (REL, Overdue, Belum Selesai) ===")
        parts.append(f"[STATS] Total WO Stagnant: {len(stag)} | Per RU: {_count_by_ru(stag, None)}")
        for r in stag[:10]:
            parts.append(
                f"RU: {r.get('ru_name')} | "
                f"WO: {r.get('order_no')} | "
                f"Type: {r.get('order_type')} | "
                f"Equipment: {r.get('equipment_tag')} | "
                f"Fin Date: {r.get('basic_fin_date')} | "
                f"Criticality: {r.get('criticality')}"
            )

    if sap.get("critical_backlog"):
        cb = _filter_ru(sap["critical_backlog"], ru)
        parts.append(f"\n=== Notifikasi Kritis Tanpa WO (Backlog) ===")
        parts.append(f"[STATS] Total Critical Backlog: {len(cb)} | Per RU: {_count_by_ru(cb, None)}")
        for r in cb[:10]:
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
        spend_rows  = _filter_ru(sap["spend_summary"], ru)
        total_plan  = sum(float(r.get("plan_cost") or 0) for r in spend_rows)
        total_act   = sum(float(r.get("act_cost") or 0) for r in spend_rows)
        avg_abs     = round((total_act / total_plan * 100), 1) if total_plan > 0 else 0
        parts.append(f"\n=== Maintenance Spend Summary per RU ===")
        parts.append(f"[STATS] Total Plan Cost: {total_plan:,.0f} | Total Actual Cost: {total_act:,.0f} | Avg Absorption: {avg_abs}%")
        for r in spend_rows:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('plant')} | "
                f"Total WO: {r.get('total_wo')} | "
                f"Plan Cost: {r.get('plan_cost'):,} | "
                f"Act Cost: {r.get('act_cost'):,} | "
                f"Absorption: {r.get('absorption_pct')}%"
            )

    if sap.get("spend_by_ru_type"):
        parts.append("--- Spend per RU per Order Type ---")
        for r in _filter_ru(sap["spend_by_ru_type"], ru):
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

_DASHBOARD_SYSTEM_OVERALL = """Kamu adalah desainer infografis eksekutif kelas dunia. Buat infografis HTML yang sangat visual, cantik, dan informatif dari hasil analisis reliability kilang minyak Pertamina berikut.

ATURAN OUTPUT: Kembalikan HANYA kode HTML mentah mulai dari <!DOCTYPE html>. Tanpa markdown fence. Semua CSS di dalam <style>. Tidak ada CDN atau resource eksternal.
Semua teks dalam Bahasa Indonesia. Semua angka dan data HARUS diambil dari analisis — tidak boleh placeholder.

Buat infografis sekantik dan sedetail mungkin. Gunakan kreativitasmu sepenuhnya dengan:
- Header putih bersih dengan aksen teal/biru profesional, judul besar "MONTHLY/WEEKLY RELIABILITY HEALTH REVIEW" + nama scope berwarna teal atau biru tua
- Layout multi-kolom seperti laporan eksekutif / majalah
- Badge status berwarna (HIJAU/KUNING/ORANYE/MERAH)
- Chart SVG inline: donut gauge untuk %, horizontal bar untuk per-RU, sparkline untuk trend
- Tabel data dengan baris berwarna sesuai severity
- Icon/emoji yang relevan di setiap section
- Section yang jelas: Executive Summary, KPI Scorecard, Leading & Lagging Indicator, Trend Direction, Risk Hotspot, Maintenance Spend, Management Action Plan, Data Quality
- Semua informasi penting dari analisis HARUS muncul di infografis
- Gunakan warna, shadow, border-radius, grid untuk tampilan premium

BAHASA KONTEN: Indonesia.
Output HANYA kode HTML mentah. Mulai langsung dengan <!DOCTYPE html>."""


_DASHBOARD_SYSTEM_PER_RU = """Kamu adalah desainer infografis eksekutif kelas dunia. Buat infografis HTML yang sangat visual, cantik, dan informatif dari hasil analisis reliability satu Refinery Unit (RU) kilang minyak Pertamina berikut.

ATURAN OUTPUT: Kembalikan HANYA kode HTML mentah mulai dari <!DOCTYPE html>. Tanpa markdown fence. Semua CSS di dalam <style>. Tidak ada CDN atau resource eksternal.
Semua teks dalam Bahasa Indonesia. Semua angka dan data HARUS diambil dari analisis — tidak boleh placeholder.

Buat infografis sekantik dan sedetail mungkin. Gunakan kreativitasmu sepenuhnya dengan:
- Header putih bersih dengan aksen teal/biru profesional, judul besar "MONTHLY/WEEKLY RELIABILITY HEALTH REVIEW" + nama RU dalam warna teal atau biru tua, besar dan mencolok
- Status nasional vs status RU dalam badge berwarna besar yang mencolok
- Layout multi-kolom seperti laporan boardroom / majalah eksekutif
- KPI yang Baik vs Sinyal Risiko Utama dengan icon dan warna kontras
- Chart SVG inline: donut gauge untuk %, horizontal bar untuk perbandingan, sparkline untuk trend
- Tabel Risk Hotspot dengan equipment tag, severity, urgency, recommended action
- Tabel Management Action Plan
- Section: Executive Summary, National vs RU Status, Leading Concern, Lagging Concern, Trend Direction, Maintenance Spend Effectiveness, Asset Integrity, Risk Hotspot, KPI vs Field Signal Mismatch, Management Action Plan, Data Quality
- Semua informasi dari analisis HARUS muncul
- Gunakan warna, shadow, border-radius, grid, icon/emoji untuk tampilan premium dan profesional

━━━ VISUAL DESIGN SYSTEM ━━━
Light professional theme (white/grey):
  --bg:#f1f5f9; --surface:#ffffff; --surface2:#f8fafc; --border:#e2e8f0
  --teal:#0d9488; --text:#0f172a; --muted:#64748b
  Status colors: Green #16a34a / Yellow #ca8a04 / Orange #ea580c / Red #dc2626 / Grey #64748b
  Status bgs:    #dcfce7 / #fef9c3 / #ffedd5 / #fee2e2 / #f1f5f9

Typography: 'Segoe UI', system-ui, Arial, sans-serif; base 13px/1.6; font-variant-numeric:tabular-nums on numbers
Cards: border-radius:14px; padding:20px 24px; border:1px solid var(--border); box-shadow:0 2px 8px rgba(0,0,0,.06)

━━━ STATUS BADGE ━━━
Pill: padding 3px 10px; border-radius:20px; font-size:11px; font-weight:700
  Green→bg #dcfce7;color #16a34a;border:1px solid #bbf7d0 | Yellow→bg #fef9c3;color #ca8a04;border:1px solid #fde68a
  Orange→bg #ffedd5;color #ea580c;border:1px solid #fed7aa | Red→bg #fee2e2;color #dc2626;border:1px solid #fecaca

━━━ SVG CHART COMPONENTS (inline, zero dependencies) ━━━

CHART A — Horizontal Bar (compare KPI values, e.g. ICU/Bad Actor trend or multi-metric for this RU):
  <svg viewBox="0 0 380 [height]" width="100%" style="display:block">
    For each row: label left (x=0), track rect (x=120,w=220,fill=#e2e8f0), fill rect (x=120,w=[pct*220],fill=[color]), value text right (x=345)
    Bar height:18px, gap rows at y+=32
  </svg>

CHART B — Donut Gauge (single % KPI — PAF, PM compliance, absorption):
  <svg viewBox="0 0 120 120" width="110" height="110">
    <circle cx="60" cy="60" r="44" fill="none" stroke="#e2e8f0" stroke-width="12"/>
    <circle cx="60" cy="60" r="44" fill="none" stroke="[color]" stroke-width="12"
      stroke-dasharray="[pct*276.5] 276.5" stroke-dashoffset="69.1"
      transform="rotate(-90 60 60)" stroke-linecap="round"/>
    <text x="60" y="56" text-anchor="middle" font-size="20" font-weight="800" fill="[color]">[val]%</text>
    <text x="60" y="72" text-anchor="middle" font-size="9" fill="#64748b">[label]</text>
  </svg>
  (circumference 2π×44≈276.5; dashoffset 276.5×0.25≈69.1 to start from top)

CHART C — Mini Sparkline (trend 5–7 points, width=120 height=40):
  Scale points: x evenly spaced 0–120, y map min→36 max→4
  <polyline points="..." fill="none" stroke="[color]" stroke-width="2" stroke-linejoin="round"/>
  Last point: <circle r="3" fill="[color]"/>

━━━ PAGE STRUCTURE ━━━

[1] HERO HEADER (full-width, bg:#ffffff, border-bottom:1px solid #e2e8f0, padding:24px 32px)
  Top row: breadcrumb "Reliability Dashboard / [RU Name]" in muted | Right: mode badge + timestamp
  Main row:
    Left: Large RU name (24px, 800, #0d9488) + location subtitle + overall status badge (16px pill) + generated date
    Right: 5-DIMENSION SCORECARD — horizontal flex row of 5 score chips:
      Each chip (padding:8px 16px; border-radius:10px; border:1px solid #e2e8f0; bg:#f8fafc; text-center):
        - Dimension label (10px muted uppercase)
        - Status color circle (12px)
        - Status text (13px bold, status color)
      Dimensions: Reliability Performance | Leading Indicator | Lagging Indicator | Asset Integrity | Maintenance Spend
      Colors from ## 1 Executive Summary scoring

[2] CONTAINER (max-width:1200px; margin:0 auto; padding:24px 28px)

[3] EXECUTIVE SUMMARY + STATUS PANEL (2-column: 65% / 35%, gap:16px)
  Left card: Extract ## 1 content
    - "Kondisi Umum" row with overall status + 1-sentence summary
    - Key findings as styled bullet rows (colored dot + bold finding + muted detail)
    - Critical items: border-left:3px solid #dc2626; bg:#fee2e2; padding:8px 12px; border-radius:6px; margin:4px 0
  Right card: "Risk Scorecard"
    - 5 rows, each dimension: label (left) + status badge (right) + progress-like fill bar
    - Bar: height:3px; bg:#e2e8f0; fill color by status; width proportional (Green=90%, Yellow=65%, Orange=40%, Red=20%)
    - Bottom: "Prioritas Perhatian" — top 2 concerns as highlighted pills

[4] KPI METRICS ROW (8 cards max, grid:repeat(4,1fr) gap:12px)
  Each KPI card (surface):
    Top: icon (36px rounded square, status-tinted bg, unicode symbol) + trend indicator (▲▼→) top-right
    Value: 32px, 800 weight, status color
    Progress bar for % KPIs (height:4px)
    Label: 11px muted uppercase
    Sub: comparison text (e.g., "Target: 99.25%") in 11px muted
  KPIs: PAF Primary (%), PAF Secondary (%), ICU Open, Bad Actor Open, Inspection Overdue, PM Compliance (%), WO Stagnant, Maintenance Spend Absorption (%)

[5] CHARTS ROW (3-column, gap:16px)
  Col 1 — "PAF & PM Compliance" — two donut gauges (CHART B) side by side in one card:
    Left donut: PAF % dari ## 2/## 6. Right donut: PM Compliance % dari ## 5.
  Col 2 — "Maintenance Spend Absorption" — one large donut gauge (CHART B) centered in card + Plan vs Actual numbers below.
  Col 3 — "ICU Open & Bad Actor" — horizontal bar chart (CHART A) showing ICU Open vs Bad Actor vs Inspection Overdue counts for this RU (bars colored by severity threshold).

[6] TWO-COLUMN ANALYSIS: Leading vs Lagging (side by side, each full card)
  Left — "Leading Indicators" (border-top:3px solid #ca8a04):
    Extract from ## 5. Render each concern as a row card (surface2, border-radius:8px, padding:10px 14px, margin-bottom:8px):
      - Indicator name bold + status badge right-aligned
      - Detail text muted 12px
      - If number present: render inline pill
  Right — "Lagging Indicators" (border-top:3px solid #dc2626):
    Extract from ## 6. Same row card style.

[7] ANALYSIS SECTIONS GRID (2-column, gap:14px)
  Sections ## 2, ## 3, ## 4, ## 7, ## 8, ## 10, ## 12
  Section ## 9 (Risk Hotspots) → full width, span 2
  Section ## 11 (Management) → full width, span 2
  Each card: circle number badge + title + status badge in header; bullet rows in body

[8] EQUIPMENT RISK TABLE (full-width, surface)
  Title: "Equipment & Asset Kritis — Memerlukan Perhatian Segera"
  Extract all equipment/tags from ## 3, ## 6, ## 8, ## 9
  Columns: No | Tag / Equipment | Unit / Lokasi | Isu Utama | Status | Target Penyelesaian | Rekomendasi
  RED rows → bg #fee2e2, left-border:3px solid #dc2626
  YELLOW rows → bg #fef9c3, left-border:3px solid #ca8a04
  Max 12 rows.

[9] MAINTENANCE SPEND PANEL (full-width, 3-column inner grid)
  Col 1: Plan vs Actual spend — two large numbers + delta indicator
  Col 2: Absorption rate donut gauge (CHART B, large, 140px)
  Col 3: Spend effectiveness — 3 bullet points

[10] MANAGEMENT ACTIONS TABLE (full-width)
  Columns: # | Isu | Risiko | Aksi yang Direkomendasikan | Owner | Timeframe
  Critical rows → red left-border + #fee2e2 bg; medium → yellow left-border
  th: color #0d9488, bg #f8fafc

[11] FOOTER
  bg #ffffff; border-top:2px solid #e2e8f0; padding:14px 32px; display:flex; justify-content:space-between
  Left: "Data Quality & Limitation" from ## 12 (max 2 lines, muted 11px)
  Right: confidence badge + "Generated by Reliability Performance & Risk Agent"

━━━ MICRO-DETAILS ━━━
- Bullet rows: display:flex;align-items:flex-start;gap:8px;margin-bottom:7px
- Colored dot: width:6px;height:6px;border-radius:50%;flex-shrink:0;margin-top:7px
- Red dot: #dc2626 | Yellow: #ca8a04 | Green: #16a34a | Muted: #94a3b8
- Tables: border-collapse:collapse;width:100%;font-size:12px; th padding:10px 14px; td padding:9px 14px
- Inline number pills: font-size:11px;font-variant-numeric:tabular-nums;background:#f1f5f9;color:#0f172a;padding:1px 7px;border-radius:4px;font-weight:700;border:1px solid #e2e8f0
- Strong critical values: color:#dc2626;font-weight:700
- Strong warning values: color:#ca8a04;font-weight:700
- Strong good values: color:#16a34a;font-weight:700
- Section labels: font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#64748b;margin-bottom:12px;padding-left:10px;border-left:3px solid #0d9488
- Chart card min-height:180px; overflow:hidden
- @media(max-width:900px): KPI grid→repeat(4,1fr); charts row→repeat(2,1fr); hero right→below
- @media(max-width:600px): all grids→1fr

BAHASA KONTEN: Indonesia.
Output HANYA kode HTML. Mulai langsung dengan <!DOCTYPE html>."""


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

RU_NAMES = [
    "RU II Dumai",
    "RU III Plaju",
    "RU IV Cilacap",
    "RU V Balikpapan",
    "RU VI Balongan",
    "RU VII Kasim",
]


def run_reliability_agent(mode: str = "weekly", ru: str = None) -> dict:
    """
    Jalankan Reliability Performance & Risk Agent.

    Args:
        mode: 'weekly' atau 'monthly'
        ru:   Nama RU (misal 'RU II Dumai') atau None untuk overall

    Returns:
        dict dengan keys: content, dashboard_html, mode, ru, status
    """
    if mode not in ("weekly", "monthly"):
        raise ValueError(f"mode harus 'weekly' atau 'monthly', bukan '{mode}'")
    if ru and ru not in RU_NAMES:
        raise ValueError(f"ru tidak dikenal: '{ru}'")

    # 1. Ambil semua data dari DB
    try:
        data = get_reliability_data()
    except Exception as e:
        raise RuntimeError(f"Gagal mengambil data dari database: {e}")

    # 2. Build konteks (filter per RU jika ada)
    try:
        context = _build_context(data, ru=ru)
    except Exception as e:
        raise RuntimeError(f"Gagal membangun konteks: {e}")

    # 3. Pilih system prompt
    suffix = _WEEKLY_SUFFIX if mode == "weekly" else _MONTHLY_SUFFIX
    system = _BASE_SYSTEM + suffix
    if ru:
        system += f"\n\nFOKUS ANALISIS: Hanya analisis {ru}. Semua section tetap diisi namun terfokus pada data {ru}."

    # 4. Build user message
    label = "Weekly Performance Review" if mode == "weekly" else "Monthly Reliability Health Review"
    scope_label = f"{ru} — " if ru else ""
    user_msg = (
        f"Berikut adalah data reliability kilang yang perlu dianalisis:\n\n"
        f"{context}\n\n"
        f"Berikan analisis reliability lengkap sesuai format yang ditentukan.\n"
        f"Mode: {scope_label}{label}"
    )

    # 5. Call LLM — analisis
    response = llm.invoke([
        {"role": "system", "content": system},
        {"role": "user",   "content": user_msg},
    ])
    analysis_content = response.content

    # 6. Call LLM — generate HTML dashboard dari hasil analisis
    label = "Weekly" if mode == "weekly" else "Monthly"
    dash_system = _DASHBOARD_SYSTEM_PER_RU if ru else _DASHBOARD_SYSTEM_OVERALL
    scope_label = f"{ru} — " if ru else ""
    dashboard_user_msg = (
        f"Buat HTML dashboard dari hasil analisis reliability {scope_label}{label} berikut:\n\n"
        f"{analysis_content}"
    )
    try:
        dashboard_response = llm_dashboard.invoke([
            {"role": "system", "content": dash_system},
            {"role": "user",   "content": dashboard_user_msg},
        ])
        dashboard_html = _extract_html(dashboard_response.content)
    except Exception:
        dashboard_html = ""

    return {
        "content":        analysis_content,
        "dashboard_html": dashboard_html,
        "mode":           mode,
        "ru":             ru,
        "status":         "success",
    }