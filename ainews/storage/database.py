import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ainews.models import ProcessedNewsItem


SCHEMA = """
CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    published TEXT,
    summary TEXT,
    score INTEGER DEFAULT 0,
    score_reasoning TEXT,
    category TEXT DEFAULT 'Industry',
    fetched_via TEXT,
    processed_at TEXT NOT NULL,
    acknowledged INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_score ON news_items(score DESC);
CREATE INDEX IF NOT EXISTS idx_published ON news_items(published DESC);
CREATE INDEX IF NOT EXISTS idx_source ON news_items(source);
"""

SCHEMA_CATEGORY_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_category ON news_items(category);"
)

SCHEMA_ACKNOWLEDGED_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_acknowledged ON news_items(acknowledged);"
)

SCHEMA_GROUP_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_group_id ON news_items(group_id);"
)

SCHEMA_PROCESSED_AT_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_processed_at ON news_items(processed_at DESC);"
)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path  # Store path for later use
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA)
        # Migrate existing databases: add category column if missing
        try:
            self.conn.execute(
                "ALTER TABLE news_items ADD COLUMN category TEXT DEFAULT 'Industry'"
            )
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
        self.conn.execute(SCHEMA_CATEGORY_INDEX)
        # Migrate existing databases: add acknowledged column if missing
        try:
            self.conn.execute(
                "ALTER TABLE news_items ADD COLUMN acknowledged INTEGER DEFAULT 0"
            )
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
        self.conn.execute(SCHEMA_ACKNOWLEDGED_INDEX)
        # Migrate existing databases: add group_id column if missing
        try:
            self.conn.execute(
                "ALTER TABLE news_items ADD COLUMN group_id INTEGER DEFAULT NULL"
            )
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
        self.conn.execute(SCHEMA_GROUP_INDEX)
        # Migrate: add learning_objectives column if missing
        try:
            self.conn.execute(
                "ALTER TABLE news_items ADD COLUMN learning_objectives TEXT DEFAULT ''"
            )
            self.conn.commit()
        except sqlite3.OperationalError:
            pass
        # Migrate: add lo_generated_with_opus column if missing
        try:
            self.conn.execute(
                "ALTER TABLE news_items ADD COLUMN lo_generated_with_opus INTEGER DEFAULT 0"
            )
            self.conn.commit()
        except sqlite3.OperationalError:
            pass
        # Add index on processed_at for fast "last 24 hours" queries
        self.conn.execute(SCHEMA_PROCESSED_AT_INDEX)
        self.conn.commit()

    def url_exists(self, url: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM news_items WHERE url = ?", (url,)
        ).fetchone()
        return row is not None

    def insert(self, item: ProcessedNewsItem) -> int:
        cursor = self.conn.execute(
            """INSERT OR IGNORE INTO news_items
               (title, url, source, published, summary, score, score_reasoning, learning_objectives, category, fetched_via, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.title,
                item.url,
                item.source,
                item.published.isoformat() if item.published else None,
                item.summary,
                item.score,
                item.score_reasoning,
                item.learning_objectives,
                item.category,
                item.fetched_via,
                item.processed_at.isoformat(),
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def acknowledge(self, item_id: int):
        self.conn.execute(
            "UPDATE news_items SET acknowledged = 1 WHERE id = ?", (item_id,)
        )
        self.conn.commit()

    def acknowledge_before_date(self, before_date) -> int:
        """Acknowledge all unacknowledged items published before the given date."""
        cursor = self.conn.execute(
            "UPDATE news_items SET acknowledged = 1 WHERE acknowledged = 0 AND published < ?",
            (before_date.isoformat(),),
        )
        self.conn.commit()
        return cursor.rowcount

    def acknowledge_below_score(self, max_score: int) -> int:
        """Acknowledge all unacknowledged items with score below the given value."""
        cursor = self.conn.execute(
            "UPDATE news_items SET acknowledged = 1 WHERE acknowledged = 0 AND score < ?",
            (max_score,),
        )
        self.conn.commit()
        return cursor.rowcount

    def update_learning_objectives(self, item_id: int, objectives: str, generated_with_opus: bool = False):
        self.conn.execute(
            "UPDATE news_items SET learning_objectives = ?, lo_generated_with_opus = ? WHERE id = ?",
            (objectives, int(generated_with_opus), item_id),
        )
        self.conn.commit()

    def query(
        self,
        min_score: int = 0,
        max_score: int = 10,
        sources: Optional[list[str]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        category: Optional[str] = None,
        show_acknowledged: bool = False,
        sort_by: str = "score",
        sort_dir: str = "DESC",
        limit: int = 200,
    ) -> list[ProcessedNewsItem]:
        sql = "SELECT * FROM news_items WHERE score >= ? AND score <= ?"
        params: list = [min_score, max_score]

        if not show_acknowledged:
            sql += " AND acknowledged = 0"

        if category:
            sql += " AND category = ?"
            params.append(category)

        if sources:
            placeholders = ",".join("?" for _ in sources)
            sql += f" AND source IN ({placeholders})"
            params.extend(sources)

        if start_date:
            sql += " AND published >= ?"
            params.append(start_date.isoformat())

        if end_date:
            sql += " AND published <= ?"
            params.append(end_date.isoformat())

        allowed_columns = {"score", "published", "source", "title"}
        col = sort_by if sort_by in allowed_columns else "score"
        direction = "ASC" if sort_dir.upper() == "ASC" else "DESC"
        sql += f" ORDER BY {col} {direction}"
        if col != "score":
            sql += ", score DESC"
        sql += ", published DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_item(r) for r in rows]

    def set_group(self, item_id: int, group_id: int):
        self.conn.execute(
            "UPDATE news_items SET group_id = ? WHERE id = ?", (group_id, item_id)
        )

    def clear_all_groups(self):
        self.conn.execute("UPDATE news_items SET group_id = NULL")
        self.conn.commit()

    def commit(self):
        self.conn.commit()

    def get_all_items_minimal(self) -> list[dict]:
        """Get id, title, url for all items (for grouping)."""
        rows = self.conn.execute(
            "SELECT id, title, url FROM news_items ORDER BY score DESC"
        ).fetchall()
        return [{"id": r["id"], "title": r["title"], "url": r["url"]} for r in rows]

    def query_grouped(
        self,
        min_score: int = 0,
        max_score: int = 10,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        category: Optional[str] = None,
        show_acknowledged: bool = False,
        sort_by: str = "score",
        sort_dir: str = "DESC",
        limit: int = 200,
    ) -> list[tuple[ProcessedNewsItem, list[ProcessedNewsItem]]]:
        """Query items and return grouped results as (primary, [related]) tuples."""
        items = self.query(
            min_score=min_score, max_score=max_score,
            start_date=start_date, end_date=end_date,
            category=category, show_acknowledged=show_acknowledged,
            sort_by=sort_by, sort_dir=sort_dir, limit=limit,
        )

        # Separate grouped and ungrouped
        groups: dict[int, list[ProcessedNewsItem]] = {}
        ungrouped: list[ProcessedNewsItem] = []
        for item in items:
            if item.group_id is not None:
                groups.setdefault(item.group_id, []).append(item)
            else:
                ungrouped.append(item)

        result: list[tuple[ProcessedNewsItem, list[ProcessedNewsItem]]] = []
        seen_groups: set[int] = set()

        # Walk items in original sort order to determine display position
        for item in items:
            if item.group_id is not None:
                if item.group_id in seen_groups:
                    continue
                seen_groups.add(item.group_id)
                members = groups[item.group_id]
                # Primary = first in list (already sorted by score DESC)
                primary = members[0]
                related = members[1:]
                result.append((primary, related))
            else:
                result.append((item, []))

        return result

    def query_items(
        self,
        min_score: int = 0,
        max_score: int = 10,
        show_acknowledged: bool = False,
        sort_by: str = "score",
        sort_dir: str = "DESC",
        limit: int = 200,
    ) -> list[ProcessedNewsItem]:
        """Query items without grouping (flat list). Used by RSS generation."""
        return self.query(
            min_score=min_score,
            max_score=max_score,
            show_acknowledged=show_acknowledged,
            sort_by=sort_by,
            sort_dir=sort_dir,
            limit=limit,
        )

    def get_all_sources(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT source FROM news_items ORDER BY source"
        ).fetchall()
        return [r["source"] for r in rows]

    def get_stats(self) -> dict:
        row = self.conn.execute(
            """SELECT COUNT(*) as total,
                      COALESCE(AVG(score), 0) as avg_score,
                      COUNT(DISTINCT source) as source_count
               FROM news_items"""
        ).fetchone()
        today = datetime.now(timezone.utc).date().isoformat()
        today_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM news_items WHERE processed_at LIKE ?",
            (f"{today}%",),
        ).fetchone()["cnt"]
        return {
            "total": row["total"],
            "avg_score": round(row["avg_score"], 1),
            "source_count": row["source_count"],
            "today": today_count,
        }

    def get_source_status(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT source,
                      COUNT(*) as item_count,
                      MAX(processed_at) as last_scanned
               FROM news_items
               GROUP BY source
               ORDER BY last_scanned DESC"""
        ).fetchall()
        return [
            {
                "source": r["source"],
                "item_count": r["item_count"],
                "last_scanned": r["last_scanned"],
            }
            for r in rows
        ]

    def get_last_run_stats(self) -> Optional[dict]:
        """Get last pipeline run time and items added in last 24 hours."""
        from datetime import datetime, timedelta
        from pathlib import Path

        # Read last run timestamp from file
        timestamp_file = Path(self.db_path).parent / ".last_run"
        last_run = None
        if timestamp_file.exists():
            try:
                with open(timestamp_file) as f:
                    last_run = f.read().strip()
            except Exception:
                pass

        # If no timestamp file, fall back to database (backward compatibility)
        if not last_run:
            row = self.conn.execute(
                "SELECT MAX(processed_at) as last_run FROM news_items"
            ).fetchone()
            if not row or not row["last_run"]:
                return None
            last_run = row["last_run"]

        # Count items added in the last 24 hours
        cutoff_time = (datetime.now() - timedelta(hours=24)).isoformat()
        count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM news_items WHERE processed_at >= ?",
            (cutoff_time,),
        ).fetchone()["cnt"]

        return {"last_run": last_run, "items_added": count}

    def get_score_distribution(self) -> dict[int, int]:
        rows = self.conn.execute(
            "SELECT score, COUNT(*) as cnt FROM news_items GROUP BY score ORDER BY score"
        ).fetchall()
        return {r["score"]: r["cnt"] for r in rows}

    def _row_to_item(self, row: sqlite3.Row) -> ProcessedNewsItem:
        published = None
        if row["published"]:
            try:
                published = datetime.fromisoformat(row["published"])
            except ValueError:
                pass
        try:
            category = row["category"] or "Industry"
        except (IndexError, KeyError):
            category = "Industry"
        try:
            acknowledged = bool(row["acknowledged"])
        except (IndexError, KeyError):
            acknowledged = False
        try:
            group_id = row["group_id"]
        except (IndexError, KeyError):
            group_id = None
        try:
            learning_objectives = row["learning_objectives"] or ""
        except (IndexError, KeyError):
            learning_objectives = ""
        try:
            lo_generated_with_opus = bool(row["lo_generated_with_opus"])
        except (IndexError, KeyError):
            lo_generated_with_opus = False
        return ProcessedNewsItem(
            id=row["id"],
            title=row["title"],
            url=row["url"],
            source=row["source"],
            published=published,
            summary=row["summary"] or "",
            score=row["score"],
            score_reasoning=row["score_reasoning"] or "",
            learning_objectives=learning_objectives,
            category=category,
            fetched_via=row["fetched_via"] or "",
            processed_at=datetime.fromisoformat(row["processed_at"]),
            acknowledged=acknowledged,
            group_id=group_id,
            lo_generated_with_opus=lo_generated_with_opus,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        self.conn.close()
