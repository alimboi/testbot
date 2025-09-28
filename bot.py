import logging
import sys
import time
import asyncio, random
import re
from pathlib import Path
import json


# Check aiogram version and import accordingly
try:
    # Try aiogram 3.x imports first
    from aiogram import Dispatcher, executor, types
    from aiogram.types import ChatMemberUpdated
    from aiogram.dispatcher import FSMContext
    AIOGRAM_VERSION = 3
except ImportError:
    try:
        # Fallback to aiogram 2.x imports
        from aiogram import Dispatcher, executor, types
        from aiogram.types import ChatMemberUpdated
        from aiogram.dispatcher import FSMContext
        AIOGRAM_VERSION = 2
    except ImportError as e:
        print(f"Critical aiogram import error: {e}", file=sys.stderr)
        sys.exit(1)

# Import with fallback error handling
try:
    from custom_storage import CustomJSONStorage
    from config import bot, OWNER_ID, ALLOWED_UPDATES
    from logging_setup import setup_logging
    from middleware import AuditMiddleware
    from audit import log_action
    from utils import ensure_data, is_owner
    from states import StudentStates, AdminStates
except ImportError as e:
    print(f"Critical import error: {e}", file=sys.stderr)
    print("Please ensure all required modules are present and config.py is properly configured", file=sys.stderr)
    sys.exit(1)

# Admin/Owner panel handlers
from admin_handlers import (
    owner_panel,
    callbacks_router,
    owner_receive_docx,
    msg_receive_group_ids,
    cb_admin_action,
    cb_new_test_action,
    cb_show_group_students,
    cb_sync_single_group,
)

# Student flow handlers - UPDATED imports
from student_handlers import (
    student_start,
    receive_test_id,
    on_answer,
    student_entering_name,
    student_confirming_name,
    process_understanding,
    process_start_choice,
    handle_test_selection,
    handle_new_test,
    handle_resume,
    handle_restart,
    process_understanding_response,
    safe_student_operation,
    rate_limit,
    cleanup_old_user_sessions,
)
from utils import (
    ensure_data,
    is_owner,
    load_group_ids,
    load_group_titles,
    load_group_members,
    load_admins,
    save_admins,
    get_user_groups,
    add_user_to_group,
    remove_group,
    add_or_update_group,
    sync_group_admins,
    get_user_admin_groups,
    can_user_create_test,
    available_tests_for_user,
    get_active_tests,
    load_tests_index,
    read_test,
    write_test,
    sync_all_groups,
    sync_group_members,
    get_group_member_data,
    notify_group_students,
    get_unreachable_users_info,
    remove_user_admin_privileges,
    remove_user_from_group_completely,
    validate_user_still_in_groups,
    USER_GROUPS_FILE,
    GROUP_MEMBERS_FILE,
    Path,
    read_json,
    write_json,
    get_users_with_active_sessions,
)
from telethon_service import get_user_telethon_service, stop_user_telethon_service

# Setup logging first
setup_logging()
log = logging.getLogger("bot")
_CONNECTION_STATUS = {"online": True}
_users_to_notify = set()

# FSM storage (local JSON file) - FIXED FOR AIOGRAM 3.x
try:
    storage = CustomJSONStorage("data/fsm_states.json")
    dp = Dispatcher(bot, storage=storage)
    log.info(f"Custom JSON storage initialized successfully (aiogram v{AIOGRAM_VERSION})")
except Exception as e:
    log.error(f"Failed to initialize custom storage: {e}")
    # Fallback based on aiogram version
    if AIOGRAM_VERSION >= 3:
        from aiogram.fsm.storage.memory import MemoryStorage
    else:
        from aiogram.contrib.fsm_storage.memory import MemoryStorage
    
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)
    log.warning(f"Using fallback MemoryStorage instead of custom storage (aiogram v{AIOGRAM_VERSION})")

# Middleware (audit)
dp.middleware.setup(AuditMiddleware())

# -------------------------
# Global navigation helpers
# -------------------------

# /cancel or /back should always exit any state
@dp.message_handler(commands=['cancel', 'back'], state='*')
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.finish()
    await message.reply("Cancelled. Use /start to open the menu.")

# /start must work even if you're inside some state
# IN bot.py, MODIFY the cmd_start_any handler (around line 100):

@dp.message_handler(commands=['start'], state='*')
async def cmd_start_any(message: types.Message, state: FSMContext):
    await state.finish()  # exit any pending input state
    
    # If in group, redirect to private
    if message.chat.type in ("group", "supergroup"):
        bot_info = await bot.get_me()
        await message.reply(
            f"💬 Iltimos, menga shaxsiy xabar yuboring!\n\n"
            f"👉 @{bot_info.username} ga o'ting va /start bosing",
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(
                    "💬 Shaxsiy chat",
                    url=f"https://t.me/{bot_info.username}?start=from_group"
                )
            )
        )
        return
    
    # Private chat - continue normally
    ensure_data()
    
    if is_owner(message.from_user.id):
        await owner_panel(message)
    else:
        await student_start(message, state)

# -------------------------
# Student flow (public) - ENHANCED WITH RATE LIMITING AND ERROR HANDLING
# -------------------------

# 1. MOST SPECIFIC FIRST - Answer buttons during answering state with validation and rate limiting
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("ans:") and len(c.data.split(":")) == 3, state=StudentStates.Answering)
@rate_limit(max_calls=10, window_seconds=60)
async def cb_ans_safe(cb: types.CallbackQuery, state: FSMContext):
    """Rate-limited and error-safe answer handler"""
    log.info(f"Answer callback received: {cb.data}")
    current_state = await state.get_state()
    log.info(f"Current user state: {current_state}")
    return await safe_student_operation(on_answer, cb, state)

# 2. Test selection from clickable buttons with validation
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("select_test:") and len(c.data.replace("select_test:", "")) > 0, state=StudentStates.Choosing)
@rate_limit(max_calls=5, window_seconds=30)
async def cb_select_test_safe(cb: types.CallbackQuery, state: FSMContext):
    """Rate-limited and error-safe test selection"""
    log.info(f"Test selection callback: {cb.data}")
    return await safe_student_operation(handle_test_selection, cb, state)

# 3. Resume/restart handlers with validation
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("resume:"), state=StudentStates.Choosing)
@rate_limit(max_calls=3, window_seconds=30)
async def cb_resume_safe(cb: types.CallbackQuery, state: FSMContext):
    """Rate-limited and error-safe resume handler"""
    return await safe_student_operation(handle_resume, cb, state)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("restart:"), state=StudentStates.Choosing)
@rate_limit(max_calls=3, window_seconds=30)
async def cb_restart_safe(cb: types.CallbackQuery, state: FSMContext):
    """Rate-limited and error-safe restart handler"""
    return await safe_student_operation(handle_restart, cb, state)

