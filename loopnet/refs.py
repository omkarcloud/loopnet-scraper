"""Reference resolvers + the slug tables for /loopnet/*.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair): each resolver takes a bare id OR any loopnet.com link for
the same record and raises ValueError with a user-facing message (RefField
turns it into a 400).

Identifier shapes (www.loopnet.com, captured 2026-11-07):
  * listing   /Listing/<slug>/<id>/           id = 6-9 digits; the bare
              /Listing/<id>/ form answers a 302 to the slug URL, and the
              redirect landing tends to be challenged, so a bare id is
              resolved to its canonical link through /service/mini-placards/
              (loopnet/fetch.py) before the page is fetched
  * broker    /commercial-real-estate-brokers/profile/<slug>/<id>[/<listingId>]
              id = 8 lower-case alphanumerics (8lybyl0b); the page is served
              WITHOUT a trailing slash (the slash form redirects into the
              challenge)
  * company   /company/<slug>/<id>/           id = 8 lower-case alphanumerics
  * property  /property/<slug>/<fips>-<parcel>/   the public record of a parcel
  * business  /biz/business-opportunity/<slug>/<listNumber>/  = BizBuySell
              listing <listNumber> (bizbuysell/refs.py resolves it)

Search URLs: /search/<type-slug>/<geo-slug>/for-sale|for-lease|auctions/<page>/
with the filters as query params (min-price, max-price, price-type=sf,
min-cap-rate, max-cap-rate, min-size, max-size, min-year-built, keyword,
min-rent, max-rent, sort=newest), 40 cards a page, 750 results at most
(page 20 redirects to page 1). Geo slugs come from the site's own typeahead
(geo_slug): "austin-tx" (city), "los-angeles-county-ca" (county), "tx"
(state), "los-angeles-ca-90064" (ZIP), "usa".
"""
import re
from urllib.parse import parse_qs, urlparse

SITE = "https://www.loopnet.com"

_LISTING_ID_RE = re.compile(r"^[0-9]{5,10}$")
_LISTING_LINK_RE = re.compile(r"/listing/(?:([A-Za-z0-9._~%-]+)/)?([0-9]{5,10})/?", re.I)
_KEY_RE = re.compile(r"^[a-z0-9]{6,12}$", re.I)
_BROKER_LINK_RE = re.compile(r"/commercial-real-estate-brokers/profile/([A-Za-z0-9._~%-]+)/([a-z0-9]{6,12})", re.I)
_COMPANY_LINK_RE = re.compile(r"/company/([A-Za-z0-9._~%-]+)/([a-z0-9]{6,12})", re.I)
_PARCEL_RE = re.compile(r"^[0-9]{3,6}-[A-Za-z0-9._-]{2,40}$")
_PROPERTY_LINK_RE = re.compile(r"/property/([A-Za-z0-9._~%-]+)/([0-9]{3,6}-[A-Za-z0-9._-]{2,40})/?", re.I)
_SEARCH_LINK_RE = re.compile(r"/search/([a-z0-9-]+)/([a-z0-9-]+)/(for-sale|for-lease|auctions)/?([0-9]+)?/?", re.I)
_LATLNG_RE = re.compile(r"^\s*(-?[0-9]{1,2}(?:\.[0-9]+)?)\s*,\s*(-?[0-9]{1,3}(?:\.[0-9]+)?)\s*$")


def _host_is_site(url):
    host = (urlparse(url).hostname or "").lower()
    return host == "loopnet.com" or host.endswith(".loopnet.com")


def _as_url(value):
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return "https:" + value
    if value.startswith(("www.loopnet.com", "loopnet.com")):
        return "https://" + value
    return None


def _link_match(value, pattern, what, example):
    """A loopnet.com link -> the pattern's groups, or a user-facing error."""
    url = _as_url(value)
    if url is None:
        return None
    if not _host_is_site(url):
        raise ValueError("Must be a loopnet.com link.")
    match = pattern.search(urlparse(url).path)
    if not match:
        raise ValueError(f"Must be a loopnet.com {what} link ({example}).")
    return match.groups()


# ---- listings ---------------------------------------------------------------------

