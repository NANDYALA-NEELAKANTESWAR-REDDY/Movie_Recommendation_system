import streamlit as st
import movie_recommendation
import importlib
importlib.reload(movie_recommendation)
import requests
import re

# --------------------------------------------------
# PAGE CONFIG
# --------------------------------------------------

st.set_page_config(
    page_title="CineMind AI",
    page_icon="🎬",
    layout="wide"
)

# --------------------------------------------------
# CUSTOM CSS
# --------------------------------------------------

st.markdown("""
<style>

@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

* { font-family: 'Inter', sans-serif; }

.hero-title {
    font-size: 52px;
    font-weight: 800;
    background: linear-gradient(135deg, #e2e8f0 0%, #a78bfa 50%, #60a5fa 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.1;
    margin-bottom: 6px;
}

.hero-subtitle {
    font-size: 17px;
    color: #6b7280;
    margin-bottom: 30px;
    letter-spacing: 0.3px;
}

.section-divider {
    border: none;
    height: 1px;
    background: linear-gradient(to right, transparent, #374151, transparent);
    margin: 28px 0;
}

.filter-label {
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: #6b7280;
    margin-bottom: 12px;
}

.movie-card {
    padding: 24px;
    border-radius: 18px;
    background: linear-gradient(145deg, #0f172a 0%, #1a1f35 100%);
    border: 1px solid #1e2a45;
    margin-bottom: 24px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.35);
}

.selected-movie-card {
    padding: 24px;
    border-radius: 18px;
    background: linear-gradient(145deg, #1e1b4b 0%, #311b92 100%);
    border: 1px solid #6366f1;
    margin-bottom: 30px;
    box-shadow: 0 6px 30px rgba(99, 102, 241, 0.25);
}

.movie-title {
    font-size: 22px;
    font-weight: 700;
    color: #e2e8f0;
    margin-bottom: 4px;
}

.movie-rank {
    font-size: 12px;
    font-weight: 600;
    color: #6366f1;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 8px;
}

.meta-pill {
    display: inline-block;
    background: #1e293b;
    border: 1px solid #2d3f5c;
    border-radius: 20px;
    padding: 4px 12px;
    font-size: 12px;
    color: #94a3b8;
    margin: 3px 4px 3px 0;
}

.director-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: linear-gradient(135deg, #312e81, #1e1b4b);
    border: 1px solid #4338ca;
    border-radius: 10px;
    padding: 6px 14px;
    font-size: 13px;
    font-weight: 600;
    color: #a5b4fc;
    margin: 6px 6px 6px 0;
}

.cast-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: #0f2027;
    border: 1px solid #1e3a5f;
    border-radius: 10px;
    padding: 5px 12px;
    font-size: 12px;
    color: #7dd3fc;
    margin: 4px 4px 4px 0;
}

.feature-chip {
    display: inline-block;
    background: #172033;
    border: 1px solid #1e3a5f;
    border-radius: 8px;
    padding: 6px 12px;
    margin: 4px 4px 4px 0;
    font-size: 12.5px;
    color: #93c5fd;
}

</style>
""", unsafe_allow_html=True)

# --------------------------------------------------
# SIDEBAR
# --------------------------------------------------

with st.sidebar:
    st.markdown("### 🎬 CineMind AI")
    st.divider()

    _source = getattr(movie_recommendation, "_data_source", "csv")
    _count  = len(movie_recommendation.movies)

    if _source == "sqlite":
        st.success("🗄️ SQLite database active")
        st.metric("Movies available", f"{_count:,}")
        try:
            import db as _db
            _info = _db.db_info()
            st.caption(f"🕒 Last updated: {_info['last_updated'][:10] if _info['last_updated'] != 'Never' else 'Never'}")
            st.caption(f"📖 Last page fetched: {_info['last_ingestion_page']}")
        except Exception:
            pass
        with st.expander("ℹ️ Expand database"):
            st.markdown(
                "To download more movies, run:\n"
                "```\npython tmdb_data_loader.py\n```\n"
                "Edit `TARGET_MOVIES` in `tmdb_data_loader.py` "
                "to control how many movies to fetch."
            )
    else:
        st.info("📄 CSV dataset active")
        st.metric("Movies available", f"{_count:,}")
        with st.expander("ℹ️ Upgrade to larger dataset"):
            st.markdown(
                "Run the ingestion script to switch to SQLite:\n"
                "```\npython tmdb_data_loader.py\n```\n"
                "Restart the app afterwards to load the new database."
            )

    st.divider()
    st.markdown("<div class='filter-label'>Quick Tips</div>", unsafe_allow_html=True)
    st.caption("• Press **Enter** after typing to search instantly")
    st.caption("• Select a movie then click **Get AI Recommendations**")
    st.caption("• Use filters to narrow results by language, genre, year, rating")


# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------

if "matches" not in st.session_state:
    st.session_state.matches = None

if "recommendations" not in st.session_state:
    st.session_state.recommendations = None

if "selected_movie" not in st.session_state:
    st.session_state.selected_movie = None


# --------------------------------------------------
# HERO HEADER
# --------------------------------------------------

st.markdown('<div class="hero-title">🎬 CineMind AI</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="hero-subtitle">AI-powered recommendations across 62,000+ films — '
    'Hollywood, Bollywood &amp; World Cinema</div>',
    unsafe_allow_html=True
)
st.markdown('<hr class="section-divider">', unsafe_allow_html=True)


# --------------------------------------------------
# SEARCH SECTION — st.form so pressing Enter works
# --------------------------------------------------

st.markdown('<div class="filter-label">🔎 Search Movies</div>', unsafe_allow_html=True)

with st.form(key="search_form", clear_on_submit=False):
    movie_name = st.text_input(
        "Movie name",
        placeholder="Try Inception, RRR, Dangal, Parasite, Spider-Man...",
        label_visibility="collapsed"
    )
    search_submitted = st.form_submit_button(
        "🔍 Search",
        use_container_width=True
    )

if search_submitted:
    if movie_name.strip() == "":
        st.warning("Please enter a movie name.")
    else:
        with st.spinner("Searching..."):
            matches = movie_recommendation.search_movies(movie_name)
        st.session_state.matches = matches
        st.session_state.recommendations = None
        st.session_state.selected_movie = None


# --------------------------------------------------
# MOVIE SELECTION  +  FILTERS
# --------------------------------------------------

if st.session_state.matches is not None:

    matches = st.session_state.matches

    if matches is None or len(matches) == 0:
        st.warning("No movies found. Try a different name.")
    else:
        st.success(f"Found **{len(matches)}** matching movie(s).")

        movie_titles = matches["title"].tolist()
        selected_movie = st.selectbox("🎬 Select a movie", movie_titles)
        st.session_state.selected_movie = selected_movie

        # Divider + filter heading
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown("### 🎛️ Recommendation Filters")
        st.markdown(
            '<div class="filter-label">Narrow down your AI recommendations</div>',
            unsafe_allow_html=True
        )

        filter_col1, filter_col2, filter_col3 = st.columns(3)

        with filter_col1:
            selected_genre = st.selectbox(
                "🎭 Genre",
                ["All Genres"] + movie_recommendation.available_genres,
                key="selected_genre"
            )
            minimum_rating = st.slider(
                "⭐ Minimum Rating",
                min_value=0.0,
                max_value=10.0,
                value=0.0,
                step=0.5,
                key="minimum_rating"
            )

        with filter_col2:
            selected_lang_label = st.selectbox(
                "🌐 Language",
                ["All Languages"] + getattr(movie_recommendation, "available_languages", []),
                key="selected_language_label"
            )
            selected_year_label = st.selectbox(
                "📅 Release Year",
                ["All Years"] + movie_recommendation.release_years,
                key="selected_year"
            )

        with filter_col3:
            number_of_recommendations = st.selectbox(
                "🔢 Number of Results",
                [3, 5, 10, 15],
                index=1,
                key="number_of_recommendations"
            )

        selected_year = (
            None
            if selected_year_label == "All Years"
            else int(selected_year_label)
        )

        _lang_map = getattr(movie_recommendation, "_lang_label_to_code", {})
        selected_language_code = (
            None
            if selected_lang_label == "All Languages"
            else _lang_map.get(selected_lang_label, None)
        )

        # Divider before recommend button
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

        if st.button(
            "🎯 Get AI Recommendations",
            use_container_width=True,
            type="primary"
        ):
            with st.spinner("🤖 AI is analysing 62,000+ movies..."):
                recommendations = movie_recommendation.recommend_movies(
                    selected_movie,
                    number_of_recommendations,
                    None if selected_genre == "All Genres" else selected_genre,
                    minimum_rating,
                    selected_year,
                    selected_language=selected_language_code
                )
            st.session_state.recommendations = recommendations


