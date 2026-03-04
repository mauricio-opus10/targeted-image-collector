"""
OpenAI Vision-based image classifier with configurable targets.

Implements a cost-optimized classification pipeline:
1. Heuristic pre-filter (free, catches obvious cases)
2. Cache lookup (free, avoids re-classification)
3. OpenAI Vision API call (paid, only when necessary)

Features:
- Configurable prompts via target config (YAML)
- Differentiated prompts based on image source (official site vs news vs search)
- Batch classification with parallel workers
- Safe error handling with fallback results
- Integrated metrics tracking
"""

import json
import requests
import time
from loguru import logger
from typing import Dict, Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps

from config import (
    OPENAI_API_KEY,
    OPENAI_VISION_MODEL,
    USE_HEURISTIC,
    HEURISTIC_MIN_CONFIDENCE,
    ALWAYS_VALIDATE_ITEM,
    ENABLE_CACHE,
    MAX_CLASSIFICATION_WORKERS,
)
from target_config import get_target_config
from classifier.heuristics import guess_category_from_text
from core.cache import get_cached_classification, save_to_cache
from core.metrics import get_metrics

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


def _safe_classification(func):
    """Decorator that catches classification errors and returns a safe default."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Classification error: {type(e).__name__}: {e}")
            return _error_result(str(e))
    return wrapper


def _build_prompt(context: dict, source_type: str = "") -> str:
    """
    Build the Vision API prompt using the target configuration.

    The prompt is dynamically assembled from the target config,
    making it work for any image category (facades, products, etc.).

    Args:
        context: Item context dict (name, city, state, organization)
        source_type: "news" for news-specific prompt variation

    Returns:
        Formatted prompt string
    """
    target = get_target_config()
    name = context.get("name", "")
    city = context.get("city", "")
    state = context.get("state", "")
    organization = context.get("organization", "")

    # Source-specific preamble
    if source_type == "news":
        preamble = (
            f"**IMPORTANT CONTEXT:** This image was extracted from a NEWS ARTICLE "
            f"or press piece. The page may contain varied images (journalist photos, "
            f"banners, ads, unrelated content). Be rigorous when validating if the "
            f"image matches the item."
        )
    else:
        preamble = (
            f"**IMPORTANT CONTEXT:** This image was extracted from the OFFICIAL "
            f"WEBSITE of the item, so there is a high probability it belongs to "
            f"the correct item."
        )

    # Build extra rules section
    extra_rules = ""
    if target.vision_extra_rules:
        rules = "\n".join(f"**IMPORTANT:** {rule}" for rule in target.vision_extra_rules)
        extra_rules = f"\n\n{rules}"

    prompt = f"""You are a visual classifier specialized in identifying {target.description}.

{preamble}

**This system collects ONLY {target.description}.**

Your task is DUAL:
1. CLASSIFY the image type: "{target.category}" or "undefined"
2. VALIDATE if the image corresponds to "{name}"

---
### CLASSIFICATION
- "{target.category}": {target.vision_target_description}
- "undefined": {target.vision_exclusion_description}
{extra_rules}

---
### RESPONSE FORMAT (exact JSON):
{{
  "category": "{target.category}|undefined",
  "confidence": 0.0-1.0,
  "is_correct_item": true|false,
  "item_confidence": 0.0-1.0,
  "why": "explanation",
  "item_evidence": "justification"
}}

