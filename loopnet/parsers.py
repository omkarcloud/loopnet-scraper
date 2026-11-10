"""HTML / JSON -> clean dicts for every /loopnet/* endpoint (pure functions,
no I/O).

Every LoopNet page is server-rendered. Search pages carry 40 placard cards
plus `window.gState`, a JSON blob whose every printable character is
shifted by +3 (gstate() undoes it): the search criteria, the total, the
750 cap, the card ids with their pins ("id||lat|lng|...") and the
property-type taxonomy. Listing pages carry the facts, spaces, brokers,
demographics and attachments as HTML, the full gallery in gState
(mainAttachments) and a schema.org RealEstateListing in ld+json. The
broker directory, broker profile, company page and property record are
plain server HTML (Angular markup, pre-rendered). The JSON services
(geography typeahead, traffic counts, mini placards) are parsed as-is.

Value conventions (shared with the other scraper packages):
  * prices   {"text": "$41.40 /SF/YR", "min": 41.4, "max": 41.4, "currency": "USD",
             "basis": "sf_year"}; "Price Upon Request" keeps the text with null numbers
  * sizes    {"text": "901 - 4,592 SF", "min_sf": 901, "max_sf": 4592}
  * dates    ISO: <time datetime="2024-05-21"> -> "2024-05-21"
  * keys     snake_case; `link` not `url`; booleans as questions
  * absent   null (never "", "N/A" or a missing key); locked values are null too

Fixtures captured 2026-11-07 (loopnet/fixtures/): for-sale / for-lease /
auction search pages, a lease listing (8 spaces, amenities, sustainability,
brochure, owner), an auction sale listing (condo units, offering memorandum,
demographics, attachments, Matterport), a plain sale listing, the
not-found search and listing pages, a broker directory page, a broker
search result, a broker profile, a company page, a property record, the
geography typeahead, traffic counts and mini placards.
"""
import json
import re

import fastjson
from bs4 import BeautifulSoup

from loopnet.refs import SEARCH_GEO_TYPES, SITE, geo_slug, geo_type

_GSTATE_RE = re.compile(r'window\.gState\s*=\s*"((?:[^"\\]|\\.)*)"')
_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")
_MONEY_RE = re.compile(r"\$\s?(\d[\d,]*\.?\d*)\s*([KMB])?", re.I)
_SF_RANGE_RE = re.compile(r"(\d[\d,]*\.?\d*)\s*(?:-|to|–)\s*(\d[\d,]*\.?\d*)\s*(SF|AC|Acres?|SM)\b", re.I)
_SF_RE = re.compile(r"(\d[\d,]*\.?\d*)\s*(SF|AC|Acres?|SM)\b", re.I)
_COUNT_RE = re.compile(r"(\d[\d,]*)\s+(Units?|Spaces?|Properties|Property|Rooms?|Beds?|Lots?|Condo Units?|Condos?)\b", re.I)
_YEAR_BUILT_RE = re.compile(r"\b(Built|Renovated|Built/Renovated)\s+(?:in\s+)?(\d{4})", re.I)
_TEL_RE = re.compile(r"[^\d+,x]")
_PLACE_RE = re.compile(r"^(.*?),\s*([A-Z]{2})(?:\s+([A-Z0-9 -]{3,10}))?$")
_PERCENT_RE = re.compile(r"-?\d[\d,]*\.?\d*\s*%")
_CITY_STATE_RE = re.compile(r"^(.*?),\s*([A-Z]{2})\b\s*([0-9A-Z -]*)$")

_MASKS = {"", "-", "—", "–", "N/A", "NA", "n/a", "Not Disclosed", "Upon Request", "Price Upon Request",
          "Rate Upon Request", "Negotiable", "TBD", "null", "None"}


# ---- basics ---------------------------------------------------------------------

def _soup(html):
    return BeautifulSoup(html or "", "lxml")


def _text(node, sep=" "):
    return node.get_text(sep, strip=True) if node is not None else ""


def _clean(value):
    """Collapse whitespace; placeholder masks -> None."""
    if value is None:
        return None
    value = " ".join(str(value).replace("\xa0", " ").split())
    return None if value in _MASKS else value


def _snake(label):
    """"Space Use" / "SpaceUse" / "Rental Rate:" -> space_use / space_use / rental_rate."""
    label = (label or "").strip()
    if " " not in label:                      # CamelCase automation ids only
        label = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", label)
    label = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").lower()
    return re.sub(r"_+", "_", label) or None


def _int(value):
    value = _clean(value)
    if value is None:
        return None
    match = _NUMBER_RE.search(value)
    if not match:
        return None
    try:
        return int(float(match.group(0).replace(",", "")))
    except ValueError:
        return None


def _number(value):
    value = _clean(value)
    if value is None:
        return None
    match = _NUMBER_RE.search(value.replace("−", "-"))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _link(href):
    href = _clean(href)
    if not href:
        return None
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return SITE + href
    return href


def _bg_image(style):
    match = re.search(r"url\(['\"]?([^'\")]+)['\"]?\)", style or "")
    return _clean(match.group(1)) if match else None


def _ld_json(soup):
    """Every ld+json block, flattened (@graph members included)."""
    blocks = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = fastjson.loads(script.string or "")
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("@graph"), list):
            blocks.extend(d for d in data["@graph"] if isinstance(d, dict))
        elif isinstance(data, dict):
            blocks.append(data)
        elif isinstance(data, list):
            blocks.extend(d for d in data if isinstance(d, dict))
    return blocks


def _ld_of_type(blocks, type_name):
    for block in blocks:
        types = block.get("@type")
        types = types if isinstance(types, list) else [types]
        if type_name in types:
            return block
    return None


def _id_from_link(link, pattern):
    match = re.search(pattern, link or "", re.I)
    return match.group(1) if match else None


def _listing_id(link):
    value = _id_from_link(link, r"/Listing/(?:[^/]+/)?(\d{5,10})/?")
    return int(value) if value else None


def _profile_id(link):
    return _id_from_link(link, r"/commercial-real-estate-brokers/profile/[^/]+/([a-z0-9]{6,12})")


def _company_id(link):
    return _id_from_link(link, r"/company/[^/]+/([a-z0-9]{6,12})")


def _phone(href_or_text):
    """tel:+13108992719 / "(310) 899-2719" / "+1 310-899-2719 x2212" -> E.164-ish digits."""
    value = _clean(href_or_text)
    if not value:
        return None
    value = value.replace("tel:", "").strip()
    ext = None
    match = re.search(r"(?:x|ext\.?)\s*(\d+)", value, re.I)
    if match:
        ext = match.group(1)
        value = value[:match.start()]
    if "," in value:                      # tel:+19412024259,2212
        value, _, pause = value.partition(",")
        ext = ext or (pause.strip() or None)
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    if len(digits) == 10:
        digits = "1" + digits
    number = "+" + digits
    return number + (f" x{ext}" if ext else "")


def _split_name_title(value):
    """"Keith Fielding, Principal" -> (name, title)."""
    value = _clean(value)
    if not value:
        return None, None
    name, _, title = value.partition(", ")
    return name.strip() or None, (title.strip() or None)


def _split_city_state(value):
    """"Los Angeles, CA 90064" -> (city, state, postal_code)."""
    value = _clean(value)
    if not value:
        return None, None, None
    match = _CITY_STATE_RE.match(value)
    if not match:
        return value, None, None
    city, state, postal = match.groups()
    return city.strip() or None, state, (postal.strip() or None)


# ---- money / size --------------------------------------------------------------

_BASIS = (
    (r"/\s*SF\s*/\s*YR|SF/YR|SF/Yr|per SF per year", "sf_year"),
    (r"/\s*SF\s*/\s*MO|SF/MO|SF/Mo", "sf_month"),
    (r"/\s*AC\b|/\s*Acre", "acre"),
    (r"/\s*SF\b|per SF|/SF", "sf"),
    (r"/\s*Unit\b|per\s+unit", "unit"),
    (r"/\s*YR\b|/\s*Year", "year"),
    (r"/\s*MO\b|/\s*Month", "month"),
)


def parse_price(value):
    """"$581,350 - $1,375,000" / "$41.40 SF/YR" / "$3.45 /SF/MO" / "From $37,301 /YR" /
    "$1,400,000 Starting Bid" / "Price Upon Request" -> {text, min, max, currency, basis}
    (masks keep the text with null numbers; None for an empty value)."""
    text = _clean(value)
    if text is None:
        raw = " ".join(str(value or "").split())
        return {"text": raw, "min": None, "max": None, "currency": None, "basis": None} if raw else None
    amounts = []
    # "$2,112,000 ($550/SF)": the parenthesised figure is a secondary basis
    primary = re.sub(r"\([^)]*\)", " ", text) if _MONEY_RE.search(re.sub(r"\([^)]*\)", " ", text)) else text
    for num, suffix in _MONEY_RE.findall(primary):
        try:
            amount = float(num.replace(",", ""))
        except ValueError:
            continue
        amount *= {"k": 1e3, "m": 1e6, "b": 1e9}.get((suffix or "").lower(), 1)
        amounts.append(amount)
    # the basis is the primary figure's: "$10,495,000 ($2,116.35/SF)" is a total
    # price, its "/SF" belongs to the parenthesised secondary figure
    basis = None
    for pattern, name in _BASIS:
        if re.search(pattern, primary, re.I):
            basis = name
            break
    currency = "USD" if "$" in text else None
    low = min(amounts) if amounts else None
    high = max(amounts) if amounts else None
    return {"text": text, "min": _tidy(low), "max": _tidy(high), "currency": currency, "basis": basis}


