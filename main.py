"""
Targeted Image Collector - Pipeline Orchestrator

Configurable system for collecting specific types of images from the web.
Combines site scraping, Google Images search (via SerpAPI), and
AI-powered validation (OpenAI Vision) into a multi-stage pipeline.

The target image type (facades, products, vehicles, etc.) is defined
via YAML configuration files — see targets/ directory.

Pipeline Architecture:
    Phase 1 - Site Scraping: Extract images from official/news websites
    Phase 2 - SerpAPI Search: Complement with Google Images results

    For each candidate image, a 7-filter validation pipeline runs:
    0.   URL validation (item name, homonym detection)
    0.5  Blocked domain filter (social media CDNs)
    1.   AI Classification (heuristic-first, then OpenAI Vision)
    2.   Correct item verification
    2.5  Minimum confidence threshold
    3.   Valid category (target match)
    4.   Per-item image limit
    5.   Image download
    6.   Minimum dimensions check
    7.   Perceptual hash deduplication

Usage:
    python main.py --input items.json --limit 100
    python main.py --input items.json --target targets/facades.yaml --parallel
    python main.py --input items.json --target targets/products.yaml --workers 3

Note:
    This is a simplified version showing the pipeline architecture.
    You'll need to implement your own data loading logic for your
    specific data source (database, API, spreadsheet, etc.).
"""

import os
import time
import argparse
from urllib.parse import urlparse
from tqdm import tqdm
from loguru import logger
from typing import Dict, Set, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

from config import (
    OUTPUT_DIR, MIN_WIDTH, MIN_HEIGHT,
    MAX_IMAGES_PER_ITEM, FILENAME_PATTERN,
    MAX_ITEM_WORKERS,
    MIN_CONFIDENCE_THRESHOLD,
    MIN_CONFIDENCE_THRESHOLD_NEWS,
    SOURCE_PROMISING_PAGE,
    TARGET_CONFIG_FILE
)
from target_config import load_target_config, get_target_config
from scraper.serpapi_client import search_images, is_blocked_domain, prefilter_result
from classifier.vision_validator import classify_image
from core.downloader import download_image, save_image
from core.dedup import phash, HashIndex
from scraper.site_scraper import extract_image_urls
from classifier.url_classifier import (
    validate_url_contains_item, is_cdn_or_generic_url, classify_url_source
)
from scraper.query_builder import build_queries
from core.cache import init_cache, clear_expired_cache, print_cache_stats
from schemas import validate_items_batch
from core.metrics import get_metrics, reset_metrics
from core.checkpoint import (
    load_checkpoint, mark_item_processed, get_pending_items,
    print_checkpoint_summary, clear_checkpoint
)

# Global cache of all item names (for homonym detection)
ALL_ITEM_NAMES: Set[str] = set()

# Global checkpoint (loaded in main)
CHECKPOINT: Dict = {}


def load_items(input_path: str) -> List[Dict]:
    """
    Load items from your data source.

    This is a placeholder - implement your own data loading logic here.
    The function should return a list of dicts with at least:
    - item_id: Unique identifier
    - name: Item name
    - city: City/location (optional but recommended)
    - state: State abbreviation (optional)
    - organization: Developer/manufacturer/brand (optional)
    - website: Official URL (optional)

    Args:
        input_path: Path to your data source

    Returns:
        List of validated item dicts
    """
    global ALL_ITEM_NAMES

    # --- IMPLEMENT YOUR DATA LOADING HERE ---
    # Example with JSON:
    # import json
    # with open(input_path, 'r') as f:
    #     raw_data = json.load(f)
    #
    # Example with CSV:
    # import pandas as pd
    # df = pd.read_csv(input_path)
    # raw_data = df.to_dict(orient="records")

    raise NotImplementedError(
        "Implement load_items() with your own data source. "
        "See docstring for expected format."
    )

    # After loading, validate with Pydantic:
    # valid_items, invalid = validate_items_batch(raw_data)
    # ALL_ITEM_NAMES = {item.name for item in valid_items}
    # return [item.to_dict() for item in valid_items]


def build_filename(item_id: str, category: str, number: int) -> str:
    """Generate output filename for a saved image."""
    return FILENAME_PATTERN.format(
        item_id=item_id,
        category=category,
        number=number
    )


# ============================================================================
# 7-FILTER VALIDATION PIPELINE
# ============================================================================