# 4. Understanding response during answering
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("understand:"), state=StudentStates.Answering)
async def cb_understand_safe(cb: types.CallbackQuery, state: FSMContext):
    """Error-safe understanding response handler"""
    return await safe_student_operation(process_understanding_response, cb, state)

# 5. New test selection
@dp.callback_query_handler(lambda c: c.data == "new_test", state=StudentStates.Choosing)
async def cb_new_test_safe(cb: types.CallbackQuery, state: FSMContext):
    """Error-safe new test handler"""
    return await safe_student_operation(handle_new_test, cb, state)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("asg:"))
async def cb_assign_groups_flow(cb: types.CallbackQuery, state: FSMContext):
    from admin_handlers import cb_assign_groups_action
    await cb_assign_groups_action(cb, state)

# 6. Resume / Restart from /start if unfinished session
@dp.callback_query_handler(lambda c: c.data in {"st:cont", "st:restart"}, state=StudentStates.Choosing)
async def cb_start_choice_safe(cb: types.CallbackQuery, state: FSMContext):
    """Error-safe start choice handler"""
    return await safe_student_operation(process_start_choice, cb, state)

# 7. Name confirm buttons
@dp.callback_query_handler(lambda c: c.data in {"st:name_ok", "st:name_re"}, state=StudentStates.ConfirmingName)
async def cb_name_confirm_safe(cb: types.CallbackQuery, state: FSMContext):
    """Error-safe name confirmation handler"""
    return await safe_student_operation(student_confirming_name, cb, state)

# 8. Understanding → start test
@dp.callback_query_handler(lambda c: c.data == "st:understood", state=StudentStates.Understanding)
async def cb_understood_safe(cb: types.CallbackQuery, state: FSMContext):
    """Error-safe understanding handler"""
    return await safe_student_operation(process_understanding, cb, state)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("new_t:"))
async def cb_new_test_flow(cb: types.CallbackQuery, state: FSMContext):
    """Handle new test creation flow callbacks"""
    log.info(f"New test flow callback: {cb.data}")
    await cb_new_test_action(cb, state)

# Group students display handlers
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("show_group_students:"))
async def cb_group_students(cb: types.CallbackQuery, state: FSMContext):
    """Handle group students display"""
    log.info(f"Group students callback: {cb.data}")
    await cb_show_group_students(cb)

# Single group sync handler
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("sync_group:"))
async def cb_sync_group(cb: types.CallbackQuery, state: FSMContext):
    """Handle single group sync"""
    log.info(f"Sync group callback: {cb.data}")
    await cb_sync_single_group(cb)

# -------------------------
# Owner/Admin panel & routing (SECOND PRIORITY)
# -------------------------


# Replace line 189-195 with:
@dp.callback_query_handler(lambda c: c.data and (
    c.data.startswith("panel:") or 
    c.data.startswith("g:") or
    c.data == "back"
))
async def cb_panel(cb: types.CallbackQuery, state: FSMContext):
    log.info(f"Owner panel callback: {cb.data}")
    await callbacks_router(cb, state)

# Add separate handler for test actions
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("t:"))
async def cb_test_actions(cb: types.CallbackQuery, state: FSMContext):
    log.info(f"Test action callback: {cb.data}")
    from admin_handlers import cb_test_action
    await cb_test_action(cb, state)



# -------------------------
# Message handlers with enhanced validation
# -------------------------

# Name input text with comprehensive validation
@dp.message_handler(state=StudentStates.EnteringName)
async def msg_name_safe(message: types.Message, state: FSMContext):
    """Input-validated name entry"""
    try:
        # Validate input
        name = (message.text or "").strip()
        if not name:
            return await message.reply("Iltimos, ismingizni kiriting.")
        
        if len(name) < 2:
            return await message.reply("Ism juda qisqa. Kamida 2 ta harf kiriting.")
        
        if len(name) > 100:
            return await message.reply("Ism juda uzun. 100 ta harfdan kam kiriting.")
        
        # Basic sanitization - allow Unicode letters, spaces, hyphens, apostrophes, dots
        if not re.match(r'^[a-zA-ZА-Яа-яЁё\u0100-\u017F\u0180-\u024F\s\-\'\.]+$', name, re.UNICODE):
            return await message.reply("Iltimos, faqat harflar va bo'sh joylardan foydalaning.")
        
        await student_entering_name(message, state)
    except Exception as e:
        log.error(f"Error in name validation: {e}")
        await safe_student_operation(student_entering_name, message, state)

# DEPRECATED: User sends "test_<uuid>" while choosing a test (keeping for backward compatibility)
@dp.message_handler(lambda m: m.text and m.text.lower().startswith("test_"), state=StudentStates.Choosing)
async def on_test_id_safe(message: types.Message, state: FSMContext):
    """Backward compatibility test ID handler"""
    return await safe_student_operation(receive_test_id, message, state)

# Owner sends DOCX to create a test
@dp.message_handler(content_types=['document'])
async def on_docx(message: types.Message, state: FSMContext):
    from utils import can_user_create_test
    if can_user_create_test(message.from_user.id):
        await owner_receive_docx(message, state)
    else:
        await message.reply("Sizda test yaratish huquqi yo'q.")

# Owner replies with group IDs during Assign/Add/Remove flows
@dp.message_handler(state=AdminStates.Confirming)
async def on_group_ids(message: types.Message, state: FSMContext):
    await msg_receive_group_ids(message, state)

# -------------------------
# Utilities - ALL ORIGINAL COMMANDS PRESERVED
# -------------------------

@dp.message_handler(commands=['mychatid'])
async def cmd_mychatid(message: types.Message):
    await message.reply(f"Chat ID: <code>{message.chat.id}</code>")

@dp.message_handler(commands=['registergroup'])
async def cmd_registergroup(message: types.Message):
    """Owner-only; run inside the target group to append its id to data/groups.txt."""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    if message.chat.type not in ("group", "supergroup"):
        return await message.reply("Run this inside the group you want to register.")

    gid = message.chat.id
    
    try:
        from utils import add_or_update_group
        title = message.chat.title or ""
        add_or_update_group(gid, title)
        await message.reply(f"Registered group: <code>{gid}</code> - {title}")
        log_action(message.from_user.id, "group_register", ok=True, group_id=gid)
    except Exception as e:
        await message.reply(f"Error registering group: {e}")
        log_action(message.from_user.id, "group_register", ok=False, group_id=gid, note=str(e))