def _tidy(number):
    if number is None:
        return None
    return int(number) if float(number).is_integer() else number


def parse_size(value):
    """"901 - 4,592 SF" / "24,279 SF" / "1.46 AC" -> {text, min, max, unit} (unit sf / acre / sm)."""
    text = _clean(value)
    if text is None:
        return None
    units = {"sf": "sf", "ac": "acre", "acre": "acre", "acres": "acre", "sm": "sm"}
    match = _SF_RANGE_RE.search(text)
    if match:
        low, high, unit = match.groups()
        return {"text": text, "min": _tidy(float(low.replace(",", ""))), "max": _tidy(float(high.replace(",", ""))),
                "unit": units.get(unit.lower(), unit.lower())}
    match = _SF_RE.search(text)
    if match:
        num, unit = match.groups()
        amount = _tidy(float(num.replace(",", "")))
        return {"text": text, "min": amount, "max": amount, "unit": units.get(unit.lower(), unit.lower())}
    return {"text": text, "min": None, "max": None, "unit": None}


def _percent(value):
    text = _clean(value)
    if text is None or "%" not in text:
        return None
    return _number(text)


def _metric_value(value):
    """A demographics / fact cell -> (number, unit) with unit percent / usd / None."""
    text = _clean(value)
    if text is None:
        return None, None
    if "%" in text:
        return _number(text), "percent"
    if "$" in text:
        return _number(text), "usd"
    number = _number(text)
    return number, None


# ---- gState ---------------------------------------------------------------------

def gstate(html):
    """window.gState (every printable char shifted +3) -> dict, or None."""
    match = _GSTATE_RE.search(html or "")
    if not match:
        return None
    try:
        raw = match.group(1).encode("utf-8").decode("unicode_escape")
    except Exception:
        return None
    decoded = "".join(chr(((ord(c) - 32 - 3) % 95) + 32) if 32 <= ord(c) <= 126 else c for c in raw)
    try:
        return json.loads(decoded)
    except ValueError:
        return None


def _pins(as_state):
    """gState as.sp "id||lat|lng|...~id||lat|lng|..." -> {id: (lat, lng)}."""
    pins = {}
    for entry in (as_state.get("sp") or "").split("~"):
        parts = entry.split("|")
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        try:
            pins[int(parts[0])] = (float(parts[2]), float(parts[3]))
        except ValueError:
            continue
    return pins


# ---- search page ------------------------------------------------------------------

def _datapoints(card):
    rows = []
    for row in card.select(".placard-data p.data-row"):
        # masks ("Price Upon Request") are datapoints here, so no _clean()
        cells = [" ".join(_text(span).split()) for span in row.find_all("span", recursive=False)
                 if "data-sep" not in (span.get("class") or [])]
        cells = [c for c in cells if c]
        if cells:
            rows.append(cells)
    return rows


def _typed_datapoints(rows, is_lease):
    """The flat datapoint cells -> price / size / counts / years."""
    out = {"price": None, "size": None, "units_count": None, "spaces_count": None, "properties_count": None,
           "year_built": None, "year_renovated": None, "property_type_label": None, "sale_type": None}
    flat = [cell for row in rows for cell in row]
    for index, cell in enumerate(flat):
        low = cell.lower()
        if out["price"] is None and ("$" in cell or "upon request" in low or "negotiable" in low):
            out["price"] = parse_price(cell)
            continue
        if out["size"] is None and _SF_RE.search(cell) and "$" not in cell:
            out["size"] = parse_size(cell)
            continue
        count = _COUNT_RE.search(cell)
        if count:
            number = _int(count.group(1))
            kind = count.group(2).lower()
            if kind.startswith("unit") or kind.startswith("condo"):
                out["units_count"] = number
            elif kind.startswith("space"):
                out["spaces_count"] = number
            elif kind.startswith("propert"):
                out["properties_count"] = number
            continue
        year = _YEAR_BUILT_RE.search(cell)
        if year:
            if "renov" in year.group(1).lower():
                out["year_renovated"] = int(year.group(2))
            else:
                out["year_built"] = int(year.group(2))
            continue
        if index == 0 and out["property_type_label"] is None:
            out["property_type_label"] = cell
        elif low in ("investment", "owner user", "investment or owner user", "owner/user", "investment/owner user"):
            out["sale_type"] = cell
    return out


def _card_photos(card):
    node = card.select_one("[data-carousel-deferred]")
    photos = []
    if node is not None:
        try:
            items = fastjson.loads(node.get("data-carousel-deferred") or "[]")
        except Exception:
            items = []
        for item in items:
            if isinstance(item, dict) and item.get("s"):
                photos.append({"link": item["s"], "caption": _clean(item.get("a"))})
    if not photos:
        for img in card.select("img.embla__slide__img[src]"):
            photos.append({"link": img["src"], "caption": _clean(img.get("alt"))})
    seen, unique = set(), []
    for photo in photos:
        if photo["link"] not in seen:
            seen.add(photo["link"])
            unique.append(photo)
    return unique


def _card_brokers(card):
    brokers = []
    for slide in card.select(".placard-broker .embla__slide"):
        name = _clean(_text(slide.select_one(".broker-name")))
        if not name:
            continue
        photo = slide.select_one("img.broker-photo")
        logo = slide.select_one("img.broker-logo")
        brokers.append({"name": name, "company": _clean(_text(slide.select_one(".broker-company"))),
                        "photo": _clean(photo.get("src")) if photo else None,
                        "company_logo": _clean(logo.get("src")) if logo else None})
    return brokers


def _auction(card):
    banner = card.select_one(".auction-banner")
    countdown = card.select_one("[data-countdown-target]")
    if banner is None and countdown is None and "auction" not in (card.get("class") or []):
        return None
    starts = _clean(countdown.get("data-start-deadline")) if countdown else None
    ends = _clean(countdown.get("data-end-deadline") or countdown.get("data-deadline")) if countdown else None
    live = card.select_one(".has-live-bids")
    bids, extra = {}, {}
    for row in card.select(".auction-live-bid"):
        label = _clean(_text(row.select_one(".auction-live-label"))) or ""
        value = _clean(_text(row.select_one(".auction-live-value")))
        key = _snake(label.rstrip(":"))
        if not key:
            continue
        if value and "$" in value:
            bids[key] = parse_price(value)
        elif value and "%" in value:
            extra[key] = _percent(value)
        else:
            extra[key] = value
    reserve = card.select_one(".auction-live-reserve")
    reserve_text = _clean(_text(reserve)) if reserve else None
    cta = card.select_one(".auction-cta[data-cta-url]")
    classes = " ".join(banner.get("class") or []) if banner else ""
    status = ("complete" if "complete" in classes or "ended" in classes else "live" if "live" in classes
              else "scheduled" if banner is not None else None)
    return {
        "status": status,
        "starts_at": _iso(starts),
        "ends_at": _iso(ends),
        "starting_bid": bids.get("starting_bid"),
        "current_bid": bids.get("current_bid"),
        "bid_increment": bids.get("bid_increment"),
        "buy_now_price": bids.get("buy_now") or bids.get("buy_now_price"),
        "projected_cap_rate": extra.get("proj_cap_rate"),
        "is_reserve_met": (True if "reserve met" in (reserve_text or "").lower() and "not" not in (reserve_text or "").lower()
                           else False if reserve_text else None),
        "has_live_bids": live is not None,
        "auction_listing_id": _int(live.get("data-auction-listing-id")) if live else None,
        "has_buy_now": (card.get("data-gtm-buy-now-enabled") or "").lower() == "true",
        "highlights": [h for h in (_clean(_text(li)) for li in card.select(".auction-highlights li")) if h],
        "documents_link": _link(cta.get("data-cta-url")) if cta else None,
    }


def _iso(value):
    """"2026-11-17T17:00:00.0000000+00:00" -> "2026-11-17T17:00:00+00:00"."""
    value = _clean(value)
    if not value:
        return None
    match = re.match(r"(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}:\d{2}))?(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?", value)
    if not match:
        return value
    date, time, zone = match.groups()
    if not time:
        return date
    return f"{date}T{time}{(zone or '').replace('Z', '+00:00')}"


