"""Offline tests for the BizBuySell parsers, reference resolvers and value
helpers.

    python -m pytest bizbuysell/test_parsers.py -q

Fixtures are real www.bizbuysell.com answers captured 2026-10-31
(bizbuysell/fixtures/): search JSON (keyword, filtered, no match), three
listing pages (owner with phone, broker, franchise resale), the not-found
page, broker directory / account / typeahead / no-match JSON, franchise
search (filtered, past the end), the Lawn Doctor brochure, the unknown
franchise answer, the category list and a county sample. No network.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bizbuysell import parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


# ---- refs -------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("2548034", {"id": 2548034, "slug": None}),
    (" 2548034 ", {"id": 2548034, "slug": None}),
    ("https://www.bizbuysell.com/business-opportunity/lb-fuel-gas-station/2567126/",
     {"id": 2567126, "slug": "lb-fuel-gas-station"}),
    ("https://www.bizbuysell.com/business-opportunity/x/2567126/amp/", {"id": 2567126, "slug": "x"}),
    ("www.bizbuysell.com/business-opportunity/some-slug/2504737/?utm=1", {"id": 2504737, "slug": "some-slug"}),
])
def test_resolve_listing(value, expected):
    assert refs.resolve_listing(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "12", "https://example.com/business-opportunity/x/2548034/",
                                   "https://www.bizbuysell.com/business-brokers/california/"])
def test_resolve_listing_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_listing(value)


def test_resolve_broker():
    assert refs.resolve_broker("15309") == {"id": 15309, "name": None, "company": None}
    assert refs.resolve_broker(
        "https://www.bizbuysell.com/business-broker/prabhjot-randhawa/liberty-business-advisors-of-s-f-inc/15309/") == \
        {"id": 15309, "name": "prabhjot-randhawa", "company": "liberty-business-advisors-of-s-f-inc"}
    with pytest.raises(ValueError):
        refs.resolve_broker("https://www.bizbuysell.com/business-brokers/california/")
    with pytest.raises(ValueError):
        refs.resolve_broker("randhawa")


def test_resolve_franchise():
    assert refs.resolve_franchise("lawn-doctor-home-services-franchise") == "lawn-doctor-home-services-franchise"
    assert refs.resolve_franchise("https://www.bizbuysell.com/franchise-for-sale/Lawn-Doctor-Home-Services-Franchise/") == \
        "lawn-doctor-home-services-franchise"
    assert refs.resolve_franchise("biz/franchise-for-sale/woof-gang-bakery-and-grooming") == "woof-gang-bakery-and-grooming"
    with pytest.raises(ValueError):
        refs.resolve_franchise("https://www.bizbuysell.com/business-brokers/")
    with pytest.raises(ValueError):
        refs.resolve_franchise("not a slug!")


def test_resolve_state_and_category():
    assert refs.resolve_state("tx") == "TX"
    assert refs.resolve_state("Texas") == "TX"
    assert refs.resolve_state("new-york") == "NY"
    assert refs.resolve_state("Ontario") == "ON"
    with pytest.raises(ValueError):
        refs.resolve_state("Mars")
    assert refs.resolve_category("Restaurants & Food") == 17
    assert refs.resolve_category("restaurants and food") == 17
    assert refs.resolve_category("service-businesses") == 20
    assert refs.resolve_category("214") == 214
    with pytest.raises(ValueError):
        refs.resolve_category("spaceships")
    assert refs.resolve_franchise_category("Restaurant & Food") == 7
    assert refs.resolve_franchise_category("retail-franchise") == 10


def test_location_objects_and_county_names():
    assert refs.state_location("TX")["stateCode"] == "TX" and refs.state_location("TX")["countryCode"] == "US"
    assert refs.state_location("ON")["countryCode"] == "CA"
    assert refs.normalize_county("Los Angeles County") == "los angeles"
    assert refs.normalize_county("los-angeles-county") == "los angeles"
    assert refs.normalize_county("Orleans Parish") == "orleans"


# ---- helpers ----------------------------------------------------------------------------

def test_value_helpers():
    assert P._number("$1,300,000") == 1300000
    assert P._number("Not Disclosed") is None
    assert P._number(282000.0) == 282000
    assert P._number("1,000") == 1000
    assert P._money(0) is None and P._money(-1) is None and P._money("$449,000") == 449000
    assert P._year("2025") == 2025 and P._year("Not Disclosed") is None
    assert P._date("01/01/1970") == "1970-01-01"
    assert P._date("11/16/2026 12:00:00 PM") == "2026-11-16T12:00:00"
    assert P._date("12/14/2026 9:05 AM") == "2026-12-14T09:05:00"
    assert P._date("December 14-16, 2026") == "December 14-16, 2026"
    assert P._split_location("Long Beach, CA") == ("Long Beach", "CA")
    assert P._split_location("Illinois") == ("Illinois", None)
    assert P._image("/shared/brokerdirectory/images/1/pic.jpg") == \
        "https://images.bizbuysell.com/shared/brokerdirectory/images/1/pic.jpg"
    assert P._link("/business-brokers/texas/") == "https://www.bizbuysell.com/business-brokers/texas/"


# ---- search -----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def bakery():
    return P.parse_search(fixture("search_bakery.json")["bbsBfsSearchResult"])


@pytest.fixture(scope="module")
def texas():
    return P.parse_search(fixture("search_texas_restaurants_p1.json")["bbsBfsSearchResult"])


def test_search_drops_ad_rows(texas):
    raw = fixture("search_texas_restaurants_p1.json")["bbsBfsSearchResult"]
    assert len(raw["value"]) > len(texas["listings"])
    assert all(l["id"] for l in texas["listings"])
    # 50 result rows + one Ten-X auction placard the site inserts at offset 0;
    # the 6 franchise ads (type -1) and 4 inline ad / broker rows are gone
    assert len(texas["listings"]) == 51
    assert not any(l["title"] in ("Wingers Alehouse", "Menchie’s", "Toastique") for l in texas["listings"])
    assert texas["total"] == 801 and texas["is_total_capped"] is False


def test_search_card_shape(bakery):
    card = bakery["listings"][0]
    assert card["id"] == 2525392
    assert card["link"].endswith("/2525392/")
    assert card["listing_type"] == "established"
    assert card["pricing"]["asking_price"] == 4775000
    assert card["pricing"]["currency"] == "USD"
    assert card["pricing"]["is_real_estate_included"] is True
    assert card["badges"]["is_sba_eligible"] is True
    assert card["contact"]["name"] == "Scott Hislop"
    assert card["contact"]["phone"] == "(888) 290-5232"
    assert card["contact"]["is_broker"] is True
    assert card["contact"]["profile_link"].startswith("https://www.bizbuysell.com/business-broker/")
    assert card["location"] == {"name": "Illinois", "place": "Illinois", "state": "IL"}
    assert card["photos"] and card["photos"][0].startswith("https://images.bizbuysell.com/")
    assert bakery["total"] == 950


def test_search_cards_never_carry_empty_strings(texas):
    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        else:
            assert value != "", "empty string leaked"
    walk(texas["listings"])


def test_search_auction_row(texas):
    auctions = [l for l in texas["listings"] if l["auction"]]
    assert auctions and auctions[0]["listing_type"] == "auction"
    assert auctions[0]["auction"]["external_link"].startswith("https://www.ten-x.com/")
    assert auctions[0]["auction"]["starts_at"].startswith("2026-12-")   # ISO, not the site's 12/14/2026 12:00:00 PM


def test_search_no_match():
    parsed = P.parse_search(fixture("search_nomatch.json")["bbsBfsSearchResult"])
    assert parsed == {"total": 0, "is_total_capped": False, "listings": [], "heading": parsed["heading"],
                      "canonical_link": parsed["canonical_link"]}


def test_counts():
    counts = P.parse_counts(fixture("counts_bakery.json")["value"]["resultCounts"])
    assert counts["by_listing_type"]["established"] == 830
    assert set(counts["by_listing_type"]) == {"established", "asset_sale", "real_estate", "startup"}
    assert counts["total"] == sum(counts["by_listing_type"].values())


def test_contact_placeholder_profile_is_null():
    card = {"listNumber": 1, "contactInfo": {"contactFullName": "Robert Moran", "brokerCompany": "UFG",
                                             "brokerProfileUrl": "/business-broker/robert-moran/ufg/0/",
                                             "contactPhoneNumber": {"telephone": "", "tpnPhone": "5617820314"}}}
    contact = P.parse_listing_card(card)["contact"]
    assert contact["profile_link"] is None and contact["phone"] == "5617820314" and contact["is_broker"] is True
    assert P.parse_listing_card({"listNumber": 2, "contactInfo": None})["contact"] is None


# ---- listing page -----------------------------------------------------------------------

@pytest.fixture(scope="module")
def owner():
    return P.parse_listing_page(fixture("listing_owner_2567126_amp.html"), 2567126)


@pytest.fixture(scope="module")
def broker_listing():
    return P.parse_listing_page(fixture("listing_broker_2548034_amp.html"), 2548034)


@pytest.fixture(scope="module")
def franchise_resale():
    return P.parse_listing_page(fixture("listing_franchise_2504737_amp.html"), 2504737)


def test_owner_listing(owner):
    assert owner["id"] == 2567126
    assert owner["title"].startswith("LB Fuel Gas Station")
    assert owner["link"] == "https://www.bizbuysell.com/business-opportunity/lb-fuel-gas-station-and-food-mart-prime-long-beach-corner-location/2567126/"
    assert owner["listing_type"] == "established"
    assert owner["pricing"]["asking_price"] == 1200000
    assert owner["pricing"]["cash_flow"] is None            # "Not Disclosed"
    assert owner["contact"]["phone"] == "714-604-5175"
    assert owner["contact"]["is_broker"] is False
    assert owner["location"]["place"] == "Long Beach" and owner["location"]["state"] == "CA"
    assert owner["category"] == "Gas Stations > Convenience Stores"
    assert len(owner["photos"]) == 7 and all(p.startswith("https://images.bizbuysell.com/shared/listings/") for p in owner["photos"])
    assert "BUSINESS HIGHLIGHTS" in owner["description"] and "\n" in owner["description"]
    assert owner["facilities"].startswith("The business operates")
    assert len(owner["similar_listings"]) == 4 and owner["similar_listings"][0]["asking_price"] > 0
    assert owner["breadcrumbs"][1]["name"] == "California"


def test_broker_listing(broker_listing):
    assert broker_listing["pricing"]["cash_flow"] == 282000
    assert broker_listing["pricing"]["asking_price"] == 1300000
    assert broker_listing["pricing"]["gross_revenue"] is None
    assert broker_listing["established_year"] is None
    assert broker_listing["employees"] == "2 Full-time"
    assert broker_listing["reason_for_selling"] == "Retiring"
    assert broker_listing["location"]["county"] == "Contra Costa County"
    assert broker_listing["location"]["city"] is None
    assert broker_listing["pricing"]["financing"] is None     # "None" is a mask
    assert broker_listing["badges"]["is_premium"] is True


def test_franchise_resale_listing(franchise_resale):
    r = franchise_resale
    assert r["established_year"] == 2025
    assert r["pricing"]["gross_revenue"] == 99794
    assert r["pricing"]["financing"] == ["Seller financing available", "Franchisor can provide financing options"]
    assert r["pricing"]["has_seller_financing"] is True
    assert r["pricing"]["is_real_estate_included"] is False
    assert r["location"]["real_estate"] == "Leased" and r["location"]["building_sqft"] == 1000
    assert r["is_franchise"] is True and r["badges"]["is_franchise_resale"] is True
    assert r["support_and_training"].startswith("Comprehensive")
    assert r["contact"]["is_broker"] is True and r["contact"]["phone"] is None and r["contact"]["name"] is None


def test_listed_by_and_lease_rows():
    html = """<html><body><h1 class="bfsTitle">X</h1>
    <dl id="dlLocationInformation"><dt>Location:</dt><dd>San Jose, CA</dd><dt>Real Estate:</dt><dd>Leased</dd>
    <dt>Lease Expiration:</dt><dd>01/01/1970</dd></dl>
    <div><div><span class="f-14"> Business Listed By: </span><br> Kevin Wallace </div>
    <div class="f-xs contact-phone-selector"></div></div></body></html>"""
    r = P.parse_listing_page(html, 1)
    assert r["contact"]["name"] == "Kevin Wallace" and r["contact"]["profile_link"] is None
    assert r["location"]["lease_expires_on"] == "1970-01-01"
    assert r["location"]["real_estate"] == "Leased"
    assert r["photos"] == [] and r["pricing"]["asking_price"] is None and r["title"] == "X"


def test_brokered_listing_contact_card():
    r = P.parse_listing_page(fixture("listing_brokered_2525392_amp.html"), 2525392)
    photo = r["contact"].pop("photo")
    assert photo.startswith("https://images.bizbuysell.com/shared/brokerdirectory/images/27404/") and photo.endswith("TRANSWORLD-LOGO-2021-Icon-VF-01.png")
    assert r["contact"] == {
        "name": "Scott Hislop",
        "company": "Transworld Business Advisors NorthStar",
        "profile_link": "https://www.bizbuysell.com/business-broker/transworld-business-advisors/transworld-business-advisors-northstar/20493/",
        "phone": "866-971-4178",
        "is_broker": True,
    }
    assert r["pricing"]["gross_revenue"] == 685262 and r["established_year"] == 2001
    assert r["employees"].startswith("7 (")


def test_not_found_page_is_detectable():
    html = fixture("listing_notfound.html")
    assert "File Not Found" in html
    assert "bfsTitle" not in html


# ---- brokers ----------------------------------------------------------------------------

def test_brokers_page():
    parsed = P.parse_brokers(fixture("brokers_texas.json")["value"])
    assert parsed["total"] == 693 and len(parsed["brokers"]) == 5
    b = parsed["brokers"][0]
    assert b["id"] and b["name"] and b["link"].startswith("https://www.bizbuysell.com/business-broker/")
    assert b["location"]["state"] == "TX"
    assert "introduction" not in b            # the card subset
    assert isinstance(b["stats"]["active_listings"], int)


def test_broker_profile():
    row = fixture("brokers_account_21978.json")["value"]["brokerSearchResult"]["value"][0]
    b = P.parse_broker(row, full=True)
    assert b["id"] == 15309 and b["name"] == "Prabhjot Randhawa"
    assert b["company"] == "Liberty Business Advisors of S. F Inc"
    assert b["contact"]["phone"] == "+12098153842" and b["contact"]["license_number"] == "01355674"
    assert b["introduction"].startswith("I'm a Business Broker")
    assert b["company_overview"] is None and b["company_website"] is None
    assert b["areas_served"][0]["state"] == "CA" and b["areas_served"][0]["county_id"] == 186
    assert b["photo"] == "https://images.bizbuysell.com/shared/brokerdirectory/images/21978/pic1.jpg"
    assert b["nda_document"].endswith(".pdf")
    assert b["languages"] == ["English"]
    assert b["stats"]["sold_listings"] == 5 and b["account_id"] == 21978


def test_brokers_no_match():
    parsed = P.parse_brokers(fixture("brokers_nomatch.json")["value"])
    assert parsed["total"] == 0 and parsed["brokers"] == []


def test_typeahead():
    rows = P.parse_typeahead(fixture("brokers_typeahead_randhawa.json")["value"])
    match = [r for r in rows if r["id"] == 15309]
    assert match and match[0]["account_id"] == 21978 and match[0]["name"] == "Prabhjot Randhawa"


# ---- franchises -------------------------------------------------------------------------

def test_franchises_page():
    parsed = P.parse_franchises(fixture("franchises_search_ca_retail.json")["value"]["franchiseSearchResult"])
    assert parsed["total"] == 56 and len(parsed["franchises"]) == 5
    f = parsed["franchises"][0]
    assert f["slug"] == "woof-gang-bakery-and-grooming"
    assert f["link"] == "https://www.bizbuysell.com/franchise-for-sale/woof-gang-bakery-and-grooming/"
    assert f["pricing"]["cash_required"] == 100000 and f["pricing"]["average_unit_revenue"] == 620375
    assert {"id": 10, "name": "Retail Franchises", "slug": "retail-franchise"} in f["categories"]
    assert f["availability"] == "Available in California"
    assert f["logo"] and f["photos"]


def test_franchises_past_the_end():
    parsed = P.parse_franchises(fixture("franchises_search_pastend.json")["value"]["franchiseSearchResult"])
    assert parsed["franchises"] == [] and parsed["total"] == 35


def test_franchise_detail():
    d = P.parse_franchise_detail(fixture("franchise_lawn_doctor.json")["value"])
    assert d["slug"] == "lawn-doctor-home-services-franchise" and d["name"] == "Lawn Doctor"
    assert d["investment"]["franchise_fee"] == 45000 and d["investment"]["cash_required"] == 60000
    assert d["investment"]["total_investment_min"] == 133000 and d["investment"]["total_investment_max"] == 149000
    assert d["investment"]["fees"]["royalty_fee"]["percent"] == "2.0% - 5.0%"
    assert d["investment"]["fees"]["franchise_fee"]["amount"] == 50000
    assert d["investment"]["financial_assistance"] == "available" and d["investment"]["is_training_provided"] is True
    assert d["units"]["total"] == 675 and d["units"]["by_year"][-1] == {"year": 2025, "franchised": 672, "company_owned": 3}
    assert d["average_unit_revenue"] == 1170356 and d["franchising_since"] == 1967
    assert d["headquarters"] == "Holmdel, NJ" and d["ceo"] == "Scott Frith"
    assert d["sections"]["about"].startswith("Lawn Doctor was founded in 1967")
    assert d["sections"]["why_this_franchise"].startswith("The Top Reasons")
    assert "- #1 Lawn Care Franchise in U.S." in d["sections"]["why_this_franchise"]
    assert "TX" in d["available_states"] and d["is_available_in_canada"] is False
    assert d["images"][0].startswith("https://www.bizbuysell.com/fnw/images/")
    assert d["categories"][0]["name"] == "Home Services"


def test_franchise_not_found_answer():
    payload = fixture("franchise_notfound.json")
    assert payload["status"] == 4 and payload["value"] is None


# ---- reference lists --------------------------------------------------------------------

def test_categories_tree():
    tree = P.parse_categories(fixture("categories.json")["value"])
    assert len(tree) == 19                       # the hidden CLASSIFIEDS group is dropped
    assert not any(t["name"] == "CLASSIFIEDS" for t in tree)
    food = next(t for t in tree if t["name"] == "Restaurants & Food")
    assert food["id"] == 17 and food["slug"] == "restaurants-and-food-businesses"
    assert any(s["name"] == "American Restaurants" and s["id"] == 214 for s in food["subcategories"])
    assert all("_cid" not in t for t in tree)


def test_counties_index():
    index = P.parse_counties(fixture("counties_sample.json")["value"])
    row = index[P.county_key("CA", "Los Angeles County")]
    assert P.county_key("ca", "los-angeles") == "CA|los angeles"
    assert all(isinstance(k, str) for k in index)       # JSON-cacheable keys
    assert row["countyId"] == 186
    loc = refs.county_location(row)
    assert loc["geoType"] == 40 and loc["countyId"] == 186 and loc["stateCode"] == "CA"
