"""Reference resolvers + the slug / id tables for /bizbuysell/*.

ONE param per input (tripadvisor QueryOrIdField convention): `company`
accepts a bare listing id OR any bizbuysell.com listing link; `broker` a
profile id OR a broker profile link; `franchise` a slug OR a franchise
link. Resolvers raise ValueError with a user-facing message (RefField turns
it into a 400).

Identifier shapes (bizbuysell.com, captured 2026-10-30):
  * listing    /business-opportunity/<slug>/<listNumber>/   listNumber = 6-8 digits
  * broker     /business-broker/<name-slug>/<company-slug>/<brokerProfileId>/
  * franchise  /franchise-for-sale/<slug>/   (the franchise search answers
               LoopNet stubs "biz/franchise-for-sale/<slug>" for the same page)

The tables below are the site's own ids, read from its JSON on 2026-10-30:
  * STATES      api/Resource/GetStatesByCountry (51 US rows) + the Canadian
                provinces the search accepts with countryCode "CA"
  * CATEGORIES  the 20 top-level rows of api/Resource/GetBfsCategories
                (siteCategoryId is what the search criteria's `categories`
                takes; sub-categories are accepted by id, see
                /bizbuysell/categories/list)
  * FRANCHISE_CATEGORIES  the 28-row categoryHierarchy of the franchise
                search (siteCategoryId -> criteria `bbsCategories`)
  * LISTING_TYPES / SORTS  the search criteria's listingTypeIds and sortList
                enums (sortField 40 = asking price, 50 = cash flow, 60 =
                listing date; sortDirection 10 asc / 20 desc)
"""
import re
from urllib.parse import urlparse

SITE = "https://www.bizbuysell.com"
IMAGE_HOST = "https://images.bizbuysell.com"

SITE_ID = 20        # BizBuySell (the BFF also serves BizQuest = 10, LoopNet = 30)
LANGUAGE_ID = 10    # English

_LISTING_ID_RE = re.compile(r"^[0-9]{5,9}$")
_LISTING_LINK_RE = re.compile(r"/business-opportunity/(?:([A-Za-z0-9._~-]+)/)?([0-9]{5,9})/?", re.I)
_BROKER_ID_RE = re.compile(r"^[0-9]{1,8}$")
_BROKER_LINK_RE = re.compile(r"/business-broker/([A-Za-z0-9._~-]+)/([A-Za-z0-9._~-]+)/([0-9]{1,8})/?", re.I)
_FRANCHISE_LINK_RE = re.compile(r"/franchise-for-sale/([A-Za-z0-9._~-]+)/?", re.I)
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]*$")


def _host_is_site(value):
    host = (urlparse(value).hostname or "").lower()
    return host == "bizbuysell.com" or host.endswith(".bizbuysell.com") or host.endswith(".loopnet.com")


def _as_url(value):
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("www.") or value.startswith("bizbuysell.com"):
        return "https://" + value
    return None


# ---- listings ------------------------------------------------------------------

def resolve_listing(value):
    """Bare listing id or a bizbuysell.com listing link -> {"id", "slug"}
    (slug None for a bare id; the fetcher then resolves it from the site's
    own 301)."""
    value = (value or "").strip()
    if _LISTING_ID_RE.match(value):
        return {"id": int(value), "slug": None}
    url = _as_url(value)
    if url:
        if not _host_is_site(url):
            raise ValueError("Must be a bizbuysell.com link.")
        match = _LISTING_LINK_RE.search(urlparse(url).path)
        if match:
            slug, listing_id = match.groups()
            return {"id": int(listing_id), "slug": (slug or None)}
        raise ValueError("Must be a bizbuysell.com listing link "
                         "(https://www.bizbuysell.com/business-opportunity/<name>/<id>/).")
    raise ValueError("Must be a BizBuySell listing id (e.g. 2548034) or a listing link.")


def listing_link(listing_id, slug=None):
    if slug:
        return f"{SITE}/business-opportunity/{slug}/{listing_id}/"
    return f"{SITE}/business-opportunity/x/{listing_id}/"


# ---- brokers -------------------------------------------------------------------

def resolve_broker(value):
    """Bare profile id or a broker profile link -> {"id", "name", "company"}
    (name / company slugs None for a bare id)."""
    value = (value or "").strip()
    if _BROKER_ID_RE.match(value):
        return {"id": int(value), "name": None, "company": None}
    url = _as_url(value)
    if url:
        if not _host_is_site(url):
            raise ValueError("Must be a bizbuysell.com link.")
        match = _BROKER_LINK_RE.search(urlparse(url).path)
        if match:
            name, company, broker_id = match.groups()
            return {"id": int(broker_id), "name": name.lower(), "company": company.lower()}
        raise ValueError("Must be a bizbuysell.com broker profile link "
                         "(https://www.bizbuysell.com/business-broker/<name>/<company>/<id>/).")
    raise ValueError("Must be a BizBuySell broker profile id (e.g. 15309) or a profile link.")


