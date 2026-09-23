"""
db.py — CineMind AI SQLite Database Layer

Provides all database operations for the movie catalog.
Shared by tmdb_data_loader.py (ingestion) and movie_recommendation.py (queries).

Database file: cinemind.db  (same directory as this file)
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------
# DATABASE PATH
# --------------------------------------------------

DB_PATH = Path(__file__).parent / "cinemind.db"


# --------------------------------------------------
# CONNECTION HELPER
# --------------------------------------------------

def _connect() -> sqlite3.Connection:
    """Open a connection with WAL mode for concurrent access."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


# --------------------------------------------------
# SCHEMA INITIALISATION
# --------------------------------------------------

_CREATE_MOVIES_TABLE = """
CREATE TABLE IF NOT EXISTS movies (
    id               INTEGER PRIMARY KEY,   -- TMDB movie ID
    title            TEXT    NOT NULL,
    original_title   TEXT,
    overview         TEXT,
    release_date     TEXT,
    vote_average     REAL    DEFAULT 0.0,
    vote_count       INTEGER DEFAULT 0,
    popularity       REAL    DEFAULT 0.0,
    original_language TEXT,
    adult            INTEGER DEFAULT 0,     -- 0 = False, 1 = True
    poster_path      TEXT,
    backdrop_path    TEXT,
    -- ML-compatible feature fields (space-separated tokens, no spaces within names)
    genres_clean     TEXT    DEFAULT '',
    keywords_clean   TEXT    DEFAULT '',
    cast_clean       TEXT    DEFAULT '',
    director_clean   TEXT    DEFAULT '',
    -- Raw JSON for UI genre filter
    genres_json      TEXT    DEFAULT '[]',
    -- Extra metadata
    runtime          INTEGER DEFAULT 0,
    enriched         INTEGER DEFAULT 0,     -- 0 = basic discover data, 1 = detail-fetched
    inserted_at      TEXT,
    updated_at       TEXT
);
"""

_CREATE_INDEX_TITLE = """
CREATE INDEX IF NOT EXISTS idx_movies_title
    ON movies (title COLLATE NOCASE);
"""

_CREATE_INDEX_VOTE = """
CREATE INDEX IF NOT EXISTS idx_movies_vote_average
    ON movies (vote_average);
"""

_CREATE_INDEX_POPULARITY = """
CREATE INDEX IF NOT EXISTS idx_movies_popularity
    ON movies (popularity);
"""

_CREATE_INDEX_RELEASE = """
CREATE INDEX IF NOT EXISTS idx_movies_release_date
    ON movies (release_date);
"""

_CREATE_PROGRESS_TABLE = """
CREATE TABLE IF NOT EXISTS ingestion_progress (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def init_db() -> None:
    """Create all tables and indexes if they do not already exist."""
    with _connect() as conn:
        conn.execute(_CREATE_MOVIES_TABLE)
        conn.execute(_CREATE_INDEX_TITLE)
        conn.execute(_CREATE_INDEX_VOTE)
        conn.execute(_CREATE_INDEX_POPULARITY)
        conn.execute(_CREATE_INDEX_RELEASE)
        conn.execute(_CREATE_PROGRESS_TABLE)
        conn.commit()


# --------------------------------------------------
# UPSERT
# --------------------------------------------------

_UPSERT_MOVIE = """
INSERT INTO movies (
    id, title, original_title, overview, release_date,
    vote_average, vote_count, popularity, original_language, adult,
    poster_path, backdrop_path, genres_clean, keywords_clean,
    cast_clean, director_clean, genres_json, runtime, enriched,
    inserted_at, updated_at
) VALUES (
    :id, :title, :original_title, :overview, :release_date,
    :vote_average, :vote_count, :popularity, :original_language, :adult,
    :poster_path, :backdrop_path, :genres_clean, :keywords_clean,
    :cast_clean, :director_clean, :genres_json, :runtime, :enriched,
    :inserted_at, :updated_at
)
ON CONFLICT(id) DO UPDATE SET
    title             = excluded.title,
    original_title    = excluded.original_title,
    overview          = excluded.overview,
    release_date      = excluded.release_date,
    vote_average      = excluded.vote_average,
    vote_count        = excluded.vote_count,
    popularity        = excluded.popularity,
    original_language = excluded.original_language,
    adult             = excluded.adult,
    poster_path       = excluded.poster_path,
    backdrop_path     = excluded.backdrop_path,
    genres_clean      = excluded.genres_clean,
    genres_json       = excluded.genres_json,
    runtime           = excluded.runtime,
    updated_at        = excluded.updated_at;
