"""
Image download module with parallel support and automatic retry.

Features:
- Polite delays between requests to avoid rate limiting
- Automatic retry with exponential backoff
- Image resizing and JPEG optimization on save
- Parallel batch downloads via ThreadPoolExecutor
"""

import requests
import time
import random
from PIL import Image
from io import BytesIO
from typing import Optional
from loguru import logger
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from functools import wraps

from config import (
    REALISTIC_HEADERS,
    TIMEOUT,
    DELAY_BETWEEN_REQUESTS,
    DELAY_JITTER,
    MAX_WIDTH,
    MAX_HEIGHT,
    JPEG_QUALITY,
    MAX_DOWNLOAD_WORKERS
)
from core.metrics import get_metrics


def _retry_on_failure(max_retries: int = 3):
    """Decorator for automatic retry with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (requests.Timeout, requests.ConnectionError) as e:
                    last_error = e
                    if attempt < max_retries:
                        delay = 1.5 * (2 ** (attempt - 1))
                        logger.warning(f"Attempt {attempt}/{max_retries} failed: {e}. Retrying in {delay:.1f}s...")
                        time.sleep(delay)
                except requests.HTTPError as e:
                    logger.debug(f"HTTP error downloading {args[0][:60] if args else 'unknown'}: {e}")
                    return None
                except Exception as e:
                    logger.debug(f"Error processing image: {type(e).__name__}")
                    return None
            logger.error(f"All {max_retries} attempts failed for {func.__name__}")
            return None
        return wrapper
    return decorator


def _apply_polite_delay():
    """Apply a polite delay between requests to avoid overloading servers."""
    jitter = random.uniform(0, DELAY_JITTER)
    delay = DELAY_BETWEEN_REQUESTS + jitter
    time.sleep(delay)


@_retry_on_failure(max_retries=3)
def download_image(url: str, apply_delay: bool = True) -> Optional[Image.Image]:
    """
    Download an image from a URL.

    Args:
        url: Image URL
        apply_delay: If True, applies polite delay before downloading

    Returns:
        PIL Image object or None on failure
    """
    metrics = get_metrics()
    metrics.record_download_attempt()

    if apply_delay:
        _apply_polite_delay()

    response = requests.get(
        url,
        headers=REALISTIC_HEADERS,
        timeout=TIMEOUT,
        stream=True
    )
    response.raise_for_status()

    img_data = BytesIO(response.content)
    img = Image.open(img_data)

    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')

    metrics.record_download_success()
    return img


def save_image(img: Image.Image, filepath: str) -> str:
    """
    Save image to disk with optimization.

    Resizes if larger than configured maximum dimensions and saves as
    optimized JPEG.

    Args:
        img: PIL Image object
        filepath: Full output path

    Returns:
        String with final dimensions (e.g., "800x600")
    """
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    if img.width > MAX_WIDTH or img.height > MAX_HEIGHT:
        img.thumbnail((MAX_WIDTH, MAX_HEIGHT), Image.Resampling.LANCZOS)
        logger.debug(f"Image resized to {img.width}x{img.height}")

    img.save(filepath, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return f"{img.width}x{img.height}"


def download_images_parallel(
    urls: list[str],
    max_workers: Optional[int] = None
) -> dict[str, Optional[Image.Image]]:
    """
    Download multiple images in parallel.

    Args:
        urls: List of image URLs
        max_workers: Number of concurrent workers

    Returns:
        Dict mapping URL to Image (or None on failure)
    """
    max_workers = max_workers or MAX_DOWNLOAD_WORKERS
    results = {}

    logger.info(f"Downloading {len(urls)} images in parallel ({max_workers} workers)...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {
            executor.submit(download_image, url, apply_delay=False): url
            for url in urls
        }

        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                results[url] = future.result()
            except Exception as e:
                logger.warning(f"Parallel download error for {url[:50]}: {e}")
                results[url] = None

    successful = sum(1 for img in results.values() if img is not None)
    logger.info(f"Downloads complete: {successful}/{len(urls)} successful")

    return results
