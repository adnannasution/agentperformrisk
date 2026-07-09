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

llm_dashboard = ChatOpenAI(
    model="gpt-4o",
    api_key=DINOIKI_API_KEY,
    base_url="https://ai.dinoiki.com/v1",
    temperature=0.4,
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

LARANGAN FORMAT:
- JANGAN menyebut bulan, tahun, atau periode apa pun di judul, heading, atau teks (contoh: "April 2026", "Juni 2026", "Bulan ini", dsb.)
- Judul utama cukup: "# Monthly Reliability Health Review" tanpa tambahan bulan/tanggal

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
                f"Warna: {r.get('color')}"
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
                f"Plan/Unplan: {r.get('plan_unplan')}"
            )
    if paf.get("trend"):
        parts.append("--- Trend PAF Realisasi ---")
        for r in _filter_ru(paf["trend"], ru)[:12]:
            parts.append(
                f"RU: {r.get('ru_name') or r.get('ru')} | "
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
                f"Issue: {r.get('issue')}"
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
                f"Action: {r.get('action_plan')}"
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

    # ── READINESS JETTY ──────────────────────────────────────────────────────
    jetty = data.get("readiness_jetty", {})
    if jetty.get("summary_by_ru"):
        parts.append("\n=== Readiness Jetty — Summary per RU ===")
        for r in _filter_ru(jetty["summary_by_ru"], ru):
            parts.append(
                f"RU: {r.get('ru_name')} | "
                f"Total Jetty: {r.get('total')} | "
                f"Operasi OK: {r.get('operasi_ok')}"
            )
    if jetty.get("jetty_issues"):
        issues = _filter_ru(jetty["jetty_issues"], ru)
        parts.append(f"\n[STATS] Jetty dengan Komponen Not Good: {len(issues)}")
        parts.append("--- Jetty — Komponen Bermasalah (Not Good) ---")
        for r in issues[:15]:
            komponen_list = ", ".join(
                f"{k['komponen']} (RTL: {k['rtl'] or '-'})"
                for k in r.get("komponen_bermasalah", [])
            )
            parts.append(
                f"RU: {r.get('ru_name')} | Area: {r.get('area')} | "
                f"Unit: {r.get('unit')} | Equipment: {r.get('equipment')} | "
                f"Status Ops: {r.get('status_operation')} | "
                f"Not Good ({r.get('not_good_count')}): {komponen_list}"
            )
    if jetty.get("perizinan_issues"):
        piz = _filter_ru(jetty["perizinan_issues"], ru)
        parts.append(f"\n[STATS] Jetty dengan Perizinan Bermasalah: {len(piz)}")
        parts.append("--- Jetty — Perizinan Bermasalah ---")
        for r in piz[:10]:
            piz_list = ", ".join(
                f"{p['jenis']}: {p['status']} (Expired: {p['expired'] or '-'})"
                for p in r.get("perizinan", [])
            )
            parts.append(
                f"RU: {r.get('ru_name')} | Area: {r.get('area')} | "
                f"Unit: {r.get('unit')} | Equipment: {r.get('equipment')} | "
                f"Perizinan: {piz_list}"
            )

    # ── READINESS TANK ───────────────────────────────────────────────────────
    tank = data.get("readiness_tank", {})
    if tank.get("summary_by_ru"):
        parts.append("\n=== Readiness Tank — Summary per RU ===")
        for r in _filter_ru(tank["summary_by_ru"], ru):
            parts.append(
                f"RU: {r.get('ru_name')} | "
                f"Total Tank: {r.get('total')} | "
                f"Operasi OK: {r.get('operasi_ok')}"
            )
    if tank.get("tank_issues"):
        issues = _filter_ru(tank["tank_issues"], ru)
        parts.append(f"\n[STATS] Tank dengan Komponen Not Good: {len(issues)}")
        parts.append("--- Tank — Komponen Bermasalah (Not Good) ---")
        for r in issues[:15]:
            komponen_list = ", ".join(
                f"{k['komponen']} (RTL: {k['rtl'] or '-'})"
                for k in r.get("komponen_bermasalah", [])
            )
            parts.append(
                f"RU: {r.get('ru_name')} | Area: {r.get('area')} | "
                f"Tag: {r.get('tag_number')} | Equipment: {r.get('equipment')} | "
                f"Tipe: {r.get('type_tangki')} | Service: {r.get('service_tangki')} | "
                f"Prioritas: {r.get('prioritas')} | "
                f"Status Ops: {r.get('status_operational')} | "
                f"Not Good ({r.get('not_good_count')}): {komponen_list}"
            )
    if tank.get("sertifikasi_issues"):
        sert = _filter_ru(tank["sertifikasi_issues"], ru)
        parts.append(f"\n[STATS] Tank dengan Sertifikasi Bermasalah: {len(sert)}")
        parts.append("--- Tank — Sertifikasi Bermasalah (ATG/COI/TERA) ---")
        for r in sert[:10]:
            sert_list = ", ".join(
                f"{s['jenis']}: {s['status']} (Expired: {s['expired'] or '-'})"
                for s in r.get("sertifikasi", [])
            )
            parts.append(
                f"RU: {r.get('ru_name')} | Area: {r.get('area')} | "
                f"Tag: {r.get('tag_number')} | Equipment: {r.get('equipment')} | "
                f"Prioritas: {r.get('prioritas')} | Sertifikasi: {sert_list}"
            )

    # ── READINESS SPM ────────────────────────────────────────────────────────
    spm = data.get("readiness_spm", {})
    if spm.get("summary_by_ru"):
        parts.append("\n=== Readiness SPM — Summary per RU ===")
        for r in _filter_ru(spm["summary_by_ru"], ru):
            parts.append(
                f"RU: {r.get('ru_name')} | "
                f"Total SPM: {r.get('total')} | "
                f"Operasi OK: {r.get('operasi_ok')}"
            )
    if spm.get("spm_issues"):
        issues = _filter_ru(spm["spm_issues"], ru)
        parts.append(f"\n[STATS] SPM dengan Komponen Not Good: {len(issues)}")
        parts.append("--- SPM — Komponen Bermasalah (Not Good) ---")
        for r in issues[:15]:
            komponen_list = ", ".join(
                f"{k['komponen']} (RTL: {k['rtl'] or '-'})"
                for k in r.get("komponen_bermasalah", [])
            )
            parts.append(
                f"RU: {r.get('ru_name')} | Area: {r.get('area')} | "
                f"Tag: {r.get('tag_no')} | Equipment: {r.get('equipment')} | "
                f"Status Ops: {r.get('status_operation')} | "
                f"Not Good ({r.get('not_good_count')}): {komponen_list}"
            )
    if spm.get("perizinan_issues"):
        piz = _filter_ru(spm["perizinan_issues"], ru)
        parts.append(f"\n[STATS] SPM dengan Perizinan Bermasalah: {len(piz)}")
        parts.append("--- SPM — Perizinan Bermasalah ---")
        for r in piz[:10]:
            piz_list = ", ".join(
                f"{p['jenis']}: {p['status']} (Expired: {p['expired'] or '-'})"
                for p in r.get("perizinan", [])
            )
            parts.append(
                f"RU: {r.get('ru_name')} | Area: {r.get('area')} | "
                f"Tag: {r.get('tag_no')} | Equipment: {r.get('equipment')} | "
                f"Perizinan: {piz_list}"
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

# Kerangka HTML + CSS disediakan aplikasi (TIDAK digenerate LLM) agar output LLM
# kecil dan tidak pernah terpotong. LLM hanya mengisi bagian dalam <body>.
_DIR = os.path.dirname(__file__)


def _load(name: str) -> str:
    try:
        with open(os.path.join(_DIR, name), "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


_SHELL_HEAD    = _load("dashboard_shell_head.html")     # <!DOCTYPE>..<style>..</style></head><body>
_SHELL_TAIL    = _load("dashboard_shell_tail.html")     # </body></html>
_BODY_EXAMPLE  = _load("dashboard_body_example.html")   # contoh isi body (pakai class yang tersedia)


_DASHBOARD_INSTRUCTION = """Kamu adalah front-end engineer yang mengisi konten infografis reliability kilang Pertamina.

CSS dan kerangka halaman SUDAH disediakan sistem — kamu TIDAK perlu menulis <style>, <head>, atau <html>.
Tugasmu: hasilkan HANYA isi bagian dalam <body> (potongan HTML) memakai class CSS yang sudah ada.

Di bawah ada CONTOH ISI BODY sebagai standar struktur & class yang WAJIB kamu ikuti. Tugasmu:
1. Hasilkan isi body BARU dengan struktur, class, layout, dan komponen PERSIS SAMA seperti contoh.
2. GANTI semua data (nama RU/scope, angka KPI, status, risk signals, spend, hotspot, trend, management action, data quality, footer) dengan nilai NYATA dari hasil analisis.
3. Pakai HANYA class yang muncul di contoh (.header, .kpi-card, .risk-row, .trend-item, .spend-row, .hotspot-table, .mgmt-table, .badge, dll). Jangan buat CSS baru.
4. Sesuaikan jumlah baris tabel/bar dengan data. Jika data tidak ada, tulis "N/A" atau hilangkan barisnya — jangan mengarang angka.
5. Mode OVERALL/Nasional: judul header jadi nama scope nasional (mis. "Reliability Health Review — Nasional") + tampilkan breakdown per RU bila relevan. Mode per-RU: pakai nama RU tersebut.

ATURAN OUTPUT: Kembalikan HANYA potongan HTML isi body (mulai dari <header ...> sampai elemen terakhir seperti <footer>). TANPA <!DOCTYPE>, TANPA <html>, TANPA <head>, TANPA <style>, TANPA <body>. Tanpa markdown fence. Tanpa penjelasan. Semua teks Bahasa Indonesia.

═══════════ CONTOH ISI BODY (TIRU STRUKTUR & CLASS INI) ═══════════
""" + _BODY_EXAMPLE + """
═══════════ AKHIR CONTOH ═══════════

Sekarang buat isi body BARU dengan struktur/class identik, berisi data dari analisis di bawah ini."""

_DASHBOARD_SYSTEM_OVERALL = _DASHBOARD_INSTRUCTION
_DASHBOARD_SYSTEM_PER_RU  = _DASHBOARD_INSTRUCTION


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


def _assemble_dashboard(body_html: str) -> str:
    """Gabungkan isi body dari LLM dengan kerangka + CSS aplikasi menjadi HTML lengkap."""
    body = body_html.strip()
    # Buang tag dokumen jika LLM terlanjur menuliskannya
    low = body.lower()
    if "<body" in low:
        body = body[low.index("<body"):]
        body = body[body.index(">") + 1:]
        low = body.lower()
    if "</body>" in low:
        body = body[:low.index("</body>")]
    return _SHELL_HEAD + "\n" + body.strip() + "\n" + _SHELL_TAIL


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
    # Batasi panjang analisis agar tidak melebihi batas token LLM dashboard
    analysis_for_dash = analysis_content[:9000] if len(analysis_content) > 9000 else analysis_content
    print(f"[Dashboard LLM] sending analysis length={len(analysis_for_dash)} chars")
    scope_desc = f"Refinery Unit: {ru}" if ru else "Scope: Nasional / Seluruh RU (Overall)"
    dashboard_user_msg = (
        f"Buat isi body infografis ({scope_label}{label}) dengan struktur/class IDENTIK seperti contoh, "
        f"berisi data dari analisis reliability berikut.\n"
        f"{scope_desc}\n"
        f"PENTING: Jangan tampilkan bulan atau periode apa pun pada judul, header, maupun label.\n\n"
        f"=== HASIL ANALISIS ===\n{analysis_for_dash}"
    )
    dashboard_error = ""
    try:
        dashboard_response = llm_dashboard.invoke([
            {"role": "system", "content": dash_system},
            {"role": "user",   "content": dashboard_user_msg},
        ])
        raw_content = dashboard_response.content or ""
        finish = getattr(dashboard_response, "response_metadata", {}) or {}
        finish_reason = finish.get("finish_reason") or finish.get("stop_reason") or "?"
        body_html = _extract_html(raw_content)
        print(f"[Dashboard LLM] body length={len(body_html)}, finish_reason={finish_reason}, preview={raw_content[:150]!r}")
        if len(body_html) < 80:
            dashboard_html = ""
            dashboard_error = f"Isi body terlalu pendek ({len(body_html)} chars). Preview: {raw_content[:200]!r}"
        else:
            # Gabungkan body dari LLM dengan kerangka + CSS aplikasi → HTML lengkap terjamin
            dashboard_html = _assemble_dashboard(body_html)
            if finish_reason == "length":
                # body mungkin terpotong; tetap ditampilkan tapi beri catatan
                dashboard_error = "Catatan: konten mungkin terpotong (finish_reason=length). Pertimbangkan jalankan ulang."
            print(f"[Dashboard LLM] assembled full HTML length={len(dashboard_html)}")
    except Exception as e:
        print(f"[Dashboard LLM Error] {e}")
        dashboard_html = ""
        dashboard_error = str(e)

    return {
        "content":        analysis_content,
        "dashboard_error": dashboard_error,
        "dashboard_html": dashboard_html,
        "mode":           mode,
        "ru":             ru,
        "status":         "success",
    }