def resolve_listing(value):
    """Bare listing id or a loopnet.com listing link -> {"id", "slug"}
    (slug None for a bare id; the fetcher resolves the canonical link)."""
    value = (value or "").strip()
    if _LISTING_ID_RE.match(value):
        return {"id": int(value), "slug": None}
    groups = _link_match(value, _LISTING_LINK_RE, "listing",
                         f"{SITE}/Listing/<address>/<id>/")
    if groups:
        slug, listing_id = groups
        return {"id": int(listing_id), "slug": slug or None}
    raise ValueError("Must be a LoopNet listing id (e.g. 29122043) or a listing link.")


def listing_link(listing_id, slug=None):
    if slug:
        return f"{SITE}/Listing/{slug}/{listing_id}/"
    return f"{SITE}/Listing/{listing_id}/"


# ---- brokers ----------------------------------------------------------------------

def resolve_broker(value):
    """Bare profile id (8lybyl0b) or a broker profile link -> {"id", "slug"}."""
    value = (value or "").strip()
    groups = _link_match(value, _BROKER_LINK_RE, "broker profile",
                         f"{SITE}/commercial-real-estate-brokers/profile/<name>/<id>")
    if groups:
        slug, broker_id = groups
        return {"id": broker_id.lower(), "slug": slug.lower()}
    if _KEY_RE.match(value):
        return {"id": value.lower(), "slug": None}
    raise ValueError("Must be a LoopNet broker id (e.g. 8lybyl0b) or a broker profile link.")


def broker_link(broker_id, slug=None):
    # no trailing slash: the slash form redirects into the Akamai challenge
    return f"{SITE}/commercial-real-estate-brokers/profile/{slug or 'profile'}/{broker_id}"


# ---- companies --------------------------------------------------------------------

def resolve_company(value):
    """Bare company id (0r9nt33l) or a /company/ link -> {"id", "slug"}."""
    value = (value or "").strip()
    groups = _link_match(value, _COMPANY_LINK_RE, "company", f"{SITE}/company/<name>/<id>/")
    if groups:
        slug, company_id = groups
        return {"id": company_id.lower(), "slug": slug.lower()}
    if _KEY_RE.match(value):
        return {"id": value.lower(), "slug": None}
    raise ValueError("Must be a LoopNet company id (e.g. 0r9nt33l) or a company page link.")


def company_link(company_id, slug=None, page=1):
    path = f"{SITE}/company/{slug or 'company'}/{company_id}/"
    return path + (f"{page}/" if page and page > 1 else "")


# ---- property records -------------------------------------------------------------

def resolve_property(value):
    """A property record link, or its bare "<fips>-<parcel>" id -> {"id", "slug"}."""
    value = (value or "").strip()
    groups = _link_match(value, _PROPERTY_LINK_RE, "property record",
                         f"{SITE}/property/<address>/<fips>-<parcel>/")
    if groups:
        slug, record_id = groups
        return {"id": record_id, "slug": slug.lower()}
    if _PARCEL_RE.match(value):
        return {"id": value, "slug": None}
    raise ValueError("Must be a LoopNet property record link "
                     f"({SITE}/property/<address>/<fips>-<parcel>/) or its <fips>-<parcel> id.")


def property_link(record_id, slug=None):
    return f"{SITE}/property/{slug or 'property'}/{record_id}/"


# ---- businesses (BizBuySell) ------------------------------------------------------

def resolve_business(value):
    """A BizBuySell listing number or a loopnet.com /biz/ (or bizbuysell.com)
    listing link -> {"id", "slug"} (bizbuysell/refs.py accepts both hosts)."""
    from bizbuysell import refs as biz_refs
    try:
        return biz_refs.resolve_listing(value)
    except ValueError:
        raise ValueError("Must be a business listing number (e.g. 2573303) or a loopnet.com "
                         f"/biz/ listing link ({SITE}/biz/business-opportunity/<name>/<id>/).")


def business_link(listing_id, slug=None):
    return f"{SITE}/biz/business-opportunity/{slug or 'business'}/{listing_id}/"


# ---- search -----------------------------------------------------------------------

LISTING_TYPES = {"sale": "for-sale", "lease": "for-lease", "auction": "auctions"}
LISTING_TYPE_BY_SEGMENT = {v: k for k, v in LISTING_TYPES.items()}