@dp.message_handler(commands=['debug'])
async def cmd_debug(message: types.Message):
    """Debug command for troubleshooting (owner only)"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    try:
        from utils import (
            load_group_ids, load_group_members, get_active_tests, 
            load_tests_index, get_user_groups, available_tests_for_user
        )
        
        lines = ["<b>Debug Info:</b>", ""]
        
        # Storage info
        lines.append(f"Aiogram version: {AIOGRAM_VERSION}")
        lines.append(f"Storage type: {type(storage).__name__}")
        
        # Groups
        groups = load_group_ids()
        lines.append(f"Registered groups: {len(groups)}")
        for gid in groups[:5]:  # Show first 5
            lines.append(f"  • {gid}")
        
        # Group members
        gm = load_group_members()
        total_members = sum(len(data.get("members", [])) for data in gm.values())
        lines.append(f"Total tracked members: {total_members}")
        
        # Active tests
        active = get_active_tests()
        lines.append(f"Active tests: {len(active)}")
        
        # Test assignments
        tests_index = load_tests_index()
        tests_with_groups = 0
        for tid, test_info in tests_index.get("tests", {}).items():
            if test_info.get("groups"):
                tests_with_groups += 1
        lines.append(f"Tests with group assignments: {tests_with_groups}")
        
        # If in PM, check user's test access
        if message.chat.type == "private":
            user_groups = get_user_groups(message.from_user.id)
            available = available_tests_for_user(message.from_user.id)
            lines.append(f"Your groups: {user_groups}")
            lines.append(f"Available tests for you: {len(available)}")
        
        # Storage states (if available)
        if hasattr(storage, 'get_states_list'):
            states = await storage.get_states_list()
            lines.append(f"Active FSM states: {len(states)}")
        elif hasattr(storage, '_data'):
            lines.append(f"Active FSM states: {len(storage._data)}")
        
        await message.reply("\n".join(lines))
        
    except Exception as e:
        await message.reply(f"Debug error: {e}")

@dp.message_handler(commands=['syncgroups'])
async def cmd_sync_groups(message: types.Message):
    """Manual group sync command (owner only)"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    try:
        from utils import sync_all_groups
        
        await message.reply("Syncing all groups...")
        results = await sync_all_groups()
        
        total = sum(results.values())
        lines = [f"Sync complete! Total members: {total}", ""]
        
        for gid, count in results.items():
            lines.append(f"Group {gid}: {count} members")
        
        await message.reply("\n".join(lines))
        
    except Exception as e:
        await message.reply(f"Sync error: {e}")

@dp.message_handler(commands=['joingroup'])
async def cmd_join_group(message: types.Message):
    """Force join current group for testing (owner only)"""
    if not is_owner(message.from_user.id):
        return
        
    if message.chat.type not in ("group", "supergroup"):
        return await message.reply("Use this in a group.")
    
    try:
        from utils import add_user_to_group
        add_user_to_group(message.from_user.id, message.chat.id)
        await message.reply(f"Added you to group {message.chat.id}")
    except Exception as e:
        await message.reply(f"Error: {e}")

@dp.message_handler(commands=['notify'])
async def cmd_notify_test(message: types.Message):
    """Manually notify students about an active test (owner only)"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    args = message.get_args()
    if not args:
        # Show available tests
        from utils import get_active_tests, read_test
        active = get_active_tests()
        if not active:
            return await message.reply("No active tests to notify about.")
        
        lines = ["Active tests you can notify about:\n"]
        for test_id in active:
            test_data = read_test(test_id)
            name = test_data.get("test_name", "Test")
            groups = test_data.get("groups", [])
            lines.append(f"• <code>{test_id}</code> - {name} (Groups: {', '.join(map(str, groups))})")
        
        lines.append(f"\nUsage: /notify <test_id>")
        return await message.reply("\n".join(lines))
    
    test_id = args.strip()
    
    try:
        from utils import read_test, notify_group_students, get_unreachable_users_info
        
        test_data = read_test(test_id)
        if not test_data:
            return await message.reply("Test not found.")
        
        test_name = test_data.get("test_name", "Test")
        assigned_groups = test_data.get("groups", [])
        
        if not assigned_groups:
            return await message.reply("Test has no assigned groups.")
        
        await message.reply(f"Notifying students about test '{test_name}'...")
        
        total_notified = 0
        total_failed = 0
        
        for group_id in assigned_groups:
            try:
                group_id = int(group_id)
                notified, failed = await notify_group_students(group_id, test_name, test_id)
                total_notified += len(notified)
                total_failed += len(failed)
            except Exception as e:
                log.error(f"Failed to notify group {group_id}: {e}")
        
        summary = f"✅ Notification complete!\n\n"
        summary += f"📊 Results:\n"
        summary += f"• ✅ Notified: {total_notified} students\n"
        summary += f"• ❌ Failed: {total_failed} students"
        
        await message.reply(summary)
        
    except Exception as e:
        await message.reply(f"Notification error: {e}")

@dp.message_handler(commands=['telethon'])
async def cmd_telethon_status(message: types.Message):
    """Check Telethon service status (owner only)"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    try:
        from telethon_service import get_telethon_service
        
        telethon = await get_telethon_service()
        if not telethon:
            return await message.reply("❌ Telethon service not available")
        
        is_connected = await telethon.is_connected()
        if is_connected:
            await message.reply("✅ Telethon service is running and connected")
        else:
            await message.reply("⚠️ Telethon service exists but not connected")
            
    except Exception as e:
        await message.reply(f"❌ Telethon check failed: {e}")

@dp.message_handler(commands=['connection'])
async def cmd_connection_status(message: types.Message):
    """Check connection status and active sessions (owner only)"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    try:
        global _CONNECTION_STATUS, _users_to_notify
        
        # Test current connection
        try:
            await bot.get_me()
            is_responsive = True
        except:
            is_responsive = False
        
        # Get active sessions
        active_users = get_users_with_active_sessions()
        pending_notifications = len(_users_to_notify)
        
        resp_text = "✅ Ha" if is_responsive else "❌ Yo'q"
        mon_text  = "🟢 Onlayn" if _CONNECTION_STATUS["online"] else "🔴 Oflayn"



        status_text = (
            "🔍 <b>Ulanish holati</b>\n\n"
            f"🤖 Bot javob beradi: {resp_text}\n"
            f"📊 Monitor holati: {mon_text}\n"
            f"👥 Faol sessiyalar: {len(active_users)} ta foydalanuvchi\n"
            f"📢 Kutilayotgan xabarlar: {pending_notifications} ta foydalanuvchi\n\n"
        )
        
        if active_users:
            status_text += f"<b>Faol sessiyaga ega foydalanuvchilar:</b>\n"
            for user_id in active_users[:10]:  # Show first 10
                status_text += f"• Foydalanuvchi {user_id}\n"
            if len(active_users) > 10:
                status_text += f"• ... va yana {len(active_users) - 10} ta\n"
        
        await message.reply(status_text)
        
    except Exception as e:
        await message.reply(f"Ulanishni tekshirishda xatolik: {e}")

@dp.message_handler(commands=['testnotify'])
async def cmd_test_notify_connection(message: types.Message):
    """Test the reconnection notification system (owner only)"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    try:
        # Simulate offline/online cycle
        global _CONNECTION_STATUS, _users_to_notify
        
        # Capture current active users
        active_users = get_users_with_active_sessions()
        _users_to_notify.update(active_users)
        
        # Send notifications
        await notify_users_on_reconnect()
        
        await message.reply(
            f"Test xabari {len(active_users)} ta faol sessiyaga yuborildi."
        )
        
    except Exception as e:
        await message.reply(f"Test xabari xatolik: {e}")

