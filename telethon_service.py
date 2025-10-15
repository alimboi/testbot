import logging
import asyncio
from typing import List, Dict, Tuple, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChatAdminRequiredError
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import (
    Channel, Chat,
    ChannelParticipantsSearch,
    ChannelParticipantsAdmins,
)

log = logging.getLogger("telethon_service")


class TelethonService:
    """
    Telethon service (bot token bilan). Guruh a'zolarini olish va info uchun.
    """

    def __init__(self, api_id: int, api_hash: str, bot_token: str, session_file: str = "telethon_session"):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.session_file = session_file
        self.client: Optional[TelegramClient] = None
        self._is_connected = False

    async def start(self) -> bool:
        """Initialize and start Telethon client"""
        try:
            # Qo‘shimcha barqarorlik parametrlari
            self.client = TelegramClient(
                self.session_file,
                self.api_id,
                self.api_hash,
                connection_retries=None,
                timeout=15
            )
            await self.client.start(bot_token=self.bot_token)
            self._is_connected = True
            log.info("Telethon client started successfully")
            return True
        except Exception as e:
            log.error(f"Failed to start Telethon client: {e}")
            self._is_connected = False
            return False

    async def stop(self):
        """Stop Telethon client"""
        if self.client and self._is_connected:
            await self.client.disconnect()
            self._is_connected = False
            log.info("Telethon client stopped")

    async def is_connected(self) -> bool:
        """Check if client is connected"""
        try:
            return bool(self._is_connected and self.client and await self.client.is_connected())
        except Exception:
            return False

    async def fetch_group_members(
        self,
        group_id: int,
        exclude_admins: bool = True,
        exclude_bots: bool = True
    ) -> Tuple[List[Dict], int]:
        """
        Bot client orqali ko‘rinadigan a'zolarni olish.
        """
        if not await self.is_connected():
            log.error("Telethon client not connected")
            return [], 0

        try:
            entity = await self.client.get_entity(group_id)
            members: List[Dict] = []
            admin_ids = set()

            # Adminlar ro‘yxatini to‘g‘ri olish
            if exclude_admins:
                try:
                    admins = await self.client.get_participants(entity, filter=ChannelParticipantsAdmins)
                    admin_ids = {u.id for u in admins}
                except Exception as e:
                    log.warning(f"Could not fetch admins for group {group_id}: {e}")

            if isinstance(entity, Channel):
                total_count = getattr(entity, 'participants_count', 0) or 0
                participants = []
                offset = 0
                limit = 100

                while True:
                    try:
                        chunk = await self.client(GetParticipantsRequest(
                            channel=entity,
                            filter=ChannelParticipantsSearch(''),
                            offset=offset,
                            limit=limit,
                            hash=0
                        ))

                        if not chunk.users:
                            break

                        participants.extend(chunk.users)

                        if len(chunk.users) < limit:
                            break

                        offset += len(chunk.users)
                        await asyncio.sleep(0.1)  # Rate limit

                    except FloodWaitError as e:
                        log.warning(f"Flood wait for {e.seconds} seconds")
                        await asyncio.sleep(e.seconds)
                        continue
                    except Exception as e:
                        log.warning(f"Error fetching participants batch: {e}")
                        break

                for user in participants:
                    if exclude_bots and getattr(user, 'bot', False):
                        continue
                    if exclude_admins and user.id in admin_ids:
                        continue

                    members.append({
                        'id': user.id,
                        'first_name': user.first_name or '',
                        'last_name': user.last_name or '',
                        'username': user.username or '',
                        'is_bot': bool(getattr(user, 'bot', False)),
                        'is_admin': user.id in admin_ids
                    })

                return members, (total_count or len(members))

            elif isinstance(entity, Chat):
                try:
                    full_chat = await self.client(GetFullChatRequest(chat_id=entity.id))
                    participants = full_chat.full_chat.participants.participants
                    total_count = len(participants)

                    for p in participants:
                        try:
                            user = await self.client.get_entity(p.user_id)
                            if exclude_bots and getattr(user, 'bot', False):
                                continue
                            if exclude_admins and (hasattr(user, 'id') and user.id in admin_ids):
                                continue

                            members.append({
                                'id': user.id,
                                'first_name': user.first_name or '',
                                'last_name': user.last_name or '',
                                'username': user.username or '',
                                'is_bot': bool(getattr(user, 'bot', False)),
                                'is_admin': user.id in admin_ids
                            })
                            await asyncio.sleep(0.05)
                        except Exception as e:
                            log.warning(f"Error processing user {getattr(p, 'user_id', '?')}: {e}")
                            continue

                    return members, total_count
                except Exception as e:
                    log.error(f"Error fetching regular group members: {e}")
                    return [], 0

            else:
                log.warning(f"Entity for group {group_id} is not a Channel or Chat")
                return [], 0

        except ChatAdminRequiredError:
            log.error(f"Bot is not admin in group {group_id}")
            return [], 0
        except Exception as e:
            log.error(f"Failed to fetch members for group {group_id}: {e}")
            return [], 0

    async def get_group_info(self, group_id: int) -> Optional[Dict]:
        """
        Guruh haqida qisqacha ma'lumot.
        """
        if not await self.is_connected():
            return None

        try:
            entity = await self.client.get_entity(group_id)
            info = {
                'id': getattr(entity, 'id', group_id),
                'title': getattr(entity, 'title', ''),
                'username': getattr(entity, 'username', ''),
                'type': 'channel' if isinstance(entity, Channel) else 'chat',
                'members_count': getattr(entity, 'participants_count', 0) or 0
            }
            return info
        except Exception as e:
            log.error(f"Failed to get group info for {group_id}: {e}")
            return None