def parse_search_card(card, pins=None):
    link = card.select_one("a.placard-link")
    href = _link(link.get("href")) if link else None
    listing_id = _int(card.get("data-lk")) or _listing_id(href)
    if not listing_id:
        return None
    transaction = _clean(card.get("data-automation-transaction-type")) or ""
    is_lease = transaction.lower() == "forlease"
    rows = _datapoints(card)
    typed = _typed_datapoints(rows, is_lease)
    rating = card.select_one(".placard-rating-value")
    pin = (pins or {}).get(listing_id)
    listing_type = {"forsale": "sale", "forlease": "lease", "auctions": "auction"}.get(transaction.lower())
    auction = _auction(card)
    if auction and listing_type is None:
        listing_type = "auction"
    return {
        "id": listing_id,
        "link": href,
        "name": _clean(_text(card.select_one(".building-name"))),
        "address": _clean(_text(card.select_one(".placard-address"))),
        "city": _clean(card.get("data-automation-city")),
        "state": _clean(card.get("data-automation-state")),
        "postal_code": _clean(card.get("data-automation-postal-code")),
        "country": _clean(card.get("data-automation-country")),
        "latitude": pin[0] if pin else None,
        "longitude": pin[1] if pin else None,
        "listing_type": listing_type,
        "listing_category": _clean(card.get("data-automation-listing-type")),
        "property_type": _clean(card.get("data-automation-property-type")) or typed["property_type_label"],
        "property_type_label": typed["property_type_label"],
        "price": typed["price"],
        "size": typed["size"],
        "units_count": typed["units_count"],
        "spaces_count": typed["spaces_count"],
        "properties_count": typed["properties_count"],
        "year_built": typed["year_built"],
        "year_renovated": typed["year_renovated"],
        "sale_type": typed["sale_type"],
        "summary": [cell for row in rows for cell in row],
        "description": _clean(_text(card.select_one(".placard-blurb"))),
        "rating": _int(_text(rating)) if rating else None,
        "is_auction": auction is not None,
        "auction": auction,
        "exposure_tier": _clean(card.get("data-gtm-listing_exposure_level")),
        "position": _int(card.get("data-gtm-listing_position")),
        "brokers": _card_brokers(card),
        "photos": _card_photos(card),
    }


def _geography(sc):
    geo = (sc or {}).get("geography") or {}
    bbox = geo.get("bb") or {}
    center = geo.get("l") or {}
    out = {
        "id": geo.get("id"),
        "type": SEARCH_GEO_TYPES.get(geo.get("t")),
        "latitude": center.get("lt"),
        "longitude": center.get("ln"),
        "bounding_box": None,
    }
    if bbox.get("tl") and bbox.get("br"):
        out["bounding_box"] = {"north": bbox["tl"].get("lt"), "south": bbox["br"].get("lt"),
                               "west": bbox["tl"].get("ln"), "east": bbox["br"].get("ln")}
    return out


def is_not_found_page(html):
    """The site answers an unknown place / listing with HTTP 200 and its
    "This listing cannot be found." page (title "LoopNet - #1 in Commercial
    Real Estate Online", path /listingnotfound/)."""
    head = (html or "")[:60000]
    return "This listing cannot be found" in head or "/listingnotfound/" in head[:5000]


def parse_search(html):
    """A search page -> {heading, place, total, is_total_capped, page, geography,
    applied_filters, results}. None when the page is not a search page."""
    state = gstate(html)
    as_state = (state or {}).get("as") or {}
    soup = _soup(html)
    cards = soup.select("article.placard-card[data-lk]")
    if not as_state and not cards:
        return None
    sc = as_state.get("sc") or {}
    if not cards and not sc:
        return None                      # a 404 / error page carries gState but no search state
    pins = _pins(as_state)
    results = [parsed for parsed in (parse_search_card(card, pins) for card in cards) if parsed]
    paging = sc.get("pagingCriteria") or {}
    total = _int(as_state.get("count"))
    cap = _int(as_state.get("mrc")) or 750
    filters = sc.get("filters") or {}
    return {
        "heading": _clean(as_state.get("h1")) or _clean(_text(soup.select_one("h1"))),
        "place": _clean(sc.get("typeaheadDisplay")),
        "total": total,
        "is_total_capped": bool(total is not None and total >= cap),
        "page": _int(paging.get("page")) or 1,
        "items_per_page": _int(paging.get("pageSize")) or 40,
        "geography": _geography(sc),
        "applied_filters": filters or None,
        "results": results,
    }


# ---- listing page -------------------------------------------------------------------

def _rates(node):
    """data-rates='{"SFYr":"$41.40 /SF/YR",...}' -> {sf_year, sf_month, year, month}."""
    raw = node.get("data-rates") if node is not None else None
    if not raw:
        return None
    try:
        rates = fastjson.loads(raw)
    except Exception:
        return None
    if not isinstance(rates, dict):
        return None
    names = {"SFYr": "per_sf_year", "SFMo": "per_sf_month", "AY": "per_year", "AM": "per_month"}
    return {names.get(k, _snake(k)): parse_price(v) for k, v in rates.items() if v}


def _header(soup):
    header = soup.select_one("#addressHeader") or soup.select_one("#topContainer")
    out = {"name": None, "street": None, "city_line": None, "heading_kpis": None, "price_line": None, "rates": None,
           "kpis": []}
    if header is None:
        return out
    h1 = header.select_one("h1")
    if h1 is not None:
        lines = [l for l in (_clean(_text(span)) for span in h1.select(".middle-line")) if l]
        out["name"] = _clean(_text(h1.select_one(".first-line")))
        if len(lines) > 1:
            out["street"], out["city_line"] = lines[0], lines[-1]
        elif lines:
            # one line: "4521 State Highway 121, Plano, TX 75024" or "New York, NY"
            match = re.match(r"^(.*?),\s*((?:[^,]+),\s*[A-Z]{2}(?:\s+[0-9A-Z-]{3,10})?)$", lines[0])
            if match:
                out["street"], out["city_line"] = match.group(1).strip(), match.group(2).strip()
            else:
                out["city_line"] = lines[0]
        if out["name"] is None and lines:
            out["name"] = lines[0]
        out["heading_kpis"] = _clean(_text(h1.select_one(".heading-kpis")))
    last = header.select_one(".last-line")
    if last is not None:
        first = last.find("span", recursive=False)
        out["price_line"] = _clean(_text(first)) if first is not None else None
        out["rates"] = _rates(last.select_one("[data-rates]"))
    out["kpis"] = [k for k in (_clean(_text(v)) for v in header.select(".kpi-value")) if k]
    return out


def _highlights(soup):
    return [h for h in (_clean(_text(li)) for li in soup.select("section.highlights .highlights-list li")) if h]


def _space_cards(soup):
    """The available-spaces cards (lease pages) or table rows (condo sale
    pages) -> {space id: values by field}."""
    cards = {}
    for card in soup.select(".available-spaces-card[data-space-id]"):
        space_id = _clean(card.get("data-space-id"))
        values = {}
        for value in card.select(".available-spaces-card-values__value"):
            field = _snake(value.get("data-automation-field")) or "value"
            values[field] = _clean(_text(value))
            if field == "rate":
                values["rates"] = _rates(value)
        cards[space_id] = {"name": _clean(_text(card.select_one(".available-spaces-card-suite"))), **values}
    for row in soup.select("tr.available-spaces-row[data-space-id]"):
        space_id = _clean(row.get("data-space-id"))
        if space_id in cards:
            continue
        values = {}
        for cell in row.select("td[data-automation-column]"):
            field = _snake(cell.get("data-automation-column")) or "value"
            secondary = cell.select_one(".available-spaces-table__cell-secondary")
            if secondary is not None:
                values[field + "_secondary"] = _clean(_text(secondary))
                secondary.extract()
            values[field] = _clean(_text(cell))
            if field == "rate":
                values["rates"] = _rates(cell)
        cards[space_id] = {"name": values.pop("unit", None) or values.pop("space", None), **values}
    return cards


def _space_details(soup):
    details = {}
    for detail in soup.select(".space-detail[id^=space-detail-]"):
        space_id = (detail.get("id") or "")[len("space-detail-"):]
        fields, rates = {}, None
        for field in detail.select(".space-detail__field"):
            key = _snake(field.get("data-automation-field") or _text(field.select_one(".space-detail__field-label")))
            value_node = field.select_one(".space-detail__field-value")
            fields[key] = _clean(_text(value_node))
            if key in ("rental_rate", "rate") and value_node is not None:
                rates = _rates(value_node) or rates
        description = _clean(_text(detail.select_one(".space-detail__description"), "\n"))
        attachments = [{"name": _clean(a.get("data-attachment-file-name") or _text(a)), "link": _link(a.get("href")),
                        "extension": _clean(a.get("data-attachment-file-extension"))}
                       for a in detail.select(".space-detail__attachments a[href]")]
        media = []
        media_node = detail.select_one("[data-space-media]")
        if media_node is not None:
            try:
                items = fastjson.loads(media_node.get("data-space-media") or "[]")
            except Exception:
                items = []
            for item in items:
                if isinstance(item, dict) and (item.get("url") or item.get("matterportUrl")):
                    media.append({"link": item.get("url") or item.get("matterportUrl"), "thumbnail": item.get("thumbUri"),
                                  "caption": _clean(item.get("caption")), "is_video": bool(item.get("isVideo")),
                                  "is_3d_tour": bool(item.get("isThreeDTour"))})
        details[space_id] = {
            "title": _clean(_text(detail.select_one(".space-detail__title"))),
            "section_title": _clean(_text(detail.select_one(".space-detail__section-title"))),
            "fields": fields, "rates": rates, "description": description,
            "contiguous_note": _clean(_text(detail.select_one(".space-detail__contiguous-message"))),
            "attachments": attachments, "media": media,
        }
    return details


