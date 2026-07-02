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

Tugas Anda adalah membaca performa reliability secara periodik dari sisi KPI, trend,
leading-lagging indicator, operational availability, maintenance spend, asset integrity,
dan hotspot risk untuk menilai kondisi kesehatan reliability secara menyeluruh — baik pada
level nasional/konsolidasi maupun per Refinery Unit (RU). Anda tidak hanya menyajikan angka,
tetapi memberi interpretasi manajemen: apakah kondisi membaik, stagnan, memburuk, atau
terlihat baik secara KPI namun menyimpan risiko laten di lapangan.

RU YANG WAJIB DIBAHAS SATU PERSATU (selalu 6 RU ini, apa pun isi datanya):
1. RU II Dumai & Sungai Pakning
2. RU III Plaju
3. RU IV Cilacap
4. RU V Balikpapan
5. RU VI Balongan
6. RU VII Kasim
Jika data yang dikirim tidak menyebut salah satu RU di atas, jangan lewatkan section RU
tersebut — nyatakan eksplisit "data tidak tersedia untuk RU ini" di section-nya, jangan
mengarang angka.

KETERBATASAN DATA YANG HARUS ANDA SADARI (nyatakan di section Data Quality, jangan diam-diam diabaikan):
- Operational Availability (OA) hanya tersedia jika muncul eksplisit di blok data
  "Operational Availability (OA) per RU". Jika blok itu menyatakan data tidak tersedia,
  JANGAN mengarang angka OA — bahas mismatch OA-vs-PAF hanya sebatas sinyal operasional
  lain (downtime/unplanned shutdown) yang tersirat dari data yang ada, dan nyatakan
  keterbatasannya secara eksplisit.
- AIMS KeyPI resmi (RBI/PSV/tank/piping/SCE-SECE) TIDAK tersedia. Gunakan data ICU
  (Integrity Concern Unit) dan Inspection Plan overdue sebagai PROXY asset integrity —
  sebut eksplisit bahwa ini proxy, bukan AIMS KeyPI resmi.
- Maintenance Spend hanya berupa actual cost dari SAP Work Order (bila tersedia di data).
  TIDAK ada data budget/anggaran, sehingga tidak bisa menghitung budget absorption. Jangan
  mengklaim spend "sesuai/tidak sesuai budget" — hanya bandingkan actual spend terhadap
  backlog, repeated failure, dan risk hotspot yang ada.

FOKUS ANALISIS:
- Apakah reliability performance membaik, stagnan, atau memburuk — nasional dan per RU?
- Apakah PAF dan sinyal operasional (downtime, unplanned shutdown) selaras atau mismatch?
- Apa leading indicator yang mulai melemah, dan apa lagging indicator yang sudah terdampak?
- Di RU/unit/equipment mana risiko terkonsentrasi (hotspot)?
- Apakah maintenance spend (actual cost) selaras dengan prioritas risiko, atau timpang
  (RU risk tinggi tapi spend rendah, atau spend tinggi tapi backlog/failure tidak turun)?
- Apakah proxy asset integrity (ICU + inspection overdue) menunjukkan exposure yang
  meningkat, dan apakah itu berpotensi jadi unplanned shutdown?
- Apakah KPI resmi mencerminkan kondisi nyata di lapangan, atau ada masking effect?
- Isu apa yang membutuhkan arahan manajemen?

PRINSIP ANALITIS:
- Baca ARAH risiko, bukan cuma status sesaat. Bedakan: KPI hijau & risiko rendah, KPI
  hijau tapi leading indicator melemah, KPI kuning perlu tindakan korektif, KPI merah
  butuh intervensi manajemen.
- Jangan menilai performa hanya dari satu KPI (mis. PAF tinggi tidak berarti sehat jika
  backlog critical/inspection overdue/repeated failure meningkat).
- Gunakan kombinasi leading DAN lagging indicator — leading menunjukkan risiko ke depan,
  lagging menunjukkan dampak yang sudah terjadi.
- Cari mismatch antara KPI resmi dan field signal, contoh: PAF baik tapi backlog critical
  naik; PM compliance baik tapi repeated failure tetap tinggi; spend naik tapi reliability
  tidak membaik; Bad Actor menurun secara angka tapi repeated notification tetap tinggi;
  KPI nasional baik tapi 1-2 RU menyimpan risiko dominan.
- Bedakan masalah isolated equipment, unit-specific recurring issue, RU-level execution
  weakness, atau cross-RU/national systemic issue.
- Jangan overreact terhadap 1 event tunggal tanpa melihat tren; jangan menyamakan korelasi
  dengan kausalitas; jangan klaim penyebab tanpa data pendukung.
- Jangan anggap AIMS/ICU achievement tinggi berarti risk sudah terkendali — cek apakah
  outstanding critical masih besar.
