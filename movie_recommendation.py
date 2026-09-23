import pandas as pd
import ast
from collections import Counter
import math
from pathlib import Path
import numpy as np
import re
import sys

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError)
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# db module is optional — only used when cinemind.db exists
try:
    import db as _db
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False

def normalize_title(text):
    return re.sub(r"[^a-z0-9]", "", str(text).lower())

# --------------------------------------------------
# PROJECT FOLDER
# --------------------------------------------------

folder = Path(__file__).parent


# --------------------------------------------------
# DATA SOURCE AUTO-DETECTION
# Prefers cinemind.db when it exists and is populated.
# Falls back to the original CSV files automatically.
# The ML pipeline below is identical in both cases.
# --------------------------------------------------

def _load_from_csv() -> pd.DataFrame:
    """Load and merge the original TMDB 5000 CSV files."""
    movies_file  = folder / "tmdb_5000_movies.csv"
    credits_file = folder / "tmdb_5000_credits.csv"

    _movies  = pd.read_csv(movies_file)
    _credits = pd.read_csv(credits_file)
    _credits = _credits.rename(columns={"movie_id": "id"})

    _movies = _movies.merge(
        _credits[["id", "cast", "crew"]],
        on="id",
        how="left"
    )

    print("[CineMind] Source: CSV files")
    print(f"[CineMind] Datasets merged — {len(_movies):,} movies")
    return _movies


def _load_from_db() -> pd.DataFrame:
    """
    Load the full movie catalog from cinemind.db.
    The DataFrame will already have the ML-compatible columns:
        genres_clean, keywords_clean, cast_clean, director_clean, overview
    """
    _movies = _db.get_all_movies_df()
    print(f"[CineMind] Source: SQLite (cinemind.db) — {len(_movies):,} movies")
    return _movies


def _load_movies() -> tuple[pd.DataFrame, str]:
    """
    Return (movies_dataframe, source_label).
    source_label is 'sqlite' or 'csv'.

    Decision logic:
      1. If db module is available AND cinemind.db exists AND has >= 1 movie
         → use SQLite
      2. Otherwise → use original CSV files
    """
    db_path = folder / "cinemind.db"

    if _DB_AVAILABLE and db_path.exists():
        try:
            count = _db.get_movie_count()
            if count > 0:
                return _load_from_db(), "sqlite"
        except Exception as exc:
            print(f"[CineMind] DB load failed ({exc}), falling back to CSV.")

    return _load_from_csv(), "csv"


# Load the movie dataset (auto-selects SQLite or CSV)
movies, _data_source = _load_movies()
print(f"[CineMind] Data source: {_data_source}")


# --------------------------------------------------
# FEATURE EXTRACTION HELPERS
# These are only called when the CSV source is active.
# The SQLite source stores pre-computed feature columns.
# --------------------------------------------------

def extract_names(text, limit=None):
    """Parse a JSON-like string of {name: ...} dicts into space-separated tokens."""
    try:
        data = ast.literal_eval(text)

        names = [
            item["name"].replace(" ", "")
            for item in data
        ]

        if limit:
            names = names[:limit]

        return " ".join(names)

    except:
        return ""


def extract_director(text):
    """Extract the Director name from a JSON-like crew string."""
    try:
        data = ast.literal_eval(text)

        for person in data:
            if person["job"] == "Director":
                return person["name"].replace(" ", "")

        return ""

    except:
        return ""


# Apply feature extraction only for CSV source
# (SQLite rows already have these columns populated)
if _data_source == "csv":
    movies["director_clean"] = movies["crew"].apply(extract_director)
    print("[CineMind] Director extraction completed!")

    movies["genres_clean"]   = movies["genres"].apply(extract_names)
    movies["keywords_clean"] = movies["keywords"].apply(extract_names)
    movies["cast_clean"]     = movies["cast"].apply(
        lambda x: extract_names(x, limit=7)
    )
    print("[CineMind] Feature extraction completed!")
else:
    # Ensure ML columns exist and are strings (DB rows already populated)
    for col in ("genres_clean", "keywords_clean", "cast_clean", "director_clean"):
        if col not in movies.columns:
            movies[col] = ""
        movies[col] = movies[col].fillna("")
    if "overview" not in movies.columns:
        movies["overview"] = ""
    movies["overview"] = movies["overview"].fillna("")
    print("[CineMind] SQLite feature columns ready.")

