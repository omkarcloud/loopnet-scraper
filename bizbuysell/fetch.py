"""BizBuySell transport: plain curl_cffi with browser-impersonated TLS, no
browser, no cookies kept. Egress: the pod's own IP by default
(config.bizbuysell_proxy(), knob BIZBUYSELL_EXIT); a block moves every new
session to the fallback tier (BIZBUYSELL_FALLBACK_EXIT, a sticky
datacenter proxy exit) for BIZBUYSELL_BLOCK_COOLDOWN seconds. Pod
probe 2026-10-31 (scrapers-patchright-depl-68b5779f9c-7wt8m,
tools/egress_probe.py): every surface below answers 200 on the pod's own
IP, on 2/2 datacenter and 2/2 residential ports.

Akamai Bot Manager fronts the site and keys its rules on the PATH, not the
exit: the homepage, un-numbered search pages, listing pages, broker pages
and franchise pages answer a press-and-hold challenge shell (2.6 KB,
`sec-if-cpt`), while the JSON APIs and the listing page's `/amp/` variant
are open. Only the `chrome` impersonation passes (safari / edge / firefox
profiles are 403 everywhere). A session that carries Akamai's cookies
(`ak_bmsc`, `bm_s`) from an HTML page gets 403 on the APIs, so cookies are
cleared before every request.

Upstream surfaces (all keyed on siteId 20 / languageId 10):

  * SEARCH     POST /api/search/BbsSearchListingsLive  {criteria}  -> listing
               cards (howMany up to 500; total clamped at 10,000; 6-10 ad
               rows per page with listNumber null). Keyword, states /
               counties, categories, listing types, price / cash-flow /
               revenue ranges, days listed / modified, established-after,
               seller-financing / home-based / absentee / price-reduced /
               SBA flags, sortList all apply server-side.
  * COUNTS     POST /_api/bff/v2/BbsBfsSearchResultsCounts {criteria} ->
               result count per listing type.
  * LISTING    GET  /business-opportunity/<slug>/<id>/amp/ -> the full
               legacy listing page (financials, description, detailed
               information, location, photos, listed-by, seller phone,
               ld+json). An id alone is resolved first: GET
               /business-opportunity/x/<id>/amp/ with redirects off answers
               301 Location = the canonical link (404 for an unknown id).
  * BROKERS    POST /_api/bff/v2/brokerSearch {criteria} -> broker profiles
               (howMany up to 100; locations / keywordPhrases / accounts).
               POST /_api/bff/v2/SearchBrokerProfilesTypeahead {keyword}
               -> name matches with account + brokerProfileId.
  * FRANCHISES POST /_api/bff/v2/LoopNetFranchiseSearchResults
               {franchiseSearchCriteria} -> franchise cards (howMany up to
               200; regions / bbsCategories / investmentMin / investmentMax).
               POST /api/search/GetFranchiseDetail {seoName} -> the brochure
               (status 4 "Franchise not found" for an unknown slug).
  * LISTS      GET  /api/Resource/GetBfsCategories, POST
               /api/Resource/GetCountiesByRegion (every US county).

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  BizBuySellUpstreamError  transport failure / 5xx / odd JSON  — retryable
  BizBuySellBlocked        403 / 429 / challenge shell          — retryable
  BizBuySellBadRequest     upstream 400                         — never retried
  BizBuySellNotFound       unknown listing / franchise / broker — never retried
"""
import json
import fastjson
import os
import re
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from bizbuysell.refs import LANGUAGE_ID, SITE, SITE_ID

IMPERSONATE = "chrome"
PAGE_TIMEOUT = 40     # listing pages are ~400 KB
API_TIMEOUT = 30

