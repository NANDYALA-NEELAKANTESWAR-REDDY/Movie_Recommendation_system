"""
tmdb_data_loader.py — CineMind AI TMDB Movie Ingestion Script

Fetches movies from the TMDB /discover/movie endpoint, page by page,
and stores them in cinemind.db via the db module.

USAGE
-----
    python tmdb_data_loader.py

CONFIGURATION
-------------
Edit the constants block below to control behaviour.
The TMDB token is read from .streamlit/secrets.toml — never hardcoded.

RESUMING
--------
The loader saves progress after every page. If it is interrupted, re-running
it will continue from the last successful page automatically.

INCREASING THE TARGET
---------------------
Change TARGET_MOVIES to 5000, 10000, 50000, etc. and re-run. Already-stored
movies are skipped via ON CONFLICT (upsert), so no duplicates are created.

SECURITY
--------
- Token is read from .streamlit/secrets.toml at startup.
- Token is NEVER printed, logged, or written to the database.
- If the token is missing, the script exits cleanly with an explanation.
"""

from __future__ import annotations

import sys
import time
import json
import re
from pathlib import Path
from datetime import datetime, timezone

import requests

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError for emoji)
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# --------------------------------------------------
# CONFIGURATION  <- Edit these to control ingestion
# --------------------------------------------------

# Per-language movie targets.
# Each language runs a separate /discover/movie pass.
# TMDB hard-limits each language to 500 pages = ~10,000 movies max.
#
# Total across all languages below: ~50,000+
# To expand further, add more languages or increase individual targets.
LANGUAGE_TARGETS: dict[str, int] = {
    # --- Indian languages ---
    "en": 10000,   # English (global + Bollywood English films)
    "hi": 10000,   # Hindi
    "ta": 10000,   # Tamil
    "te": 10000,   # Telugu
    "ml": 10000,   # Malayalam
    "kn":  5000,   # Kannada
    "bn":  5000,   # Bengali
    "mr":  3000,   # Marathi
    "pa":  2000,   # Punjabi
    "gu":  1000,   # Gujarati
    "or":   500,   # Odia
    "as":   500,   # Assamese
    "ur":   500,   # Urdu
    # --- Popular world cinema (adds variety + volume) ---
    "ja":  5000,   # Japanese
    "ko":  3000,   # Korean
    "zh":  3000,   # Chinese (Mandarin)
    "fr":  2000,   # French
    "es":  2000,   # Spanish
    "de":  1000,   # German
    "it":  1000,   # Italian
    "pt":  1000,   # Portuguese
    "ru":  1000,   # Russian
    "tr":   500,   # Turkish
}

# Human-readable language names for progress display
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "ml": "Malayalam",
    "kn": "Kannada",
    "bn": "Bengali",
    "mr": "Marathi",
    "pa": "Punjabi",
    "gu": "Gujarati",
    "or": "Odia",
    "as": "Assamese",
    "ur": "Urdu",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "tr": "Turkish",
}

REQUEST_DELAY  = 0.26   # Seconds to wait between API calls
                        # 0.26 s = ~3.8 req/s (TMDB limit: 50 req/s read)

MAX_RETRIES    = 5      # Max retry attempts on transient errors (429, 500)
BACKOFF_BASE   = 2      # Exponential backoff base in seconds (2^attempt)

SORT_BY        = "popularity.desc"  # TMDB discover sort order
MIN_VOTE_COUNT = 0      # 0 = include all movies regardless of vote count
                        # (needed to maximise Indian-language catalog depth)
RESPONSE_LANG  = "en-US"  # Metadata response language (titles, overviews)


# --------------------------------------------------
# TMDB GENRE MAP  (id → name)
# Avoids extra API calls for basic ingestion.
# Source: https://api.themoviedb.org/3/genre/movie/list
# --------------------------------------------------

GENRE_MAP: dict[int, str] = {
    28:    "Action",
    12:    "Adventure",
    16:    "Animation",
    35:    "Comedy",
    80:    "Crime",
    99:    "Documentary",
    18:    "Drama",
    10751: "Family",
    14:    "Fantasy",
    36:    "History",
    27:    "Horror",
    10402: "Music",
    9648:  "Mystery",
    10749: "Romance",
    878:   "Science Fiction",
    10770: "TV Movie",
    53:    "Thriller",
    10752: "War",
    37:    "Western",
}

RESULTS_PER_PAGE = 20   # TMDB always returns 20 per page (fixed by API)