"""

# For enriched updates we update the ML fields as well
_UPSERT_ENRICHED = """
INSERT INTO movies (
    id, title, original_title, overview, release_date,
    vote_average, vote_count, popularity, original_language, adult,
    poster_path, backdrop_path, genres_clean, keywords_clean,
    cast_clean, director_clean, genres_json, runtime, enriched,
    inserted_at, updated_at
) VALUES (
    :id, :title, :original_title, :overview, :release_date,
    :vote_average, :vote_count, :popularity, :original_language, :adult,
    :poster_path, :backdrop_path, :genres_clean, :keywords_clean,
    :cast_clean, :director_clean, :genres_json, :runtime, :enriched,
    :inserted_at, :updated_at
)
ON CONFLICT(id) DO UPDATE SET
    title             = excluded.title,
    original_title    = excluded.original_title,
    overview          = excluded.overview,
    release_date      = excluded.release_date,
    vote_average      = excluded.vote_average,
    vote_count        = excluded.vote_count,
    popularity        = excluded.popularity,
    original_language = excluded.original_language,
    adult             = excluded.adult,
    poster_path       = excluded.poster_path,
    backdrop_path     = excluded.backdrop_path,
    genres_clean      = excluded.genres_clean,
    keywords_clean    = excluded.keywords_clean,
    cast_clean        = excluded.cast_clean,
    director_clean    = excluded.director_clean,
    genres_json       = excluded.genres_json,
    runtime           = excluded.runtime,
    enriched          = excluded.enriched,
    updated_at        = excluded.updated_at;