Context: {name} - {city}/{state} - {organization}"""

    return prompt


def classify_with_heuristic(image_url: str, title: str = "", alt: str = "", source: str = "") -> Dict:
    """Classify image using text-based heuristics (no API call)."""
    result = guess_category_from_text(title, alt, source, image_url)

    metrics = get_metrics()
    metrics.record_heuristic_hit()

    return {
        "category": result["category"],
        "confidence": result["confidence"],
        "is_correct_item": None,
        "item_confidence": 0.0,
        "why": result["reason"],
        "item_evidence": "Not verified (heuristic)",
        "method": "heuristic",
        "from_cache": False
    }


@_safe_classification
def classify_with_openai(image_url: str, context: dict, from_official_site: bool = False,
                         source_type: str = "") -> Dict:
    """
    Classify image using OpenAI Vision API.

    Checks cache before making API call. Uses differentiated prompts
    based on the image source (official site, news article, or search engine).

    Args:
        image_url: URL of the image to classify
        context: Item context dict with name, city, state, organization
        from_official_site: If True, uses official site prompt
        source_type: "news" for news-specific prompt

    Returns:
        Classification result dict
    """
    item_id = str(context.get("item_id", ""))
    metrics = get_metrics()
    target = get_target_config()

    # Check cache first
    if ENABLE_CACHE and item_id:
        cached_result = get_cached_classification(item_id, image_url)
        if cached_result:
            metrics.record_cache_hit()
            return cached_result

    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not configured")
        return _error_result("missing API key")

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    prompt = _build_prompt(context, source_type=source_type)

    payload = {
        "model": OPENAI_VISION_MODEL,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": target.vision_system_message
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ],
        "max_tokens": 500
    }

    try:
        time.sleep(0.5)  # Rate limiting

        r = requests.post(OPENAI_API_URL, headers=headers, json=payload, timeout=40)
        r.raise_for_status()

        data = r.json()
        txt = data["choices"][0]["message"]["content"]
        parsed = json.loads(txt)

        cat = parsed.get("category", "undefined")
        if cat not in {target.category, "undefined"}:
            cat = "undefined"

        conf = float(parsed.get("confidence", 0.0))
        is_correct = bool(parsed.get("is_correct_item", False))
        item_conf = float(parsed.get("item_confidence", 0.0))

        if not is_correct:
            conf = min(conf, 0.3)

        result = {
            "category": cat,
            "confidence": conf,
            "is_correct_item": is_correct,
            "item_confidence": item_conf,
            "why": parsed.get("why", ""),
            "item_evidence": parsed.get("item_evidence", ""),
            "method": "openai",
            "from_cache": False
        }

        if ENABLE_CACHE and item_id:
            save_to_cache(item_id, image_url, result)

        metrics.record_openai_call()
        return result

    except Exception as e:
        logger.warning(f"OpenAI Vision error: {type(e).__name__}: {e}")
        return _error_result(str(e))


def _error_result(reason: str) -> Dict:
    """Return a safe default error result."""
    return {
        "category": "undefined",
        "confidence": 0.0,
        "is_correct_item": False,
        "item_confidence": 0.0,
        "why": f"error: {reason}",
        "item_evidence": "error",
        "method": "error",
        "from_cache": False
    }


def classify_image(image_url: str, context: dict, title: str = "", alt: str = "",
                   source: str = "", from_official_site: bool = False,
                   source_type: str = "") -> Dict:
    """
    Main classification entry point.

    Implements the cost-optimized pipeline:
    1. Try heuristic first (free)
    2. If heuristic is confident enough AND we don't need item validation, return it
    3. Otherwise, use OpenAI Vision (with cache)

    Args:
        image_url: URL of the image
        context: Item context dict
        title: Image title
        alt: Alt text
        source: Source domain
        from_official_site: If from official website
        source_type: Source type string ("news", etc.)

    Returns:
        Classification result dict
    """
    if USE_HEURISTIC:
        heuristic_result = classify_with_heuristic(image_url, title, alt, source)

        if heuristic_result["confidence"] >= HEURISTIC_MIN_CONFIDENCE:
            if not ALWAYS_VALIDATE_ITEM or heuristic_result["category"] == "undefined":
                return heuristic_result

    return classify_with_openai(image_url, context, from_official_site, source_type=source_type)


def classify_images_batch(images_data: List[Dict], max_workers: Optional[int] = None) -> List[Dict]:
    """
    Classify multiple images in parallel.

    Args:
        images_data: List of dicts with image_url, context, and optional metadata
        max_workers: Number of parallel workers

    Returns:
        List of results in the same order as input
    """
    max_workers = max_workers or MAX_CLASSIFICATION_WORKERS

    logger.info(f"Classifying {len(images_data)} images in parallel ({max_workers} workers)...")

    results = [None] * len(images_data)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(
                classify_image,
                img_data["image_url"],
                img_data["context"],
                img_data.get("title", ""),
                img_data.get("alt", ""),
                img_data.get("source", ""),
                img_data.get("from_official_site", False)
            ): i
            for i, img_data in enumerate(images_data)
        }

        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results[index] = future.result()
            except Exception as e:
                logger.error(f"Parallel classification error: {e}")
                results[index] = _error_result(str(e))

    return results
