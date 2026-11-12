"""
Google Places API (New) - Partner Integration Client
Simulates the end-to-end API integration lifecycle a Solutions Engineer
manages when onboarding a partner onto a third-party places/discovery API.

Covers:
- API key authentication via header (Places API New requirement)
- Multi-endpoint calls (Text Search, Place Details)
- Rate limiting with exponential backoff
- Structured error classification and logging
- SQLite persistence for integration health monitoring
"""

import requests
import sqlite3
import logging
import time
import json
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────

API_KEY = "AIzaSyAE7x8_GkAv4jNAag6X9eqoqNc7z7IICCw"
BASE_URL = "https://places.googleapis.com/v1"
DB_PATH = Path(__file__).parent / "integration_health.db"

MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds

# ── Logging setup ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / "integration.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── Database setup ─────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_calls (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint    TEXT NOT NULL,
            status_code INTEGER,
            latency_ms  REAL,
            error_class TEXT,
            error_msg   TEXT,
            timestamp   TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS places (
            place_id    TEXT PRIMARY KEY,
            name        TEXT,
            address     TEXT,
            rating      REAL,
            user_ratings_total INTEGER,
            fetched_at  TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def log_call(endpoint, status_code, latency_ms, error_class=None, error_msg=None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO api_calls (endpoint, status_code, latency_ms, error_class, error_msg, timestamp) VALUES (?,?,?,?,?,?)",
        (endpoint, status_code, latency_ms, error_class, error_msg, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()

def save_place(place):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT OR REPLACE INTO places (place_id, name, address, rating, user_ratings_total, fetched_at)
           VALUES (?,?,?,?,?,?)""",
        (
            place.get("id") or place.get("place_id"),
            place.get("displayName", {}).get("text") if isinstance(place.get("displayName"), dict) else place.get("name"),
            place.get("formattedAddress") or place.get("formatted_address") or place.get("vicinity"),
            place.get("rating"),
            place.get("userRatingCount") or place.get("user_ratings_total"),
            datetime.now(timezone.utc).isoformat()
        )
    )
    conn.commit()
    conn.close()

# ── Error classification ───────────────────────────────────────────────────────

def classify_error(status_code, response_json):
    """
    Maps HTTP status codes and API-level error statuses to
    human-readable error classes. This is the core of an SE's
    partner integration debugging workflow.
    """
    if status_code == 200:
        return None, None
    if status_code == 400:
        msg = response_json.get("error", {}).get("message", "Bad request") if response_json else "Bad request"
        return "INVALID_REQUEST", msg
    if status_code == 401:
        return "AUTH_FAILURE", "API key missing or invalid"
    if status_code == 403:
        return "AUTH_FAILURE", "API key lacks permission — check API restrictions in Cloud Console"
    if status_code == 429:
        return "RATE_LIMIT", "HTTP 429 — too many requests, back off and retry"
    if status_code >= 500:
        return "SERVER_ERROR", f"Upstream server error ({status_code}) — retry with backoff"
    return "UNKNOWN", f"Unexpected status {status_code}"

# ── Core request handler with retry + backoff ──────────────────────────────────

def make_post_request(endpoint_path, payload, field_mask, retries=MAX_RETRIES):
    """
    Wraps every outbound API call with:
    - Exponential backoff on rate limit and server errors
    - Structured error classification
    - Latency and status logging to SQLite
    Places API (New) uses POST with JSON body and X-Goog-FieldMask header.
    """
    url = f"{BASE_URL}/{endpoint_path}"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": field_mask
    }

    for attempt in range(1, retries + 1):
        start = time.time()
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            latency = (time.time() - start) * 1000
            data = resp.json() if resp.content else {}
            error_class, error_msg = classify_error(resp.status_code, data)

            log_call(endpoint_path, resp.status_code, round(latency, 2), error_class, error_msg)

            if error_class in ("RATE_LIMIT", "SERVER_ERROR") and attempt < retries:
                wait = BACKOFF_BASE ** attempt
                log.warning(f"[{error_class}] Attempt {attempt}/{retries} — retrying in {wait}s")
                time.sleep(wait)
                continue

            if error_class:
                log.error(f"[{error_class}] {error_msg}")
                return None, error_class

            log.info(f"[OK] {endpoint_path} — {round(latency, 2)}ms")
            return data, None

        except requests.exceptions.Timeout:
            latency = (time.time() - start) * 1000
            log_call(endpoint_path, None, round(latency, 2), "TIMEOUT", "Request timed out after 10s")
            log.error(f"[TIMEOUT] {endpoint_path} timed out on attempt {attempt}")
            if attempt < retries:
                time.sleep(BACKOFF_BASE ** attempt)

        except requests.exceptions.ConnectionError as e:
            log_call(endpoint_path, None, 0, "CONNECTION_ERROR", str(e))
            log.error(f"[CONNECTION_ERROR] {e}")
            return None, "CONNECTION_ERROR"

    return None, "MAX_RETRIES_EXCEEDED"

def make_get_request(endpoint_path, field_mask, retries=MAX_RETRIES):
    """GET handler for Place Details endpoint."""
    url = f"{BASE_URL}/{endpoint_path}"
    headers = {
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": field_mask
    }

    for attempt in range(1, retries + 1):
        start = time.time()
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            latency = (time.time() - start) * 1000
            data = resp.json() if resp.content else {}
            error_class, error_msg = classify_error(resp.status_code, data)

            log_call(endpoint_path.split("/")[0], resp.status_code, round(latency, 2), error_class, error_msg)

            if error_class in ("RATE_LIMIT", "SERVER_ERROR") and attempt < retries:
                wait = BACKOFF_BASE ** attempt
                log.warning(f"[{error_class}] Attempt {attempt}/{retries} — retrying in {wait}s")
                time.sleep(wait)
                continue

            if error_class:
                log.error(f"[{error_class}] {error_msg}")
                return None, error_class

            log.info(f"[OK] {endpoint_path.split('/')[0]} — {round(latency, 2)}ms")
            return data, None

        except requests.exceptions.Timeout:
            latency = (time.time() - start) * 1000
            log_call("places", None, round(latency, 2), "TIMEOUT", "Request timed out after 10s")
            log.error(f"[TIMEOUT] timed out on attempt {attempt}")
            if attempt < retries:
                time.sleep(BACKOFF_BASE ** attempt)

        except requests.exceptions.ConnectionError as e:
            log_call("places", None, 0, "CONNECTION_ERROR", str(e))
            log.error(f"[CONNECTION_ERROR] {e}")
            return None, "CONNECTION_ERROR"

    return None, "MAX_RETRIES_EXCEEDED"

# ── API methods ────────────────────────────────────────────────────────────────

def search_places(query, location="New Orleans, LA", radius=5000):
    """
    Endpoint: places:searchText (POST)
    Finds businesses matching a keyword query near a location.
    Equivalent to Yelp's /businesses/search endpoint.
    """
    log.info(f"Searching for '{query}' near {location}")
    payload = {
        "textQuery": f"{query} near {location}",
        "maxResultCount": 10
    }
    field_mask = "places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount"
    data, err = make_post_request("places:searchText", payload, field_mask)
    if err or not data:
        return []

    results = data.get("places", [])
    for place in results:
        save_place(place)
    log.info(f"Found {len(results)} results for '{query}'")
    return results


def get_place_details(place_id):
    """
    Endpoint: places/{place_id} (GET)
    Gets full details for a specific business by place_id.
    Equivalent to Yelp's /businesses/{id} endpoint.
    """
    log.info(f"Fetching details for place_id: {place_id}")
    field_mask = "id,displayName,formattedAddress,nationalPhoneNumber,rating,userRatingCount,regularOpeningHours,websiteUri,reviews"
    data, err = make_get_request(f"places/{place_id}", field_mask)
    if err:
        return None
    save_place(data)
    return data


def search_by_text(business_name, location="New Orleans, LA"):
    """
    Endpoint: places:searchText (POST)
    Looks up a specific business by name and location.
    Equivalent to Yelp's /businesses/search/phone endpoint.
    """
    log.info(f"Looking up business: '{business_name}' in {location}")
    payload = {
        "textQuery": f"{business_name} {location}",
        "maxResultCount": 1
    }
    field_mask = "places.id,places.displayName,places.formattedAddress,places.rating"
    data, err = make_post_request("places:searchText", payload, field_mask)
    if err or not data:
        return None
    results = data.get("places", [])
    if results:
        save_place(results[0])
        return results[0]
    return None

# ── Integration health report ──────────────────────────────────────────────────

def print_health_report():
    conn = sqlite3.connect(DB_PATH)
    print("\n" + "="*60)
    print("INTEGRATION HEALTH REPORT")
    print("="*60)

    rows = conn.execute("""
        SELECT endpoint, COUNT(*) as calls,
               ROUND(AVG(latency_ms), 1) as avg_latency,
               SUM(CASE WHEN error_class IS NULL THEN 0 ELSE 1 END) as errors
        FROM api_calls
        GROUP BY endpoint
    """).fetchall()

    print(f"{'Endpoint':<25} {'Calls':>6} {'Avg Latency':>12} {'Errors':>7}")
    print("-"*55)
    for row in rows:
        print(f"{row[0]:<25} {row[1]:>6} {str(row[2])+'ms':>12} {row[3]:>7}")

    total_places = conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
    print(f"\nPlaces stored in DB: {total_places}")

    recent_errors = conn.execute("""
        SELECT endpoint, error_class, error_msg, timestamp
        FROM api_calls WHERE error_class IS NOT NULL
        ORDER BY timestamp DESC LIMIT 5
    """).fetchall()

    if recent_errors:
        print("\nRecent Errors:")
        for e in recent_errors:
            print(f"  [{e[1]}] {e[0]} — {e[2]} ({e[3]})")

    print("="*60 + "\n")
    conn.close()

# ── Main demo run ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    log.info("Starting partner API integration demo")

    # 1. Business search (simulates partner onboarding their first API call)
    restaurants = search_places("seafood restaurants", location="New Orleans, LA")
    if restaurants:
        top = restaurants[0]
        name = top.get("displayName", {}).get("text", "Unknown")
        print(f"\nTop result: {name} — Rating: {top.get('rating')} ({top.get('userRatingCount')} reviews)")

        # 2. Fetch full details for the top result
        details = get_place_details(top["id"])
        if details:
            print(f"Address: {details.get('formattedAddress')}")
            print(f"Phone: {details.get('nationalPhoneNumber', 'N/A')}")
            print(f"Website: {details.get('websiteUri', 'N/A')}")
            reviews = details.get("reviews", [])
            if reviews:
                review_text = reviews[0].get("text", {}).get("text", "")
                print(f"Top review: \"{review_text[:120]}...\"")

    # 3. Search a second category to build up health data
    bars = search_places("cocktail bars", location="New Orleans, LA")
    if bars:
        print(f"\nFound {len(bars)} cocktail bars in New Orleans")

    # 4. Named business lookup demo
    biz = search_by_text("Dooky Chase's Restaurant", location="New Orleans, LA")
    if biz:
        name = biz.get("displayName", {}).get("text", "Unknown")
        print(f"\nBusiness lookup result: {name}")

    # 5. Print integration health report
    print_health_report()
