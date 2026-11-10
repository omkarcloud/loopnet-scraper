"""LoopNet transport: plain curl_cffi with a browser-minted Akamai jar,
replayed FROZEN on the exit it was minted on.

Akamai Bot Manager fronts every www.loopnet.com page and JSON service with
the press-and-hold "sec-if-cpt" interstitial: a bare request answers 403
"Access Denied" or the 2.6 KB challenge shell on every curl identity and
every tier (pod probe 2026-11-07, config.py's loopnet block). What passes
is the jar a headed Chrome earns (recipes/loopnet.py on a browser box,
recipes/registry.py says which: `ak_bmsc` from the edge, `bm_sv` once the
sensor POST was accepted) sent with the browser's own UA / client hints
(browser_client.headers_for) from the SAME exit IP. The jar is bound to that
IP: on the mint exit every curl identity serves search + listing pages, from
another exit only iOS Safari for a handful of calls (Mac, 2026-11-07). So
every identity is one sticky exit (config.loopnet_mint_proxy(), the tier
config.LOOPNET_EXIT names) the box minted on and the curl sessions replay on.

Rules learned on 2026-11-07:
  * FROZEN cookies: the curl session's own jar is cleared after every
    response. A jar that absorbs the challenge page's Set-Cookie is
    challenged for good.
  * Never auto-follow a redirect: the landing of a 301/302 (a bare
    /Listing/<id>/, a wrong slug, a page past the end) is challenged
    even on a good identity, while the same URL requested afresh with the
    jar passes. fetch_page() reads the Location and GETs it itself.
  * A use budget: one jar served ~100 pages in an hour; LOOPNET_IDENTITY_USES
    pages per identity, then a fresh port + mint. A refusal (403 /
    challenge shell) burns the identity at once.
  * A pool of LOOPNET_IDENTITY_SLOTS identities, round-robin per call, so
    one residential IP is not hammered by every thread.

Not-found verdicts: an unknown listing is HTTP 200 with the
"This listing cannot be found." page (/listingnotfound/); an unknown place
in a search path, broker or company is HTTP 404; an unknown property
record is HTTP 410; a directory page past the end is HTTP 404.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  LoopNetUpstreamError  transport failure / 5xx / page without content — retryable
  LoopNetBlocked        Akamai refused every identity tried              — retryable
  LoopNetBadRequest     upstream 400                                     — never retried
  LoopNetNotFound       unknown listing / broker / company / record      — never retried
"""
import os
import sys
import threading
import time
from urllib.parse import urljoin

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_client
import config
import fastjson
from loopnet.refs import SITE
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

BOX_SITE = "loopnet"             # recipes/loopnet.py
PAGE_TIMEOUT = 60                # search pages run 0.5-0.9 MB
JSON_TIMEOUT = 30
PAGE_ACCEPT = ("text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
               "image/apng,*/*;q=0.8")
JSON_ACCEPT = "application/json, text/plain, */*"
REFUSAL_MARKERS = ("sec-if-cpt", "sec-cpt-if", "Access Denied", "errors.edgesuite.net")
NOT_FOUND_MARKERS = ("This listing cannot be found", "/listingnotfound/")
REDIRECTS = (301, 302, 303, 307, 308)
MAX_REDIRECTS = 3


class LoopNetUpstreamError(UpstreamError):
    """Transport failure, 5xx or a page without its content — retryable."""


class LoopNetBlocked(LoopNetUpstreamError, Blocked):
    """Akamai refused every identity tried (403 / challenge shell) — retryable."""


class LoopNetBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class LoopNetNotFound(NotFound):
    """Listing / broker / company / property record does not exist — never retried."""


# ---- identities ----------------------------------------------------------------------
# LOOPNET_IDENTITY_SLOTS slots, each = one sticky exit the box minted a jar
# on, used round-robin by the worker threads; a slot is re-minted on a
# fresh exit when spent (its use budget) or refused. browser_client caches
# the mint per (site, exit) and single-flights it, so a burst of threads
# that hit one spent slot causes one mint.

_lock = threading.Lock()
_slots = []          # [{"proxy": str|None, "uses": int, "ready": bool}]
_cursor = 0


def _slot_count():
    return max(1, int(config.LOOPNET_IDENTITY_SLOTS or 1))


def _pick_locked():
    global _cursor
    while len(_slots) < _slot_count():
        _slots.append({"proxy": None, "uses": 0, "ready": False})
    index = _cursor % len(_slots)
    _cursor = (_cursor + 1) % len(_slots)
    return index


