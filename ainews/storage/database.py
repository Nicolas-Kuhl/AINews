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

SCHEMA_FEED_SCANS = """
CREATE TABLE IF NOT EXISTS feed_scans (
    feed_name TEXT PRIMARY KEY,
    last_scanned TEXT NOT NULL
);
"""

SCHEMA_PROCESSED_EMAILS = """
CREATE TABLE IF NOT EXISTS processed_emails (
    message_id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    subject TEXT,
    processed_at TEXT NOT NULL,
    stories_extracted INTEGER DEFAULT 0
);
"""

SCHEMA_SOURCES = """
CREATE TABLE IF NOT EXISTS sources (
    name TEXT PRIMARY KEY,
    short TEXT NOT NULL,
    mark TEXT NOT NULL,
    hue INTEGER NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('Official','Web Scrape','Newsletter'))
);
"""

SCHEMA_MORNING_BRIEFS = """
CREATE TABLE IF NOT EXISTS morning_briefs (
    date TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    paragraph TEXT NOT NULL,
    stats_json TEXT
);
"""

SCHEMA_DAY_BRIEFS = """
CREATE TABLE IF NOT EXISTS day_briefs (
    date TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    paragraph TEXT NOT NULL
);
"""


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
        # Migrate: add content column if missing
        try:
            self.conn.execute(
                "ALTER TABLE news_items ADD COLUMN content TEXT DEFAULT NULL"
            )
            self.conn.commit()
        except sqlite3.OperationalError:
            pass
        # Migrate: add starred column if missing
        try:
            self.conn.execute(
                "ALTER TABLE news_items ADD COLUMN starred INTEGER DEFAULT 0"
            )
            self.conn.commit()
        except sqlite3.OperationalError:
            pass
        # Migrate: add short_summary column if missing (2-3 sentence dek used
        # in row view; the long `summary` remains the Reader drawer's copy)
        try:
            self.conn.execute(
                "ALTER TABLE news_items ADD COLUMN short_summary TEXT DEFAULT ''"
            )
            self.conn.commit()
        except sqlite3.OperationalError:
            pass
        # Add index on processed_at for fast "last 24 hours" queries
        self.conn.execute(SCHEMA_PROCESSED_AT_INDEX)
        # Create feed_scans table for per-feed scan interval tracking
        self.conn.executescript(SCHEMA_FEED_SCANS)
        # Create processed_emails table for newsletter dedup
        self.conn.executescript(SCHEMA_PROCESSED_EMAILS)
        # Phase 2: sources metadata + Morning/Day briefs
        self.conn.executescript(SCHEMA_SOURCES)
        self.conn.executescript(SCHEMA_MORNING_BRIEFS)
        self.conn.executescript(SCHEMA_DAY_BRIEFS)
        self.conn.commit()
        # Migrate `sources` rows if the CHECK constraint is still the old
        # five-type schema (Official / Press / Research / Platform / Newsletter).
        self._migrate_sources_types_if_needed()

    def _migrate_sources_types_if_needed(self) -> None:
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='sources'"
        ).fetchone()
        if not row:
            return
        sql = row[0] or ""
        if "Web Scrape" in sql:
            return  # already on new schema
        self.conn.executescript(
            """
            CREATE TABLE sources_new (
                name TEXT PRIMARY KEY,
                short TEXT NOT NULL,
                mark TEXT NOT NULL,
                hue INTEGER NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('Official','Web Scrape','Newsletter'))
            );
            INSERT INTO sources_new (name, short, mark, hue, type)
            SELECT name, short, mark, hue,
                CASE type
                    WHEN 'Press' THEN 'Web Scrape'
                    WHEN 'Research' THEN 'Web Scrape'
                    WHEN 'Platform' THEN 'Web Scrape'
                    ELSE type
                END
            FROM sources;
            DROP TABLE sources;
            ALTER TABLE sources_new RENAME TO sources;
            """
        )
        self.conn.commit()

    def get_feed_last_scanned(self, feed_name: str) -> Optional[str]:
        """Return the ISO timestamp of the last scan for a feed, or None."""
        row = self.conn.execute(
            "SELECT last_scanned FROM feed_scans WHERE feed_name = ?",
            (feed_name,),
        ).fetchone()
        return row["last_scanned"] if row else None

    def update_feed_last_scanned(self, feed_name: str, timestamp: str):
        """Record that a feed was just scanned."""
        self.conn.execute(
            "INSERT OR REPLACE INTO feed_scans (feed_name, last_scanned) VALUES (?, ?)",
            (feed_name, timestamp),
        )
        self.conn.commit()

    def is_email_processed(self, message_id: str) -> bool:
        """Check if a newsletter email has already been processed."""
        row = self.conn.execute(
            "SELECT 1 FROM processed_emails WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        return row is not None

    def mark_email_processed(
        self, message_id: str, sender: str, subject: str, stories_count: int
    ):
        """Record that a newsletter email has been processed."""
        self.conn.execute(
            "INSERT OR REPLACE INTO processed_emails (message_id, sender, subject, processed_at, stories_extracted) VALUES (?, ?, ?, ?, ?)",
            (message_id, sender, subject, datetime.now().isoformat(), stories_count),
        )
        self.conn.commit()

    def url_exists(self, url: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM news_items WHERE url = ?", (url,)
        ).fetchone()
        return row is not None

    def get_all_titles(self) -> list[str]:
        """Return all titles in the database (lowercased) for fuzzy dedup."""
        rows = self.conn.execute("SELECT LOWER(title) FROM news_items").fetchall()
        return [row[0] for row in rows]

    def get_all_normalized_urls(self) -> set[str]:
        """Return all URLs in the database for normalized dedup."""
        rows = self.conn.execute("SELECT url FROM news_items").fetchall()
        return {row[0] for row in rows}

    def insert(self, item: ProcessedNewsItem) -> int:
        cursor = self.conn.execute(
            """INSERT OR IGNORE INTO news_items
               (title, url, source, published, summary, short_summary, content, score, score_reasoning, learning_objectives, category, fetched_via, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.title,
                item.url,
                item.source,
                item.published.isoformat() if item.published else None,
                item.summary,
                item.short_summary,
                item.content,
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

    def update_short_summary(self, item_id: int, short_summary: str) -> None:
        self.conn.execute(
            "UPDATE news_items SET short_summary = ? WHERE id = ?",
            (short_summary, item_id),
        )
        self.conn.commit()

    def acknowledge(self, item_id: int):
        self.conn.execute(
            "UPDATE news_items SET acknowledged = 1 WHERE id = ?", (item_id,)
        )
        self.conn.commit()

    def unacknowledge(self, item_id: int):
        self.conn.execute(
            "UPDATE news_items SET acknowledged = 0 WHERE id = ?", (item_id,)
        )
        self.conn.commit()

    def set_starred(self, item_id: int, starred: bool):
        self.conn.execute(
            "UPDATE news_items SET starred = ? WHERE id = ?",
            (1 if starred else 0, item_id),
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

    def get_by_id(self, item_id: int) -> Optional[ProcessedNewsItem]:
        row = self.conn.execute(
            "SELECT * FROM news_items WHERE id = ?", (item_id,)
        ).fetchone()
        return self._row_to_item(row) if row else None

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

    def group_by_title_pairs(self, title_pairs: list[tuple[str, str]]) -> int:
        """Group items whose titles match the given (title_a, title_b) pairs.

        For each pair, finds both items in the DB and assigns them the same group_id.
        If one item is already in a group, the other joins that group.
        Returns the number of new groupings made.
        """
        grouped = 0
        max_row = self.conn.execute("SELECT COALESCE(MAX(group_id), 0) FROM news_items").fetchone()
        next_group_id = (max_row[0] or 0) + 1

        for title_a, title_b in title_pairs:
            row_a = self.conn.execute(
                "SELECT id, group_id FROM news_items WHERE LOWER(title) = ?",
                (title_a.lower().strip(),),
            ).fetchone()
            row_b = self.conn.execute(
                "SELECT id, group_id FROM news_items WHERE LOWER(title) = ?",
                (title_b.lower().strip(),),
            ).fetchone()

            if not row_a or not row_b or row_a["id"] == row_b["id"]:
                continue

            # Already in the same group
            if row_a["group_id"] and row_a["group_id"] == row_b["group_id"]:
                continue

            # Pick a group_id: use existing if one has it, otherwise assign new
            if row_a["group_id"]:
                gid = row_a["group_id"]
            elif row_b["group_id"]:
                gid = row_b["group_id"]
            else:
                gid = next_group_id
                next_group_id += 1

            self.conn.execute("UPDATE news_items SET group_id = ? WHERE id = ?", (gid, row_a["id"]))
            self.conn.execute("UPDATE news_items SET group_id = ? WHERE id = ?", (gid, row_b["id"]))
            grouped += 1

        self.conn.commit()
        return grouped

    def commit(self):
        self.conn.commit()

    def get_all_items_minimal(self) -> list[dict]:
        """Get id, title, url for all items (for grouping)."""
        rows = self.conn.execute(
            "SELECT id, title, url FROM news_items ORDER BY score DESC"
        ).fetchall()
        return [{"id": r["id"], "title": r["title"], "url": r["url"]} for r in rows]

    def get_all_items_for_dedup(self, unacknowledged_only: bool = False) -> list[dict]:
        """Get id, title, url, source, summary for semantic dedup."""
        sql = "SELECT id, title, url, source, summary FROM news_items"
        if unacknowledged_only:
            sql += " WHERE acknowledged = 0"
        sql += " ORDER BY score DESC"
        rows = self.conn.execute(sql).fetchall()
        return [
            {"id": r["id"], "title": r["title"], "url": r["url"],
             "source": r["source"], "summary": r["summary"] or ""}
            for r in rows
        ]

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

    def query_by_day(
        self,
        min_score: int = 0,
        max_score: int = 10,
        show_acknowledged: bool = False,
        limit_days: int = 30,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> dict[str, list[tuple[ProcessedNewsItem, list[ProcessedNewsItem]]]]:
        """Query items grouped by day (published date), then grouped by group_id within each day.

        Returns an ordered dict of {date_str: [(primary, [related]), ...]} sorted by
        date descending, items within each day sorted by score descending.
        """
        from collections import OrderedDict

        sql = "SELECT * FROM news_items WHERE score >= ? AND score <= ?"
        params: list = [min_score, max_score]

        if not show_acknowledged:
            sql += " AND acknowledged = 0"

        if start_date:
            sql += " AND published >= ?"
            params.append(start_date.isoformat())

        if end_date:
            sql += " AND published <= ?"
            params.append(end_date.isoformat())

        sql += " ORDER BY published DESC, score DESC"

        rows = self.conn.execute(sql, params).fetchall()
        items = [self._row_to_item(r) for r in rows]

        # Fold groups FIRST across the full window so a group that spans
        # multiple days collapses to a single (primary, [related]) pair on
        # the primary's publish day, rather than showing partial fragments
        # on each day.
        groups_by_gid: dict[int, list[ProcessedNewsItem]] = {}
        ungrouped_items: list[ProcessedNewsItem] = []
        for item in items:
            if item.group_id is not None:
                groups_by_gid.setdefault(item.group_id, []).append(item)
            else:
                ungrouped_items.append(item)

        folded: list[tuple[ProcessedNewsItem, list[ProcessedNewsItem]]] = []
        from datetime import datetime as _dt

        def _sort_key(it: ProcessedNewsItem):
            return (
                it.score,
                it.published or _dt.min.replace(tzinfo=None),
            )

        for members in groups_by_gid.values():
            members.sort(key=_sort_key, reverse=True)
            folded.append((members[0], members[1:]))
        for item in ungrouped_items:
            folded.append((item, []))

        # Bucket by the PRIMARY's publish day
        day_buckets: dict[str, list[tuple[ProcessedNewsItem, list[ProcessedNewsItem]]]] = {}
        for primary, related in folded:
            if primary.published:
                day_key = primary.published.strftime("%Y-%m-%d")
            else:
                day_key = "Unknown"
            day_buckets.setdefault(day_key, []).append((primary, related))

        sorted_days = sorted(day_buckets.keys(), reverse=True)[:limit_days]

        result: OrderedDict[str, list[tuple[ProcessedNewsItem, list[ProcessedNewsItem]]]] = OrderedDict()
        for day in sorted_days:
            day_items = day_buckets[day]
            day_items.sort(key=lambda pair: pair[0].score, reverse=True)
            result[day] = day_items

        return result

    def get_all_sources(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT source FROM news_items ORDER BY source"
        ).fetchall()
        return [r["source"] for r in rows]

    # -------- sources metadata --------

    def upsert_source_meta(
        self, name: str, *, short: str, mark: str, hue: int, type: str
    ) -> None:
        self.conn.execute(
            """INSERT INTO sources (name, short, mark, hue, type)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                 short = excluded.short,
                 mark = excluded.mark,
                 hue = excluded.hue,
                 type = excluded.type""",
            (name, short, mark, int(hue), type),
        )
        self.conn.commit()

    def get_source_metas(self) -> dict[str, dict]:
        rows = self.conn.execute(
            "SELECT name, short, mark, hue, type FROM sources"
        ).fetchall()
        return {
            r["name"]: {
                "short": r["short"],
                "mark": r["mark"],
                "hue": r["hue"],
                "type": r["type"],
            }
            for r in rows
        }

    # -------- briefs --------

    def get_morning_brief(self, date: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT date, generated_at, paragraph, stats_json FROM morning_briefs WHERE date = ?",
            (date,),
        ).fetchone()
        if not row:
            return None
        return {
            "date": row["date"],
            "generated_at": row["generated_at"],
            "paragraph": row["paragraph"],
            "stats_json": row["stats_json"],
        }

    def upsert_morning_brief(
        self, date: str, *, paragraph: str, stats_json: Optional[str] = None
    ) -> None:
        self.conn.execute(
            """INSERT INTO morning_briefs (date, generated_at, paragraph, stats_json)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 generated_at = excluded.generated_at,
                 paragraph = excluded.paragraph,
                 stats_json = excluded.stats_json""",
            (date, datetime.now(timezone.utc).isoformat(), paragraph, stats_json),
        )
        self.conn.commit()

    def get_day_briefs(self, dates: list[str]) -> dict[str, str]:
        if not dates:
            return {}
        placeholders = ",".join("?" for _ in dates)
        rows = self.conn.execute(
            f"SELECT date, paragraph FROM day_briefs WHERE date IN ({placeholders})",
            dates,
        ).fetchall()
        return {r["date"]: r["paragraph"] for r in rows}

    def upsert_day_brief(self, date: str, paragraph: str) -> None:
        self.conn.execute(
            """INSERT INTO day_briefs (date, generated_at, paragraph)
               VALUES (?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 generated_at = excluded.generated_at,
                 paragraph = excluded.paragraph""",
            (date, datetime.now(timezone.utc).isoformat(), paragraph),
        )
        self.conn.commit()

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
        try:
            content = row["content"]
        except (IndexError, KeyError):
            content = None
        try:
            starred = bool(row["starred"])
        except (IndexError, KeyError):
            starred = False
        try:
            short_summary = row["short_summary"] or ""
        except (IndexError, KeyError):
            short_summary = ""
        return ProcessedNewsItem(
            id=row["id"],
            title=row["title"],
            url=row["url"],
            source=row["source"],
            published=published,
            summary=row["summary"] or "",
            content=content,
            score=row["score"],
            score_reasoning=row["score_reasoning"] or "",
            learning_objectives=learning_objectives,
            category=category,
            fetched_via=row["fetched_via"] or "",
            processed_at=datetime.fromisoformat(row["processed_at"]),
            acknowledged=acknowledged,
            group_id=group_id,
            lo_generated_with_opus=lo_generated_with_opus,
            starred=starred,
            short_summary=short_summary,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        self.conn.close()
