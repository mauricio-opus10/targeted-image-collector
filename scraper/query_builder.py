"""
Intelligent search query builder with prioritized tiers.

Generates diverse, prioritized search queries for Google Images
based on item metadata. The tier system balances precision
(specific queries) with recall (broader queries).

Query Priority Tiers:
1. Generic broad queries (name + location) - highest coverage
2. Context-specific queries (target keywords from config)
3. Official site scoped queries
4. Organization + item queries
5. Type-specific + fallback queries

Based on analysis of real search logs showing that broad queries
consistently outperform highly specific ones for image discovery.
"""

from typing import List, Tuple, Dict
from loguru import logger
from urllib.parse import urlparse

from target_config import get_target_config


def extract_domain(url: str) -> str:
    """
    Extract clean domain from a URL.

    Args:
        url: Full URL

    Returns:
        Domain without 'www.' prefix
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def get_type_keywords(item_type: str, category: str) -> List[str]:
    """
    Return type-specific keywords based on item classification.

    Args:
        item_type: Item type (e.g., "Residential", "Commercial")
        category: Category (e.g., "Vertical", "Horizontal")

    Returns:
        List of relevant search terms
    """
    keywords = []
    type_lower = (item_type or "").lower()
    cat_lower = (category or "").lower()

    if "residencial" in type_lower or "residential" in type_lower:
        if "vertical" in cat_lower:
            keywords.extend(["apartment", "residential", "condominium", "tower"])
        else:
            keywords.extend(["house", "townhouse", "gated community", "villa"])

    elif "comercial" in type_lower or "commercial" in type_lower:
        keywords.extend(["commercial", "office", "corporate", "business"])

    elif "industrial" in type_lower:
        keywords.extend(["warehouse", "industrial", "logistics"])

    keywords.extend(["development", "project"])
    return keywords


def build_queries(item: Dict) -> List[Tuple[str, int, str]]:
    """
    Build a prioritized list of search queries for an item.

    Returns queries sorted by priority tier (1 = highest priority).
    Each query is a tuple of (query_text, priority, description).

    The tier system is based on empirical analysis:
    - Broad queries (Tier 1) have the highest image yield
    - Specific queries (Tier 3-4) provide higher accuracy
    - Fallbacks (Tier 5) catch edge cases

    Args:
        item: Dict with item metadata (name, city, state,
              organization, website, item_type, category)

    Returns:
        List of (query, priority, description) tuples sorted by priority
    """
    target = get_target_config()

    name = item.get("name", "").strip()
    city = item.get("city", "").strip()
    state = item.get("state", "").strip()
    organization = item.get("organization", "").strip()
    website = item.get("website", "").strip()
    item_type = item.get("item_type", "").strip()
    category = item.get("category", "").strip()

    queries = []

    if not name:
        logger.warning("Item name is empty, cannot construct queries")
        return queries

    # Get search keywords from target config
    target_keywords = target.search_keywords[:3] if target.search_keywords else []
    primary_keyword = target_keywords[0] if target_keywords else ""

    # === TIER 1: BROAD QUERIES (highest coverage) ===

    if city and state:
        queries.append((
            f'"{name}" {city} {state}',
            1,
            "broad_basic"
        ))
        if primary_keyword:
            queries.append((
                f'"{name}" {city} {primary_keyword}',
                1,
                "broad_target"
            ))

    # === TIER 2: CONTEXT QUERIES ===

    if city and state and len(target_keywords) >= 2:
        kw_group = " OR ".join(target_keywords[:3])
        queries.append((
            f'"{name}" {city} ({kw_group})',
            2,
            "context_keywords"
        ))
    if city and state and primary_keyword:
        queries.append((
            f'{name} {city} {state} {primary_keyword}',
            2,
            "no_quotes_target"
        ))

    # === TIER 3: OFFICIAL SITE ===

    if website:
        domain = extract_domain(website)
        if domain:
            queries.append((
                f'"{name}" site:{domain}',
                3,
                "official_site_exact"
            ))
            if primary_keyword:
                queries.append((
                    f'"{name}" site:{domain} ({primary_keyword})',
                    3,
                    "official_site_typed"
                ))

    # === TIER 4: ORGANIZATION + ITEM ===

    if organization and organization != name and city:
        queries.append((
            f'"{organization}" "{name}" {city}',
            4,
            "organization_item_city"
        ))

    # === TIER 5: TYPE-SPECIFIC + FALLBACK ===

    keywords = get_type_keywords(item_type, category)
    if keywords and city:
        queries.append((
            f'{name} {keywords[0]} {city}',
            5,
            f"type_specific_{keywords[0]}"
        ))

    if not city and name:
        fallback_kw = primary_keyword or "image"
        queries.append((
            f'"{name}" {fallback_kw}',
            5,
            "fallback_no_city"
        ))

    # Ensure at least one query exists
    if not queries:
        queries.append((
            f'"{name}" {primary_keyword or "image"}',
            5,
            "fallback_basic"
        ))

    queries.sort(key=lambda x: x[1])

    logger.debug(f"Built {len(queries)} queries for '{name}' (tiers 1-5)")
    return queries


# === Utility Functions ===

def filter_queries_by_priority(queries: List[Tuple[str, int, str]],
                               max_priority: int = 3) -> List[Tuple[str, int, str]]:
    """
    Filter queries keeping only high-priority ones.

    Useful for quick runs with fewer API calls.

    Args:
        queries: Full query list
        max_priority: Maximum tier to include

    Returns:
        Filtered queries
    """
    filtered = [q for q in queries if q[1] <= max_priority]
    logger.info(f"Filtered {len(filtered)}/{len(queries)} queries (priority <= {max_priority})")
    return filtered


def deduplicate_queries(queries: List[Tuple[str, int, str]]) -> List[Tuple[str, int, str]]:
    """
    Remove duplicate queries, keeping the highest-priority version.

    Args:
        queries: Query list with possible duplicates

    Returns:
        Deduplicated queries sorted by priority
    """
    seen = {}

    for query, priority, desc in queries:
        key = query.lower().strip()
        if key not in seen or priority < seen[key][1]:
            seen[key] = (query, priority, desc)

    result = sorted(seen.values(), key=lambda x: x[1])

    if len(result) < len(queries):
        logger.debug(f"Removed {len(queries) - len(result)} duplicate queries")

    return result