SEARCH_PATH = "/api/search/BbsSearchListingsLive"
COUNTS_PATH = "/_api/bff/v2/BbsBfsSearchResultsCounts"
BROKERS_PATH = "/_api/bff/v2/brokerSearch"
BROKER_TYPEAHEAD_PATH = "/_api/bff/v2/SearchBrokerProfilesTypeahead"
FRANCHISES_PATH = "/_api/bff/v2/LoopNetFranchiseSearchResults"
FRANCHISE_PATH = "/api/search/GetFranchiseDetail"
CATEGORIES_PATH = "/api/Resource/GetBfsCategories"
COUNTIES_PATH = "/api/Resource/GetCountiesByRegion"

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
_CHALLENGE_MARKERS = ("sec-if-cpt", "sec-bc-text-container", "Access Denied", "errors.edgesuite.net")


class BizBuySellUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unexpected payload — retryable."""


class BizBuySellBlocked(BizBuySellUpstreamError, Blocked):
    """403 / 429 or the Akamai challenge shell where a page or JSON was expected — retryable."""


class BizBuySellBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class BizBuySellNotFound(NotFound):
    """Listing / broker / franchise does not exist — never retried."""


# ---- sessions ----------------------------------------------------------------
# One session per cheroot worker thread (a curl handle is not thread-safe).
# Process-wide: after a block on the default tier every new session rides
# the fallback tier until _fallback_until.
_local = threading.local()
_fallback_until = 0.0
_fallback_lock = threading.Lock()


def _proxy():
    proxy = config.bizbuysell_proxy()
    if proxy is None and time.time() < _fallback_until:
        proxy = config.bizbuysell_fallback_proxy()
    return proxy


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        proxy = _proxy()
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        sess.headers["accept-language"] = egress.accept_language(proxy)
        _local.session = sess
    # Akamai cookies set by an HTML page poison the JSON routes (403), and
    # every surface answers a cookie-less request, so none are kept.
    try:
        sess.cookies.clear()
    except Exception:
        pass
    return sess


def _drop_session(blocked=False):
    """Close the thread's session (fresh exit next time); a block on the
    default tier also starts the fallback cooldown for every thread."""
    global _fallback_until
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass
    if blocked and config.bizbuysell_proxy() is None and config.bizbuysell_fallback_proxy() is not None:
        with _fallback_lock:
            _fallback_until = max(_fallback_until, time.time() + config.BIZBUYSELL_BLOCK_COOLDOWN)


def _retrying(fn):
    """Run fn() under the shared retry policy (BizBuySellUpstreamError only;
    NotFound / BadRequest surface immediately)."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except BizBuySellUpstreamError as e:
            last = e
            _drop_session(blocked=isinstance(e, BizBuySellBlocked))
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


# ---- request helpers -----------------------------------------------------------

def _page_headers():
    return {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "upgrade-insecure-requests": "1",
    }


def _json_headers():
    return {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": SITE,
        "referer": SITE + "/",
        "x-correlation-id": str(uuid.uuid4()),
        "x-lane": "",
    }


def _looks_challenged(text):
    head = (text or "")[:6000]
    return any(marker in head for marker in _CHALLENGE_MARKERS)


def _classify(resp, label):
    if resp.status_code == 404:
        raise BizBuySellNotFound(f"{label} not found")
    if resp.status_code == 400:
        raise BizBuySellBadRequest(resp.text[:200])
    if resp.status_code in (401, 403, 429):
        raise BizBuySellBlocked(f"HTTP {resp.status_code} for {label}")
    if resp.status_code != 200:
        raise BizBuySellUpstreamError(f"HTTP {resp.status_code} for {label}")
    return resp.text


