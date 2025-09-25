import os
import re
import json
import logging
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from docx import Document
from pathlib import Path
import json
from typing import Dict, List, Tuple, Optional, Any, Set
import asyncio
import time


try:
    from config import (
        OWNER_ID, ADMIN_USER_IDS, bot,
        DATA_DIR, TESTS_DIR, STUDENTS_DIR,
        ACTIVE_TEST_FILE, GROUPS_FILE, STUDENTS_FILE,
        USER_GROUPS_FILE, GROUP_MEMBERS_FILE,
    )
except Exception:
    OWNER_ID = int(os.environ.get("OWNER_ID", "0")) or None
    ADMIN_USER_IDS = [OWNER_ID] if OWNER_ID else []
    DATA_DIR = "data"
    TESTS_DIR = os.path.join(DATA_DIR, "tests")
    STUDENTS_DIR = os.path.join(DATA_DIR, "students")
    ACTIVE_TEST_FILE = os.path.join(TESTS_DIR, "active_tests.json")
    GROUPS_FILE = os.path.join(DATA_DIR, "groups.txt")
    STUDENTS_FILE = os.path.join(DATA_DIR, "students.json")
    USER_GROUPS_FILE = os.path.join(DATA_DIR, "user_groups.json")
    GROUP_MEMBERS_FILE = os.path.join(DATA_DIR, "group_members.json")

log = logging.getLogger("utils")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    log.addHandler(h)
log.setLevel(logging.INFO)

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error(f"read_json({path}): {e}")
    return default

def write_json(path: Path, obj):
    try:
        ensure_dir(path.parent)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        log.error(f"write_json({path}): {e}")
        return False

def get_file_path(base_dir: str, filename: str) -> str:
    p = Path(base_dir) / filename
    ensure_dir(p.parent)
    return str(p)

def ensure_data():
    ensure_dir(Path(DATA_DIR))
    ensure_dir(Path(TESTS_DIR))
    ensure_dir(Path(STUDENTS_DIR))
    if not Path(ACTIVE_TEST_FILE).exists():
        write_json(Path(ACTIVE_TEST_FILE), {"active_tests": []})
    for f, default in [
        (STUDENTS_FILE, {}),
        (USER_GROUPS_FILE, {}),
        (GROUP_MEMBERS_FILE, {}),
    ]:
        p = Path(f)
        if not p.exists():
            write_json(p, default)
    Path(GROUPS_FILE).parent.mkdir(parents=True, exist_ok=True)
    if not Path(GROUPS_FILE).exists():
        Path(GROUPS_FILE).write_text("", encoding="utf-8")

def is_owner(uid: int) -> bool:
    if OWNER_ID and uid == int(OWNER_ID):
        return True
    return int(uid) in set(int(x) for x in (ADMIN_USER_IDS or []))

def _parse_groups_file(text: str) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "," in line:
            id_str, title = line.split(",", 1)
        else:
            id_str, title = line, ""
        try:
            out[int(id_str.strip())] = title.strip()
        except Exception:
            continue
    return out

def load_group_ids() -> List[int]:
    if not Path(GROUPS_FILE).exists():
        return []
    try:
        data = Path(GROUPS_FILE).read_text(encoding="utf-8")
    except Exception:
        return []
    return list(_parse_groups_file(data).keys())

def load_group_titles() -> Dict[int, str]:
    if not Path(GROUPS_FILE).exists():
        return {}
    data = Path(GROUPS_FILE).read_text(encoding="utf-8")
    return _parse_groups_file(data)

def add_or_update_group(chat_id: int, title: str = ""):
    groups = load_group_titles()
    groups[int(chat_id)] = (title or groups.get(int(chat_id), "")).strip()
    lines = []
    for gid, t in sorted(groups.items()):
        lines.append(f"{gid},{t}" if t else f"{gid}")
    Path(GROUPS_FILE).write_text("\n".join(lines), encoding="utf-8")

def remove_group(chat_id: int):
    groups = load_group_titles()
    if int(chat_id) in groups:
        del groups[int(chat_id)]
        lines = []
        for gid, t in sorted(groups.items()):
            lines.append(f"{gid},{t}" if t else f"{gid}")
        Path(GROUPS_FILE).write_text("\n".join(lines), encoding="utf-8")

def load_group_members() -> Dict[str, Dict[str, List[int]]]:
    return read_json(Path(GROUP_MEMBERS_FILE), {})

def get_group_member_ids(group_id: int) -> List[int]:
    gm = load_group_members()
    rec = gm.get(str(group_id)) or {}
    return [int(x) for x in rec.get("members", [])]

def update_group_member(group_id: int, user_id: int, present: bool):
    gm = load_group_members()
    rec = gm.get(str(group_id)) or {"members": []}
    s = set(int(x) for x in rec.get("members", []))
    if present:
        s.add(int(user_id))
    else:
        s.discard(int(user_id))
    rec["members"] = sorted(s)
    gm[str(group_id)] = rec
    write_json(Path(GROUP_MEMBERS_FILE), gm)

async def sync_group_members(group_id: int) -> int:
    """Sync members using user account if available, else bot account"""
    try:
        from telethon_service import get_user_telethon_service, get_telethon_service

        # 1) Try user Telethon (can usually fetch all members)
        try:
            user_telethon = await get_user_telethon_service()
        except Exception:
            user_telethon = None

        if user_telethon:
            try:
                members, total_count = await user_telethon.fetch_all_group_members(group_id)
            except Exception as e:
                log.warning(f"User Telethon fetch_all_group_members failed for {group_id}: {e}")
                members = None
                total_count = 0

            if members:
                member_ids = []
                member_data: Dict[int, Dict] = {}
                for member in members:
                    # skip bots if reported
                    if member.get("is_bot"):
                        continue
                    uid = int(member["id"])
                    member_ids.append(uid)
                    member_data[uid] = {
                        "first_name": member.get("first_name", "") or "",
                        "last_name": member.get("last_name", "") or "",
                        "username": member.get("username", "") or "",
                        "phone": member.get("phone", "") or "",
                        "is_premium": member.get("is_premium", False),
                        "is_bot": member.get("is_bot", False),
                        "is_admin": member.get("is_admin", False),
                    }

                # Load existing data to preserve information
                gm = load_group_members()
                existing_data = gm.get(str(group_id), {}).get("member_data", {})
                
                # Merge data: preserve existing info for users who might have incomplete new data
                for uid_str, existing_info in existing_data.items():
                    uid = int(uid_str)
                    if uid in member_data:
                        # Preserve non-empty fields from existing data
                        for field in ["phone", "first_name", "last_name", "username"]:
                            if not member_data[uid].get(field) and existing_info.get(field):
                                member_data[uid][field] = existing_info[field]

                import time
                gm[str(group_id)] = {
                    "members": sorted(member_ids),
                    "member_data": {str(k): v for k, v in member_data.items()},
                    "last_sync": int(time.time()),
                    "sync_method": "user_telethon",
                    "total_count": total_count or len(member_ids),
                }
                write_json(Path(GROUP_MEMBERS_FILE), gm)

                # update user_groups.json
                user_groups_data = read_json(Path(USER_GROUPS_FILE), {})
                for user_id in member_ids:
                    uid_s = str(user_id)
                    if uid_s not in user_groups_data:
                        user_groups_data[uid_s] = []
                    if group_id not in user_groups_data[uid_s]:
                        user_groups_data[uid_s].append(group_id)
                write_json(Path(USER_GROUPS_FILE), user_groups_data)

                log.info(f"User Telethon synced {len(member_ids)} members for group {group_id}")
                return len(member_ids)

        # 2) Try bot Telethon client
        try:
            telethon = await get_telethon_service()
        except Exception:
            telethon = None

        if telethon:
            try:
                # Use fetch_group_members (may return subset depending on bot permissions)
                members, total_count = await telethon.fetch_group_members(
                    group_id, exclude_admins=False, exclude_bots=True
                )
            except Exception as e:
                log.warning(f"Bot Telethon fetch_group_members failed for {group_id}: {e}")
                members = None
                total_count = 0

            if members:
                member_ids = []
                member_data = {}
                for member in members:
                    # member dict shape may be different; use keys defensively
                    try:
                        uid = int(member.get("id") if isinstance(member.get("id"), (int, str)) else member["id"])
                    except Exception:
                        continue
                    # skip bots if flagged
                    if member.get("is_bot"):
                        continue
                    member_ids.append(uid)
                    member_data[uid] = {
                        "first_name": member.get("first_name", "") or "",
                        "last_name": member.get("last_name", "") or "",
                        "username": member.get("username", "") or "",
                        "is_bot": member.get("is_bot", False),
                        "is_admin": member.get("is_admin", False),
                    }

                gm = load_group_members()
                import time
                gm[str(group_id)] = {
                    "members": sorted(member_ids),
                    "member_data": {str(k): v for k, v in member_data.items()},
                    "last_sync": int(time.time()),
                    "sync_method": "bot_telethon",
                    "total_count": total_count or len(member_ids),
                }
                write_json(Path(GROUP_MEMBERS_FILE), gm)

                # update user_groups.json
                user_groups_data = read_json(Path(USER_GROUPS_FILE), {})
                for user_id in member_ids:
                    uid_s = str(user_id)
                    if uid_s not in user_groups_data:
                        user_groups_data[uid_s] = []
                    if group_id not in user_groups_data[uid_s]:
                        user_groups_data[uid_s].append(group_id)
                write_json(Path(USER_GROUPS_FILE), user_groups_data)

                log.info(f"Bot Telethon synced {len(member_ids)} members for group {group_id}")
                return len(member_ids)

        # 3) Fallback to aiogram (admins only)
        log.warning("Telethon clients not available or returned no members, falling back to aiogram fallback")
        return await _sync_group_members_fallback(group_id)

    except Exception as e:
        log.error(f"Failed to sync members for group {group_id}: {e}")
        return await _sync_group_members_fallback(group_id)