def _spaces(soup):
    cards, details = _space_cards(soup), _space_details(soup)
    spaces = []
    for space_id in list(cards) + [k for k in details if k not in cards]:
        card, detail = cards.get(space_id) or {}, details.get(space_id) or {}
        fields = dict(detail.get("fields") or {})
        size = fields.get("size") or fields.get("unit_size") or card.get("size") or card.get("unit_size")
        rate_text = fields.get("rental_rate") or card.get("rate")
        price_text = fields.get("price") or fields.get("sale_price") or card.get("price")
        # "$2,112,000 ($550/SF)": the parenthesised figure is the per-SF price
        secondary = card.get("price_secondary") or fields.get("price_per_sf")
        if not secondary and price_text:
            match = re.search(r"\((\$[^)]*)\)", price_text)
            secondary = match.group(1) if match else None
        spaces.append({
            "id": _int(space_id),
            "name": detail.get("title") or card.get("name"),
            "use": fields.get("space_use") or fields.get("condo_use") or card.get("space_use") or card.get("condo_use"),
            "size": parse_size(size),
            "rate": parse_price(rate_text) if rate_text else None,
            "rates": detail.get("rates") or card.get("rates"),
            "price": parse_price(price_text) if price_text else None,
            "price_per_sf": parse_price(secondary) if secondary else None,
            "rent_type": fields.get("rent_type"),
            "term": fields.get("term") or card.get("term"),
            "build_out": fields.get("build_out") or card.get("build_out"),
            "availability": fields.get("availability") or card.get("availability"),
            "space_condition": fields.get("space_condition"),
            "layout": fields.get("layout"),
            "private_offices": _int(fields.get("private_offices")),
            "conference_rooms": _int(fields.get("conference_rooms")),
            "sale_type": fields.get("sale_type"),
            "details": fields,
            "description": detail.get("description"),
            "contiguous_note": detail.get("contiguous_note"),
            "attachments": detail.get("attachments") or [],
            "media": detail.get("media") or [],
        })
    return spaces


def _facts(soup):
    facts = {}
    for item in soup.select("#property-facts li.property-facts__item"):
        label = _clean(_text(item.select_one(".property-facts__label")))
        value = _clean(_text(item.select_one(".property-facts__value")))
        if label:
            facts[_snake(label)] = value
        else:
            text = _clean(_text(item.select_one(".property-facts__text")) or _text(item))
            if text and ":" in text:
                key, _, val = text.partition(":")
                facts[_snake(key)] = _clean(val)
    return facts


def _amenities(soup):
    out = {}
    for block in soup.select("#listing-amenities .amenities-category-container"):
        category = _clean(_text(block.select_one(".amenities-category-header"))) or "other"
        names = [n for n in (_clean(_text(li)) for li in block.select("li.amenity-item")) if n]
        if names:
            out[category] = names
    return out


def _sustainability(soup):
    cards = []
    for card in soup.select("#sustainability .sustainability-card"):
        classes = " ".join(card.get("class") or [])
        kind = re.search(r"sustainability-card--([a-z0-9-]+)", classes)
        cards.append({
            "program": kind.group(1).replace("-", " ").upper() if kind else None,
            "score": _int(_text(card.select_one(".sustainability-card__score-value"))),
            "score_total": _int(_text(card.select_one(".sustainability-card__score-total"))),
            "description": _clean(_text(card.select_one(".sustainability-card__description"))),
        })
    return cards


def _document(soup, section_id):
    section = soup.select_one(f"#{section_id}")
    if section is None:
        return None
    expand = section.select_one("a.btn-expand[href], .marketing-brochure-expand a[href]")
    preview = section.select_one("[data-preview-url]")
    locked = bool(section.select_one("i.lock")) or "--locked" in " ".join(section.get("class") or [])
    link = _link(expand.get("href")) if expand else (_link(preview.get("data-preview-url")) if preview else None)
    return {
        "name": _clean(expand.get("title") if expand else _text(section.select_one("canvas[title]")) or None)
                or _clean(_text(section.select_one(".section-title"))),
        "link": link,
        "is_locked": locked or link is None,
    }


def _attachments(soup):
    return [{"name": _clean(a.get("data-attachment-file-name") or _text(a)), "link": _link(a.get("href")),
             "extension": _clean(a.get("data-attachment-file-extension"))}
            for a in soup.select("section.listing-attachments a.content-external-link[href]")]


def _external_links(soup):
    return [{"name": _clean(a.get("title") or _text(a)), "link": _link(a.get("href"))}
            for a in soup.select("section.external-links a[href]")]


def _matterport(soup):
    tours = []
    for frame in soup.select("#matterportViewer iframe[data-src], #matterportViewer iframe[src]"):
        tours.append({"link": _clean(frame.get("data-src") or frame.get("src")),
                      "description": _clean(frame.get("data-description"))})
    return tours


def _commute(soup):
    scores = {}
    for card in soup.select(".commute-score-cards .commute-score-card"):
        divs = card.find_all("div", recursive=False)
        label = _clean(_text(divs[0])) if divs else None
        score = _int(_text(card.select_one(".commute-score")))
        low = (label or "").lower()
        key = ("walk" if "walk" in low else "transit" if "transit" in low else "bike" if "bik" in low
               else "drive" if "driv" in low else _snake(label) or "score")
        scores[key] = {"score": score, "label": label}
    return scores


def _demographics(soup):
    """The listing's trade-area table (desktop grid of row-label / row-data
    cells, or the mobile cards) -> [{metric, unit, 1_mile, 3_mile, 5_mile}]."""
    rows = []
    radii = ["1_mile", "3_mile", "5_mile"]
    header = soup.select_one("#demographics .trade-area-table--header")
    if header is not None:
        radii = [_snake(_text(c)) or f"col_{i}" for i, c in enumerate(header.select(".table-data"))] or radii
    for grid_row in soup.select("#demographics .trade-area-table:not(.trade-area-table--header)"):
        metric = _clean(_text(grid_row.select_one(".row-label")))
        cells = grid_row.select(".row-data")
        if not metric or not cells:
            continue
        row = {"metric": metric, "unit": None}
        for index, cell in enumerate(cells):
            number, unit = _metric_value(_text(cell))
            row[radii[index] if index < len(radii) else f"col_{index}"] = number
            row["unit"] = row["unit"] or unit
        rows.append(row)
    for card in soup.select("#demographics .trade-area-card"):
        metric = _clean(_text(card.select_one(".trade-area-card__header")))
        row = {"metric": metric, "unit": None}
        for item in card.select(".trade-area-card__row"):
            radius = _snake(_text(item.select_one(".radius-label"))) or "value"
            number, unit = _metric_value(_text(item.select_one(".radius-value")))
            row[radius] = number
            row["unit"] = row["unit"] or unit
        rows.append(row)
    return rows


def _team_members(section):
    members = []
    for row in section.select(".broker-team-member-row"):
        name_node = row.select_one(".broker-team-member-name-title a") or row.select_one(".broker-team-member-name-title")
        name, title = _split_name_title(name_node.get("aria-label") if name_node else None)
        if name is None and name_node is not None:
            name, title = _split_name_title(_text(name_node))
        if not name:
            continue
        link = _link(name_node.get("href")) if name_node and name_node.name == "a" else None
        phone = row.select_one("a.broker-team-member-phone-link[href]")
        photo = row.select_one(".bio-photo[data-image]")
        members.append({
            "id": _profile_id(link),
            "name": name, "title": title,
            "link": re.sub(r"/(\d{5,10})/?$", "", link) if link else None,
            "phone": _phone(phone.get("href")) if phone else None,
            "phone_text": _clean(_text(phone.select_one(".broker-team-member-phone-number"))) if phone else None,
            "photo": _clean(photo.get("data-image")) if photo else None,
            "bio": _clean(_text(row.select_one(".broker-team-member-bio"), "\n")),
            "is_power_broker": row.select_one(".power-broker-badge") is not None,
        })
    return members


