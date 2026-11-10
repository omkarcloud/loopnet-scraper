"""Marshmallow request schemas for every /loopnet/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair; loopnet/refs.py resolves each):

    listing    a listing id (29122043) OR any loopnet.com listing link
    broker     a broker profile id (8lybyl0b) OR a profile link
    company    a company id (0r9nt33l) OR a /company/ link
    property   a property-record link OR its <fips>-<parcel> id (20209-054121)
    business   a BizBuySell listing number OR a loopnet.com /biz/ listing link
    query      (listings/search) a place as typed in the site's search box
               (city "Austin, TX", state "Texas", ZIP "90064", county
               "Los Angeles County, CA"), a "lat,lng" pair, OR a pasted
               loopnet.com search link (its path and filters are reused)
    location   (brokers/search) a US state, a "City, ST" pair or a
               directory link
"""
from marshmallow import ValidationError, missing, validates_schema

from schema_fields import (BaseSchema, ChoiceField, Flag, NonNegativeNumber, PageField, PositiveInt, QueryField,
                           RefField, StrippedString)
from bizbuysell import refs as biz_refs
from bizbuysell.schemas import CategoryField, StateListField
from loopnet import refs


class ListingRefField(RefField):
    resolver = staticmethod(refs.resolve_listing)


class BrokerRefField(RefField):
    resolver = staticmethod(refs.resolve_broker)


class CompanyRefField(RefField):
    resolver = staticmethod(refs.resolve_company)


class PropertyRefField(RefField):
    resolver = staticmethod(refs.resolve_property)


class BusinessRefField(RefField):
    resolver = staticmethod(refs.resolve_business)


class BrokerLocationField(RefField):
    resolver = staticmethod(refs.resolve_broker_location)


class LatLngField(StrippedString):
    """"34.0374,-118.4417" -> {"latitude", "longitude"}."""

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        pair = refs.parse_lat_lng(value)
        if pair is None:
            raise ValidationError("Must be a latitude,longitude pair (e.g. 34.0374,-118.4417).")
        return {"latitude": pair[0], "longitude": pair[1]}


def _money(desc):
    return NonNegativeNumber(metadata={"description": desc})


class ListingsSearchSchema(BaseSchema):
    query = QueryField(max_length=300, metadata={
        "description": "where to search: a city (Austin, TX), state (Texas), ZIP (90064), county (Los Angeles "
                       "County, CA) or neighborhood as typed in the site's search box, a latitude,longitude pair, "
                       "or a pasted loopnet.com search link (its property type, listing type, page and filters are reused)"})
    listing_type = ChoiceField(list(refs.LISTING_TYPES), load_default="sale", metadata={
        "description": "sale (default), lease or auction"})
    property_type = ChoiceField(list(refs.PROPERTY_TYPES), load_default="all", metadata={
        "description": "all (default), office, retail, industrial, warehouse, flex, land, multifamily, apartment, "
                       "hospitality, hotel, specialty, restaurant, shopping-center, health-care, medical, "
                       "coworking, mixed-use, self-storage, data-center and the other site categories "
                       "(see the property type slugs on loopnet.com); a type the site does not offer for "
                       "the listing type answers 404"})
    min_price = _money("minimum price in USD (sale: asking price; lease: rate, see price_per_sf)")
    max_price = _money("maximum price in USD")
    price_per_sf = Flag(metadata={"description": "true: min_price / max_price are $ per SF per year (lease rates / sale price per SF)"})
    min_rent = _money("minimum lease rate in USD per SF per year (lease searches)")
    max_rent = _money("maximum lease rate in USD per SF per year (lease searches)")
    min_size = PositiveInt(metadata={"description": "minimum building / space size in SF"})
    max_size = PositiveInt(metadata={"description": "maximum building / space size in SF"})
    min_cap_rate = NonNegativeNumber(metadata={"description": "minimum cap rate in percent (sale searches)"})
    max_cap_rate = NonNegativeNumber(metadata={"description": "maximum cap rate in percent (sale searches)"})
    min_year_built = PositiveInt(max_value=2100, metadata={"description": "earliest year built"})
    keyword = StrippedString(load_default=None, metadata={"description": "words matched against the listings (warehouse, creative, drive-thru...)"})
    sort = ChoiceField(list(refs.SORTS), load_default="default", metadata={
        "description": "default (the site's relevance order) or newest"})
    page = PageField(max_page=refs.MAX_SEARCH_PAGE, metadata={
        "description": f"1-based page of 40 results; the site caps every search at {refs.MAX_RESULTS} results "
                       f"({refs.MAX_SEARCH_PAGE} pages)"})

    @validates_schema
    def _bounds(self, data, **kwargs):
        for low, high in (("min_price", "max_price"), ("min_rent", "max_rent"), ("min_size", "max_size"),
                          ("min_cap_rate", "max_cap_rate")):
            if data.get(low) is not None and data.get(high) is not None and data[low] > data[high]:
                raise ValidationError(f"{low} must not exceed {high}.", high)


