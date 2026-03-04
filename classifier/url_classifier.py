"""
Intelligent URL classification and validation module.

Pre-filters images by URL analysis before sending to the Vision API,
saving significant costs. Implements:

- Item name detection in URL paths
- Homonym detection (rejects URLs containing OTHER items' names)
- CDN/generic URL identification
- Source type classification (official site, news, social media, portal)
- Multi-level validation (strict and moderate modes)
"""

import re
import unicodedata
from urllib.parse import urlparse
from typing import Dict, List, Set


def normalize_text(text: str) -> str:
    """
    Normalize text for comparison (remove accents, lowercase, strip specials).

    Args:
        text: Text to normalize

    Returns:
        Normalized text string
    """
    if not text:
        return ""

    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = ' '.join(text.split())
    return text


def extract_keywords(item_name: str) -> List[str]:
    """
    Extract meaningful keywords from an item name.

    Removes common stopwords and generic terms to isolate
    the distinctive parts of the name.

    Args:
        item_name: Full item name

    Returns:
        List of distinctive keywords
    """
    stopwords = {
        'the', 'de', 'da', 'do', 'das', 'dos', 'em', 'na', 'no', 'para',
        'com', 'e', 'a', 'o', 'as', 'os', 'um', 'uma', 'ao', 'aos',
        'residencial', 'condominio', 'edificio', 'predio', 'torre',
        'residence', 'building', 'tower', 'condominium',
        'comercial', 'institucional', 'empresarial', 'corporativo',
        'hotel', 'hospital', 'shopping', 'center', 'centre', 'mall',
        'escola', 'faculdade', 'universidade', 'college', 'university',
        'clinica', 'clinic', 'laboratorio', 'laboratory',
        'escritorio', 'office', 'sala', 'loja', 'store', 'shop',
        'centro', 'business', 'park', 'plaza', 'square',
        'flat', 'apart', 'inn', 'suites'
    }

    normalized = normalize_text(item_name)
    return [w for w in normalized.split() if len(w) > 2 and w not in stopwords]


def check_for_other_items(url: str, current_item: str, all_items: Set[str]) -> Dict:
    """
    Detect if a URL references a DIFFERENT item than the current one.

    This prevents downloading images of similarly-named items.
    Uses keyword overlap analysis with the full dataset of item names.

    Args:
        url: Image or page URL
        current_item: Name of the current item being processed
        all_items: Set of ALL item names in the dataset

    Returns:
        Dict with is_valid, conflicting_item, and reason
    """
    if not url or not current_item or not all_items:
        return {"is_valid": True, "conflicting_item": None, "reason": "Insufficient parameters"}

    url_normalized = normalize_text(url)
    current_normalized = normalize_text(current_item)
    current_keywords = set(extract_keywords(current_item))

    for other_item in all_items:
        other_normalized = normalize_text(other_item)

        if other_normalized == current_normalized:
            continue
        if current_normalized in other_normalized or other_normalized in current_normalized:
            continue

        other_keywords = set(extract_keywords(other_item))
        unique_other_keywords = other_keywords - current_keywords

        if not unique_other_keywords:
            continue

        matches = [kw for kw in unique_other_keywords if kw in url_normalized]

        # 2+ unique keywords from another item = conflict
        if len(matches) >= 2:
            return {
                "is_valid": False,
                "conflicting_item": other_item,
                "reason": f"URL contains {len(matches)} keywords from another item: {', '.join(matches)}"
            }

        # 1 significant keyword (5+ chars) = conflict
        if len(matches) == 1 and len(matches[0]) >= 5:
            return {
                "is_valid": False,
                "conflicting_item": other_item,
                "reason": f"URL contains significant keyword from another item: {matches[0]}"
            }

    return {"is_valid": True, "conflicting_item": None, "reason": "No other items detected in URL"}


def is_cdn_or_generic_url(url: str) -> bool:
    """
    Check if a URL belongs to a generic CDN (no item name in path).

    Args:
        url: Image URL

    Returns:
        True if URL matches a known CDN pattern
    """
    if not url:
        return False

    cdn_patterns = [
        r'/estatico/', r'/static/', r'/assets/', r'/uploads/',
        r'/media/', r'/images/', r'/img/',
        r'cloudfront\.net', r'cloudinary\.com', r'imgix\.net',
        r'akamaized\.net', r'b-cdn\.net',
        r'/[\da-f]{32,}',         # MD5/SHA hashes
        r'/\d{4}/\d{2}/\d{2}/',   # Date paths (2024/01/15)
    ]

    return any(re.search(p, url, re.IGNORECASE) for p in cdn_patterns)


