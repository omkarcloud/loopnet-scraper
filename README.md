# 🏢 LoopNet Scraper

LoopNet Scraper is a **free and open-source** scraper that gets you **unlimited** detailed LoopNet data for free.

## ✨ What Can I Get?

- 🏢 **Full details on 300K+ active listings** — price, cap rate, size, spaces, highlights, photos, brochures & brokers
- 🔍 **For-sale, for-lease & auction search across 38 property types** — any US city, ZIP or county, with 13 filters
- 🤝 **Brokers, brokerages & public property records** — broker phones & bios, brokerage listings, parcels, zoning & demographics
- 🚦 **Traffic counts & 10,000+ businesses for sale** — daily vehicles on nearby streets, plus asking price & cash flow

## 🎥 Example: A Full LoopNet Listing

```json
{
  "id": 43019700,
  "link": "https://www.loopnet.com/Listing/8925-W-Olympic-Blvd-Beverly-Hills-CA/43019700/",
  "name": "8925 W Olympic Blvd",
  "city": "Beverly Hills",
  "state": "CA",
  "postal_code": "90211",
  "listing_type": "sale",
  "headline": "Retail for Sale 4,959 SF",
  "price": { "text": "$10,495,000 ($2,116.35/SF)", "min": 10495000, "max": 10495000, "currency": "USD", "basis": null },
  "sale_type": "Investment or Owner User",
  "property_type": "Retail",
  "building_class": "C",
  "building_size": { "text": "4,959 SF", "min": 4959, "max": 4959, "unit": "sf" },
  "lot_size": { "text": "12,281.00 SF", "min": 12281, "max": 12281, "unit": "sf" },
  "year_built": 1965,
  "zoning": "C-3T-2 - C-3T-2 with Mixed-Use Overlay (MUOZ)",
  "highlights": ["Surrounded by high-income single-family neighborhoods, driving demand for medical, retail, and lifestyle services"],
  "brochure": { "name": "8925 W Olympic Blvd_OM", "link": "https://images.loopnet.co.uk/d2/sn0x5I_wu013TROsXGfmjsm441f3bjKPyr89RRfPbnI/document.pdf", "is_locked": false },
  "photos_count": 31,
  "commute_scores": { "walk": { "score": 80, "label": "Very walkable" }, "transit": { "score": 60, "label": "Good public transit" } },
  "brokers": [
    { "id": "ywdxjssb", "name": "Conor Halloran", "title": "Partner", "link": "https://www.loopnet.com/commercial-real-estate-brokers/profile/conor-halloran/ywdxjssb", "phone": "+13108992724" }
  ],
  "date_on_market": "2026-10-28"
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free LoopNet Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/loopnet-scraper
cd loopnet-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

The first call opens Google Chrome for about 20 seconds to earn LoopNet's access cookies, so have Chrome installed. Every call after that is plain HTTP.

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/listings/details?listing=43019700"
```

```json
{
  "id": 43019700,
  "link": "https://www.loopnet.com/Listing/8925-W-Olympic-Blvd-Beverly-Hills-CA/43019700/",
  "name": "8925 W Olympic Blvd",
  "city": "Beverly Hills",
  "state": "CA",
  "latitude": 34.059651,
  "longitude": -118.386538,
  "listing_type": "sale",
  "price": { "text": "$10,495,000 ($2,116.35/SF)", "min": 10495000, "max": 10495000, "currency": "USD", "basis": null },
  "price_per_sf": { "text": "$2,116.35", "min": 2116.35, "max": 2116.35, "currency": "USD", "basis": null },
  "sale_condition": "Redevelopment Project",
  "property_type": "Retail",
  "building_size": { "text": "4,959 SF", "min": 4959, "max": 4959, "unit": "sf" },
  "year_built": 1965,
  "photos_count": 31,
  "contact_phone": "+13108992724",
  "date_on_market": "2026-10-28",
  "last_updated": "2026-10-30"
}
```

All 10 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

10 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Listing Details | `/listings/details` | Everything about one listing: price, size, spaces, photos and brokers |
| Location Autocomplete | `/locations/autocomplete` | Cities, ZIPs, counties and buildings with their LoopNet IDs |
| Search Listings | `/listings/search` | 40 listings per page for sale, lease or auction, filterable |
| Property Records | `/properties/details` | Public record: parcel, zoning, lot size, demographics and nearby listings |
| Search Brokers | `/brokers/search` | 10 brokers per page with brokerage, phones and photo |
| Broker Details | `/brokers/details` | Bio, specialties, markets, phones and every current listing |
| Brokerage Details | `/companies/details` | Website, address, phone, brokers and every listing it markets |
| Traffic Counts | `/traffic/counts` | Daily vehicle counts on the streets around any point |
| Search Businesses for Sale | `/businesses/search` | 50 businesses per page with asking price and cash flow |
| Business Details | `/businesses/details` | Asking price, cash flow, lease, description, photos and seller contact |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-loopnet-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-loopnet-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-loopnet-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/listings/search",
    params={"query": "Beverly Hills, CA", "min_price": 5000000},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about LoopNet Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/loopnet-scraper-github-whatsapp)

[![Ask Us by Email about LoopNet Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20LoopNet%20Scraper%20API&body=I%20need%20help%20using%20the%20LoopNet%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/loopnet-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/loopnet-scraper)
