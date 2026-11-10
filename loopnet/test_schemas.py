"""Offline tests for the /loopnet/* request schemas.

    python -m pytest loopnet/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loopnet import refs, schemas  # noqa: E402


def _error(cls, data):
    with pytest.raises(ValidationError) as info:
        cls().load(data)
    return info.value.messages


# ---- listings/search ------------------------------------------------------------------

def test_search_defaults():
    loaded = schemas.ListingsSearchSchema().load({"query": "  Austin,  TX "})
    assert loaded["query"] == "Austin, TX"
    assert loaded["listing_type"] == "sale" and loaded["property_type"] == "all"
    assert loaded["sort"] == "default" and loaded["page"] == 1
    assert loaded["min_price"] is None and loaded["keyword"] is None


def test_search_accepts_link_and_filters():
    link = "https://www.loopnet.com/search/office-space/los-angeles-ca/for-lease/2/?min-rent=20"
    assert schemas.ListingsSearchSchema().load({"query": link})["query"] == link
    loaded = schemas.ListingsSearchSchema().load({
        "query": "Los Angeles, CA", "listing_type": "LEASE", "property_type": "Office", "sort": "newest",
        "price_per_sf": "yes", "min_rent": "20", "max_rent": "40.5", "min_size": "1000", "max_size": "5000",
        "min_cap_rate": "6", "max_cap_rate": "9", "min_year_built": "2000", "keyword": " creative ", "page": "19"})
    assert loaded["listing_type"] == "lease" and loaded["property_type"] == "office"
    assert loaded["price_per_sf"] is True and loaded["max_rent"] == 40.5 and loaded["min_size"] == 1000
    assert loaded["keyword"] == "creative" and loaded["page"] == 19


@pytest.mark.parametrize("data,field", [
    ({}, "query"),
    ({"query": ""}, "query"),
    ({"query": "34.04,-118.44"}, "query"),        # no reverse geocoding on the site: a point is not a place
    ({"query": "Austin", "listing_type": "rent"}, "listing_type"),
    ({"query": "Austin", "property_type": "castle"}, "property_type"),
    ({"query": "Austin", "page": "20"}, "page"),
    ({"query": "Austin", "page": "0"}, "page"),
    ({"query": "Austin", "min_price": "10", "max_price": "5"}, "max_price"),
    ({"query": "Austin", "min_size": "5000", "max_size": "10"}, "max_size"),
    ({"query": "Austin", "min_cap_rate": "-1"}, "min_cap_rate"),
    ({"query": "Austin", "sort": "price"}, "sort"),
    ({"query": "Austin", "url": "x"}, "url"),
    ({"query": "Austin", "min_year_built": "3000"}, "min_year_built"),
])
def test_search_rejects(data, field):
    assert field in _error(schemas.ListingsSearchSchema, data)


def test_search_property_types_cover_the_site_slugs():
    assert set(refs.PROPERTY_TYPES.values()) >= {"commercial-real-estate", "office-space", "retail-space",
                                                 "industrial-properties", "land", "multifamily-properties",
                                                 "hospitality-properties", "specialty-properties", "restaurants",
                                                 "shopping-centers", "flex-space", "medical-offices", "warehouses",
                                                 "self-storage-facilities", "health-care-facilities", "auto-shops"}


# ---- id / link params --------------------------------------------------------------------

def test_listing_schema():
    assert schemas.ListingSchema().load({"listing": "29122043"}) == {"listing": {"id": 29122043, "slug": None}}
    loaded = schemas.ListingSchema().load({"listing": "https://www.loopnet.com/Listing/11340-W-Olympic-Blvd-Los-Angeles-CA/29122043/"})
    assert loaded == {"listing": {"id": 29122043, "slug": "11340-W-Olympic-Blvd-Los-Angeles-CA"}}
    messages = _error(schemas.ListingSchema, {"listing": "https://example.com/Listing/x/29122043/"})
    assert messages == {"listing": ["Must be a loopnet.com link."]}
    assert "listing id" in _error(schemas.ListingSchema, {"listing": "abc"})["listing"][0]
    assert "listing" in _error(schemas.ListingSchema, {})
    assert "id" in _error(schemas.ListingSchema, {"listing": "29122043", "id": "29122043"})


def test_broker_company_property_business_schemas():
    assert schemas.BrokerSchema().load({"broker": "8lybyl0b"}) == {"broker": {"id": "8lybyl0b", "slug": None}}
    assert schemas.BrokerSchema().load({"broker": "https://www.loopnet.com/commercial-real-estate-brokers/profile/keith-fielding/8lybyl0b/29122043"}) == \
        {"broker": {"id": "8lybyl0b", "slug": "keith-fielding"}}
    assert "broker" in _error(schemas.BrokerSchema, {"broker": "https://www.loopnet.com/company/x/0r9nt33l/"})
    assert schemas.CompanySchema().load({"company": "https://www.loopnet.com/company/lee-associates-west-la/0r9nt33l/"}) == \
        {"company": {"id": "0r9nt33l", "slug": "lee-associates-west-la"}, "page": 1}
    assert schemas.CompanySchema().load({"company": "0r9nt33l", "page": "3"})["page"] == 3
    assert "page" in _error(schemas.CompanySchema, {"company": "0r9nt33l", "page": "0"})
    assert schemas.PropertySchema().load({"property": "20209-054121"}) == {"property": {"id": "20209-054121", "slug": None}}
    assert "fips" in _error(schemas.PropertySchema, {"property": "hello"})["property"][0]
    assert schemas.BusinessSchema().load({"business": "2573303"}) == {"business": {"id": 2573303, "slug": None}}
    assert schemas.BusinessSchema().load({"business": "https://www.loopnet.com/biz/business-opportunity/turnkey-charcuterie-business/2573303/"}) == \
        {"business": {"id": 2573303, "slug": "turnkey-charcuterie-business"}}
    assert "/biz/" in _error(schemas.BusinessSchema, {"business": "x"})["business"][0]


# ---- other routes ---------------------------------------------------------------------------

def test_autocomplete_schema():
    assert schemas.LocationsAutocompleteSchema().load({"query": "Austin"}) == {"query": "Austin"}
    assert "query" in _error(schemas.LocationsAutocompleteSchema, {"query": ""})


def test_brokers_search_schema():
    loaded = schemas.BrokersSearchSchema().load({"location": "Austin, TX"})
    assert loaded["location"] == {"state": "TX", "city": "austin"} and loaded["page"] == 1 and loaded["sort"] == "default"
    loaded = schemas.BrokersSearchSchema().load({"location": "texas", "sort": "Name_Asc", "page": "3"})
    assert loaded["location"] == {"state": "TX", "city": None} and loaded["sort"] == "name_asc" and loaded["page"] == 3
    loaded = schemas.BrokersSearchSchema().load({"name": "Keith Fielding", "broker_type": "tenant_rep"})
    assert loaded["location"] is None and loaded["name"] == "Keith Fielding" and loaded["broker_type"] == "tenant_rep"
    assert schemas.BrokersSearchSchema().load({"company": "Lee & Associates"})["company"] == "Lee & Associates"
    assert "location" in _error(schemas.BrokersSearchSchema, {})
    assert "US state" in _error(schemas.BrokersSearchSchema, {"location": "Paris, FR"})["location"][0]
    assert "broker_type" in _error(schemas.BrokersSearchSchema, {"name": "x", "broker_type": "buyer"})


def test_traffic_schema():
    assert schemas.TrafficCountsSchema().load({"location": "34.037432, -118.441654"}) == \
        {"location": {"latitude": 34.037432, "longitude": -118.441654}}
    assert "latitude,longitude" in _error(schemas.TrafficCountsSchema, {"location": "Austin"})["location"][0]
    assert "location" in _error(schemas.TrafficCountsSchema, {"location": "95,10"})
    assert "location" in _error(schemas.TrafficCountsSchema, {})


def test_businesses_search_schema():
    loaded = schemas.BusinessesSearchSchema().load({"state": "TX,Florida", "category": "Restaurants & Food",
                                                   "sort": "newest", "min_price": "100000", "page": "2"})
    assert loaded["state"] == ["TX", "FL"] and isinstance(loaded["category"], int)
    assert loaded["sort"] == "newest" and loaded["min_price"] == 100000 and loaded["page"] == 2
    assert schemas.BusinessesSearchSchema().load({})["sort"] == "relevance"
    assert "state" in _error(schemas.BusinessesSearchSchema, {"state": "Mars"})
    assert "max_price" in _error(schemas.BusinessesSearchSchema, {"min_price": "10", "max_price": "5"})
    assert "sort" in _error(schemas.BusinessesSearchSchema, {"sort": "random"})