def validate_url_strict(url: str, item_name: str, domain: str = None,
                        all_items: Set[str] = None) -> Dict:
    """
    STRICT URL validation for maximum accuracy.

    Strategy:
    - Only accepts if URL contains item name keywords in the path
    - Rejects generic CDNs without item name
    - Rejects URLs containing OTHER items' names
    - Domain match provides a confidence bonus

    Args:
        url: Image URL
        item_name: Item name to validate against
        domain: Expected domain (e.g., "example.com")
        all_items: Set of all item names for homonym detection

    Returns:
        Dict with is_valid, confidence, reason, and validation_level
    """
    if not url or not item_name:
        return {"is_valid": False, "confidence": 0.0, "reason": "Empty URL or item name", "validation_level": "strict"}

    # Check domain match (bonus, not required)
    domain_matches = False
    if domain:
        try:
            parsed = urlparse(url)
            url_domain = parsed.netloc.replace('www.', '')
            domain_clean = domain.replace('www.', '')
            domain_matches = domain_clean in url_domain
        except Exception:
            pass

    # Check for other items' names
    if all_items:
        homonym_check = check_for_other_items(url, item_name, all_items)
        if not homonym_check["is_valid"]:
            return {
                "is_valid": False, "confidence": 0.0,
                "reason": homonym_check["reason"],
                "conflicting_item": homonym_check["conflicting_item"],
                "validation_level": "strict"
            }

    # Check CDN and keyword presence
    is_cdn = is_cdn_or_generic_url(url)
    keywords = extract_keywords(item_name)

    if not keywords:
        return {"is_valid": False, "confidence": 0.0, "reason": "No identifiable keywords in item name", "validation_level": "strict"}

    try:
        parsed = urlparse(url)
        url_path = parsed.path + parsed.query + parsed.fragment
        url_normalized = normalize_text(url_path)
    except Exception:
        return {"is_valid": False, "confidence": 0.0, "reason": "URL parsing error", "validation_level": "strict"}

    keywords_found = [kw for kw in keywords if kw in url_normalized]
    match_ratio = len(keywords_found) / len(keywords) if keywords else 0

    if is_cdn and len(keywords_found) == 0:
        return {"is_valid": False, "confidence": 0.0, "reason": "Generic CDN without item name in path", "validation_level": "strict"}

    if not is_cdn and len(keywords_found) == 0:
        return {"is_valid": False, "confidence": 0.0, "reason": "URL contains no item keywords", "validation_level": "strict"}

    if match_ratio < 0.5 or (len(keywords) >= 3 and len(keywords_found) < 2):
        return {
            "is_valid": False, "confidence": 0.3,
            "reason": f"URL contains only {len(keywords_found)}/{len(keywords)} keywords (insufficient for strict validation)",
            "validation_level": "strict"
        }

    confidence = 0.7 + (match_ratio * 0.2)
    if domain_matches:
        confidence += 0.1

    reason = f"URL approved: {len(keywords_found)}/{len(keywords)} keywords in path"
    if domain_matches:
        reason += " + official domain"

    return {
        "is_valid": True, "confidence": confidence,
        "reason": reason, "keywords_found": keywords_found,
        "validation_level": "strict", "domain_matches": domain_matches
    }


