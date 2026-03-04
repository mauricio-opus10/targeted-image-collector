"""
Configurable target definition for the image collection pipeline.

Define what kind of images to collect by loading a YAML target config.
This makes the pipeline reusable for any visual category:
- Building facades
- Product photos
- Vehicle images
- Real estate interiors
- Any other visual category

The target config customizes:
- Vision API prompts (what to look for)
- Heuristic keywords (text-based pre-filtering)
- Search query augmentation
- Category naming
"""

import yaml
from pathlib import Path
from dataclasses import dataclass, field, fields
from typing import List, Optional
from loguru import logger


@dataclass
class TargetConfig:
    """
    Configuration for a specific image collection target.

    Defines what kind of images the pipeline should collect,
    how to classify them, and what keywords to use for search
    and heuristic filtering.
    """

    # Identity
    name: str = "Generic Images"
    category: str = "target"
    description: str = "images matching the target criteria"

    # Heuristic classification keywords
    positive_keywords: List[str] = field(default_factory=list)
    negative_keywords: List[str] = field(default_factory=list)

    # URL patterns that indicate target images (regex)
    url_patterns: List[str] = field(default_factory=list)

    # Additional keywords for search queries
    search_keywords: List[str] = field(default_factory=list)

    # Keywords for gallery link discovery in site scraping
    gallery_keywords: List[str] = field(default_factory=list)

    # Vision API prompt customization
    vision_system_message: str = "You are an expert in visual classification."
    vision_target_description: str = "Image matching the target category"
    vision_exclusion_description: str = "Other image types (logos, icons, irrelevant content)"
    vision_extra_rules: List[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str) -> "TargetConfig":
        """
        Load target configuration from a YAML file.

        Args:
            path: Path to the YAML config file

        Returns:
            TargetConfig instance

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config file is empty or malformed
        """
        config_path = Path(path)

        if not config_path.exists():
            raise FileNotFoundError(f"Target config not found: {path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f"Empty target config: {path}")

        # Flatten nested 'vision' key into top-level vision_* fields
        vision = data.pop("vision", {})
        for key, value in vision.items():
            data[f"vision_{key}"] = value

        # Only pass known dataclass fields
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}

        config = cls(**filtered)
        logger.info(f"Loaded target config: {config.name} (category: {config.category})")
        return config

    @classmethod
    def default(cls) -> "TargetConfig":
        """Return a default configuration (building facades)."""
        return cls(
            name="Building Facades",
            category="facade",
            description="exterior photographs of buildings",
            positive_keywords=[
                "facade", "fachada", "exterior", "front view",
                "perspective", "render", "building", "tower",
            ],
            negative_keywords=[
                "logo", "icon", "floor plan", "planta", "map",
                "mapa", "avatar", "banner", "profile",
            ],
            url_patterns=[
                r'/fachadas?/', r'/facade/', r'/exterior/',
                r'/perspectiva', r'/render',
            ],
            search_keywords=["facade", "exterior", "render", "perspective"],
            gallery_keywords=["fachada", "facade", "exterior", "frente"],
            vision_system_message=(
                "You are an expert in visual classification of real estate developments."
            ),
            vision_target_description=(
                "External view of the building (facade, perspective, exterior render)"
            ),
            vision_exclusion_description=(
                "Other image types (floor plans, interiors, logos, maps, etc)"
            ),
            vision_extra_rules=[
                "Floor plans, layouts, and blueprints must be classified as non-target",
            ],
        )


# Global target config singleton
_target_config: Optional[TargetConfig] = None


def load_target_config(path: Optional[str] = None) -> TargetConfig:
    """
    Load and cache the target configuration.

    Args:
        path: Path to YAML config file. If None, uses default config.

    Returns:
        TargetConfig instance
    """
    global _target_config

    if path:
        _target_config = TargetConfig.from_yaml(path)
    else:
        _target_config = TargetConfig.default()
        logger.info("Using default target config (building facades)")

    return _target_config


def get_target_config() -> TargetConfig:
    """Return the current target configuration (loads default if not initialized)."""
    global _target_config
    if _target_config is None:
        _target_config = TargetConfig.default()
    return _target_config
