"""
Classification cache system for image validation results.

Saves up to ~40% on OpenAI API costs by avoiding re-classification
of previously processed images. Cache entries expire after a configurable
number of days (default: 30).

How it works:
1. Before calling OpenAI, checks if the URL was already classified
2. If found and not expired, returns cached result (free!)
3. If not found, calls OpenAI and saves result for future runs
"""

import os
import json
import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict
from loguru import logger
from config import CACHE_DIR, CACHE_EXPIRY_DAYS, ENABLE_CACHE


def init_cache():
    """Initialize cache directory structure."""
    if not ENABLE_CACHE:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    logger.debug(f"Cache initialized at: {CACHE_DIR}")


def get_cache_key(item_id: str, image_url: str) -> str:
    """
    Generate unique cache key from item ID + URL.

    Uses MD5 hash to avoid overly long filenames.

    Args:
        item_id: Unique identifier for the building
        image_url: URL of the image

    Returns:
        Hexadecimal hash string
    """
    combined = f"{item_id}_{image_url}"
    return hashlib.md5(combined.encode('utf-8')).hexdigest()


def get_cache_path(item_id: str, image_url: str) -> Path:
    """Return full path for a cache entry file."""
    key = get_cache_key(item_id, image_url)
    return Path(CACHE_DIR) / f"{key}.json"


def is_cache_expired(cache_entry: Dict) -> bool:
    """Check if a cache entry has expired."""
    expires_at = cache_entry.get("expires_at", 0)
    return time.time() > expires_at


def get_cached_classification(item_id: str, image_url: str) -> Optional[Dict]:
    """
    Retrieve classification from cache if it exists and hasn't expired.

    Args:
        item_id: Unique identifier for the building
        image_url: URL of the image

    Returns:
        Dict with classification result, or None if not found/expired
    """
    if not ENABLE_CACHE:
        return None

    cache_path = get_cache_path(item_id, image_url)

    if not cache_path.exists():
        logger.debug(f"[{item_id}] Cache miss: {image_url[:60]}...")
        return None

    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            cache_entry = json.load(f)

        if is_cache_expired(cache_entry):
            logger.debug(f"[{item_id}] Cache expired: {image_url[:60]}...")
            cache_path.unlink()
            return None

        result = cache_entry.get("result")
        age_days = (time.time() - cache_entry.get("timestamp", 0)) / 86400

        logger.info(f"[{item_id}] Cache hit ({age_days:.1f}d): {image_url[:60]}...")

        if result:
            result["from_cache"] = True
            result["cache_age_days"] = age_days

        return result

    except json.JSONDecodeError as e:
        logger.warning(f"[{item_id}] Corrupt cache entry, removing: {e}")
        cache_path.unlink()
        return None

    except Exception as e:
        logger.warning(f"[{item_id}] Error reading cache: {e}")
        return None


def save_to_cache(item_id: str, image_url: str, classification_result: Dict):
    """
    Save classification result to cache.

    Args:
        item_id: Unique identifier for the building
        image_url: URL of the image
        classification_result: OpenAI classification result dict
    """
    if not ENABLE_CACHE:
        return

    cache_path = get_cache_path(item_id, image_url)

    try:
        now = time.time()
        expires_at = now + (CACHE_EXPIRY_DAYS * 86400)

        cache_entry = {
            "url": image_url,
            "item_id": item_id,
            "result": classification_result,
            "timestamp": now,
            "expires_at": expires_at,
            "created_at": datetime.now().isoformat()
        }

        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_entry, f, ensure_ascii=False, indent=2)

        logger.debug(f"[{item_id}] Saved to cache (valid for {CACHE_EXPIRY_DAYS}d)")

    except Exception as e:
        logger.warning(f"[{item_id}] Error saving to cache: {e}")


def clear_expired_cache() -> int:
    """
    Remove expired cache entries.

    Uses file mtime as proxy for creation date (cache files are written once
    and never modified), avoiding the need to open and parse each JSON file.

    Returns:
        Number of files removed
    """
    if not ENABLE_CACHE or not os.path.exists(CACHE_DIR):
        return 0

    removed_count = 0
    total_count = 0
    expiry_seconds = CACHE_EXPIRY_DAYS * 86400
    now = time.time()

    logger.info("Cleaning expired cache entries...")

    for cache_file in Path(CACHE_DIR).glob("*.json"):
        total_count += 1
        try:
            mtime = cache_file.stat().st_mtime
            if (now - mtime) > expiry_seconds:
                cache_file.unlink()
                removed_count += 1
        except Exception as e:
            logger.debug(f"Error processing {cache_file.name}: {e}")

    logger.info(f"Cache cleanup: {removed_count}/{total_count} files removed")
    return removed_count


def get_cache_stats() -> Dict:
    """
    Return cache statistics using file mtime as age proxy.

    Returns:
        Dict with total_entries, valid_entries, expired_entries, total_size_mb
    """
    if not ENABLE_CACHE or not os.path.exists(CACHE_DIR):
        return {"total_entries": 0, "valid_entries": 0, "expired_entries": 0, "total_size_mb": 0}

    total_entries = 0
    valid_entries = 0
    expired_entries = 0
    total_size_bytes = 0
    expiry_seconds = CACHE_EXPIRY_DAYS * 86400
    now = time.time()

    for cache_file in Path(CACHE_DIR).glob("*.json"):
        total_entries += 1
        try:
            stat = cache_file.stat()
            total_size_bytes += stat.st_size
            if (now - stat.st_mtime) > expiry_seconds:
                expired_entries += 1
            else:
                valid_entries += 1
        except Exception:
            pass

    return {
        "total_entries": total_entries,
        "valid_entries": valid_entries,
        "expired_entries": expired_entries,
        "total_size_mb": round(total_size_bytes / (1024 * 1024), 2)
    }


def print_cache_stats():
    """Print cache statistics in a readable format."""
    stats = get_cache_stats()

    logger.info("=" * 50)
    logger.info("CACHE STATISTICS")
    logger.info("=" * 50)
    logger.info(f"Total entries: {stats['total_entries']}")
    logger.info(f"Valid entries: {stats['valid_entries']}")
    logger.info(f"Expired entries: {stats['expired_entries']}")
    logger.info(f"Total size: {stats['total_size_mb']} MB")
    logger.info("=" * 50)
