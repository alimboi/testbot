import logging
import asyncio
from typing import List, Dict, Set, Tuple, Optional
from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import Channel, Chat, ChannelParticipantsSearch, User
from telethon.errors import FloodWaitError, ChatAdminRequiredError, UserPrivacyRestrictedError

log = logging.getLogger("telethon_service")

class TelethonService:
    """
    Complete Telethon service for group member management and messaging.
    """
    
    def __init__(self, api_id: int, api_hash: str, bot_token: str, session_file: str = "telethon_session"):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.session_file = session_file
        self.client: Optional[TelegramClient] = None
        self._is_connected = False
    
    async def start(self):
        """Initialize and start Telethon client"""
        try:
            self.client = TelegramClient(self.session_file, self.api_id, self.api_hash)
            await self.client.start(bot_token=self.bot_token)
            self._is_connected = True
            log.info("Telethon client started successfully")
            return True
        except Exception as e:
            log.error(f"Failed to start Telethon client: {e}")
            return False
    
    async def stop(self):
        """Stop Telethon client"""
        if self.client and self._is_connected:
            await self.client.disconnect()
            self._is_connected = False
            log.info("Telethon client stopped")
    
    async def is_connected(self) -> bool:
        """Check if client is connected"""
        return self._is_connected and self.client and self.client.is_connected()
    
    async def fetch_group_members(self, group_id: int, exclude_admins: bool = True, exclude_bots: bool = True) -> Tuple[List[Dict], int]:
        """
        Fetch all members from a group.
        
        Args:
            group_id: Telegram group ID
            exclude_admins: Whether to exclude administrators
            exclude_bots: Whether to exclude bots
            
        Returns:
            Tuple of (member_list, total_count)
            member_list: List of dicts with user info
            total_count: Total member count in group
        """
        if not await self.is_connected():
            log.error("Telethon client not connected")
            return [], 0
        
        try:
            entity = await self.client.get_entity(group_id)
            members = []
            admin_ids = set()
            
            # Get administrators if we need to exclude them
            if exclude_admins:
                try:
                    admins = await self.client.get_participants(entity, filter=lambda p: p.participant)
                    admin_ids = {admin.id for admin in admins if hasattr(admin, 'participant')}
                except Exception as e:
                    log.warning(f"Could not fetch admins for group {group_id}: {e}")
            
            if isinstance(entity, Channel):
                # For channels and supergroups
                total_count = entity.participants_count or 0
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
                        
                        # Rate limiting
                        await asyncio.sleep(0.1)
                        
                    except FloodWaitError as e:
                        log.warning(f"Flood wait for {e.seconds} seconds")
                        await asyncio.sleep(e.seconds)
                        continue
                    except Exception as e:
                        log.warning(f"Error fetching participants batch: {e}")
                        break
                
                # Process participants
                for user in participants:
                    if exclude_bots and user.bot:
                        continue
                    if exclude_admins and user.id in admin_ids:
                        continue
                    
                    members.append({
                        'id': user.id,
                        'first_name': user.first_name or '',
                        'last_name': user.last_name or '',
                        'username': user.username or '',
                        'is_bot': user.bot,
                        'is_admin': user.id in admin_ids
                    })
                
            elif isinstance(entity, Chat):
                # For regular groups
                try:
                    full_chat = await self.client(GetFullChatRequest(chat_id=entity.id))
                    participants = full_chat.full_chat.participants.participants
                    total_count = len(participants)
                    
                    for p in participants:
                        try:
                            user = await self.client.get_entity(p.user_id)
                            
                            if exclude_bots and user.bot:
                                continue
                            if exclude_admins and user.id in admin_ids:
                                continue
                            
                            members.append({
                                'id': user.id,
                                'first_name': user.first_name or '',
                                'last_name': user.last_name or '',
                                'username': user.username or '',
                                'is_bot': user.bot,
                                'is_admin': user.id in admin_ids
                            })
                            
                            # Rate limiting
                            await asyncio.sleep(0.05)
                            
                        except Exception as e:
                            log.warning(f"Error processing user {p.user_id}: {e}")
                            continue
                            
                except Exception as e:
                    log.error(f"Error fetching regular group members: {e}")
                    return [], 0
            else:
                log.warning(f"Entity for group {group_id} is not a Channel or Chat")
                return [], 0
            
            log.info(f"Fetched {len(members)} members from group {group_id} (total: {total_count})")
            return members, total_count
            
        except ChatAdminRequiredError:
            log.error(f"Bot is not admin in group {group_id}")
            return [], 0
        except Exception as e:
            log.error(f"Failed to fetch members for group {group_id}: {e}")
            return [], 0
    
    
    
    
    
    async def get_group_info(self, group_id: int) -> Optional[Dict]:
        """
        Get basic information about a group.
        
        Args:
            group_id: Telegram group ID
            
        Returns:
            Dict with group info or None if failed
        """
        if not await self.is_connected():
            return None
        
        try:
            entity = await self.client.get_entity(group_id)
            
            info = {
                'id': entity.id,
                'title': getattr(entity, 'title', ''),
                'username': getattr(entity, 'username', ''),
                'type': 'channel' if isinstance(entity, Channel) else 'chat',
                'members_count': getattr(entity, 'participants_count', 0)
            }
            
            return info
            
        except Exception as e:
            log.error(f"Failed to get group info for {group_id}: {e}")
            return None
    
    
            
        except Exception as e:
            log.error(f"Failed to check bot permissions for group {group_id}: {e}")
            return {}

