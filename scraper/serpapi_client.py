"""
SerpAPI Google Images search client.

Wraps the SerpAPI SDK for Google Images search with:
- Result normalization (consistent dict structure)
- Empty query caching (avoids repeating searches that returned no results)
- Polite delays between API calls
- Multi-page search support
- Pre-filtering by image dimensions and product flag
"""

import time
import random
import hashlib
import json
from pathlib import Path
from serpapi import GoogleSearch
from loguru import logger
from typing import List, Dict, Optional, Tuple, Set, Callable
from urllib.parse import urlparse

from config import (
    SERPAPI_API_KEY,
    SERPAPI_DEFAULT_TBS,
    SERPAPI_GL,
    SERPAPI_HL,
    DELAY_BETWEEN_REQUESTS,
    DELAY_JITTER,
    OUTPUT_DIR,
    SERPAPI_MIN_WIDTH,
    SERPAPI_MIN_HEIGHT,
    SERPAPI_FILTER_PRODUCTS
)


# === Empty Query Cache ===
# Avoids repeating searches that already returned no results

EMPTY_QUERIES_CACHE_FILE = Path(OUTPUT_DIR) / "empty_queries_cache.json"
EMPTY_QUERIES_CACHE: Dict[str, float] = {}
EMPTY_QUERY_CACHE_DAYS = 7


def _get_query_hash(query: str) -> str:
    return hashlib.md5(query.lower().strip().encode()).hexdigest()[:16]


def _load_empty_queries_cache():
    global EMPTY_QUERIES_CACHE
    if not EMPTY_QUERIES_CACHE_FILE.exists():
        return
    try:
        with open(EMPTY_QUERIES_CACHE_FILE, 'r') as f:
            data = json.load(f)
            now = time.time()
            max_age = EMPTY_QUERY_CACHE_DAYS * 86400
            EMPTY_QUERIES_CACHE = {k: v for k, v in data.items() if now - v < max_age}
    except Exception as e:
        logger.debug(f"Error loading empty queries cache: {e}")


def _save_empty_queries_cache():
    try:
        with open(EMPTY_QUERIES_CACHE_FILE, 'w') as f:
            json.dump(EMPTY_QUERIES_CACHE, f)
    except Exception as e:
        logger.debug(f"Error saving empty queries cache: {e}")


def is_query_cached_empty(query: str) -> bool:
    """Check if a query previously returned no results."""
    if not EMPTY_QUERIES_CACHE:
        _load_empty_queries_cache()
    return _get_query_hash(query) in EMPTY_QUERIES_CACHE


def mark_query_as_empty(query: str):
    """Mark a query as returning no results."""
    EMPTY_QUERIES_CACHE[_get_query_hash(query)] = time.time()
    _save_empty_queries_cache()


def _polite_delay():
    """Apply polite delay between SerpAPI calls."""
    delay = DELAY_BETWEEN_REQUESTS + random.uniform(0, DELAY_JITTER)
    time.sleep(delay)


def normalize_serpapi_result(raw_result: Dict) -> Dict:
    """
    Normalize a raw SerpAPI result into a consistent structure.

    Extracts both the image URL and the page URL (for page exploration),
    along with dimensions and product metadata for pre-filtering.

    Args:
        raw_result: Raw result dict from SerpAPI

    Returns:
        Normalized dict with image_url, page_url, title, source,
        thumbnail, position, original_width, original_height, is_product
    """
    return {
        "image_url": raw_result.get("original") or raw_result.get("thumbnail", ""),
        "page_url": raw_result.get("link", ""),
        "title": raw_result.get("title", ""),
        "source": raw_result.get("source", ""),
        "thumbnail": raw_result.get("thumbnail", ""),
        "position": raw_result.get("position", 0),
        "original_width": raw_result.get("original_width", 0),
        "original_height": raw_result.get("original_height", 0),
        "is_product": raw_result.get("is_product", False)
    }