def broker_link(path_or_url):
    if not path_or_url:
        return None
    return path_or_url if path_or_url.startswith("http") else SITE + path_or_url


# ---- franchises ----------------------------------------------------------------

def resolve_franchise(value):
    """Franchise slug or a bizbuysell.com / LoopNet franchise link -> slug."""
    value = (value or "").strip().rstrip("/")
    url = _as_url(value)
    if url:
        if not _host_is_site(url):
            raise ValueError("Must be a bizbuysell.com link.")
        match = _FRANCHISE_LINK_RE.search(urlparse(url).path)
        if match:
            return match.group(1).lower()
        raise ValueError("Must be a bizbuysell.com franchise link "
                         "(https://www.bizbuysell.com/franchise-for-sale/<name>/).")
    match = _FRANCHISE_LINK_RE.search("/" + value.lstrip("/") + "/")
    if match and "/" in value:
        return match.group(1).lower()
    if _SLUG_RE.match(value) and "/" not in value:
        return value.lower()
    raise ValueError("Must be a BizBuySell franchise slug (e.g. lawn-doctor-home-services-franchise) "
                     "or a franchise link.")


def franchise_link(slug):
    return f"{SITE}/franchise-for-sale/{slug}/" if slug else None


def franchise_slug_from_stub(stub):
    """The franchise search answers LoopNet stubs ("biz/franchise-for-sale/<slug>")
    for pages that live at bizbuysell.com/franchise-for-sale/<slug>/."""
    if not stub:
        return None
    match = _FRANCHISE_LINK_RE.search("/" + stub.strip("/") + "/")
    return match.group(1).lower() if match else None


# ---- states / provinces ---------------------------------------------------------

# code -> (country, name, seo slug). US rows from api/Resource/GetStatesByCountry;
# Canadian provinces answer the same criteria shape with countryCode "CA"
# (Ontario: 288 listings on 2026-10-31).
STATES = {
    "AK": ("US", "Alaska", "alaska"), "AL": ("US", "Alabama", "alabama"), "AR": ("US", "Arkansas", "arkansas"),
    "AZ": ("US", "Arizona", "arizona"), "CA": ("US", "California", "california"), "CO": ("US", "Colorado", "colorado"),
    "CT": ("US", "Connecticut", "connecticut"), "DC": ("US", "District of Columbia", "district-of-columbia"),
    "DE": ("US", "Delaware", "delaware"), "FL": ("US", "Florida", "florida"), "GA": ("US", "Georgia", "georgia"),
    "HI": ("US", "Hawaii", "hawaii"), "IA": ("US", "Iowa", "iowa"), "ID": ("US", "Idaho", "idaho"),
    "IL": ("US", "Illinois", "illinois"), "IN": ("US", "Indiana", "indiana"), "KS": ("US", "Kansas", "kansas"),
    "KY": ("US", "Kentucky", "kentucky"), "LA": ("US", "Louisiana", "louisiana"), "MA": ("US", "Massachusetts", "massachusetts"),
    "MD": ("US", "Maryland", "maryland"), "ME": ("US", "Maine", "maine"), "MI": ("US", "Michigan", "michigan"),
    "MN": ("US", "Minnesota", "minnesota"), "MO": ("US", "Missouri", "missouri"), "MS": ("US", "Mississippi", "mississippi"),
    "MT": ("US", "Montana", "montana"), "NC": ("US", "North Carolina", "north-carolina"), "ND": ("US", "North Dakota", "north-dakota"),
    "NE": ("US", "Nebraska", "nebraska"), "NH": ("US", "New Hampshire", "new-hampshire"), "NJ": ("US", "New Jersey", "new-jersey"),
    "NM": ("US", "New Mexico", "new-mexico"), "NV": ("US", "Nevada", "nevada"), "NY": ("US", "New York", "new-york"),
    "OH": ("US", "Ohio", "ohio"), "OK": ("US", "Oklahoma", "oklahoma"), "OR": ("US", "Oregon", "oregon"),
    "PA": ("US", "Pennsylvania", "pennsylvania"), "RI": ("US", "Rhode Island", "rhode-island"), "SC": ("US", "South Carolina", "south-carolina"),
    "SD": ("US", "South Dakota", "south-dakota"), "TN": ("US", "Tennessee", "tennessee"), "TX": ("US", "Texas", "texas"),
    "UT": ("US", "Utah", "utah"), "VA": ("US", "Virginia", "virginia"), "VT": ("US", "Vermont", "vermont"),
    "WA": ("US", "Washington", "washington"), "WI": ("US", "Wisconsin", "wisconsin"), "WV": ("US", "West Virginia", "west-virginia"),
    "WY": ("US", "Wyoming", "wyoming"),
    "AB": ("CA", "Alberta", "alberta"), "BC": ("CA", "British Columbia", "british-columbia"),
    "MB": ("CA", "Manitoba", "manitoba"), "NB": ("CA", "New Brunswick", "new-brunswick"),
    "NL": ("CA", "Newfoundland and Labrador", "newfoundland-and-labrador"), "NS": ("CA", "Nova Scotia", "nova-scotia"),
    "NT": ("CA", "Northwest Territories", "northwest-territories"), "NU": ("CA", "Nunavut", "nunavut"),
    "ON": ("CA", "Ontario", "ontario"), "PE": ("CA", "Prince Edward Island", "prince-edward-island"),
    "QC": ("CA", "Quebec", "quebec"), "SK": ("CA", "Saskatchewan", "saskatchewan"), "YT": ("CA", "Yukon", "yukon"),
}

