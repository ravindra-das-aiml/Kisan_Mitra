# 🌾 Kisan Mitra

**AI-powered crop doctor, mandi price analytics and farmer–buyer marketplace — in 14 Indian languages.**

Kisan Mitra is a multilingual web application that helps farmers diagnose crop problems from a photo, track official mandi prices, plan farm activities and sell directly to buyers. AI features (crop-image analysis, Farm Assistant chatbot and marketplace assistant) are powered by the **Groq API**.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)
![MySQL](https://img.shields.io/badge/Database-MySQL-4479A1?logo=mysql&logoColor=white)
![AI](https://img.shields.io/badge/AI-Groq-F55036)
![Status](https://img.shields.io/badge/Status-Local%20development-orange)

---

## Table of contents

- [Features](#features)
- [Tech stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Feature guide](#feature-guide)
- [Frontend](#frontend)
- [Troubleshooting](#troubleshooting)
- [Security notes](#security-notes)
- [Disclaimers](#disclaimers)

---

## Features

| Area | What it does |
| --- | --- |
| **Crop Doctor** | Upload a JPG, PNG or WebP image (max 8 MB) and receive a cautious, structured assessment with symptoms, treatment and prevention tips. Reports are saved privately and exportable as PDF. |
| **Farm Assistant** | Streaming AI chatbot for crop questions, a farm calendar, and optional email reminders and weather-risk alerts. |
| **Mandi Prices & Analytics** | Daily official AGMARKNET prices by state, district and commodity, with trend and market-comparison charts and sortable tables. |
| **Marketplace** | Buyer and seller profiles, crop listings, quantity-based offers, counter-offers, negotiation messages and order history. |
| **Direct chat** | Private buyer–farmer chat per listing, real-time via WebSockets, with in-app and browser notifications. |
| **Weather** | Current conditions and 7-day forecast for the user's location. |
| **Role-based access** | Farmer, Buyer and Admin permissions enforced by the backend. |
| **Multilingual UI** | 14 languages with built-in dictionaries and optional LibreTranslate for dynamic text. |

## Tech stack

- **Backend:** Python 3.11+, FastAPI (Uvicorn), WebSockets
- **Database:** MySQL
- **AI:** Groq API (text and vision models)
- **Frontend:** HTML, CSS and vanilla JavaScript (no build step), Chart.js
- **Data & services:** data.gov.in / AGMARKNET, Open-Meteo (weather), OpenStreetMap Nominatim (location labels), optional SMTP and LibreTranslate

## Prerequisites

- Windows 10/11 and Python 3.11+
- MySQL Server running locally
- A Groq API key from the [Groq Console](https://console.groq.com/keys)
- A data.gov.in API key and resource ID (for live mandi prices)
- *Optional:* SMTP credentials for reminders and weather alerts
- Internet access for Groq, weather and mandi services

## Quick start

### 1. Configure secrets

Copy `.env.example` to `.env` and fill in your credentials. **Never commit or share `.env`.**

### 2. Create a virtual environment and install dependencies

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
```

### 3. Start the backend (terminal 1)

```powershell
.venv\Scripts\activate
python -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

Check `http://127.0.0.1:8000/health` — it should report `ai_provider: groq` and `ai: configured` once a valid key is set.

### 4. Start the frontend (terminal 2)

```powershell
.venv\Scripts\activate
python -m http.server 5500 --directory frontend
```

Open **`http://localhost:5500/landing.html`**, then register as a Farmer or Buyer and sign in. The email set as `ADMIN_EMAIL` receives the Admin role when it registers.

## Configuration

All settings live in the project-root `.env` file.

| Variable | Required | Description |
| --- | :---: | --- |
| `GROQ_API_KEY` | ✅ | Your Groq API key. |
| `GROQ_CHAT_MODEL` | ✅ | Text model for the chatbot and marketplace assistant (default `openai/gpt-oss-120b`). |
| `GROQ_VISION_MODEL` | ✅ | Image-capable model for Crop Doctor (default `qwen/qwen3.8-27b`). Must support image input and be available to your Groq account. |
| `DB_PASSWORD` | ✅ | Local MySQL password (also verify host, port and username). |
| `JWT_SECRET` | ✅ | Long random secret used to sign tokens. **Change the default.** |
| `DATA_GOV_API_KEY` | ✅ | data.gov.in API key for live mandi prices. |
| `DATA_GOV_RESOURCE_ID` | ✅ | Exact resource ID of the official OGD dataset (default `9ef84268-d588-465a-a308-a864a43d0070`; change only to a verified resource). |
| `ADMIN_EMAIL` | ✅ | Email that receives the Admin role on registration. Set it **before** creating that account. Admin is not selectable during public registration. |
| `CORS_ORIGINS` | – | Allowed frontend origins (`http://localhost:5500`, `http://127.0.0.1:5500`). |
| SMTP settings | – | Required only for email reminders and weather alerts. |
| `LIBRETRANSLATE_URL` | – | Self-hosted translation endpoint, e.g. `http://127.0.0.1:5000/translate`. |

## Feature guide

### AI features (Groq)

- **Crop disease detection** sends the image to the configured Groq vision model. The displayed confidence is an *uncalibrated AI assessment score*, not a scientific probability.
- **Farm Assistant** uses `GROQ_CHAT_MODEL` and streams its responses.
- **Marketplace assistant** gives advisory help only; it cannot place offers or change orders.
- The application has no Gemini or xAI dependency — only `GROQ_API_KEY` is needed for AI.

### Reports and privacy

Report details, images and PDF endpoints check the authenticated user's ID, so users only see their own reports. PDFs are generated on demand from the saved report.

### Weather

Current conditions and a 7-day forecast by latitude/longitude. Browser location permission is required; use `localhost` or HTTPS.

### Live mandi prices and analytics

The **Mandi Prices** page calls `GET /api/mandi/live`, which fetches daily published records from the Government of India's data.gov.in AGMARKNET resource, normalizes them and stores them in MySQL for historical analytics.

1. Create a data.gov.in account and generate an API key from the Open Government Data Platform.
2. Set `DATA_GOV_API_KEY` (and, if needed, `DATA_GOV_RESOURCE_ID`) in `.env`.
3. Restart FastAPI.
4. Open **Mandi Prices** and choose state, district and commodity.
5. Open **Mandi Analytics** and load a commodity — it refreshes the current official dataset before querying MySQL history.

**Complete state / district / commodity lists.** To populate the dropdowns with the exact values in your dataset, run once from the `frontend` folder (Node 18+):

```bash
DATA_GOV_API_KEY=your_key node tools/build-mandi-data.mjs
```

This writes `js/mandi-data.js`, which the dashboard picks up automatically. Without it, `js/mandi-fallback.js` supplies all states/UTs and about 140 commodities, and states without a district list show a text box for typing the district.

> **Data note:** AGMARKNET records are *daily published observations*, not tick-by-tick auction prices. A newly fetched record may carry an earlier arrival date if that is the latest the market has published. The dashboard shows source and refresh status, never labels stale records as live, and never generates mock prices.

### Buyer–farmer chat

- Buyers start a private conversation from an active listing with **Chat with farmer**; each conversation is unique per buyer and listing.
- Messages are stored in MySQL and delivered instantly over FastAPI WebSockets; lists also refresh every 20 seconds as a fallback.
- Unread notifications are stored in MySQL and marked read when the recipient opens the conversation.
- Choose **Enable browser alerts** on the Marketplace page to allow browser notifications. They appear only while the page is open — background push is not implemented.
- Chat tables are created automatically at startup and are also included in `backend/schema.sql` and `kisan_mitra_updated.sql` for manual setup.
- Run a **single** FastAPI process locally. For multi-worker production, add a shared pub/sub layer such as Redis; the current connection manager is in-process.

### Farm calendar and notifications

Reminders are checked while the backend process is running. Email delivery requires user consent and SMTP configuration.

### Translation

Built-in dictionaries translate common labels and cached translations are reused. For uncached dynamic text, configure an optional self-hosted LibreTranslate endpoint (`LIBRETRANSLATE_URL`). Without it, uncached text stays in its original language.

## Frontend

The frontend is static HTML/CSS/JS in `frontend/` — no build step.

```text
frontend/
├── landing.html            Public landing page (logout redirects here)
├── index.html              Crop Doctor dashboard
├── login.html / register.html
├── farm-tools.html         Farm Assistant, calendar, alert preferences
├── analytics.html          Mandi analytics
├── marketplace.html        Buyer & Seller portal and chat
├── reports.html / report.html
├── admin.html
├── header.html / footer.html
├── css/
│   ├── style.css           Single responsive stylesheet (dark default + light)
│   └── landing.css         Landing page styles
├── js/                     Page modules, i18n.js, components.js, ui.js
└── tools/build-mandi-data.mjs
```

**Design principles**

- **Responsive:** mobile-first layout with a collapsible menu, scrollable tables and touch-friendly controls.
- **Motion-free:** no animations, transitions or 3D effects anywhere in the UI.
- **Interactive:** show/hide password, drag-and-drop or paste a crop photo, sortable tables, live report search, character counters, `Ctrl/Cmd + Enter` to send chat messages, and a back-to-top button.
- **Themes:** dark by default, with a persistent light/dark toggle.
- **Session flow:** logging out clears the session and returns to the landing page.

## Troubleshooting

| Problem | Solution |
| --- | --- |
| **Groq 401 / invalid API key** | Create a key in the [Groq Console](https://console.groq.com/keys), set `GROQ_API_KEY` in the root `.env`, save and restart the backend. |
| **Groq model not found** | Verify `GROQ_CHAT_MODEL` and `GROQ_VISION_MODEL` against the models enabled for your account. Crop Doctor needs a vision-capable model. |
| **MySQL connection error** | Start MySQL and verify host, port, username and password in `.env`. |
| **Weather location denied** | Allow location in browser settings and reload; `localhost` or HTTPS is required. |
| **Mandi error / no data** | Check `DATA_GOV_API_KEY`, `DATA_GOV_RESOURCE_ID` and the dataset's field names. |
| **CORS error** | Serve the frontend from `http://localhost:5500` or `http://127.0.0.1:5500`, matching `CORS_ORIGINS`. |

## Security notes

This project is a **local development starter**, not a production deployment. Before any public release: use HTTPS and secure sessions, restrict CORS, add rate limiting, keep backups, store secrets in a secret manager, and replace the default `JWT_SECRET`.

## Disclaimers

- AI crop assessments can be wrong and are **not a laboratory diagnosis**. Confirm serious crop-health issues with a local agricultural extension officer.
- Mandi data reflects daily published records and may not match same-day market prices.
- The marketplace supports listings, offers and chat only; the assistant cannot accept offers or process payments.
