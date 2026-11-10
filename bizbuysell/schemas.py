"""Marshmallow request schemas for every /bizbuysell/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    company    a listing id (2548034) OR any bizbuysell.com listing link
    broker     a broker profile id OR a broker profile link
    franchise  a franchise slug OR a franchise link
    state      US state / Canadian province names or codes, comma-separated
    category   a category name / slug / id (bizbuysell/refs.py CATEGORIES;
               sub-category ids from /bizbuysell/categories/list)

Every field carries a `description` because it becomes the public docs.
"""
from marshmallow import ValidationError, validates_schema

from schema_fields import (BaseSchema, ChoiceField, CommaListField, Flag, PageField, PageSizeField,
                           PositiveInt, RefField, StrippedString)
from bizbuysell import refs

MAX_SEARCH_PAGE_SIZE = 200     # the site serves up to 500 per call; 200 keeps a page under ~1 MB
MAX_BROKER_PAGE_SIZE = 100     # the directory's own ceiling
MAX_FRANCHISE_PAGE_SIZE = 200  # the franchise search's own ceiling


def _max_length(n):
    """validate.Length(max=n) that tolerates the None StrippedString returns
    for an empty value (marshmallow runs validators on it; len(None) is a 500)."""
    def check(value):
        if value is not None and len(value) > n:
            raise ValidationError(f"Longer than maximum length {n}.")
    return check


def _optional_query(description, n=200):
    return StrippedString(required=False, load_default=None, validate=_max_length(n),
                          metadata={"description": description})


class ListingRefField(RefField):
    resolver = staticmethod(refs.resolve_listing)


class BrokerRefField(RefField):
    resolver = staticmethod(refs.resolve_broker)


class FranchiseRefField(RefField):
    resolver = staticmethod(refs.resolve_franchise)


