"""Raw HTML / JSON -> clean dicts for every /bizbuysell/* endpoint (pure
functions, no I/O).

Value conventions (shared with the other scraper packages):
  * money   numbers in USD (the site is US-only in dollars); `currency`
            sits next to the amount at the record level
  * dates   ISO where the site prints one ("01/01/1970" lease expiry ->
            "1970-01-01"); years stay integers
  * keys    snake_case; `link` not `url`; booleans as questions
  * nulls   "Not Disclosed", empty strings and the site's -1 / 0 placeholders
            are null, never strings

Sources:
  * search cards      api/search/BbsSearchListingsLive `bbsBfsSearchResult.value`
                      (60 fields; 6-10 ad rows per page carry type -1 / -2 and
                      no listNumber, dropped here)
  * listing page      the `/amp/` variant of /business-opportunity/<slug>/<id>/:
                      h1.bfsTitle, #ldp-section-financials (asking price),
                      the second .financials block (cash flow / EBITDA /
                      gross revenue / established), #ldp-section-description,
                      #dlDetailedInformation + #dlLocationInformation dt/dd
                      pairs, "Business Listed By", the seller's tel: link,
                      the #slider gallery, the tracking blob
                      {"listnumber", "adlevelid", "listingtypeid", ...} and
                      three ld+json blocks (Product with offers + similar
                      listings, LocalBusiness address, BreadcrumbList)
  * brokers           _api/bff/v2/brokerSearch `value.brokerSearchResult.value`
                      (80-field profiles) + SearchBrokerProfilesTypeahead stubs
  * franchises        _api/bff/v2/LoopNetFranchiseSearchResults cards and
                      api/search/GetFranchiseDetail brochures
  * reference lists   api/Resource/GetBfsCategories, GetCountiesByRegion

Fixtures captured 2026-10-31 (bizbuysell/fixtures/): a keyword search
(bakery), a filtered Texas restaurant page, a no-match search, an owner
listing with a phone (2567126), a broker listing without the broker card
(2548034), a brokered listing with the broker card + phone (2525392), a
franchise resale with every detail row (2504737), the not-found page, a Texas broker
page, one broker account, a typeahead, a franchise search page, a
past-the-end franchise page, the Lawn Doctor brochure, the unknown-franchise
answer, the category list and a county sample.
"""
import fastjson
import re

from bs4 import BeautifulSoup

from bizbuysell import refs
from bizbuysell.refs import IMAGE_HOST, SITE

_NOT_DISCLOSED = {"", "not disclosed", "n/a", "na", "-", "none", "null"}
_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")
_US_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_US_DATETIME_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AP]M)?$", re.I)
_TRACKING_RE = re.compile(r'JSON\.stringify\((\{"listnumber"[^)]*\})\)')
_TEL_RE = re.compile(r"[^0-9+]")
_IMG_SIZE_RE = re.compile(r"-W\d+(\.[a-z]+)$")
CURRENCY = "USD"


# ---- helpers --------------------------------------------------------------------

def _clean(value):
    if value is None:
        return None
    text = " ".join(str(value).split())
    return None if text.lower() in _NOT_DISCLOSED else text


def _number(value):
    """"$1,300,000" / 282000.0 -> 1300000 (int when whole); masked -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else value
    text = _clean(value)
    if text is None:
        return None
    match = _NUMBER_RE.search(text.replace("−", "-"))
    if not match:
        return None
    try:
        number = float(match.group(0).replace(",", ""))
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _money(value):
    """A non-positive amount is the site's "not disclosed" placeholder."""
    number = _number(value)
    return number if number is not None and number > 0 else None