def _team(soup):
    section = soup.select_one("#broker-biographies")
    if section is None:
        return None
    company_link = section.select_one(".broker-company-header-name a[href]")
    logo = section.select_one("img.broker-company-header-logo")
    link = _link(company_link.get("href")) if company_link else None
    return {
        "type": _clean(section.get("data-team-type")),
        "title": _clean(_text(section.select_one(".section-title"))),
        "company": {"id": _company_id(link), "name": _clean(_text(company_link)) if company_link else
                    (_clean(logo.get("alt")) if logo else None), "link": link,
                    "logo": _clean(logo.get("src")) if logo else None} if (company_link or logo) else None,
        "members": _team_members(section),
    }


def _auction_contact(soup):
    section = soup.select_one("#auction-contact")
    if section is None:
        return None
    phone = section.select_one("a.broker-team-member-phone-link[href]")
    photo = section.select_one(".auction-contact-photo[data-background-image]")
    return {
        "name": _clean(_text(section.select_one(".auction-contact-name"))),
        "phone": _phone(phone.get("href")) if phone else None,
        "phone_text": _clean(_text(phone.select_one(".broker-team-member-phone-number"))) if phone else None,
        "photo": _clean(photo.get("data-background-image")) if photo else None,
        "platform": _clean(_text(section.select_one(".auction-contact-platform-description"))),
        "auctioneer_license": _clean(_text(section.select_one(".auction-contact-license-value"))),
    }


def _owner(soup):
    section = soup.select_one("section.owner-architect-section")
    if section is None:
        return None
    link = section.select_one(".owner-architect-company-header-name a[href]")
    logo = section.select_one("img.owner-architect-logo")
    href = _link(link.get("href")) if link else None
    return {
        "role": _clean(_text(section.select_one(".section-title"))),
        "id": _company_id(href),
        "name": _clean(_text(link)) if link else (_clean(logo.get("alt")) if logo else None),
        "link": href,
        "logo": _clean(logo.get("data-image") or logo.get("src")) if logo else None,
        "description": _clean(_text(section.select_one(".owner-architect-company-bio"), "\n")),
    }


def _timestamps(soup):
    out = {"listing_id": None, "date_on_market": None, "last_updated": None}
    section = soup.select_one("#propertyTimestamp")
    if section is None:
        return out
    for row in section.select(".property-timestamp__row, .property-timestamp__date"):
        label = _clean(_text(row.select_one(".property-timestamp__label"))) or ""
        value = row.select_one(".property-timestamp__value")
        if value is None:
            continue
        low = label.lower()
        if "listing id" in low:
            out["listing_id"] = _int(_text(value))
        elif "date on market" in low:
            out["date_on_market"] = _clean(value.get("datetime")) or _clean(_text(value))
        elif "last updated" in low:
            out["last_updated"] = _clean(value.get("datetime")) or _clean(_text(value))
    return out


def _gallery(as_state):
    photos = []
    for item in as_state.get("mainAttachments") or []:
        if not isinstance(item, dict) or not item.get("uri"):
            continue
        photos.append({"link": item["uri"], "thumbnail": item.get("thumbUri"), "caption": _clean(item.get("description")),
                       "type": _clean(item.get("attachmentTypeDescription")), "width": item.get("width"),
                       "height": item.get("height")})
    return photos


def _ld_listing(blocks):
    """The RealEstateListing block of a listing page -> offers, agents, dates."""
    block = _ld_of_type(blocks, "RealEstateListing") or {}
    offers = []
    for offer in block.get("offers") or []:
        if isinstance(offer, dict):
            offers.append({"name": _clean(offer.get("name")), "price": offer.get("price"),
                           "currency": offer.get("priceCurrency"), "valid_through": _iso(offer.get("validThrough")),
                           "availability": (offer.get("availability") or "").rsplit("/", 1)[-1] or None})
    agents = []
    for agent in block.get("provider") or []:
        if not isinstance(agent, dict):
            continue
        link = agent.get("@id") or ""
        link = link.split("#")[0] or None
        address = agent.get("address") or {}
        agents.append({"id": _profile_id(link), "name": _clean(agent.get("name")),
                       "link": re.sub(r"/(\d{5,10})/?$", "", link) if link else None,
                       "phone": _phone(agent.get("telephone")), "company": _clean((agent.get("memberOf") or {}).get("name")),
                       "city": _clean(address.get("addressLocality")), "state": _clean(address.get("addressRegion")),
                       "photo": (agent.get("image") or {}).get("url") if isinstance(agent.get("image"), dict) else None,
                       "bio": _clean(agent.get("description"))})
    location = ((block.get("contentLocation") or {}).get("address") or {})
    return {
        "offers": offers, "agents": agents,
        "name": _clean(block.get("name")), "description": _clean(block.get("description")),
        "date_modified": _clean(block.get("dateModified")),
        "address": {"street": _clean(location.get("streetAddress")), "city": _clean(location.get("addressLocality")),
                    "state": _clean(location.get("addressRegion")), "postal_code": _clean(location.get("postalCode")),
                    "country": _clean(location.get("addressCountry"))} if location else None,
        "collections": [p.get("@id", "").split("#")[0] for p in block.get("isPartOf") or [] if isinstance(p, dict)],
    }


_LISTING_TYPE_LABEL = {"ForSale": "sale", "ForLease": "lease", "ForAuction": "auction"}


_HEADLINE_TYPE = re.compile(r"^(.+?)\s+for\s+(?:sale|lease|auction)\b", re.I)
_KPI_PERCENT = re.compile(r"^\s*([\d.,]+)\s*%\s*(.+?)\s*$")


def _kpi_percent(kpis, label):
    """A header KPI "5.75% Cap Rate" / "56% Leased" -> 5.75 / 56 for `label`
    ("cap rate" / "leased"); the facts table does not always repeat them."""
    for kpi in kpis or []:
        match = _KPI_PERCENT.match(kpi or "")
        if match and match.group(2).lower() == label:
            return _number(match.group(1))
    return None


def _headline_type(heading):
    """"Retail for Sale 4,959 SF" -> "Retail": the type the page headlines
    when its facts list has no Property Type row."""
    match = _HEADLINE_TYPE.match(heading or "")
    return _clean(match.group(1)) if match else None


def _headline_building_size(kpis, spaces, price, price_per_sf):
    """The headline's SF figure as the building size when the facts list has
    none, only where the page itself proves it: a whole-building sale (no
    spaces / condo units, whose sizes the headline would show instead), one
    SF figure, and price / price-per-SF landing on it within 1 %."""
    if spaces or not price or not price_per_sf or not price.get("min") or not price_per_sf.get("min"):
        return None
    for kpi in (kpis or [])[1:]:
        size = parse_size(kpi)
        if size and size.get("unit") == "sf" and size.get("min") and size.get("min") == size.get("max"):
            implied = price["min"] / price_per_sf["min"]
            return size if abs(implied - size["min"]) <= 0.01 * size["min"] else None
    return None