@dp.message_handler(commands=['sessions'])
async def cmd_active_sessions(message: types.Message):
    """Show detailed active session info (owner only)"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    try:
        session_dir = Path("data/sessions")
        if not session_dir.exists():
            return await message.reply("No session directory found.")
        
        sessions_info = []
        
        # Check all session files
        for session_file in session_dir.rglob("*.json"):
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)
                
                user_id = None
                test_id = session_data.get("active_test_id", "unknown")
                
                # Extract user_id from file path or data
                if session_file.name.startswith("session_"):
                    parts = session_file.stem.split("_")
                    if len(parts) >= 2:
                        user_id = parts[1]
                elif session_file.parent.name.isdigit():
                    user_id = session_file.parent.name
                
                if user_id:
                    current_q = session_data.get("current_q", 0)
                    total_q = session_data.get("total_q", 0)
                    last_updated = session_data.get("last_updated", session_file.stat().st_mtime)
                    age_minutes = int((time.time() - last_updated) / 60)
                    
                    sessions_info.append({
                        'user_id': user_id,
                        'test_id': test_id[:8] + "..." if len(test_id) > 8 else test_id,
                        'progress': f"{current_q}/{total_q}",
                        'age_minutes': age_minutes
                    })
                    
            except Exception as e:
                log.debug(f"Error reading session {session_file}: {e}")
                continue
        
        if not sessions_info:
            return await message.reply("No active sessions found.")
        
        # Sort by age
        sessions_info.sort(key=lambda x: x['age_minutes'])
        
        lines = ["**Active Test Sessions:**\n"]
        for session in sessions_info[:20]:  # Show first 20
            lines.append(
                f"👤 User {session['user_id']}: {session['progress']} "
                f"({session['age_minutes']}m ago) - {session['test_id']}"
            )
        
        if len(sessions_info) > 20:
            lines.append(f"\n... and {len(sessions_info) - 20} more sessions")
        
        await message.reply("\n".join(lines))
        
    except Exception as e:
        await message.reply(f"Error getting session info: {e}")

@dp.message_handler(commands=['groupinfo'])
async def cmd_group_info(message: types.Message):
    """Get detailed group information (owner only)"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    args = message.get_args()
    if not args:
        from utils import load_group_ids
        groups = load_group_ids()
        if not groups:
            return await message.reply("No groups registered.\n\nUsage: /groupinfo <group_id>")
        
        lines = ["Registered groups:\n"]
        for gid in groups:
            lines.append(f"• <code>{gid}</code>")
        lines.append(f"\nUsage: /groupinfo <group_id>")
        return await message.reply("\n".join(lines))
    
    try:
        group_id = int(args.strip())
        
        from telethon_service import get_telethon_service
        from utils import load_group_members, get_group_member_data
        
        # Get info from our data
        gm = load_group_members()
        group_data = gm.get(str(group_id), {})
        member_count = len(group_data.get("members", []))
        last_sync = group_data.get("last_sync", 0)
        sync_method = group_data.get("sync_method", "none")
        
        lines = [f"<b>Group Info: {group_id}</b>\n"]
        
        # Try to get live info from Telethon
        telethon = await get_telethon_service()
        if telethon:
            group_info = await telethon.get_group_info(group_id)
            if group_info:
                lines.append(f"📝 Title: {group_info['title']}")
                lines.append(f"🔗 Username: @{group_info['username']}" if group_info['username'] else "🔗 Username: none")
                lines.append(f"📊 Live member count: {group_info['members_count']}")
                lines.append(f"🏷 Type: {group_info['type']}")
            else:
                lines.append("❌ Could not fetch live group info")
        else:
            lines.append("⚠️ Telethon not available for live info")
        
        lines.append("")
        lines.append(f"💾 <b>Stored Data:</b>")
        lines.append(f"👥 Tracked students: {member_count}")
        lines.append(f"🔄 Last sync: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_sync)) if last_sync else 'never'}")
        lines.append(f"🛠 Sync method: {sync_method}")
        
        # Show some member examples
        member_data = get_group_member_data(group_id)
        if member_data:
            lines.append(f"\n👤 <b>Sample members:</b>")
            for i, (user_id, info) in enumerate(list(member_data.items())[:5]):
                name = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip() or "No name"
                username = f"@{info['username']}" if info.get('username') else "no username"
                lines.append(f"  • {name} ({username}) - ID: {user_id}")
            
            if len(member_data) > 5:
                lines.append(f"  ... and {len(member_data) - 5} more")
        
        await message.reply("\n".join(lines))
        
    except ValueError:
        await message.reply("Invalid group ID. Must be a number.")
    except Exception as e:
        await message.reply(f"Error getting group info: {e}")


@dp.message_handler(commands=['syncadmins'])
async def cmd_sync_admins(message: types.Message):
    """Manually sync all group admins (owner only)"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    try:
        await message.reply("⏳ Barcha guruh adminlarini sinxronlash...")
        
        groups = load_group_ids()
        total_admins = 0
        
        for group_id in groups:
            admins = await sync_group_admins(group_id)
            total_admins += len(admins)
        
        from utils import load_admins
        admins_data = load_admins()
        group_admins = admins_data.get('group_admins', {})
        
        lines = [f"✅ Sinxronlash tugadi!\n"]
        lines.append(f"👨‍🏫 Jami adminlar: {len(group_admins)}")
        lines.append(f"👥 Jami guruhlar: {len(groups)}\n")
        
        lines.append("<b>Adminlar ro'yxati:</b>")
        for admin_id, admin_data in list(group_admins.items())[:10]:  # Show first 10
            name = admin_data.get('name', 'No name')
            username = admin_data.get('username', '')
            groups_count = len(admin_data.get('groups', []))
            
            admin_line = f"• {name}"
            if username:
                admin_line += f" (@{username})"
            admin_line += f": {groups_count} guruh"
            lines.append(admin_line)
        
        if len(group_admins) > 10:
            lines.append(f"... va yana {len(group_admins) - 10} admin")
        
        await message.reply("\n".join(lines))
        
    except Exception as e:
        await message.reply(f"Xatolik: {e}")

@dp.message_handler(commands=['makeadmin'])
async def cmd_make_admin(message: types.Message):
    """Manually make someone admin for specific groups (owner only)"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    args = message.get_args()
    if not args:
        return await message.reply(
            "Foydalanish:\n"
            "/makeadmin user_id group1,group2\n"
            "Masalan: /makeadmin 123456789 -100123,-100456"
        )
    
    try:
        parts = args.split(maxsplit=1)
        if len(parts) != 2:
            return await message.reply("Format: /makeadmin user_id group_ids")
        
        user_id = int(parts[0])
        group_ids = [int(g.strip()) for g in parts[1].split(',')]
        
        from utils import load_admins, save_admins
        admins_data = load_admins()
        
        if 'group_admins' not in admins_data:
            admins_data['group_admins'] = {}
        
        user_id_str = str(user_id)
        
        if user_id_str not in admins_data['group_admins']:
            admins_data['group_admins'][user_id_str] = {
                'groups': [],
                'name': f"User {user_id}",
                'username': '',
                'can_create': True,
                'can_activate': True
            }
        
        # Add groups
        for gid in group_ids:
            if gid not in admins_data['group_admins'][user_id_str]['groups']:
                admins_data['group_admins'][user_id_str]['groups'].append(gid)
        
        save_admins(admins_data)
        
        await message.reply(
            f"✅ User {user_id} endi {len(group_ids)} ta guruh admini.\n"
            f"Guruhlar: {', '.join(map(str, group_ids))}"
        )
        
    except ValueError:
        await message.reply("Noto'g'ri format. User ID va guruh ID lar raqam bo'lishi kerak.")
    except Exception as e:
        await message.reply(f"Xatolik: {e}")