class UserTelethonService:
    """User account Telethon service (owner session) — barcha a'zolarni ko‘ra oladi."""

    def __init__(self, api_id: int, api_hash: str, session_file: str = "data/owner_session"):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_file = session_file
        self.client: Optional[TelegramClient] = None
        self._is_connected = False

    async def start(self) -> bool:
        try:
            self.client = TelegramClient(
                self.session_file,
                self.api_id,
                self.api_hash,
                connection_retries=None,
                timeout=15
            )
            await self.client.connect()

            if not await self.client.is_user_authorized():
                log.error("User session not authorized. Run setup_owner_telethon.py first")
                self._is_connected = False
                return False

            self._is_connected = True
            me = await self.client.get_me()
            log.info(f"User Telethon client started as {me.first_name} (ID: {me.id})")
            return True

        except Exception as e:
            log.error(f"Failed to start user Telethon client: {e}")
            self._is_connected = False
            return False

    async def fetch_all_group_members(self, group_id: int) -> Tuple[List[Dict], int]:
        """User client orqali — botdan ko‘rinmaydigan a'zolarni ham ko‘ra oladi."""
        if not self._is_connected or not self.client:
            log.error("User client not connected")
            return [], 0

        try:
            entity = await self.client.get_entity(group_id)
            all_participants = []
            async for participant in self.client.iter_participants(entity):
                all_participants.append(participant)

            members: List[Dict] = []
            for user in all_participants:
                members.append({
                    'id': user.id,
                    'first_name': user.first_name or '',
                    'last_name': user.last_name or '',
                    'username': user.username or '',
                    'phone': getattr(user, 'phone', '') or '',
                    'is_bot': bool(getattr(user, 'bot', False)),
                    'is_premium': bool(getattr(user, 'premium', False)),
                    'is_verified': bool(getattr(user, 'verified', False)),
                })

            total = len(all_participants)
            log.info(f"User client fetched {total} members from group {group_id}")
            return members, total

        except Exception as e:
            log.error(f"User client failed to fetch members: {e}")
            return [], 0

    async def stop(self):
        if self.client and self._is_connected:
            await self.client.disconnect()
            self._is_connected = False
            log.info("User Telethon client stopped")


# Global singletonlar
_user_telethon_service: Optional[UserTelethonService] = None

async def get_user_telethon_service() -> Optional[UserTelethonService]:
    """User account Telethon service (owner sessiyasi)"""
    global _user_telethon_service
    if _user_telethon_service is None:
        try:
            from config import TELETHON_API_ID, TELETHON_API_HASH
            _user_telethon_service = UserTelethonService(
                TELETHON_API_ID,
                TELETHON_API_HASH
            )
            success = await _user_telethon_service.start()
            if not success:
                _user_telethon_service = None
                return None
        except Exception as e:
            log.error(f"Failed to initialize user Telethon service: {e}")
            _user_telethon_service = None
            return None
    return _user_telethon_service

async def stop_user_telethon_service():
    global _user_telethon_service
    if _user_telethon_service:
        await _user_telethon_service.stop()
        _user_telethon_service = None

# --- compatibility wrappers (bot.py backward-compat) ---
async def get_telethon_service(*args, **kwargs):
    return await get_user_telethon_service(*args, **kwargs)

async def stop_telethon_service(*args, **kwargs):
    return await stop_user_telethon_service(*args, **kwargs)