def parse_listing(html, listing_id=None, link=None):
    """A listing page -> the full record. None when the page is not a listing."""
    state = gstate(html)
    as_state = (state or {}).get("as") or {}
    soup = _soup(html)
    header = _header(soup)
    if not as_state.get("listingId") and header["name"] is None and soup.select_one("#propertyTimestamp") is None:
        return None
    blocks = _ld_json(soup)
    ld = _ld_listing(blocks)
    stamps = _timestamps(soup)
    facts = _facts(soup)
    geo = ((as_state.get("geography") or [{}])[0] or {}).get("l") or {}
    city, state_code, postal = _split_city_state(header["city_line"])
    address = ld["address"] or {}
    watch = _clean(as_state.get("watchPropertyType"))
    listing_type = _LISTING_TYPE_LABEL.get(watch)
    heading = (header["heading_kpis"] or "").lower()
    if "auction" in heading or soup.select_one("#auction-contact") is not None:
        listing_type = "auction"
    elif listing_type is None and header["kpis"]:
        listing_type = "lease" if "lease" in heading else ("sale" if "sale" in heading else None)
    price = parse_price(header["price_line"]) if header["price_line"] else None
    starting_bid = price if price and "starting bid" in (price["text"] or "").lower() else None
    secure = soup.select_one("#secure-information")
    team = _team(soup)
    spaces = _spaces(soup)
    sale_type = facts.get("sale_type") or next((sp["sale_type"] for sp in spaces if sp.get("sale_type")), None)
    price_per_sf = parse_price(facts.get("price_per_sf")) if facts.get("price_per_sf") else None
    building_size = (parse_size(facts.get("building_size") or facts.get("total_building_size"))
                     or _headline_building_size(header["kpis"], spaces, price, price_per_sf))
    canonical = soup.select_one('link[rel="canonical"]') or soup.select_one('meta[property="og:url"]')
    page_link = _clean(canonical.get("href") or canonical.get("content")) if canonical else None
    return {
        "id": _int(as_state.get("listingId")) or stamps["listing_id"] or listing_id,
        "link": page_link or link,
        "name": header["name"],
        "address": header["street"] or address.get("street"),
        "city": city or address.get("city"),
        "state": state_code or address.get("state"),
        "postal_code": postal or address.get("postal_code"),
        "country": address.get("country"),
        "latitude": geo.get("lt"),
        "longitude": geo.get("ln"),
        "listing_type": listing_type,
        "headline": header["heading_kpis"],
        "summary": header["kpis"],
        "price": price if not starting_bid else None,
        "rates": header["rates"],
        "cap_rate": _percent(facts.get("cap_rate")) or _kpi_percent(header["kpis"], "cap rate"),
        "percent_leased": _percent(facts.get("percent_leased")) or _kpi_percent(header["kpis"], "leased"),
        "price_per_sf": price_per_sf,
        "net_operating_income": parse_price(facts.get("net_operating_income") or facts.get("noi")) if (facts.get("net_operating_income") or facts.get("noi")) else None,
        "sale_type": sale_type,
        "sale_condition": facts.get("sale_condition"),
        "property_type": facts.get("property_type") or facts.get("building_type") or _headline_type(header["heading_kpis"]),
        "property_subtype": facts.get("property_subtype"),
        "building_class": facts.get("building_class"),
        "building_size": building_size,
        "lot_size": parse_size(facts.get("lot_size") or facts.get("total_land_area")),
        "year_built": _int(facts.get("year_built")),
        "year_renovated": _int(facts.get("year_renovated")),
        "floors": _int(facts.get("floors") or facts.get("building_height")),
        "zoning": facts.get("zoning"),
        "status": facts.get("status"),
        "rating": _int(facts.get("loopnet_rating")),
        "property_facts": facts,
        "highlights": _highlights(soup),
        "description": _clean(_text(soup.select_one("#note-summary-overview .overview-content"), "\n")),
        "description_title": _clean(_text(soup.select_one("#note-summary-overview .section-title"))),
        "spaces": spaces,
        "amenities": _amenities(soup),
        "sustainability": _sustainability(soup),
        "commute_scores": _commute(soup),
        "demographics": _demographics(soup),
        "market_narrative": {"title": _clean(_text(soup.select_one("#market-narrative .section-title"))),
                             "text": _clean(_text(soup.select_one("#market-narrative .market-narrative-content"), "\n"))}
                            if soup.select_one("#market-narrative") else None,
        "brochure": _document(soup, "marketing-brochure"),
        "offering_memorandum": _document(soup, "offering-memorandum"),
        "has_secure_information": secure is not None,
        "is_secure_information_locked": bool(secure is not None and ("--locked" in " ".join(secure.get("class") or [])
                                                                       or secure.select_one("i.lock") is not None)),
        "attachments": _attachments(soup),
        "external_links": _external_links(soup),
        "virtual_tours": _matterport(soup),
        "photos": _gallery(as_state),
        "photos_count": len(_gallery(as_state)),
        "offers": ld["offers"],
        "auction": {"starting_bid": starting_bid, "ends_at": next((o["valid_through"] for o in ld["offers"] if o.get("valid_through")), None),
                    "contact": _auction_contact(soup)} if listing_type == "auction" else None,
        "team": team,
        "brokers": (team or {}).get("members") or ld["agents"],
        "contact_phone": _phone((soup.select_one(".contact-box__cta[data-phone-dial]") or {}).get("data-phone-dial")
                                if soup.select_one(".contact-box__cta[data-phone-dial]") else None),
        "owner": _owner(soup),
        "breadcrumbs": [b for b in (_clean(_text(c)) for c in soup.select(".breadcrumbs__crumb")) if b],
        "is_off_market": bool(as_state.get("isOffMarket")),
        "date_on_market": stamps["date_on_market"],
        "last_updated": stamps["last_updated"] or ld["date_modified"],
    }


# ---- broker directory + search -------------------------------------------------------------

def _photo(src):
    """A broker photo -> its absolute link; None for the site's relative
    no-photo placeholder (/modules/brokerdirectory/.../no-photo.svg)."""
    src = _clean(src)
    if not src or "no-photo" in src:
        return None
    return _link(src)


def _name_and_address(text):
    """"The Baker Building | 2256 Barry Ave" -> (name, address); a listing
    without a name reads "| 8925 W Olympic Blvd" and takes the address as
    its name, like the listing page does."""
    text = _clean(text)
    if not text:
        return None, None
    if "|" not in text:
        return text, None
    name, _, address = text.partition("|")
    name, address = _clean(name), _clean(address)
    return name or address, address


def _size_and_type(text):
    """"5,000 SF / Office" -> ("5,000 SF / Office", size, "Office"); a
    listing without a size reads "/ Retail" -> ("Retail", None, "Retail")."""
    text = _clean(text)
    if not text:
        return None, None, None
    if text.startswith("/"):
        size_text, kind = "", text[1:]
    elif " / " in text:
        size_text, _, kind = text.partition(" / ")
    elif re.search(r"\d", text):
        size_text, kind = text, ""
    else:
        size_text, kind = "", text
    size_text, kind = size_text.strip(), kind.strip()
    summary = " / ".join(part for part in (size_text, kind) if part) or None
    return summary, (parse_size(size_text) if size_text else None), (kind or None)


def parse_broker_card(card):
    name_link = card.select_one(".broker-detail h4 a")
    href = _link(name_link.get("ng-href") or name_link.get("href")) if name_link else None
    name = _clean(_text(name_link)) if name_link else None
    if not name:
        return None
    phones = {}
    for row in card.select("p.contact-number"):
        kind = _clean(_text(row.find("i"))) or "phone"
        number = _clean(_text(row).replace(kind, "", 1))
        if number:
            phones[kind.lower()] = _phone(number)
    oneline = _clean(_text(card.select_one(".broker-oneline")))
    title = oneline.split(" at ")[0].strip() if oneline and " at " in oneline else oneline
    photo = card.select_one(".broker-photo img")
    logo = card.select_one("img.broker-firm-logo")
    city, state, _ = _split_city_state(_text(card.select_one(".company-location .location")))
    return {
        "id": _profile_id(href),
        "name": name,
        "link": href,
        "title": title or None,
        "company": _clean(_text(card.select_one(".company-location .company"))),
        "city": city, "state": state,
        "listings_count": _int(_text(card.select_one(".listing-count"))),
        "languages": [l for l in (_clean(_text(s)) for s in card.select(".broker-languages .language")) if l],
        "office_phone": phones.get("office"),
        "mobile_phone": phones.get("mobile"),
        "phones": phones or None,
        "has_email_form": card.select_one("a.broker-email") is not None,
        "photo": _photo(photo.get("src")) if photo else None,
        "company_logo": _clean(logo.get("src")) if logo else None,
    }


def parse_broker_directory(html):
    """A directory page or a broker search result -> {heading, results, has_next, has_prev}."""
    soup = _soup(html)
    cards = soup.select(".search-result-placard")
    heading = _clean(_text(soup.select_one(".caption-sorting h1, h1.title-primary")))
    if not cards and heading is None and soup.select_one("section.search-results-wrap") is None:
        return None
    nav = soup.select_one(".page-navigation")
    has_next = has_prev = False
    if nav is not None:
        for a in nav.select("a"):
            target = _clean(a.get("ng-href") or a.get("href"))
            text = _text(a).lower()
            if "next" in text and target:
                has_next = True
            if "prev" in text and target:
                has_prev = True
    return {
        "heading": heading,
        "results": [r for r in (parse_broker_card(c) for c in cards) if r],
        "has_next": has_next,
        "has_prev": has_prev,
    }


# ---- broker profile ---------------------------------------------------------------------