# --------------------------------------------------
# TOKEN LOADING
# --------------------------------------------------

def _load_token() -> str:
    """
    Load TMDB bearer token from .streamlit/secrets.toml.
    Exits the process if the file or key is missing.
    NEVER prints the token value.
    """
    secrets_path = Path(__file__).parent / ".streamlit" / "secrets.toml"

    if not secrets_path.exists():
        print(
            f"[ERROR] Secrets file not found: {secrets_path}\n"
            "Create .streamlit/secrets.toml with:\n"
            '    TMDB_TOKEN = "your_token_here"'
        )
        sys.exit(1)

    # Use tomllib (Python 3.11+) or fall back to manual parse
    try:
        import tomllib  # Python 3.11+
        with open(secrets_path, "rb") as f:
            config = tomllib.load(f)
    except ImportError:
        # Fallback: simple key=value parser for TOML
        config = _parse_simple_toml(secrets_path)

    token = config.get("TMDB_TOKEN", "").strip()

    if not token:
        print(
            "[ERROR] TMDB_TOKEN is missing or empty in .streamlit/secrets.toml.\n"
            "Add: TMDB_TOKEN = \"your_token_here\""
        )
        sys.exit(1)

    # Sanity check: token should look like a JWT (3 dot-separated parts)
    if len(token.split(".")) != 3:
        print(
            "[WARNING] TMDB_TOKEN does not look like a valid JWT bearer token.\n"
            "Continuing anyway — the API will confirm validity."
        )

    return token


def _parse_simple_toml(path: Path) -> dict[str, str]:
    """Minimal TOML parser for simple key = 'value' pairs (no sections)."""
    result: dict[str, str] = {}
    pattern = re.compile(r'^(\w+)\s*=\s*["\'](.+?)["\']')
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = pattern.match(line.strip())
            if m:
                result[m.group(1)] = m.group(2)
    return result


# --------------------------------------------------
# GENRE HELPERS
# --------------------------------------------------

def _genre_ids_to_clean(genre_ids: list[int]) -> str:
    """
    Convert a list of TMDB genre IDs to a space-separated string of
    genre names with no internal spaces — matching the ML pipeline format.

    Example: [28, 878] → "Action ScienceFiction"
    """
    return " ".join(
        GENRE_MAP.get(gid, "").replace(" ", "")
        for gid in genre_ids
        if gid in GENRE_MAP
    )


def _genre_ids_to_json(genre_ids: list[int]) -> str:
    """Convert genre IDs to JSON list of {id, name} dicts for the UI filter."""
    items = [
        {"id": gid, "name": GENRE_MAP[gid]}
        for gid in genre_ids
        if gid in GENRE_MAP
    ]
    return json.dumps(items)


# --------------------------------------------------
# API REQUEST WITH RETRY
# --------------------------------------------------

def _fetch_page(
    session: requests.Session,
    page: int,
    with_original_language: str | None = None
) -> dict | None:
    """
    Fetch a single /discover/movie page.

    Parameters
    ----------
    session : requests.Session
        Authenticated session.
    page : int
        Page number (1-based).
    with_original_language : str | None
        ISO 639-1 language code to filter by (e.g. 'hi', 'te', 'ta').
        None = no filter (returns all languages).

    Returns the parsed JSON dict on success, or None on unrecoverable error.
    Raises SystemExit on 401 (invalid token).

    HTTP status handling:
        200 -> return data
        401 -> abort (bad token)
        404 -> skip (no such page)
        429 -> exponential backoff + retry
        5xx -> exponential backoff + retry
        other -> skip with warning
    """
    url = "https://api.themoviedb.org/3/discover/movie"
    params: dict = {
        "sort_by":          SORT_BY,
        "page":             page,
        "language":         RESPONSE_LANG,
        "vote_count.gte":   MIN_VOTE_COUNT,
    }
    if with_original_language:
        params["with_original_language"] = with_original_language


    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, params=params, timeout=15)

        except requests.Timeout:
            wait = BACKOFF_BASE ** attempt
            print(f"  [TIMEOUT] page {page} attempt {attempt}/{MAX_RETRIES}"
                  f" — retrying in {wait}s")
            time.sleep(wait)
            continue

        except requests.ConnectionError as exc:
            wait = BACKOFF_BASE ** attempt
            print(f"  [CONN ERROR] page {page} attempt {attempt}/{MAX_RETRIES}"
                  f": {type(exc).__name__} — retrying in {wait}s")
            time.sleep(wait)
            continue

        status = response.status_code

        if status == 200:
            try:
                return response.json()
            except ValueError:
                print(f"  [JSON ERROR] page {page} — invalid JSON response, skipping.")
                return None

        elif status == 401:
            # Do NOT print the token. Just the status code.
            print(
                "[FATAL] HTTP 401 — TMDB rejected the bearer token.\n"
                "Check TMDB_TOKEN in .streamlit/secrets.toml.\n"
                "Aborting."
            )
            sys.exit(1)

        elif status == 404:
            print(f"  [404] page {page} not found — skipping.")
            return None

        elif status == 429:
            retry_after = int(response.headers.get("Retry-After", BACKOFF_BASE ** attempt))
            print(f"  [429] Rate limited on page {page}."
                  f" Waiting {retry_after}s (attempt {attempt}/{MAX_RETRIES})...")
            time.sleep(retry_after)
            continue

        elif 500 <= status < 600:
            wait = BACKOFF_BASE ** attempt
            print(f"  [HTTP {status}] Server error on page {page}."
                  f" Retrying in {wait}s (attempt {attempt}/{MAX_RETRIES})...")
            time.sleep(wait)
            continue

        else:
            print(f"  [HTTP {status}] Unexpected status on page {page} — skipping.")
            return None

    print(f"  [FAILED] page {page} failed after {MAX_RETRIES} attempts — skipping.")
    return None


