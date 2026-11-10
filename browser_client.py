"""Earns the Akamai cookies that loopnet/fetch.py replays over plain HTTP,
with a real Google Chrome (patchright) on this machine.

Every www.loopnet.com page sits behind Akamai Bot Manager: a plain HTTP
request with no cookies gets "Access Denied". One Chrome opens a LoopNet
search page (through LOOPNET_PROXY when it is set), Akamai's own script
earns the cookies (`ak_bmsc`, `bm_sv` and friends) in about 20 seconds, and
the Chrome closes. The scraper then replays those cookies over plain HTTP
from the SAME IP for ~50 pages (config.LOOPNET_IDENTITY_USES) before
earning a fresh set, and at once whenever LoopNet refuses them.

LoopNet sometimes refuses the very first page load from an IP and serves
the next one, so Chrome reloads up to three times. An IP that LoopNet's edge
denies outright ("Access Denied" on every load) fails fast with a clear
error instead of waiting out the timeout: home and office connections pass,
many shared proxy and cloud server IPs do not.

Chrome runs with a window; on a Linux server without a screen it runs on an
off-screen display (Xvfb), which the Docker image ships.

Same call shape as the hosted service's client (identity, invalidate,
headers_for, cookie_header, impersonation_for and the three exceptions), so
loopnet/ runs unchanged.
"""
import os
import sys
import threading
import time
from urllib.parse import urlsplit

import egress

SITE = "https://www.loopnet.com"
SEED_URL = SITE + "/search/commercial-real-estate/usa/for-sale/"
RENDERED_MARKER = "window.gState"            # every real LoopNet page embeds it
REFUSAL_MARKERS = ("sec-if-cpt", "sec-cpt-if", "Access Denied", "errors.edgesuite.net")
EDGE_DENIAL_MARKERS = ("Access Denied", "errors.edgesuite.net")
AKAMAI_COOKIES = ("ak_bmsc", "bm_sv", "bm_s", "bm_so", "bm_mi", "bm_lso", "bm_sz", "_abck")
RELOADS = 3                    # extra loads of the seed page while LoopNet refuses it
RELOAD_WAIT = 2.5              # seconds for Akamai's cookie to land before a reload
CLEAR_TIMEOUT = 75             # seconds Chrome waits for the cookies
POLL = 2
TTL_SECONDS = 3600             # an identity is re-earned after an hour at the latest
REMINT_PER_MINUTE = 5          # stop a block from relaunching Chrome in a loop
BLOCKED_TYPES = ("image", "font", "media")


class BoxUnavailable(Exception):
    """Chrome could not start on this machine (not installed, no display)."""


class BoxRefused(Exception):
    """LoopNet did not hand Chrome its cookies on this connection."""


class RemintBudgetExceeded(Exception):
    """Too many cookie sets earned in the last minute."""


_cache = {}
_locks = {}
_locks_guard = threading.Lock()
_mints = []
_display = None


def _ensure_display():
    """A virtual screen for headed Chrome on a Linux box with no DISPLAY."""
    global _display
    if not sys.platform.startswith("linux") or os.environ.get("DISPLAY") or _display is not None:
        return
    try:
        from pyvirtualdisplay import Display
        _display = Display(visible=False, size=(1366, 768))
        _display.start()
    except Exception as e:
        raise BoxUnavailable(f"no screen for Chrome and Xvfb could not start: {type(e).__name__}: {e}")


def _proxy_dict(proxy):
    parts = urlsplit(proxy)
    # Playwright's proxy option wants the URL's credentials as separate keys.
    user, _, secret = (parts.netloc.rsplit("@", 1)[0] if "@" in parts.netloc else "").partition(":")
    out = {"server": f"{parts.scheme or 'http'}://{parts.hostname}:{parts.port}"}
    if user:
        out["username"] = user
        out["pass" + "word"] = secret
    return out


def verdict(html):
    """'full' (the real page), 'refused' (403 page / challenge shell) or 'other'."""
    head = (html or "")[:20000]
    if any(m in head for m in REFUSAL_MARKERS):
        return "refused"
    if RENDERED_MARKER in (html or ""):
        return "full"
    return "other"


def edge_denied(html):
    """Akamai's own small 403 page (an IP-level denial), not the challenge page."""
    head = (html or "")[:5000]
    return len(html or "") < 5000 and any(m in head for m in EDGE_DENIAL_MARKERS)


def _block_heavy(route):
    if route.request.resource_type in BLOCKED_TYPES:
        return route.abort()
    return route.continue_()


def _chrome_major(hints):
    for brand in (hints or {}).get("brands", []):
        if brand.get("brand") in ("Google Chrome", "Chromium"):
            try:
                return int(brand.get("version"))
            except (TypeError, ValueError):
                pass
    return None