@dp.message_handler(commands=['removeadmin'])
async def cmd_remove_admin(message: types.Message):
    """Remove admin from groups (owner only)"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    args = message.get_args()
    if not args:
        return await message.reply(
            "Foydalanish:\n"
            "/removeadmin user_id [group_ids]\n"
            "Barcha guruhlardan o'chirish: /removeadmin 123456789\n"
            "Ayrim guruhlardan: /removeadmin 123456789 -100123,-100456"
        )
    
    try:
        parts = args.split(maxsplit=1)
        user_id = int(parts[0])
        
        from utils import load_admins, save_admins
        admins_data = load_admins()
        
        if 'group_admins' not in admins_data:
            return await message.reply("Adminlar ro'yxati bo'sh.")
        
        user_id_str = str(user_id)
        
        if user_id_str not in admins_data['group_admins']:
            return await message.reply(f"User {user_id} admin emas.")
        
        if len(parts) == 1:
            # Remove from all groups
            del admins_data['group_admins'][user_id_str]
            await message.reply(f"✅ User {user_id} barcha guruhlardan o'chirildi.")
        else:
            # Remove from specific groups
            group_ids = [int(g.strip()) for g in parts[1].split(',')]
            admin_data = admins_data['group_admins'][user_id_str]
            
            for gid in group_ids:
                if gid in admin_data['groups']:
                    admin_data['groups'].remove(gid)
            
            # If no groups left, remove admin completely
            if not admin_data['groups']:
                del admins_data['group_admins'][user_id_str]
            
            await message.reply(f"✅ User {user_id} {len(group_ids)} ta guruhdan o'chirildi.")
        
        save_admins(admins_data)
        
    except ValueError:
        await message.reply("Noto'g'ri format. User ID va guruh ID lar raqam bo'lishi kerak.")
    except Exception as e:
        await message.reply(f"Xatolik: {e}")

@dp.message_handler(commands=['listadmins'])
async def cmd_list_admins(message: types.Message):
    """List all admins (owner only)"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    try:
        from utils import load_admins, load_group_titles
        admins_data = load_admins()
        group_admins = admins_data.get('group_admins', {})
        
        if not group_admins:
            return await message.reply("Hozircha adminlar yo'q.")
        
        group_titles = load_group_titles()
        
        lines = ["<b>👨‍🏫 Barcha adminlar:</b>\n"]
        
        for admin_id, admin_data in group_admins.items():
            name = admin_data.get('name', 'No name')
            username = admin_data.get('username', '')
            groups = admin_data.get('groups', [])
            
            admin_line = f"• {name}"
            if username:
                admin_line += f" (@{username})"
            admin_line += f" - ID: <code>{admin_id}</code>"
            lines.append(admin_line)
            
            if groups:
                lines.append("  Guruhlar:")
                for gid in groups:
                    title = group_titles.get(gid, f"Guruh {gid}")
                    lines.append(f"    - {title} (<code>{gid}</code>)")
            else:
                lines.append("  Guruhlar: yo'q")
            lines.append("")
        
        # Split into multiple messages if too long
        text = "\n".join(lines)
        if len(text) > 4000:
            # Send in chunks
            chunks = []
            current_chunk = []
            current_length = 0
            
            for line in lines:
                if current_length + len(line) > 3900:
                    chunks.append("\n".join(current_chunk))
                    current_chunk = [line]
                    current_length = len(line)
                else:
                    current_chunk.append(line)
                    current_length += len(line)
            
            if current_chunk:
                chunks.append("\n".join(current_chunk))
            
            for chunk in chunks:
                await message.reply(chunk)
        else:
            await message.reply(text)
        
    except Exception as e:
        await message.reply(f"Xatolik: {e}")

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin:"))
async def cb_admin_panel(cb: types.CallbackQuery, state: FSMContext):
    """Handle admin panel callbacks"""
    log.info(f"Admin panel callback: {cb.data}")
    await cb_admin_action(cb, state)

# Route admin test callbacks (admin_t:*)
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_t:"))
async def cb_admin_test(cb: types.CallbackQuery, state: FSMContext):
    """Handle admin test management callbacks"""
    log.info(f"Admin test callback: {cb.data}")
    await cb_admin_action(cb, state)


# Enhanced health check
async def bot_health_check() -> dict:
    """Comprehensive bot health check"""
    health = {
        "timestamp": int(time.time()),
        "bot_responsive": True,
        "storage_writable": False,
        "telethon_connected": False,
        "active_sessions": 0,
        "registered_groups": 0,
        "active_tests": 0
    }
    
    try:
        # Test storage write
        test_file = Path("data/health_check.tmp")
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text('{"test": true}')
        if test_file.exists():
            test_file.unlink()
            health["storage_writable"] = True
    except:
        pass
    
    try:
        # Check Telethon
        from telethon_service import get_telethon_service
        telethon = await get_telethon_service()
        health["telethon_connected"] = telethon and await telethon.is_connected()
    except:
        pass
    
    try:
        # Count active sessions
        from utils import load_group_ids, get_active_tests
        health["registered_groups"] = len(load_group_ids())
        health["active_tests"] = len(get_active_tests())
        
        if hasattr(storage, '_data'):
            health["active_sessions"] = len(storage._data)
    except:
        pass
    
    return health

