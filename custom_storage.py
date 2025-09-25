import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional

# Import the correct storage base class
try:
    from aiogram.contrib.fsm_storage.memory import BaseStorage
except ImportError:
    try:
        from aiogram.fsm.storage.base import BaseStorage
    except ImportError:
        # Create a minimal base class if nothing works
        class BaseStorage:
            pass

log = logging.getLogger("custom_storage")

class CustomJSONStorage(BaseStorage):
    """
    Bulletproof JSON file-based storage for FSM states.
    Handles all edge cases and None values gracefully.
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
                        for key, value in self._data.items():
                            if not isinstance(value, dict):
                                self._data[key] = {'state': None, 'data': {}}
                            else:
                                if 'data' not in value:
                                    value['data'] = {}
                                elif value['data'] is None:
                                    value['data'] = {}
                                elif not isinstance(value['data'], dict):
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
                    # Only save non-empty records
                    if clean_value['state'] or clean_value['data']:
                        clean_data[key] = clean_value
            
            # Write atomically using a temporary file
            temp_file = self.file_path.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(clean_data, f, ensure_ascii=False, indent=2)
            
            # Atomic move
            temp_file.replace(self.file_path)
            
        except Exception as e:
            log.error(f"Could not save FSM storage to {self.file_path}: {e}")
    
    def _make_key(self, chat: Optional[int] = None, user: int = 0) -> str:
        """Generate storage key"""
        if chat is None:
            return str(user)
        return f"{chat}:{user}"
    
    def _ensure_record(self, key: str) -> Dict[str, Any]:
        """Ensure a record exists with proper structure"""
        if key not in self._data:
            self._data[key] = {'state': None, 'data': {}}
        
        record = self._data[key]
        
        # Guarantee proper structure
        if not isinstance(record, dict):
            record = {'state': None, 'data': {}}
            self._data[key] = record
        
        if 'data' not in record:
            record['data'] = {}
        elif record['data'] is None:
            record['data'] = {}
        elif not isinstance(record['data'], dict):
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
            # If source is not a dict, try to convert or ignore
            try:
                if hasattr(source, 'items'):
                    target.update(source)
            except Exception as e:
                log.warning(f"Could not update dict with source {type(source)}: {e}")
    
    # ===============================
    # Core storage methods
    # ===============================
    
    async def get_state(self, *, chat: Optional[int] = None, user: int, default: Optional[str] = None) -> Optional[str]:
        """Get current state for user"""
        async with self._lock:
            try:
                key = self._make_key(chat, user)
                record = self._data.get(key, {})
                return record.get('state', default)
            except Exception as e:
                log.error(f"Error getting state for user {user}: {e}")
                return default
    
    async def get_data(self, *, chat: Optional[int] = None, user: int, default: Optional[dict] = None) -> Dict[str, Any]:
        """Get user data"""
        async with self._lock:
            try:
                key = self._make_key(chat, user)
                record = self._data.get(key, {})
                data = record.get('data', {})
                
                # Ensure we always return a dict
                if not isinstance(data, dict):
                    data = {}
                
                return data.copy() if data else (default or {})
            except Exception as e:
                log.error(f"Error getting data for user {user}: {e}")
                return default or {}
    
    async def set_state(self, *, chat: Optional[int] = None, user: int, state: Optional[str] = None):
        """Set user state"""
        async with self._lock:
            try:
                key = self._make_key(chat, user)
                record = self._ensure_record(key)
                record['state'] = state
                
                # Clean up empty records
                if not record['state'] and not record['data']:
                    self._data.pop(key, None)
                
                await self._save_data()
            except Exception as e:
                log.error(f"Error setting state for user {user}: {e}")
    
    async def set_data(self, *, chat: Optional[int] = None, user: int, data: Dict[str, Any]):
        """Set user data"""
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
                
                # Clean up empty records
                if not record['state'] and not record['data']:
                    self._data.pop(key, None)
                
                await self._save_data()
            except Exception as e:
                log.error(f"Error setting data for user {user}: {e}")
    
    async def update_data(self, *, chat: Optional[int] = None, user: int, data: Dict[str, Any], **kwargs):
        """Update user data (merge with existing) - BULLETPROOF VERSION"""
        async with self._lock:
            try:
                key = self._make_key(chat, user)
                record = self._ensure_record(key)
                
                # At this point record['data'] is guaranteed to be a dict
                # But let's be extra safe about the input data
                
                if data is not None:
                    self._safe_dict_update(record['data'], data)
                
                if kwargs:
                    self._safe_dict_update(record['data'], kwargs)
                
                await self._save_data()
            except Exception as e:
                log.error(f"Error updating data for user {user}: {e}")
    
    async def finish(self, *, chat: Optional[int] = None, user: int):
        """Clear all user data and state"""
        async with self._lock:
            try:
                key = self._make_key(chat, user)
                self._data.pop(key, None)
                await self._save_data()
            except Exception as e:
                log.error(f"Error finishing session for user {user}: {e}")
    
    # ===============================
    # Additional utility methods
    # ===============================
    
    async def reset_all(self, full=True):
        """Reset all storage data"""
        async with self._lock:
            try:
                self._data.clear()
                if full:
                    await self._save_data()
                log.info("Storage reset completed")
            except Exception as e:
                log.error(f"Error resetting storage: {e}")
    
    async def get_states_list(self) -> Dict[str, str]:
        """Get all active states (for debugging)"""
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
        """Get all users currently in a specific state"""
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
        """Clean up old sessions (if you add timestamps to records)"""
        async with self._lock:
            try:
                import time
                cutoff_time = time.time() - (max_age_hours * 3600)
                cleaned = 0
                
                keys_to_remove = []
                for key, record in self._data.items():
                    # If record has a timestamp and it's old, mark for removal
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
        """Close storage and save data"""
        try:
            await self._save_data()
            log.info("Storage closed successfully")
        except Exception as e:
            log.error(f"Error closing storage: {e}")
    
    async def wait_closed(self):
        """Wait for storage to close (compatibility method)"""
        pass
    
    def __del__(self):
        """Ensure data is saved on cleanup"""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._save_data())
            else:
                asyncio.run(self._save_data())
        except Exception:
            pass