def _int(value):
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def _bool(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("true", "1", "yes", "y")


def _year(value):
    number = _int(_number(value))
    return number if number and 1600 <= number <= 2100 else None


def _date(value):
    """"01/01/1970" -> "1970-01-01"; anything else as printed (or None)."""
    text = _clean(value)
    if text is None:
        return None
    match = _US_DATE_RE.match(text)
    if match:
        month, day, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    match = _US_DATETIME_RE.match(text)
    if match:
        month, day, year, hour, minute, second, meridiem = match.groups()
        hour = int(hour) % 12 + (12 if (meridiem or "").upper() == "PM" else 0) if meridiem else int(hour)
        return f"{year}-{int(month):02d}-{int(day):02d}T{hour:02d}:{minute}:{second or '00'}"
    return text


def _link(path):
    if not path:
        return None
    return path if path.startswith("http") else SITE + ("" if path.startswith("/") else "/") + path


def _image(path):
    if not path:
        return None
    if path.startswith("http"):
        return path
    return IMAGE_HOST + ("" if path.startswith("/") else "/") + path


def _text(node, sep=" "):
    return _clean(node.get_text(sep, strip=True)) if node is not None else None


def _split_location(text):
    """"Long Beach, CA" / "Contra Costa County, CA" -> (city_or_county, state_code)."""
    text = _clean(text)
    if not text:
        return None, None
    if "," in text:
        place, _, state = text.rpartition(",")
        return _clean(place), _clean(state)
    return text, None


# ---- search cards ----------------------------------------------------------------

def _contact(card):
    info = card.get("contactInfo") or {}
    phone = info.get("contactPhoneNumber") or {}
    number = _clean(phone.get("telephone")) or _clean(phone.get("tpnPhone"))
    ext = _clean(phone.get("tpnPhoneExt"))
    name = _clean(info.get("contactFullName")) or _clean(card.get("brokerContactFullName"))
    company = _clean(info.get("brokerCompany")) or _clean(card.get("brokerCompany"))
    profile = info.get("brokerProfileUrl")
    if profile and profile.rstrip("/").endswith("/0"):
        profile = None   # the site's placeholder profile for contacts without a directory page
    if not any((name, number, company, profile)):
        return None
    return {
        "name": name,
        "phone": number,
        "phone_extension": ext,
        "company": company,
        "profile_link": _link(profile),
        "photo": _image(info.get("contactPhoto") or card.get("brokerContactPhoto")),
        "is_broker": bool(company or profile),
    }


def parse_listing_card(card):
    """One search card -> a listing summary. Ad rows (no listNumber) -> None."""
    listing_id = _int(card.get("listNumber"))
    # type -1 = franchise ads (franchise ids as listNumber), -2 = inline
    # ad / broker placards: neither is a listing
    if not listing_id or (_int(card.get("type")) or 0) < 0 or card.get("isInlineAd") or card.get("isInlineBroker"):
        return None
    place, state = _split_location(card.get("location"))
    meta = card.get("diamondMetaData") or {}
    listing_type_id = _int(card.get("listingTypeId"))
    photos = [p for p in (card.get("img") or []) if p]
    return {
        "id": listing_id,
        "title": _clean(card.get("header")),
        "link": _link(card.get("urlStub")) or refs.listing_link(listing_id),
        "listing_type": refs.LISTING_TYPE_NAMES.get(listing_type_id),
        "description": _clean(card.get("description")),
        "location": {"name": _clean(card.get("location")), "place": place, "state": state or _clean(card.get("region"))},
        "pricing": {
            "asking_price": _money(card.get("price")),
            "cash_flow": _money(card.get("cashFlow")),
            "ebitda": _money(card.get("ebitda")),
            "unit_revenue": _money(card.get("unitRevenue")),
            "currency": CURRENCY,
            "is_price_reduced": _bool(card.get("listingPriceReduced")),
            "is_real_estate_included": _bool(card.get("realEstateIncludedInAskingPrice")),
            "has_seller_financing": (_int(card.get("financingTypeId")) or 0) > 0,
        },
        "startup": ({"initial_fee": _money(card.get("initialFee")), "cash_required": _money(card.get("initialCapital"))}
                    if card.get("initialFee") or card.get("initialCapital") else None),
        "auction": ({"starts_at": _date(card.get("auctionStartDate")), "ends_at": _date(card.get("auctionEndDate")),
                     "date_text": _clean(card.get("auctionDateDisplay")), "external_link": card.get("externalUrl"),
                     "highlights": _clean(card.get("auctionPlacardHighlights"))}
                    if card.get("auctionStartDate") or card.get("externalUrl") else None),
        "category": _clean(meta.get("bqPrimaryBizTypeName")) or _clean(meta.get("bbsPrimaryBizTypeName")),
        "category_id": _int(meta.get("bbsPrimaryBizTypeId")),
        "badges": {
            "is_recently_added": _bool(card.get("recentlyAdded")) or False,
            "is_recently_updated": _bool(card.get("recentlyUpdated")) or False,
            "is_hot": _bool(card.get("hotProperty")) or False,
            "is_franchise_resale": (_int(card.get("isFdResale")) or 0) > 0,
            "is_sba_eligible": _int(card.get("bbsLenderStatusTypeId")) in (20, 30, 40),
            "is_premium": (_int(card.get("adLevelId")) or 0) >= 4,
        },
        "photos": photos,
        "logo": (card.get("logoImg") or [None])[0] if isinstance(card.get("logoImg"), list) else card.get("logoImg"),
        "contact": _contact(card),
        "related_search_link": _link(card.get("relatedSearchUrlStub")),
    }


def parse_search(result):
    """`bbsBfsSearchResult` -> {total, listings}. Ad rows are dropped."""
    listings = [parsed for parsed in (parse_listing_card(c) for c in result.get("value") or []) if parsed]
    total = _int(result.get("total")) or 0
    return {
        "total": total,
        "is_total_capped": total >= refs.MAX_RESULTS,
        "listings": listings,
        "heading": _clean(result.get("h1Header")),
        "canonical_link": _link(result.get("canonicalUrl")),
    }


def parse_counts(rows):
    """resultCounts rows -> {listing_type: count}, plus the sum."""
    counts = {}
    for row in rows or []:
        name = refs.LISTING_TYPE_NAMES.get(_int(row.get("listingTypeId")))
        if name:
            counts[name] = _int(row.get("resultCount")) or 0
    return {"total": sum(counts.values()), "by_listing_type": counts}


# ---- listing page ---------------------------------------------------------------

def _soup(html):
    return BeautifulSoup(html, "lxml")


def _ld_json(soup):
    blocks = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = fastjson.loads(script.string or "")
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type"):
            blocks.setdefault(data["@type"], data)
    return blocks


def _dl_pairs(dl):
    """A <dl> of dt/dd pairs -> [(label, dd node)]."""
    pairs = []
    if dl is None:
        return pairs
    label = None
    for child in dl.find_all(["dt", "dd"], recursive=False):
        if child.name == "dt":
            label = _text(child)
        elif label:
            pairs.append((label.rstrip(":").strip(), child))
            label = None
    return pairs


def _dd_value(dd):
    """A <dd> -> its text, or a list when it holds several <p> lines."""
    paragraphs = [_text(p) for p in dd.find_all("p")]
    paragraphs = [p for p in paragraphs if p]
    if len(paragraphs) > 1:
        return paragraphs
    return _text(dd)


def _financial_rows(soup):
    rows = {}
    for p in soup.select(".financials p"):
        title = p.select_one("span.title")
        if title is None:
            continue
        label = (_text(title) or "").rstrip(":").strip().lower()
        value_span = title.find_next_sibling("span")
        if value_span is None:
            continue
        for help_span in value_span.select("span.help"):
            help_span.decompose()
        rows[label] = _text(value_span)
    return rows


def _description(section):
    if section is None:
        return None, None
    tagline = _text(section.select_one(".profileAdLine"))
    body = section.select_one(".businessDescription")
    if body is None:
        return tagline, None
    for br in body.find_all("br"):
        br.replace_with("\n")
    lines = [" ".join(line.split()) for line in body.get_text("\n").split("\n")]
    text = "\n".join(line for line in lines if line).strip()
    return tagline, (text or None)


def _photos(soup):
    seen, photos = set(), []
    for img in soup.select("#slider img, img.mainPhoto-print"):
        src = img.get("src") or img.get("data-src")
        if src and "/shared/listings/" in src and src not in seen:
            seen.add(src)
            photos.append(src)
    return photos


def _tracking(html):
    match = _TRACKING_RE.search(html)
    if not match:
        return {}
    try:
        return fastjson.loads(match.group(1))
    except ValueError:
        return {}


def _listed_by(soup):
    """The "Business Listed By" block -> {name, company, profile_link, photo}.
    Brokered listings render a .broker-card (name link, company, phone);
    owner listings a bare name after the label, or nothing at all."""
    card = soup.select_one(".broker-card")
    if card is not None:
        name_node = card.select_one("a.broker-name") or card.select_one(".broker-name")
        href = name_node.get("href") if name_node is not None and name_node.name == "a" else None
        photo = None
        holder = card.find_parent("div", class_="broker")
        if holder is not None:
            img = holder.select_one("img.headshot")
            photo = _image(img.get("src")) if img is not None and img.get("src") else None
        return {
            "name": _text(name_node),
            "company": _text(card.select_one(".cmp-name")),
            "profile_link": _link(href.split("?")[0]) if href and "/business-broker/" in href else None,
            "photo": photo,
        }
    node = soup.find(string=re.compile(r"Business Listed By", re.I))
    if node is None:
        return None
    label = node.find_parent(["span", "div", "p"])
    name = None
    if label is not None:
        tail = []
        for sibling in label.next_siblings:
            if getattr(sibling, "name", None) in ("div", "p", "dl"):
                break
            text = sibling if isinstance(sibling, str) else sibling.get_text(" ", strip=True)
            tail.append(text)
        name = _clean(" ".join(tail).split("Ad#")[0])
    return {"name": name, "company": None, "profile_link": None, "photo": None} if name else None


def _phone(soup):
    for a in soup.select(".contact-phone-selector a[href^='tel:']"):
        raw = a.get("href", "")[4:]
        digits = _TEL_RE.sub("", raw)
        if digits:
            return _clean(a.get_text(" ", strip=True)) or raw
    return None


def _breadcrumbs(ld):
    crumbs = []
    for item in (ld.get("itemListElement") or []):
        entry = item.get("item") or {}
        if entry.get("name"):
            crumbs.append({"name": _clean(entry.get("name")), "link": _link(entry.get("@id"))})
    return crumbs


def _similar(product):
    out = []
    for item in product.get("isSimilarTo") or []:
        offer = item.get("offers") or {}
        place = ((offer.get("availableAtOrFrom") or {}).get("address") or {})
        match = re.search(r"/(\d{5,9})/?$", item.get("url") or "")
        out.append({
            "id": int(match.group(1)) if match else _int(item.get("productid")),
            "title": _clean((item.get("name") or "").replace(" - BizBuySell", "")),
            "link": item.get("url"),
            "asking_price": _money(offer.get("price")),
            "currency": offer.get("priceCurrency") or CURRENCY,
            "location": _clean(", ".join(p for p in (place.get("addressLocality"), place.get("addressRegion")) if p)) or None,
        })
    return out


_DETAIL_KEYS = {
    "employees": "employees", "facilities": "facilities", "competition": "competition",
    "growth & expansion": "growth_and_expansion", "financing": "financing",
    "support & training": "support_and_training", "reason for selling": "reason_for_selling",
    "franchise": "franchise", "inventory": "inventory", "ff&e": "furniture_fixtures_equipment",
    "real estate": "real_estate", "home-based": "home_based", "relocatable": "relocatable",
}
_LOCATION_KEYS = {
    "location": "name", "real estate": "real_estate", "building sf": "building_sqft",
    "lease expiration": "lease_expires_on", "rent": "rent", "building status": "building_status",
}


def parse_listing_page(html, listing_id, link=None):
    """The `/amp/` listing page -> the full listing record."""
    soup = _soup(html)
    ld = _ld_json(soup)
    product, business, crumbs = ld.get("Product") or {}, ld.get("LocalBusiness") or {}, ld.get("BreadcrumbList") or {}
    tracking = _tracking(html)
    financials = _financial_rows(soup)
    tagline, description = _description(soup.select_one("#ldp-section-description"))

    details, extra_details = {}, {}
    for label, dd in _dl_pairs(soup.select_one("#dlDetailedInformation")):
        key = _DETAIL_KEYS.get(label.lower())
        value = _dd_value(dd)
        if key:
            details[key] = value
        else:
            extra_details[label] = value
    location_rows = {}
    for label, dd in _dl_pairs(soup.select_one("#dlLocationInformation")):
        location_rows[_LOCATION_KEYS.get(label.lower(), label.lower().replace(" ", "_"))] = _dd_value(dd)

    location_text = location_rows.get("name") or _text(soup.select_one("span.f-l.c-neutral-800"))
    place, state = _split_location(location_text)
    address = business.get("address") or {}
    crumb_list = _breadcrumbs(crumbs)
    county = next((c["name"] for c in crumb_list if c.get("link") and "county-businesses-for-sale" in c["link"]), None)
    category_crumb = next((c["name"] for c in crumb_list if c.get("link") and c["link"].rstrip("/").endswith("-for-sale")
                           and "businesses-for-sale" not in c["link"]), None)
    financing = details.get("financing")
    financing_lines = financing if isinstance(financing, list) else ([financing] if financing else [])
    listing_type_id = _int(tracking.get("listingtypeid"))
    canonical = product.get("url") or business.get("url") or link
    title = _text(soup.select_one("h1.bfsTitle"))
    listed_by = _listed_by(soup)

    return {
        "id": listing_id,
        "title": title,
        "link": canonical,
        "listing_type": refs.LISTING_TYPE_NAMES.get(listing_type_id),
        "tagline": tagline or _clean(product.get("alternateName")),
        "description": description or _clean(product.get("description")),
        "category": _clean(product.get("category")) or category_crumb,
        "location": {
            "name": location_text,
            "place": place,
            "state": state or _clean(address.get("addressRegion")),
            "county": county,
            "city": _clean(address.get("addressLocality")) if county is None or _clean(address.get("addressLocality")) != (county or "").replace(" County", "") else None,
            "real_estate": _clean(location_rows.get("real_estate")) if not isinstance(location_rows.get("real_estate"), list) else location_rows.get("real_estate"),
            "building_sqft": _number(location_rows.get("building_sqft")) if not isinstance(location_rows.get("building_sqft"), list) else None,
            "lease_expires_on": _date(location_rows.get("lease_expires_on")) if not isinstance(location_rows.get("lease_expires_on"), list) else None,
            "rent": location_rows.get("rent"),
        },
        "pricing": {
            "asking_price": _money(financials.get("asking price")) or _money((product.get("offers") or {}).get("price")),
            "cash_flow": _money(financials.get("cash flow (sde)") or financials.get("cash flow")),
            "ebitda": _money(financials.get("ebitda")),
            "gross_revenue": _money(financials.get("gross revenue")),
            "inventory": _money(details.get("inventory")),
            "furniture_fixtures_equipment": _money(details.get("furniture_fixtures_equipment")),
            "currency": CURRENCY,
            "financing": financing_lines or None,
            "has_seller_financing": any("seller financing" in str(line).lower() for line in financing_lines),
            "is_real_estate_included": None if location_rows.get("real_estate") is None
            else "included" in str(location_rows.get("real_estate")).lower(),
        },
        "established_year": _year(financials.get("established")),
        "employees": details.get("employees"),
        "facilities": details.get("facilities"),
        "competition": details.get("competition"),
        "growth_and_expansion": details.get("growth_and_expansion"),
        "support_and_training": details.get("support_and_training"),
        "reason_for_selling": details.get("reason_for_selling"),
        "is_franchise": bool(details.get("franchise")),
        "franchise_note": details.get("franchise"),
        "is_home_based": _bool(details.get("home_based")) if details.get("home_based") is not None else None,
        "is_relocatable": _bool(details.get("relocatable")) if details.get("relocatable") is not None else None,
        "other_details": extra_details or None,
        "contact": {
            **(listed_by or {"name": None, "company": None, "profile_link": None, "photo": None}),
            "phone": _phone(soup),
            "is_broker": bool((listed_by or {}).get("profile_link")) or (_int(tracking.get("account")) or 0) > 0,
        },
        "badges": {
            "is_premium": (_int(tracking.get("adlevelid")) or 0) >= 4,
            "is_franchise_resale": (_int(tracking.get("isfdresale")) or 0) > 0,
        },
        "photos": _photos(soup) or ([product["image"]] if product.get("image") else []),
        "breadcrumbs": crumb_list,
        "similar_listings": _similar(product),
    }


# ---- brokers -------------------------------------------------------------------

def _broker_areas(record):
    areas = []
    for area in record.get("areasServed") or []:
        areas.append({
            "country": area.get("country"),
            "state": area.get("region"),
            "county_id": _int(area.get("countyId")) or None,
            "license_number": _clean(area.get("brokerLicense")),
            "is_licensed": _bool(area.get("isRegionLicensed")),
        })
    return areas


def _broker_links(record):
    links = []
    for item in record.get("profileLinks") or []:
        if item.get("linkUrl"):
            links.append({"name": _clean(item.get("linkName")), "link": item["linkUrl"]})
    return links


def _expertise(record, key):
    return [_clean(x.get("description")) for x in (record.get(key) or []) if x.get("description")]


def parse_broker(record, full=True):
    """One brokerSearch profile row -> the broker record (full=False keeps
    the directory-card subset)."""
    name = " ".join(p for p in (_clean(record.get("firstName")), _clean(record.get("lastName"))) if p) or None
    languages = [_clean(x.get("name")) for x in (record.get("personLanguages") or []) if isinstance(x, dict) and x.get("name")]
    if not languages and record.get("personLanguagesDescription"):
        languages = [s.strip() for s in record["personLanguagesDescription"].split(",") if s.strip()]
    out = {
        "id": _int(record.get("brokerProfileId")),
        "name": name,
        "link": _link(record.get("url")),
        "company": _clean(record.get("companyName")),
        "company_website": _clean(record.get("companyUrl")),
        "tagline": _clean(record.get("tagline")),
        "location": {
            "name": _clean(record.get("locationDescriptionShort")) or _clean(record.get("locationDescription")),
            "city": _clean(record.get("city")),
            "state": _clean(record.get("regionCode")),
            "country": _clean(record.get("countryCode")),
            "zip": _clean(record.get("zip")),
        },
        "contact": {
            "phone": _clean(record.get("telephone")),
            "fax": _clean(record.get("fax")),
            "license_number": _clean(record.get("licenseNumber")) if _clean(record.get("licenseNumber")) != "0" else None,
        },
        "photo": _image(record.get("personalPhotoFName")),
        "company_logo": _image(record.get("companyPhotoFName")),
        "languages": languages,
        "designations": [_int(d.get("designationId")) for d in (record.get("personDesignations") or []) if d.get("designationId")],
        "stats": {
            "active_listings": _int(record.get("activeListingsCount")),
            "for_sale_listings": _int(record.get("forSaleListingsCount")),
            "sold_listings": _int(record.get("soldListingsCount")),
            "sold_last_six_months": _int(record.get("soldListingsInLastSixMonthsCount")),
            "sba_eligible_listings": _int(record.get("sbaEligibleListingsCount")),
            "verified_comps": _int(record.get("verifiedCompsCount")),
            "message_response_score": _int(record.get("messageResponseScore")),
            "profile_completeness": _int(record.get("completeness")),
        },
        "is_premium": (_int(record.get("listingTier")) or 0) > 0,
    }
    if full:
        out.update({
            "introduction": _clean(record.get("introduction")),
            "company_overview": _clean(record.get("companyOverview")),
            "services": _clean(record.get("services")),
            "affiliations": _clean(record.get("affiliations")),
            "expertise": {"industries": _expertise(record, "expertiseCategories"),
                          "services": _expertise(record, "expertiseServices")},
            "areas_served": _broker_areas(record),
            "links": _broker_links(record),
            "nda_document": _image(record.get("ndaFileName")),
            "account_id": _int(record.get("account")),
            "person_id": _int(record.get("personId")),
        })
    return out


def parse_brokers(value):
    """The brokerSearch `value` -> {total, brokers, ...}."""
    result = value.get("brokerSearchResult") or {}
    brokers = [parse_broker(r, full=False) for r in (result.get("value") or []) if isinstance(r, dict)]
    return {
        "total": _int(result.get("total")) if (_int(result.get("total")) or 0) >= 0 else 0,
        "brokers": brokers,
        "heading": _clean(value.get("h1Header")),
        "canonical_link": _link(value.get("canonicalUrl")),
    }


def parse_typeahead(rows):
    return [{
        "id": _int(r.get("brokerProfileId")),
        "name": _clean(r.get("fullName")),
        "company": _clean(r.get("companyName")),
        "location": _clean(r.get("locationDescription")),
        "link": _link(r.get("url")),
        "account_id": _int(r.get("account")),
    } for r in rows or [] if isinstance(r, dict)]


# ---- franchises ----------------------------------------------------------------

def _franchise_categories(rows):
    out = []
    for cat in rows or []:
        if isinstance(cat, dict) and cat.get("name"):
            out.append({"id": _int(cat.get("siteCategoryId")), "name": _clean(cat.get("name")),
                        "slug": _clean(cat.get("urlStub"))})
    return out


def parse_franchise_card(card):
    slug = refs.franchise_slug_from_stub(card.get("urlStub"))
    return {
        "slug": slug,
        "name": _clean(card.get("header")),
        "link": refs.franchise_link(slug),
        "description": _clean(card.get("description")),
        "availability": _clean(card.get("location")),
        "pricing": {"cash_required": _money(card.get("price")), "average_unit_revenue": _money(card.get("unitRevenue")),
                    "currency": CURRENCY},
        "categories": _franchise_categories(card.get("categoryDetails")),
        "logo": (card.get("logoImg") or [None])[0] if isinstance(card.get("logoImg"), list) else card.get("logoImg"),
        "photos": [p for p in (card.get("img") or []) if p],
        "is_sponsored": (_int(card.get("sponsorLevelId")) or 0) > 0,
        "franchise_id": _int(card.get("listNumber")),
    }


def parse_franchises(result):
    cards = [parse_franchise_card(c) for c in (result.get("value") or []) if isinstance(c, dict) and c.get("header")]
    return {"total": max(_int(result.get("total")) or 0, 0), "franchises": cards,
            "canonical_link": _link(result.get("canonicalUrl"))}


def _html_text(fragment):
    if not fragment:
        return None
    soup = BeautifulSoup(fragment, "lxml")
    for li in soup.find_all("li"):
        li.replace_with("\n- " + " ".join(li.get_text(" ", strip=True).split()) + "\n")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    lines = [" ".join(line.split()) for line in soup.get_text("\n").split("\n")]
    return "\n".join(line for line in lines if line).strip() or None


def parse_franchise_detail(value):
    """GetFranchiseDetail `value` -> the brochure record."""
    fees = {}
    for row in value.get("vmFranchiseFeeLst") or []:
        key = refs.FRANCHISE_FEE_TYPES.get(_int(row.get("feeTypeId")), f"fee_type_{row.get('feeTypeId')}")
        fees[key] = {"amount": _money(row.get("feeValue")), "percent": _clean(row.get("feePercent")),
                     "base": _clean(row.get("feeBase"))}
    sections = {}
    for comp in value.get("displayComponents") or []:
        key = refs.FRANCHISE_SECTIONS.get(_int(comp.get("componentTypeId")), f"section_{comp.get('componentTypeId')}")
        text = _html_text(comp.get("content"))
        if text:
            sections[key] = text if key not in sections else sections[key] + "\n" + text
    units = [{"year": _int(u.get("year")), "franchised": _int(u.get("franchisedUnits")),
              "company_owned": _int(u.get("companyOwnedUnits"))} for u in (value.get("franchiseUnitLst") or [])]
    slug = refs.franchise_slug_from_stub(value.get("urlStub")) or refs.franchise_slug_from_stub(value.get("canonicalUrl"))
    return {
        "slug": slug,
        "name": _clean(value.get("name")),
        "link": refs.franchise_link(slug),
        "heading": _clean(value.get("h1Header")),
        "tagline": _clean(value.get("tagLine")) or _clean(value.get("generalDescription")),
        "website": _clean(value.get("website")),
        "categories": _franchise_categories(value.get("categoryDetails")),
        "investment": {
            "cash_required": _money(value.get("cashRequired")),
            "net_worth_required": _money(value.get("netWorthRequired")),
            "total_investment_min": _money(value.get("totalInvestmentMin")),
            "total_investment_max": _money(value.get("totalInvestmentMax")),
            "franchise_fee": _money(value.get("franchiseFee")),
            "currency": CURRENCY,
            "fees": fees or None,
            "financial_assistance": refs.FINANCIAL_ASSIST.get(_int(value.get("financialAssistTypeId"))),
            "is_training_provided": _bool(value.get("trainingProvided")),
        },
        "units": {
            "total": _int(value.get("totalNumberOfUnits")),
            "franchised": _int(_number(value.get("franchisedUnits"))),
            "company_owned": _int(value.get("latestCompanyOwnedUnits")),
            "new_units_opened": _int(value.get("newUnitsOpened")),
            "data_year": _int(value.get("latestDataYear")),
            "by_year": units,
        },
        "average_unit_revenue": _money(value.get("averageUnitRevenue")),
        "franchising_since": _year(value.get("franchisingSince")),
        "headquarters": _clean(value.get("corporateHeadquaters")),
        "ceo": _clean(value.get("ceoName")),
        "stock_ticker": _clean(value.get("stockTicker")),
        "attributes": [_clean(a) for a in (value.get("additionalClassificationLst") or []) if a],
        "available_states": list(value.get("locationFilters") or []),
        "is_available_in_canada": _bool(value.get("franchisedInCanada")),
        "sections": sections or None,
        "images": [_link(i.get("url")) for i in (value.get("images") or []) if isinstance(i, dict) and i.get("url")],
        "franchise_id": _int(value.get("franchiseId")),
    }


# ---- reference lists ----------------------------------------------------------

def parse_categories(rows):
    """GetBfsCategories rows -> the two-level tree keyed on siteCategoryId
    (the id the search criteria take)."""
    tops, subs = [], {}
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("name") or not row.get("isDisplayable", True):
            continue
        entry = {"id": _int(row.get("siteCategoryId")), "name": _clean(row.get("name")), "slug": _clean(row.get("urlStub"))}
        if row.get("parentCategoryId"):
            subs.setdefault(_int(row["parentCategoryId"]), []).append(entry)
        else:
            entry["_cid"] = _int(row.get("categoryId"))
            tops.append(entry)
    out = []
    for top in sorted(tops, key=lambda t: (t["name"] or "")):
        children = sorted(subs.get(top.pop("_cid"), []), key=lambda s: (s["name"] or ""))
        out.append({**top, "subcategories": children})
    return out


def county_key(state_code, name):
    """The counties index key: a string, because the index is JSON-cached
    (cache.py) and a tuple key would neither store nor survive the round trip."""
    return f"{(state_code or '').upper()}|{refs.normalize_county(name)}"


def parse_counties(rows):
    """GetCountiesByRegion rows -> {"<state code>|<normalized name>": row}."""
    index = {}
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("countyId"):
            continue
        index.setdefault(county_key(row.get("stateCode"), row.get("regionName")), row)
    return index
