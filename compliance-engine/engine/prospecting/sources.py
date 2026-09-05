"""Where leads come from.

Three sources, all normalised to ``Prospect``:

* ``CsvSource`` - a file you hand it (always available).
* ``OverpassSource`` - OpenStreetMap, free, no key; businesses with a ``website`` tag.
* ``GooglePlacesSource`` - Places API (New) text search; best coverage, needs a key.

Large brands, chains, and aggregator domains are dropped so the pipeline stays
pointed at genuinely small businesses.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol
from urllib.parse import urlparse

import httpx

SKIP_DOMAINS = {
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com", "yelp.com", "google.com",
    "youtube.com", "tiktok.com", "linktr.ee", "wixsite.com", "business.site", "godaddysites.com",
    "square.site", "doordash.com", "grubhub.com", "ubereats.com", "toasttab.com", "opentable.com",
    "amazon.com", "walmart.com", "target.com", "starbucks.com", "mcdonalds.com", "subway.com",
    "cvs.com", "walgreens.com", "homedepot.com", "lowes.com", "bankofamerica.com", "chase.com",
    "wellsfargo.com", "usps.com", "ups.com", "fedex.com",
}


@dataclass
class Prospect:
    url: str
    domain: str
    business_name: str | None = None
    category: str | None = None
    city: str | None = None
    region: str | None = None
    country: str = "US"
    phone: str | None = None
    email: str | None = None
    source: str = "manual"

    def as_lead_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["contact_email"] = d.pop("email")
        d["contact_source"] = "source_listing" if d["contact_email"] else None
        d.pop("phone")
        return d


def normalise_url(raw: str) -> tuple[str, str] | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    p = urlparse(raw)
    host = (p.hostname or "").lower()
    if not host or "." not in host:
        return None
    host = host[4:] if host.startswith("www.") else host
    root = ".".join(host.split(".")[-2:])
    if host in SKIP_DOMAINS or root in SKIP_DOMAINS:
        return None
    return f"{p.scheme}://{p.netloc}{p.path or '/'}", host


class LeadSource(Protocol):
    name: str
    def search(self, *, category: str, city: str, region: str | None = None, limit: int = 50) -> Iterator[Prospect]: ...


class CsvSource:
    """CSV with at least a ``url`` (or ``domain``/``website``) column."""

    name = "csv"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def search(self, *, category: str = "", city: str = "", region: str | None = None, limit: int = 100000) -> Iterator[Prospect]:
        yield from self.iter_all(limit=limit)

    def iter_all(self, limit: int = 100000) -> Iterator[Prospect]:
        with self.path.open(newline="", encoding="utf-8") as fh:
            n = 0
            for row in csv.DictReader(fh):
                row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
                raw = row.get("url") or row.get("website") or row.get("domain")
                norm = normalise_url(raw or "")
                if not norm:
                    continue
                url, domain = norm
                yield Prospect(
                    url=url, domain=domain, business_name=row.get("business_name") or row.get("name") or None,
                    category=row.get("category") or None, city=row.get("city") or None,
                    region=row.get("region") or row.get("state") or None, country=row.get("country") or "US",
                    phone=row.get("phone") or None, email=(row.get("email") or None), source="csv",
                )
                n += 1
                if n >= limit:
                    return


OSM_CATEGORY_TAGS: dict[str, str] = {
    "restaurant": '["amenity"="restaurant"]', "cafe": '["amenity"="cafe"]', "bar": '["amenity"="bar"]',
    "dentist": '["amenity"="dentist"]', "doctor": '["amenity"="doctors"]', "clinic": '["amenity"="clinic"]',
    "lawyer": '["office"="lawyer"]', "attorney": '["office"="lawyer"]', "accountant": '["office"="accountant"]',
    "veterinarian": '["amenity"="veterinary"]', "vet": '["amenity"="veterinary"]', "pharmacy": '["amenity"="pharmacy"]',
    "gym": '["leisure"="fitness_centre"]', "fitness": '["leisure"="fitness_centre"]', "salon": '["shop"="hairdresser"]',
    "hairdresser": '["shop"="hairdresser"]', "barber": '["shop"="hairdresser"]', "spa": '["shop"="beauty"]',
    "florist": '["shop"="florist"]', "bakery": '["shop"="bakery"]', "auto repair": '["shop"="car_repair"]',
    "mechanic": '["shop"="car_repair"]', "plumber": '["craft"="plumber"]', "electrician": '["craft"="electrician"]',
    "hvac": '["craft"="hvac"]', "contractor": '["craft"="builder"]', "roofing": '["craft"="roofer"]',
    "landscaping": '["craft"="gardener"]', "chiropractor": '["healthcare"="chiropractor"]', "hotel": '["tourism"="hotel"]',
    "real estate": '["office"="estate_agent"]', "insurance": '["office"="insurance"]', "optician": '["shop"="optician"]',
    "pet store": '["shop"="pet"]', "bookstore": '["shop"="books"]', "jeweler": '["shop"="jewelry"]',
    "furniture": '["shop"="furniture"]', "cleaning": '["shop"="dry_cleaning"]', "tattoo": '["shop"="tattoo"]',
}


class OverpassSource:
    name = "overpass"

    def __init__(self, endpoint: str = "https://overpass-api.de/api/interpreter", timeout: float = 60.0,
                 client: httpx.Client | None = None):
        self.endpoint = endpoint
        self.client = client or httpx.Client(timeout=timeout, trust_env=True)

    @staticmethod
    def build_query(category: str, city: str, region: str | None) -> str:
        tag = OSM_CATEGORY_TAGS.get(category.lower())
        if tag is None:
            tag = f'["shop"="{re.sub(r"[^a-z_]", "_", category.lower())}"]'
        area_filter = f'["name"="{city}"]["boundary"="administrative"]'
        if region:
            area_filter += f'["is_in:state_code"="{region.upper()}"]'
        return (
            "[out:json][timeout:60];"
            f"area{area_filter}->.a;"
            f'(nwr(area.a){tag}["website"];nwr(area.a){tag}["contact:website"];);'
            "out tags center 200;"
        )

    def search(self, *, category: str, city: str, region: str | None = None, limit: int = 50) -> Iterator[Prospect]:
        q = self.build_query(category, city, region)
        r = self.client.post(self.endpoint, data={"data": q})
        r.raise_for_status()
        yield from self.parse(r.json(), category=category, city=city, region=region, limit=limit)

    @staticmethod
    def parse(payload: dict[str, Any], *, category: str, city: str, region: str | None, limit: int) -> Iterator[Prospect]:
        seen: set[str] = set()
        for el in payload.get("elements", []):
            tags = el.get("tags", {})
            site = tags.get("website") or tags.get("contact:website")
            norm = normalise_url(site or "")
            if not norm or norm[1] in seen:
                continue
            seen.add(norm[1])
            yield Prospect(
                url=norm[0], domain=norm[1], business_name=tags.get("name"), category=category,
                city=tags.get("addr:city") or city, region=region, phone=tags.get("phone") or tags.get("contact:phone"),
                email=tags.get("email") or tags.get("contact:email"), source="overpass",
            )
            if len(seen) >= limit:
                return


class GooglePlacesSource:
    name = "google_places"
    endpoint = "https://places.googleapis.com/v1/places:searchText"

    def __init__(self, api_key: str, timeout: float = 30.0, client: httpx.Client | None = None):
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=timeout, trust_env=True)

    def search(self, *, category: str, city: str, region: str | None = None, limit: int = 50) -> Iterator[Prospect]:
        page_token = None
        seen: set[str] = set()
        while True:
            body: dict[str, Any] = {"textQuery": f"{category} in {city}{', ' + region if region else ''}", "pageSize": 20}
            if page_token:
                body["pageToken"] = page_token
            r = self.client.post(
                self.endpoint, json=body,
                headers={
                    "X-Goog-Api-Key": self.api_key,
                    "X-Goog-FieldMask": "places.displayName,places.websiteUri,places.formattedAddress,"
                                        "places.nationalPhoneNumber,places.primaryType,places.userRatingCount,nextPageToken",
                },
            )
            r.raise_for_status()
            data = r.json()
            for p in self.parse(data, category=category, city=city, region=region):
                if p.domain in seen:
                    continue
                seen.add(p.domain)
                yield p
                if len(seen) >= limit:
                    return
            page_token = data.get("nextPageToken")
            if not page_token:
                return

    @staticmethod
    def parse(data: dict[str, Any], *, category: str, city: str, region: str | None) -> Iterator[Prospect]:
        for place in data.get("places", []):
            # Chains have thousands of reviews; small businesses don't.
            if (place.get("userRatingCount") or 0) > 2500:
                continue
            norm = normalise_url(place.get("websiteUri") or "")
            if not norm:
                continue
            yield Prospect(
                url=norm[0], domain=norm[1], business_name=(place.get("displayName") or {}).get("text"),
                category=category, city=city, region=region, phone=place.get("nationalPhoneNumber"), source="google_places",
            )


def dedupe(prospects: Iterable[Prospect]) -> list[Prospect]:
    seen: set[str] = set()
    out = []
    for p in prospects:
        if p.domain not in seen:
            seen.add(p.domain)
            out.append(p)
    return out