def _post_json(path, body, label, method="POST"):
    """POST a JSON body (or GET when method="GET") and return the decoded
    envelope. The challenge shell / a non-JSON body is a block."""
    def once():
        try:
            if method == "GET":
                resp = _session().get(SITE + path, headers=_json_headers(), timeout=API_TIMEOUT)
            else:
                resp = _session().post(SITE + path, data=json.dumps(body), headers=_json_headers(),
                                       timeout=API_TIMEOUT)
        except Exception as e:
            raise BizBuySellUpstreamError(f"request failed: {type(e).__name__}: {e}")
        if resp.status_code == 204:   # the typeahead's "no match"
            return {}
        text = _classify(resp, label)
        if _looks_challenged(text):
            raise BizBuySellBlocked(f"challenge page for {label}")
        try:
            payload = fastjson.loads(text)
        except ValueError:
            raise BizBuySellBlocked(f"non-JSON response for {label}: {text[:120]!r}")
        if not isinstance(payload, dict):
            raise BizBuySellUpstreamError(f"unexpected payload shape for {label}")
        return payload
    return _retrying(once)


def _base_criteria(**fields):
    body = {"siteId": SITE_ID, "languageId": LANGUAGE_ID}
    body.update({k: v for k, v in fields.items() if v is not None})
    return body


# ---- listings ----------------------------------------------------------------

def fetch_search(criteria):
    """POST the search criteria -> the `bbsBfsSearchResult` object."""
    payload = _post_json(SEARCH_PATH, _base_criteria(**criteria), "listing search")
    result = payload.get("bbsBfsSearchResult")
    if not isinstance(result, dict):
        raise BizBuySellUpstreamError(f"search answered without a result: {str(payload)[:160]}")
    if result.get("status") not in (1, None) and result.get("value") is None:
        raise BizBuySellUpstreamError(f"search status {result.get('status')}: {result.get('message')}")
    return result


def fetch_counts(criteria):
    """POST the search criteria -> the per-listing-type count rows."""
    payload = _post_json(COUNTS_PATH, _base_criteria(**criteria), "listing counts")
    value = payload.get("value") or {}
    return value.get("resultCounts") or []


def _canonical_link(location):
    """A Location header value -> an absolute listing link ending in "/"
    (the site answers absolute links today; a relative one must not become
    a request without a host, and `link + "amp/"` needs the slash)."""
    location = (location or "").split("?")[0].split("#")[0].strip()
    if not location:
        return ""
    if location.startswith("//"):
        location = "https:" + location
    elif location.startswith("/"):
        location = SITE + location
    return location.rstrip("/") + "/"


def _resolve_listing_link(listing_id):
    """GET /business-opportunity/x/<id>/amp/ with redirects off: the site's
    301 Location is the canonical listing link; an unknown id is a 404."""
    def once():
        try:
            resp = _session().get(f"{SITE}/business-opportunity/x/{listing_id}/amp/", headers=_page_headers(),
                                  timeout=API_TIMEOUT, allow_redirects=False)
        except Exception as e:
            raise BizBuySellUpstreamError(f"request failed: {type(e).__name__}: {e}")
        if resp.status_code in (301, 302, 303, 307, 308):
            location = _canonical_link(resp.headers.get("location"))
            if "/business-opportunity/" in location and f"/{listing_id}/" in location:
                return location
            raise BizBuySellNotFound(f"listing {listing_id} not found")
        text = _classify(resp, f"listing {listing_id}")
        if _looks_challenged(text):
            raise BizBuySellBlocked(f"challenge page resolving listing {listing_id}")
        if "bfsTitle" in text or "ldp-section-financials" in text:
            return f"{SITE}/business-opportunity/x/{listing_id}/"   # served the page itself
        raise BizBuySellNotFound(f"listing {listing_id} not found")
    return _retrying(once)


