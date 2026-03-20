"""SQLite + FTS5 cache for crawled Confluence pages.

Single file at ~/.cache/confluence-subtree-mcp/cache.db.
Pages stored in a regular table, full-text index via FTS5 virtual table.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .crawler import PageData

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    space_key TEXT,
    path TEXT,          -- JSON array
    web_url TEXT,
    markdown_content TEXT,
    last_modified TEXT,
    version_when TEXT,
    source_type TEXT DEFAULT 'confluence',
    cached_at TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    id UNINDEXED,
    title,
    markdown_content,
    content=pages,
    content_rowid=rowid
);

-- Triggers to keep FTS in sync with pages table
CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
    INSERT INTO pages_fts(rowid, id, title, markdown_content)
    VALUES (new.rowid, new.id, new.title, new.markdown_content);
END;

CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, id, title, markdown_content)
    VALUES ('delete', old.rowid, old.id, old.title, old.markdown_content);
END;

CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, id, title, markdown_content)
    VALUES ('delete', old.rowid, old.id, old.title, old.markdown_content);
    INSERT INTO pages_fts(rowid, id, title, markdown_content)
    VALUES (new.rowid, new.id, new.title, new.markdown_content);
END;
"""


def _make_synthetic_pages() -> list[PageData]:
    """Generate placeholder pages for dry-run mode."""
    now = datetime.now(timezone.utc).isoformat()
    return [
        PageData(
            id="syn-1",
            title="Project Hub",
            space_key="DEMO",
            path=[],
            web_url="https://example.atlassian.net/wiki/spaces/DEMO/pages/syn-1",
            markdown_content=(
                "# Project Hub\n\n"
                "Central page linking all project docs.\n\n"
                "## Links\n\n"
                "- [Architecture](https://example.atlassian.net/wiki/spaces/DEMO/pages/syn-2)\n"
                "- [Runbooks](https://example.atlassian.net/wiki/spaces/DEMO/pages/syn-3)\n"
                "- [External API Docs](https://httpbin.org)\n"
            ),
            last_modified=now,
            version_when=now,
        ),
        PageData(
            id="syn-2",
            title="Architecture",
            space_key="DEMO",
            path=["Project Hub"],
            web_url="https://example.atlassian.net/wiki/spaces/DEMO/pages/syn-2",
            markdown_content=(
                "# Architecture\n\n"
                "## Components\n\n"
                "- **API Gateway** — handles routing\n"
                "- **Worker Service** — processes background jobs\n"
                "- **Database** — PostgreSQL with read replicas"
            ),
            last_modified=now,
            version_when=now,
        ),
        PageData(
            id="syn-3",
            title="Runbooks",
            space_key="DEMO",
            path=["Project Hub"],
            web_url="https://example.atlassian.net/wiki/spaces/DEMO/pages/syn-3",
            markdown_content=(
                "# Runbooks\n\n"
                "## Deploy\n\n"
                "1. Merge to main\n2. Wait for CI\n3. Approve deploy in Slack\n\n"
                "## Rollback\n\n"
                "1. Run `./rollback.sh`\n2. Notify #ops"
            ),
            last_modified=now,
            version_when=now,
        ),
        PageData(
            id="syn-4",
            title="API Reference",
            space_key="DEMO",
            path=["Project Hub", "Architecture"],
            web_url="https://example.atlassian.net/wiki/spaces/DEMO/pages/syn-4",
            markdown_content=(
                "# API Reference\n\n"
                '## GET /health\n\nReturns `200 OK` with `{"status": "healthy"}`.\n\n'
                "## POST /items\n\nCreate a new item.\n\n"
                "| Field | Type | Required |\n|-------|------|----------|\n"
                "| name | string | yes |\n| count | int | no |"
            ),
            last_modified=now,
            version_when=now,
        ),
        PageData(
            id="syn-5",
            title="On-Call Guide",
            space_key="DEMO",
            path=["Project Hub", "Runbooks"],
            web_url="https://example.atlassian.net/wiki/spaces/DEMO/pages/syn-5",
            markdown_content=(
                "# On-Call Guide\n\n"
                "## Alerts\n\n"
                "- **HighLatency** — check DB connections first\n"
                "- **ErrorRate** — check recent deploys\n"
                "- **DiskFull** — run cleanup script"
            ),
            last_modified=now,
            version_when=now,
        ),
    ]


