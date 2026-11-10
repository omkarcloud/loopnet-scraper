"""The /bizbuysell/* endpoint functions (route_glue's route_table calls them
with the schema's loaded kwargs).

Caching lives here (cache.cached_call, keyed on the validated params):
search / counts / broker / franchise pages cache their own responses; a
listing record is cached under its id alone (the slug is only a fast path,
so a link and a bare id for the same listing share one row); the county
list and the category tree are fetched once per month / week and reused by
every search that names a county or asks for the tree.
"""
import math

from cache import cached_call
from bizbuysell import cache_config as ttl
from bizbuysell import parsers, refs
from bizbuysell.fetch import (BizBuySellNotFound, fetch_broker_typeahead, fetch_brokers, fetch_categories,
                              fetch_counties, fetch_counts, fetch_franchise, fetch_franchises, fetch_listing,
                              fetch_search)

FLAG_ON = 20   # the search criteria's "only these" flag value (0 = any)


# ---- shared criteria builders --------------------------------------------------

def _counties():
    return cached_call("bizbuysell.counties", {}, lambda: parsers.parse_counties(fetch_counties()), ttl.COUNTIES_CACHE)


def _category_tree():
    return cached_call("bizbuysell.category_tree", {}, lambda: parsers.parse_categories(fetch_categories()),
                       ttl.CATEGORIES_CACHE)


def _category_names():
    """siteCategoryId -> name for every category and sub-category (the
    search cards carry only the sub-category id)."""
    names = dict(refs.CATEGORY_NAMES)
    try:
        for top in _category_tree():
            names[top["id"]] = top["name"]
            for sub in top.get("subcategories") or []:
                names[sub["id"]] = sub["name"]
    except Exception as e:   # the tree is a nicety; a search must not fail on it
        print(f"bizbuysell: category tree unavailable: {type(e).__name__}: {e}")
    return names


def _name_categories(listings):
    names = None
    for listing in listings:
        if listing.get("category") is None and listing.get("category_id"):
            if names is None:
                names = _category_names()
            listing["category"] = names.get(listing["category_id"])
    return listings


def _locations(states, county):
    """`state` codes (+ one `county`) -> the criteria's locations[]."""
    if not states:
        return None
    if county:
        code = states[0]
        index = _counties()
        row = index.get(parsers.county_key(code, county))
        if row is None:
            raise ValueError(f"county '{county}' is not a county of {refs.STATES[code][1]} "
                             "(use the county name as BizBuySell prints it, e.g. Los Angeles County).")
        return [refs.county_location(row)]
    return [refs.state_location(code) for code in states]


def _search_criteria(query=None, state=None, county=None, category=None, listing_type=None, min_price=None,
                     max_price=None, min_cash_flow=None, max_cash_flow=None, min_revenue=None, max_revenue=None,
                     listed_within_days=None, updated_within_days=None, established_after=None,
                     seller_financing=None, home_based=None, absentee_owner=None, price_reduced=None,
                     sba_eligible=None, real_estate_included=None, include_relocatable=None, sort="relevance",
                     page=1, per_page=50):
    offset = (page - 1) * per_page
    criteria = {
        "keyword": query,
        "locations": _locations(state, county),
        "categories": [category] if category else None,
        "listingTypeIds": [refs.LISTING_TYPES[listing_type]] if listing_type else None,
        "askingPriceMin": min_price, "askingPriceMax": max_price,
        "cashFlowMin": min_cash_flow, "cashFlowMax": max_cash_flow,
        "grossIncomeMin": min_revenue, "grossIncomeMax": max_revenue,
        "daysListedAgo": listed_within_days, "daysModifiedAgo": updated_within_days,
        "establishedAfterYear": established_after,
        "listingsWithSellerFinancing": FLAG_ON if seller_financing else None,
        "homeBasedListings": FLAG_ON if home_based else None,
        "absenteeOwnerListings": FLAG_ON if absentee_owner else None,
        "listingsWithPriceReduced": FLAG_ON if price_reduced else None,
        "includeSbaEligible": FLAG_ON if sba_eligible else None,
        "realEstateIncluded": FLAG_ON if real_estate_included else None,
        "showRelocatableListings": True if include_relocatable else None,
        "sortList": refs.SORTS.get(sort or "relevance"),
        "pageNumber": page, "offset": offset, "howMany": per_page,
    }
    return {k: v for k, v in criteria.items() if v is not None}


def _pagination(page, per_page, total, has_items):
    reachable = min(total or 0, refs.MAX_RESULTS)
    total_pages = max(1, math.ceil(reachable / per_page)) if reachable else (1 if has_items else 0)
    return {"page": page, "items_per_page": per_page, "total_pages": total_pages, "total_count": total}


# ---- companies/search ------------------------------------------------------------

def _companies_search(**data):
    page, per_page = data["page"], data["per_page"]
    # the site answers `per_page` result rows plus the odd inserted auction
    # placard (a real listing with its own id), so nothing is sliced off
    parsed = parsers.parse_search(fetch_search(_search_criteria(**data)))
    listings = _name_categories(parsed["listings"])
    return {
        "query": data.get("query"),
        "is_total_capped": parsed["is_total_capped"],
        "heading": parsed["heading"],
        "results": listings,
        "pagination": _pagination(page, per_page, parsed["total"], bool(listings)),
    }


def companies_search(**data):
    return cached_call("bizbuysell.companies_search", data, _companies_search, ttl.SEARCH_CACHE)


# ---- companies/counts ------------------------------------------------------------