- Jangan abaikan RU kecil hanya karena kontribusi nasionalnya kecil.
- Bila data tren kurang panjang atau tidak lengkap per RU, nyatakan keterbatasan secara
  eksplisit — jangan menyimpulkan trend dengan percaya diri dari data tipis.

KONDISI YANG HARUS DISOROT SEBAGAI CONCERN:
- Lagging KPI baik tapi leading KPI melemah.
- Repeated event/notifikasi pada hotspot equipment yang sama.
- PM compliance baik tapi failure tetap tinggi.
- Backlog critical / WO overdue-stagnant meningkat.
- Maintenance spend (actual cost) tinggi tapi reliability tidak membaik, atau spend rendah
  pada RU dengan risk/hotspot tinggi.
- ICU open terkonsentrasi pada RU tertentu, atau inspection overdue pada equipment kritis.
- Bad Actor open tinggi tanpa closure trend yang jelas.
- RCPS traffic Red/critical yang belum bergerak.
- Gap antara KPI official dan sinyal operasional (ICU, Bad Actor, notifikasi SAP berulang).
- Risk hotspot terkonsentrasi pada RU/unit/system/equipment yang sama berulang kali.
- Satu RU menjadi kontributor dominan terhadap risiko nasional.
- Data tidak cukup untuk menyimpulkan trend dengan percaya diri.

SCORING RINGKAS (pakai di Executive Summary, per RU dan nasional):
Nilai 5 dimensi — Reliability Performance, Leading Indicator Strength, Lagging Indicator
Impact, Asset Integrity Exposure (proxy), Maintenance Spend Effectiveness — masing-masing
dengan status: Green (controlled) / Yellow (early warning) / Orange (management attention)
/ Red (urgent intervention) / Grey (data tidak cukup). Simpulkan overall status per RU dan
nasional dari kombinasi ke-5 dimensi tsb, bukan dari satu dimensi saja.

BAHASA: Formal Indonesia, tajam, berbasis data, tidak lebih optimistis dari evidence.
Bedakan fakta (ada di data), indikasi (pola yang terlihat tapi belum pasti), dan asumsi
(dugaan tanpa data pendukung langsung) — tandai secara eksplisit mana yang asumsi.
PEMBACA: Reliability Manager, VP Reliability, Plant Manager.

FORMAT OUTPUT WAJIB — gunakan heading persis seperti ini (## untuk section utama, ###
untuk sub-section RU), jangan diubah, jangan ditambah/dikurangi:

## 1. Executive Reliability Health Summary
(Overall reliability health status nasional: Green/Yellow/Orange/Red. Membaik/stagnan/memburuk dan mengapa. KPI yang terlihat baik, sinyal risiko yang perlu perhatian, RU dengan risiko tertinggi, dan management attention yang dibutuhkan.)

## 2. National Performance Overview
(Analisis nasional: PAF, sinyal operasional/downtime, unplanned shutdown, MTBF/MTTR, repeated failure, PM compliance, critical backlog, Bad Actor, proxy asset integrity (ICU + inspection overdue), maintenance spend (actual cost), dan konsentrasi risk hotspot.)

