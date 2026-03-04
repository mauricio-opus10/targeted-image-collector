"""
Checkpoint system for resumable long-running processes.

Prevents re-processing items that were already completed successfully.
Allows interrupted runs to resume from where they left off.

How it works:
1. On startup, computes a hash of the input data source
2. If the hash matches the saved checkpoint, resumes from where it stopped
3. If the hash differs (input changed), starts fresh
4. After each item is processed, updates the checkpoint on disk
"""

import os
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from loguru import logger

from config import OUTPUT_DIR

CHECKPOINT_FILE = Path(OUTPUT_DIR) / "checkpoint.json"


def _compute_input_hash(input_path: str) -> str:
    """Compute MD5 hash of the input file to detect changes."""
    try:
        with open(input_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception as e:
        logger.warning(f"Error computing input hash: {e}")
        return ""


def load_checkpoint(input_path: str) -> Dict:
    """
    Load checkpoint if it exists and is compatible with current input.

    Args:
        input_path: Path to the input data file

    Returns:
        Valid checkpoint dict or a fresh empty checkpoint
    """
    current_hash = _compute_input_hash(input_path)

    if not CHECKPOINT_FILE.exists():
        logger.info("No previous checkpoint found, starting fresh")
        return _create_new_checkpoint(input_path, current_hash)

    try:
        with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
            checkpoint = json.load(f)

        saved_hash = checkpoint.get("input_hash", "")

        if saved_hash != current_hash:
            logger.info("Input data changed, starting fresh")
            return _create_new_checkpoint(input_path, current_hash)

        processed_count = len(checkpoint.get("processed_items", []))
        logger.info(f"Checkpoint found: {processed_count} items already processed")
        logger.info(f"Resuming run from {checkpoint.get('started_at', 'N/A')}")

        return checkpoint

    except Exception as e:
        logger.warning(f"Error loading checkpoint: {e}")
        return _create_new_checkpoint(input_path, current_hash)


def _create_new_checkpoint(input_path: str, input_hash: str) -> Dict:
    """Create a fresh empty checkpoint."""
    checkpoint = {
        "input_path": input_path,
        "input_hash": input_hash,
        "started_at": datetime.now().isoformat(),
        "processed_items": [],
        "items_with_images": [],
        "total_images_saved": 0,
        "last_updated": datetime.now().isoformat()
    }
    _save_checkpoint(checkpoint)
    return checkpoint


def _save_checkpoint(checkpoint: Dict):
    """Persist checkpoint to disk."""
    try:
        checkpoint["last_updated"] = datetime.now().isoformat()
        with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving checkpoint: {e}")


def mark_item_processed(checkpoint: Dict, item_id: str, images_saved: int = 0):
    """
    Mark an item as processed in the checkpoint.

    Args:
        checkpoint: Current checkpoint dict
        item_id: Unique identifier of the processed item
        images_saved: Number of images saved for this item
    """
    item_id_str = str(item_id)

    if item_id_str not in checkpoint["processed_items"]:
        checkpoint["processed_items"].append(item_id_str)

    if images_saved > 0 and item_id_str not in checkpoint["items_with_images"]:
        checkpoint["items_with_images"].append(item_id_str)
        checkpoint["total_images_saved"] += images_saved

    _save_checkpoint(checkpoint)
    logger.debug(f"[{item_id}] Checkpoint updated ({len(checkpoint['processed_items'])} items processed)")


def is_item_processed(checkpoint: Dict, item_id: str) -> bool:
    """Check if an item was already processed."""
    return str(item_id) in checkpoint.get("processed_items", [])


def get_pending_items(checkpoint: Dict, all_items: List[Dict], id_field: str = "item_id") -> List[Dict]:
    """
    Filter out already-processed items.

    Args:
        checkpoint: Current checkpoint dict
        all_items: Full list of items to process
        id_field: Name of the ID field in each item dict

    Returns:
        List of items that still need processing
    """
    processed = set(checkpoint.get("processed_items", []))

    pending = [
        item for item in all_items
        if str(item.get(id_field, "")) not in processed
    ]

    skipped = len(all_items) - len(pending)

    if skipped > 0:
        logger.info(f"Skipping {skipped} already-processed items (checkpoint)")
        logger.info(f"Processing {len(pending)} pending items")

    return pending


def clear_checkpoint():
    """Remove checkpoint file (forces fresh start)."""
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("Checkpoint removed")


def print_checkpoint_summary(checkpoint: Dict):
    """Print a human-readable checkpoint summary."""
    logger.info("=" * 50)
    logger.info("CHECKPOINT SUMMARY")
    logger.info("=" * 50)
    logger.info(f"Started at: {checkpoint.get('started_at', 'N/A')}")
    logger.info(f"Items processed: {len(checkpoint.get('processed_items', []))}")
    logger.info(f"Items with images: {len(checkpoint.get('items_with_images', []))}")
    logger.info(f"Total images: {checkpoint.get('total_images_saved', 0)}")
    logger.info("=" * 50)