def _identity(force=False, refused=None):
    """The next identity of the pool, re-minted when spent or when `force`
    reports that the identity on exit `refused` was refused. The rotation
    decision and the new exit happen under one lock; the mint itself is
    browser_client's (single-flight per exit)."""
    with _lock:
        index = _pick_locked()
        slot = _slots[index]
        if force and refused is not None:
            # rotate the refused slot, whichever position it sits in
            for candidate in _slots:
                if candidate["ready"] and candidate["proxy"] == refused:
                    slot = candidate
                    break
        spent = slot["uses"] >= config.LOOPNET_IDENTITY_USES
        stale = force and (not slot["ready"] or refused == slot["proxy"])
        rotate = not slot["ready"] or spent or stale
        if rotate:
            old = slot["proxy"] if slot["ready"] else None
            slot["proxy"] = config.loopnet_mint_proxy()
            slot["uses"] = 0
            slot["ready"] = True
            if old is not None and old != slot["proxy"]:
                browser_client.invalidate(BOX_SITE, proxy=old)
        proxy = slot["proxy"]
    try:
        return browser_client.identity(BOX_SITE, proxy=proxy, force=rotate)
    except browser_client.BoxUnavailable as e:
        raise LoopNetUpstreamError(f"browser box unavailable for the Akamai jar mint: {e}")
    except browser_client.BoxRefused as e:
        _forget(proxy)
        raise LoopNetBlocked(f"the Akamai jar mint did not pass on the browser box: {e}")
    except browser_client.RemintBudgetExceeded as e:
        raise LoopNetBlocked(str(e))


def _forget(proxy):
    """A mint on `proxy` failed: the next call draws a fresh exit for that slot."""
    with _lock:
        for slot in _slots:
            if slot["ready"] and slot["proxy"] == proxy:
                slot["ready"] = False


def _charge(ident):
    with _lock:
        for slot in _slots:
            if slot["ready"] and slot["proxy"] == ident.get("proxy"):
                slot["uses"] += 1


def _burn(ident):
    """The site refused this identity: forget it so the next call mints."""
    browser_client.invalidate(BOX_SITE, proxy=ident.get("proxy"))
    with _lock:
        for slot in _slots:
            if slot["ready"] and slot["proxy"] == ident.get("proxy"):
                slot["uses"] = config.LOOPNET_IDENTITY_USES


def identity_status():
    """For logs / tests: the pool's exits and their use counts."""
    with _lock:
        return [dict(slot) for slot in _slots]


def _reset_for_tests():
    global _cursor
    with _lock:
        _slots.clear()
        _cursor = 0


# ---- sessions ------------------------------------------------------------------------
# One curl session per thread PER EXIT (a curl handle is never shared across
# threads; the session carries keep-alive and the identity's proxy, the
# cookie travels per request). The jar is cleared after every response.

_local = threading.local()


def _session(ident):
    sessions = getattr(_local, "sessions", None)
    if sessions is None:
        sessions = _local.sessions = {}
    key = (ident.get("proxy"), browser_client.impersonation_for(ident, "chrome"))
    sess = sessions.get(key)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=key[1])
        if key[0]:
            sess.proxies = {"http": key[0], "https": key[0]}
        sessions[key] = sess
    return sess


def _drop_session(ident):
    sessions = getattr(_local, "sessions", None) or {}
    key = (ident.get("proxy"), browser_client.impersonation_for(ident, "chrome"))
    sess = sessions.pop(key, None)
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _headers(ident, accept, referer=None, extra=None):
    headers = browser_client.headers_for(ident, accept=accept, referer=referer or SITE + "/")
    headers["cookie"] = browser_client.cookie_header(ident)
    if extra:
        headers.update(extra)
    return headers


def _is_refusal(resp):
    if resp.status_code in (403, 429):
        return True
    head = (resp.text or "")[:20000]
    return resp.status_code == 200 and len(head) < 20000 and any(m in head for m in REFUSAL_MARKERS)


