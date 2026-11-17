"""The one network helper the loopnet and bizbuysell modules ask for: the
Accept-Language their requests announce. LoopNet is a US site, so this kit
always sends the plain English list a desktop Chrome in the US sends."""

ACCEPT_LANGUAGE = "en-US,en;q=0.9"


def site_accept_language(site=None):
    return ACCEPT_LANGUAGE


def accept_language(proxy=None, country=None):
    return ACCEPT_LANGUAGE


def exit_proxy(exit=None):
    return exit if exit and "://" in str(exit) else None


def new_session(exit=None, impersonate="chrome", **kw):
    from curl_cffi import requests as curl
    sess = curl.Session(impersonate=impersonate, **kw)
    proxy = exit_proxy(exit)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    return sess
