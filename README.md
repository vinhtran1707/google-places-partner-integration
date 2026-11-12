# Google Places API — Partner Integration Client

A production-style integration client demonstrating the full API onboarding lifecycle a Solutions Engineer owns when connecting a partner to Google's Places API (New). Built as a portfolio project targeting SE and data engineering roles.

## What This Demonstrates

- **API authentication** via header-based API key (Places API New requirement — not URL param)
- **Multi-endpoint orchestration** across Text Search and Place Details in a single workflow
- **Exponential backoff with retry logic** on rate limit and server errors
- **Structured error classification** mapping HTTP status codes and API-level errors to actionable error classes (`AUTH_FAILURE`, `RATE_LIMIT`, `SERVER_ERROR`, etc.)
- **SQLite persistence** for integration health monitoring — every API call is logged with endpoint, latency, status, and error class
- **Health reporting** — aggregated call stats, average latency per endpoint, and recent error log printed at the end of every run

## Endpoints Covered

| Endpoint | Method | Equivalent Yelp Endpoint |
|---|---|---|
| `places:searchText` | POST | `/businesses/search` |
| `places/{place_id}` | GET | `/businesses/{id}` |
| `places:searchText` (named lookup) | POST | `/businesses/search/phone` |

## Sample Output

```
2026-11-11 23:40:33 [INFO] Starting partner API integration demo
2026-11-11 23:40:33 [INFO] Searching for 'seafood restaurants' near New Orleans, LA
2026-11-11 23:40:35 [INFO] [OK] places:searchText — 1151.16ms
2026-11-11 23:40:35 [INFO] Found 10 results for 'seafood restaurants'

Top result: Blue Bayou Restaurant & Oyster Bar — Rating: 4.6 (5767 reviews)
Address: 717 Canal St, New Orleans, LA 70130, USA
Phone: (504) 291-3788
Website: http://bluebayourestaurantnola.com/
Top review: "Damon is a sweetheart and a true southern hospitality waiter..."

Found 10 cocktail bars in New Orleans
Business lookup result: Dooky Chase Restaurant

============================================================
INTEGRATION HEALTH REPORT
============================================================
Endpoint                   Calls  Avg Latency  Errors
-------------------------------------------------------
places                         1      603.9ms       0
places:searchText              3      924.8ms       0

Places stored in DB: 21
============================================================
```

## Setup

**Requirements:** Python 3.8+, `requests` library

```bash
pip install requests
```

**Configuration:** Set your API key as an environment variable — never hardcode it in source files.

```bash
# Windows
set PLACES_API_KEY=your_key_here

# Mac/Linux
export PLACES_API_KEY=your_key_here
```

You'll need a Google Cloud project with **Places API (New)** enabled. Create a key at [console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials).

**Run:**

```bash
python client.py
```

## Project Structure

```
├── client.py             # Main integration client
├── integration.log       # Persistent log file (auto-created)
└── integration_health.db # SQLite health DB (auto-created, gitignored)
```

## Design Decisions

**Why POST for search?** The Places API (New) uses POST with a JSON body for search endpoints, unlike the legacy API which used GET with query params. This matches modern API design patterns and allows richer request payloads.

**Why SQLite for health monitoring?** Lightweight, zero-dependency persistence that mirrors what a real integration would log to a time-series database or observability platform. Useful for demoing latency trends and error rate tracking across runs.

**Why classify errors structurally?** Raw HTTP status codes aren't actionable for partners. Mapping them to named error classes (`AUTH_FAILURE`, `RATE_LIMIT`) is standard SE practice — it's what goes into runbooks and partner-facing error documentation.

## Author

Vinh Tran — [linkedin.com/in/vinh-tran1707](https://linkedin.com/in/vinh-tran1707) — [github.com/vinhtran1707](https://github.com/vinhtran1707)
