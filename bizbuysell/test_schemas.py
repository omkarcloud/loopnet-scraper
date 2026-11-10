"""Offline tests for the /bizbuysell/* request schemas.

    python -m pytest bizbuysell/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bizbuysell import schemas  # noqa: E402


def _errors(schema, data):
    with pytest.raises(ValidationError) as exc:
        schema().load(data)
    return exc.value.normalized_messages()


# ---- companies/search ----------------------------------------------------------------

def test_search_defaults():
    loaded = schemas.CompaniesSearchSchema().load({})
    assert loaded["page"] == 1 and loaded["per_page"] == 50 and loaded["sort"] == "relevance"
    assert loaded["query"] is None and loaded["state"] is None and loaded["category"] is None


def test_search_accepts_every_filter():
    loaded = schemas.CompaniesSearchSchema().load({
        "query": " coffee shop ", "state": "tx, Florida", "category": "Restaurants & Food", "listing_type": "Established",
        "min_price": "100000", "max_price": "500000", "min_cash_flow": "50000", "listed_within_days": "7",
        "established_after": "2015", "seller_financing": "true", "home_based": "0", "sort": "price_desc",
        "page": "2", "per_page": "100"})
    assert loaded["query"] == "coffee shop"
    assert loaded["state"] == ["TX", "FL"]
    assert loaded["category"] == 17
    assert loaded["listing_type"] == "established"
    assert loaded["min_price"] == 100000 and loaded["max_price"] == 500000
    assert loaded["seller_financing"] is True and loaded["home_based"] is False
    assert loaded["sort"] == "price_desc" and loaded["page"] == 2 and loaded["per_page"] == 100


def test_search_empty_query_is_none_not_500():
    assert schemas.CompaniesSearchSchema().load({"query": ""})["query"] is None
    assert schemas.CompaniesSearchSchema().load({"county": " "})["county"] is None


def test_search_county_needs_one_state():
    errors = _errors(schemas.CompaniesSearchSchema, {"county": "Los Angeles"})
    assert "county" in errors
    errors = _errors(schemas.CompaniesSearchSchema, {"county": "Los Angeles", "state": "CA,TX"})
    assert "county" in errors
    loaded = schemas.CompaniesSearchSchema().load({"county": "Los Angeles County", "state": "California"})
    assert loaded["county"] == "Los Angeles County" and loaded["state"] == ["CA"]


@pytest.mark.parametrize("data,field", [
    ({"state": "Mars"}, "state"),
    ({"category": "spaceships"}, "category"),
    ({"listing_type": "franchise"}, "listing_type"),
    ({"sort": "oldest"}, "sort"),
    ({"min_price": "0"}, "min_price"),
    ({"min_price": "500", "max_price": "100"}, "min_price"),
    ({"per_page": "201"}, "per_page"),
    ({"page": "201", "per_page": "100"}, "page"),
    ({"seller_financing": "maybe"}, "seller_financing"),
    ({"url": "x"}, "url"),
])
def test_search_rejects(data, field):
    assert field in _errors(schemas.CompaniesSearchSchema, data)


def test_search_rejection_message_is_readable():
    errors = _errors(schemas.CompaniesSearchSchema, {"state": "Mars"})
    assert "Mars" in errors["state"][0] and "TX" in errors["state"][0]
    errors = _errors(schemas.CompaniesSearchSchema, {"category": "spaceships"})
    assert "/bizbuysell/categories/list" in errors["category"][0]


def test_counts_schema_has_no_paging():
    loaded = schemas.CompaniesCountsSchema().load({"query": "bakery", "state": "TX"})
    assert loaded["query"] == "bakery" and "page" not in loaded and "sort" not in loaded
    assert "page" in _errors(schemas.CompaniesCountsSchema, {"page": "2"})


# ---- companies/details ------------------------------------------------------------------

def test_company_schema_accepts_id_and_link():
    assert schemas.CompanySchema().load({"company": "2548034"}) == {"company": {"id": 2548034, "slug": None}}
    loaded = schemas.CompanySchema().load(
        {"company": "https://www.bizbuysell.com/business-opportunity/lb-fuel-gas-station/2567126/"})
    assert loaded == {"company": {"id": 2567126, "slug": "lb-fuel-gas-station"}}


@pytest.mark.parametrize("value", ["", "abc", "https://example.com/business-opportunity/x/2548034/"])
def test_company_schema_rejects(value):
    assert "company" in _errors(schemas.CompanySchema, {"company": value})


def test_company_schema_rejects_sibling_params():
    errors = _errors(schemas.CompanySchema, {"company": "2548034", "id": "2548034"})
    assert "id" in errors
    errors = _errors(schemas.CompanySchema, {"company": "2548034", "url": "x"})
    assert "url" in errors


# ---- brokers ----------------------------------------------------------------------------

def test_brokers_search_schema():
    loaded = schemas.BrokersSearchSchema().load({"query": "transworld", "state": "california", "per_page": "100"})
    assert loaded == {"query": "transworld", "state": ["CA"], "county": None, "page": 1, "per_page": 100}
    assert "per_page" in _errors(schemas.BrokersSearchSchema, {"per_page": "101"})
    assert "county" in _errors(schemas.BrokersSearchSchema, {"county": "Los Angeles"})


def test_broker_schema():
    assert schemas.BrokerSchema().load({"broker": "15309"}) == {"broker": {"id": 15309, "name": None, "company": None}}
    loaded = schemas.BrokerSchema().load(
        {"broker": "https://www.bizbuysell.com/business-broker/Prabhjot-Randhawa/liberty-business-advisors-of-s-f-inc/15309/"})
    assert loaded["broker"] == {"id": 15309, "name": "prabhjot-randhawa", "company": "liberty-business-advisors-of-s-f-inc"}
    assert "broker" in _errors(schemas.BrokerSchema, {"broker": "randhawa"})
    assert "broker" in _errors(schemas.BrokerSchema, {})


# ---- franchises -------------------------------------------------------------------------

def test_franchises_search_schema():
    loaded = schemas.FranchisesSearchSchema().load({"category": "Retail Franchises", "state": "CA", "max_investment": "100000"})
    assert loaded["category"] == 10 and loaded["state"] == ["CA"] and loaded["max_investment"] == 100000
    assert loaded["page"] == 1 and loaded["per_page"] == 50
    assert schemas.FranchisesSearchSchema().load({"category": "home-services-franchise"})["category"] == 9
    assert schemas.FranchisesSearchSchema().load({"category": "7"})["category"] == 7
    assert "category" in _errors(schemas.FranchisesSearchSchema, {"category": "spaceships"})
    assert "min_investment" in _errors(schemas.FranchisesSearchSchema, {"min_investment": "9", "max_investment": "1"})
    assert "per_page" in _errors(schemas.FranchisesSearchSchema, {"per_page": "201"})


def test_franchise_schema():
    assert schemas.FranchiseSchema().load({"franchise": "lawn-doctor-home-services-franchise"}) == \
        {"franchise": "lawn-doctor-home-services-franchise"}
    assert schemas.FranchiseSchema().load(
        {"franchise": "https://www.bizbuysell.com/franchise-for-sale/lawn-doctor-home-services-franchise/"}) == \
        {"franchise": "lawn-doctor-home-services-franchise"}
    assert "franchise" in _errors(schemas.FranchiseSchema, {"franchise": "https://example.com/franchise-for-sale/x/"})
    assert "franchise" in _errors(schemas.FranchiseSchema, {})


def test_categories_schema_rejects_params():
    assert schemas.CategoriesSchema().load({}) == {}
    assert "page" in _errors(schemas.CategoriesSchema, {"page": "1"})
