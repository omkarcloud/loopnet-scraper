"""Start the LoopNet Scraper API.

    python run.py            # http://localhost:8000
    PORT=9000 python run.py  # another port

Then:  curl "http://localhost:8000/listings/details?listing=43019700"

The first LoopNet page opens Chrome for ~20 seconds to earn LoopNet's access
cookies; every request after that is plain HTTP.
"""
import bottle
from cheroot import wsgi

import config
import routes  # noqa: F401  (mounts the routes on bottle's default app)


def main():
    app = bottle.default_app()
    print(f"LoopNet Scraper listening on http://localhost:{config.PORT}/")
    print(f"Try:  curl \"http://localhost:{config.PORT}/listings/details?listing=43019700\"")
    server = wsgi.Server(("0.0.0.0", config.PORT), app, server_name="loopnet-scraper", numthreads=16)
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