class PageCache:
    """SQLite-backed cache with FTS5 full-text search."""

    def __init__(self, config: Config):
        self._config = config
        self._conn: sqlite3.Connection | None = None

    @property
    def db_path(self) -> Path:
        return self._config.cache_dir / "cache.db"

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if self._config.dry_run:
                self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            else:
                self._config.cache_dir.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def load_from_disk(self) -> bool:
        """Check if cache DB exists and has data."""
        if self._config.dry_run:
            return False
        if not self.db_path.is_file():
            return False
        try:
            conn = self._get_conn()
            row = conn.execute("SELECT COUNT(*) FROM pages").fetchone()
            return row[0] > 0
        except sqlite3.Error as exc:
            print(f"[WARN] Cache corrupted ({exc}), will re-crawl", file=sys.stderr)
            self.close()
            self.db_path.unlink(missing_ok=True)
            return False

    def save_to_disk(self):
        """Commit pending changes."""
        if self._config.dry_run:
            print("[DRY-RUN] Skipping cache write to disk", file=sys.stderr)
            return
        conn = self._get_conn()
        conn.commit()

    def update(
        self, pages: list[PageData], root_versions: dict[str, str] | None = None
    ):
        """Replace cache contents with freshly crawled pages."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()

        # Clear and rebuild
        conn.execute("DELETE FROM pages")
        for p in pages:
            conn.execute(
                """INSERT OR REPLACE INTO pages
                   (id, title, space_key, path, web_url, markdown_content,
                    last_modified, version_when, source_type, cached_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p.id,
                    p.title,
                    p.space_key,
                    json.dumps(p.path),
                    p.web_url,
                    p.markdown_content,
                    p.last_modified,
                    p.version_when,
                    p.source_type,
                    now,
                ),
            )

        # Store metadata
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('crawled_at', ?)", (now,)
        )
        if root_versions is not None:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('root_versions', ?)",
                (json.dumps(root_versions),),
            )
        conn.commit()

    def load_synthetic(self):
        """Load synthetic pages for dry-run mode."""
        print("[DRY-RUN] Loading synthetic pages", file=sys.stderr)
        self.update(_make_synthetic_pages())

    def get_meta(self, key: str) -> str | None:
        conn = self._get_conn()
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    @property
    def crawled_at(self) -> str | None:
        return self.get_meta("crawled_at")

    def get_root_versions(self) -> dict[str, str]:
        raw = self.get_meta("root_versions")
        return json.loads(raw) if raw else {}

    def get_page(self, page_id: str) -> dict | None:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM pages WHERE id = ?", (page_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def all_pages(self) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM pages").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def is_stale(self) -> bool:
        """Check if cache exceeds TTL."""
        crawled = self.crawled_at
        if not crawled:
            return True
        try:
            dt = datetime.fromisoformat(crawled)
            age_minutes = (datetime.now(timezone.utc) - dt).total_seconds() / 60
            return age_minutes > self._config.cache_ttl_minutes
        except ValueError:
            return True

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search using FTS5. BM25 ranking with title boost."""
        terms = query.strip()
        if not terms:
            return []

        conn = self._get_conn()

        # FTS5 query: quote each term for safety, prefix match with *
        fts_terms = " ".join(f'"{t}"*' for t in terms.split())

        try:
            rows = conn.execute(
                """SELECT p.*, bm25(pages_fts, 0, 10.0, 1.0) AS rank
                   FROM pages_fts fts
                   JOIN pages p ON p.id = fts.id
                   WHERE pages_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (fts_terms, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # Fallback if FTS query syntax fails
            return self._fallback_search(terms, limit)

        results = []
        for row in rows:
            d = self._row_to_dict(row)
            content = d.get("markdown_content", "")
            snippet = self._make_snippet(content, terms.lower().split())
            results.append(
                self._search_result(d, snippet, round(-row["rank"], 2), content)
            )
        return results

    def _fallback_search(self, query: str, limit: int) -> list[dict]:
        """Simple LIKE fallback if FTS query fails."""
        conn = self._get_conn()
        pattern = f"%{query}%"
        rows = conn.execute(
            "SELECT * FROM pages WHERE title LIKE ? OR markdown_content LIKE ? LIMIT ?",
            (pattern, pattern, limit),
        ).fetchall()
        results = []
        for row in rows:
            d = self._row_to_dict(row)
            content = d.get("markdown_content", "")
            snippet = self._make_snippet(content, query.lower().split())
            results.append(self._search_result(d, snippet, 1.0, content))
        return results

    @staticmethod
    def _search_result(d: dict, snippet: str, score: float, content: str) -> dict:
        return {
            "id": d["id"],
            "title": d["title"],
            "path": d.get("path", []),
            "webUrl": d.get("web_url", ""),
            "sourceType": d.get("source_type", "confluence"),
            "contentLength": len(content),
            "snippet": snippet,
            "score": score,
            "hint": f"Call get_page(\"{d['id']}\") to read full content",
        }

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        # Deserialise path from JSON string
        if isinstance(d.get("path"), str):
            try:
                d["path"] = json.loads(d["path"])
            except (json.JSONDecodeError, TypeError):
                d["path"] = []
        return d

    @staticmethod
    def _make_snippet(content: str, terms: list[str], max_len: int = 500) -> str:
        """Extract a snippet around the first matched term."""
        content_lower = content.lower()
        best_pos = len(content)
        for term in terms:
            pos = content_lower.find(term)
            if 0 <= pos < best_pos:
                best_pos = pos

        if best_pos >= len(content):
            return content[:max_len]

        start = max(0, best_pos - 50)
        end = start + max_len
        snippet = content[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."
        return snippet
