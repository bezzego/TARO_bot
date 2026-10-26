"""FSM-хранилище в SQLite: состояние диалога переживает перезапуск бота.

С MemoryStorage любой рестарт обрывал запись на середине: клиент занимал слот,
а прислать чек уже не мог («нет активной записи»).
"""
import json
from typing import Any, Mapping

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey, StateType

import database


def _key(key: StorageKey) -> str:
    return ":".join(str(p) for p in (
        key.bot_id, key.chat_id, key.user_id, key.thread_id, key.business_connection_id, key.destiny,
    ))


class SQLiteStorage(BaseStorage):
    """Использует общее соединение database.db (таблица fsm создаётся в init_db)."""

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        await database.db.execute(
            "INSERT INTO fsm (key, state) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET state=excluded.state",
            (_key(key), value))
        await database.db.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        cur = await database.db.execute("SELECT state FROM fsm WHERE key=?", (_key(key),))
        row = await cur.fetchone()
        return row["state"] if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        await database.db.execute(
            "INSERT INTO fsm (key, data) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET data=excluded.data",
            (_key(key), json.dumps(dict(data), ensure_ascii=False)))
        await database.db.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        cur = await database.db.execute("SELECT data FROM fsm WHERE key=?", (_key(key),))
        row = await cur.fetchone()
        if not row or not row["data"]:
            return {}
        try:
            return json.loads(row["data"])
        except ValueError:
            return {}

    async def close(self) -> None:
        pass