_STATE_BY_NAME = {}
for _code, (_country, _name, _slug) in STATES.items():
    _STATE_BY_NAME[_code.lower()] = _code
    _STATE_BY_NAME[_name.lower()] = _code
    _STATE_BY_NAME[_slug] = _code


def resolve_state(value):
    """"TX" / "texas" / "Texas" -> "TX" (US states, DC, Canadian provinces)."""
    key = " ".join((value or "").split()).lower()
    code = _STATE_BY_NAME.get(key) or _STATE_BY_NAME.get(key.replace(" ", "-"))
    if not code:
        raise ValueError(f"'{value}' is not a US state / Canadian province name or code (TX, Texas, ON, ...).")
    return code


def state_location(code):
    """The minimal `locations[]` object the search / broker criteria accept
    for a state (verified 2026-10-31: countryCode + stateCode is enough)."""
    country, name, slug = STATES[code]
    return {"geoType": 20, "countryCode": country, "stateCode": code, "regionName": name,
            "regionNameSeo": slug, "displayName": name}


def county_location(county):
    """A county row from api/Resource/GetCountiesByRegion -> the `locations[]`
    object (countyId is the field the search keys on)."""
    return {"geoType": 40, "countryCode": county.get("countryCode") or "US", "stateCode": county.get("stateCode"),
            "regionName": county.get("regionName"), "regionNameSeo": county.get("regionNameSeo"),
            "displayName": county.get("displayName"), "countyId": county.get("countyId"),
            "legacyRegionId": county.get("legacyRegionId"), "regionId": county.get("regionId")}


def normalize_county(name):
    """"los angeles county" / "Los Angeles" / "los-angeles-county" -> "los angeles"."""
    key = " ".join((name or "").replace("-", " ").split()).lower()
    for suffix in (" county", " parish", " borough", " census area", " municipality", " city and borough"):
        if key.endswith(suffix):
            key = key[: -len(suffix)]
            break
    return key


# ---- business categories (search criteria `categories` = siteCategoryId) --------

CATEGORIES = (
    (88, "Agriculture", "agriculture-businesses"),
    (136, "Automotive & Boat", "automotive-and-boat-businesses"),
    (141, "Beauty & Personal Care", "beauty-and-personal-care-businesses"),
    (81, "Building & Construction", "building-and-construction-businesses"),
    (89, "Communication & Media", "communication-and-media-businesses"),
    (27, "Education & Children", "education-and-child-related-businesses"),
    (22, "Entertainment & Recreation", "entertainment-and-recreation-businesses"),
    (118, "Financial Services", "financial-services-businesses"),
    (31, "Health Care & Fitness", "health-care-and-fitness-businesses"),
    (57, "Manufacturing", "manufacturing-businesses"),
    (92, "Non-Classifiable Establishments", "all-non-classifiable-establishments"),
    (115, "Online & Technology", "online-and-technology-businesses"),
    (188, "Pet Services", "pet-service-businesses"),
    (17, "Restaurants & Food", "restaurants-and-food-businesses"),
    (1, "Retail", "retail-businesses"),
    (20, "Service Businesses", "service-businesses"),
    (30, "Transportation & Storage", "transportation-and-storage-businesses"),
    (206, "Travel", "travel-businesses"),
    (78, "Wholesale & Distributors", "wholesale-and-distribution-businesses"),
)