class ListingSchema(BaseSchema):
    listing = ListingRefField(metadata={
        "description": "listing id (e.g. 29122043) or a loopnet.com listing link"})


class LocationsAutocompleteSchema(BaseSchema):
    query = QueryField(max_length=120, metadata={
        "description": "a place, address or property name as typed in the site's search box (Austin, 90064, "
                       "Los Angeles County, 11340 W Olympic Blvd)"})


class BrokersSearchSchema(BaseSchema):
    location = BrokerLocationField(required=False, load_default=None, metadata={
        "description": "a US state (TX, Texas), a 'City, ST' pair (Austin, TX) or a loopnet.com broker directory link; "
                       "with no name / company this browses the site's directory for the place"})
    name = StrippedString(load_default=None, metadata={"description": "broker first and/or last name (Keith Fielding)"})
    company = StrippedString(load_default=None, metadata={"description": "brokerage name words (Lee & Associates)"})
    broker_type = ChoiceField(list(refs.BROKER_TYPES), metadata={
        "description": "landlord_rep, tenant_rep or investment_sale (the site's broker search form filter)"})
    sort = ChoiceField(list(refs.BROKER_SORTS), load_default="default", metadata={
        "description": "default, name_asc or name_desc (directory browsing only)"})
    page = PageField(max_page=1000, metadata={"description": "1-based directory page of 10 brokers (directory browsing only)"})

    @validates_schema
    def _needs_something(self, data, **kwargs):
        if not (data.get("location") or data.get("name") or data.get("company")):
            raise ValidationError("Give a location (state or 'City, ST'), a name or a company.", "location")


class BrokerSchema(BaseSchema):
    broker = BrokerRefField(metadata={
        "description": "broker profile id (e.g. 8lybyl0b) or a loopnet.com broker profile link"})


class CompanySchema(BaseSchema):
    company = CompanyRefField(metadata={
        "description": "company id (e.g. 0r9nt33l) or a loopnet.com /company/ link"})
    page = PageField(max_page=200, metadata={"description": "1-based page of the company's listings (20 a page)"})


class PropertySchema(BaseSchema):
    property = PropertyRefField(metadata={
        "description": "property record link (https://www.loopnet.com/property/<address>/<fips>-<parcel>/) or "
                       "its <fips>-<parcel> id (e.g. 20209-054121)"})


class TrafficCountsSchema(BaseSchema):
    location = LatLngField(required=True, metadata={
        "description": "latitude,longitude of the point (e.g. 34.0374,-118.4417; a listing's coordinates)"})


class BusinessesSearchSchema(BaseSchema):
    """The Businesses-for-Sale vertical is BizBuySell's data (the /biz/ pages
    embed its BFF), so the fields are the bizbuysell scraper's own
    (bizbuysell/schemas.py), served by that module."""
    query = StrippedString(load_default=None, metadata={
        "description": "keywords matched against business listing titles and descriptions (coffee shop, HVAC)"})
    state = StateListField(metadata={
        "description": "US state (or Canadian province) names or codes, comma-separated (TX,Florida; up to 10)"})
    category = CategoryField(metadata={
        "description": "industry: a BizBuySell category name, slug or id (Restaurants & Food, service-businesses, 28)"})
    min_price = _money("minimum asking price in USD")
    max_price = _money("maximum asking price in USD")
    min_cash_flow = _money("minimum annual cash flow (seller's discretionary earnings) in USD")
    max_cash_flow = _money("maximum annual cash flow in USD")
    sort = ChoiceField(list(biz_refs.SORTS), load_default="relevance", metadata={
        "description": "relevance (default), newest, price_asc, price_desc, cash_flow_asc, cash_flow_desc"})
    page = PageField(max_page=200, metadata={"description": "1-based page of 50 businesses"})

    @validates_schema
    def _bounds(self, data, **kwargs):
        for low, high in (("min_price", "max_price"), ("min_cash_flow", "max_cash_flow")):
            if data.get(low) is not None and data.get(high) is not None and data[low] > data[high]:
                raise ValidationError(f"{low} must not exceed {high}.", high)


class BusinessSchema(BaseSchema):
    business = BusinessRefField(metadata={
        "description": "business listing number (e.g. 2573303) or a loopnet.com /biz/ listing link"})