# --------------------------------------------------
# TMDB HELPER (POSTER & DIRECTOR)
# --------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def get_movie_details_tmdb(movie_id, stored_poster_path=""):
    """Use the database poster first, then optionally enrich from TMDB."""
    poster_url = None
    director_name = None

    if stored_poster_path:
        poster_url = str(stored_poster_path).strip()
        if poster_url.startswith("/"):
            poster_url = "https://image.tmdb.org/t/p/w500" + poster_url
        elif not poster_url.startswith(("http://", "https://")):
            poster_url = "https://image.tmdb.org/t/p/w500/" + poster_url

    try:
        token = st.secrets.get("TMDB_TOKEN")
        # Posters may already exist in SQLite, but director data can still
        # require the credits request.
        if token and (not poster_url or not director_name):
            headers = {
                "Authorization": f"Bearer {token}",
                "accept": "application/json"
            }
            url = f"https://api.themoviedb.org/3/movie/{movie_id}?append_to_response=credits"
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                poster_path = data.get("poster_path")
                if poster_path:
                    poster_url = "https://image.tmdb.org/t/p/w500" + poster_path
                credits = data.get("credits", {})
                crew = credits.get("crew", [])
                for member in crew:
                    if member.get("job") == "Director":
                        director_name = member.get("name")
                        break
    except Exception:
        pass
    return poster_url, director_name


def _detokenise(token):
    """Convert CamelCase actor/director tokens back to 'First Last' readable names."""
    if not token:
        return ""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(token))


# --------------------------------------------------
# RECOMMENDATION RESULTS
# --------------------------------------------------