def parse_broker_profile(html, broker_id=None):
    soup = _soup(html)
    root = soup.select_one("#fgBrokerDetails")
    name = _clean(_text(soup.select_one("h1.bd-content-highlight")))
    if root is None or not name:
        return None
    blocks = _ld_json(soup)
    person = _ld_of_type(blocks, "RealEstateAgent") or _ld_of_type(blocks, "Person") or {}
    title_line = _clean(_text(soup.select_one("h2.bd-content-title")))
    title, company_name = (title_line.split(", ", 1) + [None])[:2] if title_line else (None, None)
    skills = {}
    for item in soup.select(".bd-skill-item"):
        label = _snake(_text(item.select_one(".bd-skill-title")))
        content = _clean(_text(item.select_one(".bd-skill-content")))
        skills[label] = [c.strip() for c in content.split(",") if c.strip()] if content else []
    company_node = soup.select_one('#company-section [data-url*="/profile/company/"]')
    company_id = _id_from_link(company_node.get("data-url") if company_node else "", r"/profile/company/([a-z0-9]{6,12})")
    member = person.get("memberOf") or {}
    phones = [p for p in (_clean(_text(s)) for s in soup.select(".bd-header-modules-desktop-all-phones span")) if p]
    phone = _phone(person.get("telephone")) or (_phone(phones[0]) if phones else None)
    listings = []
    catalog = person.get("hasOfferCatalog") or {}
    for item in catalog.get("itemListElement") or []:
        if not isinstance(item, dict):
            continue
        address = ((item.get("contentLocation") or {}).get("address") or {})
        link = _clean(item.get("url")) or (item.get("@id") or "").split("#")[0] or None
        listing_name, listing_address = _name_and_address(item.get("name"))
        summary, size, kind = _size_and_type(item.get("description"))
        listings.append({"id": _listing_id(link), "name": listing_name, "address": listing_address, "link": link,
                         "summary": summary, "property_type": kind, "size": size,
                         "image": (item.get("image") or {}).get("url") if isinstance(item.get("image"), dict) else None,
                         "city": _clean(address.get("addressLocality")), "state": _clean(address.get("addressRegion")),
                         "postal_code": _clean(address.get("postalCode")), "country": _clean(address.get("addressCountry"))})
    photo = soup.select_one("img.bd-content-photo")
    address = person.get("address") or {}
    city, state, postal = _split_city_state(_text(soup.select_one(".bd-content-location")))
    crumbs = [c for c in (_clean(_text(li)) for li in soup.select(".broker-details__breadcrumb li")) if c and c != "/"]
    canonical = soup.select_one('link[rel="canonical"]')
    return {
        "id": broker_id or _profile_id(_clean(canonical.get("href")) if canonical else None),
        "name": name,
        "link": _clean(canonical.get("href")) if canonical else None,
        "title": title,
        "company": {"id": company_id, "name": company_name or _clean(member.get("name")),
                    "link": f"{SITE}/company/{_snake(company_name or member.get('name') or 'company').replace('_', '-')}/{company_id}/" if company_id else None,
                    "website": _clean(member.get("url")), "logo": (member.get("logo") or {}).get("url") if isinstance(member.get("logo"), dict) else None},
        "city": city or _clean(address.get("addressLocality")),
        "state": state or _clean(address.get("addressRegion")),
        "postal_code": postal,
        "tagline": _clean(_text(soup.select_one(".bd-content-tagline"))),
        "phone": phone,
        "phones": [_phone(p) for p in phones] or ([phone] if phone else []),
        "photo": _photo(photo.get("src")) if photo else None,
        "specialties": skills.get("specialties") or [],
        "property_types": skills.get("property_types") or [],
        "markets": skills.get("markets") or [],
        "languages": skills.get("languages") or [],
        "bio": _clean(_text(soup.select_one("#bdBio"), "\n")),
        "listings_count": _int(catalog.get("numberOfItems")),
        "listings": listings,
        "breadcrumbs": crumbs,
    }


# ---- company page -----------------------------------------------------------------------

def _company_listing(article):
    link_node = article.select_one("header a.left-h4[href]") or article.select_one("a[href*='/Listing/']")
    href = _link(link_node.get("href")) if link_node else None
    listing_id = _int(article.get("data-id")) or _listing_id(href)
    if not listing_id:
        return None
    points = [p for p in (_clean(_text(li)) for li in article.select(".data-points-a li")) if p]
    price_node = article.select_one(".data-points-a li[name=Price]")
    price = parse_price(_text(price_node)) if price_node else None
    size = next((parse_size(p) for p in points if _SF_RE.search(p) and "$" not in p), None)
    year = next((int(m.group(2)) for p in points for m in [_YEAR_BUILT_RE.search(p)] if m), None)
    rating = next((_int(m.group(1)) for p in points for m in [re.search(r"(\d)\s*Star", p)] if m), None)
    contacts = []
    for li in article.select("ul.contacts li.contact"):
        first = _clean(_text(li.select_one(".first-name")))
        last = _clean(_text(li.select_one(".last-name")))
        photo = li.select_one(".contact-photo")
        name = " ".join(p for p in (first, last) if p) or _clean(li.get("title"))
        if name:
            contacts.append({"name": name, "photo": _bg_image(photo.get("style")) if photo else None})
    city, state, postal = _split_city_state(_text(article.select_one("header .right-h6")))
    image = article.select_one("figure[style]")
    kind = _clean(article.get("gtm-listing-search-type"))
    return {
        "id": listing_id,
        "link": href,
        "address": _clean(_text(link_node)) if link_node else None,
        "city": city or _clean(article.get("gtm-listing-city")),
        "state": state or _clean(article.get("gtm-listing-state")),
        "postal_code": postal or _clean(article.get("gtm-listing-zip")),
        "country": _clean(article.get("gtm-listing-country")),
        "listing_type": {"FS": "sale", "FL": "lease", "AU": "auction"}.get(kind, kind.lower() if kind else None),
        "listing_category": _clean(article.get("gtm-listing-type-name")),
        "property_type": _clean(article.get("gtm-listing-property-type-name")),
        "space_use": _clean(article.get("gtm-listing-space-use")),
        "headline": _clean(_text(article.select_one("header .right-h4"))),
        "price": price,
        "size": size,
        "year_built": year,
        "rating": rating,
        "summary": points,
        "description": _clean(_text(article.select_one(".data-points-b li"))),
        "exposure_tier": _clean(article.get("gtm-listing-exposure-level")),
        "image": _bg_image(image.get("style")) if image else None,
        "brokers": contacts,
    }


def parse_company(html, company_id=None):
    soup = _soup(html)
    info = soup.select_one("section.company-info")
    if info is None:
        return None
    blocks = _ld_json(soup)
    site = _ld_of_type(blocks, "WebSite") or {}
    publisher = site.get("publisher") or {}
    address = publisher.get("address") or {}
    name = _clean(site.get("name")) or _clean(_text(info.select_one("h1.company-info__title-name")))
    phone = info.select_one("a.company-info__title-phone__number[href]")
    logo = info.select_one(".company-info__bio-logo__img[style]")
    city, state, postal = _split_city_state(_text(info.select_one(".company-info__title-address-state")))
    contacts = []
    for node in soup.select(".company-brokers__broker"):
        link = node.select_one(".company-brokers__broker-name a[href]")
        href = _link(link.get("href")) if link else None
        tel = node.select_one("a.company-brokers__broker-phone__number[href]")
        img = node.select_one("a.company-brokers__broker-img[style]")
        if link is None:
            continue
        contacts.append({"id": _profile_id(href), "name": _clean(_text(link)), "link": href,
                         "phone": _phone(tel.get("href")) if tel else None,
                         "photo": _bg_image(img.get("style")) if img else None})
    listings = [l for l in (_company_listing(a) for a in soup.select(".company-listings__content-placards article.placard[data-id]")) if l]
    pages = set()
    for a in soup.select("a[href*='/company/']"):
        match = re.search(r"/company/[^/]+/[a-z0-9]{6,12}/(\d+)/?$", a.get("href") or "", re.I)
        if match:
            pages.add(int(match.group(1)))
    canonical = soup.select_one('link[rel="canonical"]')
    link = _clean(canonical.get("href")) if canonical else None
    return {
        "id": company_id or _company_id(link),
        "name": name,
        "link": re.sub(r"/\d+/?$", "/", link) if link else None,
        "website": _clean(site.get("url")),
        "logo": _bg_image(logo.get("style")) if logo else (_clean(publisher.get("logo")) or None),
        "address": _clean(_text(info.select_one(".company-info__title-address-street"))) or _clean(address.get("streetaddress")),
        "city": city or _clean(address.get("addressLocality")),
        "state": state or _clean(address.get("addressRegion")),
        "postal_code": postal or _clean(address.get("postalCode")),
        "country": _clean(address.get("addressCountry")),
        "phone": _phone(phone.get("href")) if phone else None,
        "description": _clean(_text(info.select_one(".company-info__bio-about__text"), "\n")) or _clean(site.get("Description")),
        "contacts": contacts,
        "contacts_count": len(contacts),
        "listings": listings,
        "listing_pages": max(pages) if pages else (1 if listings else 0),
    }


# ---- property record ---------------------------------------------------------------------

_RECORD_KEYS = {
    "Address": "address", "ApnComps": "parcel_number", "LegalDescription": "legal_description", "LandUse": "land_use",
    "CountyName": "county", "ZoningDescription": "zoning", "StateName": "state_name", "FloodZone": "flood_zone",
    "Lot": "lot_number", "TaxYear": "tax_year", "LotAcresTotal": "lot_size", "AssessmentYear": "assessment_year",
    "SubmarketName": "submarket", "Census": "census_tract", "ResearchMarketName": "market",
    "BuildingSquareFeetTotal": "total_size", "CBSADescription": "cbsa",
}


def _record_details(soup):
    details = {}
    for cell in soup.select("#detailsInf [data-automation-id]"):
        key = cell.get("data-automation-id")
        label = _clean(_text(cell.select_one(".assessment-key label")))
        value = _clean(_text(cell.select_one(".assessment-value")))
        details[_RECORD_KEYS.get(key) or _snake(label) or _snake(key)] = value
    return details


