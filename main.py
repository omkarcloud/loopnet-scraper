"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. The schemas in loopnet/schemas.py turn the same inputs the API
takes (an id or a loopnet.com link, a place name...) into the function's
arguments.
"""
import json
import os

from loopnet import api, schemas

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a listing id or any loopnet.com listing link
    listing = schemas.ListingSchema().load({"listing": "43019700"})
    save("listing_43019700.json", api.listing_details(**listing))

    # 40 listings per page; filter by listing type, property type, price, size and cap rate
    search = schemas.ListingsSearchSchema().load({"query": "Beverly Hills, CA", "listing_type": "sale"})
    save("search_beverly_hills_for_sale.json", api.listings_search(**search))

    # a broker profile id or link
    broker = schemas.BrokerSchema().load({"broker": "ywdxjssb"})
    save("broker_ywdxjssb.json", api.broker_details(**broker))
