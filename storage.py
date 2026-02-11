import modal
import time

# Объявляем постоянные словари. 
# create_if_missing=True создаст их при первом запуске.
users_db = modal.Dict.from_name("nano-banana-users", create_if_missing=True)
sessions_db = modal.Dict.from_name("nano-banana-sessions", create_if_missing=True)

class Storage:
    @staticmethod
    def get_user(user_id: int):
        return users_db.get(user_id)

    @staticmethod
    def save_user(user_id: int, data: dict):
        current = users_db.get(user_id, {})
        # Обновляем поля
        current.update(data)
        current["updated_at"] = time.time()
        users_db[user_id] = current

    @staticmethod
    def get_session(user_id: int):
        return sessions_db.get(user_id, {"state": "IDLE", "data": {}})

    @staticmethod
    def set_session(user_id: int, state: str, data_updates: dict = None):
        current = sessions_db.get(user_id, {"state": "IDLE", "data": {}})
        new_data = current["data"]
        if data_updates:
            new_data.update(data_updates)
        
        sessions_db[user_id] = {
            "state": state,
            "data": new_data
        }
    
    @staticmethod
    def clear_session(user_id: int):
        sessions_db[user_id] = {"state": "IDLE", "data": {}}