def _nearby_listings(soup):
    out = []
    for article in soup.select("section.top-listings-nearby article.placard"):
        link = article.select_one(".listing-info-wrapper a[href]") or article.select_one("a.listing-image[href]")
        href = _link(link.get("href")) if link else None
        paragraphs = [p for p in (_clean(_text(p)) for p in article.select(".listing-info-wrapper p")) if p]
        image = article.select_one(".image[style]")
        price = next((parse_price(p) for p in paragraphs if "$" in p), None)
        size = next((parse_size(p) for p in paragraphs if _SF_RE.search(p) and "$" not in p), None)
        city, state, postal = _split_city_state(paragraphs[0] if paragraphs else None)
        out.append({"id": _int(article.get("data-id")) or _listing_id(href), "link": href,
                    "address": _clean(_text(link)) if link else None, "city": city, "state": state, "postal_code": postal,
                    "price": price, "size": size,
                    "property_type": _clean(_text(article.select_one("p.listing-type"))) or _clean(article.get("gtm-listing-property-type-name")),
                    "listing_type": {"FS": "sale", "FL": "lease"}.get(_clean(article.get("gtm-listing-search-type"))),
                    "image": _bg_image(image.get("style")) if image else None})
    return out


def _record_demographics(soup):
    rows = []
    radii = None
    for row in soup.select("section.demographics > .flex"):
        label = _clean(_text(row.select_one(".flex-half:not(.text-uppercase)") or row.find("div")))
        cols = [_clean(_text(c)) for c in row.select(".flex-half.text-uppercase .flex-third")]
        if "first-row" in " ".join((row.select_one(".flex-half.text-uppercase") or {}).get("class", []) if row.select_one(".flex-half.text-uppercase") else []):
            radii = [_snake(c) for c in cols]
            continue
        if not label or not cols:
            continue
        entry = {"metric": label, "unit": None}
        for index, cell in enumerate(cols):
            number, unit = _metric_value(cell)
            key = radii[index] if radii and index < len(radii) else f"col_{index}"
            entry[key] = number
            entry["unit"] = entry["unit"] or unit
        rows.append(entry)
    return rows


def _transportation(soup):
    out = []
    section = soup.select_one("section.public-transportation")
    if section is None:
        return out
    category = None
    for row in section.select(":scope > .flex"):
        title = row.select_one(".transportation-title[data-automation-id$=-Title]")
        if title is not None:
            category = _clean(_text(title))
            continue
        name = _clean(_text(row.select_one(".transit-description")))
        drive = _clean(_text(row.select_one(".drive-column")))
        walk = _clean(_text(row.select_one(".walk-column")))
        distance = _clean(_text(row.select_one(".distance-column")))
        if not (drive or walk or distance):
            continue
        out.append({"category": category, "name": name, "drive_time": drive, "walk_time": walk, "distance": distance,
                    "distance_miles": _number(distance) if distance and "mi" in distance else None})
    return out


def _nearby_properties(soup):
    out = []
    for row in soup.select("section.nearby-properties .flex.address-row"):
        link = row.select_one(".address a[href]")
        cells = [_clean(_text(c)) for c in row.select(".second .flex-fourth")]
        cells += [None] * (4 - len(cells))
        href = _link(link.get("href")) if link else None
        out.append({"id": _id_from_link(href, r"/property/[^/]+/([0-9]{3,6}-[A-Za-z0-9._-]+)/?"),
                    "address": _clean(_text(link)) if link else None, "link": href,
                    "land_use": cells[0], "total_size": parse_size(cells[1]), "lot_size": parse_size(cells[2]), "zoning": cells[3]})
    return out


def parse_property_record(html, record_id=None):
    soup = _soup(html)
    title = _clean(_text(soup.select_one("h1.main-title")))
    details = _record_details(soup)
    if not title and not details:
        return None
    blocks = _ld_json(soup)
    place = _ld_of_type(blocks, "Place") or {}
    address = place.get("address") or {}
    photos = []
    for img in soup.select("#photo-gallery-container img[src]"):
        src = _clean(img.get("src"))
        if src and src not in photos:
            photos.append(src)
    canonical = soup.select_one('link[rel="canonical"]')
    link = _clean(canonical.get("href")) if canonical else _clean(place.get("url"))
    contained = [c.get("name") for c in place.get("containedInPlace") or [] if isinstance(c, dict) and c.get("name")]
    return {
        "id": record_id or _id_from_link(link, r"/property/[^/]+/([0-9]{3,6}-[A-Za-z0-9._-]+)/?"),
        "link": link,
        "name": title,
        "address": details.get("address") or _clean(address.get("streetAddress")),
        "city": _clean(address.get("addressLocality")),
        "state": _clean(address.get("addressRegion")),
        "postal_code": _clean(address.get("postalCode")),
        "country": _clean(address.get("addressCountry")),
        "parcel_number": details.get("parcel_number"),
        "legal_description": details.get("legal_description"),
        "land_use": details.get("land_use"),
        "zoning": details.get("zoning"),
        "county": details.get("county"),
        "flood_zone": details.get("flood_zone"),
        "lot_number": details.get("lot_number"),
        "lot_size": parse_size(details.get("lot_size")),
        "total_size": parse_size(details.get("total_size")),
        "tax_year": _int(details.get("tax_year")),
        "assessment_year": _int(details.get("assessment_year")),
        "submarket": details.get("submarket"),
        "market": details.get("market"),
        "cbsa": details.get("cbsa"),
        "census_tract": details.get("census_tract"),
        "details": details,
        "description": _clean(place.get("description")),
        "contained_in": contained,
        "photos": photos,
        "nearby_listings": _nearby_listings(soup),
        "demographics": _record_demographics(soup),
        "public_transportation": _transportation(soup),
        "nearby_properties": _nearby_properties(soup),
    }


# ---- JSON services ------------------------------------------------------------------------

def parse_geography_lookup(rows):
    """services/geography/lookup rows -> places (section headers and empty ids dropped)."""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        kind = geo_type(row)          # a type-9 row without a County is a point of interest, not a county
        if kind == "header" or not _clean(row.get("ID")):
            continue
        address = row.get("Address") or {}
        location = row.get("Location") or {}
        bbox = row.get("BoundingBox") or {}
        upper, lower = bbox.get("UpperLeft") or {}, bbox.get("LowerRight") or {}
        display = _clean(row.get("Display"))
        out.append({
            "id": _clean(row.get("ID")),
            "name": display,
            "display": _clean(row.get("TypeaheadUIDisplay")) or display,
            "type": kind,
            "slug": geo_slug(row) if kind in ("city", "postal_code", "county", "state", "country", "neighborhood", "market", "submarket") else None,
            "street": " ".join(p for p in (_clean(address.get("StreetNumber")), _clean(address.get("StreetName"))) if p) or None,
            "building_name": _clean(address.get("BuildingName") or address.get("EntityName")),
            "city": _clean(address.get("City")),
            "state": _clean(address.get("State")),
            "state_name": _clean(address.get("SubdivisionName")),
            "postal_code": _clean(address.get("PostalCode")),
            "country": _clean(address.get("CountryCode")),
            "latitude": location.get("y"),
            "longitude": location.get("x"),
            "bounding_box": {"north": upper.get("y"), "south": lower.get("y"), "west": upper.get("x"), "east": lower.get("x")}
                            if upper and lower else None,
            "property_type_id": _int(row.get("PropertyTypeId")),
        })
    return out


def parse_traffic(rows):
    """services/listing/trafficpinprofile rows -> traffic counts (AADT)."""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        coordinate = row.get("Coordinate") or {}
        out.append({
            "street": _clean(row.get("CollectionStreet")),
            "cross_street": _clean(row.get("CrossStreet")),
            "cross_street_direction": _clean(row.get("CrossStreetDirection")),
            "traffic_count": _int(row.get("TrafficCount")) or _int(row.get("TrafficVolumn")),
            "year": _int(row.get("Year")),
            "distance_miles": _number(row.get("Distance")),
            "latitude": coordinate.get("latitude"),
            "longitude": coordinate.get("longitude"),
        })
    return out


def parse_mini_placards(rows):
    """service/mini-placards rows -> {listing id: {link, address, city_line, property_type, photo, is_auction}}."""
    out = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        listing_id = _int(row.get("listingId"))
        card = _soup(row.get("placardHtml") or "")
        link = card.select_one("a.mini-placard-link[href]")
        photo = card.select_one(".mini-placard-photo[style]")
        if not listing_id:
            continue
        out[listing_id] = {
            "link": _link(link.get("href")) if link else None,
            "address": _clean(_text(card.select_one(".mini-placard-address"))),
            "city_line": _clean(_text(card.select_one(".mini-placard-line2"))),
            "property_type": _clean(_text(card.select_one(".mini-placard-point"))),
            "photo": _bg_image(photo.get("style")) if photo else None,
            "is_auction": bool(row.get("isAuction")),
        }
    return out