class StateListField(CommaListField):
    """Comma-separated state / province names or codes -> ["TX", "FL"]."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_items", 10)
        super().__init__(upper=False, **kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        items = super()._deserialize(value, attr, data, **kwargs)
        if not items:
            return None
        codes = []
        for item in items:
            try:
                code = refs.resolve_state(item)
            except ValueError as e:
                raise ValidationError(str(e))
            if code not in codes:
                codes.append(code)
        return codes


class CategoryField(StrippedString):
    resolver = staticmethod(refs.resolve_category)

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        try:
            return type(self).resolver(value)
        except ValueError as e:
            raise ValidationError(str(e))


class FranchiseCategoryField(CategoryField):
    resolver = staticmethod(refs.resolve_franchise_category)


class Money(PositiveInt):
    """Whole US dollars (an upper bound of 0 means "no bound" upstream, so 1 is the floor)."""


def _state_desc(noun):
    return (f"{noun} by US state or Canadian province: names or codes, comma-separated "
            "(e.g. TX,Florida; up to 10)")


class CompaniesSearchSchema(BaseSchema):
    query = _optional_query("keywords matched against listing titles and full descriptions (e.g. coffee shop, HVAC)")
    state = StateListField(metadata={"description": _state_desc("limit listings")})
    county = _optional_query("a county name inside the single `state` given (e.g. Los Angeles or Los Angeles County)", 80)
    category = CategoryField(metadata={
        "description": "industry: a name or slug from the 20 top-level categories (Restaurants & Food, "
                       "service-businesses, ...) or any category id from /bizbuysell/categories/list"})
    listing_type = ChoiceField(list(refs.LISTING_TYPES), metadata={
        "description": "established (operating businesses), asset_sale, real_estate (business real estate), "
                       "startup (new franchise / startup opportunities); default all"})
    min_price = Money(metadata={"description": "minimum asking price in USD"})
    max_price = Money(metadata={"description": "maximum asking price in USD"})
    min_cash_flow = Money(metadata={"description": "minimum annual cash flow (seller's discretionary earnings) in USD"})
    max_cash_flow = Money(metadata={"description": "maximum annual cash flow in USD"})
    min_revenue = Money(metadata={"description": "minimum annual gross revenue in USD"})
    max_revenue = Money(metadata={"description": "maximum annual gross revenue in USD"})
    listed_within_days = PositiveInt(max_value=3650, metadata={
        "description": "only listings first published within the last N days (e.g. 7 for a weekly feed)"})
    updated_within_days = PositiveInt(max_value=3650, metadata={
        "description": "only listings published or changed within the last N days"})
    established_after = PositiveInt(max_value=2100, metadata={
        "description": "only businesses established after this year (e.g. 2015)"})
    seller_financing = Flag(metadata={"description": "true = only listings where the seller offers financing"})
    home_based = Flag(metadata={"description": "true = only home-based businesses"})
    absentee_owner = Flag(metadata={"description": "true = only businesses run without the owner on site"})
    price_reduced = Flag(metadata={"description": "true = only listings whose asking price was recently reduced"})
    sba_eligible = Flag(metadata={"description": "true = only listings carrying BizBuySell's SBA Loan Eligible badge"})
    real_estate_included = Flag(metadata={"description": "true = only listings whose asking price includes the real estate"})
    include_relocatable = Flag(metadata={
        "description": "true = when searching a state, also include businesses elsewhere that can be relocated there"})
    sort = ChoiceField(list(refs.SORTS), load_default="relevance", metadata={
        "description": "relevance (the site's order), newest, price_asc, price_desc, cash_flow_desc, cash_flow_asc"})
    page = PageField(max_page=refs.MAX_RESULTS, metadata={"description": "1-based page"})
    per_page = PageSizeField(default=50, max_size=MAX_SEARCH_PAGE_SIZE, metadata={
        "description": f"listings per page (default 50, max {MAX_SEARCH_PAGE_SIZE}); the site stops at 10,000 results per search"})

    @validates_schema
    def _county_needs_one_state(self, data, **kwargs):
        if data.get("county") and len(data.get("state") or []) != 1:
            raise ValidationError("county needs exactly one state (e.g. state=CA&county=Los Angeles).", "county")
        page, per_page = data.get("page") or 1, data.get("per_page") or 50
        if (page - 1) * per_page >= refs.MAX_RESULTS:
            raise ValidationError(f"page x per_page cannot pass the site's {refs.MAX_RESULTS}-result ceiling.", "page")
        for low, high in (("min_price", "max_price"), ("min_cash_flow", "max_cash_flow"), ("min_revenue", "max_revenue")):
            if data.get(low) is not None and data.get(high) is not None and data[low] > data[high]:
                raise ValidationError(f"{low} must not exceed {high}.", low)


class CompaniesCountsSchema(CompaniesSearchSchema):
    class Meta(BaseSchema.Meta):
        exclude = ("sort", "page", "per_page")


class CompanySchema(BaseSchema):
    company = ListingRefField(metadata={
        "description": "listing id (e.g. 2548034) or a bizbuysell.com listing link"})


class BrokersSearchSchema(BaseSchema):
    query = _optional_query("broker or brokerage name words (e.g. transworld, randhawa)")
    state = StateListField(metadata={"description": _state_desc("limit brokers")})
    county = _optional_query("a county name inside the single `state` given", 80)
    page = PageField(max_page=1000, metadata={"description": "1-based page"})
    per_page = PageSizeField(default=30, max_size=MAX_BROKER_PAGE_SIZE, metadata={
        "description": f"brokers per page (default 30, max {MAX_BROKER_PAGE_SIZE})"})

    @validates_schema
    def _county_needs_one_state(self, data, **kwargs):
        if data.get("county") and len(data.get("state") or []) != 1:
            raise ValidationError("county needs exactly one state (e.g. state=CA&county=Los Angeles).", "county")


class BrokerSchema(BaseSchema):
    broker = BrokerRefField(metadata={
        "description": "broker profile link (https://www.bizbuysell.com/business-broker/<name>/<company>/<id>/) "
                       "or the profile id; a bare id is resolved through the site's name lookup, so the link is the sure form"})


class FranchisesSearchSchema(BaseSchema):
    category = FranchiseCategoryField(metadata={
        "description": "franchise category name, slug or id (Restaurant & Food, home-services-franchise, 10, ...; "
                       "see /bizbuysell/categories/list)"})
    state = StateListField(metadata={"description": _state_desc("limit franchises available")})
    min_investment = Money(metadata={"description": "minimum total investment in USD"})
    max_investment = Money(metadata={"description": "maximum total investment in USD"})
    page = PageField(max_page=1000, metadata={"description": "1-based page"})
    per_page = PageSizeField(default=50, max_size=MAX_FRANCHISE_PAGE_SIZE, metadata={
        "description": f"franchises per page (default 50, max {MAX_FRANCHISE_PAGE_SIZE})"})

    @validates_schema
    def _bounds(self, data, **kwargs):
        low, high = data.get("min_investment"), data.get("max_investment")
        if low is not None and high is not None and low > high:
            raise ValidationError("min_investment must not exceed max_investment.", "min_investment")


class FranchiseSchema(BaseSchema):
    franchise = FranchiseRefField(metadata={
        "description": "franchise slug (e.g. lawn-doctor-home-services-franchise) or a bizbuysell.com franchise link"})


class CategoriesSchema(BaseSchema):
    """No parameters."""