# ADD this new function to utils.py:
async def sync_all_groups_comprehensive() -> Dict[int, int]:
    """
    Comprehensive sync of all groups including members and admins.
    This is the main sync function that should be used for full synchronization.
    """
    results = {}
    admin_results = {}
    
    groups = load_group_ids()
    log.info(f"Starting comprehensive sync for {len(groups)} groups")
    
    for group_id in groups:
        try:
            # Sync members first
            member_count = await sync_group_members(group_id)
            results[group_id] = member_count
            
            # Small delay to avoid rate limits
            await asyncio.sleep(0.5)
            
            # Sync admins
            admin_dict = await sync_group_admins(group_id)
            admin_results[group_id] = len(admin_dict)
            
            # Another small delay
            await asyncio.sleep(0.5)
            
            log.info(f"Group {group_id}: {member_count} members, {len(admin_dict)} admins")
            
        except Exception as e:
            log.error(f"Failed to sync group {group_id}: {e}")
            results[group_id] = 0
            admin_results[group_id] = 0
    
    total_members = sum(results.values())
    total_admins = sum(admin_results.values())
    
    log.info(f"Comprehensive sync complete: {total_members} total members, {total_admins} total admins across {len(groups)} groups")
    return results


async def _sync_group_members_fallback(group_id: int) -> int:
    try:
        from config import bot
        
        admins = await bot.get_chat_administrators(group_id)
        member_ids = set()
        
        for admin in admins:
            if not admin.user.is_bot:
                member_ids.add(admin.user.id)
        
        gm = load_group_members()
        import time
        gm[str(group_id)] = {
            "members": sorted(member_ids),
            "last_sync": int(time.time()),
            "sync_method": "aiogram_fallback",
            "total_count": len(member_ids)
        }
        write_json(Path(GROUP_MEMBERS_FILE), gm)
        
        log.info(f"Fallback sync: {len(member_ids)} admin members for group {group_id}")
        return len(member_ids)
        
    except Exception as e:
        log.error(f"Fallback sync failed for group {group_id}: {e}")
        return 0

async def sync_all_groups() -> Dict[int, int]:
    """
    Sync both members and admins for all groups.
    This is a wrapper for sync_all_groups_comprehensive for backward compatibility.
    """
    return await sync_all_groups_comprehensive()

def add_user_to_group(user_id: int, group_id: int):
    update_group_member(group_id, user_id, True)
    user_groups = get_user_groups(user_id)
    if group_id not in user_groups:
        user_groups.append(group_id)
        set_user_groups(user_id, user_groups)

def get_group_member_data(group_id: int) -> Dict:
    gm = load_group_members()
    rec = gm.get(str(group_id)) or {}
    return rec.get("member_data", {})



async def notify_group_students(group_id: int, test_name: str, test_id: str) -> Tuple[List[int], List[int]]:
    """Enhanced notification with better error handling and reporting"""
    try:
        from config import bot
        from telethon_service import get_telethon_service
        
        member_ids = get_group_member_ids(group_id)
        if not member_ids:
            log.warning(f"No members found for group {group_id}")
            return [], []
        
        notified = []
        failed = []
        
        bot_username = (await bot.get_me()).username
        message = (
            f"🧪 <b>Yangi test!</b>\n\n"
            f"Test nomi: <b>{test_name}</b>\n"
            f"Test kodi: <code>{test_id}</code>\n\n"
            f"Testni boshlash uchun:\n"
            f"1. @{bot_username} botiga /start yuboring\n"
            f"2. Mavjud testlar ro'yxatidan tanlang\n\n"
            f"⏰ Test hozir faol!"
        )
        
        # Try to notify via bot first (faster)
        for user_id in member_ids:
            try:
                await bot.send_message(user_id, message)
                notified.append(user_id)
                log.debug(f"Notified user {user_id} about test {test_name}")
                
                # Small delay to avoid rate limits
                await asyncio.sleep(0.05)
                
            except Exception as e:
                failed.append(user_id)
                log.debug(f"Failed to notify user {user_id} via bot: {e}")
        
        # If many failed via bot, try Telethon as fallback
        if len(failed) > len(notified) * 0.3:  # If more than 30% failed
            log.info(f"Many bot notifications failed ({len(failed)}), trying Telethon fallback")
            
            telethon = await get_telethon_service()
            if telethon:
                telethon_message = (
                    f"🧪 Yangi test: {test_name}\n\n"
                    f"Testni boshlash uchun @{bot_username} botiga /start yuboring\n"
                    f"Test kodi: test_{test_id}"
                )
                
                telethon_notified, telethon_failed = await telethon.bulk_message_users(
                    failed, telethon_message, delay=0.5
                )
                
                notified.extend(telethon_notified)
                failed = telethon_failed
        
        success_rate = len(notified) / len(member_ids) * 100 if member_ids else 0
        log.info(f"Group {group_id} notification complete: {len(notified)}/{len(member_ids)} notified ({success_rate:.1f}% success rate)")
        
        return notified, failed
        
    except Exception as e:
        log.error(f"Failed to notify group {group_id}: {e}")
        return [], member_ids
async def _resolve_group_titles(ids):
    """Return list[(gid, title_or_id)] - resolves group IDs to titles"""
    out = []
    group_titles = load_group_titles()
    
    for gid in ids:
        try:
            gid_int = int(gid)
            title = group_titles.get(gid_int)
            
            if not title:
                # Try to get title from Telegram API
                try:
                    from config import bot
                    chat = await bot.get_chat(gid_int)
                    title = chat.title or str(gid_int)
                    
                    # Update our records
                    add_or_update_group(gid_int, title)
                    
                except Exception as e:
                    log.warning(f"Could not get title for group {gid_int}: {e}")
                    title = str(gid_int)
            
            out.append((gid_int, title))
        except (ValueError, TypeError):
            continue
    
    return out

async def detect_and_remove_kicked_users(group_id: int) -> List[int]:
    """
    Detect users who were removed from a group and clean up their data.
    Uses owner's Telethon account to get accurate member list.
    Returns list of removed user IDs.
    """
    try:
        from telethon_service import get_user_telethon_service
        
        # Get current members using owner account
        user_telethon = await get_user_telethon_service()
        if not user_telethon:
            log.warning("User Telethon not available for kicked user detection")
            return []
        
        # Get ALL current members from Telegram
        current_members, _ = await user_telethon.fetch_all_group_members(group_id)
        current_member_ids = set(member['id'] for member in current_members)
        
        # Get our stored members
        gm = load_group_members()
        stored_data = gm.get(str(group_id), {})
        stored_member_ids = set(int(uid) for uid in stored_data.get("members", []))
        
        # Find removed users (were in our data but not in current members)
        removed_users = stored_member_ids - current_member_ids
        
        if removed_users:
            log.info(f"Detected {len(removed_users)} removed users from group {group_id}: {removed_users}")
            
            # Clean up each removed user
            for user_id in removed_users:
                await cleanup_removed_user(user_id, group_id)
        
        return list(removed_users)
        
    except Exception as e:
        log.error(f"Failed to detect removed users for group {group_id}: {e}")
        return []

async def cleanup_removed_user(user_id: int, group_id: int):
    """
    Completely remove a user from all group-related data when they're kicked/removed.
    This ensures they can't access tests anymore.
    """
    try:
        log.info(f"Cleaning up removed user {user_id} from group {group_id}")
        
        # 1. Remove from group_members.json
        gm = load_group_members()
        if str(group_id) in gm:
            members = gm[str(group_id)].get("members", [])
            if user_id in members:
                members.remove(user_id)
                gm[str(group_id)]["members"] = members
            
            # Remove from member_data
            member_data = gm[str(group_id)].get("member_data", {})
            if str(user_id) in member_data:
                del member_data[str(user_id)]
                gm[str(group_id)]["member_data"] = member_data
            
            write_json(Path(GROUP_MEMBERS_FILE), gm)
            log.info(f"Removed user {user_id} from group_members.json for group {group_id}")
        
        # 2. Remove from user_groups.json
        user_groups_data = read_json(Path(USER_GROUPS_FILE), {})
        user_id_str = str(user_id)
        
        if user_id_str in user_groups_data:
            groups = user_groups_data[user_id_str]
            if group_id in groups:
                groups.remove(group_id)
                
                if groups:
                    user_groups_data[user_id_str] = groups
                else:
                    # User has no groups left, remove completely
                    del user_groups_data[user_id_str]
                
                write_json(Path(USER_GROUPS_FILE), user_groups_data)
                log.info(f"Removed group {group_id} from user {user_id}'s groups")
        
        # 3. Remove admin privileges if they had any
        admins_data = load_admins()
        group_admins = admins_data.get('group_admins', {})
        
        if user_id_str in group_admins:
            admin_groups = group_admins[user_id_str].get('groups', [])
            if group_id in admin_groups:
                admin_groups.remove(group_id)
                
                if admin_groups:
                    group_admins[user_id_str]['groups'] = admin_groups
                else:
                    # No admin groups left, remove from admins
                    del group_admins[user_id_str]
                
                admins_data['group_admins'] = group_admins
                save_admins(admins_data)
                log.info(f"Removed admin privileges for user {user_id} in group {group_id}")
        
        # 4. Log the removal for audit
        from audit import log_action
        log_action(0, "user_removed_from_group", ok=True, 
                  extra={"user_id": user_id, "group_id": group_id})
        
    except Exception as e:
        log.error(f"Failed to cleanup removed user {user_id} from group {group_id}: {e}")