# --------------------------------------------------
# PAGE PROCESSING
# --------------------------------------------------

def _process_page(data: dict) -> list[dict]:
    """
    Convert raw TMDB /discover/movie results into movie dicts
    compatible with the db.upsert_movies_batch interface.
    """
    now = datetime.now(timezone.utc).isoformat()
    results = data.get("results", [])
    movies = []

    for item in results:
        movie_id = item.get("id")
        if not movie_id:
            continue

        genre_ids = item.get("genre_ids", [])

        movie = {
            "id":                movie_id,
            "title":             item.get("title", ""),
            "original_title":    item.get("original_title", ""),
            "overview":          item.get("overview", ""),
            "release_date":      item.get("release_date", ""),
            "vote_average":      item.get("vote_average", 0.0),
            "vote_count":        item.get("vote_count", 0),
            "popularity":        item.get("popularity", 0.0),
            "original_language": item.get("original_language", ""),
            "adult":             item.get("adult", False),
            "poster_path":       item.get("poster_path") or "",
            "backdrop_path":     item.get("backdrop_path") or "",
            # ML-compatible fields
            "genres_clean":      _genre_ids_to_clean(genre_ids),
            "keywords_clean":    "",   # populated during enrichment (future)
            "cast_clean":        "",   # populated during enrichment (future)
            "director_clean":    "",   # populated during enrichment (future)
            # UI genre filter
            "genres_json":       _genre_ids_to_json(genre_ids),
            "runtime":           0,    # populated during enrichment (future)
            "inserted_at":       now,
        }
        movies.append(movie)

    return movies


# --------------------------------------------------
# MAIN INGESTION LOOP
# --------------------------------------------------

