# Reliability Performance & Risk Agent

Agent AI untuk memantau dan menganalisis health reliability sistem kilang
berdasarkan KPI, trend, leading-lagging indicator, dan risk hotspot.

## Struktur Project

```
├── static/
│   └── reliability.html       # UI web
├── app.py                     # Flask app utama
├── db.py                      # Koneksi DB + migrasi
├── reliability_agent.py       # Logic agent + LLM
├── reliability_data.py        # Agregasi data dari DB
├── reliability_routes.py      # Flask blueprint / API routes
├── requirements.txt
├── Procfile                   # Untuk Railway/Heroku
└── .env.example
```

## Setup

1. Copy `.env.example` → `.env` dan isi nilai yang dibutuhkan
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Jalankan lokal:
   ```
   python app.py
   ```
4. Akses di: `http://localhost:5000/reliability`

## Deploy ke Railway

1. Push ke GitHub
2. Connect repo ke Railway
3. Set environment variables di Railway dashboard:
   - `DATABASE_URL`
   - `DINOIKI_API_KEY`
   - `SECRET_KEY`
4. Railway otomatis deploy via `Procfile`

## API Endpoints

| Method | Endpoint | Fungsi |
|--------|----------|--------|
| GET  | `/reliability` | Halaman UI |
| POST | `/reliability/upload-laporan` | Upload laporan bulanan .docx |
| POST | `/reliability/run` | Jalankan agent (`mode`: weekly/monthly) |
| GET  | `/reliability/history` | Riwayat output |
| GET  | `/reliability/history/<id>` | Detail output |
| GET  | `/health` | Health check |

## Sumber Data

Agent membaca dari 13 sumber data:
- PAF, Issue PAF, Bad Actor, ICU, BOC (MTBF/MTTR)
- RCPS, RCPS Rekomendasi, IRKAP Program & Actual
- Critical Equipment, Inspection Plan
- SAP Notifications & Work Orders
- Maintenance Spend — actual cost dari `sap_work_orders.act_cost` (bila kolomnya ada di DB;
  diintrospeksi otomatis via `information_schema`, tidak wajib)
- Laporan Bulanan (upload manual)

**Keterbatasan data saat ini** (dinyatakan eksplisit oleh agent di section "Data Quality and
Limitation" pada setiap output):
- **Operational Availability (OA) resmi** tidak tersedia, kecuali tabel `boc` punya kolom
  `oa` / `operational_availability` / `availability` (dicek otomatis). Sebagai fallback, agent
  menghitung **Estimated Availability** dari `boc.mtbf`, `boc.mttr`, `boc.running_hours`, dan
  `boc.frequency` (Inherent Availability = MTBF/(MTBF+MTTR)) — ini estimasi teknis, bukan OA
  resmi, dan biasanya lebih tinggi dari OA aktual karena tidak memperhitungkan planned
  shutdown/turnaround/logistic delay.
- **AIMS KeyPI resmi** (RBI/PSV/tank/piping/SCE-SECE) belum ada sumber datanya — agent memakai
  ICU + Inspection Plan overdue sebagai proxy asset integrity.
- **Budget/anggaran maintenance** belum ada sumber datanya, sehingga Maintenance Spend hanya
  membahas actual cost tanpa perbandingan ke budget.
