"""Cache TTL per /bizbuysell/* endpoint (cache.py, keyed on the validated
params). Listings are added and re-priced daily, so search-shaped answers
live for hours and records for a day; reference lists for weeks.
"""
from datetime import timedelta

# Search pages: new listings land all day, price drops too; an hour keeps a
# browsing client consistent across pages without serving stale counts.
SEARCH_CACHE = timedelta(hours=1)
# Per-type counts move with the same cadence as the search.
COUNTS_CACHE = timedelta(hours=1)
# One row per listing id: the parsed listing page (price edits are rare
# within a day; a sold listing stays visible until the seller removes it).
LISTING_CACHE = timedelta(hours=12)
# Broker directory pages: profiles change rarely, the listing counts daily.
BROKERS_CACHE = timedelta(hours=12)
# One row per broker profile (typeahead + directory lookup = two upstream calls).
BROKER_CACHE = timedelta(hours=24)
# Franchise directory pages and brochures are marketing copy, edited rarely.
FRANCHISES_CACHE = timedelta(hours=12)
FRANCHISE_CACHE = timedelta(hours=24)
# The category tree and the county list are static site reference data.
CATEGORIES_CACHE = timedelta(days=7)
COUNTIES_CACHE = timedelta(days=30)