# Public value -> the site's search path segment: its own SEO slugs, read
# from the site's link footer and verified live on 2026-11-07 (a slug the
# site does not pair with a listing type answers HTTP 404 -> a 404 here).
# "all" is the unfiltered commercial-real-estate search.
PROPERTY_TYPES = {
    "all": "commercial-real-estate",
    "office": "office-space",
    "office-building": "office-buildings",
    "retail": "retail-space",
    "retail-building": "retail-properties",
    "industrial": "industrial-properties",
    "industrial-space": "industrial-space",
    "warehouse": "warehouses",
    "flex": "flex-space",
    "land": "land",
    "residential-land": "residential-land",
    "farm": "farms",
    "multifamily": "multifamily-properties",
    "apartment": "apartment-buildings",
    "residential-income": "residential-income-properties",
    "hospitality": "hospitality-properties",
    "hotel": "hotels",
    "motel": "motels",
    "specialty": "specialty-properties",
    "restaurant": "restaurants",
    "shopping-center": "shopping-centers",
    "strip-mall": "strip-malls",
    "storefront": "storefront-properties",
    "health-care": "health-care-facilities",
    "medical": "medical-offices",
    "senior-housing": "senior-housing-facilities",
    "sports-entertainment": "sports-entertainment-properties",
    "coworking": "coworking-space",
    "mixed-use": "mixed-use-properties",
    "self-storage": "self-storage-facilities",
    "data-center": "data-centers",
    "telecom": "telecom-and-call-centers",
    "auto-shop": "auto-shops",
    "car-wash": "car-washes",
    "gas-station": "gas-stations",
    "church": "churches",
    "golf-course": "golf-courses-and-driving-ranges",
    "mobile-home-park": "mobile-home-parks",
    "parking": "parking-lots-and-garages",
}
PROPERTY_TYPE_BY_SLUG = {v: k for k, v in PROPERTY_TYPES.items()}

SORTS = {"default": None, "newest": "newest"}

# The 750-result cap every search carries (gState as.mrc), 40 cards a page.
SEARCH_PAGE_SIZE = 40
MAX_RESULTS = 750
MAX_SEARCH_PAGE = 19

# The query params the search page honours (verified on the gState filters
# 2026-11-07); a sale search reads `min-price` / `max-price` as the sale
# price, a lease search as the rate (with price-type=sf, $/SF/yr).
FILTER_PARAMS = {
    "min_price": "min-price", "max_price": "max-price",
    "min_rent": "min-rent", "max_rent": "max-rent",
    "min_size": "min-size", "max_size": "max-size",
    "min_cap_rate": "min-cap-rate", "max_cap_rate": "max-cap-rate",
    "min_year_built": "min-year-built",
    "keyword": "keyword",
}


def parse_lat_lng(value):
    """"34.05,-118.24" -> (lat, lng) or None."""
    match = _LATLNG_RE.match(value or "")
    if not match:
        return None
    lat, lng = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def parse_search_link(value):
    """A pasted loopnet.com search link -> {"property_type_slug", "geo_slug",
    "listing_type", "page", "params"} or None when `value` is not a link."""
    url = _as_url((value or "").strip())
    if url is None:
        return None
    if not _host_is_site(url):
        raise ValueError("Must be a loopnet.com search link.")
    parsed = urlparse(url)
    match = _SEARCH_LINK_RE.search(parsed.path)
    if not match:
        raise ValueError("Must be a loopnet.com search link "
                         f"({SITE}/search/<property type>/<place>/for-sale/).")
    type_slug, geo_slug, segment, page = match.groups()
    params = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}
    return {"property_type_slug": type_slug.lower(), "geo_slug": geo_slug.lower(),
            "listing_type": LISTING_TYPE_BY_SEGMENT[segment.lower()],
            "page": int(page) if page else 1, "params": params}


def slugify(text):
    text = re.sub(r"[^a-z0-9]+", "-", (text or "").lower())
    return text.strip("-")


# Typeahead GeographyType codes (services/geography/lookup, read from the
# rows on 2026-11-07: 1 state "Texas", 2 city "Austin, TX", 3 postal code
# "90064, Los Angeles, CA", 5 a listed property, 9 a county "Texas County,
# MO" (Address.County set) or a point of interest, 14 a building park).
GEO_TYPES = {0: "header", 1: "state", 2: "city", 3: "postal_code", 4: "county", 5: "property",
             6: "country", 7: "market", 8: "submarket", 9: "county", 10: "neighborhood",
             11: "state", 12: "address", 13: "market", 14: "building_park", 15: "country"}
