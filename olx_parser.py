import asyncio
import aiohttp
import ssl
import logging
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional, List, Set, Dict

logger = logging.getLogger(__name__)

COMMON_SYNONYMS: Dict[str, List[str]] = {
    "iphone": ["iphone", "айфон", "iph"],
    "айфон": ["iphone", "айфон", "iph"],
    "iph": ["iphone", "айфон", "iph"],
    "macbook": ["macbook", "макбук"],
    "макбук": ["macbook", "макбук"],
    "playstation": ["playstation", "плейстейшн", "соні", "пс"],
    "плейстейшн": ["playstation", "плейстейшн", "соні", "пс"],
    "ps5": ["ps5", "пс5", "playstation 5", "плейстейшн 5"],
    "пс5": ["ps5", "пс5", "playstation 5", "плейстейшн 5"],
    "ps4": ["ps4", "пс4", "playstation 4", "плейстейшн 4"],
    "пс4": ["ps4", "пс4", "playstation 4", "плейстейшн 4"],
    "airpods": ["airpods", "аірподс", "еірподс", "аирподс"],
    "аірподс": ["airpods", "аірподс", "еірподс", "аирподс"],
    "samsung": ["samsung", "самсунг"],
    "самсунг": ["samsung", "самсунг"],
    "xiaomi": ["xiaomi", "сяомі", "ксіомі", "ксіаомі"],
    "сяомі": ["xiaomi", "сяомі", "ксіомі", "ксіаомі"],
    "навушники": ["навушники", "наушники"],
    "наушники": ["навушники", "наушники"],
    "годинник": ["годинник", "часы"],
    "часы": ["годинник", "часы"],
}

def generate_query_variants(query: str) -> List[str]:
    raw_parts = [p.strip() for p in query.split(",") if p.strip()]
    if not raw_parts:
        raw_parts = [query.strip()]

    variants: Set[str] = set()

    for part in raw_parts:
        variants.add(part)
        words = part.lower().split()
        
        for idx, w in enumerate(words):
            if w in COMMON_SYNONYMS:
                for syn in COMMON_SYNONYMS[w]:
                    new_words = list(words)
                    new_words[idx] = syn
                    variants.add(" ".join(new_words))

    return list(variants)

def is_title_match(query: str, title: str) -> bool:
    title_clean = title.lower().replace("-", " ")
    alternatives = [a.strip() for a in query.split(",") if a.strip()]
    if not alternatives:
        alternatives = [query.strip()]

    for alt in alternatives:
        words = alt.lower().split()
        matched_all_words = True

        for word in words:
            synonyms = COMMON_SYNONYMS.get(word, [word])
            word_matched = False
            for syn in synonyms:
                pattern = r"(?:\b|_)" + re.escape(syn) + r"(?:\b|_)"
                if re.search(pattern, title_clean):
                    word_matched = True
                    break
            
            if not word_matched:
                matched_all_words = False
                break

        if matched_all_words:
            return True

    return False

@dataclass
class OlxOffer:
    id: int
    title: str
    url: str
    price_str: str
    price_val: Optional[float]
    location: str
    photo_url: Optional[str]
    created_time: str
    created_dt: Optional[datetime]

async def _fetch_single_query(
    session: aiohttp.ClientSession,
    query: str,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    limit: int = 40
) -> List[OlxOffer]:
    params = {
        "query": query,
        "sort_by": "created_at:desc",
        "limit": str(limit),
    }
    if min_price is not None and min_price > 0:
        params["filter_float_price:from"] = str(int(min_price))
    if max_price is not None and max_price > 0:
        params["filter_float_price:to"] = str(int(max_price))

    url = "https://www.olx.ua/api/v1/offers/"
    offers: List[OlxOffer] = []

    try:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                logger.warning(f"OLX API returned status {resp.status} for query '{query}'")
                return []
            
            data = await resp.json()
            raw_offers = data.get("data", [])
            
            for item in raw_offers:
                try:
                    offer_id = item.get("id")
                    title = item.get("title", "Без назви")
                    item_url = item.get("url", "")
                    created_time_str = item.get("created_time", "")
                    
                    created_dt = None
                    if created_time_str:
                        try:
                            created_dt = datetime.fromisoformat(created_time_str).astimezone(timezone.utc)
                        except Exception:
                            pass

                    # Price parsing
                    price_str = "Договірна / Без ціни"
                    price_val = None
                    for p in item.get("params", []):
                        if p.get("key") == "price":
                            val_data = p.get("value", {})
                            price_str = val_data.get("label", price_str)
                            price_val = val_data.get("value")
                            break

                    # Location parsing
                    loc = item.get("location", {})
                    city = loc.get("city", {}).get("name", "")
                    region = loc.get("region", {}).get("name", "")
                    location_str = f"{city}, {region}" if city and region else (city or region or "Україна")

                    # Photo parsing
                    photos = item.get("photos", [])
                    photo_url = None
                    if photos:
                        raw_link = photos[0].get("link", "")
                        if raw_link:
                            photo_url = raw_link.replace("{width}", "1000").replace("{height}", "750")

                    offers.append(OlxOffer(
                        id=offer_id,
                        title=title,
                        url=item_url,
                        price_str=price_str,
                        price_val=price_val,
                        location=location_str,
                        photo_url=photo_url,
                        created_time=created_time_str,
                        created_dt=created_dt
                    ))
                except Exception as parse_err:
                    logger.error(f"Error parsing offer item: {parse_err}")
                    continue

    except Exception as e:
        logger.error(f"Network error fetching query '{query}': {e}")
        return []

    return offers

async def fetch_olx_offers(
    query: str,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    limit: int = 40
) -> List[OlxOffer]:
    variants = generate_query_variants(query)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    connector = aiohttp.TCPConnector(ssl=ssl_context)
    timeout = aiohttp.ClientTimeout(total=20)

    all_offers: List[OlxOffer] = []
    seen_ids: Set[int] = set()

    async with aiohttp.ClientSession(connector=connector, timeout=timeout, headers=headers) as session:
        tasks = [
            _fetch_single_query(session, v, min_price=min_price, max_price=max_price, limit=limit)
            for v in variants
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, list):
                for offer in res:
                    if offer.id not in seen_ids:
                        seen_ids.add(offer.id)
                        if is_title_match(query, offer.title):
                            all_offers.append(offer)

    # Sort so that newest created_time is first
    all_offers.sort(key=lambda x: x.created_time, reverse=True)
    return all_offers