async def validate_user_still_in_groups(user_id: int) -> Tuple[bool, List[int]]:
    """
    Validate if a user is still in their registered groups.
    Returns (has_valid_groups, valid_group_ids)
    """
    try:
        from config import bot
        
        # Get user's supposed groups
        user_groups = get_user_groups(user_id)
        gm = load_group_members()
        
        # Collect all groups user is supposedly in
        all_user_groups = set(user_groups)
        for gid_str, rec in gm.items():
            if user_id in rec.get("members", []):
                all_user_groups.add(int(gid_str))
        
        if not all_user_groups:
            return False, []
        
        valid_groups = []
        
        # Check each group with Telegram API
        for group_id in all_user_groups:
            try:
                member = await bot.get_chat_member(group_id, user_id)
                if member.status not in ["left", "kicked", "restricted"]:
                    valid_groups.append(group_id)
                else:
                    log.info(f"User {user_id} is no longer in group {group_id} (status: {member.status})")
                    # Clean up this invalid membership
                    await cleanup_removed_user(user_id, group_id)
            except Exception as e:
                # If we get an error (like user not found), they're not in the group
                log.info(f"User {user_id} not found in group {group_id}: {e}")
                await cleanup_removed_user(user_id, group_id)
        
        return len(valid_groups) > 0, valid_groups
        
    except Exception as e:
        log.error(f"Failed to validate user {user_id} groups: {e}")
        return False, []

async def enhanced_sync_group_members(group_id: int) -> int:
    """
    Enhanced sync that also detects and removes kicked users.
    This should replace the regular sync_group_members function when needed.
    """
    try:
        # First detect and remove kicked users
        removed_users = await detect_and_remove_kicked_users(group_id)
        if removed_users:
            log.info(f"Cleaned up {len(removed_users)} removed users from group {group_id}")
        
        # Then do normal sync
        count = await sync_group_members(group_id)
        
        return count
        
    except Exception as e:
        log.error(f"Enhanced sync failed for group {group_id}: {e}")
        return 0

async def smart_user_lookup_with_validation(user_id: int) -> bool:
    """
    Enhanced user lookup that validates membership before granting access.
    """
    try:
        # First validate if user is still in their groups
        has_valid_groups, valid_groups = await validate_user_still_in_groups(user_id)
        
        if not has_valid_groups:
            log.info(f"User {user_id} has no valid group memberships")
            return False
        
        # If user has valid groups, return True
        if valid_groups:
            log.info(f"User {user_id} validated in groups: {valid_groups}")
            return True
        
        # If no valid groups found, trigger full sync
        log.info(f"No valid groups for user {user_id}, triggering comprehensive sync")
        
        # Sync all groups with removal detection
        for group_id in load_group_ids():
            await enhanced_sync_group_members(group_id)
        
        # Check again after sync
        has_valid_groups, valid_groups = await validate_user_still_in_groups(user_id)
        
        return has_valid_groups
        
    except Exception as e:
        log.error(f"Smart user lookup with validation failed for {user_id}: {e}")
        return False

# Update the smart_user_lookup function in utils.py
async def smart_user_lookup_with_validation(user_id: int) -> bool:
    """
    Enhanced user lookup that validates membership before granting access.
    """
    try:
        # First validate if user is still in their groups
        has_valid_groups, valid_groups = await validate_user_still_in_groups(user_id)
        
        if not has_valid_groups:
            log.info(f"User {user_id} has no valid group memberships")
            return False
        
        # If user has valid groups, return True
        if valid_groups:
            log.info(f"User {user_id} validated in groups: {valid_groups}")
            return True
        
        # If no valid groups found, trigger full sync
        log.info(f"No valid groups for user {user_id}, triggering comprehensive sync")
        
        # Sync all groups with removal detection
        for group_id in load_group_ids():
            await enhanced_sync_group_members(group_id)
        
        # Check again after sync
        has_valid_groups, valid_groups = await validate_user_still_in_groups(user_id)
        
        return has_valid_groups
        
    except Exception as e:
        log.error(f"Smart user lookup with validation failed for {user_id}: {e}")
        return False

def remove_user_from_group_completely(user_id: int, group_id: int):
    """
    Completely remove user from all group-related data structures.
    This should be called when a user leaves or is kicked from a group.
    """
    try:
        # 1. Remove from group_members.json
        update_group_member(group_id, user_id, False)
        
        # 2. Remove from user_groups.json
        user_groups_data = read_json(Path(USER_GROUPS_FILE), {})
        user_id_str = str(user_id)
        
        if user_id_str in user_groups_data:
            if group_id in user_groups_data[user_id_str]:
                user_groups_data[user_id_str].remove(group_id)
                
            # If user has no groups left, remove them entirely
            if not user_groups_data[user_id_str]:
                del user_groups_data[user_id_str]
                
            write_json(Path(USER_GROUPS_FILE), user_groups_data)
        
        # 3. Remove admin privileges for this group if they had any
        remove_user_admin_privileges(user_id, group_id)
        
        log.info(f"Completely removed user {user_id} from group {group_id}")
        
    except Exception as e:
        log.error(f"Error removing user {user_id} from group {group_id}: {e}")

def remove_user_admin_privileges(user_id: int, group_id: int):
    """
    Remove admin privileges for a specific group.
    If user has no groups left, remove them from admins entirely.
    """
    try:
        admins_data = load_admins()
        group_admins = admins_data.get('group_admins', {})
        user_id_str = str(user_id)
        
        if user_id_str in group_admins:
            admin_groups = group_admins[user_id_str].get('groups', [])
            
            if group_id in admin_groups:
                admin_groups.remove(group_id)
                log.info(f"Removed admin privileges for user {user_id} in group {group_id}")
                
                # If user has no admin groups left, remove them completely
                if not admin_groups:
                    del group_admins[user_id_str]
                    log.info(f"User {user_id} has no admin groups left, removed from admins")
                else:
                    group_admins[user_id_str]['groups'] = admin_groups
                
                admins_data['group_admins'] = group_admins
                save_admins(admins_data)
                
    except Exception as e:
        log.error(f"Error removing admin privileges for user {user_id}: {e}")

async def validate_user_group_membership(user_id: int) -> List[int]:
    """
    Validate user's group membership by checking with Telegram API.
    Returns list of groups where user is actually still a member.
    """
    try:
        from config import bot
        user_groups = get_user_groups(user_id)
        valid_groups = []
        
        for group_id in user_groups:
            try:
                # Check if user is still in the group
                member = await bot.get_chat_member(group_id, user_id)
                if member.status not in ["left", "kicked"]:
                    valid_groups.append(group_id)
                else:
                    log.info(f"User {user_id} no longer in group {group_id}, status: {member.status}")
                    # Remove from all data
                    remove_user_from_group_completely(user_id, group_id)
                    
            except Exception as e:
                log.warning(f"Could not check membership for user {user_id} in group {group_id}: {e}")
                # If we can't check, assume they're still there to avoid false removals
                valid_groups.append(group_id)
        
        return valid_groups
        
    except Exception as e:
        log.error(f"Error validating group membership for user {user_id}: {e}")
        return get_user_groups(user_id)  # Return original list if validation fails

async def cleanup_invalid_memberships():
    """
    Periodic cleanup to remove users who are no longer in groups.
    This should be run periodically to catch any missed removals.
    """
    try:
        log.info("Starting cleanup of invalid memberships...")
        
        # Get all users from user_groups.json
        user_groups_data = read_json(Path(USER_GROUPS_FILE), {})
        cleanup_count = 0
        
        for user_id_str, groups in list(user_groups_data.items()):
            try:
                user_id = int(user_id_str)
                valid_groups = await validate_user_group_membership(user_id)
                
                # If valid groups differ from stored groups, update
                if set(valid_groups) != set(groups):
                    log.info(f"Updating groups for user {user_id}: {groups} -> {valid_groups}")
                    
                    if valid_groups:
                        user_groups_data[user_id_str] = valid_groups
                    else:
                        del user_groups_data[user_id_str]
                    
                    cleanup_count += 1
                    
            except Exception as e:
                log.error(f"Error cleaning up user {user_id_str}: {e}")
        
        # Save updated data
        if cleanup_count > 0:
            write_json(Path(USER_GROUPS_FILE), user_groups_data)
            log.info(f"Cleanup complete: updated {cleanup_count} users")
        else:
            log.info("Cleanup complete: no changes needed")
            
    except Exception as e:
        log.error(f"Error during membership cleanup: {e}")


