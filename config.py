"""Configuration for the LoopNet Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT                        port the API listens on (default 8000)
    LOOPNET_PROXY               proxy URL for every LoopNet request AND for the
                                Chrome that earns LoopNet's access cookies,
                                e.g. http://user:pass@host:port (default:
                                none — direct). From a home or office
                                connection you don't need one. LoopNet ties
                                its cookies to the IP they were earned on, so
                                use a STICKY proxy (one that keeps the same
                                exit IP) if you set one.
    BIZBUYSELL_PROXY            proxy URL for the businesses-for-sale
                                endpoints (default: none — direct)
    BIZBUYSELL_FALLBACK_PROXY   optional proxy a blocked businesses-for-sale
                                request moves to for BIZBUYSELL_BLOCK_COOLDOWN
                                seconds (default: none)

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# LoopNet access cookies: earned by a real Chrome on this machine, then reused
# over plain HTTP. One set of cookies per exit IP (the cookies are tied to the
# IP), re-earned after LOOPNET_IDENTITY_USES pages or as soon as LoopNet
# refuses them.
LOOPNET_IDENTITY_SLOTS = 1
LOOPNET_IDENTITY_USES = 50
LOOPNET_IDENTITIES_PER_CALL = 2      # cookie sets tried per page: the current one, then a fresh one after a refusal
LOOPNET_MINTS_PER_CALL = 3           # failed Chrome cookie runs one request waits through before giving up

LOOPNET_PROXY = os.environ.get("LOOPNET_PROXY") or None


def loopnet_mint_proxy():
    """The proxy the cookie-earning Chrome and the plain-HTTP requests share (None = direct)."""
    return os.environ.get("LOOPNET_PROXY") or None


# Businesses for sale (served by the bizbuysell module): after a block on a
# direct connection, new sessions use the fallback proxy (when one is set)
# for this many seconds.
BIZBUYSELL_BLOCK_COOLDOWN = 300

BIZBUYSELL_PROXY = os.environ.get("BIZBUYSELL_PROXY") or None


def bizbuysell_proxy():
    """The proxy for one businesses-for-sale session (None = direct)."""
    return os.environ.get("BIZBUYSELL_PROXY") or None


def bizbuysell_fallback_proxy():
    """The proxy a blocked direct businesses-for-sale session moves to (None = no fallback)."""
    return os.environ.get("BIZBUYSELL_FALLBACK_PROXY") or None