def _companies_counts(**data):
    criteria = _search_criteria(**data, page=1, per_page=1)
    for key in ("pageNumber", "offset", "howMany", "sortList"):
        criteria.pop(key, None)
    counts = parsers.parse_counts(fetch_counts(criteria))
    return {"query": data.get("query"), **counts}


def companies_counts(**data):
    return cached_call("bizbuysell.companies_counts", data, _companies_counts, ttl.COUNTS_CACHE)


# ---- companies/details -----------------------------------------------------------

def _listing_record(company):
    html, link = fetch_listing(company["id"], company.get("slug"))
    return parsers.parse_listing_page(html, company["id"], link)


def company_details(company):
    """Everything on the public listing page: financials, description, the
    detailed-information rows, location, photos, listed-by name and seller
    phone (when the seller shows one), similar listings. Keyed on the id so
    a link and a bare id share one cached row."""
    return cached_call("bizbuysell.company", {"id": company["id"]},
                       lambda id: _listing_record({"id": id, "slug": company.get("slug")}), ttl.LISTING_CACHE)


# ---- brokers/search --------------------------------------------------------------

def _brokers_search(query=None, state=None, county=None, page=1, per_page=30):
    criteria = {
        "keywordPhrases": [query] if query else None,
        "locations": _locations(state, county),
        "pageNumber": page, "offset": (page - 1) * per_page, "howMany": per_page,
    }
    criteria = {k: v for k, v in criteria.items() if v is not None}
    if "locations" not in criteria:
        criteria["seoName"] = "/business-brokers/"
    parsed = parsers.parse_brokers(fetch_brokers(criteria))
    brokers = parsed["brokers"][:per_page]
    return {
        "query": query,
        "heading": parsed["heading"],
        "results": brokers,
        "pagination": _pagination(page, per_page, parsed["total"], bool(brokers)),
    }


def brokers_search(**data):
    return cached_call("bizbuysell.brokers_search", data, _brokers_search, ttl.BROKERS_CACHE)


# ---- brokers/details -------------------------------------------------------------

def _candidate_names(broker):
    """Name fragments for the site's typeahead, from the profile link's
    slugs (the typeahead matches person and company names)."""
    names = []
    for slug in (broker.get("name"), broker.get("company")):
        if slug:
            words = [w for w in slug.replace("-", " ").split() if w and not w.isdigit()]
            if words:
                names.append(" ".join(words))
                if len(words) > 2:
                    names.append(" ".join(words[:2]))
    return names


def _broker_record(broker):
    broker_id = broker["id"]
    accounts = []
    for keyword in _candidate_names(broker):
        for stub in parsers.parse_typeahead(fetch_broker_typeahead(keyword)):
            if stub["id"] == broker_id and stub["account_id"]:
                accounts.append(stub["account_id"])
                break
        if accounts:
            break
    if not accounts:
        if not broker.get("name"):
            raise BizBuySellNotFound(
                f"broker {broker_id} cannot be looked up by id alone: pass the profile link "
                "(https://www.bizbuysell.com/business-broker/<name>/<company>/<id>/), as returned by /bizbuysell/brokers/search")
        raise BizBuySellNotFound(f"broker {broker_id} not found")
    value = fetch_brokers({"accounts": accounts, "howMany": 100})
    for row in (value.get("brokerSearchResult") or {}).get("value") or []:
        if parsers._int(row.get("brokerProfileId")) == broker_id:
            return parsers.parse_broker(row, full=True)
    raise BizBuySellNotFound(f"broker {broker_id} not found")


def broker_details(broker):
    """The full directory profile: overview, introduction, services,
    affiliations, areas served, links, listing counts."""
    return cached_call("bizbuysell.broker", {"id": broker["id"]},
                       lambda id: _broker_record({**broker, "id": id}), ttl.BROKER_CACHE)


# ---- franchises/search -----------------------------------------------------------

def _franchises_search(category=None, state=None, min_investment=None, max_investment=None, page=1, per_page=50):
    criteria = {
        "regions": state or None,
        "bbsCategories": [category] if category else None,
        "investmentMin": min_investment, "investmentMax": max_investment,
        "pageNumber": page, "offset": (page - 1) * per_page, "howMany": per_page,
    }
    criteria = {k: v for k, v in criteria.items() if v is not None}
    parsed = parsers.parse_franchises(fetch_franchises(criteria))
    franchises = parsed["franchises"][:per_page]
    return {
        "category": refs.FRANCHISE_CATEGORY_NAMES.get(category) if category else None,
        "results": franchises,
        "pagination": _pagination(page, per_page, parsed["total"], bool(franchises)),
    }


def franchises_search(**data):
    return cached_call("bizbuysell.franchises_search", data, _franchises_search, ttl.FRANCHISES_CACHE)


# ---- franchises/details ----------------------------------------------------------

def _franchise_details(franchise):
    return parsers.parse_franchise_detail(fetch_franchise(franchise))


def franchise_details(**data):
    return cached_call("bizbuysell.franchise", data, _franchise_details, ttl.FRANCHISE_CACHE)


# ---- categories/list -------------------------------------------------------------

def _categories_list():
    return {
        "business_categories": _category_tree(),
        "franchise_categories": [{"id": cat_id, "name": name, "slug": slug} for cat_id, name, slug in refs.FRANCHISE_CATEGORIES],
        "listing_types": sorted(refs.LISTING_TYPES),
        "states": [{"code": code, "name": name, "country": country} for code, (country, name, _) in refs.STATES.items()],
    }


def categories_list(**data):
    return cached_call("bizbuysell.categories", {}, _categories_list, ttl.CATEGORIES_CACHE)