# --------------------------------------------------
# WEIGHTED MOVIE PROFILE  (unchanged ML logic)
# --------------------------------------------------

movies["movie_profile"] = (
    (movies["genres_clean"].fillna("") + " ") * 4 +
    (movies["keywords_clean"].fillna("") + " ") * 2 +
    (movies["director_clean"].fillna("") + " ") * 3 +
    (movies["cast_clean"].fillna("") + " ") * 2 +
    (movies["overview"].fillna("") + " ")
)
print("[CineMind] Weighted movie profile created!")

# --------------------------------------------------
# TF-IDF VECTORISATION  (unchanged ML logic)
#
# TODO(v2): Replace this block with:
#   1. Sentence-transformer embeddings (e.g., all-MiniLM-L6-v2)
#   2. FAISS / annoy / hnswlib approximate nearest-neighbour index
#   3. Sparse nearest-neighbour search via sklearn NearestNeighbors
#      with metric='cosine' (avoids full N×N matrix)
# --------------------------------------------------

def build_tfidf_matrix(texts, max_features=10000):
    """Build sparse TF-IDF rows without importing SciPy or scikit-learn."""
    stop_words = {
        "a", "an", "and", "are", "as", "at", "be", "by", "for",
        "from", "in", "is", "it", "of", "on", "or", "that", "the",
        "this", "to", "was", "with",
    }
    tokenized = []
    document_frequency = Counter()

    for text in texts.fillna(""):
        tokens = [
            token for token in re.findall(r"[a-z0-9]+", str(text).lower())
            if token not in stop_words
        ]
        tokenized.append(tokens)
        document_frequency.update(set(tokens))

    vocabulary = {
        token for token, _ in document_frequency.most_common(max_features)
    }
    document_count = len(tokenized)
    inverse_document_frequency = {
        token: math.log((1 + document_count) / (1 + document_frequency[token])) + 1
        for token in vocabulary
    }

    matrix = []
    for tokens in tokenized:
        counts = Counter(token for token in tokens if token in vocabulary)
        row = {
            token: (count / len(tokens)) * inverse_document_frequency[token]
            for token, count in counts.items()
        } if tokens else {}
        norm = math.sqrt(sum(value * value for value in row.values()))
        matrix.append({token: value / norm for token, value in row.items()} if norm else {})

    return matrix, len(vocabulary)


tfidf_matrix, tfidf_feature_count = build_tfidf_matrix(movies["movie_profile"])

print(f"[CineMind] TF-IDF matrix: {len(tfidf_matrix):,} movies × {tfidf_feature_count:,} features")

# --------------------------------------------------
# GENRE LIST & RELEASE YEARS  (for Streamlit UI filters)
# Works for both SQLite and CSV sources.
# --------------------------------------------------

if _data_source == "sqlite":
    # SQLite: use genres_json column for accurate names
    import json as _json
    _genre_set: set[str] = set()
    for _gjson in movies["genres_json"].dropna():
        try:
            for _g in _json.loads(_gjson):
                if isinstance(_g, dict) and _g.get("name"):
                    _genre_set.add(_g["name"])
        except Exception:
            pass
    available_genres = sorted(_genre_set)
else:
    # CSV: parse from the original genres column
    available_genres = sorted({
        item["name"]
        for text in movies["genres"]
        for item in (
            ast.literal_eval(text)
            if isinstance(text, str) and text.strip()
            else []
        )
        if isinstance(item, dict) and item.get("name")
    })

release_years = sorted(
    pd.to_datetime(
        movies["release_date"],
        errors="coerce"
    ).dt.year.dropna().astype(int).unique().tolist()
)

# Language code → human-readable label mapping
_LANG_LABELS = {
    "en": "English", "hi": "Hindi", "ta": "Tamil",
    "te": "Telugu", "ml": "Malayalam", "bn": "Bengali",
    "kn": "Kannada", "mr": "Marathi", "pa": "Punjabi",
    "ur": "Urdu", "or": "Odia", "gu": "Gujarati",
    "as": "Assamese", "ja": "Japanese", "ko": "Korean",
    "zh": "Chinese", "fr": "French", "es": "Spanish",
    "de": "German", "it": "Italian", "pt": "Portuguese",
    "ru": "Russian", "ar": "Arabic", "tr": "Turkish",
    "th": "Thai", "sv": "Swedish", "nl": "Dutch",
    "pl": "Polish", "fa": "Persian",
}

