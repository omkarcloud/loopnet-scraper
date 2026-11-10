"""Offline tests for the LoopNet parsers, reference resolvers and value
helpers.

    python -m pytest loopnet/test_parsers.py -q

Fixtures are real www.loopnet.com pages captured 2026-11-07
(loopnet/fixtures/): a for-sale search page (Texas, 750 cap), a for-lease
page 2 (Los Angeles), the auctions page, a filtered lease search (9
results), the 404 search page, a lease listing (8 spaces, amenities,
sustainability, brochure, owner), an auction sale listing (offering
memorandum, demographics, Matterport), a plain sale listing (condo units
table, external links), the listing-not-found page, a broker directory
page, two broker search results, a broker profile, a 404 broker page, a
company page (+ page 2), a property record, four geography lookups, the
traffic counts JSON and a mini-placards reply. No network.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loopnet import parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


@pytest.fixture(scope="module")
def sale_search():
    return P.parse_search(fixture("search_sale_tx.html"))


@pytest.fixture(scope="module")
def lease_listing():
    return P.parse_listing(fixture("listing_lease.html"))


@pytest.fixture(scope="module")
def auction_listing():
    return P.parse_listing(fixture("listing_sale_auction.html"))


@pytest.fixture(scope="module")
def sale_listing():
    return P.parse_listing(fixture("listing_sale.html"))


# ---- refs --------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("29122043", {"id": 29122043, "slug": None}),
    ("https://www.loopnet.com/Listing/11340-W-Olympic-Blvd-Los-Angeles-CA/29122043/",
     {"id": 29122043, "slug": "11340-W-Olympic-Blvd-Los-Angeles-CA"}),
    ("www.loopnet.com/Listing/29122043/", {"id": 29122043, "slug": None}),
    ("https://www.loopnet.com/listing/x/29122043?src=1", {"id": 29122043, "slug": "x"}),
])
def test_resolve_listing(value, expected):
    assert refs.resolve_listing(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "12", "https://example.com/Listing/x/29122043/",
                                   "https://www.loopnet.com/company/x/0r9nt33l/"])
def test_resolve_listing_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_listing(value)


def test_resolve_broker_company_property():
    assert refs.resolve_broker("8LYBYL0B") == {"id": "8lybyl0b", "slug": None}
    assert refs.resolve_broker("https://www.loopnet.com/commercial-real-estate-brokers/profile/keith-fielding/8lybyl0b/29122043") == \
        {"id": "8lybyl0b", "slug": "keith-fielding"}
    assert refs.resolve_company("https://www.loopnet.com/company/lee-associates-west-la/0r9nt33l/2/") == \
        {"id": "0r9nt33l", "slug": "lee-associates-west-la"}
    assert refs.resolve_property("20209-054121") == {"id": "20209-054121", "slug": None}
    assert refs.resolve_property("https://www.loopnet.com/property/900-n-18th-st-kansas-city-ks-66102/20209-054121/") == \
        {"id": "20209-054121", "slug": "900-n-18th-st-kansas-city-ks-66102"}
    assert refs.resolve_business("https://www.loopnet.com/biz/business-opportunity/turnkey-charcuterie-business/2573303/") == \
        {"id": 2573303, "slug": "turnkey-charcuterie-business"}
    for bad in ("hello", "https://www.loopnet.com/Listing/x/1/"):
        with pytest.raises(ValueError):
            refs.resolve_property(bad)
    with pytest.raises(ValueError):
        refs.resolve_broker("https://www.loopnet.com/company/x/0r9nt33l/")


def test_broker_link_has_no_trailing_slash():
    assert refs.broker_link("8lybyl0b", "keith-fielding").endswith("/keith-fielding/8lybyl0b")


def test_parse_search_link_and_paths():
    parsed = refs.parse_search_link("https://www.loopnet.com/search/office-space/los-angeles-ca/for-lease/2/?min-rent=20&sort=newest")
    assert parsed == {"property_type_slug": "office-space", "geo_slug": "los-angeles-ca", "listing_type": "lease",
                      "page": 2, "params": {"min-rent": "20", "sort": "newest"}}
    assert refs.parse_search_link("Austin, TX") is None
    with pytest.raises(ValueError):
        refs.parse_search_link("https://www.loopnet.com/Listing/x/29122043/")
    assert refs.search_path("commercial-real-estate", "tx", "sale", 3, {"min-price": 5, "keyword": "warehouse"}) == \
        "/search/commercial-real-estate/tx/for-sale/3/?min-price=5&keyword=warehouse"
    assert refs.search_path("land", "usa", "auction") == "/search/land/usa/auctions/"


def test_parse_lat_lng():
    assert refs.parse_lat_lng("34.0374, -118.4417") == (34.0374, -118.4417)
    assert refs.parse_lat_lng("Austin, TX") is None
    assert refs.parse_lat_lng("95,10") is None


def test_broker_location():
    assert refs.resolve_broker_location("Austin, TX") == {"state": "TX", "city": "austin"}
    assert refs.resolve_broker_location("texas") == {"state": "TX", "city": None}
    assert refs.resolve_broker_location("Los Angeles, California") == {"state": "CA", "city": "los-angeles"}
    assert refs.resolve_broker_location("https://www.loopnet.com/commercial-real-estate-brokers/united-states/ca/los-angeles/3/") == \
        {"state": "CA", "city": "los-angeles"}
    with pytest.raises(ValueError):
        refs.resolve_broker_location("Paris, FR")
    assert refs.broker_directory_path("CA", "los-angeles", 2, "1") == "/commercial-real-estate-brokers/united-states/ca/los-angeles/2/?sorting=1"


def test_geo_slugs_from_typeahead_rows():
    rows = {r["name"]: r for r in P.parse_geography_lookup(fixture("geography_texas.json"))}
    assert rows["Texas"]["type"] == "state" and rows["Texas"]["slug"] == "tx"
    assert rows["Texas City, TX"]["slug"] == "texas-city-tx"
    assert rows["Texas County, MO"]["type"] == "county" and rows["Texas County, MO"]["slug"] == "texas-county-mo"
    zip_rows = P.parse_geography_lookup(fixture("geography_90064.json"))
    assert zip_rows[0]["type"] == "postal_code" and zip_rows[0]["slug"] == "los-angeles-ca-90064"
    assert zip_rows[0]["postal_code"] == "90064" and zip_rows[0]["city"] == "Los Angeles"
    county = [r for r in P.parse_geography_lookup(fixture("geography_la_county.json")) if r["type"] == "county"][0]
    assert county["slug"] == "los-angeles-county-ca" and county["id"] == "186"
    austin = P.parse_geography_lookup(fixture("geography_austin.json"))
    assert austin[0]["slug"] == "austin-tx" and austin[0]["latitude"] == pytest.approx(30.2939, abs=1e-3)
    assert austin[0]["bounding_box"]["north"] > austin[0]["bounding_box"]["south"]
    assert all(r["id"] for r in austin)          # the empty-id Guildford row is dropped
    assert P.parse_geography_lookup(fixture("geography_empty.json")) == []


# ---- value helpers -------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("$581,350 - $1,375,000", (581350, 1375000, "USD", None)),
    ("$41.40 SF/YR", (41.4, 41.4, "USD", "sf_year")),
    ("$3.45 /SF/MO", (3.45, 3.45, "USD", "sf_month")),
    ("From $37,301 /YR", (37301, 37301, "USD", "year")),
    ("From $581,350 per unit", (581350, 581350, "USD", "unit")),
    ("$1,400,000 Starting Bid", (1400000, 1400000, "USD", None)),
    ("$1.2M", (1200000, 1200000, "USD", None)),
])
def test_parse_price(value, expected):
    price = P.parse_price(value)
    assert (price["min"], price["max"], price["currency"], price["basis"]) == expected
    assert price["text"] == value


def test_parse_price_masks_keep_text():
    assert P.parse_price("Price Upon Request") == {"text": "Price Upon Request", "min": None, "max": None,
                                                   "currency": None, "basis": None}
    assert P.parse_price("") is None
    assert P.parse_price("$2,112,000 ($550/SF)")["min"] == 2112000


@pytest.mark.parametrize("value,expected", [
    ("901 - 4,592 SF", (901, 4592, "sf")),
    ("24,279 SF", (24279, 24279, "sf")),
    ("1.46 AC", (1.46, 1.46, "acre")),
    ("3.04 AC", (3.04, 3.04, "acre")),
])
def test_parse_size(value, expected):
    size = P.parse_size(value)
    assert (size["min"], size["max"], size["unit"]) == expected


def test_phone_and_names():
    assert P._phone("tel:+13108992719") == "+13108992719"
    assert P._phone("(941) 202-4259 x2212") == "+19412024259 x2212"
    assert P._phone("tel:+19412024259,2212") == "+19412024259 x2212"
    assert P._phone("+1 630-699-9687") == "+16306999687"
    assert P._phone("") is None
    assert P._split_name_title("David Noonan, Senior Managing Director") == ("David Noonan", "Senior Managing Director")
    assert P._split_city_state("Los Angeles, CA 90064") == ("Los Angeles", "CA", "90064")
    assert P._split_city_state("New York, NY") == ("New York", "NY", None)
    assert P._snake("SpaceUse") == "space_use" and P._snake("Rental Rate:") == "rental_rate"
    assert P._iso("2026-11-17T17:00:00.0000000+00:00") == "2026-11-17T17:00:00+00:00"


# ---- search pages ---------------------------------------------------------------------------

def test_search_sale_page(sale_search):
    assert sale_search["total"] == 750 and sale_search["is_total_capped"] is True
    assert sale_search["page"] == 1 and sale_search["items_per_page"] == 40
    assert sale_search["place"] == "Texas - USA"
    assert sale_search["geography"]["type"] == "state" and sale_search["geography"]["id"] == 44
    assert sale_search["geography"]["bounding_box"]["north"] == pytest.approx(36.5034, abs=1e-3)
    assert sale_search["applied_filters"]["listingType"] == 1
    results = sale_search["results"]
    assert len(results) == 40
    first = results[0]
    assert first["id"] == 42148644
    assert first["link"] == "https://www.loopnet.com/Listing/W-Spring-Creek-Pkwy-Midway-Rd-Plano-TX/42148644/"
    assert first["name"] == "THE GARAGE By Dennis Collins"
    assert first["address"] == "W Spring Creek Pkwy & Midway Rd, Plano, TX 75024"
    assert (first["city"], first["state"], first["postal_code"], first["country"]) == ("Plano", "TX", "75024", "US")
    assert first["listing_type"] == "sale" and first["listing_category"] == "ConsolidatedCondosForSale"
    assert first["property_type"] == "Flex" and first["property_type_label"] == "Flex Condos"
    assert first["price"]["min"] == 581350 and first["price"]["max"] == 1375000
    assert first["size"]["min"] == 1057 and first["size"]["max"] == 2500
    assert first["units_count"] == 3
    assert first["latitude"] == pytest.approx(33.0657, abs=1e-3) and first["longitude"] == pytest.approx(-96.8386, abs=1e-3)
    assert first["brokers"][0]["name"] == "Adam Hancock" and first["brokers"][0]["company"] == "Foundry Capital LLC"
    assert first["brokers"][0]["photo"].startswith("https://")
    assert len(first["photos"]) > 5 and first["photos"][0]["link"].startswith("https://images")
    assert first["exposure_tier"] == "Tier1" and first["position"] == 1
    assert first["is_auction"] is False and first["auction"] is None
    assert first["description"].startswith("A private community")
    portfolio = next(r for r in results if r["id"] == 30900890)
    assert portfolio["listing_category"] == "CommercialPortfolioForSale"
    assert portfolio["properties_count"] == 3 and portfolio["price"]["text"] == "Price Upon Request"
    assert portfolio["price"]["min"] is None
    renovated = next(r for r in results if r["year_renovated"])
    assert 1900 < renovated["year_renovated"] <= 2026
    assert next(r for r in results if r["id"] == 41189404)["year_renovated"] == 2011


def test_search_lease_page():
    parsed = P.parse_search(fixture("search_lease_la_p2.html"))
    assert parsed["page"] == 2 and parsed["total"] == 750
    # the search page's gState codes are not the typeahead's: Los Angeles is t=3 there
    assert parsed["geography"]["type"] == "city" and parsed["geography"]["id"] == 41096
    assert len(parsed["results"]) == 40
    assert all(r["listing_type"] == "lease" for r in parsed["results"])
    rated = next(r for r in parsed["results"] if r["rating"])
    assert 1 <= rated["rating"] <= 5
    priced = next(r for r in parsed["results"] if r["price"] and r["price"]["basis"])
    assert priced["price"]["basis"] in ("sf_year", "sf_month")
    spaces = next(r for r in parsed["results"] if r["spaces_count"])
    assert spaces["spaces_count"] >= 1


def test_search_filtered_lease_page():
    parsed = P.parse_search(fixture("search_lease_filters.html"))
    assert parsed["total"] == 9 and parsed["is_total_capped"] is False
    assert len(parsed["results"]) == 9
    filters = parsed["applied_filters"]
    assert filters["listingType"] == 2 and filters["leaseFilters"]["rentMin"] == 20
    assert filters["kq"] == "creative" or filters["leaseFilters"].get("kq") == "creative" or "creative" in json.dumps(filters)


def test_search_auction_page():
    parsed = P.parse_search(fixture("search_auctions_usa.html"))
    assert parsed["total"] == 177 and parsed["geography"]["type"] == "country"
    assert len(parsed["results"]) == 40
    first = parsed["results"][0]
    assert first["is_auction"] is True and first["listing_type"] == "auction"
    auction = first["auction"]
    assert auction["status"] == "scheduled"
    assert auction["starts_at"] == "2026-11-05T17:00:00+00:00" and auction["ends_at"] == "2026-11-17T17:00:00+00:00"
    assert auction["current_bid"]["min"] == 5001 and auction["bid_increment"]["min"] == 2500
    assert auction["is_reserve_met"] is True and auction["has_live_bids"] is True
    assert auction["auction_listing_id"] == 20027471
    assert auction["highlights"][0].startswith("Opportunity Zone")
    assert auction["documents_link"].startswith("https://www.loopnet.com/Listing/205-S-Greenville-West-Dr")
    assert first["size"]["unit"] == "acre" and first["size"]["min"] == 3.04
    starting = next(r for r in parsed["results"] if r["auction"]["starting_bid"])
    assert starting["auction"]["starting_bid"]["min"] >= 1
    not_met = next(r for r in parsed["results"] if r["auction"]["is_reserve_met"] is False)
    assert not_met["auction"]["starting_bid"]["min"] == 1
    unknown = next(r for r in parsed["results"] if r["auction"]["is_reserve_met"] is None)
    assert unknown["auction"]["current_bid"] is None


def test_search_not_found_pages():
    assert P.parse_search(fixture("search_404.html")) is None
    assert P.is_not_found_page(fixture("listing_not_found.html")) is True
    assert P.is_not_found_page(fixture("search_sale_tx.html")) is False


# ---- listing pages ----------------------------------------------------------------------------

def test_lease_listing_header(lease_listing):
    r = lease_listing
    assert r["id"] == 29122043
    assert r["link"] == "https://www.loopnet.com/Listing/11340-W-Olympic-Blvd-Los-Angeles-CA/29122043/"
    assert r["name"] == "CPLA" and r["address"] == "11340 W Olympic Blvd"
    assert (r["city"], r["state"], r["postal_code"], r["country"]) == ("Los Angeles", "CA", "90064", "US")
    assert r["latitude"] == pytest.approx(34.0374, abs=1e-3)
    assert r["listing_type"] == "lease" and r["headline"] == "Office for Lease 901 - 15,746 SF"
    assert r["summary"] == ["Office for Lease", "8 Spaces Available", "901 - 15,746 SF", "Renovated 2000"]
    assert r["price"]["min"] == 41.4 and r["price"]["basis"] == "sf_year"
    assert r["rates"]["per_sf_month"]["min"] == 3.45 and r["rates"]["per_year"]["min"] == 37301
    assert r["property_type"] == "Office" and r["building_class"] == "A" and r["floors"] == 3
    assert r["building_size"]["min"] == 84850 and r["rating"] == 4
    assert r["property_facts"]["typical_floor_size"] == "28,283 SF"
    assert r["date_on_market"] == "2024-05-21" and r["last_updated"] == "2026-09-22"
    assert r["is_off_market"] is False
    assert r["breadcrumbs"][-1] == "11340 W Olympic Blvd, Los Angeles, CA 90064"
    assert r["description_title"] == "Property Overview" and r["description"].startswith("CPLA AT 11340")
    assert len(r["highlights"]) == 6


def test_lease_listing_spaces(lease_listing):
    spaces = lease_listing["spaces"]
    assert len(spaces) == 8
    first = spaces[0]
    assert first["id"] == 17759427 and first["name"] == "1st Floor, Ste 100"
    assert first["use"] == "Office" and first["size"]["min"] == 4592
    assert first["rate"]["min"] == 41.4 and first["rates"]["per_month"]["min"] == 15842
    assert first["rent_type"] == "Full Service" and first["term"] == "2 Years"
    assert first["build_out"] == "Fully Built-Out as Standard Office"
    assert first["details"]["build_out"] == first["build_out"]
    assert first["layout"] == "Mostly Open Floor Plan"
    assert first["description"].startswith("The recently reimagined CPLA")
    assert first["attachments"][0]["extension"] == "pdf" and first["attachments"][0]["link"].endswith(".pdf")
    assert len(first["media"]) == 5 and first["media"][-1]["caption"] == "Floor Plan"
    contiguous = next(s for s in spaces if s["contiguous_note"])
    assert "2,451 SF" in contiguous["contiguous_note"]


def test_lease_listing_sections(lease_listing):
    r = lease_listing
    assert r["amenities"]["Building Features & Infrastructure"] == ["Courtyard", "Signage"]
    assert r["sustainability"] == [{"program": "ENERGY STAR", "score": 91, "score_total": 100,
                                    "description": r["sustainability"][0]["description"]}]
    assert r["commute_scores"]["walk"] == {"score": 80, "label": "Very walkable"}
    assert r["commute_scores"]["bike"]["score"] == 50
    assert r["brochure"]["link"].endswith("document.pdf") and r["brochure"]["is_locked"] is False
    assert r["offering_memorandum"] is None and r["has_secure_information"] is False
    assert r["market_narrative"]["title"] == "About Olympic Corridor"
    assert r["photos_count"] == 28 and r["photos"][0]["type"] == "Primary Photo"
    assert r["photos"][0]["width"] == 1350
    assert r["team"]["type"] == "leasing_team" and r["team"]["company"]["id"] == "0r9nt33l"
    assert r["team"]["company"]["link"] == "https://www.loopnet.com/company/lee-associates-west-la/0r9nt33l/"
    members = r["team"]["members"]
    assert len(members) == 3
    assert members[0] == {
        "id": "8lybyl0b", "name": "Keith Fielding", "title": "Principal",
        "link": "https://www.loopnet.com/commercial-real-estate-brokers/profile/keith-fielding/8lybyl0b",
        "phone": "+13108992719", "phone_text": "(310) 899-2719",
        "photo": members[0]["photo"], "bio": members[0]["bio"], "is_power_broker": True}
    assert members[0]["bio"].startswith("Keith Fielding is a Principal")
    assert r["brokers"] == members
    assert r["contact_phone"] == "+14243178212"
    assert r["owner"]["name"] == "Vantage Property Investors" and r["owner"]["id"] == "r0r83q1l"
    assert r["owner"]["role"] == "About the Owner"
    assert r["offers"][0]["price"] == 41.4 and r["offers"][0]["currency"] == "USD"
    assert r["auction"] is None and r["demographics"] == []


def test_auction_listing(auction_listing):
    r = auction_listing
    assert r["id"] == 42750507 and r["listing_type"] == "auction"
    assert r["name"] == "Versatile Retail/Office Condo Package"
    assert r["address"] == "11-15 E Broadway" and r["city"] == "New York" and r["postal_code"] == "10038"
    assert r["price"] is None
    assert r["auction"]["starting_bid"]["min"] == 1400000
    assert r["auction"]["ends_at"] == "2026-12-02T17:00:00+00:00"
    assert r["auction"]["contact"]["name"] == "Victoria Quade"
    assert r["auction"]["contact"]["phone"] == "+19412024259 x2212"
    assert r["auction"]["contact"]["auctioneer_license"].startswith("Ten-X")
    assert r["offers"][0]["price"] == 1400000 and r["offers"][0]["valid_through"] == "2026-12-02T17:00:00+00:00"
    assert r["sale_type"] == "Investment" and r["property_subtype"] == "Loft/Creative Space"
    assert r["year_built"] == 1991 and r["lot_size"]["min"] == 5610
    assert r["building_size"]["min"] == 61173 and r["floors"] == 15
    assert r["zoning"].startswith("C6-1G")
    assert r["offering_memorandum"]["is_locked"] is True
    assert r["has_secure_information"] is True and r["is_secure_information_locked"] is True
    assert len(r["attachments"]) == 5 and r["attachments"][1]["name"] == "Basement"
    assert r["attachments"][0]["extension"] == "svg"
    assert r["virtual_tours"][0]["link"].startswith("https://my.matterport.com/show/?m=3qVdi4uSjpq")
    assert r["spaces"][0]["name"] == "Lower Level - Unit 1-3" and r["spaces"][0]["use"] == "Flex"
    assert r["spaces"][0]["size"]["min"] == 16795 and r["spaces"][0]["sale_type"] == "Investment"
    population = next(d for d in r["demographics"] if d["metric"] == "2025 Population")
    assert population["1_mile"] == 198882 and population["5_mile"] == 2759265 and population["unit"] is None
    income = next(d for d in r["demographics"] if d["metric"] == "Median Household Income")
    assert income["1_mile"] == 108355 and income["unit"] == "usd"
    growth = next(d for d in r["demographics"] if d["metric"].startswith("Population Growth"))
    assert growth["3_mile"] == 5.8 and growth["unit"] == "percent"
    assert r["team"]["type"] == "sale_advisors" and r["team"]["company"]["name"] == "Newmark"
    assert r["brokers"][0]["name"] == "David Noonan" and r["brokers"][0]["title"] == "Senior Managing Director"
    assert r["brokers"][0]["phone"] == "+12123722268"
    assert r["date_on_market"] == "2026-10-26"
    assert r["description_title"] == "Executive Summary"


def test_sale_listing_with_condo_table(sale_listing):
    r = sale_listing
    assert r["id"] == 40977810 and r["listing_type"] == "sale"
    assert r["name"] == "Palmera Plano"
    assert r["address"] == "4521 State Highway 121" and r["city"] == "Plano" and r["postal_code"] == "75024"
    assert r["price"]["text"] == "From $1,144,000 per unit" and r["price"]["basis"] == "unit"
    assert r["summary"][1] == "13 Condo Units"
    assert r["property_type"] == "Office" and r["year_built"] == 2028
    assert r["property_facts"]["parking_ratio"] == "3.11/1,000 SF"
    assert r["external_links"] == [{"name": "View the Palmera Plano Website", "link": "http://www.palmeraplano.com/"}]
    spaces = r["spaces"]
    assert len(spaces) == 13
    unit = next(s for s in spaces if s["id"] == 6668218)
    assert unit["name"] == "1st Floor - Unit BLDG 01" and unit["use"] == "Office"
    assert unit["size"]["min"] == 3840 and unit["price"]["min"] == 2112000
    assert unit["price_per_sf"]["min"] == 550 and unit["price_per_sf"]["basis"] == "sf"
    assert unit["availability"] == "Oct 31, 2027"
    assert r["auction"] is None


def test_whole_building_sale_takes_type_and_size_from_the_headline():
    # the facts list has no Property Type / Building Size rows; the headline
    # "Retail for Sale 4,959 SF" carries both, and $10,495,000 / $2,116.35 per SF
    # lands on 4,959 SF, so the size is the building's
    r = P.parse_listing(fixture("listing_sale_building.html"))
    assert r["id"] == 43019700 and r["listing_type"] == "sale"
    assert r["headline"] == "Retail for Sale 4,959 SF"
    assert "property_type" not in r["property_facts"] and "building_size" not in r["property_facts"]
    assert r["property_type"] == "Retail"
    assert r["building_size"] == {"text": "4,959 SF", "min": 4959, "max": 4959, "unit": "sf"}
    assert r["price"]["min"] == 10495000 and r["price_per_sf"]["min"] == 2116.35
    assert r["property_facts"]["apn_parcel_id"] == "4333-005-020"
    assert r["spaces"] == [] and r["demographics"] == []


def test_headline_size_is_not_the_building_when_the_page_does_not_prove_it(auction_listing, sale_listing):
    # condo units: the headline shows the unit sizes, the facts the building
    assert auction_listing["building_size"]["min"] == 61173
    assert sale_listing["building_size"]["min"] == 48220
    kpis = ["Retail for Sale", "4,959 SF"]
    price = {"min": 10495000}
    assert P._headline_building_size(kpis, [], price, {"min": 2116.35})["min"] == 4959
    assert P._headline_building_size(kpis, [], price, {"min": 1500}) is None        # price / SF disagrees
    assert P._headline_building_size(kpis, [{"id": 1}], price, {"min": 2116.35}) is None
    assert P._headline_building_size(["Office for Sale", "600 - 2,470 SF"], [], price, {"min": 500}) is None
    assert P._headline_building_size(kpis, [], None, None) is None
    assert P._headline_type("Office for Lease 901 - 15,746 SF") == "Office"
    assert P._headline_type("Flex for Auction 16,795 SF") == "Flex"
    assert P._headline_type("Featured") is None


def test_listing_not_found_page_is_not_a_listing():
    assert P.parse_listing(fixture("listing_not_found.html")) is None


# ---- brokers ----------------------------------------------------------------------------------

def test_broker_directory_page():
    parsed = P.parse_broker_directory(fixture("brokers_directory_ca_2.html"))
    assert parsed["heading"] == "California CA - USA Commercial Real Estate Brokers"
    assert parsed["has_next"] is True and parsed["has_prev"] is True
    results = parsed["results"]
    assert len(results) == 10
    first = results[0]
    assert first["id"] == "7wexbfyb" and first["name"] == "Elena Saccone"
    assert first["link"] == "https://www.loopnet.com/commercial-real-estate-brokers/profile/elena-saccone/7wexbfyb"
    assert first["title"] == "Senior Associate" and first["company"] == "Cushman & Wakefield"
    assert first["city"] == "San Francisco" and first["state"] == "CA"
    assert first["listings_count"] == 1 and first["languages"] == ["English"]
    assert first["office_phone"] == "+16306999687" and first["mobile_phone"] is None
    assert first["has_email_form"] is True
    assert first["photo"].startswith("https://images") and first["company_logo"].startswith("https://images")
    mobile = next(r for r in results if r["mobile_phone"])
    assert mobile["mobile_phone"].startswith("+1")
    no_title = next(r for r in results if r["title"] is None)
    assert no_title["company"]


def test_broker_search_results():
    by_name = P.parse_broker_directory(fixture("brokers_search_name.html"))
    assert len(by_name["results"]) == 1 and by_name["results"][0]["id"] == "8lybyl0b"
    assert by_name["results"][0]["listings_count"] == 29 and by_name["has_next"] is False
    by_company = P.parse_broker_directory(fixture("brokers_search_company.html"))
    assert len(by_company["results"]) == 10 and by_company["has_next"] is True
    assert all("Lee & Associates" in r["company"] for r in by_company["results"])


def test_broker_profile():
    r = P.parse_broker_profile(fixture("broker_profile.html"), "8lybyl0b")
    assert r["id"] == "8lybyl0b" and r["name"] == "Keith Fielding"
    assert r["title"] == "Principal"
    assert r["company"] == {"id": "0r9nt33l", "name": "Lee & Associates - West LA",
                            "link": "https://www.loopnet.com/company/lee-associates-west-la/0r9nt33l/",
                            "website": "https://www.lee-associates.com/", "logo": r["company"]["logo"]}
    assert r["city"] == "Santa Monica" and r["state"] == "CA" and r["postal_code"] == "90404"
    assert r["tagline"] == "Tenant and landlord representation"
    assert r["phone"] == "+13108992719" and r["phones"] == ["+13108992719"]
    assert r["specialties"] == ["Investment Sales Broker"]
    assert r["property_types"] == ["Industrial", "Land", "Office", "Retail", "Flex", "Multifamily"]
    assert r["markets"] == ["Los Angeles"] and r["languages"] == ["English"]
    assert r["bio"].startswith("Keith Fielding is a Principal")
    assert r["listings_count"] == 20 and len(r["listings"]) == 20
    assert r["listings"][0]["id"] == 29122043 and r["listings"][0]["summary"] == "901 - 15,746 SF / Office"
    assert r["listings"][0]["postal_code"] == "90064"
    assert r["breadcrumbs"] == ["Broker Search", "United States", "California", "Santa Monica"]


def test_broker_404_page_is_not_a_profile():
    assert P.parse_broker_profile(fixture("broker_404.html")) is None


# ---- company ----------------------------------------------------------------------------------

def test_company_page():
    r = P.parse_company(fixture("company.html"), "0r9nt33l")
    assert r["id"] == "0r9nt33l" and r["name"] == "Lee & Associates - West LA"
    assert r["link"] == "https://www.loopnet.com/company/lee-associates-west-la/0r9nt33l/"
    assert r["website"] == "https://www.lee-associates.com/"
    assert r["address"] == "1508 17th St" and r["city"] == "Santa Monica" and r["postal_code"] == "90404"
    assert r["phone"] == "+13108992700"
    assert r["description"].startswith("Lee & Associates began in 1979")
    assert r["contacts_count"] == 32 and r["contacts"][0]["id"] and r["contacts"][0]["phone"].startswith("+1")
    assert r["listing_pages"] == 8
    listings = r["listings"]
    assert len(listings) == 20
    first = listings[0]
    assert first["id"] == 29122043 and first["address"] == "11340 W Olympic Blvd"
    assert first["listing_type"] == "lease" and first["property_type"] == "Office"
    assert first["headline"] == "15,746 SF Office Available"
    assert first["price"]["min"] == 41.4 and first["size"]["min"] == 901 and first["year_built"] == 1975
    assert first["rating"] == 4 and first["brokers"][0]["name"] == "Keith Fielding"
    page2 = P.parse_company(fixture("company_p2.html"), "0r9nt33l")
    assert len(page2["listings"]) == 20 and page2["listings"][0]["id"] != first["id"]


# ---- property record ----------------------------------------------------------------------------

def test_property_record():
    r = P.parse_property_record(fixture("property_record.html"), "20209-054121")
    assert r["id"] == "20209-054121"
    assert r["link"] == "https://www.loopnet.com/property/900-n-18th-st-kansas-city-ks-66102/20209-054121/"
    assert r["name"] == "900 N 18Th St, Kansas City, KS 66102" and r["address"] == "900 N 18Th St"
    assert (r["city"], r["state"], r["postal_code"], r["country"]) == ("Kansas City", "KS", "66102", "US")
    assert r["parcel_number"] == "054121" and r["county"] == "Wyandotte" and r["zoning"] == "KR2"
    assert r["land_use"] == "Storemultistory" and r["lot_number"] == "22"
    assert r["lot_size"]["min"] == 0.16 and r["lot_size"]["unit"] == "acre"
    assert r["total_size"]["min"] == 5818 and r["tax_year"] == 2025 and r["assessment_year"] == 2025
    assert r["submarket"] == "Kansas City KS" and r["cbsa"] == "Kansas City, MO-KS" and r["census_tract"] == "041600"
    assert r["flood_zone"].startswith("B and X")
    assert r["details"]["state_name"] == "Kansas"
    assert r["contained_in"][0] == "Kansas City"
    assert len(r["photos"]) >= 1 and r["photos"][0].startswith("https://images")
    assert len(r["nearby_listings"]) == 7
    assert r["nearby_listings"][0]["id"] == 40926828 and r["nearby_listings"][0]["price"]["min"] == 3997241
    assert r["nearby_listings"][0]["size"]["min"] == 8400 and r["nearby_listings"][0]["property_type"] == "Office"
    population = r["demographics"][0]
    assert population["metric"] == "2025 Total Population" and population["1_mile"] == 19945
    growth = next(d for d in r["demographics"] if d["metric"] == "Pop Growth 2025-2030")
    assert growth["1_mile"] == 2.13 and growth["unit"] == "percent"
    income = next(d for d in r["demographics"] if d["metric"] == "Median Household Inc")
    assert income["5_mile"] == 58099 and income["unit"] == "usd"
    rail = r["public_transportation"][0]
    assert rail["category"] == "COMMUTER RAIL" and rail["drive_time"] == "13 min" and rail["distance_miles"] == 6.5
    airport = r["public_transportation"][1]
    assert airport["category"] == "AIRPORT" and airport["name"] == "Kansas City International"
    assert len(r["nearby_properties"]) > 20
    assert r["nearby_properties"][0]["id"] == "20209-087645"
    assert r["nearby_properties"][0]["total_size"]["min"] == 126962 and r["nearby_properties"][0]["zoning"] == "KC0"


# ---- JSON services ---------------------------------------------------------------------------

def test_traffic_counts():
    rows = P.parse_traffic(fixture("traffic.json"))
    assert rows[0] == {"street": "W Olympic Blvd", "cross_street": "Corinth Ave", "cross_street_direction": "SW",
                       "traffic_count": 49268, "year": 2026, "distance_miles": 0.03,
                       "latitude": 34.037889, "longitude": -118.441753}
    assert len(rows) >= 5
    none = P.parse_traffic(fixture("traffic_none.json"))
    assert none[0]["street"] == "Not Available"


def test_mini_placards():
    cards = P.parse_mini_placards(fixture("mini_placards.json"))
    assert cards[29122043]["link"] == "https://www.loopnet.com/Listing/11340-W-Olympic-Blvd-Los-Angeles-CA/29122043/"
    assert cards[29122043]["address"] == "11340 W Olympic Blvd" and cards[29122043]["is_auction"] is False
    assert cards[42750507]["is_auction"] is True and cards[42750507]["property_type"] == "Flex Condo"
    assert 999999999 not in cards


def test_parsers_never_crash_on_junk():
    assert P.parse_search("") is None
    assert P.parse_listing("<html><body>x</body></html>") is None
    assert P.parse_broker_directory("") is None
    assert P.parse_broker_profile("<html></html>") is None
    assert P.parse_company("<html></html>") is None
    assert P.parse_property_record("<html></html>") is None
    assert P.parse_geography_lookup(None) == [] and P.parse_traffic([{}]) == [
        {"street": None, "cross_street": None, "cross_street_direction": None, "traffic_count": None, "year": None,
         "distance_miles": None, "latitude": None, "longitude": None}]
    assert P.parse_mini_placards([{"listingId": "x"}]) == {}