"""


def upsert_movie(movie: dict, enriched: bool = False) -> None:
    """
    Insert or update a single movie record.

    Parameters
    ----------
    movie : dict
        Must contain at minimum: id, title.
        All other fields default to empty / 0 if missing.
    enriched : bool
        If True, also updates keywords_clean / cast_clean / director_clean.
    """
    now = datetime.now(timezone.utc).isoformat()

    row = {
        "id":                int(movie["id"]),
        "title":             movie.get("title", ""),
        "original_title":    movie.get("original_title", ""),
        "overview":          movie.get("overview", ""),
        "release_date":      movie.get("release_date", ""),
        "vote_average":      float(movie.get("vote_average", 0.0)),
        "vote_count":        int(movie.get("vote_count", 0)),
        "popularity":        float(movie.get("popularity", 0.0)),
        "original_language": movie.get("original_language", ""),
        "adult":             int(bool(movie.get("adult", False))),
        "poster_path":       movie.get("poster_path", ""),
        "backdrop_path":     movie.get("backdrop_path", ""),
        "genres_clean":      movie.get("genres_clean", ""),
        "keywords_clean":    movie.get("keywords_clean", ""),
        "cast_clean":        movie.get("cast_clean", ""),
        "director_clean":    movie.get("director_clean", ""),
        "genres_json":       movie.get("genres_json", "[]"),
        "runtime":           int(movie.get("runtime", 0)),
        "enriched":          int(bool(enriched)),
        "inserted_at":       movie.get("inserted_at", now),
        "updated_at":        now,
    }

    sql = _UPSERT_ENRICHED if enriched else _UPSERT_MOVIE

    with _connect() as conn:
        conn.execute(sql, row)
        conn.commit()


def upsert_movies_batch(movies: list[dict], enriched: bool = False) -> int:
    """
    Bulk upsert a list of movie dicts. Returns number of rows processed.
    Uses a single transaction for performance.
    """
    if not movies:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    sql = _UPSERT_ENRICHED if enriched else _UPSERT_MOVIE

    rows = []
    for movie in movies:
        rows.append({
            "id":                int(movie["id"]),
            "title":             movie.get("title", ""),
            "original_title":    movie.get("original_title", ""),
            "overview":          movie.get("overview", ""),
            "release_date":      movie.get("release_date", ""),
            "vote_average":      float(movie.get("vote_average", 0.0)),
            "vote_count":        int(movie.get("vote_count", 0)),
            "popularity":        float(movie.get("popularity", 0.0)),
            "original_language": movie.get("original_language", ""),
            "adult":             int(bool(movie.get("adult", False))),
            "poster_path":       movie.get("poster_path", ""),
            "backdrop_path":     movie.get("backdrop_path", ""),
            "genres_clean":      movie.get("genres_clean", ""),
            "keywords_clean":    movie.get("keywords_clean", ""),
            "cast_clean":        movie.get("cast_clean", ""),
            "director_clean":    movie.get("director_clean", ""),
            "genres_json":       movie.get("genres_json", "[]"),
            "runtime":           int(movie.get("runtime", 0)),
            "enriched":          int(bool(enriched)),
            "inserted_at":       movie.get("inserted_at", now),
            "updated_at":        now,
        })

    with _connect() as conn:
        conn.executemany(sql, rows)
        conn.commit()

    return len(rows)


# --------------------------------------------------
# PROGRESS TRACKING (for loader resume)
# --------------------------------------------------

def get_last_page(lang: str = "en") -> int:
    """Return the last successfully completed ingestion page for a given language (0 if none)."""
    key = f"last_page_{lang}"
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM ingestion_progress WHERE key = ?;",
            (key,)
        ).fetchone()
    return int(row["value"]) if row else 0


def set_last_page(page: int, lang: str = "en") -> None:
    """Persist the last successfully completed page number for a given language."""
    key = f"last_page_{lang}"
    with _connect() as conn:
        conn.execute(
            "INSERT INTO ingestion_progress (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
            (key, str(page))
        )
        conn.commit()


def reset_progress(lang: str | None = None) -> None:
    """Reset ingestion progress. If lang is None, resets ALL languages."""
    with _connect() as conn:
        if lang is None:
            conn.execute(
                "DELETE FROM ingestion_progress WHERE key LIKE 'last_page_%';"
            )
        else:
            conn.execute(
                "DELETE FROM ingestion_progress WHERE key = ?;",
                (f"last_page_{lang}",)
            )
        conn.commit()


# --------------------------------------------------
# QUERIES
# --------------------------------------------------

def get_movie_count() -> int:
    """Return total number of movies stored."""
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM movies;").fetchone()
    return row["cnt"] if row else 0


def search_movies_db(query: str, limit: int = 5) -> list[dict]:
    """
    Case-insensitive title search. Returns a list of row dicts.
    """
    pattern = f"%{query}%"
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM movies WHERE title LIKE ? COLLATE NOCASE LIMIT ?;",
            (pattern, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_movies_df():
    """
    Load the full movie catalog as a pandas DataFrame.
    Columns match what movie_recommendation.py expects:
        id, title, overview, release_date, vote_average, vote_count,
        popularity, genres_clean, keywords_clean, cast_clean, director_clean,
        poster_path, backdrop_path, original_language, genres_json
    """
    import pandas as pd

    with _connect() as conn:
        df = pd.read_sql_query("SELECT * FROM movies;", conn)

    # Ensure ML feature columns are strings (never NaN)
    for col in ("genres_clean", "keywords_clean", "cast_clean",
                "director_clean", "overview"):
        df[col] = df[col].fillna("")

    return df


def get_genres_db() -> list[str]:
    """
    Return a sorted list of unique genre names from the genres_json column.
    """
    genres: set[str] = set()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT genres_json FROM movies WHERE genres_json != '' AND genres_json != '[]';"
        ).fetchall()

    for row in rows:
        try:
            items = json.loads(row["genres_json"])
            for item in items:
                if isinstance(item, dict) and item.get("name"):
                    genres.add(item["name"])
        except (json.JSONDecodeError, TypeError):
            pass

    return sorted(genres)


def get_years_db() -> list[int]:
    """
    Return a sorted list of unique release years from the database.
    """
    import pandas as pd

    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT release_date FROM movies WHERE release_date IS NOT NULL AND release_date != '';"
        ).fetchall()

    years: set[int] = set()
    for row in rows:
        try:
            dt = pd.to_datetime(row["release_date"], errors="coerce")
            if not pd.isna(dt):
                years.add(int(dt.year))
        except Exception:
            pass

    return sorted(years)


def get_movie_by_id(movie_id: int) -> dict | None:
    """Return a single movie dict by TMDB ID, or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM movies WHERE id = ?;", (movie_id,)
        ).fetchone()
    return dict(row) if row else None