def _request(method, url, *, accept, label, timeout, json_body=None, form=None, extra_headers=None, referer=None):
    """One request under the identity ladder: the current identity, then one
    fresh mint when the site refuses it; a transport failure or a 5xx is
    retried MAX_RETRIES times on a fresh connection. Redirects are returned
    as-is (status + Location) for the caller to follow. 404 / 410 / 400
    surface at once."""
    last = None
    forced, refused = False, None
    mint_failures = 0
    attempts = config.MAX_RETRIES + config.LOOPNET_IDENTITIES_PER_CALL
    for attempt in range(1, attempts + 1):
        try:
            ident = _identity(force=forced, refused=refused)
        except LoopNetBlocked as e:
            # the box could not mint on that exit (the Akamai edge denies
            # about half the residential exits outright): _identity() forgot
            # the slot, so the next attempt takes the pool's other identity
            # or a fresh exit. LOOPNET_MINTS_PER_CALL caps the failed mints
            # one call waits on.
            mint_failures += 1
            if mint_failures >= config.LOOPNET_MINTS_PER_CALL:
                raise
            last = e
            forced, refused = False, None
            continue
        forced, refused = False, None
        headers = _headers(ident, accept, referer, extra_headers)
        sess = _session(ident)
        try:
            if json_body is not None:
                headers["content-type"] = "application/json"
                resp = sess.request(method, url, headers=headers, json=json_body, timeout=timeout, allow_redirects=False)
            elif form is not None:
                resp = sess.request(method, url, headers=headers, data=form, timeout=timeout, allow_redirects=False)
            else:
                resp = sess.request(method, url, headers=headers, timeout=timeout, allow_redirects=False)
        except Exception as e:
            last = LoopNetUpstreamError(f"request failed: {type(e).__name__}: {e}")
            _drop_session(ident)
            time.sleep(config.RETRY_BACKOFF * attempt)
            continue
        finally:
            try:
                sess.cookies.clear()          # FROZEN jar: never keep a Set-Cookie
            except Exception:
                pass
        _charge(ident)
        if _is_refusal(resp):
            _burn(ident)
            last = LoopNetBlocked(f"Akamai refused the identity for {label} (HTTP {resp.status_code})")
            forced, refused = True, ident.get("proxy")
            continue
        if resp.status_code in (404, 410):
            raise LoopNetNotFound(f"{label} not found")
        if resp.status_code == 400:
            raise LoopNetBadRequest(resp.text[:200])
        if resp.status_code >= 500:
            last = LoopNetUpstreamError(f"HTTP {resp.status_code} for {label}")
            _drop_session(ident)
            time.sleep(config.RETRY_BACKOFF * attempt)
            continue
        if resp.status_code not in REDIRECTS and resp.status_code != 200:
            raise LoopNetUpstreamError(f"HTTP {resp.status_code} for {label}")
        return resp
    raise last or LoopNetUpstreamError(f"{label}: no attempt succeeded")


# ---- pages -----------------------------------------------------------------------------

def fetch_page(path, label, follow=True, referer=None):
    """GET a www page with the identity; returns (html, final_url). A
    redirect is followed by a fresh GET of its Location (never by curl:
    the auto-followed landing is challenged). `follow=False` returns the
    redirect's ("", location) instead, for callers that treat a redirect
    as "past the end"."""
    url = path if path.startswith("http") else SITE + path
    for _ in range(MAX_REDIRECTS + 1):
        resp = _request("GET", url, accept=PAGE_ACCEPT, label=label, timeout=PAGE_TIMEOUT, referer=referer)
        if resp.status_code in REDIRECTS:
            location = resp.headers.get("location") or ""
            target = urljoin(url, location) if location else None
            if not target:
                raise LoopNetUpstreamError(f"{label}: redirect without a location")
            if not follow:
                return "", target
            url = target
            continue
        text = resp.text or ""
        if any(m in text[:60000] for m in NOT_FOUND_MARKERS):
            raise LoopNetNotFound(f"{label} not found")
        if len(text) < 5000:
            raise LoopNetUpstreamError(f"{label}: page without content ({len(text)} bytes)")
        return text, str(resp.url) or url
    raise LoopNetUpstreamError(f"{label}: too many redirects")


# ---- the open JSON services ---------------------------------------------------------------
# The geography typeahead and the traffic-count service answered a
# cookie-less curl_cffi chrome request 200 from the pod's own IP and from
# every datacenter / residential port (pod probe 2026-11-07), while every
# page was 403: so they ride a plain direct session first (own IP first,
# no identity use), and only a refusal sends them through the identity.

_open_local = threading.local()


def _open_session():
    sess = getattr(_open_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate="chrome")
        _open_local.session = sess
    return sess


def _drop_open_session():
    sess = getattr(_open_local, "session", None)
    _open_local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _open_json(method, url, body, label):
    """One cookie-less direct request -> the parsed payload, or None when the
    service refused it (the caller then goes through the identity)."""
    import egress
    headers = {"accept": JSON_ACCEPT, "accept-language": egress.site_accept_language("loopnet"),
               "x-requested-with": "XMLHttpRequest", "referer": SITE + "/"}
    try:
        sess = _open_session()
        if body is not None:
            resp = sess.request(method, url, headers=headers, json=body, timeout=JSON_TIMEOUT, allow_redirects=False)
        else:
            resp = sess.request(method, url, headers=headers, timeout=JSON_TIMEOUT, allow_redirects=False)
    except Exception:
        _drop_open_session()
        return None
    finally:
        try:
            _open_session().cookies.clear()
        except Exception:
            pass
    if resp.status_code != 200:
        return None
    try:
        return fastjson.loads(resp.text)
    except Exception:
        return None


