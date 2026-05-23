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

Agent membaca dari 12 sumber data:
- PAF, Issue PAF, Bad Actor, ICU, BOC (MTBF/MTTR)
- RCPS, RCPS Rekomendasi, IRKAP Program & Actual
- Critical Equipment, Inspection Plan
- SAP Notifications & Work Orders
- Laporan Bulanan (upload manual)
