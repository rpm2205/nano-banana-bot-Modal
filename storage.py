import modal
import time
from copy import deepcopy

# Объявляем постоянные словари.
# create_if_missing=True создаст их при первом запуске.
users_db = modal.Dict.from_name("nano-banana-users", create_if_missing=True)
sessions_db = modal.Dict.from_name("nano-banana-sessions", create_if_missing=True)


class Storage:
    @staticmethod
    async def get_user(user_id: int):
        result = await users_db.get.aio(user_id)
        return result if result is not None else None

    @staticmethod
    async def save_user(user_id: int, data: dict):
        current = await users_db.get.aio(user_id)
        if current is None:
            current = {}
        # Обновляем поля
        current.update(data)
        current["updated_at"] = time.time()
        await users_db.put.aio(user_id, current)

    @staticmethod
    async def get_session(user_id: int):
        result = await sessions_db.get.aio(user_id)
        return result if result is not None else {"state": "IDLE", "data": {}}

    @staticmethod
    async def set_session(
        user_id: int, state: str, data_updates: dict = None, reset_data: bool = False
    ):
        current = await sessions_db.get.aio(user_id) or {"state": "IDLE", "data": {}}
        new_data = {} if reset_data else deepcopy(current.get("data", {}))
        if data_updates:
            new_data.update(deepcopy(data_updates))

        await sessions_db.put.aio(user_id, {"state": state, "data": new_data})

    @staticmethod
    async def clear_session(user_id: int):
        await sessions_db.put.aio(user_id, {"state": "IDLE", "data": {}})

    @staticmethod
    async def set_last_update_id(user_id: int, update_id: int):
        """
        Обновляет lastUpdateId в data текущей сессии одним циклом get+put
        и возвращает актуальный state после обновления.
        """
        current = await sessions_db.get.aio(user_id) or {"state": "IDLE", "data": {}}
        state = current.get("state", "IDLE")
        data = deepcopy(current.get("data", {}))
        data["lastUpdateId"] = update_id
        await sessions_db.put.aio(
            user_id,
            {
                "state": state,
                "data": data,
            },
        )
        return state