def fetch_listing(listing_id, slug=None):
    """The listing page HTML (the `/amp/` variant, which Akamai serves to
    plain clients). Returns (html, canonical_link)."""
    link = f"{SITE}/business-opportunity/{slug}/{listing_id}/" if slug else _resolve_listing_link(listing_id)
    link = link.rstrip("/") + "/"

    def once(link, followed=False):
        try:
            resp = _session().get(link + "amp/", headers=_page_headers(), timeout=PAGE_TIMEOUT,
                                  allow_redirects=False)
        except Exception as e:
            raise BizBuySellUpstreamError(f"request failed: {type(e).__name__}: {e}")
        if resp.status_code in (301, 302, 303, 307, 308):
            location = _canonical_link(resp.headers.get("location"))
            if "/404" in location or not location:
                raise BizBuySellNotFound(f"listing {listing_id} not found")
            if f"/{listing_id}/" not in location:
                raise BizBuySellNotFound(f"listing {listing_id} not found")
            # a stale slug 301s to the current canonical link: retry once there
            if location != link and not followed:
                return once(location, followed=True)
            raise BizBuySellUpstreamError(f"listing {listing_id}: unexpected redirect to {location}")
        text = _classify(resp, f"listing {listing_id}")
        if _looks_challenged(text):
            raise BizBuySellBlocked(f"challenge page for listing {listing_id}")
        title = _page_title(text)
        if "File Not Found" in title or "Page Not Found" in title:
            raise BizBuySellNotFound(f"listing {listing_id} not found")
        if "bfsTitle" not in text and "ldp-section-financials" not in text:
            raise BizBuySellUpstreamError(f"unexpected listing page for {listing_id} ({title[:60]!r})")
        return text, link
    return _retrying(lambda: once(link))


def _page_title(text):
    match = _TITLE_RE.search(text or "")
    return " ".join(match.group(1).split()) if match else ""


# ---- brokers -----------------------------------------------------------------

def fetch_brokers(criteria):
    """POST the broker criteria -> the BFF `value` (brokerSearchResult + lists)."""
    payload = _post_json(BROKERS_PATH, _base_criteria(**criteria), "broker search")
    value = payload.get("value")
    if not isinstance(value, dict) or not isinstance(value.get("brokerSearchResult"), dict):
        raise BizBuySellUpstreamError(f"broker search answered without a result: {str(payload)[:160]}")
    return value


def fetch_broker_typeahead(keyword):
    """POST a name fragment -> matching broker stubs (account, brokerProfileId, url)."""
    payload = _post_json(BROKER_TYPEAHEAD_PATH, _base_criteria(keyword=keyword), "broker typeahead")
    value = payload.get("value")
    return value if isinstance(value, list) else []


# ---- franchises --------------------------------------------------------------

def fetch_franchises(criteria):
    """POST the franchise criteria -> the `franchiseSearchResult` object."""
    body = {"franchiseSearchCriteria": _base_criteria(**criteria), "industriesHierarchy": 10,
            "languageTypeId": LANGUAGE_ID, "email": ""}
    payload = _post_json(FRANCHISES_PATH, body, "franchise search")
    value = payload.get("value") or {}
    result = value.get("franchiseSearchResult")
    if not isinstance(result, dict):
        raise BizBuySellUpstreamError(f"franchise search answered without a result: {str(payload)[:160]}")
    if result.get("status") == 4:   # the site's own "no such category / region" answer
        return {"status": 4, "total": 0, "count": 0, "value": [], "criteria": result.get("criteria")}
    return result


def fetch_franchise(slug):
    """POST the franchise slug -> the brochure record (status 4 = unknown)."""
    payload = _post_json(FRANCHISE_PATH, _base_criteria(seoName=f"/franchise-for-sale/{slug}/"),
                         f"franchise {slug}")
    if payload.get("status") == 4 or not payload.get("value"):
        raise BizBuySellNotFound(f"franchise {slug} not found")
    return payload["value"]


# ---- reference lists ---------------------------------------------------------

def fetch_categories():
    """GET the full business category list (208 rows: 20 top-level + sub-categories)."""
    payload = _post_json(f"{CATEGORIES_PATH}?siteId={SITE_ID}&languageId={LANGUAGE_ID}", None,
                         "categories", method="GET")
    return payload.get("value") or []


def fetch_counties():
    """POST -> every US county row (the regionId filter is ignored upstream)."""
    payload = _post_json(COUNTIES_PATH, {"regionId": "0"}, "counties")
    return payload.get("value") or []