def fetch_json(path, label, body=None, method=None, referer=None):
    """A JSON service (POST with a JSON body, or GET) -> parsed payload: a
    plain direct request first, the identity on a refusal."""
    url = path if path.startswith("http") else SITE + path
    method = method or ("POST" if body is not None else "GET")
    payload = _open_json(method, url, body, label)
    if payload is not None:
        return payload
    resp = _request(method, url, accept=JSON_ACCEPT, label=label, timeout=JSON_TIMEOUT, json_body=body,
                    referer=referer, extra_headers={"x-requested-with": "XMLHttpRequest"})
    if resp.status_code in REDIRECTS:
        raise LoopNetUpstreamError(f"{label}: unexpected redirect")
    try:
        return fastjson.loads(resp.text)
    except Exception:
        raise LoopNetUpstreamError(f"{label}: non-JSON response ({(resp.text or '')[:120]!r})")


def fetch_form(path, label, form, referer=None):
    """A form POST that answers a server-rendered page -> html."""
    url = path if path.startswith("http") else SITE + path
    resp = _request("POST", url, accept=PAGE_ACCEPT, label=label, timeout=PAGE_TIMEOUT, form=form, referer=referer)
    if resp.status_code in REDIRECTS:
        location = resp.headers.get("location") or ""
        html, _ = fetch_page(urljoin(url, location), label)
        return html
    text = resp.text or ""
    if len(text) < 5000:
        raise LoopNetUpstreamError(f"{label}: page without content ({len(text)} bytes)")
    return text


# ---- the surfaces ---------------------------------------------------------------------

def fetch_search(path):
    """A search page (refs.search_path). A path past the end answers a
    redirect to page 1, reported as None (an empty page); an unknown place
    is a real 404."""
    html, final = fetch_page(path, f"search {path}", follow=False)
    if not html:
        return None
    return html


def fetch_listing(listing_id, slug=None):
    """The listing page HTML + its canonical link. A bare id goes through
    the site's own 302 to the slug URL (the redirect is followed by a
    fresh GET)."""
    from loopnet.refs import listing_link
    html, final = fetch_page(listing_link(listing_id, slug), f"listing {listing_id}")
    return html, final.split("?")[0]


def fetch_mini_placards(listing_ids):
    """POST /service/mini-placards/ -> rows with the canonical link per id."""
    return fetch_json("/service/mini-placards/", "mini placards", body={"listingIds": list(listing_ids)},
                      referer=SITE + "/search/commercial-real-estate/usa/for-sale/")


def fetch_geography(query):
    """POST /services/geography/lookup/ (the search-box typeahead) -> rows."""
    rows = fetch_json("/services/geography/lookup/", f"geography lookup {query!r}", body={"i": query, "l": [None, None]})
    if not isinstance(rows, list):
        raise LoopNetUpstreamError("geography lookup: unexpected payload shape")
    return rows


def fetch_traffic(latitude, longitude):
    rows = fetch_json(f"/services/listing/trafficpinprofile/{latitude:.6f}/{longitude:.6f}/",
                      f"traffic counts near {latitude},{longitude}", method="GET")
    if not isinstance(rows, list):
        raise LoopNetUpstreamError("traffic counts: unexpected payload shape")
    return rows


def fetch_broker_directory(path):
    """A broker directory page; a page past the end is a 404 -> None."""
    try:
        html, _ = fetch_page(path, f"broker directory {path}")
    except LoopNetNotFound:
        return None
    return html


def fetch_broker_search(first_name="", last_name="", company="", geography="", broker_type=""):
    """POST the broker search form -> the result page HTML."""
    form = {"brokerFirstName": first_name or "", "brokerLastName": last_name or "", "companyName": company or "",
            "geography": geography or "", "searchBrokerType": broker_type or ""}
    return fetch_form("/commercial-real-estate-brokers/result", "broker search", form,
                      referer=SITE + "/commercial-real-estate-brokers/")


def fetch_broker(broker_id, slug=None):
    from loopnet.refs import broker_link
    html, final = fetch_page(broker_link(broker_id, slug), f"broker {broker_id}")
    return html, final.split("?")[0]


def fetch_company(company_id, slug=None, page=1):
    from loopnet.refs import company_link
    try:
        html, final = fetch_page(company_link(company_id, slug, page), f"company {company_id}")
    except LoopNetNotFound:
        if page > 1:
            return None, None
        raise
    return html, final.split("?")[0]


def fetch_property(record_id, slug=None):
    from loopnet.refs import property_link
    html, final = fetch_page(property_link(record_id, slug), f"property record {record_id}")
    return html, final.split("?")[0]
