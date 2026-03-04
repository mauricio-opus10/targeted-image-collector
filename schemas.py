"""
Pydantic schemas for data validation.

Ensures all input data is properly validated before processing,
catching malformed entries early in the pipeline.
"""

from typing import Optional
from pydantic import BaseModel, field_validator, Field
from loguru import logger


class ItemSchema(BaseModel):
    """
    Validation schema for input item data.

    Ensures all required fields are present and valid before
    the item enters the processing pipeline. Works for any
    entity type (buildings, products, vehicles, etc.).
    """

    item_id: str = Field(..., description="Unique item identifier")
    name: str = Field(..., min_length=1, description="Item name")
    city: Optional[str] = Field(None, description="City or location")
    state: Optional[str] = Field(None, max_length=2, description="State/region abbreviation")
    organization: Optional[str] = Field(None, description="Organization (developer, manufacturer, brand)")
    website: Optional[str] = Field(None, description="Official website URL")
    item_type: Optional[str] = Field(None, description="Type classification")
    category: Optional[str] = Field(None, description="Category")
    address: Optional[str] = Field(None, description="Full address")

    @field_validator('item_id')
    @classmethod
    def validate_item_id(cls, v):
        if not v or not v.strip():
            raise ValueError("item_id cannot be empty")
        return v.strip()

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("name cannot be empty")
        if len(v.strip()) < 3:
            raise ValueError("name must be at least 3 characters")
        return v.strip()

    @field_validator('website')
    @classmethod
    def validate_website(cls, v):
        if v and v.strip():
            v = v.strip()
            if not v.startswith(('http://', 'https://')):
                v = 'https://' + v
            return v
        return None

    @field_validator('state')
    @classmethod
    def validate_state(cls, v):
        if v and v.strip():
            v = v.strip().upper()
            if len(v) != 2:
                logger.warning(f"Invalid state abbreviation: {v}")
            return v
        return None

    class Config:
        extra = 'allow'
        coerce_numbers_to_str = True

    def to_dict(self) -> dict:
        return self.model_dump()


class ClassificationResult(BaseModel):
    """Schema for image classification results."""

    category: str = Field(...)
    confidence: float = Field(..., ge=0.0, le=1.0)
    is_correct_item: Optional[bool] = Field(None)
    item_confidence: float = Field(0.0, ge=0.0, le=1.0)
    why: str = Field("")
    item_evidence: str = Field("")
    method: str = Field("unknown")
    from_cache: bool = Field(False)

    @field_validator('confidence', 'item_confidence')
    @classmethod
    def validate_confidence(cls, v):
        return max(0.0, min(1.0, v))


class URLValidationResult(BaseModel):
    """Schema for URL validation results."""

    is_valid: bool
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reason: str
    conflicting_item: Optional[str] = None
    keywords_found: list[str] = Field(default_factory=list)
    validation_level: str = Field("moderate")


class SerpAPIResult(BaseModel):
    """Schema for normalized SerpAPI results."""

    image_url: str
    page_url: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str] = None
    thumbnail: Optional[str] = None
    position: Optional[int] = None

    @field_validator('image_url')
    @classmethod
    def validate_image_url(cls, v):
        if not v or not v.strip():
            raise ValueError("image_url cannot be empty")
        return v.strip()


# === Batch Validation ===

def validate_item(data: dict) -> Optional[ItemSchema]:
    """Validate a single item data dict."""
    try:
        return ItemSchema(**data)
    except Exception as e:
        logger.error(f"Validation error: {e}")
        return None


def validate_items_batch(items_data: list[dict]) -> tuple[list[ItemSchema], list[dict]]:
    """
    Validate a list of item data dicts.

    Returns:
        Tuple of (valid_items, invalid_items)
    """
    valid = []
    invalid = []

    for data in items_data:
        try:
            valid.append(ItemSchema(**data))
        except Exception as e:
            logger.warning(f"Invalid item {data.get('item_id', '?')}: {e}")
            invalid.append(data)

    logger.info(f"Validated: {len(valid)}/{len(items_data)} items")

    if invalid:
        logger.warning(f"{len(invalid)} invalid items were skipped")

    return valid, invalid