_lang_codes_in_db = sorted(movies["original_language"].dropna().unique().tolist())
available_languages = [
    _LANG_LABELS.get(code, code.upper())
    for code in _lang_codes_in_db
    if code.strip()
]
_lang_label_to_code = {
    _LANG_LABELS.get(code, code.upper()): code
    for code in _lang_codes_in_db
    if code.strip()
}

def search_movies(search_text, number_of_results=5):

    search_normalized = normalize_title(search_text)

    normalized_titles = movies["title"].apply(normalize_title)

    matches = movies[
        normalized_titles.str.contains(
            search_normalized,
            na=False,
            regex=False
        )
    ]

    if matches.empty:
        print("\n[SEARCH] No movies found!")
        return None

    print("\n[SEARCH] Movies found:")

    for i, (_, movie) in enumerate(
        matches.head(number_of_results).iterrows(),
        start=1
    ):
        print(f"{i}. {movie['title']}")

    return matches.head(number_of_results)
def get_common_features(movie_index, recommended_index):

    features = []

    # Genre comparison
    movie_genres = set(
        movies.iloc[movie_index]["genres_clean"].split()
    )

    recommended_genres = set(
        movies.iloc[recommended_index]["genres_clean"].split()
    )

    common_genres = movie_genres & recommended_genres

    if common_genres:
        features.append(
            "Genres: " + ", ".join(common_genres)
        )

    # Keyword comparison
    movie_keywords = set(
        movies.iloc[movie_index]["keywords_clean"].split()
    )

    recommended_keywords = set(
        movies.iloc[recommended_index]["keywords_clean"].split()
    )

    common_keywords = movie_keywords & recommended_keywords

    if common_keywords:
        features.append(
            "Keywords: " +
            ", ".join(list(common_keywords)[:5])
        )

    # Director comparison
    movie_director = movies.iloc[movie_index]["director_clean"]
    recommended_director = movies.iloc[recommended_index]["director_clean"]

    if (
        movie_director
        and movie_director == recommended_director
    ):
        features.append(
            "Same Director: " + movie_director
        )

    # Cast comparison
    movie_cast = set(
        movies.iloc[movie_index]["cast_clean"].split()
    )

    recommended_cast = set(
        movies.iloc[recommended_index]["cast_clean"].split()
    )

    common_cast = movie_cast & recommended_cast

    if common_cast:
        features.append(
            "Common Cast: " +
            ", ".join(list(common_cast)[:5])
        )

    return features
def calculate_feature_score(movie_index, recommended_index):

    score = 0

    # -------------------------
    # 1. Genre similarity
    # -------------------------
    movie_genres = set(
        movies.iloc[movie_index]["genres_clean"].split()
    )

    recommended_genres = set(
        movies.iloc[recommended_index]["genres_clean"].split()
    )

    if movie_genres and recommended_genres:
        genre_score = len(
            movie_genres & recommended_genres
        ) / len(
            movie_genres | recommended_genres
        )
    else:
        genre_score = 0


    # -------------------------
    # 2. Keyword similarity
    # -------------------------
    movie_keywords = set(
        movies.iloc[movie_index]["keywords_clean"].split()
    )

    recommended_keywords = set(
        movies.iloc[recommended_index]["keywords_clean"].split()
    )

    if movie_keywords and recommended_keywords:
        keyword_score = len(
            movie_keywords & recommended_keywords
        ) / len(
            movie_keywords | recommended_keywords
        )
    else:
        keyword_score = 0


    # -------------------------
    # 3. Director similarity
    # -------------------------
    movie_director = movies.iloc[movie_index]["director_clean"]
    recommended_director = movies.iloc[recommended_index]["director_clean"]

    if (
        movie_director
        and recommended_director
        and movie_director == recommended_director
    ):
        director_score = 1
    else:
        director_score = 0


    # -------------------------
    # 4. Cast similarity
    # -------------------------
    movie_cast = set(
        movies.iloc[movie_index]["cast_clean"].split()
    )

    recommended_cast = set(
        movies.iloc[recommended_index]["cast_clean"].split()
    )

    if movie_cast and recommended_cast:
        cast_score = len(
            movie_cast & recommended_cast
        ) / len(
            movie_cast | recommended_cast
        )
    else:
        cast_score = 0


    # -------------------------
    # 5. TF-IDF cosine similarity
    # -------------------------
    movie_vector = tfidf_matrix[movie_index]
    recommended_vector = tfidf_matrix[recommended_index]
    shared_tokens = movie_vector.keys() & recommended_vector.keys()
    cosine_score = sum(
        movie_vector[token] * recommended_vector[token]
        for token in shared_tokens
    )


    # -------------------------
    # 6. Final feature score
    # -------------------------
    final_feature_score = (
        0.30 * genre_score +
        0.20 * keyword_score +
        0.20 * director_score +
        0.15 * cast_score +
        0.15 * cosine_score
    )

    return final_feature_score
