"""Debug dumps: keep the raw body of a failed response for a post-mortem."""
import os


def dump(env_var, name, text, encoding=None):
    """Write `text` to $<env_var>/<name>.txt. Does nothing when the variable
    is unset or the text is empty; a write failure is swallowed."""
    dbg = os.environ.get(env_var, "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w", encoding=encoding) as f:
                f.write(text)
        except OSError:
            pass
