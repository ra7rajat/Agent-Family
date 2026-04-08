# Agent Family — Credentials & Setup Guide

> This document covers **every credential, API key, and configuration value** needed to run the full Agent Family stack. Follow the steps in order.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Google AI Studio API Key (LLM)](#2-google-ai-studio-api-key)
3. [Google Cloud Project Setup](#3-google-cloud-project-setup)
4. [Enable Required Google APIs](#4-enable-required-google-apis)
5. [OAuth 2.0 Web Client (Calendar + Tasks + Login)](#5-oauth-20-web-client)
6. [Token Encryption Key](#6-token-encryption-key)
7. [Create Your `.env` File](#7-create-your-env-file)
8. [Install Dependencies](#8-install-dependencies)
9. [Run the Stack](#9-run-the-stack)
10. [Environment Variable Reference](#10-environment-variable-reference)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

| Tool | Min Version | Install |
|------|-------------|---------|
| Python | 3.12 | [python.org](https://python.org) |
| Node.js | 18 | [nodejs.org](https://nodejs.org) |
| npm | 9 | Bundled with Node.js |
| Google account | — | [accounts.google.com](https://accounts.google.com) |

---

## 2. Google AI Studio API Key

This key lets the **Master Agent and sub-agents** call Gemini models.

### Steps

1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Click **Create API key**
3. Select **Create API key in new project** (or pick an existing project)
4. Copy the key (starts with `AIza...`)

### Add to `.env`

```env
GOOGLE_API_KEY=AIzaSy...your_key_here
```

> [!NOTE]
> **Alternative — Vertex AI**: If you're working with an enterprise GCP project, set `GOOGLE_GENAI_USE_VERTEXAI=true` instead and configure `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION`. Vertex AI uses Application Default Credentials (ADC) — no API key needed.

---

## 3. Google Cloud Project Setup

The OAuth2 flow and Google Calendar/Tasks APIs run through a GCP project.

### Steps

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown (top left) → **New Project**
3. Give it a name (e.g., `agent-family`) and click **Create**
4. Make sure this project is **selected** in the dropdown for all following steps

---

## 4. Enable Required Google APIs

You must enable three APIs in your GCP project.

### Steps

1. In GCP Console → go to **APIs & Services → Library**
2. Search for and **enable** each of the following:

| API Name | What it's used for |
|----------|-------------------|
| **Google Calendar API** | CalendarAgent reads and creates events |
| **Google Tasks API** | TaskAgent creates and manages tasks |
| **Google People API** *(optional)* | Fetches user display name/picture |

For each API:
- Click the API name in search results
- Click **Enable**

---

## 5. OAuth 2.0 Web Client

This is the most important credential. It enables the **"Sign in with Google"** web flow.

> [!IMPORTANT]
> You **must** create a **Web application** type client — not Desktop or Service Account. The web type is what sends a `refresh_token` and supports the browser redirect flow.

### Steps

1. Go to **APIs & Services → Credentials**
2. Click **+ Create Credentials → OAuth client ID**
3. If prompted, configure the **OAuth consent screen** first:
   - User type: **External**
   - App name: `Agent Family` (or anything)
   - User support email: your Gmail
   - Scopes → click **Add or Remove Scopes**, add:
     - `https://www.googleapis.com/auth/calendar.events`
     - `https://www.googleapis.com/auth/tasks`
     - `openid`
     - `email`
   - Test users → add your own Gmail address
   - Click **Save and Continue** through all steps
4. Back on **Create OAuth client ID**:
   - Application type: **Web application**
   - Name: `Agent Family Web`
   - **Authorized redirect URIs** → click **+ Add URI**:
     ```
     http://localhost:8000/auth/callback
     ```
   - Click **Create**
5. A dialog appears with your credentials — copy both values:
   - **Client ID** (ends in `.apps.googleusercontent.com`)
   - **Client Secret**

### Add to `.env`

```env
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret
```

> [!WARNING]
> Never commit these values to Git. They are in `.env` which should be listed in your `.gitignore`.

---

## 6. Token Encryption Key

The server encrypts all OAuth tokens in memory using **Fernet symmetric encryption**. You need to generate a unique key once.

### Generate the key

Run this command in your terminal (inside the project directory):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

You'll get a base64 string that looks like:

```
3Zmk9Qq6J9p8VbXj1y0NCfqR3H4Tz5V0Kg8bN2Wd3Ls=
```

### Add to `.env`

```env
TOKEN_ENCRYPTION_KEY=your_fernet_key_here
```

> [!CAUTION]
> **Store this key safely.** If you lose it or rotate it, all existing encrypted sessions are invalidated and every user will need to sign in again. Never share it or commit it to version control.

---

## 7. Create Your `.env` File

Copy the example file and fill in all values:

```bash
cp .env.example .env
```

Then open `.env` and fill in every placeholder. Here is the complete reference with all required and optional values:

```env
# ── LLM (required) ────────────────────────────────────────────────────────────
GOOGLE_API_KEY=AIzaSy...

# ── Agent models (optional — defaults shown) ──────────────────────────────────
MASTER_MODEL=gemini-2.0-flash-lite
SUB_AGENT_MODEL=gemini-2.0-flash-lite

# ── OAuth2 client (required for login + Google APIs) ──────────────────────────
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret

# ── Token storage encryption (required) ───────────────────────────────────────
TOKEN_ENCRYPTION_KEY=your_fernet_key_here

# ── Web OAuth2 session config (required) ──────────────────────────────────────
OAUTH_REDIRECT_URI=http://localhost:8000/auth/callback
SESSION_TTL_DAYS=7
FRONTEND_URL=http://localhost:3000

# ── Feature flags ─────────────────────────────────────────────────────────────
GOOGLE_SERVICES_ENABLED=true     # Set true to use real Google APIs
HITL_ENABLED=true                # Set true for human approval on writes

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL=INFO
```

> [!NOTE]
> Set `GOOGLE_SERVICES_ENABLED=false` while developing without real Google API access. The agents will still orchestrate and respond but won't make actual Calendar/Tasks API calls.

---

## 8. Install Dependencies

### Python backend

```bash
# From the project root
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

### Next.js frontend

```bash
cd web
npm install
```

---

## 9. Run the Stack

Open **two terminal windows**:

### Terminal 1 — FastAPI backend

```bash
# From the project root, with venv activated
source .venv/bin/activate
.venv/bin/uvicorn agent_family.server:app --reload --port 8000
```

You should see:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### Terminal 2 — Next.js frontend

```bash
cd web
npm run dev
```

You should see:
```
▲ Next.js 15.x
✓ Ready in 1.2s
○ http://localhost:3000
```

### Open your browser

Navigate to **[http://localhost:3000](http://localhost:3000)**

The agents will animate in and prompt you to **Connect Google Account**. Click the button and complete the Google sign-in flow.

---

## 10. Environment Variable Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_API_KEY` | ✅ | — | Google AI Studio key for Gemini LLM calls |
| `GOOGLE_GENAI_USE_VERTEXAI` | ☑️ Alt | `false` | Set `true` to use Vertex AI instead of API key |
| `GOOGLE_CLOUD_PROJECT` | ☑️ If Vertex | — | GCP project ID for Vertex AI |
| `GOOGLE_CLOUD_LOCATION` | ☑️ If Vertex | `us-central1` | Vertex AI region |
| `MASTER_MODEL` | ❌ | `gemini-2.0-flash-lite` | Gemini model for Master Agent |
| `SUB_AGENT_MODEL` | ❌ | `gemini-2.0-flash-lite` | Gemini model for sub-agents |
| `GOOGLE_CLIENT_ID` | ✅ | — | OAuth2 Web client ID from GCP Console |
| `GOOGLE_CLIENT_SECRET` | ✅ | — | OAuth2 Web client secret from GCP Console |
| `TOKEN_ENCRYPTION_KEY` | ✅ | — | Fernet base64 key for encrypting session tokens |
| `OAUTH_REDIRECT_URI` | ✅ | `http://localhost:8000/auth/callback` | Must match GCP Console redirect URI exactly |
| `SESSION_TTL_DAYS` | ❌ | `7` | How many days before a session expires |
| `FRONTEND_URL` | ❌ | `http://localhost:3000` | Where browser is redirected after login |
| `GOOGLE_SERVICES_ENABLED` | ❌ | `false` | Set `true` to make real Calendar/Tasks API calls |
| `HITL_ENABLED` | ❌ | `true` | Require human approval for write operations |
| `LOG_LEVEL` | ❌ | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`) |
| `CALENDAR_AGENT_URL` | ❌ | `http://localhost:8001` | URL if CalendarAgent runs as a remote service |
| `TASK_AGENT_URL` | ❌ | `http://localhost:8002` | URL if TaskAgent runs as a remote service |

---

## 11. Troubleshooting

### `redirect_uri_mismatch` error from Google

Your `OAUTH_REDIRECT_URI` in `.env` doesn't exactly match what's configured in GCP Console.

- Go to **GCP Console → APIs & Services → Credentials → your OAuth client**
- Under **Authorized redirect URIs**, verify `http://localhost:8000/auth/callback` is listed **exactly** (no trailing slash, correct port)

---

### `TOKEN_ENCRYPTION_KEY environment variable is required`

The `.env` file is not being loaded or the variable is missing.

```bash
# Verify it exists in your .env
grep TOKEN_ENCRYPTION_KEY .env

# Re-generate if needed
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

### `400 Bad Request` on OAuth callback

Usually means the authorization code was already used (codes are single-use). Try signing in again from a fresh `http://localhost:3000` visit.

---

### Agents respond but Google API calls fail

Check that `GOOGLE_SERVICES_ENABLED=true` in your `.env`. When it's `false`, Calendar and Tasks calls are intentionally disabled.

---

### `401 Not authenticated` on `POST /api/v1/chat`

Your session cookie is missing or expired. Sign in again at `http://localhost:3000`.

---

### Frontend shows blank page or hydration errors

```bash
cd web
npm run build    # Check for TypeScript errors
npm run dev      # Restart dev server
```

---

### Run tests

```bash
# Python backend tests
source .venv/bin/activate
pytest tests/ -v

# Frontend tests
cd web
npx jest --verbose
```