async def check_user_current_admin_status(user_id: int) -> List[int]:
    """
    Check user's CURRENT admin status by validating with Telegram API.
    Returns list of groups where user is currently an admin.
    """
    try:
        from config import bot
        
        # Get stored admin groups
        stored_admin_groups = get_user_admin_groups(user_id)
        current_admin_groups = []
        
        for group_id in stored_admin_groups:
            try:
                # Check current status in Telegram
                member = await bot.get_chat_member(group_id, user_id)
                if member.status in ["administrator", "creator"]:
                    current_admin_groups.append(group_id)
                else:
                    log.info(f"User {user_id} no longer admin in group {group_id}, current status: {member.status}")
                    # Remove admin privileges
                    remove_user_admin_privileges(user_id, group_id)
                    
            except Exception as e:
                log.warning(f"Could not check admin status for user {user_id} in group {group_id}: {e}")
                # If we can't check, don't assume they're still admin
        
        return current_admin_groups
        
    except Exception as e:
        log.error(f"Error checking admin status for user {user_id}: {e}")
        return []

async def get_unreachable_users_info(group_id: int, failed_user_ids: List[int]) -> List[Dict]:
    try:
        member_data = get_group_member_data(group_id)
        unreachable = []
        
        for user_id in failed_user_ids:
            user_info = member_data.get(str(user_id), {})
            unreachable.append({
                'id': user_id,
                'first_name': user_info.get('first_name', 'Unknown'),
                'last_name': user_info.get('last_name', ''),
                'username': user_info.get('username', ''),
                'full_name': f"{user_info.get('first_name', 'Unknown')} {user_info.get('last_name', '')}".strip()
            })
        
        return unreachable
        
    except Exception as e:
        log.error(f"Failed to get unreachable user info: {e}")
        return []

def load_students() -> Dict[str, dict]:
    return read_json(Path(STUDENTS_FILE), {})

def save_students(data: Dict[str, dict]):
    write_json(Path(STUDENTS_FILE), data)

def save_student_data(user_id: int, payload: dict):
    students = load_students()
    base = students.get(str(user_id), {})
    base.update(payload or {})
    students[str(user_id)] = base
    save_students(students)

def get_user_groups(user_id: int) -> List[int]:
    m = read_json(Path(USER_GROUPS_FILE), {})
    ids = m.get(str(user_id), [])
    try:
        return [int(x) for x in ids]
    except Exception:
        return []

def set_user_groups(user_id: int, groups: List[int]):
    m = read_json(Path(USER_GROUPS_FILE), {})
    m[str(user_id)] = sorted(set(int(x) for x in groups))
    write_json(Path(USER_GROUPS_FILE), m)

# Add this fix to your utils.py file in the get_all_students_with_groups function

def get_all_students_with_groups() -> List[Dict]:
    students = []
    gm = load_group_members()
    group_titles = load_group_titles()
    
    all_users = {}
    
    for group_id_str, group_data in gm.items():
        group_id = int(group_id_str)
        member_data = group_data.get("member_data", {})
        
        for user_id_str, user_info in member_data.items():
            user_id = int(user_id_str)
            if user_id not in all_users:
                all_users[user_id] = {
                    'groups': [],
                    'info': user_info
                }
            all_users[user_id]['groups'].append(group_id)
    
    user_groups_data = read_json(Path(USER_GROUPS_FILE), {})
    for user_id_str, group_ids in user_groups_data.items():
        user_id = int(user_id_str)
        if user_id not in all_users:
            all_users[user_id] = {
                'groups': [int(gid) for gid in group_ids],
                'info': {}
            }
    
    student_data = load_students()
    
    for user_id, data in all_users.items():
        user_info = data['info']
        user_groups = data['groups']
        
        group_names = []
        for gid in user_groups:
            title = group_titles.get(gid, f"Group {gid}")
            group_names.append(title)
        
        test_info = student_data.get(str(user_id), {})
        
        name_parts = []
        if user_info.get('first_name'):
            name_parts.append(user_info['first_name'])
        if user_info.get('last_name'):
            name_parts.append(user_info['last_name'])
        
        display_name = " ".join(name_parts) if name_parts else test_info.get("full_name", "Unknown")
        
        students.append({
            "user_id": user_id,
            "name": display_name,
            "username": user_info.get('username', ''),
            "groups": group_names,
            "last_test": test_info.get("last_test_id"),
            "last_score": test_info.get("last_score"),
            "last_activity": test_info.get("finished_at"),
        })
    
    # FIX: Handle None values in sorting by using 'or 0' to provide default
    return sorted(students, key=lambda x: x.get("last_activity") or 0, reverse=True)

def load_admins() -> Dict[str, dict]:
    p = Path(DATA_DIR) / "admins.json"
    d = read_json(p, {"owner_id": OWNER_ID, "admins": {}})
    return d

def save_admins(d: Dict[str, dict]):
    p = Path(DATA_DIR) / "admins.json"
    write_json(p, d)

# Add to utils.py
def get_student_admins(user_id: int) -> List[int]:
    """Get admin IDs who manage groups where this student is a member"""
    try:
        # Get student's groups
        user_groups = get_user_groups(user_id)
        gm = load_group_members()
        
        # Also check group_members.json for groups
        for gid_str, rec in gm.items():
            try:
                gid = int(gid_str)
                if user_id in rec.get("members", []):
                    if gid not in user_groups:
                        user_groups.append(gid)
            except (ValueError, TypeError):
                continue
        
        if not user_groups:
            return []
        
        # Get all admins for these groups
        admins_data = load_admins()
        group_admins = admins_data.get('group_admins', {})
        
        relevant_admins = []
        for admin_id_str, admin_data in group_admins.items():
            admin_groups = admin_data.get('groups', [])
            # Check if this admin manages any of the student's groups
            if any(g in user_groups for g in admin_groups):
                relevant_admins.append(int(admin_id_str))
        
        return relevant_admins
        
    except Exception as e:
        log.error(f"Error getting student admins: {e}")
        return []

def test_path(test_id: str) -> Path:
    p = Path(TESTS_DIR) / f"test_{test_id}.json"
    ensure_dir(p.parent)
    return p

def get_all_tests() -> List[Path]:
    return list(Path(TESTS_DIR).glob("test_*.json"))

def read_test(test_id: str) -> dict:
    p = test_path(test_id)
    return read_json(p, {})

def write_test(test_id: str, obj: dict):
    p = test_path(test_id)
    write_json(p, obj)

def add_test_index(test_id: str, name: str):
    obj = read_test(test_id) or {}
    obj.setdefault("test_id", test_id)
    if name:
        obj["test_name"] = name
    obj.setdefault("questions", [])
    obj.setdefault("answers", {})
    obj.setdefault("references", {})
    obj.setdefault("groups", [])
    if "group_id" not in obj:
        obj["group_id"] = None
    write_test(test_id, obj)

def save_test_content(test_id: str, content: dict):
    obj = read_test(test_id) or {"test_id": test_id}
    for k in ("test_name", "questions", "answers", "references"):
        if k in content:
            obj[k] = content[k]
    obj.setdefault("groups", [])
    obj.setdefault("group_id", None)
    write_test(test_id, obj)

def load_tests_index() -> dict:
    active = set(get_active_tests())
    out = {"tests": {}}
    for p in get_all_tests():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        tid = data.get("test_id") or p.stem.replace("test_", "")
        name = data.get("test_name") or "Test"
        groups = data.get("groups") or []
        gid = data.get("group_id")
        if gid and not groups:
            groups = [str(gid)]
        out["tests"][tid] = {
            "name": name,
            "active": tid in active,
            "groups": [str(g) for g in groups],
        }
    return out

def save_tests_index(idx: dict):
    return

def get_active_tests() -> List[str]:
    data = read_json(Path(ACTIVE_TEST_FILE), {"active_tests": []})
    return list(dict.fromkeys(data.get("active_tests", [])))

def set_active_test(test_id: str):
    data = read_json(Path(ACTIVE_TEST_FILE), {"active_tests": []})
    arr = list(data.get("active_tests", []))
    if test_id not in arr:
        arr.append(test_id)
    data["active_tests"] = arr
    write_json(Path(ACTIVE_TEST_FILE), data)

def remove_active_test(test_id: str):
    data = read_json(Path(ACTIVE_TEST_FILE), {"active_tests": []})
    arr = [x for x in data.get("active_tests", []) if x != test_id]
    data["active_tests"] = arr
    write_json(Path(ACTIVE_TEST_FILE), data)

def set_test_active(test_id: str, active: bool):
    if active:
        set_active_test(test_id)
    else:
        remove_active_test(test_id)

def assign_test_groups(test_id: str, groups: List[int]):
    obj = read_test(test_id) or {"test_id": test_id}
    norm = [int(x) for x in groups if str(x).strip()]
    obj["groups"] = sorted(set(norm))
    obj["group_id"] = (norm[0] if norm else None)
    write_test(test_id, obj)

