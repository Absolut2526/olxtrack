import aiosqlite
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
from config import DB_PATH

async def init_db():
    """Initializes the database and creates/migrates tables if needed."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                query TEXT NOT NULL,
                min_price REAL,
                max_price REAL,
                only_private INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seen_offers (
                subscription_id INTEGER NOT NULL,
                offer_id INTEGER NOT NULL,
                last_price REAL,
                seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (subscription_id, offer_id)
            );
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_seen_sub ON seen_offers(subscription_id);")
        
        # Migrations for existing DBs
        try:
            await db.execute("ALTER TABLE subscriptions ADD COLUMN only_private INTEGER DEFAULT 0;")
        except Exception:
            pass  # Already exists

        try:
            await db.execute("ALTER TABLE seen_offers ADD COLUMN last_price REAL;")
        except Exception:
            pass  # Already exists

        await db.commit()

async def add_subscription(
    user_id: int,
    query: str,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    only_private: int = 0
) -> int:
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO subscriptions 
               (user_id, query, min_price, max_price, only_private, is_active, created_at) 
               VALUES (?, ?, ?, ?, ?, 1, ?)""",
            (user_id, query.strip(), min_price, max_price, only_private, now_iso)
        )
        await db.commit()
        return cursor.lastrowid

async def update_subscription_price(sub_id: int, user_id: int, min_price: Optional[float], max_price: Optional[float]) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE subscriptions SET min_price = ?, max_price = ? WHERE id = ? AND user_id = ?",
            (min_price, max_price, sub_id, user_id)
        )
        await db.commit()
        return cursor.rowcount > 0

async def toggle_private_filter(sub_id: int, user_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT only_private FROM subscriptions WHERE id = ? AND user_id = ?",
            (sub_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            new_status = 0 if row[0] == 1 else 1

        await db.execute(
            "UPDATE subscriptions SET only_private = ? WHERE id = ? AND user_id = ?",
            (new_status, sub_id, user_id)
        )
        await db.commit()
        return new_status

async def get_user_subscriptions(user_id: int) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, query, min_price, max_price, only_private, is_active, created_at FROM subscriptions WHERE user_id = ? ORDER BY id DESC",
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_subscription_by_id(sub_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, query, min_price, max_price, only_private, is_active, created_at FROM subscriptions WHERE id = ? AND user_id = ?",
            (sub_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def delete_subscription(sub_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM subscriptions WHERE id = ? AND user_id = ?",
            (sub_id, user_id)
        )
        await db.execute("DELETE FROM seen_offers WHERE subscription_id = ?", (sub_id,))
        await db.commit()
        return cursor.rowcount > 0

async def toggle_subscription(sub_id: int, user_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT is_active FROM subscriptions WHERE id = ? AND user_id = ?",
            (sub_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            new_status = 0 if row[0] == 1 else 1

        await db.execute(
            "UPDATE subscriptions SET is_active = ? WHERE id = ? AND user_id = ?",
            (new_status, sub_id, user_id)
        )
        await db.commit()
        return new_status

async def get_all_active_subscriptions() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, user_id, query, min_price, max_price, only_private, created_at FROM subscriptions WHERE is_active = 1"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_seen_offer(sub_id: int, offer_id: int) -> Tuple[bool, Optional[float]]:
    """Returns (is_seen, last_price)"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT last_price FROM seen_offers WHERE subscription_id = ? AND offer_id = ?",
            (sub_id, offer_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row is not None:
                return True, row[0]
            return False, None

async def mark_offer_seen(sub_id: int, offer_id: int, price: Optional[float] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO seen_offers (subscription_id, offer_id, last_price) VALUES (?, ?, ?) ON CONFLICT(subscription_id, offer_id) DO UPDATE SET last_price=excluded.last_price",
            (sub_id, offer_id, price)
        )
        await db.commit()

async def mark_offers_seen_batch(sub_id: int, offers_data: List[Tuple[int, Optional[float]]]):
    if not offers_data:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO seen_offers (subscription_id, offer_id, last_price) VALUES (?, ?, ?) ON CONFLICT(subscription_id, offer_id) DO UPDATE SET last_price=excluded.last_price",
            [(sub_id, oid, p) for oid, p in offers_data]
        )
        await db.commit()
