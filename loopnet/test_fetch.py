"""Offline tests of the identity ladder in loopnet/fetch.py: no network, no box."""
import pytest

import browser_client
import config
from loopnet import fetch


class _Cookies:
    def clear(self):
        pass


class _Resp:
    def __init__(self, status_code=200, text="<html>" + "x" * 6000 + "</html>"):
        self.status_code = status_code
        self.text = text
        self.headers = {}


class _Session:
    def __init__(self, responses):
        self.responses = responses
        self.cookies = _Cookies()
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        return self.responses.pop(0) if self.responses else _Resp()


@pytest.fixture
def pool(monkeypatch):
    """Exits p1, p2, ... in draw order; `refuse` lists the exits whose mint fails."""
    fetch._reset_for_tests()
    state = {"next": 0, "refuse": set(), "minted": [], "session": _Session([])}

    def mint_proxy():
        state["next"] += 1
        return f"http://p{state['next']}"

    def identity(site, proxy=None, variant="", force=False):
        state["minted"].append(proxy)
        if proxy in state["refuse"]:
            raise browser_client.BoxRefused("loopnet: challenge not cleared in 75s")
        return {"proxy": proxy, "cookies": {"ak_bmsc": "a", "bm_sv": "b"}, "user_agent": "UA"}

    monkeypatch.setattr(config, "loopnet_mint_proxy", mint_proxy)
    monkeypatch.setattr(config, "LOOPNET_IDENTITY_SLOTS", 2)
    monkeypatch.setattr(config, "LOOPNET_IDENTITIES_PER_CALL", 2)
    monkeypatch.setattr(config, "LOOPNET_MINTS_PER_CALL", 3)
    monkeypatch.setattr(config, "RETRY_BACKOFF", 0)
    monkeypatch.setattr(browser_client, "identity", identity)
    monkeypatch.setattr(browser_client, "invalidate", lambda *a, **k: None)
    monkeypatch.setattr(fetch, "_headers", lambda ident, accept, referer=None, extra=None: {})
    monkeypatch.setattr(fetch, "_session", lambda ident: state["session"])
    yield state
    fetch._reset_for_tests()


def _get():
    return fetch._request("GET", "https://www.loopnet.com/x/", accept="text/html", label="test page", timeout=5)


def test_failed_mint_falls_back_to_the_next_identity(pool):
    pool["refuse"].add("http://p1")
    resp = _get()
    assert resp.status_code == 200
    assert pool["minted"] == ["http://p1", "http://p2"]
    assert len(pool["session"].calls) == 1


def test_two_denied_exits_then_a_good_one(pool):
    pool["refuse"].update({"http://p1", "http://p2"})
    assert _get().status_code == 200
    assert pool["minted"] == ["http://p1", "http://p2", "http://p3"]


def test_three_failed_mints_give_up_as_blocked(pool):
    pool["refuse"].update({"http://p1", "http://p2", "http://p3", "http://p4"})
    with pytest.raises(fetch.LoopNetBlocked):
        _get()
    assert pool["minted"] == ["http://p1", "http://p2", "http://p3"]   # never a fourth mint in one call
    assert pool["session"].calls == []


def test_a_failed_mint_does_not_cost_the_healthy_slot(pool):
    assert _get().status_code == 200                          # slot 0 minted on p1
    pool["refuse"].add("http://p2")
    assert _get().status_code == 200                          # slot 1 fails on p2 -> back to p1
    assert pool["minted"] == ["http://p1", "http://p2", "http://p1"]


class _Driver:
    def __init__(self, html):
        self.html = html
        self.navigations = 0

    def content(self):
        return self.html

    def call(self, fn):
        self.navigations += 1


EDGE_DENIAL = ('<HTML><HEAD><TITLE>Access Denied</TITLE></HEAD><BODY><H1>Access Denied</H1>'
               'Reference #18.ef18d017 https://errors.edgesuite.net/18.ef18d017</BODY></HTML>')
CHALLENGE_SHELL = "<html><head></head><body>" + "<script>sec-if-cpt</script>" * 100 + "</body></html>"


def test_recipe_fails_fast_on_an_edge_denied_exit(monkeypatch):
    RecipeError = pytest.importorskip("browser_worker.types").RecipeError   # the box recipe (grow only)
    recipe_module = pytest.importorskip("recipes.loopnet")
    monkeypatch.setattr(recipe_module, "RELOAD_WAIT", 0)
    recipe, driver = recipe_module.LoopNet(), _Driver(EDGE_DENIAL)
    cookies = {"ak_bmsc": "a", "bm_s": "b"}
    for _ in range(recipe_module.RELOADS):
        assert recipe.passed(cookies, driver) is False          # reload while the reloads last
    assert driver.navigations == recipe_module.RELOADS
    with pytest.raises(RecipeError, match="denied by the Akamai edge"):
        recipe.passed(cookies, driver)


def test_recipe_keeps_waiting_on_the_challenge_shell(monkeypatch):
    recipe_module = pytest.importorskip("recipes.loopnet")
    monkeypatch.setattr(recipe_module, "RELOAD_WAIT", 0)
    recipe, driver = recipe_module.LoopNet(), _Driver(CHALLENGE_SHELL)
    for _ in range(recipe_module.RELOADS + 3):
        assert recipe.passed({"ak_bmsc": "a"}, driver) is False  # never raises: the timeout decides
    full = _Driver("<script>window.gState = {}</script>" + "x" * 6000)
    assert recipe.passed({"ak_bmsc": "a", "bm_sv": "b"}, full) is True


def test_refusal_burns_the_identity_and_remints(pool):
    pool["session"].responses = [_Resp(403, "Access Denied"), _Resp()]
    assert _get().status_code == 200
    assert pool["minted"][:2] == ["http://p1", "http://p2"]
    assert len(pool["session"].calls) == 2
