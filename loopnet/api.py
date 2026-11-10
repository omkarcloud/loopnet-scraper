"""The /loopnet/* endpoint functions (route_glue's route_table calls them
with the schema's loaded kwargs). Every endpoint caches its own parsed
result through cache.cached_call keyed on the validated params (TTLs in
cache_config.py); a listing / broker / company / property record is keyed
on its id alone, so a pasted link and a bare id share one cached row.

Every www page costs one use of an Akamai identity that serves
LOOPNET_IDENTITY_USES pages before a box re-mint (fetch.py), so each
endpoint fetches exactly the page it needs: a search is ONE page, a bare
listing id costs one small mini-placard call to learn its canonical link
(the site's own redirect lands on the challenge) plus the page.

The Businesses-for-Sale vertical (/biz/) is BizBuySell's data served by
BizBuySell's BFF with a page-minted token; the bizbuysell scraper already
reads the same listings from bizbuysell.com's open JSON, so
businesses/search and businesses/details delegate to it and point the
links back at loopnet.com/biz/.
"""
from cache import cached_call
from loopnet import cache_config as ttl
from loopnet import parsers, refs
from loopnet.fetch import (LoopNetNotFound, LoopNetUpstreamError, fetch_broker, fetch_broker_directory,
                           fetch_broker_search, fetch_company, fetch_geography, fetch_listing, fetch_mini_placards,
                           fetch_property, fetch_search, fetch_traffic)

BIZ_PREFIX = refs.SITE + "/biz"
BIZBUYSELL_SITE = "https://www.bizbuysell.com"


# ---- listings/search --------------------------------------------------------------------

def _place_slug(query):
    """A typed place -> the search-path slug of the site's best typeahead
    match (city / state / ZIP / county / country rows only)."""
    rows = parsers.parse_geography_lookup(fetch_geography(query))
    places = [row for row in rows if row["type"] in refs.SEARCHABLE_GEO_TYPES and row["slug"]]
    if not places:
        raise LoopNetNotFound(f"no place matches {query!r} on LoopNet (try a city like 'Austin, TX', a state, "
                              "a ZIP or a county)")
    return places[0]


def _resolve_query(query):
    """The `query` param -> (place row or None, geo slug, link-derived settings)."""
    link = refs.parse_search_link(query)
    if link:
        return None, link["geo_slug"], link
    pair = refs.parse_lat_lng(query)
    if pair:
        rows = parsers.parse_geography_lookup(fetch_geography(f"{pair[0]:.5f}, {pair[1]:.5f}"))
        places = [row for row in rows if row["type"] in refs.SEARCHABLE_GEO_TYPES and row["slug"]]
        if not places:
            raise LoopNetNotFound(f"no LoopNet place around {pair[0]},{pair[1]}")
        return places[0], places[0]["slug"], None
    place = _place_slug(query)
    return place, place["slug"], None