# ADD THIS CLASS TO telethon_service.py AFTER TelethonService class:

class UserTelethonService:
    """User account Telethon service for fetching all group members"""
    
    def __init__(self, api_id: int, api_hash: str, session_file: str = "data/owner_session"):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_file = session_file
        self.client: Optional[TelegramClient] = None
        self._is_connected = False
    
    async def start(self):
        """Start user client (must have existing session from setup)"""
        try:
            self.client = TelegramClient(self.session_file, self.api_id, self.api_hash)
            await self.client.connect()
            
            if not await self.client.is_user_authorized():
                log.error("User session not authorized. Run setup_owner_telethon.py first")
                return False
            
            self._is_connected = True
            me = await self.client.get_me()
            log.info(f"User Telethon client started as {me.first_name} (ID: {me.id})")
            return True
            
        except Exception as e:
            log.error(f"Failed to start user Telethon client: {e}")
            return False
    
    async def fetch_all_group_members(self, group_id: int) -> Tuple[List[Dict], int]:
        """Fetch ALL members including those hidden from bots"""
        if not self._is_connected:
            log.error("User client not connected")
            return [], 0
        
        try:
            entity = await self.client.get_entity(group_id)
            
            # Get ALL participants as user
            all_participants = []
            async for participant in self.client.iter_participants(entity):
                all_participants.append(participant)
            
            members = []
            for user in all_participants:
                member_data = {
                    'id': user.id,
                    'first_name': user.first_name or '',
                    'last_name': user.last_name or '',
                    'username': user.username or '',
                    'phone': user.phone or '',  # Only available for user client
                    'is_bot': user.bot,
                    'is_premium': getattr(user, 'premium', False),
                    'is_verified': getattr(user, 'verified', False),
                }
                members.append(member_data)
            
            total = len(all_participants)
            log.info(f"User client fetched {total} members from group {group_id}")
            return members, total
            
        except Exception as e:
            log.error(f"User client failed to fetch members: {e}")
            return [], 0
    
    async def stop(self):
        """Stop user client"""
        if self.client and self._is_connected:
            await self.client.disconnect()
            self._is_connected = False
            log.info("User Telethon client stopped")

# ADD THESE GLOBALS AFTER _telethon_service:
_user_telethon_service: Optional[UserTelethonService] = None

async def get_user_telethon_service() -> Optional[UserTelethonService]:
    """Get user account Telethon service"""
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
            return None
    
    return _user_telethon_service

async def stop_user_telethon_service():
    """Stop user Telethon service"""
    global _user_telethon_service
    if _user_telethon_service:
        await _user_telethon_service.stop()
        _user_telethon_service = None# --- compatibility wrappers ---
# Provide older names expected by bot.py
async def get_telethon_service(*args, **kwargs):
    """Compatibility wrapper for get_user_telethon_service"""
    return await get_user_telethon_service(*args, **kwargs)

async def stop_telethon_service(*args, **kwargs):
    """Compatibility wrapper for stop_user_telethon_service"""
    return await stop_user_telethon_service(*args, **kwargs)
# --- end compatibility wrappers ---
