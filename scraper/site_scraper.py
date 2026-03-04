"""
HTML image extraction engine for websites.

Multi-method extraction supporting modern web patterns:
- Standard <img> tags with lazy-loading attributes (data-src, data-lazy-src, etc.)
- <picture> and <source> elements with srcset parsing
- CSS background images (inline styles and data-bg attributes)
- Gallery link discovery and follow-through
- Intelligent thumbnail filtering

Features:
- Polite delays between requests
- URL normalization (protocol, path cleanup)
- Realistic browser headers
- Smart thumbnail detection (context-aware, not just name-based)
- Configurable gallery keywords via target config
"""

import requests
import time
import random
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
from loguru import logger
from typing import List, Dict, Optional

from target_config import get_target_config

TIMEOUT = 15
MAX_RETRIES = 2

REALISTIC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}


def normalize_url(url: str) -> str:
    """
    Normalize URL preserving www if present.

    Ensures https:// protocol and cleans up double slashes in path.

    Args:
        url: URL to normalize

    Returns:
        Normalized URL string
    """
    if not url:
        return url

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        parsed = urlparse(url)
        path = parsed.path.replace('//', '/')

        return urlunparse((
            parsed.scheme or 'https',
            parsed.netloc,
            path,
            parsed.params,
            parsed.query,
            parsed.fragment
        ))
    except Exception as e:
        logger.warning(f"Error normalizing URL {url}: {e}")
        return url


def _polite_delay():
    """Wait 2-3 seconds between requests to be polite to servers."""
    delay = random.uniform(2.0, 3.0)
    time.sleep(delay)


def is_valid_image_url(url: str) -> bool:
    """
    Check if a URL likely points to a valid image.

    Accepts known image extensions and CDN patterns.
    Rejects SVGs, tracking pixels, spacers, and other non-photo content.
    """
    if not url:
        return False

    url_lower = url.lower()

    image_extensions = ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif']
    cdn_patterns = ['cloudinary', 'imgix', 'cloudfront', 'akamai', 'fastly', 'cdn', 'media', 'image', 'foto', 'photo']

    has_extension = any(ext in url_lower for ext in image_extensions)
    is_cdn = any(pattern in url_lower for pattern in cdn_patterns)

    reject_patterns = [
        'data:image/svg', '.svg', 'blank.gif', 'pixel.gif',
        'spacer.', '/emoji/', 'gravatar.com',
    ]

    if any(pattern in url_lower for pattern in reject_patterns):
        return False

    return has_extension or is_cdn or '/upload' in url_lower


def is_likely_thumbnail(url: str, width: Optional[str], height: Optional[str]) -> bool:
    """
    Intelligently detect thumbnail images.

    Unlike naive approaches that reject anything with "thumb" in the name,
    this checks context: HTML dimensions, URL size patterns, and definitive
    thumbnail indicators (icons, logos, sprites, etc.).

    Args:
        url: Image URL
        width: HTML width attribute (may be None)
        height: HTML height attribute (may be None)

    Returns:
        True if the image is likely a thumbnail
    """
    url_lower = url.lower()

    definite_thumbnails = [
        'icon', 'logo', 'sprite', 'favicon', 'avatar',
        'btn_', 'button_', '_ico.', '_icon.',
        '16x16', '32x32', '48x48', '64x64',
        '/icons/', '/logos/', '/buttons/',
    ]

    if any(pattern in url_lower for pattern in definite_thumbnails):
        return True

    if width and height:
        try:
            w = int(str(width).replace('px', ''))
            h = int(str(height).replace('px', ''))
            if w < 100 or h < 100:
                return True
        except (ValueError, TypeError):
            pass

    if 'thumb' in url_lower:
        size_pattern = re.search(r'thumb[_-]?(\d+)', url_lower)
        if size_pattern:
            size = int(size_pattern.group(1))
            if size < 200:
                return True

    return False