def tests_for_group(group_id: int, only_active=True) -> List[dict]:
    act = set(get_active_tests()) if only_active else None
    out = []
    for p in get_all_tests():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        tid = data.get("test_id") or p.stem.replace("test_", "")
        grps = data.get("groups") or []
        gid = data.get("group_id")
        if gid and not grps:
            grps = [gid]
        if int(group_id) in [int(x) for x in grps]:
            if only_active and act is not None and tid not in act:
                continue
            data["test_id"] = tid
            out.append(data)
    return out

def available_tests_for_user(user_id: int) -> List[dict]:
    user_groups = set(get_user_groups(user_id))
    
    gm = load_group_members()
    for gid_str, rec in gm.items():
        try:
            gid = int(gid_str)
            members = set(int(x) for x in rec.get("members", []))
            if user_id in members:
                user_groups.add(gid)
        except (ValueError, TypeError):
            continue
    
    if not user_groups:
        log.warning(f"User {user_id} has no group memberships")
        return []
    
    log.info(f"User {user_id} is member of groups: {user_groups}")
    
    out = []
    active_tests = set(get_active_tests())
    
    for p in get_all_tests():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
            
        tid = data.get("test_id") or p.stem.replace("test_", "")
        
        if tid not in active_tests:
            continue
        
        test_groups = set()
        for g in (data.get("groups") or []):
            try:
                test_groups.add(int(g))
            except (ValueError, TypeError):
                pass
        
        if data.get("group_id"):
            try:
                test_groups.add(int(data["group_id"]))
            except (ValueError, TypeError):
                pass
        
        if not test_groups:
            continue
        
        if user_groups.intersection(test_groups):
            data["test_id"] = tid
            out.append(data)
            log.info(f"Test {tid} available for user {user_id} (groups: {test_groups})")
        else:
            log.info(f"Test {tid} NOT available for user {user_id} (test groups: {test_groups}, user groups: {user_groups})")
    
    return out

_Q_HEADER = re.compile(r"^\s*(\d+)[\.\)]\s*(.+)$")
_OPT_LINE = re.compile(r"^\s*([A-Da-d])[\.\)]\s*(.+)$")
_ANS_PAIR = re.compile(r"^\s*(\d+)\s*[\.\)\-]?\s*([A-Da-d])\s*$")
_ANS_TOK = re.compile(r"^\s*(\d+)([A-Da-d])\s*$")
_REF_LINE = re.compile(r"^\s*(\d+)[\.\)]\s*(.+)$")

def parse_questions_from_text(block: str) -> List[dict]:
    """Enhanced parser that handles code blocks and multi-line questions"""
    lines = [ln.rstrip() for ln in block.splitlines()]
    items: List[dict] = []
    cur = None
    in_code_block = False
    code_lines = []

    def push():
        if not cur:
            return
        # Join any accumulated code lines to the question text
        if code_lines:
            cur["text"] = cur["text"] + "\n" + "\n".join(code_lines)
            code_lines.clear()
        opts = cur.get("options", {})
        if len(opts) >= 2:
            items.append(cur)

    for i, ln in enumerate(lines):
        # Skip empty lines but preserve them in code blocks
        if not ln.strip():
            if in_code_block and cur:
                code_lines.append(ln)
            continue
        
        # Check for question header
        q_match = re.match(r'^\s*(\d+)\s*[\.\\)]\s*(.+)$', ln)
        
        # Check for option line
        opt_match = re.match(r'^\s*([A-Da-d])\s*[\.\\)]\s*(.+)$', ln)
        
        # Determine if this is a new question
        if q_match:
            # Check if this might be code that looks like a question number
            # by looking at the next line
            next_line = lines[i+1] if i+1 < len(lines) else ""
            next_is_option = bool(re.match(r'^\s*([A-Da-d])\s*[\.\\)]\s*', next_line))
            
            # It's a real question if:
            # 1. We have no current question, OR
            # 2. The next line is an option, OR
            # 3. The number is sequential
            expected_num = len(items) + 1 if not cur else cur["index"] + 1
            actual_num = int(q_match.group(1))
            
            is_new_question = (
                not cur or 
                next_is_option or 
                (actual_num == expected_num)
            )
            
            if is_new_question:
                # Save previous question if exists
                if cur:
                    push()
                
                # Start new question
                idx = int(q_match.group(1))
                text = q_match.group(2).strip()
                cur = {"index": idx, "text": text, "options": {}}
                in_code_block = False
                code_lines = []
                continue
        
        # Check for option line
        if opt_match and cur:
            # Save any accumulated code lines before starting options
            if code_lines:
                cur["text"] = cur["text"] + "\n" + "\n".join(code_lines)
                code_lines = []
                in_code_block = False
            
            key = opt_match.group(1).upper()
            val = opt_match.group(2).strip()
            cur["options"][key] = val
            continue
        
        # If we're here, this is a continuation line
        if cur:
            # Detect code patterns
            is_code = any([
                ln.strip().startswith('const '),
                ln.strip().startswith('let '),
                ln.strip().startswith('var '),
                ln.strip().startswith('function '),
                'console.log' in ln,
                '.push(' in ln,
                '.pop(' in ln,
                '.shift(' in ln,
                '.unshift(' in ln,
                '.splice(' in ln,
                '.slice(' in ln,
                '.split(' in ln,
                '.join(' in ln,
                '=>' in ln,
                '= [' in ln,
                '= {' in ln,
                ln.strip().endswith(';'),
                ln.strip().endswith('{') or ln.strip().endswith('}'),
                ln.strip().startswith('//') or ln.strip().startswith('/*'),
            ])
            
            if is_code or in_code_block:
                in_code_block = True
                code_lines.append(ln)
            elif cur["options"]:
                # We're in options section, continue last option
                last_key = sorted(cur["options"].keys())[-1]
                cur["options"][last_key] = (cur["options"][last_key] + " " + ln.strip()).strip()
            else:
                # Continue question text
                if code_lines:
                    # Flush code lines first
                    cur["text"] = cur["text"] + "\n" + "\n".join(code_lines)
                    code_lines = []
                    in_code_block = False
                # Add as regular text
                cur["text"] = (cur["text"] + " " + ln.strip()).strip()

    # Don't forget the last question
    if cur:
        push()

    # Renumber if needed
    if items:
        for i, it in enumerate(items, 1):
            it["index"] = i
    
    return items

def parse_questions_from_text_v2(block: str) -> List[dict]:
    """Alternative approach: preserve exact formatting between question and options"""
    lines = block.splitlines()
    items = []
    current_q = None
    buffer = []
    
    for i, line in enumerate(lines):
        # Check if this is a question header
        q_match = re.match(r'^\s*(\d+)\s*[\.\\)]\s*(.*)$', line)
        
        if q_match:
            # Look ahead to see if options follow soon
            has_options_ahead = False
            for j in range(i+1, min(i+15, len(lines))):  # Look up to 15 lines ahead
                if re.match(r'^\s*[A-Da-d]\s*[\.\\)]\s*', lines[j]):
                    has_options_ahead = True
                    break
            
            if has_options_ahead:
                # Save previous question if exists
                if current_q and buffer:
                    current_q["text"] = current_q["text"] + "\n" + "\n".join(buffer)
                    buffer = []
                if current_q and len(current_q.get("options", {})) >= 2:
                    items.append(current_q)
                
                # Start new question
                current_q = {
                    "index": int(q_match.group(1)),
                    "text": q_match.group(2).strip() if q_match.group(2) else "",
                    "options": {}
                }
                buffer = []
                continue
        
        # Check if this is an option
        opt_match = re.match(r'^\s*([A-Da-d])\s*[\.\\)]\s*(.*)$', line)
        if opt_match and current_q is not None:
            # Save any buffer to question text
            if buffer and not current_q["options"]:
                if current_q["text"]:
                    current_q["text"] = current_q["text"] + "\n" + "\n".join(buffer)
                else:
                    current_q["text"] = "\n".join(buffer)
                buffer = []
            
            key = opt_match.group(1).upper()
            val = opt_match.group(2).strip() if opt_match.group(2) else ""
            
            # Check if we're continuing a previous option or starting new
            if key in current_q["options"]:
                # Continuing previous option (shouldn't happen usually)
                current_q["options"][key] = current_q["options"][key] + " " + val
            else:
                # New option
                current_q["options"][key] = val
            continue
        
        # Continuation line
        if current_q:
            if current_q["options"]:
                # We're in options, append to last option
                last_key = max(current_q["options"].keys())
                if line.strip():
                    current_q["options"][last_key] = current_q["options"][last_key] + " " + line.strip()
            else:
                # We're still in question text, buffer it
                buffer.append(line.rstrip())
    
    # Don't forget the last question
    if current_q:
        if buffer and not current_q["options"]:
            if current_q["text"]:
                current_q["text"] = current_q["text"] + "\n" + "\n".join(buffer)
            else:
                current_q["text"] = "\n".join(buffer)
        if len(current_q.get("options", {})) >= 2:
            items.append(current_q)
    
    # Renumber questions
    for i, item in enumerate(items, 1):
        item["index"] = i
    
    return items

