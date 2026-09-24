"""Where assessments live, and what a series of them is worth (FR-10, FR-11).

A single stream check is a snapshot and is easy to dismiss - the water was cloudy
because it rained, the volunteer was new, it was one bad day. A *series* at the
same spot is something a municipality has to answer, and it is the only way a
citizen-science programme produces early warning rather than anecdote. So
persistence is not an implementation detail here; the repeat visit is the
product.

Design notes:

* **SQLite through the standard library.** One file, no service, no migration
  story to get wrong in a week, and it runs identically on a laptop, in the demo
  container and on a free-tier host. ``:memory:`` gives tests a real database
  rather than a mock of one.
* **A site is a place on the ground, not a row someone created.** Coordinates
  round to roughly a hundred metres to form ``site_key``, so a volunteer standing
  near yesterday's spot extends yesterday's series instead of starting a new one.
  Nobody has to name or register anything.
* **The full assessment is kept as JSON** next to the extracted columns. The
  columns exist to be queried; the JSON exists so a stored assessment can always
  be shown exactly as it was produced, even after the rules change. Every row
  records the version that produced it.
* **A review replaces a visit, it does not add one.** When a person confirms or
  corrects what the model proposed, the new assessment carries ``supersedes`` and
  the row it replaces is marked and drops out of every count, trend and feed
  while staying fetchable by id. Without this, the most careful volunteers -
  the ones who check the model's work - would manufacture trends by reviewing.
* **Contributors are anonymous by construction.** A contributor is an opaque id
  the browser generates and keeps; there is no account, no email and no way back
  to a person. It is enough for a streak and a badge (Track 5) and not enough to
  identify anyone.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .assess import Assessment
from .bioindex import Band
from .onehealth import Level

DEFAULT_DB = os.environ.get("AQUAPLOT_DB", "aquaplot.db")
SITE_PRECISION = 3  # decimal degrees, about 110 m: close enough to be "the same spot"
RECENT_DAYS = 90

BAND_ORDINAL: dict[str, int] = {Band.HIGH: 5, Band.GOOD: 4, Band.MODERATE: 3, Band.POOR: 2, Band.BAD: 1}
LEVEL_ORDINAL: dict[str, int] = {Level.OK: 0, Level.WATCH: 1, Level.CONCERN: 2, Level.ALERT: 3}

SCHEMA = """
CREATE TABLE IF NOT EXISTS assessments (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    site_key      TEXT NOT NULL,
    site_name     TEXT,
    lat           REAL,
    lon           REAL,
    place_id      INTEGER,
    place_name    TEXT,
    band          TEXT NOT NULL,
    band_ordinal  INTEGER NOT NULL,
    bmwp          REAL,
    aspt          REAL,
    families      INTEGER,
    ept_families  INTEGER,
    pressure      REAL,
    certainty     REAL,
    overall_level TEXT,
    level_ordinal INTEGER,
    invasives     INTEGER DEFAULT 0,
    confirmations INTEGER DEFAULT 0,
    observer      TEXT,
    contributor   TEXT,
    version       TEXT,
    superseded_by TEXT,
    payload       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS site_names (
    site_key  TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    named_at  TEXT NOT NULL
);
"""

# Indexes are created after the migration, because one of them names a column an
# older database will not have until the migration has added it.
INDEXES = """
CREATE INDEX IF NOT EXISTS ix_site ON assessments(site_key, created_at);
CREATE INDEX IF NOT EXISTS ix_live ON assessments(superseded_by, created_at);
CREATE INDEX IF NOT EXISTS ix_time ON assessments(created_at);
CREATE INDEX IF NOT EXISTS ix_contributor ON assessments(contributor, created_at);
"""


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def site_key(lat: float | None, lon: float | None) -> str | None:
    """A stable key for 'this spot on the stream'. None when there are no coordinates."""
    if lat is None or lon is None:
        return None
    return f"{round(lat, SITE_PRECISION):.{SITE_PRECISION}f},{round(lon, SITE_PRECISION):.{SITE_PRECISION}f}"


@dataclass
class Store:
    path: str = DEFAULT_DB

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        # check_same_thread=False plus one lock: the app is a single process and
        # every write here is tiny, so a connection pool would be ceremony.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._write() as c:
            c.executescript(SCHEMA)
            self._migrate(c)
            c.executescript(INDEXES)

    def _migrate(self, cursor: sqlite3.Cursor) -> None:
        """Add columns a database written by an earlier version is missing.

        Forward-only and additive: a running deployment must survive a schema
        change without anyone deleting the data citizens contributed.
        """
        have = {row["name"] for row in cursor.execute("PRAGMA table_info(assessments)").fetchall()}
        for column, ddl in (("superseded_by", "TEXT"),):
            if column not in have:
                cursor.execute(f"ALTER TABLE assessments ADD COLUMN {column} {ddl}")

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            finally:
                cur.close()

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ---- writing ------------------------------------------------------------

    def save(self, assessment: Assessment, contributor: str | None = None) -> str | None:
        """Store one assessment. Returns its site key, or None if it had no coordinates.

        An assessment without coordinates is still stored - the reading is real -
        but it can never join a series, which is why the pipeline penalises it.
        """
        d = assessment.as_dict()
        key = site_key(assessment.region.lat, assessment.region.lon) or "unlocated"
        place = assessment.region.place
        with self._write() as c:
            c.execute(
                """INSERT OR REPLACE INTO assessments
                   (id, created_at, site_key, site_name, lat, lon, place_id, place_name, band, band_ordinal,
                    bmwp, aspt, families, ept_families, pressure, certainty, overall_level, level_ordinal,
                    invasives, confirmations, observer, contributor, version, superseded_by, payload)
                   VALUES
                   (:id,:created_at,:site_key,:site_name,:lat,:lon,:place_id,:place_name,:band,:band_ordinal,
                    :bmwp,:aspt,:families,:ept_families,:pressure,:certainty,:overall_level,:level_ordinal,
                    :invasives,:confirmations,:observer,:contributor,:version,NULL,:payload)""",
                {
                    "id": assessment.id,
                    "created_at": assessment.created_at,
                    "site_key": key,
                    "site_name": assessment.site_name,
                    "lat": assessment.region.lat,
                    "lon": assessment.region.lon,
                    "place_id": place.id if place else None,
                    "place_name": place.display_name if place else None,
                    "band": assessment.ecology.band.value,
                    "band_ordinal": BAND_ORDINAL[assessment.ecology.band],
                    "bmwp": assessment.ecology.bmwp,
                    "aspt": assessment.ecology.aspt,
                    "families": assessment.ecology.families,
                    "ept_families": assessment.ecology.ept_families,
                    "pressure": assessment.pressures.pressure,
                    "certainty": assessment.certainty,
                    "overall_level": assessment.signal.worst.value,
                    "level_ordinal": LEVEL_ORDINAL[assessment.signal.worst],
                    "invasives": len(assessment.invasives),
                    "confirmations": assessment.confirmations,
                    "observer": assessment.observer,
                    "contributor": contributor,
                    "version": assessment.version,
                    "payload": json.dumps(d),
                },
            )
            if assessment.supersedes:
                # The superseded row stays fetchable by id - an audit trail of what
                # the model said before a person corrected it - but leaves every
                # count, trend and feed.
                c.execute(
                    "UPDATE assessments SET superseded_by = ? WHERE id = ? AND superseded_by IS NULL",
                    (assessment.id, assessment.supersedes),
                )
            if assessment.site_name and key != "unlocated":
                c.execute(
                    "INSERT OR REPLACE INTO site_names VALUES (?,?,?)",
                    (key, assessment.site_name, assessment.created_at),
                )
        return None if key == "unlocated" else key

    # ---- reading ------------------------------------------------------------

    def get(self, assessment_id: str) -> dict[str, Any] | None:
        rows = self._query("SELECT payload FROM assessments WHERE id = ?", (assessment_id,))
        return json.loads(rows[0]["payload"]) if rows else None

    def sites(self, bbox: tuple[float, float, float, float] | None = None, limit: int = 500) -> list[dict[str, Any]]:
        """Every site with at least one assessment, latest first, with its trend.

        This is what the map draws and the dashboard ranks: one row per place on
        the ground, not one per visit.
        """
        where, params = "WHERE superseded_by IS NULL AND site_key != 'unlocated'", []
        if bbox is not None:
            south, west, north, east = bbox
            where += " AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?"
            params += [south, north, west, east]
        rows = self._query(
            f"""SELECT site_key, COUNT(*) n, MAX(created_at) last_seen, MIN(created_at) first_seen,
                       AVG(band_ordinal) mean_band, SUM(invasives) invasives
                FROM assessments {where} GROUP BY site_key ORDER BY last_seen DESC LIMIT ?""",
            tuple(params + [limit]),
        )
        out = []
        for row in rows:
            history = self.history(row["site_key"])
            latest = history[0]
            out.append(
                {
                    "site_key": row["site_key"],
                    "name": self.name_of(row["site_key"]) or latest.get("site_name") or latest.get("place_name") or "Unnamed site",
                    "lat": latest["lat"],
                    "lon": latest["lon"],
                    "place": latest.get("place_name"),
                    "assessments": row["n"],
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                    "band": latest["band"],
                    "band_ordinal": latest["band_ordinal"],
                    "pressure": latest["pressure"],
                    "level": latest["overall_level"],
                    "invasives": row["invasives"],
                    "trend": trend_of(history),
                }
            )
        return out

    def history(self, key: str, limit: int = 50) -> list[dict[str, Any]]:
        """Every assessment at one site, newest first."""
        rows = self._query(
            """SELECT id, created_at, site_name, place_name, lat, lon, band, band_ordinal, bmwp, aspt,
                      families, ept_families, pressure, certainty, overall_level, invasives, confirmations
               FROM assessments WHERE site_key = ? AND superseded_by IS NULL ORDER BY created_at DESC LIMIT ?""",
            (key, limit),
        )
        return [dict(r) for r in rows]

    def name_of(self, key: str) -> str | None:
        rows = self._query("SELECT name FROM site_names WHERE site_key = ?", (key,))
        return rows[0]["name"] if rows else None

    def rename(self, key: str, name: str) -> None:
        with self._write() as c:
            c.execute("INSERT OR REPLACE INTO site_names VALUES (?,?,?)", (key, name, datetime.now(UTC).isoformat()))

    def nearby(self, lat: float, lon: float, radius_m: float = 250.0, limit: int = 5) -> list[dict[str, Any]]:
        """Sites within ``radius_m`` of a point, nearest first.

        This is what lets the app ask "is this the stretch you checked in June?"
        instead of silently starting a new series because someone stood four
        metres further along the bank. The site grid already merges anything
        within ~100 m; this catches the wider case and puts the decision to the
        person, which is the only one who actually knows.
        """
        # A degree of latitude is ~111 km everywhere; longitude shrinks with
        # latitude. Good enough over a few hundred metres, and it avoids a
        # geospatial dependency for one query.
        dlat = radius_m / 111_320
        dlon = radius_m / max(1.0, 111_320 * math.cos(math.radians(lat)))
        rows = self._query(
            """SELECT site_key, lat, lon, MAX(created_at) last_seen, COUNT(*) n
               FROM assessments
               WHERE superseded_by IS NULL AND site_key != 'unlocated'
                 AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
               GROUP BY site_key""",
            (lat - dlat, lat + dlat, lon - dlon, lon + dlon),
        )
        out = []
        for row in rows:
            metres = haversine_m(lat, lon, row["lat"], row["lon"])
            if metres > radius_m:
                continue
            history = self.history(row["site_key"], limit=2)
            out.append(
                {
                    "site_key": row["site_key"],
                    "name": self.name_of(row["site_key"]) or history[0].get("site_name") or history[0].get("place_name") or "Unnamed site",
                    "lat": row["lat"],
                    "lon": row["lon"],
                    "metres_away": round(metres),
                    "assessments": row["n"],
                    "last_seen": row["last_seen"],
                    "band": history[0]["band"],
                }
            )
        return sorted(out, key=lambda s: s["metres_away"])[:limit]

    def export_rows(self, limit: int = 10000) -> list[dict[str, Any]]:
        """Every live assessment, flattened, for the CSV export."""
        rows = self._query(
            """SELECT id, created_at, site_key, site_name, place_name, lat, lon, band, band_ordinal,
                      bmwp, aspt, families, ept_families, pressure, certainty, overall_level,
                      invasives, confirmations, observer, version
               FROM assessments WHERE superseded_by IS NULL ORDER BY created_at LIMIT ?""",
            (limit,),
        )
        # Full float precision on a derived index is noise in a spreadsheet, and
        # invites a reader to believe the number is more exact than it is.
        rounding = {"bmwp": 1, "aspt": 2, "pressure": 1, "certainty": 1, "lat": 6, "lon": 6}
        return [
            {k: (round(v, rounding[k]) if k in rounding and isinstance(v, float) else v) for k, v in dict(r).items()}
            for r in rows
        ]

    def recent(self, days: int = RECENT_DAYS, limit: int = 200) -> list[dict[str, Any]]:
        since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        rows = self._query(
            """SELECT id, created_at, site_key, site_name, place_name, lat, lon, band, pressure,
                      overall_level, certainty, invasives
               FROM assessments WHERE created_at >= ? AND superseded_by IS NULL ORDER BY created_at DESC LIMIT ?""",
            (since, limit),
        )
        return [dict(r) for r in rows]

    def alerts(self, days: int = 30) -> list[dict[str, Any]]:
        """Sites whose most recent assessment reached alert or concern - the early-warning feed."""
        since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        rows = self._query(
            """SELECT a.* FROM assessments a
               JOIN (SELECT site_key, MAX(created_at) m FROM assessments WHERE superseded_by IS NULL GROUP BY site_key) t
                 ON a.site_key = t.site_key AND a.created_at = t.m
               WHERE a.superseded_by IS NULL AND a.level_ordinal >= 2 AND a.created_at >= ?
               ORDER BY a.level_ordinal DESC, a.created_at DESC""",
            (since,),
        )
        out = []
        for row in rows:
            payload = json.loads(row["payload"])
            findings = [
                f
                for domain in payload["one_health"]["domains"]
                for f in domain["findings"]
                if f["level"] in ("alert", "concern")
            ]
            out.append(
                {
                    "id": row["id"],
                    "site_key": row["site_key"],
                    "name": self.name_of(row["site_key"]) or row["site_name"] or row["place_name"] or "Unnamed site",
                    "lat": row["lat"],
                    "lon": row["lon"],
                    "created_at": row["created_at"],
                    "level": row["overall_level"],
                    "band": row["band"],
                    "headline": payload["one_health"]["headline"],
                    "findings": findings[:3],
                }
            )
        return out

    def summary(self) -> dict[str, Any]:
        """The numbers the dashboard leads with (FR-11)."""
        rows = self._query(
            """SELECT COUNT(*) n, COUNT(DISTINCT site_key) sites, COUNT(DISTINCT contributor) people,
                      AVG(band_ordinal) mean_band, AVG(pressure) mean_pressure, SUM(invasives) invasives,
                      SUM(confirmations) confirmations
               FROM assessments WHERE superseded_by IS NULL"""
        )
        row = dict(rows[0]) if rows else {}
        bands = {
            r["band"]: r["n"]
            for r in self._query("SELECT band, COUNT(*) n FROM assessments WHERE superseded_by IS NULL GROUP BY band")
        }
        levels = {
            r["overall_level"]: r["n"]
            for r in self._query("SELECT overall_level, COUNT(*) n FROM assessments WHERE superseded_by IS NULL GROUP BY overall_level")
        }
        months = [
            {"month": r["m"], "assessments": r["n"], "mean_band": round(r["mb"], 2) if r["mb"] is not None else None}
            for r in self._query(
                """SELECT substr(created_at,1,7) m, COUNT(*) n, AVG(band_ordinal) mb
                   FROM assessments WHERE superseded_by IS NULL GROUP BY m ORDER BY m"""
            )
        ]
        return {
            "assessments": row.get("n", 0),
            "sites": row.get("sites", 0),
            "contributors": row.get("people", 0),
            "mean_band_ordinal": round(row["mean_band"], 2) if row.get("mean_band") is not None else None,
            "mean_pressure": round(row["mean_pressure"], 1) if row.get("mean_pressure") is not None else None,
            "invasive_records": row.get("invasives", 0),
            "human_confirmations": row.get("confirmations", 0),
            "by_band": bands,
            "by_level": levels,
            "by_month": months,
        }

    def progress(self, contributor: str) -> dict[str, Any]:
        """One contributor's record, and the badges it has earned (Track 5).

        Badges reward the behaviours that make the data useful - returning to the
        same site, confirming what the model guessed, covering more than one
        stream - rather than raw volume, which would reward spamming the map.
        """
        rows = self._query(
            """SELECT created_at, site_key, band_ordinal, confirmations, invasives
               FROM assessments WHERE contributor = ? AND superseded_by IS NULL ORDER BY created_at""",
            (contributor,),
        )
        if not rows:
            return {"assessments": 0, "sites": 0, "confirmations": 0, "badges": [], "next": FIRST_STEP}
        sites = {r["site_key"] for r in rows}
        repeats = len(rows) - len(sites)
        confirmations = sum(r["confirmations"] for r in rows)
        months = sorted({r["created_at"][:7] for r in rows})
        streak = longest_run(months)
        earned = [b for b in BADGES if b["test"](len(rows), len(sites), repeats, confirmations, streak, sum(r["invasives"] for r in rows))]
        remaining = [b for b in BADGES if b not in earned]
        return {
            "assessments": len(rows),
            "sites": len(sites),
            "repeat_visits": repeats,
            "confirmations": confirmations,
            "month_streak": streak,
            "badges": [{"key": b["key"], "name": b["name"], "why": b["why"]} for b in earned],
            "next": {"key": remaining[0]["key"], "name": remaining[0]["name"], "why": remaining[0]["why"]} if remaining else None,
        }


def trend_of(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Is this site getting better or worse? Newest first, as ``history`` returns it."""
    if len(history) < 2:
        return {"direction": "new", "detail": "One assessment so far. A second visit turns this into a trend."}
    latest, previous = history[0]["band_ordinal"], history[1]["band_ordinal"]
    change = latest - previous
    if change > 0:
        return {"direction": "improving", "detail": f"Improved from {history[1]['band']} to {history[0]['band']}."}
    if change < 0:
        return {"direction": "declining", "detail": f"Declined from {history[1]['band']} to {history[0]['band']}."}
    return {"direction": "stable", "detail": f"Held at {history[0]['band']} across {len(history)} assessments."}


def longest_run(months: list[str]) -> int:
    """Longest run of consecutive calendar months in a sorted list of YYYY-MM strings."""
    best = run = 0
    previous = None
    for m in months:
        year, month = int(m[:4]), int(m[5:7])
        index = year * 12 + month
        run = run + 1 if previous is not None and index == previous + 1 else 1
        best, previous = max(best, run), index
    return best


FIRST_STEP = {"key": "first-check", "name": "First check", "why": "Record one stream assessment."}

# The behaviours worth rewarding, in the order a new volunteer meets them.
BADGES: list[dict[str, Any]] = [
    {"key": "first-check", "name": "First check", "why": "Recorded a stream assessment.",
     "test": lambda n, sites, repeats, conf, streak, inv: n >= 1},
    {"key": "reviewer", "name": "Reviewer", "why": "Confirmed or corrected what the model suggested, five times.",
     "test": lambda n, sites, repeats, conf, streak, inv: conf >= 5},
    {"key": "returner", "name": "Returner", "why": "Went back to the same spot - the visit that turns a reading into a trend.",
     "test": lambda n, sites, repeats, conf, streak, inv: repeats >= 1},
    {"key": "three-streams", "name": "Three streams", "why": "Assessed three different sites.",
     "test": lambda n, sites, repeats, conf, streak, inv: sites >= 3},
    {"key": "sentinel", "name": "Sentinel", "why": "Recorded an invasive species, the sighting that makes early detection possible.",
     "test": lambda n, sites, repeats, conf, streak, inv: inv >= 1},
    {"key": "season-watch", "name": "Season watch", "why": "Assessed in three consecutive months.",
     "test": lambda n, sites, repeats, conf, streak, inv: streak >= 3},
    {"key": "keeper", "name": "Stream keeper", "why": "Ten assessments across at least two sites.",
     "test": lambda n, sites, repeats, conf, streak, inv: n >= 10 and sites >= 2},
]