@dp.message_handler(commands=['health'])
async def cmd_health(message: types.Message):
    """Bot health check command - ENHANCED"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    try:
        health = await bot_health_check()
        
        status_emoji = "🟢"
        if not health["storage_writable"] or not health["bot_responsive"]:
            status_emoji = "🔴"
        elif not health["telethon_connected"]:
            status_emoji = "🟡"
        
        health_report = f"{status_emoji} <b>Bot Health Report</b>\n\n"
        
        for key, value in health.items():
            if key == "timestamp":
                continue
                
            emoji = "✅" if value else "❌"
            if isinstance(value, bool):
                display_value = "Yes" if value else "No"
            else:
                display_value = str(value)
                emoji = "📊"
            
            clean_key = key.replace("_", " ").title()
            health_report += f"{emoji} {clean_key}: {display_value}\n"
        
        health_report += f"\n🕒 Check time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(health['timestamp']))}"
        
        await message.reply(health_report)
        
    except Exception as e:
        await message.reply(f"Health check failed: {e}")

@dp.message_handler(commands=['cleanup'])
async def cmd_cleanup(message: types.Message):
    """Manual cleanup command (owner only) - NEW"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    try:
        # Clean up old FSM states
        cleaned_states = 0
        if hasattr(storage, 'cleanup_old_sessions'):
            cleaned_states = await storage.cleanup_old_sessions(max_age_hours=24)
        
        # Clean up old session files
        session_dir = Path("data/sessions")
        total_cleaned_files = 0
        if session_dir.exists():
            for user_dir in session_dir.iterdir():
                if user_dir.is_dir() and user_dir.name.isdigit():
                    user_id = int(user_dir.name)
                    cleaned = await cleanup_old_user_sessions(user_id, max_age_hours=24)
                    total_cleaned_files += cleaned
        
        summary = f"🧹 Cleanup complete!\n\n"
        summary += f"🗑 FSM states cleaned: {cleaned_states}\n"
        summary += f"📁 Session files cleaned: {total_cleaned_files}"
        
        await message.reply(summary)
        
    except Exception as e:
        await message.reply(f"Cleanup error: {e}")

@dp.message_handler(commands=['help'])
async def cmd_help(message: types.Message):
    """Basic help command - ENHANCED"""
    if is_owner(message.from_user.id):
        help_text = (
            "<b>Owner Commands:</b>\n"
            "/start - Open admin panel\n"
            "/registergroup - Register current group\n"
            "/syncgroups - Sync all group members\n"
            "/debug - Show debug information\n"
            "/health - Bot health check\n"
            "/cleanup - Clean old sessions\n"
            "/joingroup - Force join current group\n"
            "/notify <test_id> - Manually notify about test\n"
            "/telethon - Check Telethon status\n"
            "/groupinfo <group_id> - Detailed group info\n"
            "/testaccess - Check your test access\n"
            "/userdebug <user_id> - Debug user access\n"
            "/mychatid - Get chat ID\n"
            "/help - This help message\n\n"
            "<b>Admin Features:</b>\n"
            "• Upload DOCX files to create tests\n"
            "• Manage groups and students\n"
            "• Activate/deactivate tests\n"
            "• Auto-notify students when tests activate\n"
            "• View statistics and backups"
        )
    else:
        help_text = (
            "<b>Student Commands:</b>\n"
            "/start - View available tests\n"
            "/testaccess - Check your test access\n"
            "/help - This help message\n\n"
            "<b>How to take a test:</b>\n"
            "1. Use /start to see available tests\n"
            "2. Click on a test button to select it\n"
            "3. Enter your full name\n"
            "4. Answer questions by clicking A/B/C/D\n"
            "5. View your results at the end"
        )
    
    await message.reply(help_text)

@dp.message_handler(commands=['testaccess'])
async def cmd_test_access(message: types.Message):
    """Debug command to check test access for current user"""
    try:
        from utils import available_tests_for_user, get_user_groups, load_group_members, get_active_tests, read_test
        
        user_id = message.from_user.id
        
        lines = [f"<b>Test Access Debug for User {user_id}:</b>", ""]
        
        # User's groups
        user_groups_json = get_user_groups(user_id)
        lines.append(f"👥 Groups from user_groups.json: {user_groups_json}")
        
        # Groups from membership data
        gm = load_group_members()
        groups_from_members = []
        for gid_str, rec in gm.items():
            try:
                gid = int(gid_str)
                members = set(int(x) for x in rec.get("members", []))
                if user_id in members:
                    groups_from_members.append(gid)
            except (ValueError, TypeError):
                continue
        lines.append(f"👥 Groups from group_members.json: {groups_from_members}")
        
        # Available tests
        available = available_tests_for_user(user_id)
        lines.append(f"🧪 Available tests: {len(available)}")
        
        # All active tests and their group assignments
        active_tests = get_active_tests()
        lines.append(f"", f"<b>All Active Tests:</b>")
        
        for test_id in active_tests:
            test_data = read_test(test_id)
            test_name = test_data.get("test_name", "Unknown")
            test_groups = test_data.get("groups", [])
            
            # Check if user can access this test
            user_groups_set = set(user_groups_json + groups_from_members)
            test_groups_set = set(int(g) for g in test_groups if str(g).isdigit())
            can_access = bool(user_groups_set.intersection(test_groups_set)) or not test_groups_set
            
            access_icon = "✅" if can_access else "❌"
            lines.append(f"{access_icon} {test_name}")
            lines.append(f"   Test groups: {test_groups}")
            lines.append(f"   Can access: {can_access}")
        
        await message.reply("\n".join(lines))
        
    except Exception as e:
        await message.reply(f"Debug error: {e}")