def parse_answers_from_text(block: str) -> Dict[str, str]:
    """Enhanced answer parser that handles various formats"""
    ans: Dict[str, str] = {}
    
    # Handle different answer formats
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
            
        # Try different patterns
        # Pattern 1: "1.a" or "1)a" 
        m = re.match(r'^\s*(\d+)\s*[\.\\)]\s*([A-Da-d])\s*$', line)
        if m:
            ans[str(int(m.group(1)))] = m.group(2).upper()
            continue
            
        # Pattern 2: "1-a" or "1:a"
        m = re.match(r'^\s*(\d+)\s*[-:]\s*([A-Da-d])\s*$', line)
        if m:
            ans[str(int(m.group(1)))] = m.group(2).upper()
            continue
            
        # Pattern 3: "1a" (no separator)
        m = re.match(r'^\s*(\d+)([A-Da-d])\s*$', line)
        if m:
            ans[str(int(m.group(1)))] = m.group(2).upper()
            continue
            
        # Pattern 4: Split by commas or spaces for multiple answers
        tokens = re.split(r'[,\s]+', line)
        for token in tokens:
            token = token.strip()
            if not token:
                continue
                
            # Try each token with the patterns above
            for pattern in [
                r'^(\d+)[\.\\)]?([A-Da-d])$',
                r'^(\d+)[-:]([A-Da-d])$'
            ]:
                m = re.match(pattern, token)
                if m:
                    ans[str(int(m.group(1)))] = m.group(2).upper()
                    break
    
    return ans


def parse_references_from_text(block: str) -> Dict[str, str]:
    """Enhanced reference parser that preserves code formatting"""
    refs: Dict[str, str] = {}
    current_ref = None
    current_text = []
    
    for line in block.splitlines():
        # Check if this is a new reference number
        m = re.match(r'^\s*(\d+)[\.\\)]\s*(.*)$', line)
        if m:
            # Save previous reference if exists
            if current_ref and current_text:
                refs[str(current_ref)] = ' '.join(current_text).strip()
            
            # Start new reference
            current_ref = int(m.group(1))
            remaining = m.group(2).strip()
            current_text = [remaining] if remaining else []
        elif current_ref and line.strip():
            # Continue current reference
            current_text.append(line.strip())
    
    # Don't forget the last reference
    if current_ref and current_text:
        refs[str(current_ref)] = ' '.join(current_text).strip()
    
    return refs

def validate_parsed_test(parsed_data: dict) -> Tuple[bool, str]:
    """Validate parsed test data"""
    questions = parsed_data.get("questions", [])
    answers = parsed_data.get("answers", {})
    
    if not questions:
        return False, "No questions found"
    
    # Check that all questions have at least 2 options
    for q in questions:
        opts = q.get("options", {})
        if len(opts) < 2:
            return False, f"Question {q.get('index')} has less than 2 options"
    
    # Check that answers exist for all questions
    for q in questions:
        idx = str(q.get("index"))
        if idx not in answers:
            return False, f"No answer found for question {idx}"
        if answers[idx] not in ["A", "B", "C", "D"]:
            return False, f"Invalid answer '{answers[idx]}' for question {idx}"
    
    return True, "Valid"

def _split_sections_from_doc(doc: Document) -> Tuple[str, str, str]:
    """Enhanced section splitter that preserves ALL content including code"""
    sections = {"questions": [], "answers": [], "refs": []}
    current_section = "questions"
    
    # More flexible header patterns
    headers = {
        "questions": re.compile(r'^\s*\**\s*Savollar\s*:?\s*\**\s*$', re.IGNORECASE),
        "answers": re.compile(r'^\s*\**\s*Javoblar\s*:?\s*\**\s*$', re.IGNORECASE),
        "refs": re.compile(r'^\s*\**\s*Izohlar\s*:?\s*\**\s*$', re.IGNORECASE)
    }
    
    for para in doc.paragraphs:
        text = para.text
        
        # Check if this is a section header
        header_found = False
        for section, pattern in headers.items():
            if pattern.match(text.strip()):
                current_section = section if section != "refs" else "refs"
                header_found = True
                break
        
        if header_found:
            continue
        
        # Add to current section, preserving ALL content
        if current_section == "questions":
            sections["questions"].append(text)
        elif current_section == "answers":
            sections["answers"].append(text)
        else:
            sections["refs"].append(text)
    
    # Join with newlines to preserve structure
    return (
        "\n".join(sections["questions"]),
        "\n".join(sections["answers"]),
        "\n".join(sections["refs"])
    )

def smart_parse_questions(text: str) -> List[dict]:
    """Smart parser that tries multiple strategies"""
    # Try the enhanced parser first
    result = parse_questions_from_text(text)
    
    # Validate the result
    if result and all(q.get("text") and len(q.get("options", {})) >= 2 for q in result):
        return result
    
    # If first parser failed, try alternative approach
    result_v2 = parse_questions_from_text_v2(text)
    if result_v2 and all(q.get("text") and len(q.get("options", {})) >= 2 for q in result_v2):
        return result_v2
    
    # Return best result
    return result if len(result) >= len(result_v2) else result_v2


# Additional helper to validate and fix incomplete questions
def validate_and_fix_questions(questions: List[dict], full_text: str) -> List[dict]:
    """Post-process questions to ensure completeness"""
    for q in questions:
        # Check if question seems incomplete (too short for a code question)
        if len(q["text"]) < 50 and "kod" in q["text"].lower():
            # Try to find more content in the original text
            q_num = q["index"]
            
            # Find question in original text
            pattern = rf'\b{q_num}\s*[\.\\)]\s*(.*?)(?=\n\s*[A-Da-d]\s*[\.\\)])'
            match = re.search(pattern, full_text, re.DOTALL)
            
            if match:
                full_question = match.group(1).strip()
                if len(full_question) > len(q["text"]):
                    q["text"] = full_question
    
    return questions

def parse_combined_file(file_path: str) -> Optional[dict]:
    try:
        doc = Document(file_path)
    except Exception as e:
        raise ValueError(f"Cannot open DOCX: {e}")

    qtxt, atxt, rtxt = _split_sections_from_doc(doc)
    questions = parse_questions_from_text(qtxt)
    answers = parse_answers_from_text(atxt)
    refs = parse_references_from_text(rtxt)

    if not questions:
        raise ValueError("No questions parsed. Ensure 'Savollar' section and numbering like '1) ...' with options A-D.")
    for k, v in answers.items():
        if v not in {"A", "B", "C", "D"}:
            raise ValueError(f"Answer {k} has invalid option '{v}'")

    test_name = Path(file_path).stem
    if questions:
        test_name = questions[0]["text"][:40] or test_name

    return {
        "test_name": test_name,
        "questions": questions,
        "answers": answers,
        "references": refs,
    }

def parse_docx_bytes(raw: bytes) -> Tuple[str, dict]:
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(raw)
        tmp.flush()
        tmp_path = tmp.name
    try:
        parsed = parse_combined_file(tmp_path)
        name = parsed.get("test_name") or "Test"
        return name, parsed
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

def score_user_answers(user_answers: Dict[str, str], correct: Dict[str, str]) -> Tuple[int, int]:
    total = len(correct or {})
    if total == 0:
        return 0, 0
    ok = 0
    for k, v in user_answers.items():
        if str(k) in correct and str(v).upper() == str(correct[str(k)]).upper():
            ok += 1
    return ok, total






_session_locks = {}
_session_lock_main = asyncio.Lock()

async def get_session_lock(user_id: int, test_id: str) -> asyncio.Lock:
    """Get a lock specific to this user's test session"""
    key = f"{user_id}:{test_id}"
    async with _session_lock_main:
        if key not in _session_locks:
            _session_locks[key] = asyncio.Lock()
        return _session_locks[key]

def get_session_path(user_id: int, test_id: str) -> Path:
    """Get the path for a specific session file"""
    session_dir = Path("data/sessions")
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir / f"session_{user_id}_{test_id}.json"

async def save_test_session_safe(user_id: int, test_id: str, session_data: dict) -> bool:
    """Thread-safe session saving with error handling"""
    try:
        session_lock = await get_session_lock(user_id, test_id)
        async with session_lock:
            # Prepare data for JSON serialization
            clean_data = session_data.copy()
            clean_data['last_updated'] = int(time.time())
            
            # Handle excluded_options conversion
            if 'excluded_options' in clean_data:
                clean_excluded = {}
                for k, v in clean_data['excluded_options'].items():
                    if isinstance(v, set):
                        clean_excluded[k] = list(v)
                    elif isinstance(v, list):
                        clean_excluded[k] = v
                    else:
                        clean_excluded[k] = []
                clean_data['excluded_options'] = clean_excluded
            
            # Write to temporary file first, then move (atomic operation)
            session_path = get_session_path(user_id, test_id)
            temp_path = session_path.with_suffix('.tmp')
            
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(clean_data, f, ensure_ascii=False, indent=2)
            
            # Atomic move
            temp_path.replace(session_path)
            return True
            
    except Exception as e:
        log.error(f"Failed to save session for user {user_id}, test {test_id}: {e}")
        return False

