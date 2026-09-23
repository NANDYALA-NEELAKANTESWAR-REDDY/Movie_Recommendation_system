# CineMind AI

CineMind AI is a Streamlit movie recommendation app powered by a SQLite movie catalog and content-based similarity scoring.

## Features

- Search a catalog of movies.
- Generate recommendations using genres, keywords, cast, directors, ratings, language, and release year.
- Display movie posters from stored TMDB poster paths.
- Filter recommendations by genre, rating, language, year, and result count.
- Fall back to CSV data when the SQLite database is unavailable.

## Run Locally

1. Install Python 3.11 or newer.
2. Install the required packages:

```powershell
pip install streamlit pandas numpy requests
```

3. Start the app from this folder:

```powershell
streamlit run app.py
```

The app opens at .

## Optional TMDB Token

The app can use a TMDB API token to enrich posters and director information when stored database data is unavailable. Create `.streamlit/secrets.toml`:

```toml
TMDB_TOKEN = "your_tmdb_read_access_token"
```

Do not commit this file.

## Data Sources

The app prefers `cinemind.db` when it contains movies. If the database is unavailable, it loads:

- `tmdb_5000_movies.csv`
- `tmdb_5000_credits.csv`

To rebuild or expand the SQLite catalog, run:

```powershell
python tmdb_data_loader.py
```

## Project Files

- `app.py` - Streamlit interface.
- `movie_recommendation.py` - Loading, feature extraction, TF-IDF, and recommendations.
- `db.py` - SQLite database layer.
- `tmdb_data_loader.py` - TMDB data ingestion.
- `verify_upgrade.py` - Database verification utility.