def _run_language_pass(
    session: requests.Session,
    db,
    lang: str,
    lang_target: int,
    grand_total_target: int,
) -> tuple[int, int]:
    """
    Fetch movies for a single language until lang_target is reached.
    Returns (pages_fetched, new_movies_added).

    Uses per-language progress keys so each language can be resumed
    independently if the process is interrupted.
    """
    lang_name = LANGUAGE_NAMES.get(lang, lang.upper())
    print()
    print("-" * 60)
    print(f"  Language: {lang_name} ({lang})  |  Target: {lang_target:,}")
    print("-" * 60)

    # Count movies already in DB for this language
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    lang_count = conn.execute(
        "SELECT COUNT(*) FROM movies WHERE original_language = ?;", (lang,)
    ).fetchone()[0]
    conn.close()

    print(f"  Already in DB  : {lang_count:,} {lang_name} movies")

    if lang_count >= lang_target:
        print(f"  [SKIP] {lang_name} target already met.")
        return 0, 0

    start_page = db.get_last_page(lang) + 1
    if start_page > 1:
        print(f"  Resuming from  : page {start_page}")
    else:
        print(f"  Starting from  : page 1")

    total_new   = 0
    total_pages = 0
    max_pages   = 500  # TMDB hard limit per language

    for page in range(start_page, max_pages + 1):

        # Check per-language count directly
        conn = sqlite3.connect(db.DB_PATH)
        current_lang_count = conn.execute(
            "SELECT COUNT(*) FROM movies WHERE original_language = ?;", (lang,)
        ).fetchone()[0]
        conn.close()

        if current_lang_count >= lang_target:
            print(
                f"\n  [DONE] {lang_name} target reached: "
                f"{current_lang_count:,} / {lang_target:,}"
            )
            break

        remaining = lang_target - current_lang_count
        overall   = db.get_movie_count()
        print(
            f"  [{lang}] Page {page:>4}  |  {lang_name}: {current_lang_count:>5,}"
            f"  |  Need: {remaining:>5,}  |  DB total: {overall:>6,}  ...",
            end="", flush=True
        )

        data = _fetch_page(session, page, with_original_language=lang)

        if data is None:
            print("  SKIPPED")
            continue

        total_tmdb_pages   = data.get("total_pages", 1)
        total_tmdb_results = data.get("total_results", 0)

        if page == start_page:
            print(
                f"\n  TMDB has {total_tmdb_results:,} {lang_name} movies"
                f" across {total_tmdb_pages:,} pages."
            )

        if page > total_tmdb_pages:
            print(f"\n  Reached TMDB last page for {lang_name} ({total_tmdb_pages}).")
            break

        movies = _process_page(data)

        if not movies:
            print("  (empty page)")
            db.set_last_page(page, lang)
            time.sleep(REQUEST_DELAY)
            continue

        before = db.get_movie_count()
        db.upsert_movies_batch(movies, enriched=False)
        db.set_last_page(page, lang)

        after    = db.get_movie_count()
        page_new = after - before
        total_new   += page_new
        total_pages += 1

        print(f"  +{page_new:>2} new  (total DB: {after:,})")

        time.sleep(REQUEST_DELAY)

    return total_pages, total_new


def run_ingestion() -> None:
    """
    Main entry point for the ingestion process.

    Loops over every language in LANGUAGE_TARGETS, fetching movies
    page-by-page with independent resume support per language.
    Progress is saved to cinemind.db after every page so the process
    can be safely interrupted and restarted.
    """

    import db  # local import; keep db.py co-located

    grand_total = sum(LANGUAGE_TARGETS.values())

    print("=" * 60)
    print("  CineMind AI — TMDB Multi-Language Ingestion")
    print("=" * 60)
    print(f"  Languages      : {', '.join(LANGUAGE_TARGETS.keys())}")
    print(f"  Grand target   : {grand_total:,} movies")
    print(f"  Sort order     : {SORT_BY}")
    print(f"  Min vote count : {MIN_VOTE_COUNT}")
    print(f"  Request delay  : {REQUEST_DELAY}s")
    print("=" * 60)

    # Load token (exits if missing -- never prints value)
    token = _load_token()
    print("  Token          : loaded OK")

    # Initialise DB
    db.init_db()
    print(f"  Existing movies: {db.get_movie_count():,}")
    print("=" * 60)

    # Build session with auth header (token used here, never printed after)
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "accept":        "application/json",
    })
    del token  # Remove reference immediately after use

    grand_pages = 0
    grand_new   = 0

    for lang, lang_target in LANGUAGE_TARGETS.items():
        pages, new = _run_language_pass(
            session, db, lang, lang_target, grand_total
        )
        grand_pages += pages
        grand_new   += new

    # --------------------------------------------------
    # FINAL SUMMARY
    # --------------------------------------------------
    final_count = db.get_movie_count()

    print()
    print("=" * 60)
    print("  INGESTION COMPLETE")
    print("=" * 60)
    print(f"  Languages      : {', '.join(LANGUAGE_TARGETS.keys())}")
    print(f"  Pages fetched  : {grand_pages:,}")
    print(f"  New movies     : {grand_new:,}")
    print(f"  Total in DB    : {final_count:,}")
    print(f"  DB path        : {db.DB_PATH}")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  - Edit LANGUAGE_TARGETS in tmdb_data_loader.py to adjust targets")
    print("  - Run: python tmdb_data_loader.py")
    print("  - Check DB: python db.py")
    print("  - Launch app: python -m streamlit run app.py")


# --------------------------------------------------
# ENTRY POINT
# --------------------------------------------------

if __name__ == "__main__":
    run_ingestion()