def search_images(query: str, ijn: int = 0, tbs: str = SERPAPI_DEFAULT_TBS,
                  apply_delay: bool = True) -> List[Dict]:
    """
    Search Google Images via SerpAPI.

    Features:
    - Empty query cache (skips known-empty queries)
    - Result normalization
    - Polite delays

    Args:
        query: Search query string
        ijn: Page number (0-based)
        tbs: Google Images filter params (e.g., "itp:photos,isz:l")
        apply_delay: If True, applies delay before search

    Returns:
        List of normalized result dicts
    """
    if not SERPAPI_API_KEY:
        raise RuntimeError("SERPAPI_API_KEY not configured in .env")

    if ijn == 0 and is_query_cached_empty(query):
        logger.info(f"Query in empty cache, skipping: {query[:50]}...")
        return []

    if apply_delay and ijn > 0:
        _polite_delay()

    params = {
        "engine": "google_images",
        "q": query,
        "ijn": ijn,
        "tbs": tbs,
        "gl": SERPAPI_GL,
        "hl": SERPAPI_HL,
        "api_key": SERPAPI_API_KEY,
        "safe": "active",
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()

        if "error" in results:
            logger.error(f"SerpAPI error: {results['error']}")
            if "hasn't returned any results" in str(results['error']):
                mark_query_as_empty(query)
            return []

        raw_images = results.get("images_results", []) or []
        normalized = [normalize_serpapi_result(img) for img in raw_images]

        if normalized:
            logger.info(f"SerpAPI returned {len(normalized)} images for '{query}' (page {ijn})")
        else:
            logger.warning(f"SerpAPI returned no images for '{query}' (page {ijn})")
            if ijn == 0:
                mark_query_as_empty(query)

        return normalized

    except KeyError as e:
        logger.error(f"Malformed SerpAPI response: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected SerpAPI error: {e}")
        return []


def search_images_multi_page(query: str, max_pages: int = 2) -> List[Dict]:
    """
    Search across multiple Google Images pages.

    Args:
        query: Search query
        max_pages: Maximum pages to fetch

    Returns:
        Consolidated list of normalized results
    """
    all_images = []

    for page in range(max_pages):
        images = search_images(query, ijn=page, apply_delay=(page > 0))
        if not images:
            break
        all_images.extend(images)

    return all_images


# === Pre-filtering ===

def prefilter_result(result: Dict, item_id: str = "") -> Tuple[bool, str]:
    """
    Pre-filter a SerpAPI result BEFORE downloading or classifying.

    Checks:
    - Image dimensions (rejects small images using SerpAPI metadata)
    - Product flag (rejects e-commerce product images)

    Args:
        result: Normalized SerpAPI result
        item_id: Item ID for logging

    Returns:
        Tuple of (passed, rejection_reason)
    """
    w = result.get("original_width", 0)
    h = result.get("original_height", 0)

    if w > 0 and h > 0:
        if w < SERPAPI_MIN_WIDTH or h < SERPAPI_MIN_HEIGHT:
            logger.debug(f"[{item_id}] Rejected (small dimensions): {w}x{h}")
            return (False, "small_dimensions")

    if SERPAPI_FILTER_PRODUCTS and result.get("is_product", False):
        logger.debug(f"[{item_id}] Rejected (product image)")
        return (False, "is_product")

    return (True, "")


# === Blocked Domains ===

BLOCKED_DOMAINS = [
    'tiktok.com', 'lookaside.fbsbx.com', 'lookaside.instagram.com',
    'scontent.fbsbx.com', 'scontent-gru', 'fbcdn.net', 'cdninstagram.com',
]


def is_blocked_domain(url: str) -> bool:
    """Check if URL belongs to a blocked domain (social media CDNs that break Vision API)."""
    if not url:
        return False
    url_lower = url.lower()
    return any(blocked in url_lower for blocked in BLOCKED_DOMAINS)