if st.session_state.recommendations is not None:

    recommendations = st.session_state.recommendations
    selected_movie_title = st.session_state.selected_movie

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # ----------------------------------------------
    # 1. DISPLAY SELECTED MOVIE CARD
    # ----------------------------------------------
    selected_info = movie_recommendation.get_movie_by_title(selected_movie_title)

    if selected_info:
        st.markdown('### 📌 Selected Movie Details')
        st.markdown('<div class="selected-movie-card">', unsafe_allow_html=True)
        st.markdown(f'<div class="movie-rank" style="color:#a5b4fc;">Selected Base Movie</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="movie-title">🎬 {selected_info["title"]}</div>', unsafe_allow_html=True)
        st.write("")

        poster_url, fetched_director = get_movie_details_tmdb(
            selected_info["id"], selected_info.get("poster_path", "")
        )
        director_display = selected_info.get("director", "").strip() or fetched_director or ""
        director_display = _detokenise(director_display).strip()

        p_col, d_col = st.columns([1, 3])
        with p_col:
            if poster_url:
                st.image(poster_url, use_container_width=True)
            else:
                st.markdown(
                    """<div style="height:220px;border-radius:12px;background:#1a1f35;
                    display:flex;align-items:center;justify-content:center;
                    color:#374151;font-size:13px;border:1px solid #1e2a45;">
                    No Poster</div>""",
                    unsafe_allow_html=True
                )

        with d_col:
            m1, m2, m3 = st.columns(3)
            with m1:
                st.metric("⭐ Rating", f'{selected_info["rating"]:.1f}/10')
            with m2:
                st.metric("📅 Release", selected_info["release_date"] or "—")
            with m3:
                lang = selected_info.get("original_language", "").upper()
                st.metric("🌐 Language", lang if lang else "—")

            st.write("")

            genres_list = selected_info["genres"].split() if selected_info["genres"] else []
            if genres_list:
                genres_html = "".join(
                    f'<span class="meta-pill">🎭 {g}</span>'
                    for g in genres_list
                )
                st.markdown(genres_html, unsafe_allow_html=True)

            if director_display:
                st.markdown(
                    f'<div class="director-badge">🎬 Director &nbsp;&middot;&nbsp; {director_display}</div>',
                    unsafe_allow_html=True
                )

            cast_tokens = (selected_info.get("cast", "") or "").split()
            if cast_tokens:
                cast_html = "".join(
                    f'<span class="cast-badge">👤 {_detokenise(actor)}</span>'
                    for actor in cast_tokens[:6]
                )
                st.markdown(cast_html, unsafe_allow_html=True)

            if selected_info["overview"]:
                st.write("")
                st.markdown(f'📝 **About:** {selected_info["overview"]}')

        st.markdown('</div>', unsafe_allow_html=True)

    # ----------------------------------------------
    # 2. DISPLAY RECOMMENDED MOVIES
    # ----------------------------------------------
    st.header("🎯 Recommended Movies")
    st.caption(f"Similar to **{selected_movie_title}**")

    active_genre  = st.session_state.get("selected_genre", "All Genres")
    active_lang   = st.session_state.get("selected_language_label", "All Languages")
    active_year   = st.session_state.get("selected_year", "All Years")
    active_rating = st.session_state.get("minimum_rating", 0.0)
    active_count  = st.session_state.get("number_of_recommendations", 5)

    st.caption(
        f"Filters: 🎭 {active_genre} | "
        f"🌐 {active_lang} | "
        f"⭐ Rating >= {active_rating:.1f} | "
        f"📅 Year: {active_year} | "
        f"🔢 Showing: {active_count}"
    )

    if not recommendations:
        st.warning("No movies matched your selected filters.")
        st.info("Try lowering the minimum rating or switching Language/Genre to All.")

    else:

        for i, movie in enumerate(recommendations, start=1):

            st.markdown('<div class="movie-card">', unsafe_allow_html=True)

            # Rank label + title
            st.markdown(f'<div class="movie-rank">#{i} Recommendation</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="movie-title">🎬 {movie["title"]}</div>', unsafe_allow_html=True)
            st.write("")

            poster_url, fetched_director = get_movie_details_tmdb(
                movie["id"], movie.get("poster_path", "")
            )
            director_display = movie.get("director", "").strip() or fetched_director or ""
            director_display = _detokenise(director_display).strip()

            poster_col, details_col = st.columns([1, 3])

            with poster_col:
                if poster_url:
                    st.image(poster_url, use_container_width=True)
                else:
                    st.markdown(
                        """<div style="height:220px;border-radius:12px;background:#1a1f35;
                        display:flex;align-items:center;justify-content:center;
                        color:#374151;font-size:13px;border:1px solid #1e2a45;">
                        No Poster</div>""",
                        unsafe_allow_html=True
                    )

            with details_col:

                # Metrics row
                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric("⭐ Rating", f'{movie["rating"]:.1f}/10')
                with m2:
                    st.metric("🎯 AI Score", f'{movie["score"]:.3f}')
                with m3:
                    st.metric("📅 Release", movie["release_date"] or "—")

                st.write("")

                # Genres as pills
                genres_list = movie["genres"].split() if movie["genres"] else []
                if genres_list:
                    genres_html = "".join(
                        f'<span class="meta-pill">🎭 {g}</span>'
                        for g in genres_list
                    )
                    st.markdown(genres_html, unsafe_allow_html=True)

                # Thin divider
                st.markdown(
                    '<hr class="section-divider" style="margin:12px 0;">',
                    unsafe_allow_html=True
                )

                # Director
                if director_display:
                    st.markdown(
                        f'<div class="director-badge">🎬 Director &nbsp;&middot;&nbsp; {director_display}</div>',
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(
                        '<div class="director-badge" style="opacity:0.4;">🎬 Director &middot; Unknown</div>',
                        unsafe_allow_html=True
                    )

                # Cast
                cast_tokens = (movie.get("cast", "") or "").split()
                if cast_tokens:
                    cast_html = "".join(
                        f'<span class="cast-badge">👤 {_detokenise(actor)}</span>'
                        for actor in cast_tokens[:6]
                    )
                    st.markdown(cast_html, unsafe_allow_html=True)

                st.write("")

                # Why recommended
                if movie["common_features"]:
                    st.markdown("**💡 Why AI recommended this:**")
                    chips_html = "".join(
                        f'<span class="feature-chip">✓ {feat}</span>'
                        for feat in movie["common_features"]
                    )
                    st.markdown(chips_html, unsafe_allow_html=True)

                st.write("")

                # Overview
                if movie["overview"]:
                    st.markdown(f'📝 **About:** {movie["overview"]}')

            st.markdown('</div>', unsafe_allow_html=True)
