# me-cli-sunset / WebUI-XL

![banner](bnr.png)

CLI + **Web UI** + **Telegram bot** untuk mengelola paket, kuota, pembelian, bookmark, decoy, dan monitoring akun MyXL.

Fork: [arifianilhamnrr/me-cli-sunset](https://github.com/arifianilhamnrr/me-cli-sunset) · Upstream: [purplemashu/me-cli-sunset](https://github.com/purplemashu/me-cli-sunset)

---

## Mode deploy

| Mode | Cocok untuk | Entry point |
|------|-------------|-------------|
| **Cloudflare Worker** | Production, tanpa VPS, multi-user | `worker/` → `*.workers.dev` atau custom domain |
| **Web UI (FastAPI)** | Self-host lokal / VPS | `python run-web.py` → port **8089** |
| **CLI** | Terminal / Termux | `python main.py` |

**Production (fork ini):** [https://webui-xl.arifianilhamnur.workers.dev](https://webui-xl.arifianilhamnur.workers.dev)

---

## Deploy ke Cloudflare Worker (disarankan)

### One-click deploy

Klik tombol di bawah → login Cloudflare → fork repo otomatis → D1 + R2 + secrets diisi lewat wizard → deploy.

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/arifianilhamnrr/me-cli-sunset/tree/main/worker)

> Tombol di atas mengarah ke folder `worker/`. Cloudflare akan clone repo, provision **D1** (`DB`) dan **R2** (`DATA`), lalu jalankan `npm run deploy` (termasuk migrasi D1).  
> Setelah deploy, isi **Worker secrets** (MyXL API) lewat dashboard atau CLI — lihat [Secrets](#secrets-worker).

### Deploy manual (step-by-step)

#### 1. Prasyarat

- Akun [Cloudflare](https://dash.cloudflare.com/) (Workers Free tier cukup untuk mulai)
- [Node.js 20+](https://nodejs.org/)
- Nilai API MyXL (dari [channel Telegram](https://t.me/alyxcli) / maintainer)

```bash
git clone https://github.com/arifianilhamnrr/me-cli-sunset.git
cd me-cli-sunset/worker
npm ci
```

#### 2. Login Wrangler

```bash
npx wrangler login
```

#### 3. Provision D1 & R2

```bash
# Production
npx wrangler d1 create webui-xl
npx wrangler r2 bucket create webui-xl-data

# Opsional — staging
npx wrangler d1 create webui-xl-staging
npx wrangler r2 bucket create webui-xl-staging-data
```

Salin `database_id` dari output ke `worker/wrangler.toml` di section `[env.production]` / `[env.staging]`.

#### 4. Migrasi schema D1

```bash
npm run db:migrations:apply:production
# atau staging:
npm run db:migrations:apply:staging
```

#### 5. Set secrets

Jangan commit rahasia. Salin template lokal:

```bash
cp .dev.vars.example .dev.vars   # untuk wrangler dev saja
```

Production / staging via Wrangler:

```bash
npx wrangler secret put SESSION_SECRET --env production
npx wrangler secret put STORAGE_ENCRYPTION_KEY --env production
npx wrangler secret put BASE_API_URL --env production
npx wrangler secret put BASE_CIAM_URL --env production
npx wrangler secret put BASIC_AUTH --env production
npx wrangler secret put UA --env production
npx wrangler secret put API_KEY --env production
npx wrangler secret put AES_KEY_ASCII --env production
npx wrangler secret put AX_FP_KEY --env production
npx wrangler secret put AX_FP --env production
npx wrangler secret put ENCRYPTED_FIELD_KEY --env production
npx wrangler secret put XDATA_KEY --env production
npx wrangler secret put AX_API_SIG_KEY --env production
npx wrangler secret put X_API_BASE_SECRET --env production

# Opsional — Telegram webhook
npx wrangler secret put TELEGRAM_BOT_TOKEN --env production
npx wrangler secret put TELEGRAM_WEBHOOK_SECRET --env production
```

Generate `SESSION_SECRET`:

```bash
openssl rand -hex 32
```

#### 6. Migrasi data dari VPS / FastAPI (opsional)

Kalau pindah dari install lama (`webui_data/`):

```bash
cd ..   # repo root
STORAGE_ENCRYPTION_KEY=<sama dengan secret Worker> \
  python3 scripts/migrate-to-d1-r2.py \
  --remote \
  --d1 webui-xl \
  --r2-bucket webui-xl-data \
  --write-manifest ./manifest-production.json

python3 scripts/verify-migration.py \
  --manifest ./manifest-production.json \
  --remote \
  --d1 webui-xl \
  --r2-bucket webui-xl-data
```

#### 7. Deploy

```bash
cd worker
npm run typecheck
npm test
npm run deploy:production
```

Smoke test:

```bash
curl -sS "https://<nama-worker>.<subdomain>.workers.dev/health"
```

#### 8. Custom domain (opsional)

Di Cloudflare Dashboard → Workers → `webui-xl` → **Triggers** → **Custom Domains**, atau uncomment `routes` di `wrangler.toml`.

Runbook lengkap: [docs/cutover-runbook.md](docs/cutover-runbook.md) · Checklist: [docs/cutover-checklist.md](docs/cutover-checklist.md)

### Deploy via GitHub Actions

1. Repo → **Settings** → **Secrets and variables** → **Actions**
2. Tambah `CLOUDFLARE_API_TOKEN` (permission: Workers Scripts Edit, D1, R2)
3. Tambah `CLOUDFLARE_ACCOUNT_ID`
4. **Actions** → **Deploy Worker** → **Run workflow** → pilih `staging` atau `production`

### Secrets (Worker)

| Secret | Wajib | Keterangan |
|--------|-------|------------|
| `SESSION_SECRET` | Ya | Cookie signing (`openssl rand -hex 32`) |
| `STORAGE_ENCRYPTION_KEY` | Ya | Enkripsi blob user di R2 |
| `BASE_API_URL`, `BASE_CIAM_URL`, `BASIC_AUTH`, `UA` | Ya | Endpoint & auth API |
| `API_KEY`, `ENCRYPTED_FIELD_KEY`, `AES_KEY_ASCII` | Ya | Enkripsi / signature |
| `XDATA_KEY`, `AX_API_SIG_KEY`, `X_API_BASE_SECRET` | Ya | Request signing |
| `AX_FP`, `AX_FP_KEY` | Ya | Device fingerprint |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | Tidak | Bot Telegram (webhook) |

### Reset password user (D1)

Akun yang dimigrasi dari hash PBKDF2 200k (VPS) perlu reset di Workers Free tier:

```bash
python3 scripts/reset-worker-password.py \
  --username admin \
  --password 'password-baru' \
  --remote \
  --wrangler-env production
```

---

## Fitur Web UI

- Login multi-user — data per user di D1 + R2 (Worker) atau `webui_data/` (FastAPI)
- Dashboard neumorphic, paket aktif, beli paket (pulsa / QRIS / decoy)
- Bookmark, hot deals, family plan, circle, store, notifikasi, transaksi
- Decoy (`/settings/decoy`), monitoring kuota + alert Telegram

**Telegram (ringkas):**

- `/link username password` — hubungkan chat ke user Web UI
- `/nomor` — pilih nomor MyXL aktif
- `/kuota` — info pelanggan + kuota & paket aktif
- Menu beli paket: hot / family code / option code / bookmark

---

## Setup lokal — FastAPI Web UI + CLI

### Persyaratan

- Python 3.10+ (disarankan 3.11–3.12)
- Git
- File `.env` dari `.env.template`

```bash
cp .env.template .env
# isi variabel API
```

| Variabel | Wajib | Keterangan |
|----------|-------|------------|
| `BASE_API_URL`, `BASE_CIAM_URL`, `BASIC_AUTH`, `UA` | Ya | Endpoint & auth |
| `API_KEY`, `ENCRYPTED_FIELD_KEY`, `AES_KEY_ASCII` | Ya | Enkripsi |
| `XDATA_KEY`, `AX_API_SIG_KEY`, `X_API_BASE_SECRET` | Ya | Signing |
| `AX_FP`, `AX_FP_KEY` | Ya | Fingerprint |
| `WEBUI_HOST`, `WEBUI_PORT` | Tidak | Default `127.0.0.1:8089` |

### Linux

```bash
git clone https://github.com/arifianilhamnrr/me-cli-sunset.git
cd me-cli-sunset
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.template .env && nano .env

python main.py          # CLI
python run-web.py       # Web UI → http://127.0.0.1:8089
```

### Windows (PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.template .env
notepad .env
python run-web.py
```

### Termux

```bash
pkg install git python python-pip -y
git clone https://github.com/arifianilhamnrr/me-cli-sunset.git
cd me-cli-sunset
pip install -r requirements.txt
cp .env.template .env
python main.py
```

---

## Struktur repo

```
me-cli-sunset/
├── main.py                 # CLI
├── run-web.py              # FastAPI Web UI
├── app/                    # Core client
├── webui/                  # FastAPI templates & bot
├── worker/                 # Cloudflare Worker (Hono + D1 + R2)
│   ├── wrangler.toml
│   ├── migrations/
│   └── src/
├── scripts/
│   ├── migrate-to-d1-r2.py
│   └── reset-worker-password.py
├── docs/
│   ├── cutover-runbook.md
│   └── DESIGN-cf-worker-migration.md
├── webui_data/             # Jangan commit — data lokal FastAPI
└── .env                    # Jangan commit
```

---

## Troubleshooting

| Masalah | Solusi |
|---------|--------|
| Login gagal setelah migrasi ke Worker | Reset password: `scripts/reset-worker-password.py` (Free tier tidak support verify PBKDF2 200k) |
| OTP / fingerprint error | Pastikan `AX_FP` secret benar; per-user `ax.fp` ada di R2 setelah migrasi |
| Kartu UI tidak kelihatan | Hard refresh (`Ctrl+Shift+R`); cek `/static/css/custom.css` ter-load |
| `ModuleNotFoundError` (CLI) | Aktifkan venv |
| Telegram tidak merespons (FastAPI) | Cek `webui_data/telegram.json`, restart `run-web.py` |
| Deploy button gagal | Pastikan repo **public**; folder `worker/` harus punya `package.json` + `wrangler.toml` sendiri |

---

## Git & kontribusi

```bash
./scripts/setup-my-github.sh "Nama" email@example.com github_username
./scripts/commit-my-changes.sh
git push -u origin main
```

---

## Disclaimer

Fork ini dikembangkan oleh [arifianilhamnrr](https://github.com/arifianilhamnrr) di atas upstream [purplemashu/me-cli-sunset](https://github.com/purplemashu/me-cli-sunset). Disclaimer dan kontak di bawah mengacu ke **upstream asli**, bukan maintainer fork ini.

**Upstream disclaimer:** By using this tool, you agree to comply with applicable laws and regulations and release the developer from claims arising from its use.

**Environment variables (upstream):** [OUR TELEGRAM CHANNEL](https://t.me/alyxcli)

**Kontak fork ini:** [arifianilhamnur@gmail.com](mailto:arifianilhamnur@gmail.com) · Telegram [@arnrdev](https://t.me/arnrdev)