async def load_test_session_safe(user_id: int, test_id: str) -> Optional[dict]:
    """Thread-safe session loading with error handling"""
    try:
        session_lock = await get_session_lock(user_id, test_id)
        async with session_lock:
            session_path = get_session_path(user_id, test_id)
            
            if not session_path.exists():
                return None
            
            with open(session_path, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
            
            # Convert excluded_options back to the expected format
            if 'excluded_options' in session_data:
                for k, v in session_data['excluded_options'].items():
                    if isinstance(v, list):
                        session_data['excluded_options'][k] = v
            
            return session_data
            
    except Exception as e:
        log.error(f"Failed to load session for user {user_id}, test {test_id}: {e}")
        return None

async def delete_test_session_safe(user_id: int, test_id: str) -> bool:
    """Thread-safe session deletion"""
    try:
        session_lock = await get_session_lock(user_id, test_id)
        async with session_lock:
            session_path = get_session_path(user_id, test_id)
            
            if session_path.exists():
                session_path.unlink()
                return True
            return False
            
    except Exception as e:
        log.error(f"Failed to delete session for user {user_id}, test {test_id}: {e}")
        return False

def get_user_sessions_safe(user_id: int) -> List[Dict]:
    """Get all sessions for a user"""
    try:
        session_dir = Path("data/sessions")
        if not session_dir.exists():
            return []
        
        sessions = []
        pattern = f"session_{user_id}_*.json"
        
        for session_file in session_dir.glob(pattern):
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)
                
                test_id = session_data.get("active_test_id")
                if test_id:
                    # Get test info
                    test = read_test(test_id)
                    if test:
                        current_q = session_data.get("current_q", 1)
                        total_q = session_data.get("total_q", 0)
                        
                        sessions.append({
                            "test_id": test_id,
                            "test_name": test.get("test_name", "Test"),
                            "progress": f"{current_q}/{total_q}",
                            "started_at": session_data.get("started_at", 0),
                            "last_updated": session_data.get("last_updated", 0)
                        })
                        
            except Exception as e:
                log.warning(f"Error reading session file {session_file}: {e}")
                continue
        
        # Sort by last updated
        sessions.sort(key=lambda x: x.get("last_updated", 0), reverse=True)
        return sessions
        
    except Exception as e:
        log.error(f"Failed to get user sessions for {user_id}: {e}")
        return []

# Improved error handling for student operations
async def handle_student_error(cb_or_msg, error: Exception, context: str = "operation"):
    """Centralized error handling for student operations"""
    log.error(f"Student {context} error: {error}")
    
    user_friendly_message = "Xatolik yuz berdi. Iltimos qaytadan urinib ko'ring."
    
    # Specific error handling
    if "Test topilmadi" in str(error):
        user_friendly_message = "Test topilmadi yoki o'chirilgan. /start buyrug'ini yuboring."
    elif "permission" in str(error).lower():
        user_friendly_message = "Bu test uchun ruxsatingiz yo'q."
    elif "session" in str(error).lower():
        user_friendly_message = "Sessiya xatoligi. /start buyrug'ini yuboring."
    
    try:
        if hasattr(cb_or_msg, 'answer'):  # CallbackQuery
            await cb_or_msg.answer(user_friendly_message, show_alert=True)
        else:  # Message
            await cb_or_msg.reply(user_friendly_message)
    except Exception as e:
        log.error(f"Failed to send error message: {e}")

        # Add these wrapper functions to utils.py to maintain compatibility with student_handlers.py