def extract_url_from_srcset(srcset: str) -> Optional[str]:
    """Extract the largest image URL from a srcset attribute."""
    if not srcset:
        return None

    parts = srcset.split(',')
    best_url = None
    best_size = 0

    for part in parts:
        part = part.strip()
        if not part:
            continue

        tokens = part.split()
        if not tokens:
            continue

        url = tokens[0]
        size = 0

        if len(tokens) > 1:
            match = re.search(r'(\d+)', tokens[1])
            if match:
                size = int(match.group(1))
                if 'x' in tokens[1]:
                    size *= 100

        if size > best_size or best_url is None:
            best_size = size
            best_url = url

    return best_url


def extract_url_from_style(style: str) -> Optional[str]:
    """Extract image URL from CSS background-image style attribute."""
    if not style:
        return None

    patterns = [
        r'background-image\s*:\s*url\([\'"]?([^\'")\s]+)[\'"]?\)',
        r'background\s*:[^;]*url\([\'"]?([^\'")\s]+)[\'"]?\)',
    ]

    for pattern in patterns:
        match = re.search(pattern, style, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def extract_images_from_page(page_url: str, max_images: int = 20,
                             apply_delay: bool = True) -> List[Dict]:
    """
    Extract all images from a web page using multiple methods.

    Methods used:
    1. <img> tags with multiple src attributes (src, data-src, srcset, etc.)
    2. <picture> and <source> elements
    3. CSS background images from inline styles and data attributes
    4. Direct image links from anchor tags (gallery patterns)

    Args:
        page_url: URL of the page to scrape
        max_images: Maximum number of images to extract
        apply_delay: If True, applies polite delay before request

    Returns:
        List of dicts with url, alt, and source metadata
    """
    images = []
    urls_seen = set()

    page_url = normalize_url(page_url)

    try:
        if apply_delay:
            _polite_delay()

        resp = requests.get(page_url, timeout=TIMEOUT, headers=REALISTIC_HEADERS, allow_redirects=True)
        resp.raise_for_status()

    except requests.exceptions.HTTPError as e:
        logger.warning(f"HTTP error accessing {page_url}: {e}")
        return images
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout accessing {page_url}")
        return images
    except Exception as e:
        logger.warning(f"Error accessing {page_url}: {e}")
        return images

    soup = BeautifulSoup(resp.text, "html.parser")

    def add_image(img_url: str, alt: str = "", source_type: str = "img"):
        if len(images) >= max_images or not img_url or img_url in urls_seen:
            return False

        img_url = urljoin(page_url, img_url)
        if not is_valid_image_url(img_url) or img_url in urls_seen:
            return False

        urls_seen.add(img_url)
        images.append({"url": img_url, "alt": alt, "source": f"page_extraction_{source_type}"})
        return True

    # Method 1: <img> tags
    for img_tag in soup.find_all("img"):
        if len(images) >= max_images:
            break

        width = img_tag.get("width")
        height = img_tag.get("height")
        alt = img_tag.get("alt", "")

        img_attrs = ["src", "data-src", "data-lazy-src", "data-original",
                     "data-lazy", "data-image", "data-full", "data-zoom-image"]

        img_url = None
        for attr in img_attrs:
            img_url = img_tag.get(attr)
            if img_url and not img_url.startswith('data:'):
                break

        srcset = img_tag.get("srcset") or img_tag.get("data-srcset")
        if srcset:
            srcset_url = extract_url_from_srcset(srcset)
            if srcset_url:
                img_url = srcset_url

        if not img_url:
            continue

        if is_likely_thumbnail(img_url, width, height):
            continue

        add_image(img_url, alt, "img")

    # Method 2: <picture> and <source>
    for picture_tag in soup.find_all("picture"):
        if len(images) >= max_images:
            break

        best_url = None
        for source_tag in picture_tag.find_all("source"):
            srcset = source_tag.get("srcset")
            if srcset:
                url = extract_url_from_srcset(srcset)
                if url:
                    best_url = url
                    break

        if not best_url:
            img_tag = picture_tag.find("img")
            if img_tag:
                best_url = img_tag.get("src") or img_tag.get("data-src")

        if best_url:
            add_image(best_url, "", "picture")

    # Method 3: CSS backgrounds
    bg_attrs = ["data-bg", "data-background", "data-image-src", "data-src"]

    for elem in soup.find_all(["div", "section", "figure", "a"], limit=100):
        if len(images) >= max_images:
            break

        for attr in bg_attrs:
            bg_url = elem.get(attr)
            if bg_url and not bg_url.startswith('data:'):
                add_image(bg_url, "", "data_bg")
                break

        style = elem.get("style")
        if style:
            bg_url = extract_url_from_style(style)
            if bg_url:
                add_image(bg_url, "", "css_bg")

    # Method 4: Gallery links
    for a_tag in soup.find_all("a", href=True):
        if len(images) >= max_images:
            break

        href = a_tag.get("href", "")
        if any(ext in href.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
            if not is_likely_thumbnail(href, None, None):
                add_image(href, "", "gallery_link")

    logger.debug(f"Extracted {len(images)} images from {page_url}")
    return images


def find_gallery_links(page_url: str) -> Dict[str, List[str]]:
    """
    Discover gallery/section links on a page.

    Searches for links containing gallery-related keywords and classifies
    them by content type (target-specific galleries vs general galleries).
    Gallery keywords are loaded from the target configuration.

    Args:
        page_url: URL of the main page

    Returns:
        Dict with lists of gallery URLs by type
    """
    page_url = normalize_url(page_url)
    target = get_target_config()

    galleries = {"target": [], "general": []}

    try:
        _polite_delay()
        resp = requests.get(page_url, timeout=TIMEOUT, headers=REALISTIC_HEADERS, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Failed to fetch galleries from {page_url}: {e}")
        return galleries

    soup = BeautifulSoup(resp.text, "html.parser")

    gallery_elements = soup.find_all(["a"], href=True, limit=100)

    for elem in gallery_elements:
        href = elem.get("href", "")
        elem_class = " ".join(elem.get("class", []))
        text = elem.get_text().lower()
        combined = f"{href} {elem_class} {text}".lower()

        full_url = urljoin(page_url, href)

        # Check target-specific gallery keywords
        if any(w in combined for w in target.gallery_keywords):
            if full_url not in galleries["target"]:
                galleries["target"].append(full_url)

        elif any(w in combined for w in ["galeria", "gallery", "fotos", "photos", "imagens", "images"]):
            if full_url not in galleries["general"] and full_url not in galleries["target"]:
                galleries["general"].append(full_url)

    return galleries


def extract_image_urls(page_url: str, max_images: int = 30) -> List[Dict]:
    """
    Main entry point: extract images from an item's website.

    Strategy:
    1. Discover gallery links (target-specific, general)
    2. Extract images from each discovered gallery
    3. If few images found, extract from the main page as fallback

    Args:
        page_url: URL of the item's website
        max_images: Maximum images to extract

    Returns:
        List of image data dicts
    """
    all_images = []
    urls_seen = set()

    page_url = normalize_url(page_url)
    logger.info(f"Starting site scraping: {page_url}")

    galleries = find_gallery_links(page_url)

    # Extract from target-specific galleries first
    for gallery_url in galleries.get("target", [])[:2]:
        if len(all_images) >= max_images:
            break
        for img in extract_images_from_page(gallery_url, max_images=20, apply_delay=True):
            if img["url"] not in urls_seen:
                urls_seen.add(img["url"])
                all_images.append(img)

    # Extract from general galleries
    for gallery_url in galleries.get("general", [])[:1]:
        if len(all_images) >= max_images:
            break
        for img in extract_images_from_page(gallery_url, max_images=20, apply_delay=True):
            if img["url"] not in urls_seen:
                urls_seen.add(img["url"])
                all_images.append(img)

    # Fallback: extract from main page if few images found
    if len(all_images) < 5:
        logger.info(f"Few gallery images ({len(all_images)}), extracting from main page")
        for img in extract_images_from_page(page_url, max_images=20, apply_delay=False):
            if len(all_images) >= max_images:
                break
            if img["url"] not in urls_seen:
                urls_seen.add(img["url"])
                all_images.append(img)

    logger.info(f"Total images extracted: {len(all_images)}")
    return all_images[:max_images]