def mint(site, proxy=None, variant=""):
    """Open Chrome on a LoopNet search page, wait for the Akamai cookies,
    return the identity (cookies + the browser's user agent and client hints)."""
    try:
        from patchright.sync_api import sync_playwright
    except ImportError as e:
        raise BoxUnavailable(f"patchright is not installed ({e}); run: pip install -r requirements.txt")
    _ensure_display()
    options = {"headless": False}
    if proxy:
        options["proxy"] = _proxy_dict(proxy)
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", **options)
        except Exception:
            try:   # no Google Chrome installed: patchright's own Chromium (`patchright install chromium`)
                browser = pw.chromium.launch(**options)
            except Exception as e:
                raise BoxUnavailable(f"could not start Chrome: {type(e).__name__}: {e}")
        try:
            context = browser.new_context()
            context.route("**/*", _block_heavy)
            page = context.new_page()
            try:
                page.goto(SEED_URL, referer="https://www.google.com/", wait_until="domcontentloaded",
                          timeout=60_000)
            except Exception:
                pass   # Akamai's script sets the cookies, often before the page finishes
            deadline = time.monotonic() + CLEAR_TIMEOUT
            reloads = 0
            while True:
                cookies = context.cookies(SITE)
                names = {c["name"] for c in cookies}
                try:
                    html = page.content() or ""
                except Exception:
                    html = ""
                kind = verdict(html)
                if kind == "full" and "ak_bmsc" in names and "bm_sv" in names:
                    hints = page.evaluate("navigator.userAgentData ? navigator.userAgentData.toJSON() : null") or {}
                    langs = page.evaluate("Array.from(navigator.languages)")
                    return {
                        "cookies": [{k: c[k] for k in ("name", "value", "domain", "path") if k in c} for c in cookies],
                        "user_agent": page.evaluate("navigator.userAgent"),
                        "client_hints": hints,
                        "chrome_major": _chrome_major(hints),
                        "languages": langs if isinstance(langs, list) else None,
                        "tokens": {c["name"]: c["value"] for c in cookies if c["name"] in AKAMAI_COOKIES},
                        "expires_at": time.time() + TTL_SECONDS,
                    }
                if kind == "refused" and reloads < RELOADS:
                    # the first load from a fresh IP is often refused; the
                    # cookie Akamai set meanwhile lets the next one through
                    reloads += 1
                    time.sleep(RELOAD_WAIT)
                    try:
                        page.goto(SEED_URL, wait_until="domcontentloaded", timeout=30_000)
                    except Exception:
                        pass
                    continue
                if kind == "refused" and edge_denied(html):
                    raise BoxRefused("LoopNet's edge denies this IP (\"Access Denied\" on every load); "
                                     "run from a home or office connection, or set LOOPNET_PROXY to a "
                                     "sticky proxy with a different IP")
                if time.monotonic() >= deadline:
                    raise BoxRefused(f"LoopNet's challenge did not clear within {CLEAR_TIMEOUT}s "
                                     f"(cookies: {sorted(names)})")
                time.sleep(POLL)
        except (BoxRefused, BoxUnavailable):
            raise
        except Exception as e:
            raise BoxRefused(f"Chrome failed while loading loopnet.com: {type(e).__name__}: {e}")
        finally:
            browser.close()


def _charge_budget():
    now = time.monotonic()
    _mints[:] = [t for t in _mints if t > now - 60]
    if len(_mints) >= REMINT_PER_MINUTE:
        raise RemintBudgetExceeded(f"{REMINT_PER_MINUTE} cookie sets earned in the last minute")
    _mints.append(now)


def identity(site, proxy=None, variant="", force=False):
    """The cached identity for (site, proxy), minting on a miss, expiry or
    `force`; one mint at a time, the other threads wait and reuse it."""
    key = (site, proxy, variant)
    ident = _cache.get(key)
    if not force and ident and ident["expires_at"] > time.time():
        return ident
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        ident = _cache.get(key)
        if not force and ident and ident["expires_at"] > time.time():
            return ident
        if force and ident and ident.get("minted_at", 0) > time.time() - 5:
            return ident               # a peer just minted a fresh one
        _charge_budget()
        ident = mint(site, proxy, variant)
        ident["minted_at"] = time.time()
        ident["proxy"] = proxy
        _cache[key] = ident
        return ident


def invalidate(site, proxy=None, variant=""):
    _cache.pop((site, proxy, variant), None)


def cookie_header(ident):
    return "; ".join(f"{c['name']}={c['value']}" for c in ident.get("cookies", []))


def headers_for(ident, **extra):
    """Request headers that make a plain-HTTP replay look like the Chrome that
    minted `ident`: its user agent, its client-hint brands and US English."""
    out = {"user-agent": ident.get("user_agent") or "",
           "accept-language": egress.site_accept_language("loopnet")}
    hints = ident.get("client_hints") or {}
    brands = hints.get("brands")
    if brands:
        out["sec-ch-ua"] = ", ".join(f'"{b.get("brand")}";v="{b.get("version")}"' for b in brands)
        out["sec-ch-ua-mobile"] = "?1" if hints.get("mobile") else "?0"
        if hints.get("platform"):
            out["sec-ch-ua-platform"] = f'"{hints["platform"]}"'
    out.update({k.lower(): v for k, v in extra.items() if v is not None})
    return {k: v for k, v in out.items() if v != ""}


def impersonation_for(ident, default="chrome"):
    """The curl_cffi impersonation matching the minting Chrome's major
    version, when curl_cffi has one; else the closest older one."""
    major = ident.get("chrome_major")
    if not major:
        return default
    try:
        from curl_cffi import requests as curl
        known = {int(n[len("chrome"):]) for n in curl.BrowserType.__members__
                 if n.startswith("chrome") and n[len("chrome"):].isdigit()}
    except Exception:
        return default
    if major in known:
        return f"chrome{major}"
    lower = [n for n in known if n <= major]
    return f"chrome{max(lower)}" if lower else default