def validate_url_contains_item(url: str, item_name: str,
                               all_items: Set[str] = None) -> Dict:
    """
    MODERATE URL validation (wider acceptance, still catches homonyms).

    Args:
        url: Image URL
        item_name: Item name
        all_items: Set of all item names for homonym detection

    Returns:
        Dict with is_valid, confidence, reason, and metadata
    """
    if not url or not item_name:
        return {
            "is_valid": False, "confidence": 0.0, "reason": "Empty URL or item name",
            "url_path": "", "keywords_found": [], "keywords_expected": [], "conflicting_item": None
        }

    if all_items:
        homonym_check = check_for_other_items(url, item_name, all_items)
        if not homonym_check["is_valid"]:
            return {
                "is_valid": False, "confidence": 0.0, "reason": homonym_check["reason"],
                "url_path": url[:100], "keywords_found": [],
                "keywords_expected": extract_keywords(item_name),
                "conflicting_item": homonym_check["conflicting_item"]
            }

    keywords = extract_keywords(item_name)
    if not keywords:
        return {"is_valid": True, "confidence": 0.5, "reason": "No identifiable keywords",
                "url_path": "", "keywords_found": [], "keywords_expected": [], "conflicting_item": None}

    try:
        parsed = urlparse(url)
        url_path = parsed.path + parsed.query + parsed.fragment
        url_normalized = normalize_text(url_path)
    except Exception:
        return {"is_valid": True, "confidence": 0.5, "reason": "URL parsing error",
                "url_path": "", "keywords_found": [], "keywords_expected": keywords, "conflicting_item": None}

    keywords_found = [kw for kw in keywords if kw in url_normalized]
    match_ratio = len(keywords_found) / len(keywords) if keywords else 0

    if is_cdn_or_generic_url(url):
        return {"is_valid": True, "confidence": 0.5, "reason": "Generic CDN URL (cannot validate by URL)",
                "url_path": url_path[:100], "keywords_found": [], "keywords_expected": keywords, "conflicting_item": None}

    if len(keywords_found) == 0:
        return {
            "is_valid": False, "confidence": 0.0,
            "reason": f"URL contains no keywords from '{item_name}'",
            "url_path": url_path[:100], "keywords_found": [], "keywords_expected": keywords, "conflicting_item": None
        }

    min_required = 1 if len(keywords) >= 2 else 0
    if len(keywords_found) < min_required:
        return {
            "is_valid": False, "confidence": 0.2 + (match_ratio * 0.3),
            "reason": f"URL contains only {len(keywords_found)}/{len(keywords)} keywords",
            "url_path": url_path[:100], "keywords_found": keywords_found,
            "keywords_expected": keywords, "conflicting_item": None
        }

    confidence = 0.6 + (match_ratio * 0.4)
    return {
        "is_valid": True, "confidence": confidence,
        "reason": f"URL contains {len(keywords_found)}/{len(keywords)} item keywords",
        "url_path": url_path[:100], "keywords_found": keywords_found,
        "keywords_expected": keywords, "conflicting_item": None
    }


# === URL Source Classification ===

NEWS_DOMAINS = {
    'g1.globo.com', 'oglobo.globo.com', 'folha.uol.com.br',
    'estadao.com.br', 'correiobraziliense.com.br', 'gazetadopovo.com.br',
    'valor.globo.com', 'infomoney.com.br', 'exame.com',
    'gauchazh.clicrbs.com.br', 'diariodonordeste.verdesmares.com.br',
    'uol.com.br', 'terra.com.br', 'r7.com',
}

NEWS_URL_PATTERNS = [
    r'/noticia[s]?/', r'/noticias/', r'/news/',
    r'/opiniao/', r'/colunist[a]?/', r'/blog/',
    r'/sala-de-imprensa/', r'/press/',
    r'/artigo[s]?/', r'/materia/',
]

SOCIAL_DOMAINS = {
    'instagram.com', 'facebook.com', 'twitter.com', 'x.com',
    'tiktok.com', 'youtube.com', 'linkedin.com',
}

GOV_DOMAINS_PATTERNS = [r'\.gov\.br', r'\.leg\.br', r'\.jus\.br']


def classify_url_source(url: str) -> str:
    """
    Classify the source type of a URL.

    Returns the source type to adapt pipeline behavior:
    - "official": Official item/organization website
    - "news": News site, newspaper, magazine, blog
    - "social": Social media (Instagram, Facebook, etc.)
    - "gov": Government website
    - "official": Default when unidentified

    Args:
        url: URL to classify

    Returns:
        Source type string
    """
    if not url:
        return "official"

    url_lower = url.lower()

    try:
        parsed = urlparse(url_lower)
        domain = parsed.netloc.replace('www.', '')
        path = parsed.path
    except Exception:
        return "official"

    # Social media
    for social in SOCIAL_DOMAINS:
        if social in domain:
            return "social"

    # News by domain
    for news in NEWS_DOMAINS:
        if news in domain:
            return "news"

    # News by domain keyword
    if any(kw in domain for kw in ('noticia', 'noticias', 'news', 'jornal', 'diario', 'gazeta')):
        return "news"

    # News by URL path pattern
    for pattern in NEWS_URL_PATTERNS:
        if re.search(pattern, path):
            return "news"

    # Government
    for pattern in GOV_DOMAINS_PATTERNS:
        if re.search(pattern, domain):
            return "gov"

    return "official"