def _search(query, listing_type="sale", property_type="all", min_price=None, max_price=None, price_per_sf=None,
            min_rent=None, max_rent=None, min_size=None, max_size=None, min_cap_rate=None, max_cap_rate=None,
            min_year_built=None, keyword=None, sort="default", page=1):
    place, geo_slug, link = _resolve_query(query)
    type_slug = refs.PROPERTY_TYPES[property_type]
    params = {}
    if link:
        # a pasted search link: its path wins over the defaults, its own
        # query params are kept, explicit params here override them
        listing_type = link["listing_type"]
        type_slug = link["property_type_slug"] if property_type == "all" else type_slug
        page = link["page"] if page == 1 else page
        params.update(link["params"])
    values = {"min_price": min_price, "max_price": max_price, "min_rent": min_rent, "max_rent": max_rent,
              "min_size": min_size, "max_size": max_size, "min_cap_rate": min_cap_rate, "max_cap_rate": max_cap_rate,
              "min_year_built": min_year_built, "keyword": keyword}
    for name, value in values.items():
        if value is not None:
            params[refs.FILTER_PARAMS[name]] = int(value) if isinstance(value, float) and value.is_integer() else value
    if price_per_sf:
        params["price-type"] = "sf"
    if refs.SORTS.get(sort):
        params["sort"] = refs.SORTS[sort]
    path = refs.search_path(type_slug, geo_slug, listing_type, page, params)
    html = fetch_search(path)
    parsed = parsers.parse_search(html) if html else None
    if html and parsed is None:
        raise LoopNetUpstreamError(f"search {path}: page carried no results markup")
    results = parsed["results"] if parsed else []
    total = parsed["total"] if parsed else None
    # the site caps every search at 750 results = 19 pages; a page past
    # the end redirects to page 1 and is reported as an empty page
    if total is not None:
        total_pages = max(1, min(refs.MAX_SEARCH_PAGE, -(-min(total, refs.MAX_RESULTS) // refs.SEARCH_PAGE_SIZE)))
    else:
        total_pages = page - 1 if page > 1 else 1
    return {
        "query": query,
        "place": (parsed or {}).get("place") or (place or {}).get("display"),
        "heading": (parsed or {}).get("heading"),
        "listing_type": listing_type,
        "property_type": refs.PROPERTY_TYPE_BY_SLUG.get(type_slug, type_slug),
        "search_link": refs.SITE + path,
        "geography": (parsed or {}).get("geography") or (
            {"id": place["id"], "type": place["type"], "latitude": place["latitude"], "longitude": place["longitude"],
             "bounding_box": place["bounding_box"]} if place else None),
        "is_total_capped": bool((parsed or {}).get("is_total_capped")),
        "applied_filters": (parsed or {}).get("applied_filters"),
        "results": results,
        "pagination": {"page": page, "items_per_page": refs.SEARCH_PAGE_SIZE, "total_pages": total_pages,
                       "total_count": total},
    }


def listings_search(**data):
    return cached_call("loopnet.listings_search", data, _search, ttl.SEARCH_CACHE)


# ---- listings/details --------------------------------------------------------------------

def _canonical(listing_id):
    """A bare id -> (id, slug) through the site's mini-placard service (one
    small POST; the bare /Listing/<id>/ redirect lands on the challenge)."""
    placards = parsers.parse_mini_placards(fetch_mini_placards([listing_id]))
    card = placards.get(listing_id)
    link = (card or {}).get("link")
    slug = refs.resolve_listing(link)["slug"] if link else None
    return slug


def _listing_record(listing_id, slug=None):
    if not slug:
        try:
            slug = _canonical(listing_id)
        except LoopNetUpstreamError:
            slug = None
    html, link = fetch_listing(listing_id, slug)
    record = parsers.parse_listing(html, listing_id, link)
    if record is None:
        raise LoopNetUpstreamError(f"listing {listing_id}: page carried no listing markup")
    return record


def listing_details(listing):
    return cached_call("loopnet.listing", {"id": listing["id"]},
                       lambda id: _listing_record(id, listing.get("slug")), ttl.LISTING_CACHE)


# ---- locations/autocomplete -------------------------------------------------------------------

def _autocomplete(query):
    rows = parsers.parse_geography_lookup(fetch_geography(query))
    return {"query": query, "count": len(rows), "results": rows}


def locations_autocomplete(**data):
    return cached_call("loopnet.autocomplete", data, _autocomplete, ttl.AUTOCOMPLETE_CACHE)


# ---- brokers/search -----------------------------------------------------------------------------

def _brokers_search(location=None, name=None, company=None, broker_type=None, sort="default", page=1):
    if name or company or broker_type:
        # the site's broker search form (one result page, no paging)
        first, last = (name or "").strip(), ""
        if " " in first:
            first, last = first.rsplit(" ", 1)
        geography = None
        if location:
            geography = (f"{location['city'].replace('-', ' ').title()}, {location['state']}" if location.get("city")
                         else refs.US_STATES.get(location["state"], location["state"]))
        html = fetch_broker_search(first, last, company, geography, refs.BROKER_TYPES.get(broker_type) if broker_type else "")
        parsed = parsers.parse_broker_directory(html) or {"heading": None, "results": [], "has_next": False}
        # the form answers its first page only: its "Next" is a server-session
        # page the frozen-cookie transport cannot follow, so the site's own
        # "more results" flag is reported as is_truncated and never as a next link
        results = parsed["results"] if page == 1 else []
        return {"location": geography, "name": name, "company": company, "broker_type": broker_type,
                "heading": parsed["heading"], "is_truncated": bool(parsed["has_next"]), "results": results,
                "pagination": {"page": page, "items_per_page": len(results) or refs.BROKER_PAGE_SIZE, "has_next": False,
                               "total_pages": None, "total_count": None}}
    path = refs.broker_directory_path(location["state"], location.get("city"), page, refs.BROKER_SORTS.get(sort))
    html = fetch_broker_directory(path)
    parsed = parsers.parse_broker_directory(html) if html else None
    results = parsed["results"] if parsed else []
    return {
        "location": (f"{location['city'].replace('-', ' ').title()}, {location['state']}" if location.get("city")
                     else refs.US_STATES.get(location["state"], location["state"])),
        "name": None, "company": None, "broker_type": None,
        "heading": (parsed or {}).get("heading"),
        "directory_link": refs.SITE + path,
        "results": results,
        "pagination": {"page": page, "items_per_page": refs.BROKER_PAGE_SIZE,
                       "has_next": bool(parsed and parsed["has_next"]), "total_pages": None, "total_count": None},
    }


def brokers_search(**data):
    return cached_call("loopnet.brokers_search", data, _brokers_search, ttl.BROKERS_CACHE)


# ---- brokers/details ---------------------------------------------------------------------------

def _broker_record(broker_id, slug=None):
    html, link = fetch_broker(broker_id, slug)
    record = parsers.parse_broker_profile(html, broker_id)
    if record is None:
        raise LoopNetUpstreamError(f"broker {broker_id}: page carried no profile markup")
    record["link"] = record["link"] or link
    return record


def broker_details(broker):
    return cached_call("loopnet.broker", {"id": broker["id"]},
                       lambda id: _broker_record(id, broker.get("slug")), ttl.BROKER_CACHE)


# ---- companies/details ------------------------------------------------------------------------

def _company_record(company_id, slug=None, page=1):
    html, link = fetch_company(company_id, slug, page)
    if html is None:              # a listings page past the end
        return {"id": company_id, "results": [], "pagination": {"page": page, "items_per_page": 20, "has_next": False,
                                                                 "total_pages": None, "total_count": None}}
    record = parsers.parse_company(html, company_id)
    if record is None:
        raise LoopNetUpstreamError(f"company {company_id}: page carried no company markup")
    listings = record.pop("listings")
    total_pages = record.pop("listing_pages") or None
    record["link"] = record["link"] or link
    record["results"] = listings
    record["pagination"] = {"page": page, "items_per_page": 20, "total_pages": total_pages,
                            "total_count": None, "has_next": bool(total_pages and page < total_pages)}
    return record


def company_details(company, page=1):
    return cached_call("loopnet.company", {"id": company["id"], "page": page},
                       lambda id, page: _company_record(id, company.get("slug"), page), ttl.COMPANY_CACHE)


# ---- properties/details -----------------------------------------------------------------------

def _property_record(record_id, slug=None):
    html, link = fetch_property(record_id, slug)
    record = parsers.parse_property_record(html, record_id)
    if record is None:
        raise LoopNetUpstreamError(f"property record {record_id}: page carried no record markup")
    record["link"] = record["link"] or link
    return record


def property_details(property):
    return cached_call("loopnet.property", {"id": property["id"]},
                       lambda id: _property_record(id, property.get("slug")), ttl.PROPERTY_CACHE)


# ---- traffic/counts ------------------------------------------------------------------------------

def _traffic(location):
    rows = parsers.parse_traffic(fetch_traffic(location["latitude"], location["longitude"]))
    rows = [r for r in rows if r["street"] and r["street"].lower() != "not available"]
    return {"latitude": location["latitude"], "longitude": location["longitude"], "count": len(rows), "results": rows}


def traffic_counts(**data):
    return cached_call("loopnet.traffic", data, _traffic, ttl.TRAFFIC_CACHE)


# ---- businesses (BizBuySell data) ------------------------------------------------------------------

def _biz_link(link):
    """A bizbuysell.com link -> the same page on loopnet.com/biz/."""
    if isinstance(link, str) and link.startswith(BIZBUYSELL_SITE):
        return BIZ_PREFIX + link[len(BIZBUYSELL_SITE):]
    return link


def _relink(value):
    if isinstance(value, dict):
        return {k: (_biz_link(v) if k == "link" else _relink(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_relink(v) for v in value]
    return value


def _businesses_search(query=None, state=None, category=None, min_price=None, max_price=None, min_cash_flow=None,
                       max_cash_flow=None, sort="relevance", page=1):
    from bizbuysell import api as biz_api
    result = biz_api.companies_search(query=query, state=state, category=category, min_price=min_price,
                                      max_price=max_price, min_cash_flow=min_cash_flow, max_cash_flow=max_cash_flow,
                                      sort=sort, page=page, per_page=50)
    return _relink(result)


def businesses_search(**data):
    return cached_call("loopnet.businesses_search", data, _businesses_search, ttl.BUSINESSES_CACHE)


def business_details(business):
    from bizbuysell import api as biz_api
    return _relink(biz_api.company_details(business))
