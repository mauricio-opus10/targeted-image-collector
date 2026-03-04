"""
Centralized configuration for the Targeted Image Collector.

All settings are configurable via environment variables with sensible defaults.
Target-specific settings (keywords, prompts, categories) are loaded from
YAML config files — see target_config.py and targets/ directory.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# API KEYS
# ============================================================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "")
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")

# ============================================================================
# TARGET CONFIGURATION
# ============================================================================
# Path to YAML target config (e.g., "targets/facades.yaml")
# If not set, uses built-in default (building facades)
TARGET_CONFIG_FILE = os.getenv("TARGET_CONFIG", "")

# ============================================================================
# DIRECTORIES
# ============================================================================
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
CACHE_DIR = os.path.join(OUTPUT_DIR, "cache")
DEDUP_DB_PATH = os.path.join(OUTPUT_DIR, "dedup.db")

# ============================================================================
# IMAGE LIMITS PER ITEM
# ============================================================================
MAX_IMAGES_PER_ITEM = int(os.getenv("MAX_IMAGES_PER_ITEM", "3"))
MIN_DESIRED_IMAGES = int(os.getenv("MIN_DESIRED_IMAGES", "3"))

# ============================================================================
# IMAGE QUALITY
# ============================================================================
MIN_WIDTH = int(os.getenv("MIN_WIDTH", "400"))
MIN_HEIGHT = int(os.getenv("MIN_HEIGHT", "400"))
MAX_WIDTH = int(os.getenv("MAX_WIDTH", "1000"))
MAX_HEIGHT = int(os.getenv("MAX_HEIGHT", "1000"))
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "90"))

# ============================================================================
# FILE NAMING
# ============================================================================
FILENAME_PATTERN = "{item_id}_{category}_{number:02d}.jpg"

# Source identifier for page exploration results
SOURCE_PROMISING_PAGE = "promising_page"

# ============================================================================
# NETWORK & TIMEOUTS
# ============================================================================
TIMEOUT = int(os.getenv("TIMEOUT", "20"))
RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", "3"))
RETRY_WAIT = float(os.getenv("RETRY_WAIT", "1.5"))

DELAY_BETWEEN_REQUESTS = float(os.getenv("DELAY_BETWEEN_REQUESTS", "2.0"))
DELAY_JITTER = float(os.getenv("DELAY_JITTER", "1.0"))

REALISTIC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0"
}

# ============================================================================
# PARALLELIZATION
# ============================================================================
MAX_DOWNLOAD_WORKERS = int(os.getenv("MAX_DOWNLOAD_WORKERS", "5"))
MAX_CLASSIFICATION_WORKERS = int(os.getenv("MAX_CLASSIFICATION_WORKERS", "3"))
MAX_ITEM_WORKERS = int(os.getenv("MAX_ITEM_WORKERS", "2"))
CLASSIFICATION_BATCH_SIZE = int(os.getenv("CLASSIFICATION_BATCH_SIZE", "5"))

# ============================================================================
# SITE SCRAPING
# ============================================================================
PRIORITIZE_SITE_SCRAPING = True
SITE_SCRAPING_MAX_IMAGES = 50

# ============================================================================
# HEURISTIC CLASSIFICATION (cost optimization)
# ============================================================================
USE_HEURISTIC = True
HEURISTIC_MIN_CONFIDENCE = float(os.getenv("HEURISTIC_MIN_CONFIDENCE", "0.85"))
ALWAYS_VALIDATE_ITEM = True

# ============================================================================
# MINIMUM CONFIDENCE THRESHOLD
# ============================================================================
# Images below this confidence are rejected
# Based on validation analysis: confidence < 85% has ~13% accuracy
MIN_CONFIDENCE_THRESHOLD = float(os.getenv("MIN_CONFIDENCE_THRESHOLD", "0.85"))

# Reduced threshold for news site images (more ambiguous context)
MIN_CONFIDENCE_THRESHOLD_NEWS = float(os.getenv("MIN_CONFIDENCE_THRESHOLD_NEWS", "0.85"))

# ============================================================================
# CACHE
# ============================================================================
ENABLE_CACHE = True
CACHE_EXPIRY_DAYS = 30

# ============================================================================
# PAGE EXPLORATION
# ============================================================================
MAX_PROMISING_PAGES_TOTAL = int(os.getenv("MAX_PROMISING_PAGES", "15"))
MAX_IMAGES_PER_PROMISING_PAGE = int(os.getenv("MAX_IMAGES_PER_PAGE", "15"))

# ============================================================================
# SERPAPI SETTINGS
# ============================================================================
SERPAPI_DEFAULT_TBS = "itp:photos,isz:l"
SERPAPI_GL = "br"
SERPAPI_HL = "pt"
SERPAPI_MAX_PAGES = int(os.getenv("SERPAPI_MAX_PAGES", "2"))

# Pre-filters: reject small images and product images before downloading
SERPAPI_MIN_WIDTH = int(os.getenv("SERPAPI_MIN_WIDTH", "400"))
SERPAPI_MIN_HEIGHT = int(os.getenv("SERPAPI_MIN_HEIGHT", "400"))
SERPAPI_FILTER_PRODUCTS = os.getenv("SERPAPI_FILTER_PRODUCTS", "true").lower() == "true"

# ============================================================================
# METRICS
# ============================================================================
ENABLE_METRICS = True
METRICS_OUTPUT_FILE = os.path.join(OUTPUT_DIR, "metrics.json")

# ============================================================================
# VERSION
# ============================================================================
VERSION = "2.0.0"