def _validate_url_filters(img_url: str, name: str, item_id: str, source: str) -> bool:
    """Apply URL validation filters (Filters 0 and 0.5)."""
    metrics = get_metrics()

    skip_url_validation = SOURCE_PROMISING_PAGE in source or source == "site_news"

    if not skip_url_validation and not is_cdn_or_generic_url(img_url):
        url_validation = validate_url_contains_item(
            img_url, name, all_items=ALL_ITEM_NAMES
        )
        if not url_validation["is_valid"]:
            metrics.record_rejection("url_validation")
            return False

    if is_blocked_domain(img_url):
        metrics.record_rejection("blocked_social_media")
        return False

    return True


def _validate_classification_result(result: Dict, item_id: str, source: str = "") -> bool:
    """Apply classification validation filters (Filters 2, 2.5, 3)."""
    metrics = get_metrics()
    target = get_target_config()

    is_correct = result.get("is_correct_item", None)
    confidence = result.get("confidence", 0.0)
    category = result.get("category", "undefined")

    # Filter 2: Correct item
    if is_correct is False:
        metrics.record_rejection("wrong_item")
        return False

    # Filter 2.5: Minimum confidence (lower threshold for news sources)
    threshold = MIN_CONFIDENCE_THRESHOLD_NEWS if source == "site_news" else MIN_CONFIDENCE_THRESHOLD
    if confidence < threshold:
        metrics.record_rejection("low_confidence")
        return False

    # Filter 3: Valid category (must match target)
    if category != target.category:
        metrics.record_rejection("wrong_category")
        return False

    return True


def _validate_and_download(
    img_url: str, item_id: str, saved: Dict,
    max_targets: int, index: HashIndex
) -> Tuple[bool, Optional[Image.Image]]:
    """Apply download, dimension, and dedup filters (Filters 4-7)."""
    metrics = get_metrics()

    # Filter 4: Limit reached
    if saved["target"] >= max_targets:
        metrics.record_rejection("limit_reached")
        return False, None

    # Filter 5: Download
    img = download_image(img_url, apply_delay=False)
    if img is None:
        metrics.record_rejection("download_failed")
        return False, None

    # Filter 6: Dimensions
    if img.width < MIN_WIDTH or img.height < MIN_HEIGHT:
        metrics.record_rejection("dimensions")
        return False, None

    # Filter 7: Deduplication
    h = phash(img)
    ok, dup = index.add_and_check(h, img_url, item_id)
    if not ok:
        metrics.record_rejection("duplicate")
        return False, None

    return True, img


def classify_and_save(img_url: str, item: Dict, item_dir: str,
                      index: HashIndex, saved: Dict, max_targets: int,
                      from_official_site: bool = False,
                      source: str = "", query_used: str = "",
                      source_type: str = "") -> bool:
    """
    Classify, validate, and save an image through the full 7-filter pipeline.

    Returns True if the image was saved, False if rejected at any stage.
    """
    item_id = str(item.get("item_id", ""))
    name = item.get("name", "")
    target = get_target_config()
    start_time = time.time()

    # Filters 0, 0.5: URL validation
    if not _validate_url_filters(img_url, name, item_id, source):
        return False

    # Filter 1: AI Classification
    classification = classify_image(
        image_url=img_url,
        context=item,
        source=urlparse(img_url).netloc if img_url else "",
        from_official_site=from_official_site,
        source_type=source_type
    )

    # Filters 2, 2.5, 3: Classification validation
    if not _validate_classification_result(classification, item_id, source=source):
        return False

    # Filters 4-7: Download, dimensions, deduplication
    success, img = _validate_and_download(img_url, item_id, saved, max_targets, index)
    if not success:
        return False

    # Save image
    rank = saved["target"] + 1
    filename = build_filename(item_id, target.category, rank)
    filepath = os.path.join(item_dir, filename)
    save_image(img, filepath)
    saved["target"] += 1

    elapsed_ms = int((time.time() - start_time) * 1000)
    method = classification.get("method", "unknown")
    confidence = classification.get("confidence", 0.0)

    metrics = get_metrics()
    metrics.record_image_saved(target.category, source)

    logger.info(
        f'[{item_id}] SAVED {target.category.upper()} ({saved["target"]}/{max_targets}) | '
        f'conf={confidence:.2f} | {method} | {elapsed_ms}ms'
    )

    return True


