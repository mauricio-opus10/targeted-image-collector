"""
Heuristic image classifier based on textual patterns.

Analyzes URL paths, alt text, and titles to quickly classify images
WITHOUT calling the Vision API. This saves significant costs by
filtering out obvious non-target images (logos, icons, irrelevant content)
before they reach the expensive OpenAI Vision endpoint.

Keywords are loaded from the target configuration (YAML), making
this classifier reusable for any image category.
"""

from typing import Optional, Dict
import re

from target_config import get_target_config


def _normalize_text(text: str) -> str:
    """Normalize text for comparison (lowercase, remove accents)."""
    if not text:
        return ""

    text = text.lower().strip()

    replacements = {
        'a': 'a', 'a': 'a', 'a': 'a', 'a': 'a',
        'e': 'e', 'e': 'e',
        'i': 'i',
        'o': 'o', 'o': 'o', 'o': 'o',
        'u': 'u', 'u': 'u',
        'c': 'c'
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def _score_keywords(text: str, keywords: list) -> float:
    """
    Calculate keyword match score.

    Args:
        text: Text to analyze
        keywords: List of keywords to match against

    Returns:
        Score between 0.0 and 1.0
    """
    if not text:
        return 0.0

    text = _normalize_text(text)
    matches = sum(1 for kw in keywords if _normalize_text(kw) in text)

    return min(matches / 3.0, 1.0)


def _has_exclude_keywords(text: str) -> bool:
    """Check if text contains any exclusion keywords from target config."""
    if not text:
        return False

    target = get_target_config()
    text = _normalize_text(text)
    return any(_normalize_text(kw) in text for kw in target.negative_keywords)


def _analyze_url_pattern(url: str) -> Optional[str]:
    """
    Detect image category from URL path patterns defined in target config.

    Args:
        url: Image URL

    Returns:
        Target category string if pattern matches, None otherwise
    """
    if not url:
        return None

    url_lower = url.lower()
    target = get_target_config()

    for pattern in target.url_patterns:
        if re.search(pattern, url_lower):
            return target.category

    return None


def guess_category_from_text(title: str, alt: str, source: str, url: str = "") -> Dict:
    """
    Classify image based on textual analysis of metadata.

    Examines URL patterns, alt text, titles, and source context to
    determine if an image matches the target category without calling
    the Vision API.

    Args:
        title: Image title
        alt: Alt text
        source: HTML source context
        url: Image URL (optional)

    Returns:
        Dict with category, confidence (0.0-1.0), and reason
    """
    target = get_target_config()
    combined_text = f"{title} {alt} {source} {url}"

    # Check exclusions first (high confidence reject)
    if _has_exclude_keywords(combined_text):
        return {
            "category": "undefined",
            "confidence": 0.9,
            "reason": "Contains exclusion keywords (logo, icon, map, floor plan, etc)"
        }

    # URL pattern analysis (high confidence)
    url_category = _analyze_url_pattern(url)
    if url_category:
        return {
            "category": url_category,
            "confidence": 0.95,
            "reason": f"URL pattern match: {url}"
        }

    # Keyword scoring using target config
    score_target = _score_keywords(combined_text, target.positive_keywords)

    if score_target > 0.3:
        return {
            "category": target.category,
            "confidence": min(0.5 + score_target * 0.4, 0.9),
            "reason": f"Target keywords found (score: {score_target:.2f})"
        }

    if score_target > 0:
        return {
            "category": target.category,
            "confidence": 0.4,
            "reason": "Low confidence - few textual indicators"
        }

    return {
        "category": "undefined",
        "confidence": 0.0,
        "reason": "No textual indicators found"
    }
