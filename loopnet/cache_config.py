"""Cache TTL per /loopnet/* endpoint (cache.py, keyed on the validated
params). Every page costs one use of an Akamai identity that serves
~60 pages before a box re-mint (loopnet/fetch.py), so the cache is also
the identity budget: nothing is fetched twice within the TTL.
"""
from datetime import timedelta

# Search pages: listings are added / repriced daily; an hour keeps a paging
# client on one consistent result set.
SEARCH_CACHE = timedelta(hours=1)
# A listing page moves with its "Last Updated" stamp (days apart); 6 h.
LISTING_CACHE = timedelta(hours=6)
# Typeahead rows are the site's geography table: a day.
AUTOCOMPLETE_CACHE = timedelta(hours=24)
# Broker directory / search pages and profiles change with hires: 12 h.
BROKERS_CACHE = timedelta(hours=12)
BROKER_CACHE = timedelta(hours=12)
# A company page lists its 20 newest listings per page: 6 h.
COMPANY_CACHE = timedelta(hours=6)
# Public parcel records move once a tax year: 7 days.
PROPERTY_CACHE = timedelta(days=7)
# Traffic counts are annual AADT figures: 7 days.
TRAFFIC_CACHE = timedelta(days=7)
# Businesses for sale (BizBuySell data): same cadence as that scraper.
BUSINESSES_CACHE = timedelta(hours=6)
BUSINESS_CACHE = timedelta(hours=12)