def process_item(item: Dict, out_dir: str,
                 site_only: bool = False, serpapi_only: bool = False,
                 max_pages: int = 2) -> Dict:
    """
    Process a single item through the full pipeline.

    Phase 1: Scrape the official/news website (if available)
    Phase 2: Search Google Images via SerpAPI (if more images needed)

    Args:
        item: Item data dict
        out_dir: Output directory
        site_only: If True, skip SerpAPI phase
        serpapi_only: If True, skip site scraping phase
        max_pages: Max SerpAPI pages per query

    Returns:
        Result dict with item_id, name, images count
    """
    item_id = item.get("item_id")
    name = item.get("name", "")
    target = get_target_config()
    metrics = get_metrics()

    logger.info("")
    logger.info("=" * 80)
    logger.info(f"ITEM {item_id}: {name}")
    logger.info("=" * 80)

    saved = {"target": 0}
    max_targets = MAX_IMAGES_PER_ITEM
    index = HashIndex()
    item_dir = os.path.join(out_dir, "images", str(item_id))
    os.makedirs(item_dir, exist_ok=True)

    try:
        # PHASE 1: Site scraping (official or news)
        if not serpapi_only:
            site_url = item.get("website", "").strip()
            if site_url:
                phase_start = time.time()
                url_source = classify_url_source(site_url)
                is_news = url_source in ("news", "gov")

                if is_news:
                    source_label = "site_news"
                    source_type_label = "news"
                    logger.info(f'[{item_id}] Scraping NEWS site: {site_url}')
                else:
                    source_label = "official_site"
                    source_type_label = ""
                    logger.info(f'[{item_id}] Scraping official site: {site_url}')

                try:
                    image_data = extract_image_urls(site_url, max_images=30)

                    if image_data:
                        logger.info(f'[{item_id}] Site: {len(image_data)} candidates')

                        for img in image_data:
                            if saved["target"] >= max_targets:
                                break
                            img_url = img.get("url", "")
                            if img_url:
                                classify_and_save(
                                    img_url, item, item_dir, index,
                                    saved, max_targets,
                                    from_official_site=not is_news,
                                    source=source_label,
                                    source_type=source_type_label
                                )
                except Exception as e:
                    logger.warning(f'[{item_id}] Site scraping error: {type(e).__name__}: {e}')

                metrics.record_phase_time("site_scraping", time.time() - phase_start)

        # PHASE 2: SerpAPI search
        need_more = saved["target"] < MAX_IMAGES_PER_ITEM

        if not site_only and need_more:
            phase_start = time.time()
            remaining = MAX_IMAGES_PER_ITEM - saved["target"]
            logger.info(f'[{item_id}] Searching SerpAPI (need {remaining} more images)...')

            queries = build_queries(item)

            if queries:
                logger.info(f'[{item_id}] SerpAPI: {len(queries)} prioritized queries')

                for idx, (query_text, priority, desc) in enumerate(queries, 1):
                    if saved["target"] >= MAX_IMAGES_PER_ITEM:
                        logger.info(f'[{item_id}] Target reached, stopping SerpAPI')
                        break

                    logger.info(f'[{item_id}] Query {idx}/{len(queries)} (P{priority}): {query_text[:60]}...')

                    for page in range(max_pages):
                        if saved["target"] >= MAX_IMAGES_PER_ITEM:
                            break

                        try:
                            results = search_images(query_text, ijn=page, apply_delay=(page > 0))
                            if not results:
                                break

                            for result in results:
                                if saved["target"] >= MAX_IMAGES_PER_ITEM:
                                    break

                                passed, _ = prefilter_result(result, item_id)
                                if not passed:
                                    continue

                                img_url = result.get("image_url", "")
                                if img_url:
                                    classify_and_save(
                                        img_url, item, item_dir, index,
                                        saved, max_targets,
                                        from_official_site=False,
                                        source="serpapi_direct",
                                        query_used=query_text
                                    )

                        except Exception as e:
                            logger.warning(f'[{item_id}] SerpAPI error: {type(e).__name__}: {e}')

            metrics.record_phase_time("serpapi_search", time.time() - phase_start)

        # Record result
        has_images = saved["target"] > 0
        metrics.record_item_processed(has_images=has_images)

        logger.info(f'[{item_id}] DONE: {saved["target"]}/{MAX_IMAGES_PER_ITEM} {target.category} images')

        return {
            "item_id": item_id,
            "name": name,
            "images": saved["target"],
            "total": saved["target"]
        }

    except Exception as e:
        logger.error(f'[{item_id}] Error processing item: {type(e).__name__}: {e}')
        return {"item_id": item_id, "name": name, "images": 0, "total": 0, "error": str(e)}


