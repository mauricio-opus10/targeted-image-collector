"""
Performance and cost monitoring system.

Tracks detailed metrics across the entire pipeline:
- API calls and costs (OpenAI Vision, SerpAPI)
- Cache efficiency (hit/miss rates)
- Download success rates
- Rejection reasons breakdown
- Per-phase timing
- Overall efficiency scoring
"""

import json
import time
from typing import Dict, Optional
from datetime import datetime
from pathlib import Path
from loguru import logger
from config import METRICS_OUTPUT_FILE, ENABLE_METRICS


class Metrics:
    """
    Tracks performance, cost, and quality metrics for the scraping pipeline.

    Provides real-time monitoring of:
    - OpenAI API usage and estimated cost
    - Cache hit rates
    - Download success rates
    - Image rejection reasons
    - Processing time per phase
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset all metric counters."""
        self.start_time = time.time()

        self.openai_calls = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.heuristic_hits = 0

        self.downloads_attempted = 0
        self.downloads_successful = 0
        self.downloads_failed = 0

        self.images_saved = {"target": 0, "total": 0}

        self.images_by_source = {
            "official_site": 0,
            "serpapi_direct": 0,
            "page_exploration": 0
        }

        self.rejections = {
            "url_validation": 0,
            "wrong_item": 0,
            "wrong_category": 0,
            "low_confidence": 0,
            "dimensions": 0,
            "duplicate": 0,
            "download_failed": 0,
            "limit_reached": 0,
            "blocked_social_media": 0
        }

        self.errors = {
            "timeout": 0,
            "http_404": 0,
            "http_500": 0,
            "connection": 0,
            "other": 0
        }

        self.phase_times = {
            "site_scraping": 0.0,
            "serpapi_search": 0.0,
            "classification": 0.0,
            "download": 0.0
        }

        self.items_processed = 0
        self.items_with_images = 0

    # === Recording methods ===

    def record_openai_call(self):
        self.openai_calls += 1
        self.cache_misses += 1

    def record_cache_hit(self):
        self.cache_hits += 1

    def record_heuristic_hit(self):
        self.heuristic_hits += 1

    def record_download_attempt(self):
        self.downloads_attempted += 1

    def record_download_success(self):
        self.downloads_successful += 1

    def record_download_failure(self):
        self.downloads_failed += 1

    def record_image_saved(self, category: str, source: str):
        """Record a saved image by category and source."""
        self.images_saved["target"] += 1
        self.images_saved["total"] += 1
        if source in self.images_by_source:
            self.images_by_source[source] += 1

    def record_rejection(self, reason: str):
        """Record an image rejection with its reason."""
        if reason in self.rejections:
            self.rejections[reason] += 1

    def record_error(self, error_type: str):
        """Record an error by type."""
        if error_type in self.errors:
            self.errors[error_type] += 1
        else:
            self.errors["other"] += 1

    def record_phase_time(self, phase: str, duration: float):
        """Record time spent in a processing phase."""
        if phase in self.phase_times:
            self.phase_times[phase] += duration

    def record_item_processed(self, has_images: bool = True):
        """Record a processed item."""
        self.items_processed += 1
        if has_images:
            self.items_with_images += 1

    # === Computed statistics ===

    def get_total_cost(self) -> float:
        """Estimated total cost in USD (OpenAI Vision ~$0.01/image)."""
        return self.openai_calls * 0.01

    def get_cache_hit_rate(self) -> float:
        """Cache hit rate as percentage."""
        total = self.cache_hits + self.cache_misses
        return (self.cache_hits / total * 100) if total > 0 else 0.0

    def get_download_success_rate(self) -> float:
        """Download success rate as percentage."""
        total = self.downloads_attempted
        return (self.downloads_successful / total * 100) if total > 0 else 0.0

    def get_avg_images_per_item(self) -> float:
        """Average images saved per processed item."""
        return (self.images_saved["total"] / self.items_processed) if self.items_processed > 0 else 0.0

    def get_total_runtime(self) -> float:
        """Total runtime in seconds."""
        return time.time() - self.start_time

    def get_efficiency_score(self) -> float:
        """
        Composite efficiency score (0-100).

        Weighted average of:
        - Cache hit rate (40%)
        - Download success rate (30%)
        - Images per item vs target (30%)
        """
        cache_score = self.get_cache_hit_rate() * 0.4
        download_score = self.get_download_success_rate() * 0.3
        avg_images = self.get_avg_images_per_item()
        image_score = min(100, (avg_images / 3.0) * 100) * 0.3
        return cache_score + download_score + image_score

    # === Export ===

    def to_dict(self) -> Dict:
        """Export all metrics as a dictionary."""
        return {
            "timestamp": datetime.now().isoformat(),
            "runtime_seconds": self.get_total_runtime(),
            "items": {
                "processed": self.items_processed,
                "with_images": self.items_with_images,
                "success_rate": (self.items_with_images / self.items_processed * 100) if self.items_processed > 0 else 0
            },
            "images": {
                "total": self.images_saved["total"],
                "target": self.images_saved["target"],
                "avg_per_item": self.get_avg_images_per_item(),
                "by_source": self.images_by_source
            },
            "classification": {
                "openai_calls": self.openai_calls,
                "cache_hits": self.cache_hits,
                "heuristic_hits": self.heuristic_hits,
                "cache_hit_rate": self.get_cache_hit_rate(),
                "total_cost_usd": self.get_total_cost()
            },
            "downloads": {
                "attempted": self.downloads_attempted,
                "successful": self.downloads_successful,
                "failed": self.downloads_failed,
                "success_rate": self.get_download_success_rate()
            },
            "rejections": self.rejections,
            "errors": self.errors,
            "performance": {
                "phase_times": self.phase_times,
                "efficiency_score": self.get_efficiency_score()
            }
        }

    def save_to_file(self, filepath: Optional[str] = None):
        """Save metrics to a JSON file."""
        if not ENABLE_METRICS:
            return

        filepath = filepath or METRICS_OUTPUT_FILE
        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info(f"Metrics saved to: {filepath}")
        except Exception as e:
            logger.warning(f"Error saving metrics: {e}")

    def print_summary(self):
        """Print a human-readable metrics summary."""
        runtime = self.get_total_runtime()

        logger.info("")
        logger.info("=" * 80)
        logger.info("METRICS SUMMARY")
        logger.info("=" * 80)

        logger.info("")
        logger.info("ITEMS:")
        logger.info(f"  Processed: {self.items_processed}")
        logger.info(f"  With images: {self.items_with_images}")
        if self.items_processed > 0:
            logger.info(f"  Success rate: {self.items_with_images / self.items_processed * 100:.1f}%")

        logger.info("")
        logger.info("IMAGES:")
        logger.info(f"  Total saved: {self.images_saved['total']}")
        logger.info(f"  Target matches: {self.images_saved['target']}")
        logger.info(f"  Avg per item: {self.get_avg_images_per_item():.1f}")

        logger.info("")
        logger.info("CLASSIFICATION & COST:")
        logger.info(f"  OpenAI calls: {self.openai_calls}")
        logger.info(f"  Cache hits: {self.cache_hits}")
        logger.info(f"  Heuristics: {self.heuristic_hits}")
        logger.info(f"  Cache hit rate: {self.get_cache_hit_rate():.1f}%")
        logger.info(f"  Estimated cost: ${self.get_total_cost():.2f}")

        logger.info("")
        logger.info("REJECTIONS:")
        total_rejections = sum(self.rejections.values())
        for reason, count in sorted(self.rejections.items(), key=lambda x: x[1], reverse=True):
            if count > 0:
                pct = (count / total_rejections * 100) if total_rejections > 0 else 0
                logger.info(f"  {reason}: {count} ({pct:.1f}%)")

        logger.info("")
        logger.info("PERFORMANCE:")
        logger.info(f"  Total runtime: {runtime:.1f}s ({runtime/60:.1f}min)")
        logger.info(f"  Efficiency score: {self.get_efficiency_score():.1f}/100")
        logger.info("=" * 80)


# Global metrics instance
_metrics = Metrics()


def get_metrics() -> Metrics:
    """Return the global metrics instance."""
    return _metrics


def reset_metrics():
    """Reset global metrics."""
    _metrics.reset()
