"""
Image deduplication system with persistent storage.

Uses perceptual hashing (pHash) to detect visually similar images,
even if they differ in resolution, compression, or minor edits.

Features:
- SQLite persistence across runs
- Thread-safe for parallel processing
- Configurable Hamming distance threshold
- Per-item scoped deduplication
- Cleanup of old entries
"""

import sqlite3
import imagehash
import time
from PIL import Image
from typing import Optional, Tuple
from pathlib import Path
from loguru import logger
from config import DEDUP_DB_PATH


def phash(img: Image.Image, hash_size: int = 8) -> str:
    """
    Compute perceptual hash of an image.

    Args:
        img: PIL Image object
        hash_size: Hash grid size (default: 8x8 = 64 bits)

    Returns:
        Hexadecimal hash string
    """
    return str(imagehash.phash(img, hash_size=hash_size))


class HashIndex:
    """
    Persistent image hash index backed by SQLite.

    Stores perceptual hashes and detects duplicates using Hamming distance.
    Thread-safe for use with concurrent.futures.
    """

    def __init__(self, db_path: Optional[str] = None, threshold: int = 6):
        """
        Initialize the hash index.

        Args:
            db_path: Path to SQLite database (uses config default if None)
            threshold: Maximum Hamming distance to consider as duplicate
        """
        self.db_path = db_path or DEDUP_DB_PATH
        self.threshold = threshold

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        logger.debug(f"HashIndex initialized: {self.db_path}")

    def _init_db(self):
        """Create database schema if it doesn't exist."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS image_hashes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash TEXT NOT NULL,
                url TEXT NOT NULL,
                item_id TEXT,
                timestamp INTEGER NOT NULL,
                UNIQUE(hash, item_id)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_hash ON image_hashes(hash)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_item_id ON image_hashes(item_id)
        """)

        conn.commit()
        conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """Return a thread-safe database connection."""
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def add_and_check(
        self,
        img_hash: str,
        url: str,
        item_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Add a hash and check if a similar one already exists.

        Args:
            img_hash: Perceptual hash string (hex)
            url: URL of the image
            item_id: Identifier for scoping (optional)

        Returns:
            Tuple of (is_unique, duplicate_url):
            - is_unique: True if no similar hash was found
            - duplicate_url: URL of the duplicate if found
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            if item_id:
                cursor.execute(
                    "SELECT hash, url FROM image_hashes WHERE item_id = ?",
                    (item_id,)
                )
            else:
                cursor.execute("SELECT hash, url FROM image_hashes")

            try:
                new_hash = imagehash.hex_to_hash(img_hash)
            except Exception:
                logger.warning(f"Invalid hash: {img_hash}")
                return True, None

            for db_hash_str, db_url in cursor.fetchall():
                try:
                    db_hash = imagehash.hex_to_hash(db_hash_str)
                    distance = new_hash - db_hash

                    if distance <= self.threshold:
                        logger.debug(
                            f"Duplicate detected (distance={distance}): "
                            f"{url[:50]}... ~ {db_url[:50]}..."
                        )
                        return False, db_url

                except Exception as e:
                    logger.debug(f"Error comparing hash: {e}")
                    continue

            timestamp = int(time.time())
            cursor.execute("""
                INSERT OR IGNORE INTO image_hashes (hash, url, item_id, timestamp)
                VALUES (?, ?, ?, ?)
            """, (img_hash, url, item_id, timestamp))

            conn.commit()
            return True, None

        except sqlite3.Error as e:
            logger.error(f"SQLite error checking duplicate: {e}")
            return True, None

        finally:
            conn.close()

    def count(self, item_id: Optional[str] = None) -> int:
        """Count stored hashes, optionally filtered by item_id."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            if item_id:
                cursor.execute(
                    "SELECT COUNT(*) FROM image_hashes WHERE item_id = ?",
                    (item_id,)
                )
            else:
                cursor.execute("SELECT COUNT(*) FROM image_hashes")
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def clear_old_entries(self, days: int = 90):
        """Remove entries older than the specified number of days."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cutoff = int(time.time()) - (days * 86400)
            cursor.execute("DELETE FROM image_hashes WHERE timestamp < ?", (cutoff,))
            deleted = cursor.rowcount
            conn.commit()

            if deleted > 0:
                logger.info(f"Removed {deleted} old hashes (>{days} days)")

        except sqlite3.Error as e:
            logger.error(f"Error cleaning old hashes: {e}")
        finally:
            conn.close()

    def clear_item(self, item_id: str):
        """Remove all hashes for a specific item."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM image_hashes WHERE item_id = ?", (item_id,))
            deleted = cursor.rowcount
            conn.commit()
            logger.debug(f"Removed {deleted} hashes for item {item_id}")
        except sqlite3.Error as e:
            logger.error(f"Error clearing item hashes: {e}")
        finally:
            conn.close()

    def get_stats(self) -> dict:
        """Return index statistics."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT COUNT(*) FROM image_hashes")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT item_id) FROM image_hashes")
            items_count = cursor.fetchone()[0]

            db_size_mb = Path(self.db_path).stat().st_size / (1024 * 1024)

            cursor.execute("SELECT MIN(timestamp) FROM image_hashes")
            oldest_ts = cursor.fetchone()[0]
            oldest_days = (time.time() - oldest_ts) / 86400 if oldest_ts else 0

            return {
                "total_hashes": total,
                "items_count": items_count,
                "db_size_mb": round(db_size_mb, 2),
                "oldest_days": round(oldest_days, 1)
            }
        finally:
            conn.close()
