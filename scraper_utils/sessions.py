"""Per-thread HTTP sessions: where a site keeps them and how it drops them.

The store itself stays in the site module (`_local = threading.local()` in its
fetch.py) and is passed in on every call, so the site's tests can still read,
replace and reset it."""
from collections import OrderedDict


def close_quietly(sess):
    """Close a session; a session that fails to close is simply let go."""
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def drop(local):
    """Close the thread's session so a poisoned connection (or exit) dies."""
    sess = getattr(local, "session", None)
    local.session = None
    close_quietly(sess)


def thread_store(local):
    """The thread's {key: session} store, created on first use."""
    store = getattr(local, "sessions", None)
    if store is None:
        store = local.sessions = OrderedDict()
    return store


def drop_keyed(store, key):
    """Close and forget the session kept under `key`."""
    close_quietly(store.pop(key, None))


def keyed(store, key, build, cap):
    """The session kept under `key`, built on first use. The store holds the
    `cap` most recently used sessions; older ones are closed."""
    sess = store.get(key)
    if sess is None:
        sess = build()
        store[key] = sess
        while len(store) > cap:
            _, old = store.popitem(last=False)
            close_quietly(old)
    else:
        store.move_to_end(key)
    return sess