def get_movie_by_title(movie_title):
    """Return a dict of the movie's own metadata by exact title match."""
    row = movies[movies["title"].str.lower() == movie_title.lower()]
    if row.empty:
        return None
    m = row.iloc[0]
    return {
        "id": int(m["id"]),
        "title": m["title"],
        "poster_path": m.get("poster_path", ""),
        "rating": m["vote_average"],
        "vote_count": int(m.get("vote_count", 0)),
        "release_date": m["release_date"],
        "genres": m["genres_clean"],
        "overview": m["overview"],
        "original_language": m.get("original_language", ""),
        "director": m.get("director_clean", ""),
        "cast": m.get("cast_clean", ""),
        "popularity": float(m.get("popularity", 0)),
    }


def recommend_movies(
    movie_title,
    number_of_recommendations=5,
    selected_genre=None,
    minimum_rating=0,
    selected_year=None,
    selected_language=None
):

    movie_matches = movies[
        movies["title"].str.lower() == movie_title.lower()
    ]

    if movie_matches.empty:
        return []

    movie_index = movie_matches.index[0]

    final_scores = {}

    for index in range(len(movies)):

        if index == movie_index:
            continue

        if movies.iloc[index]["vote_count"] < 100:
            continue

        if movies.iloc[index]["vote_average"] <= 0:
            continue

        candidate = movies.iloc[index]

        if selected_genre:
            candidate_genres = {
                normalize_title(genre)
                for genre in candidate["genres_clean"].split()
            }
            if normalize_title(selected_genre) not in candidate_genres:
                continue

        if candidate["vote_average"] < minimum_rating:
            continue

        if selected_year is not None:
            release_year = pd.to_datetime(
                candidate["release_date"],
                errors="coerce"
            ).year
            if pd.isna(release_year) or int(release_year) != selected_year:
                continue

        if selected_language is not None:
            if str(candidate.get("original_language", "")).strip() != selected_language:
                continue

        feature_score = calculate_feature_score(
            movie_index,
            index
        )

        rating_score = (
            movies.iloc[index]["vote_average"] / 10
        )

        popularity_score = (
            movies.iloc[index]["popularity"] /
            movies["popularity"].max()
        )

        final_score = (
            0.80 * feature_score +
            0.10 * rating_score +
            0.10 * popularity_score
        )

        final_scores[index] = final_score

    similar_movies = sorted(
        final_scores.items(),
        key=lambda item: item[1],
        reverse=True
    )

    recommendations = []

    count = 0

    for index, score in similar_movies:

        if index == movie_index:
            continue

        movie = movies.iloc[index]

        common_features = get_common_features(
            movie_index,
            index
        )

        recommendations.append({
            "id": int(movie["id"]),
            "title": movie["title"],
            "poster_path": movie.get("poster_path", ""),
            "score": score,
            "rating": movie["vote_average"],
            "release_date": movie["release_date"],
            "genres": movie["genres_clean"],
            "keywords": movie["keywords_clean"],
            "overview": movie["overview"],
            "common_features": common_features,
            "director": movie.get("director_clean", ""),
            "cast": movie.get("cast_clean", ""),
            "original_language": movie.get("original_language", ""),
        })

        count += 1

        if count == number_of_recommendations:
            break

    return recommendations
if __name__ == "__main__":

    search_text = input("\nEnter a movie name: ")

    matches = search_movies(search_text)

    if matches is not None:

        choice = input("\nEnter movie number: ")

        try:
            choice = int(choice)

            if 1 <= choice <= len(matches):

                selected_movie = matches.iloc[
                    choice - 1
                ]["title"]

                recommendations = recommend_movies(
                    selected_movie
                )

                for i, movie in enumerate(
                    recommendations,
                    start=1
                ):
                    print(
                        f"\n{i}.  {movie['title']}"
                    )

            else:
                print("\n[ERROR] Invalid choice!")

        except ValueError:
            print("\n[ERROR] Please enter a number!")