@dp.message_handler(commands=['userdebug'])
async def cmd_user_debug(message: types.Message):
    """Enhanced debug command for admins to check any user's access"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    args = message.get_args()
    if not args:
        return await message.reply("Usage: /userdebug <user_id>")
    
    try:
        target_user_id = int(args.strip())
        
        from utils import available_tests_for_user, get_user_groups, load_group_members
        
        lines = [f"<b>Debug Info for User {target_user_id}:</b>", ""]
        
        # User's groups
        user_groups_json = get_user_groups(target_user_id)
        lines.append(f"Groups from user_groups.json: {user_groups_json}")
        
        # Groups from membership
        gm = load_group_members()
        groups_from_members = []
        for gid_str, rec in gm.items():
            try:
                gid = int(gid_str)
                members = set(int(x) for x in rec.get("members", []))
                if target_user_id in members:
                    groups_from_members.append(gid)
            except (ValueError, TypeError):
                continue
        lines.append(f"Groups from group_members.json: {groups_from_members}")
        
        # Available tests
        available = available_tests_for_user(target_user_id)
        lines.append(f"Available tests: {len(available)}")
        for test in available:
            lines.append(f"  • {test.get('test_name')} (groups: {test.get('groups')})")
        
        await message.reply("\n".join(lines))
        
    except ValueError:
        await message.reply("Invalid user ID. Must be a number.")
    except Exception as e:
        await message.reply(f"Debug error: {e}")

# -------------------------
# Background tasks and cleanup - NEW FUNCTIONALITY
# -------------------------


async def validate_all_stored_users():
    """
    Validate all users in user_groups.json to ensure they're still in their groups.
    """
    try:
        from utils import validate_user_still_in_groups, read_json, Path, USER_GROUPS_FILE
        
        user_groups_data = read_json(Path(USER_GROUPS_FILE), {})
        invalid_users = []
        
        for user_id_str in list(user_groups_data.keys()):
            try:
                user_id = int(user_id_str)
                has_valid_groups, valid_groups = await validate_user_still_in_groups(user_id)
                
                if not has_valid_groups:
                    invalid_users.append(user_id)
                    log.info(f"User {user_id} has no valid groups, removing from data")
                
                # Small delay to avoid rate limits
                await asyncio.sleep(0.1)
                
            except Exception as e:
                log.error(f"Failed to validate user {user_id_str}: {e}")
        
        if invalid_users:
            log.info(f"Found and cleaned up {len(invalid_users)} users with no valid groups")
        
    except Exception as e:
        log.error(f"Error validating stored users: {e}")




# -------------------------
# Auto track bot's status in groups AND user interactions - PRESERVED
# -------------------------

@dp.my_chat_member_handler()
async def on_my_status(update: ChatMemberUpdated):
    """
    Automatically add/remove group ID to/from data/groups.txt when the bot is added/removed.
    """
    chat = update.chat
    if chat.type not in ("group", "supergroup"):
        return

    new_status = update.new_chat_member.status
    
    try:
        from utils import add_or_update_group, remove_group
        
        if new_status in ("member", "administrator"):
            title = chat.title or ""
            add_or_update_group(chat.id, title)
            log.info(f"Group auto-registered: {chat.id} - {title}")
            log_action(0, "group_auto_add", ok=True, group_id=chat.id)
            
        elif new_status in ("left", "kicked"):
            remove_group(chat.id)
            log.info(f"Group auto-removed: {chat.id}")
            log_action(0, "group_auto_remove", ok=True, group_id=chat.id)
            
    except Exception as e:
        log.error(f"Error handling membership update: {e}")


@dp.message_handler(commands=['validateusers'])
async def cmd_validate_users(message: types.Message):
    """Manually validate all users and clean up removed ones (owner only)"""
    if not is_owner(message.from_user.id):
        return await message.reply("Owner only.")
    
    try:
        await message.reply("⏳ Validating all users, this may take a while...")
        
        groups = load_group_ids()
        total_removed = []
        
        for group_id in groups:
            from utils import detect_and_remove_kicked_users
            removed = await detect_and_remove_kicked_users(group_id)
            if removed:
                total_removed.extend(removed)
            await asyncio.sleep(1)  # Rate limiting
        
        # Also validate all stored users
        await validate_all_stored_users()
        
        unique_removed = set(total_removed)
        
        if unique_removed:
            await message.reply(
                f"✅ Validation complete!\n\n"
                f"🗑 Removed {len(unique_removed)} users who are no longer in groups:\n"
                f"{', '.join(str(uid) for uid in list(unique_removed)[:10])}"
                f"{' ...' if len(unique_removed) > 10 else ''}"
            )
        else:
            await message.reply("✅ Validation complete! All users are valid.")
        
    except Exception as e:
        await message.reply(f"❌ Validation failed: {e}")

@dp.chat_member_handler()
async def on_member_update(update: ChatMemberUpdated):
    """Enhanced handler for member updates including proper removal handling"""
    chat = update.chat
    if chat.type not in ("group", "supergroup"):
        return
    
    # Check if this group is registered
    from utils import load_group_ids
    registered_groups = load_group_ids()
    if chat.id not in registered_groups:
        return
    
    user = update.new_chat_member.user
    old_status = update.old_chat_member.status if update.old_chat_member else None
    new_status = update.new_chat_member.status
    
    log.info(f"Member update in group {chat.id}: User {user.id} ({user.first_name}) status change: {old_status} -> {new_status}")
    
    # Handle user joining
    if old_status in [None, "left", "kicked"] and new_status in ["member", "administrator", "creator"]:
        # User joined the group!
        log.info(f"User {user.id} ({user.first_name}) joined group {chat.id}")
        
        # Add to members immediately
        from utils import add_user_to_group
        add_user_to_group(user.id, chat.id)
        
        # Trigger background sync with owner account to get full info
        asyncio.create_task(sync_single_user_background(chat.id, user.id))
        
        # Check if there are active tests for this group
        from utils import tests_for_group
        active_tests = tests_for_group(chat.id, only_active=True)
        
        if active_tests:
            # Notify new member about available tests
            try:
                bot_info = await bot.get_me()
                welcome_msg = (
                    f"👋 Xush kelibsiz, {user.first_name}!\n\n"
                    f"📚 Bu guruh uchun faol testlar mavjud.\n"
                    f"Testni boshlash uchun @{bot_info.username} ga o'ting va /start bosing."
                )
                await bot.send_message(chat.id, welcome_msg)
            except Exception as e:
                log.error(f"Failed to send welcome message: {e}")
    
    # Handle user becoming admin
    elif new_status in ["administrator", "creator"] and old_status not in ["administrator", "creator"]:
        log.info(f"User {user.id} became admin in group {chat.id}")
        # Sync admins for this group
        from utils import sync_group_admins
        asyncio.create_task(sync_group_admins(chat.id))
    
    # Handle user losing admin privileges but staying in group
    elif old_status in ["administrator", "creator"] and new_status == "member":
        log.info(f"User {user.id} lost admin privileges in group {chat.id}")
        # Remove admin privileges for this group only
        from utils import remove_user_admin_privileges
        remove_user_admin_privileges(user.id, chat.id)
    
    # Handle user leaving or being kicked/banned
    elif new_status in ["left", "kicked", "banned"] and old_status in ["member", "administrator", "creator"]:
        log.info(f"User {user.id} left/was removed from group {chat.id} (status: {new_status})")
        
        # Completely remove user from all group-related data
        from utils import remove_user_from_group_completely
        remove_user_from_group_completely(user.id, chat.id)
        
        # Log the removal for security audit
        if old_status in ["administrator", "creator"]:
            log.warning(f"SECURITY: Admin user {user.id} ({user.first_name}) was removed from group {chat.id}, admin privileges revoked")


async def sync_single_user_background(group_id: int, user_id: int):
    """Sync single user's data using owner account"""
    try:
        await asyncio.sleep(2)  # Small delay to avoid rate limits
        
        user_telethon = await get_user_telethon_service()
        
        if user_telethon and user_telethon.client:
            # Get user info using owner account
            try:
                user_entity = await user_telethon.client.get_entity(user_id)
                
                # Update member_data
                from utils import load_group_members, write_json, Path, GROUP_MEMBERS_FILE
                gm = load_group_members()
                
                if str(group_id) in gm:
                    if "member_data" not in gm[str(group_id)]:
                        gm[str(group_id)]["member_data"] = {}
                    
                    gm[str(group_id)]["member_data"][str(user_id)] = {
                        "first_name": user_entity.first_name or "",
                        "last_name": user_entity.last_name or "",
                        "username": user_entity.username or "",
                        "phone": user_entity.phone or "",
                        "is_premium": getattr(user_entity, 'premium', False),
                        "is_bot": user_entity.bot,
                        "is_admin": False
                    }
                    
                    write_json(Path(GROUP_MEMBERS_FILE), gm)
                    log.info(f"Updated member data for user {user_id} in group {group_id}")
                    
            except Exception as e:
                log.error(f"Failed to get user info for {user_id}: {e}")
    except Exception as e:
        log.error(f"Background user sync failed: {e}")




