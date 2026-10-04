# BIN Card Lookup (HTML + Python)

Single-page HTML UI served by **Flask**. BIN lookups run in Python (no Node.js required).

## Run locally

```powershell
cd C:\Users\motod\Downloads\here445
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:43123

## Push to GitHub

1. Create a new empty repo on GitHub.
2. In this folder:

```powershell
git init
git add .
git commit -m "Add HTML frontend and Python Flask app for BIN lookup"
git branch -M main
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

## Deploy on Railway

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**.
2. Select your repo. Railway detects Python from `requirements.txt`.
3. No custom start command needed — `Procfile` runs Gunicorn on `$PORT`.
4. After deploy, open the public URL Railway gives you.

### Railway settings (if needed)

| Setting | Value |
|--------|--------|
| Root directory | `.` (repo root) |
| Start command | (leave empty — uses Procfile) |

## Project layout

| Path | Purpose |
|------|---------|
| `app.py` | Flask server, `/api/lookup` streaming, `/api/combine` |
| `static/index.html` | Web UI |
| `bin_lookup/` | Card parsing, BIN API, HTML export |

Legacy Windows launcher files (`stock go threw…py`, `START HERE.txt`) still work for local Next.js setup if you add the old zip; **Railway and GitHub use the Flask app above.**
