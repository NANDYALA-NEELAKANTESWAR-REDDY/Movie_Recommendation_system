"""Quick verification script for the CineMind AI upgrade."""
import movie_recommendation as mr

print("=" * 50)
print("VERIFICATION: CineMind AI")
print("=" * 50)
print(f"Data source    : {mr._data_source}")
print(f"Movies loaded  : {len(mr.movies):,}")
print(f"Genres count   : {len(mr.available_genres)}")
print(f"Genres (first8): {mr.available_genres[:8]}")
year_min = min(mr.release_years) if mr.release_years else "N/A"
year_max = max(mr.release_years) if mr.release_years else "N/A"
print(f"Year range     : {year_min} - {year_max}")

print()
print("--- Search test ---")
results = mr.search_movies("Spider")
if results is not None:
    print(f"Search 'Spider': {len(results)} results")
    for i, row in results.head(3).iterrows():
        print(f"  {row['title']} (id={row['id']})")
else:
    print("Search returned None")

print()
print("--- Recommendation test ---")
# Pick a movie we know is in the DB
test_title = results.iloc[0]["title"] if results is not None and len(results) > 0 else None

if test_title:
    recs = mr.recommend_movies(test_title, 3)
    print(f"Recommendations for '{test_title}': {len(recs)}")
    for r in recs:
        print(f"  - {r['title']} | score={r['score']:.4f} | rating={r['rating']}")
        print(f"    common: {r['common_features'][:2]}")
else:
    print("No test movie available")

print()
print("--- Duplicate ID check ---")
import db
import sqlite3
conn = sqlite3.connect(db.DB_PATH)
dupes = conn.execute(
    "SELECT COUNT(*) FROM (SELECT id FROM movies GROUP BY id HAVING COUNT(*) > 1)"
).fetchone()[0]
print(f"Duplicate IDs  : {dupes}")
conn.close()

print()
print("=" * 50)
print("ALL CHECKS COMPLETE")
print("=" * 50)
