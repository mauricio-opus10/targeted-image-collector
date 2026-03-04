# Architecture Documentation

## System Overview

The Targeted Image Collector is a multi-stage pipeline that collects, validates, and deduplicates images from the web based on configurable target definitions. It's designed for multi-site scraping — each item has its own unique website — with cost optimization and resilience built in.

## Core Concept: Multi-site Scraping

Unlike traditional web scrapers that target a single site with fixed selectors, this pipeline operates across hundreds of different websites. Each item in the input list may have a completely different website with unique HTML structures. This requires:

- Multiple extraction methods instead of site-specific selectors
- AI-based validation instead of position-based rules
- Heuristic pre-filtering to keep costs manageable
- Source classification to adapt behavior per site type

## Target Configuration

The system is parameterized by a YAML target config that defines:

```yaml
name: "Category Name"       # Human-readable name
category: "slug"             # Internal category identifier
description: "what to find"  # Used in Vision API prompts

positive_keywords: [...]     # Heuristic: keywords indicating target images
negative_keywords: [...]     # Heuristic: keywords indicating non-target images
url_patterns: [...]          # Heuristic: URL regex patterns
search_keywords: [...]       # Query builder: augment search queries
gallery_keywords: [...]      # Site scraper: gallery link discovery

vision:
  system_message: "..."             # Vision API system prompt
  target_description: "..."         # What the target image looks like
  exclusion_description: "..."      # What to reject
  extra_rules: [...]                # Additional classification rules
```

All modules read from this config at runtime via `get_target_config()`, making the pipeline fully reusable across different image categories.

## Pipeline Flow

```
Input (items list)
    │
    ├── Load Target Config (YAML)
    │
    ├── Phase 1: Site Scraping
    │   ├── URL Source Classification (official/news/social/gov)
    │   ├── Gallery Discovery (link analysis with target keywords)
    │   ├── Multi-Method Image Extraction
    │   │   ├── <img> tags (src, data-src, data-lazy-src, etc.)
    │   │   ├── <picture> + <source> with srcset parsing
    │   │   ├── CSS background-image (inline + data-bg)
    │   │   └── Gallery link follow-through
    │   └── Intelligent Thumbnail Filtering
    │
    ├── Phase 2: SerpAPI Search
    │   ├── Query Builder (5 priority tiers, target-aware)
    │   ├── Empty Query Cache (skip known-empty queries)
    │   ├── Result Normalization
    │   └── Pre-Filters (dimensions, product flag)
    │
    └── 7-Filter Validation Pipeline (per image)
        ├── Filter 0:   URL Validation (item name in URL)
        ├── Filter 0.5: Blocked Domains (social media CDNs)
        ├── Filter 1:   AI Classification
        │   ├── Heuristic (text-based, free, uses target keywords)
        │   ├── Cache Lookup (free)
        │   └── OpenAI Vision API (paid, last resort, dynamic prompt)
        ├── Filter 2:   Correct Item Verification
        ├── Filter 2.5: Confidence Threshold
        ├── Filter 3:   Category Filter (target category)
        ├── Filter 4:   Per-Item Image Limit
        ├── Filter 5:   Image Download (retry + backoff)
        ├── Filter 6:   Dimension Check (min 400x400)
        └── Filter 7:   Perceptual Hash Deduplication
```

## Module Responsibilities

### `target_config.py` - Target Definition
- Defines `TargetConfig` dataclass with all configurable fields
- Loads from YAML files with `from_yaml()` classmethod
- Provides sensible defaults via `default()` (building facades)
- Global singleton pattern via `load_target_config()` / `get_target_config()`

### `main.py` - Pipeline Orchestrator
- Coordinates the two-phase pipeline
- Manages parallel processing (ThreadPoolExecutor)
- Implements the 7-filter validation chain
- Handles checkpoint/resume logic
- Loads target config from `--target` CLI argument

### `scraper/site_scraper.py` - HTML Image Extraction
- Multi-method extraction engine
- Handles modern web patterns (lazy loading, srcset, CSS backgrounds)
- Gallery discovery using target-specific keywords
- Smart thumbnail detection (context-aware: dimensions, URL patterns, not just name)

### `scraper/serpapi_client.py` - Google Images Client
- SerpAPI SDK wrapper with result normalization
- Empty query cache (persistent, 7-day TTL)
- Pre-filters using SerpAPI metadata (dimensions, product flag)
- Blocked domain list (social media CDNs that break Vision API)

### `scraper/query_builder.py` - Query Generation
- 5-tier priority system based on empirical analysis
- Tier 1: Broad queries (name + city) — highest coverage
- Tier 2: Context queries (target-specific keywords from config)
- Tier 3: Official site scoped
- Tier 4: Organization + item
- Tier 5: Type-specific + fallback
- Query deduplication