# -------------------------
# Fallback callback handler (MUST BE LAST) - PRESERVED
# -------------------------

@dp.callback_query_handler(lambda c: True)
async def cb_fallback(cb: types.CallbackQuery, state: FSMContext):
    """Fallback for unhandled callbacks - MUST BE LAST HANDLER"""
    current_state = await state.get_state()
    log.warning(f"Unhandled callback: data='{cb.data}', state='{current_state}', user={cb.from_user.id}")
    
    # Provide helpful feedback based on callback type
    if cb.data and cb.data.startswith("ans:") and current_state != StudentStates.Answering.state:
        await cb.answer("Avval testni boshlang. /start buyrug'ini yuboring.", show_alert=True)
    elif cb.data and cb.data.startswith("select_test:") and current_state != StudentStates.Choosing.state:
        await cb.answer("Testni tanlash uchun /start buyrug'ini yuboring.", show_alert=True)
    else:
        await cb.answer("Bu tugma hozircha ishlamaydi. /start ni bosing.", show_alert=True)

# -------------------------
# Error handling - PRESERVED
# -------------------------

@dp.errors_handler()
async def error_handler(update: types.Update, exception: Exception):
    """Global error handler"""
    log.error(f"Update {update} caused error: {exception}", exc_info=True)
    
    # Try to notify user if possible
    if update.message:
        try:
            await update.message.reply("Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring yoki /start buyrug'ini yuboring.")
        except Exception:
            pass
    elif update.callback_query:
        try:
            await update.callback_query.answer("Xatolik yuz berdi. Qaytadan urinib ko'ring.")
        except Exception:
            pass
    
    return True  # Mark as handled

# -------------------------
# Startup & shutdown - ENHANCED WITH BACKGROUND TASKS
# -------------------------

async def on_startup(dp: Dispatcher):
    """Minimal startup without automatic syncing"""
    try:
        ensure_data()
        
        asyncio.create_task(_heartbeat_watchdog())
        log.info("Watchdog started")
        owner_telethon = await get_user_telethon_service()
        
        if owner_telethon:
            log.info("✅ Owner Telethon initialized")
        else:
            log.warning("⚠️ Owner Telethon not available")
        
        log.info("Bot started successfully")
        
    except Exception as e:
        log.error(f"Startup failed: {e}")
        log.warning(f"Watchdog not started: {e}")
        raise

async def on_shutdown(dp: Dispatcher):
    """Bot shutdown cleanup - PRESERVED"""
    try:
        log.info("Bot shutting down...")
        
        # Stop Telethon service
        try:
            from telethon_service import stop_telethon_service
            await stop_telethon_service()
            log.info("Telethon service stopped")
        except Exception as e:
            log.warning(f"Error stopping Telethon: {e}")
        
        log_action(OWNER_ID, "bot_stop", ok=True)
        
        # Close storage
        if hasattr(dp.storage, 'close'):
            await dp.storage.close()
            
        if hasattr(dp.bot, 'session'):
            await dp.bot.session.close()
        
    except Exception as e:
        log.error(f"Shutdown error: {e}")





async def _heartbeat_watchdog():
    """
    Enhanced connection monitor that tracks users with active sessions
    and notifies them when connection is restored.
    """
    global _CONNECTION_STATUS, _users_to_notify
    
    from config import bot, OWNER_ID
    interval = 30  # Check every 30 seconds

    while True:
        try:
            # Test bot connection
            await bot.get_me()
            
            # If we just came back online
            if not _CONNECTION_STATUS["online"]:
                _CONNECTION_STATUS["online"] = True
                log.info("Bot connection restored")
                
                # Notify owner
                try:
                    await bot.send_message(
                        OWNER_ID, 
                        "🔄 Bot is back online. Students with active sessions have been notified."
                    )
                except Exception:
                    pass
                
                # Notify affected users
                await notify_users_on_reconnect()
                
            else:
                # Still online, nothing to do
                _CONNECTION_STATUS["online"] = True

        except Exception as e:
            # Connection failed
            if _CONNECTION_STATUS["online"]:
                # First time we detect offline status
                _CONNECTION_STATUS["online"] = False
                log.warning(f"Bot connection lost: {e}")
                
                # Capture users with active sessions
                try:
                    active_users = get_users_with_active_sessions()
                    _users_to_notify.update(active_users)
                    log.info(f"Captured {len(active_users)} users with active sessions for reconnect notification")
                except Exception as capture_error:
                    log.error(f"Failed to capture active users: {capture_error}")
            
            # If we're still offline, log periodically
            if not _CONNECTION_STATUS["online"]:
                log.warning(f"Bot still offline: {e}")

        await asyncio.sleep(interval)

async def notify_users_on_reconnect():
    """
    Notify users who had active sessions during disconnection - IN UZBEK
    """
    global _users_to_notify
    
    if not _users_to_notify:
        return
    
    notify_list = list(_users_to_notify)
    _users_to_notify.clear()
    
    # UZBEK NOTIFICATION MESSAGE
    message = (
        "🔄 Bot yana ishlamoqda!\n\n"
        "Agar test yechayotgan bo'lsangiz, qolgan joyingizdan davom etishingiz mumkin.\n"
        "Test davom ettirish uchun /start yuboring."
    )
    
    notified_count = 0
    
    for user_id in notify_list:
        try:
            await bot.send_message(user_id, message)
            notified_count += 1
            await asyncio.sleep(0.1)  # Rate limiting
        except Exception as e:
            log.debug(f"Failed to notify user {user_id} about reconnection: {e}")
    
    log.info(f"Notified {notified_count}/{len(notify_list)} users about reconnection")




if __name__ == "__main__":
    backoff = 5  
    while True:
        try:
            executor.start_polling(
                dp,
                skip_updates=True,
                on_startup=on_startup,
                on_shutdown=on_shutdown,
                allowed_updates=ALLOWED_UPDATES,
            )
            break  # clean exit (e.g., KeyboardInterrupt)
        except KeyboardInterrupt:
            log.info("Bot stopped by user")
            break
        except Exception as e:
            # Exponential backoff with jitter, capped to 5 minutes
            wait = min(backoff, 300) + random.uniform(0, 3)
            log.error(f"Bot crashed: {e}. Restarting in {int(wait)}s ...", exc_info=True)
            time.sleep(wait)
            backoff = min(backoff * 2, 300)
            continue