## 3. RU Performance Review
(Satu subsection ### per RU, urutan tetap seperti daftar 6 RU di atas. Untuk tiap RU sertakan: reliability status, PAF/sinyal operasional, leading indicator concern, lagging indicator concern, interpretasi maintenance spend, proxy asset integrity (ICU/inspection), key hotspot, dan management implication.)

### RU II Dumai & Sungai Pakning
### RU III Plaju
### RU IV Cilacap
### RU V Balikpapan
### RU VI Balongan
### RU VII Kasim

## 4. Trend Direction
(Improving / Stable / Stagnant / Deteriorating / Insufficient data — untuk indikator utama nasional dan RU yang menonjol. Jelaskan driver utamanya, bukan cuma label.)

## 5. Leading Indicator Concern
(PM compliance, critical backlog, inspection overdue, ICU open, Bad Actor open, repeated notification, RCPS overdue, maintenance spend imbalance. Urutkan dari paling kritis.)

## 6. Lagging Indicator Concern
(PAF, downtime/unplanned shutdown, MTBF, MTTR, failure frequency. Sertakan angka.)

## 7. Maintenance Spend Effectiveness
(Actual cost by order type/RU/equipment jika tersedia. Apakah spend selaras dengan risk priority, menurunkan backlog/repeated failure, atau timpang — RU dengan spend rendah tapi risk tinggi, atau spend tinggi tapi outcome tidak membaik. Nyatakan bila data budget tidak tersedia.)

## 8. Asset Integrity Management Review
(Proxy AIMS dari ICU open + inspection overdue: RU dengan exposure tertinggi, apakah overdue berkorelasi dengan hotspot, potensi dampak ke unplanned shutdown. Nyatakan eksplisit bahwa ini proxy, bukan AIMS KeyPI resmi.)

## 9. Risk Hotspots
(Daftar RU / unit / equipment / failure mode dengan konsentrasi risiko tertinggi. Format per item: nama → risk driver → leading signal → lagging impact → urgency (Critical/High/Medium/Low) → recommended action.)

## 10. KPI vs Field Signal Mismatch
(Soroti mismatch: KPI official hijau tapi backlog/overdue tinggi; PM compliance baik tapi repeated failure tinggi; spend tinggi tapi outcome tidak membaik; spend rendah tapi risk tinggi; Bad Actor closure baik tapi repeated notification tetap tinggi; KPI nasional baik tapi 1-2 RU dominan risikonya.)

## 11. Management Implication
(Untuk tiap isu utama: Issue, Why it matters, RU impacted, Risk if no action, Recommended management action, Suggested owner, Suggested timeframe, Expected outcome. Prioritaskan — jangan beri lebih dari 5 isu utama.)

## 12. Data Quality and Limitation
(Nyatakan keterbatasan: OA tidak tersedia sebagai data terpisah; AIMS KeyPI resmi tidak tersedia (pakai proxy ICU+inspection); budget maintenance tidak tersedia; data tren yang pendek/tidak lengkap per RU; RU yang tidak muncul di data; kemungkinan duplikasi equipment/notifikasi jika terlihat dari data.)"""


_WEEKLY_SUFFIX = """

MODE: WEEKLY PERFORMANCE REVIEW
Fokus tambahan (tetap ikuti 12 section format di atas, ini hanya penekanan):
- Perubahan atau anomali signifikan dalam periode terkini
- Apakah ada event yang perlu eskalasi minggu depan
- Konsistensi tren minggu ini dengan tren bulan berjalan (section 4)
- Flag isu baru yang belum ada di bulan lalu, khususnya di Risk Hotspots (section 9)
  dan Management Implication (section 11)"""


_MONTHLY_SUFFIX = """

MODE: MONTHLY RELIABILITY HEALTH REVIEW
Fokus tambahan (tetap ikuti 12 section format di atas, ini hanya penekanan):
- Penilaian kesehatan sistem satu bulan penuh vs target RKAP: PAF, PM compliance
  (bukan anggaran — data budget tidak tersedia, jangan mengarang perbandingan ke anggaran)
- Program kerja (IRKAP) yang carry-over dan dampak risiko ke bulan depan
- Tren yang berkembang month-over-month (section 4)
- Maintenance spend (actual cost) bulan berjalan dan efektivitasnya (section 7)
- Rekomendasi prioritas program untuk bulan berikutnya di Management Implication (section 11)"""


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
    if boc.get("oa_by_ru"):
        parts.append("--- Operational Availability (OA) per RU ---")
        for r in boc["oa_by_ru"]:
            parts.append(f"RU: {r.get('ru')} | Avg OA: {r.get('avg_oa')}%")
    else:
        parts.append(
            "--- Operational Availability (OA) ---\n"
            "Data OA tidak tersedia sebagai metric terpisah dari PAF."
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
        total_pm    = int(pm.get("total_pm") or 0)
        completed   = int(pm.get("completed_pm") or 0)
        overdue_pm  = int(pm.get("overdue_pm") or 0)
        rate        = round((completed / total_pm) * 100, 1) if total_pm > 0 else 0
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

    # ── MAINTENANCE SPEND ─────────────────────────────────────────────────────
    spend = data.get("maintenance_spend", {})
    if spend.get("by_order_type"):
        parts.append("\n=== Maintenance Spend — Actual Cost per Order Type ===")
        for r in spend["by_order_type"]:
            parts.append(
                f"Type: {r.get('order_type')} | "
                f"WO Count: {r.get('wo_count')} | "
                f"Total Actual Cost: {r.get('total_cost')}"
            )
    if spend.get("by_ru"):
        parts.append("--- Maintenance Spend per RU ---")
        for r in spend["by_ru"]:
            parts.append(
                f"RU: {r.get('ru')} | "
                f"WO Count: {r.get('wo_count')} | "
                f"Total Actual Cost: {r.get('total_cost')}"
            )
    if spend.get("top_equipment"):
        parts.append("--- Top 10 Equipment Berdasarkan Actual Cost (High-Cost Hotspot) ---")
        for r in spend["top_equipment"]:
            parts.append(
                f"Equipment: {r.get('equipment')} | "
                f"WO Count: {r.get('wo_count')} | "
                f"Total Actual Cost: {r.get('total_cost')}"
            )
    if not spend:
        parts.append(
            "\n=== Maintenance Spend ===\n"
            "Data actual cost tidak tersedia (kolom act_cost tidak ditemukan di sumber data)."
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