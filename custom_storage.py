import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional

# Import the correct storage base class
try:
    from aiogram.contrib.fsm_storage.memory import BaseStorage  # aiogram 2.x
except ImportError:
    try:
        from aiogram.fsm.storage.base import BaseStorage  # aiogram 3.x
    except ImportError:
        # Minimal base class fallback
        class BaseStorage:
            pass

log = logging.getLogger("custom_storage")

class CustomJSONStorage(BaseStorage):
    """
    JSON file-based storage for FSM states (aiogram 2.x/3.x bilan mos).
    Signaturalari positional ham, keyword ham qabul qiladi.
    """

    def __init__(self, file_path: str = "data/fsm_states.json"):
        super().__init__()
        self.file_path = Path(file_path)
        self._data: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._load_data()

    def _load_data(self):
        """Load data from JSON file with error handling"""
        try:
            if self.file_path.exists():
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._data = data
                        # Ensure all records have proper structure
                        for key, value in list(self._data.items()):
                            if not isinstance(value, dict):
                                self._data[key] = {'state': None, 'data': {}}
                            else:
                                if 'data' not in value or not isinstance(value.get('data'), dict):
                                    value['data'] = {}
                                if 'state' not in value:
                                    value['state'] = None
                    else:
                        log.warning("Invalid data format in storage file, starting fresh")
                        self._data = {}
            else:
                self._data = {}
                log.info(f"Storage file {self.file_path} does not exist, starting fresh")
        except Exception as e:
            log.error(f"Could not load FSM storage from {self.file_path}: {e}")
            self._data = {}

    async def _save_data(self):
        """Save data to JSON file with error handling"""
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

            # Create a clean copy of data for saving
            clean_data = {}
            for key, value in self._data.items():
                if isinstance(value, dict):
                    clean_value = {
                        'state': value.get('state'),
                        'data': value.get('data', {}) if isinstance(value.get('data'), dict) else {}
                    }
                    # Save all records (hatto bo‘sh bo‘lsa ham) — lekin xohlasangiz shu yerda filtrlasangiz bo‘ladi
                    clean_data[key] = clean_value

            # Write atomically using a temporary file
            temp_file = self.file_path.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(clean_data, f, ensure_ascii=False, indent=2)

            # Atomic move
            temp_file.replace(self.file_path)

        except Exception as e:
            log.error(f"Could not save FSM storage to {self.file_path}: {e}")

    def _make_key(self, chat: Optional[int] = None, user: Optional[int] = None) -> str:
        """Generate storage key"""
        if user is None:
            user = 0
        if chat is None:
            return str(user)
        return f"{chat}:{user}"

    def _ensure_record(self, key: str) -> Dict[str, Any]:
        """Ensure a record exists with proper structure"""
        if key not in self._data or not isinstance(self._data[key], dict):
            self._data[key] = {'state': None, 'data': {}}

        record = self._data[key]
        if 'data' not in record or not isinstance(record.get('data'), dict):
            record['data'] = {}
        if 'state' not in record:
            record['state'] = None
        return record

    def _safe_dict_update(self, target: dict, source: Any) -> None:
        """Safely update dict, handling None and non-dict sources"""
        if source is None:
            return
        if isinstance(source, dict):
            target.update(source)
        else:
            try:
                if hasattr(source, 'items'):
                    target.update(source)
            except Exception as e:
                log.warning(f"Could not update dict with source {type(source)}: {e}")

    # ===============================
    # Core storage methods (positional + kwargs mos)
    # ===============================

    async def get_state(self, chat=None, user=None, default=None, **kwargs) -> Optional[str]:
        async with self._lock:
            try:
                key = self._make_key(chat, user)
                record = self._data.get(key, {})
                return record.get('state', default)
            except Exception as e:
                log.error(f"Error getting state for user {user}: {e}")
                return default

    async def get_data(self, chat=None, user=None, default=None, **kwargs) -> Dict[str, Any]:
        async with self._lock:
            try:
                key = self._make_key(chat, user)
                record = self._data.get(key, {})
                data = record.get('data', {})
                if not isinstance(data, dict):
                    data = {}
                return data.copy() if data else (default or {})
            except Exception as e:
                log.error(f"Error getting data for user {user}: {e}")
                return default or {}

    async def set_state(self, chat=None, user=None, state=None, **kwargs):
        async with self._lock:
            try:
                key = self._make_key(chat, user)
                record = self._ensure_record(key)
                record['state'] = state
                await self._save_data()
            except Exception as e:
                log.error(f"Error setting state for user {user}: {e}")

    async def set_data(self, chat=None, user=None, data=None, **kwargs):
        async with self._lock:
            try:
                key = self._make_key(chat, user)
                record = self._ensure_record(key)
                if data is None:
                    record['data'] = {}
                elif isinstance(data, dict):
                    record['data'] = data.copy()
                else:
                    log.warning(f"Invalid data type for user {user}: {type(data)}")
                    record['data'] = {}
                await self._save_data()
            except Exception as e:
                log.error(f"Error setting data for user {user}: {e}")

    async def update_data(self, chat=None, user=None, data=None, **kwargs):
        async with self._lock:
            try:
                key = self._make_key(chat, user)
                record = self._ensure_record(key)

                if data is not None:
                    self._safe_dict_update(record['data'], data)
                if kwargs:
                    self._safe_dict_update(record['data'], kwargs)

                await self._save_data()
            except Exception as e:
                log.error(f"Error updating data for user {user}: {e}")

    async def finish(self, chat=None, user=None, **kwargs):
        async with self._lock:
            try:
                key = self._make_key(chat, user)
                self._data.pop(key, None)
                await self._save_data()
            except Exception as e:
                log.error(f"Error finishing session for user {user}: {e}")

    # ===============================
    # Utilities
    # ===============================

    async def reset_all(self, full=True):
        async with self._lock:
            try:
                self._data.clear()
                if full:
                    await self._save_data()
                log.info("Storage reset completed")
            except Exception as e:
                log.error(f"Error resetting storage: {e}")

    async def get_states_list(self) -> Dict[str, str]:
        async with self._lock:
            try:
                states = {}
                for key, record in self._data.items():
                    if isinstance(record, dict) and record.get('state'):
                        states[key] = record['state']
                return states
            except Exception as e:
                log.error(f"Error getting states list: {e}")
                return {}

    async def get_users_in_state(self, state_name: str) -> list:
        async with self._lock:
            try:
                users = []
                for key, record in self._data.items():
                    if isinstance(record, dict) and record.get('state') == state_name:
                        # Extract user_id from key (format: "chat:user" or just "user")
                        if ':' in key:
                            user_id = int(key.split(':')[-1])
                        else:
                            user_id = int(key)
                        users.append(user_id)
                return users
            except Exception as e:
                log.error(f"Error getting users in state {state_name}: {e}")
                return []

    async def cleanup_old_sessions(self, max_age_hours: int = 24):
        async with self._lock:
            try:
                import time
                cutoff_time = time.time() - (max_age_hours * 3600)
                cleaned = 0

                keys_to_remove = []
                for key, record in self._data.items():
                    if isinstance(record, dict):
                        timestamp = record.get('timestamp', time.time())
                        if timestamp < cutoff_time:
                            keys_to_remove.append(key)

                for key in keys_to_remove:
                    self._data.pop(key, None)
                    cleaned += 1

                if cleaned > 0:
                    await self._save_data()
                    log.info(f"Cleaned up {cleaned} old sessions")

                return cleaned
            except Exception as e:
                log.error(f"Error cleaning up old sessions: {e}")
                return 0

    async def close(self) -> None:
        try:
            await self._save_data()
            log.info("Storage closed successfully")
        except Exception as e:
            log.error(f"Error closing storage: {e}")

    async def wait_closed(self):
        pass

    def __del__(self):
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._save_data())
            else:
                asyncio.run(self._save_data())
        except Exception:
            pass