def main():
    global CHECKPOINT

    parser = argparse.ArgumentParser(description="Targeted Image Collector")
    parser.add_argument("--input", required=True, help="Path to input data file")
    parser.add_argument("--target", default="", help="Path to target YAML config (e.g., targets/facades.yaml)")
    parser.add_argument("--out", default=OUTPUT_DIR, help="Output directory")
    parser.add_argument("--limit", type=int, default=10, help="Max items to process")
    parser.add_argument("--max-pages", type=int, default=2, help="Max SerpAPI pages per query")
    parser.add_argument("--site-only", action="store_true", help="Only scrape official sites")
    parser.add_argument("--serpapi-only", action="store_true", help="Only use SerpAPI")
    parser.add_argument("--clear-cache", action="store_true", help="Clear expired cache entries")
    parser.add_argument("--clear-checkpoint", action="store_true", help="Clear checkpoint and start fresh")
    parser.add_argument("--parallel", action="store_true", help="Process items in parallel")
    parser.add_argument("--workers", type=int, default=MAX_ITEM_WORKERS, help="Number of parallel workers")

    args = parser.parse_args()

    # Load target configuration
    target_path = args.target or TARGET_CONFIG_FILE
    target = load_target_config(target_path if target_path else None)

    # Setup
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(os.path.join(args.out, "logs"), exist_ok=True)

    logger.add(
        os.path.join(args.out, "logs", "run.log"),
        enqueue=True, backtrace=False, diagnose=False
    )

    # Initialize subsystems
    init_cache()
    if args.clear_cache:
        clear_expired_cache()
    if args.clear_checkpoint:
        clear_checkpoint()

    reset_metrics()

    # Load items
    all_items = load_items(args.input)[:args.limit]

    # Checkpoint: load and filter
    CHECKPOINT = load_checkpoint(args.input)
    items = get_pending_items(CHECKPOINT, all_items, id_field="item_id")

    if not items:
        logger.info("=" * 80)
        logger.info("ALL ITEMS ALREADY PROCESSED!")
        logger.info("=" * 80)
        print_checkpoint_summary(CHECKPOINT)
        logger.info("Use --clear-checkpoint to start fresh")
        return

    logger.info("=" * 80)
    logger.info(f"TARGETED IMAGE COLLECTOR - {target.name}")
    logger.info("=" * 80)
    logger.info(f"   Target: {target.description}")
    logger.info(f"   Category: {target.category}")
    logger.info(f"   Total items: {len(all_items)}")
    logger.info(f"   Pending: {len(items)}")
    logger.info(f"   Already processed: {len(all_items) - len(items)}")
    logger.info(f"   Images per item: {MAX_IMAGES_PER_ITEM}")
    logger.info(f"   Parallel: {'ON' if args.parallel else 'OFF'}")
    if args.parallel:
        logger.info(f"   Workers: {args.workers}")
    logger.info("=" * 80)

    summary = []

    if args.parallel and len(items) > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_item = {
                executor.submit(
                    process_item, item, args.out, args.site_only, args.serpapi_only, args.max_pages
                ): item for item in items
            }

            for future in tqdm(as_completed(future_to_item), total=len(items), desc="Items"):
                try:
                    result = future.result()
                    summary.append(result)
                    mark_item_processed(CHECKPOINT, result["item_id"], result.get("images", 0))
                except Exception as e:
                    logger.error(f"Parallel processing error: {type(e).__name__}: {e}")
    else:
        for item in tqdm(items, desc="Processing"):
            result = process_item(item, args.out, args.site_only, args.serpapi_only, args.max_pages)
            summary.append(result)
            mark_item_processed(CHECKPOINT, result["item_id"], result.get("images", 0))

    # Final report
    logger.info("")
    logger.info("=" * 80)
    logger.info("PROCESSING COMPLETE")
    logger.info("=" * 80)

    total_images = sum(s["images"] for s in summary)
    logger.info(f"Items processed: {len(summary)}")
    logger.info(f"Total images: {total_images}")

    print_checkpoint_summary(CHECKPOINT)
    print_cache_stats()

    metrics = get_metrics()
    metrics.print_summary()
    metrics.save_to_file()

    logger.info("")
    logger.info("=" * 80)
    logger.info("IMAGE COLLECTOR FINISHED!")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