SEARCHABLE_GEO_TYPES = ("state", "city", "postal_code", "county", "country", "neighborhood", "market", "submarket")

# The search page's own gState `sc.geography.t` codes are a DIFFERENT table
# from the typeahead's (read from saved search pages on 2026-11-07: 2 the
# zip "los-angeles-ca-90064", 3 a city "austin-tx" / "new-york-ny", 10 the
# county "los-angeles-county-ca", 11 the state "tx", 15 the country "usa").
SEARCH_GEO_TYPES = {2: "postal_code", 3: "city", 10: "county", 11: "state", 15: "country"}


def geo_type(row):
    kind = GEO_TYPES.get(row.get("GeographyType"))
    address = row.get("Address") or {}
    if kind == "county" and not address.get("County"):
        return "point_of_interest"
    return kind


def geo_slug(row):
    """The search-path slug of a typeahead row, as the site builds it:
    "Austin, TX" -> austin-tx, "Texas County, MO" -> texas-county-mo,
    "90064, Los Angeles, CA" -> los-angeles-ca-90064, a state its code
    ("tx"), the country "usa"."""
    kind = geo_type(row)
    address = row.get("Address") or {}
    display = (row.get("Display") or "").strip()
    if kind == "country":
        return "usa" if (address.get("CountryCode") or "US") == "US" else slugify(display)
    if kind == "state":
        return (address.get("State") or slugify(display)).lower()
    if kind == "postal_code" and address.get("PostalCode"):
        return slugify(f"{address.get('City') or ''} {address.get('State') or ''} {address['PostalCode']}")
    if kind == "county" and address.get("County"):
        return slugify(f"{address['County']} County {address.get('State') or ''}")
    if kind == "city" and address.get("City"):
        return slugify(f"{address['City']} {address.get('State') or ''}")
    return slugify(display)


def search_path(property_type_slug, geo_slug_value, listing_type, page=1, params=None):
    segment = LISTING_TYPES[listing_type]
    path = f"/search/{property_type_slug}/{geo_slug_value}/{segment}/"
    if page and page > 1:
        path += f"{page}/"
    query = {k: v for k, v in (params or {}).items() if v not in (None, "", False)}
    if query:
        from urllib.parse import urlencode
        path += "?" + urlencode(query)
    return path


# ---- broker directory -------------------------------------------------------------

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_STATE_BY_NAME = {name.lower(): code for code, name in US_STATES.items()}
_STATE_BY_NAME.update({code.lower(): code for code in US_STATES})

BROKER_TYPES = {"landlord_rep": "LandlordRep", "tenant_rep": "TenantRep", "investment_sale": "InvestmentSale"}
BROKER_SORTS = {"default": None, "name_asc": "1", "name_desc": "2"}
BROKER_PAGE_SIZE = 10
_DIRECTORY_LINK_RE = re.compile(r"/commercial-real-estate-brokers/united-states/([a-z]{2})(?:/([a-z0-9-]+))?(?:/([0-9]+))?/?", re.I)


def resolve_broker_location(value):
    """"TX" / "Texas" / "Austin, TX" / a directory link -> {"state", "city"}
    (city = the site's own slug, e.g. "los-angeles")."""
    value = " ".join((value or "").split())
    url = _as_url(value)
    if url:
        if not _host_is_site(url):
            raise ValueError("Must be a loopnet.com broker directory link.")
        match = _DIRECTORY_LINK_RE.search(urlparse(url).path)
        if not match:
            raise ValueError("Must be a loopnet.com broker directory link "
                             f"({SITE}/commercial-real-estate-brokers/united-states/<st>/<city>/).")
        state, city, _ = match.groups()
        return {"state": state.upper(), "city": city.lower() if city else None}
    city, state = None, value
    if "," in value:
        city, state = [part.strip() for part in value.rsplit(",", 1)]
    code = _STATE_BY_NAME.get(state.lower())
    if not code:
        raise ValueError("Must be a US state (TX, Texas), a 'City, ST' pair (Austin, TX) or a "
                         "loopnet.com broker directory link.")
    return {"state": code, "city": slugify(city) if city else None}


def broker_directory_path(state, city=None, page=1, sort=None):
    path = f"/commercial-real-estate-brokers/united-states/{state.lower()}/"
    if city:
        path += f"{city}/"
    if page and page > 1:
        path += f"{page}/"
    if sort:
        path += f"?sorting={sort}"
    return path