def save_test_session(user_id: int, test_id: str, session_data: dict) -> bool:
    """Synchronous wrapper for save_test_session_safe"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If called from async context, create task
            future = asyncio.ensure_future(save_test_session_safe(user_id, test_id, session_data))
            return True  # Return immediately, save happens in background
        else:
            # If called from sync context, run until complete
            return loop.run_until_complete(save_test_session_safe(user_id, test_id, session_data))
    except Exception as e:
        log.error(f"Error in save_test_session wrapper: {e}")
        # Fallback to simple file write
        try:
            session_path = get_session_path(user_id, test_id)
            session_path.parent.mkdir(parents=True, exist_ok=True)
            with open(session_path, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as fallback_error:
            log.error(f"Fallback save also failed: {fallback_error}")
            return False

def load_test_session(user_id: int, test_id: str) -> Optional[dict]:
    """Synchronous wrapper for load_test_session_safe"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Can't run async in already running loop, use sync fallback
            session_path = get_session_path(user_id, test_id)
            if not session_path.exists():
                return None
            with open(session_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            return loop.run_until_complete(load_test_session_safe(user_id, test_id))
    except Exception as e:
        log.error(f"Error in load_test_session wrapper: {e}")
        return None

def delete_test_session(user_id: int, test_id: str) -> bool:
    """Synchronous wrapper for delete_test_session_safe"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Can't run async in already running loop, use sync fallback
            session_path = get_session_path(user_id, test_id)
            if session_path.exists():
                session_path.unlink()
                return True
            return False
        else:
            return loop.run_until_complete(delete_test_session_safe(user_id, test_id))
    except Exception as e:
        log.error(f"Error in delete_test_session wrapper: {e}")
        return False

def get_user_sessions(user_id: int) -> List[Dict]:
    """Wrapper for get_user_sessions_safe (already synchronous)"""
    return get_user_sessions_safe(user_id)

# ========== GROUP ADMIN MANAGEMENT ==========

async def sync_group_admins(group_id: int) -> Dict[int, dict]:
    """
    Sync Telegram group admins with local data.
    This fetches admins from Telegram and updates our local records.
    """
    try:
        from config import bot, OWNER_ID
        
        # Get current admins from Telegram
        chat_admins = await bot.get_chat_administrators(group_id)
        
        telegram_admins = {}
        for admin in chat_admins:
            if not admin.user.is_bot:
                telegram_admins[admin.user.id] = {
                    'username': admin.user.username or '',
                    'first_name': admin.user.first_name or '',
                    'last_name': admin.user.last_name or '',
                    'status': admin.status,
                    'is_creator': admin.status == 'creator'
                }
        
        # Load current admin data
        admins_data = load_admins()
        if 'group_admins' not in admins_data:
            admins_data['group_admins'] = {}
        
        # Process each Telegram admin
        for admin_id, admin_info in telegram_admins.items():
            admin_id_str = str(admin_id)
            
            # Skip bot owner (they're always super admin)
            if admin_id == OWNER_ID:
                continue
            
            # Update or create admin entry
            if admin_id_str not in admins_data['group_admins']:
                admins_data['group_admins'][admin_id_str] = {
                    'groups': [],
                    'name': f"{admin_info['first_name']} {admin_info['last_name']}".strip(),
                    'username': admin_info['username'],
                    'can_create': True,
                    'can_activate': True
                }
            
            # Add this group to admin's list if not present
            if group_id not in admins_data['group_admins'][admin_id_str]['groups']:
                admins_data['group_admins'][admin_id_str]['groups'].append(group_id)
            
            # Update admin info
            admins_data['group_admins'][admin_id_str]['username'] = admin_info['username']
            admins_data['group_admins'][admin_id_str]['name'] = f"{admin_info['first_name']} {admin_info['last_name']}".strip()
        
        # Remove admins who are no longer admins in Telegram
        for admin_id_str in list(admins_data['group_admins'].keys()):
            admin_data = admins_data['group_admins'][admin_id_str]
            if group_id in admin_data['groups']:
                if int(admin_id_str) not in telegram_admins:
                    admin_data['groups'].remove(group_id)
                    # If admin has no groups left, remove them
                    if not admin_data['groups']:
                        del admins_data['group_admins'][admin_id_str]
        
        # Save updated admin data
        save_admins(admins_data)
        
        log.info(f"Synced {len(telegram_admins)} admins for group {group_id}")
        return telegram_admins
        
    except Exception as e:
        log.error(f"Failed to sync admins for group {group_id}: {e}")
        return {}

def is_group_admin(user_id: int, group_id: int) -> bool:
    """Check if user is admin for a specific group"""
    if is_owner(user_id):
        return True
    
    admins_data = load_admins()
    group_admins = admins_data.get('group_admins', {})
    user_admin_data = group_admins.get(str(user_id), {})
    
    return group_id in user_admin_data.get('groups', [])

def get_user_admin_groups(user_id: int) -> List[int]:
    """Get all groups where user is admin"""
    if is_owner(user_id):
        return load_group_ids()  # Owner can access all groups
    
    admins_data = load_admins()
    group_admins = admins_data.get('group_admins', {})
    user_admin_data = group_admins.get(str(user_id), {})
    
    return user_admin_data.get('groups', [])

def can_user_create_test(user_id: int) -> bool:
    """Check if user can create tests"""
    if is_owner(user_id):
        return True
    
    admins_data = load_admins()
    group_admins = admins_data.get('group_admins', {})
    user_admin_data = group_admins.get(str(user_id), {})
    
    return user_admin_data.get('can_create', False) and len(user_admin_data.get('groups', [])) > 0

def can_user_manage_test(user_id: int, test_id: str) -> bool:
    """Check if user can manage a specific test"""
    if is_owner(user_id):
        return True
    
    test_data = read_test(test_id)
    if not test_data:
        return False
    
    test_groups = set()
    for g in test_data.get('groups', []):
        try:
            test_groups.add(int(g))
        except:
            pass
    
    user_admin_groups = set(get_user_admin_groups(user_id))
    
    # User can manage if they admin any group the test is assigned to
    return bool(test_groups.intersection(user_admin_groups))

def is_admin(user_id: int) -> bool:
    """Check if user is admin of any group"""
    if is_owner(user_id):
        return True
    
    admins_data = load_admins()
    group_admins = admins_data.get('group_admins', {})
    
    return str(user_id) in group_admins and len(group_admins[str(user_id)].get('groups', [])) > 0

async def get_bot_admin_groups(user_id: int) -> List[int]:
    """
    Get groups where the BOT is admin, filtered by user permissions.
    For owner: all groups where bot is admin
    For admins: only their assigned groups where bot is admin
    """
    try:
        from config import bot
        
        all_groups = load_group_ids()
        bot_admin_groups = []
        
        # Check each group to see if bot is admin
        for group_id in all_groups:
            try:
                bot_member = await bot.get_chat_member(group_id, (await bot.get_me()).id)
                if bot_member.status in ["administrator", "creator"]:
                    bot_admin_groups.append(group_id)
            except Exception as e:
                log.debug(f"Bot not admin in group {group_id}: {e}")
                continue
        
        # Filter based on user permissions
        if is_owner(user_id):
            # Owner can access all groups where bot is admin
            return bot_admin_groups
        else:
            # Admins can only access their assigned groups
            user_admin_groups = get_user_admin_groups(user_id)
            return [gid for gid in bot_admin_groups if gid in user_admin_groups]
    
    except Exception as e:
        log.error(f"Error getting bot admin groups: {e}")
        return []
# utils.py
def get_users_with_active_sessions(max_age_hours: int = 6) -> List[int]:
    """
    Get user IDs who have active test sessions.
    Only considers sessions updated within max_age_hours.
    """
    try:
        session_dir = Path("data/sessions")
        if not session_dir.exists():
            return []
        
        active_users = set()
        cutoff_time = time.time() - (max_age_hours * 3600)
        
        # Check session files
        for session_file in session_dir.glob("*.json"):
            try:
                # Check file modification time first
                if session_file.stat().st_mtime < cutoff_time:
                    continue
                
                # Parse filename to get user_id
                # Expecting format: session_<user_id>_<test_id>.json or <user_id>/<test_id>.json
                if session_file.name.startswith("session_"):
                    parts = session_file.stem.split("_")
                    if len(parts) >= 2:
                        user_id = int(parts[1])
                        active_users.add(user_id)
                elif session_file.parent.name.isdigit():
                    # User directory structure
                    user_id = int(session_file.parent.name)
                    active_users.add(user_id)
            except (ValueError, IndexError, OSError) as e:
                log.debug(f"Skipping session file {session_file}: {e}")
                continue
        
        # Also check user session directories
        for user_dir in session_dir.iterdir():
            if user_dir.is_dir() and user_dir.name.isdigit():
                try:
                    user_id = int(user_dir.name)
                    
                    # Check if user has any recent session files
                    for test_session in user_dir.glob("*.json"):
                        if test_session.stat().st_mtime >= cutoff_time:
                            active_users.add(user_id)
                            break
                except (ValueError, OSError):
                    continue
        
        return sorted(active_users)
        
    except Exception as e:
        log.error(f"Error getting users with active sessions: {e}")
        return []


async def notify_groups_and_members(group_ids: List[int], test_name: str, test_id: str) -> Dict:
    """
    Notify groups and their members about a new test.
    First tries private messages, then notifies groups with statistics.
    """
    from config import bot
    
    results = {
        'total_notified': 0,
        'total_failed': 0,
        'groups_notified': 0,
        'group_details': {}
    }
    
    bot_username = (await bot.get_me()).username
    
    for group_id in group_ids:
        group_results = {
            'members': 0,
            'notified': 0,
            'failed': 0,
            'failed_users': []
        }
        
        # Get group members
        member_ids = get_group_member_ids(group_id)
        member_data = get_group_member_data(group_id)
        group_results['members'] = len(member_ids)
        
        # Try to send private messages
        for user_id in member_ids:
            try:
                private_message = (
                    f"🎯 <b>Yangi test faollashtirildi!</b>\n\n"
                    f"📚 Test nomi: <b>{test_name}</b>\n"
                    f"🏷 Test kodi: <code>{test_id}</code>\n\n"
                    f"Testni boshlash uchun:\n"
                    f"👉 @{bot_username} ga o'ting\n"
                    f"👉 /start buyrug'ini yuboring\n\n"
                    f"⏰ Test hozir faol!"
                )
                
                await bot.send_message(user_id, private_message)
                group_results['notified'] += 1
                
                # Small delay to avoid rate limits
                await asyncio.sleep(0.05)
                
            except Exception as e:
                group_results['failed'] += 1
                user_info = member_data.get(str(user_id), {})
                username = user_info.get('username', '')
                name = f"{user_info.get('first_name', '')} {user_info.get('last_name', '')}".strip() or f"User {user_id}"
                
                group_results['failed_users'].append({
                    'name': name,
                    'username': username,
                    'id': user_id
                })
                log.debug(f"Failed to notify user {user_id}: {e}")
        
        # Send message to group
        try:
            group_titles = load_group_titles()
            group_title = group_titles.get(group_id, f"Guruh {group_id}")
            
            group_message = (
                f"📢 <b>YANGI TEST BOSHLANDI!</b>\n\n"
                f"📚 Test: <b>{test_name}</b>\n"
                f"👥 Guruh: {group_title}\n"
                f"🎯 Barcha guruh a'zolari uchun!\n\n"
            )
            
            if group_results['notified'] > 0:
                group_message += f"✅ {group_results['notified']} ta talabaga shaxsiy xabar yuborildi\n"
            
            if group_results['failed'] > 0:
                group_message += f"\n⚠️ {group_results['failed']} ta talabaga xabar yetmadi:\n"
                
                # List first 5 unreachable users
                for i, user in enumerate(group_results['failed_users'][:5]):
                    username_str = f"@{user['username']}" if user['username'] else f"ID: {user['id']}"
                    group_message += f"{i+1}. {user['name']} ({username_str})\n"
                
                if group_results['failed'] > 5:
                    group_message += f"... va yana {group_results['failed'] - 5} kishi\n"
                
                group_message += "\n💡 Ular botni bloklagan yoki yoqmagan bo'lishi mumkin.\n"
            
            group_message += (
                f"\nTestni boshlash uchun:\n"
                f"👉 @{bot_username} botiga o'ting\n"
                f"👉 /start buyrug'ini yuboring"
            )
            
            await bot.send_message(group_id, group_message)
            results['groups_notified'] += 1
            
        except Exception as e:
            log.error(f"Failed to notify group {group_id}: {e}")
        
        # Update totals
        results['total_notified'] += group_results['notified']
        results['total_failed'] += group_results['failed']
        results['group_details'][group_id] = group_results
        
        # Delay between groups
        await asyncio.sleep(0.5)
    
    return results
async def validate_and_sync_new_user(user_id: int) -> Tuple[bool, List[int]]:
    
    """
    Validate if a user is in any groups, syncing with owner account if needed.
    Specifically designed for users starting the bot for the first time.
    """
    try:
        # First check if user exists in our data
        user_groups = get_user_groups(user_id)
        gm = load_group_members()
        
        user_found_in_data = False
        for gid_str, rec in gm.items():
            if user_id in rec.get("members", []):
                user_found_in_data = True
                break
        
        if user_found_in_data or user_groups:
            # User exists, validate they're still in groups
            return await validate_user_still_in_groups(user_id)
        
        # User not in our data - they might be new
        log.info(f"User {user_id} not found in data, checking with owner account...")
        
        # Get owner's Telethon client
        from telethon_service import get_user_telethon_service
        user_telethon = await get_user_telethon_service()
        
        if not user_telethon:
            log.error("Owner Telethon not available for new user check")
            return False, []
        
        # Get all groups where bot is present
        groups = load_group_ids()
        found_groups = []
        
        for group_id in groups:
            try:
                # Fetch ALL members using owner account
                members, _ = await user_telethon.fetch_all_group_members(group_id)
                
                # Check if our user is in this group
                for member in members:
                    if member['id'] == user_id:
                        found_groups.append(group_id)
                        
                        # Add user to our data immediately
                        add_user_to_group(user_id, group_id)
                        
                        # Update member data
                        gm = load_group_members()
                        if str(group_id) not in gm:
                            gm[str(group_id)] = {"members": [], "member_data": {}}
                        
                        gm[str(group_id)]["member_data"][str(user_id)] = {
                            "first_name": member.get("first_name", ""),
                            "last_name": member.get("last_name", ""),
                            "username": member.get("username", ""),
                            "phone": member.get("phone", ""),
                            "is_premium": member.get("is_premium", False),
                            "is_bot": False,
                            "is_admin": False
                        }
                        write_json(Path(GROUP_MEMBERS_FILE), gm)
                        
                        log.info(f"Found and added new user {user_id} to group {group_id}")
                        break
                
                # Small delay to avoid rate limits
                await asyncio.sleep(0.2)
                
            except Exception as e:
                log.error(f"Error checking group {group_id} for user {user_id}: {e}")
                continue
        
        return len(found_groups) > 0, found_groups
        
    except Exception as e:
        log.error(f"Error in validate_and_sync_new_user for {user_id}: {e}")
        return False, []