# the franchise search's categoryHierarchy (siteCategoryId -> `bbsCategories`)
FRANCHISE_CATEGORIES = (
    (1, "Automotive", "automotive-franchise"), (8, "Beauty & Fitness", "beauty-and-fitness-franchise"),
    (2, "Business Opportunities", "business-opportunities-franchise"), (3, "Business Services", "business-services-franchise"),
    (4, "Child Related", "child-related-franchise"), (5, "Cleaning & Maintenance", "cleaning-and-maintenance-franchise"),
    (6, "Computer & Internet", "computer-and-internet-franchise"), (22, "Education", "education-franchise"),
    (23, "Green", "green-franchise"), (24, "Health & Senior Care", "health-and-senior-care-franchise"),
    (13, "High Capital Franchises", "high-capital-franchise"), (14, "Home Based Businesses", "home-based-businesses-franchise"),
    (9, "Home Services", "home-services-franchise"), (19, "Hot Franchises", "hot-franchises"),
    (15, "Low Cost Franchises", "low-cost-franchise"), (29, "Master Franchise", "master-franchises"),
    (25, "Mobile", "mobile-franchise"), (28, "Multi-Unit", "multi-unit-franchises"),
    (26, "Pet", "pet-franchise"), (7, "Restaurant & Food", "food-and-restaurant-franchise"),
    (10, "Retail Franchises", "retail-franchise"), (27, "SBA Approved", "sba-approved-franchise"),
    (11, "Sports & Recreation", "sports-and-recreation-franchise"), (12, "Travel & Lodging", "travel-and-lodging-franchise"),
    (20, "Veteran's Franchises", "veterans-franchise"),
)


def _category_resolver(table, what):
    by_key = {}
    for cat_id, name, slug in table:
        by_key[str(cat_id)] = cat_id
        by_key[name.lower()] = cat_id
        by_key[slug] = cat_id
        by_key[name.lower().replace("&", "and")] = cat_id

    def resolve(value):
        key = " ".join((value or "").split()).lower()
        if key.isdigit():
            return int(key)   # any id, sub-categories included (/categories/list)
        found = by_key.get(key) or by_key.get(key.replace(" ", "-")) or by_key.get(key.replace("-", " "))
        if found is None:
            names = ", ".join(name for _, name, _ in table)
            raise ValueError(f"Unknown {what} '{value}'. Use an id from /bizbuysell/categories/list or one of: {names}.")
        return found
    return resolve


resolve_category = _category_resolver(CATEGORIES, "category")
resolve_franchise_category = _category_resolver(FRANCHISE_CATEGORIES, "franchise category")

CATEGORY_NAMES = {cat_id: name for cat_id, name, _ in CATEGORIES}
FRANCHISE_CATEGORY_NAMES = {cat_id: name for cat_id, name, _ in FRANCHISE_CATEGORIES}

# ---- enums ----------------------------------------------------------------------

LISTING_TYPES = {"established": 40, "asset_sale": 30, "real_estate": 80, "startup": 20}
LISTING_TYPE_NAMES = {40: "established", 30: "asset_sale", 80: "real_estate", 20: "startup", 90: "auction"}

# public sort -> the criteria's sortList (None = the site's relevance order)
SORTS = {
    "relevance": None,
    "newest": [{"sortField": 60, "sortDirection": 20}],
    "price_asc": [{"sortField": 40, "sortDirection": 10}],
    "price_desc": [{"sortField": 40, "sortDirection": 20}],
    "cash_flow_desc": [{"sortField": 50, "sortDirection": 20}],
    "cash_flow_asc": [{"sortField": 50, "sortDirection": 10}],
}

# the site never pages past 10,000 results (total is clamped there)
MAX_RESULTS = 10000

# franchise fee rows (vmFranchiseFeeLst.feeTypeId), named from the public brochure
FRANCHISE_FEE_TYPES = {10: "franchise_fee", 20: "ad_fund_fee", 30: "royalty_fee", 40: "liquid_capital"}
# brochure sections (displayComponents.componentTypeId), named from the public page order
FRANCHISE_SECTIONS = {10: "about", 20: "why_this_franchise", 30: "ideal_candidate", 40: "territories",
                      50: "training_and_support", 60: "financing"}
FINANCIAL_ASSIST = {10: "available", 20: "none", 0: None}