def get_movies_paginated(
    page: int = 1,
    page_size: int = 20,
    min_rating: float = 0.0,
    genre: str | None = None,
    year: int | None = None,
    order_by: str = "popularity DESC"
) -> tuple[list[dict], int]:
    """
    Paginated movie query with optional filters.

    Returns (rows, total_count).
    """
    conditions = ["vote_average >= ?"]
    params: list = [min_rating]

    if genre:
        conditions.append("genres_clean LIKE ?")
        params.append(f"%{genre.replace(' ', '')}%")

    if year is not None:
        conditions.append("release_date LIKE ?")
        params.append(f"{year}-%")

    where_clause = " AND ".join(conditions)

    # Whitelist allowed order_by values to prevent SQL injection
    allowed_orders = {
        "popularity DESC", "popularity ASC",
        "vote_average DESC", "vote_average ASC",
        "release_date DESC", "release_date ASC",
        "title ASC", "title DESC"
    }
    if order_by not in allowed_orders:
        order_by = "popularity DESC"

    offset = (page - 1) * page_size

    with _connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM movies WHERE {where_clause};",
            params
        ).fetchone()["cnt"]

        rows = conn.execute(
            f"SELECT * FROM movies WHERE {where_clause}"
            f" ORDER BY {order_by} LIMIT ? OFFSET ?;",
            params + [page_size, offset]
        ).fetchall()

    return [dict(r) for r in rows], total


# --------------------------------------------------
# DIAGNOSTICS
# --------------------------------------------------

def db_info() -> dict:
    """Return a summary dict for display/debugging."""
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS cnt FROM movies;").fetchone()["cnt"]
        enriched = conn.execute(
            "SELECT COUNT(*) AS cnt FROM movies WHERE enriched = 1;"
        ).fetchone()["cnt"]
        last_update = conn.execute(
            "SELECT MAX(updated_at) AS ts FROM movies;"
        ).fetchone()["ts"]
        last_page = get_last_page()

    return {
        "total_movies": count,
        "enriched_movies": enriched,
        "last_updated": last_update or "Never",
        "last_ingestion_page": last_page,
        "db_path": str(DB_PATH),
    }


# --------------------------------------------------
# MODULE SELF-TEST
# --------------------------------------------------

if __name__ == "__main__":
    print("Initialising database...")
    init_db()
    info = db_info()
    print(f"  DB path          : {info['db_path']}")
    print(f"  Total movies     : {info['total_movies']}")
    print(f"  Enriched movies  : {info['enriched_movies']}")
    print(f"  Last updated     : {info['last_updated']}")
    print(f"  Last page done   : {info['last_ingestion_page']}")
    print("Database ready.")