### `classifier/vision_validator.py` - AI Classification
- Three-stage classification: heuristic → cache → OpenAI Vision
- Dynamic prompt construction from target config
- Differentiated prompts by source type (official site vs news article)
- Batch classification with parallel workers
- Safe error handling with fallback results

### `classifier/url_classifier.py` - URL Analysis
- Item name detection in URL paths
- Homonym detection (other items with similar names in URL)
- CDN/generic URL identification
- Source type classification (official, news, social, gov)

### `classifier/heuristics.py` - Text-Based Classification
- Bilingual keyword matching loaded from target config
- URL pattern analysis using target-specific regex
- Exclusion keyword detection
- Saves ~40% on Vision API costs

### `core/cache.py` - Classification Cache
- File-based JSON cache (one file per classification)
- Configurable TTL (default: 30 days)
- Uses MD5 hash of item_id + URL as key
- Efficient cleanup using file mtime as age proxy

### `core/checkpoint.py` - Progress Tracking
- JSON-based persistent progress
- Input file hash for change detection (auto-restart on new input)
- Automatic resume on restart
- Per-item tracking

### `core/dedup.py` - Image Deduplication
- Perceptual hashing (pHash) via imagehash library
- SQLite persistence across runs
- Configurable Hamming distance threshold (default: 6)
- Per-item scoped deduplication
- Thread-safe for parallel processing

### `core/downloader.py` - Image Download
- Automatic retry with exponential backoff
- Polite delays between requests
- Image resizing and JPEG optimization
- Parallel batch downloads

### `core/metrics.py` - Performance Monitoring
- Real-time tracking of API calls, cache hits, downloads, rejections
- Cost estimation (OpenAI Vision ~$0.01/image)
- Composite efficiency score
- JSON export for post-run analysis

## Design Decisions

### Why Configurable Targets?
Different use cases need different image types (facades, products, vehicles). Instead of hardcoding what to look for, the YAML target system externalizes all category-specific logic: keywords, prompts, search terms. This makes the pipeline reusable without code changes.

### Why Heuristics Before Vision API?
The Vision API costs ~$0.01 per image. By pre-filtering with text-based heuristics (URL patterns, alt text, titles), we reject ~40% of images before they reach the API. The heuristic catches obvious non-targets with high confidence using keywords from the target config.

### Why Multi-Method Extraction?
Since the pipeline scrapes hundreds of different websites, no single extraction method covers all cases. Modern sites use lazy loading (`data-src`), responsive images (`srcset`), CSS backgrounds, and `<picture>` elements. The multi-method approach maximizes coverage across diverse site architectures.

### Why 30-Day Cache?
Images at stable URLs change infrequently. A 30-day cache window captures repeat runs and avoids re-classifying the same images. The file-based approach (one JSON per entry) makes cleanup trivial and avoids database overhead.

### Why Differentiated Prompts by Source?
Images from official sites have different characteristics than those from news articles. Official site images are likely to be the correct item, so the prompt focuses on category classification. News article images could be anything (journalist photos, other items, ads), so the prompt emphasizes both category AND item verification.

### Why pHash over Exact Hash?
Exact hash comparison (MD5/SHA) only catches identical images. Perceptual hashing catches visually similar images even with different resolutions, compression levels, or minor edits. The Hamming distance threshold of 6 (out of 64 bits) provides a good balance between catching duplicates and avoiding false positives.

### Why SQLite for Deduplication?
In-memory deduplication loses data between runs, causing re-downloads. SQLite provides persistence with zero infrastructure requirements. It's also thread-safe, supporting parallel processing without external locking.

### Why 5-Tier Query System?
Empirical analysis of search logs showed that broad queries (name + city) consistently find more images than specific ones (site:domain.com). However, specific queries have higher accuracy. The tier system processes broad queries first for coverage, then falls back to specific queries when needed.

### Why Pre-Filter SerpAPI Results?
SerpAPI returns metadata including image dimensions and product flags. Filtering small images and irrelevant results BEFORE downloading saves bandwidth and Vision API costs. This catches ~15-20% of results that would be rejected later anyway.

## Cost Model

| Operation | Cost | Optimization |
|-----------|------|-------------|
| SerpAPI query | ~$0.005 | Empty query cache (-30% calls) |
| OpenAI Vision | ~$0.01/image | Heuristics + cache (-40% calls) |
| Image download | Free (bandwidth) | Pre-filters + dedup (-25% downloads) |

Typical cost per item: $0.05 - $0.15 (depending on cache hit rate and target complexity)
