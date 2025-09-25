import os
import time
import shutil
import asyncio
import logging
from pathlib import Path
from aiogram import types
from aiogram.dispatcher import FSMContext
from typing import List
import uuid

from states import AdminStates
from audit import log_action
from utils import (
    is_owner, ensure_data,
    load_group_ids, load_group_members,
    load_tests_index, save_tests_index,
    add_test_index, save_test_content, parse_docx_bytes,
    set_test_active, assign_test_groups, test_path,
    read_test,
    # ADD THESE NEW IMPORTS:
    get_user_admin_groups, can_user_create_test, 
    can_user_manage_test, is_admin, is_group_admin,
    load_group_titles,
    parse_docx_bytes, add_test_index, save_test_content, assign_test_groups, set_test_active, notify_groups_and_members,
    write_test,
    get_bot_admin_groups
)
from aiogram.utils.exceptions import MessageNotModified

# Add logging
log = logging.getLogger("admin_handlers")

# Import with fallback
try:
    from config import bot, OWNER_ID
except ImportError:
    # Fallback if config.py missing
    import os
    from aiogram import Bot
    bot = Bot(token=os.getenv("BOT_TOKEN", ""))
    OWNER_ID = int(os.getenv("OWNER_ID", "0")) or None

GROUPS_FILE = Path("data/groups.txt")

# Thread lock for file operations
_file_lock = asyncio.Lock()

# ---------- Owner panel ----------

async def owner_panel(message: types.Message):
    if not is_owner(message.from_user.id):
        return
    ensure_data()
    
    from keyboards import owner_home_kb
    await message.answer("Owner panel", reply_markup=owner_home_kb())

async def cb_panel_home(cb: types.CallbackQuery):
    if not is_owner(cb.from_user.id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    
    from keyboards import owner_home_kb
    try:
        await cb.message.edit_text("Owner panel", reply_markup=owner_home_kb())
        await cb.answer()
    except MessageNotModified:
        await cb.answer()

async def safe_edit(message: types.Message, text: str, kb: types.InlineKeyboardMarkup):
    try:
        await message.edit_text(text, reply_markup=kb)
    except MessageNotModified:
        # Nothing changed; ignore instead of crashing
        pass

async def admin_panel(message: types.Message, admin_groups: List[int] = None):
    """Panel for group admins (teachers)"""
    if not admin_groups:
        admin_groups = get_user_admin_groups(message.from_user.id)
    
    if not admin_groups:
        return await message.answer("Siz hech qanday guruh admini emassiz.")
    
    # Create keyboard with limited options
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📚 Mening Testlarim", callback_data="admin:tests"),
        types.InlineKeyboardButton("👥 Mening Guruhlarim", callback_data="admin:groups"),
    )
    kb.add(
        types.InlineKeyboardButton("➕ Yangi Test", callback_data="admin:new_test"),
        types.InlineKeyboardButton("📊 Statistika", callback_data="admin:stats"),
    )
    
    group_titles = load_group_titles()
    group_names = [group_titles.get(gid, f"Guruh {gid}") for gid in admin_groups]
    
    text = (
        f"👨‍🏫 <b>O'qituvchi paneli</b>\n\n"
        f"Sizning guruhlaringiz:\n"
        + "\n".join([f"• {name}" for name in group_names])
    )
    
    await message.answer(text, reply_markup=kb)

# ---------- Admins (read-only) ----------

async def cb_admin_action(cb: types.CallbackQuery, state: FSMContext):
    """Handle admin panel callbacks"""
    user_id = cb.from_user.id
    
    if not is_admin(user_id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    
    data = cb.data or ""
    
    # Admin home
    if data == "admin:home":
        admin_groups = get_user_admin_groups(user_id)
        await admin_panel(cb.message, admin_groups)
        await cb.answer()
        return
    
    # Admin tests
    if data == "admin:tests":
        return await cb_panel_tests(cb)
    
    # Admin groups
    if data == "admin:groups":
        admin_groups = get_user_admin_groups(user_id)
        group_titles = load_group_titles()
        
        lines = ["<b>Sizning guruhlaringiz:</b>\n"]
        for gid in admin_groups:
            title = group_titles.get(gid, f"Guruh {gid}")
            
            # Get member count
            gm = load_group_members()
            members = gm.get(str(gid), {}).get("members", [])
            
            lines.append(f"• {title}")
            lines.append(f"  ID: <code>{gid}</code>")
            lines.append(f"  A'zolar: {len(members)} ta\n")
        
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="admin:home"))
        
        await cb.message.edit_text("\n".join(lines), reply_markup=kb)
        await cb.answer()
        return
    
    # Admin new test
    if data == "admin:new_test":
        await cb.message.answer("DOCX formatida test faylini yuboring.\n\nFayl tuzilishi:\n• Savollar\n• Javoblar\n• Izohlar (ixtiyoriy)")
        await cb.answer()
        return
    
    # Admin stats
    if data == "admin:stats":
        admin_groups = get_user_admin_groups(user_id)
        
        # Count students in admin's groups
        total_students = set()
        gm = load_group_members()
        for gid in admin_groups:
            members = gm.get(str(gid), {}).get("members", [])
            total_students.update(members)
        
        # Count active tests
        idx = load_tests_index().get("tests", {})
        admin_tests = 0
        active_tests = 0
        
        for tid, rec in idx.items():
            test_groups = [int(g) for g in rec.get("groups", []) if str(g).isdigit()]
            if any(g in admin_groups for g in test_groups):
                admin_tests += 1
                if rec.get("active"):
                    active_tests += 1
        
        stats_text = (
            f"📊 <b>Statistika</b>\n\n"
            f"👥 Guruhlar: {len(admin_groups)} ta\n"
            f"🎓 Talabalar: {len(total_students)} ta\n"
            f"📚 Testlar: {admin_tests} ta\n"
            f"✅ Faol testlar: {active_tests} ta"
        )
        
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="admin:home"))
        
        await cb.message.edit_text(stats_text, reply_markup=kb)
        await cb.answer()
        return
    
    # Handle test view/actions for admins (admin_t:*)
    if data.startswith("admin_t:"):
        # Convert to regular test callback and handle
        new_data = data.replace("admin_t:", "t:")
        cb.data = new_data
        return await cb_test_action(cb, state)
    
    await cb.answer("Noma'lum buyruq")

async def cb_panel_admins(cb: types.CallbackQuery):
    if not is_owner(cb.from_user.id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    
    from utils import load_admins
    from keyboards import back_kb
    
    data = load_admins()
    owner = data.get("owner_id") or OWNER_ID

    lines = [f"<b>Owner:</b> <code>{owner}</code>", "", "<b>Panel Admins:</b>"]
    if not data.get("admins"):
        lines.append("— none —")
    else:
        for uid, rec in data["admins"].items():
            scope = "global" if rec.get("global") else (", ".join(rec.get("groups", [])) or "—")
            lines.append(f"• <code>{uid}</code> — {scope}")

    try:
        await cb.message.edit_text("\n".join(lines), reply_markup=back_kb())
        await cb.answer()
    except MessageNotModified:
        await cb.answer()

# ---------- Groups (with Add/Remove) ----------

def _groups_manage_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔄 Yangilash", callback_data="g:sync"),
        types.InlineKeyboardButton("➕ Guruh qo'shish", callback_data="g:add"),
    )
    kb.add(types.InlineKeyboardButton("➖ Guruhni o'chirish", callback_data="g:remove"))
    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="panel:home"))
    return kb

async def cb_panel_groups(cb: types.CallbackQuery):
    if not is_owner(cb.from_user.id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    
    gids = load_group_ids()
    titles = load_group_titles()
    
    lines = ["<b>Groups:</b>\n"]
    if gids:
        for gid in gids:
            title = titles.get(gid, "No name")
            lines.append(f"• {title}")
            lines.append(f"  ID: <code>{gid}</code>")
    else:
        lines.append("— none —")
    
    text = "\n".join(lines)
    
    try:
        await cb.message.edit_text(text, reply_markup=_groups_manage_kb())
        await cb.answer()
    except MessageNotModified:
        await cb.answer()

async def _groups_write_all(ids):
    async with _file_lock:
        GROUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # normalize and dedupe
        norm = sorted(set(str(i) for i in ids))
        GROUPS_FILE.write_text("\n".join(norm), encoding="utf-8")

async def _groups_append(ids):
    async with _file_lock:
        existing = set()
        if GROUPS_FILE.exists():
            try:
                existing = set(map(str.strip, GROUPS_FILE.read_text(encoding="utf-8").splitlines()))
            except Exception:
                pass
        for i in ids:
            existing.add(str(i))
        await _groups_write_all(existing)

async def _groups_remove(ids):
    async with _file_lock:
        existing = set()
        if GROUPS_FILE.exists():
            try:
                existing = set(map(str.strip, GROUPS_FILE.read_text(encoding="utf-8").splitlines()))
            except Exception:
                pass
        for i in ids:
            existing.discard(str(i))
        await _groups_write_all(existing)

# ---------- Students (approx count) ----------

async def cb_panel_students(cb: types.CallbackQuery):
    """Show students by group - first show groups, then students in selected group"""
    if not is_owner(cb.from_user.id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    
    from keyboards import back_kb
    
    groups = load_group_ids()
    group_titles = load_group_titles()
    
    if not groups:
        try:
            await cb.message.edit_text("Guruhlar ro'yxatdan o'tmagan.", reply_markup=back_kb())
            await cb.answer()
        except MessageNotModified:
            await cb.answer()
        return
    
    # Show groups as clickable buttons
    kb = types.InlineKeyboardMarkup(row_width=1)
    
    for gid in groups:
        title = group_titles.get(gid, f"Guruh {gid}")
        
        # Get member count
        gm = load_group_members()
        members = gm.get(str(gid), {}).get("members", [])
        
        kb.add(types.InlineKeyboardButton(
            f"👥 {title} ({len(members)} a'zo)",
            callback_data=f"show_group_students:{gid}"
        ))
    
    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="panel:home"))
    
    try:
        await cb.message.edit_text(
            "<b>👥 Guruhlar ro'yxati:</b>\n\nGuruh a'zolarini ko'rish uchun guruhni tanlang:",
            reply_markup=kb
        )
        await cb.answer()
    except MessageNotModified:
        await cb.answer()

# ADD new function for showing students in specific group:
async def cb_show_group_students(cb: types.CallbackQuery):
    """Show students in a specific group"""
    if not is_owner(cb.from_user.id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    
    data = cb.data or ""
    if not data.startswith("show_group_students:"):
        return await cb.answer("Noto'g'ri format")
    
    try:
        group_id = int(data.replace("show_group_students:", ""))
    except ValueError:
        return await cb.answer("Noto'g'ri guruh ID")
    
    group_titles = load_group_titles()
    group_title = group_titles.get(group_id, f"Guruh {group_id}")
    
    gm = load_group_members()
    group_data = gm.get(str(group_id), {})
    members = group_data.get("members", [])
    member_data = group_data.get("member_data", {})
    
    if not members:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ Guruhlar ro'yxatiga", callback_data="panel:students"))
        
        try:
            await cb.message.edit_text(
                f"<b>👥 {group_title}</b>\n\nBu guruhda hech kim yo'q.",
                reply_markup=kb
            )
            await cb.answer()
        except MessageNotModified:
            await cb.answer()
        return
    
    lines = [f"<b>👥 {group_title}</b>", f"Jami: {len(members)} a'zo", ""]
    
    for i, user_id in enumerate(members[:20], 1):  # Show first 20
        user_info = member_data.get(str(user_id), {})
        name = f"{user_info.get('first_name', '')} {user_info.get('last_name', '')}".strip()
        if not name:
            name = "Noma'lum"
        
        username = user_info.get('username', '')
        username_str = f"@{username}" if username else "username yo'q"
        
        lines.append(f"{i}. {name} ({username_str})")
        lines.append(f"   ID: <code>{user_id}</code>")
        
        # Show additional info if available
        if user_info.get('phone'):
            lines.append(f"   📱 {user_info['phone']}")
        
        lines.append("")  # Empty line between students
    
    if len(members) > 20:
        lines.append(f"... va yana {len(members) - 20} a'zo")
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔄 Sinxronlash", callback_data=f"sync_group:{group_id}"))
    kb.add(types.InlineKeyboardButton("⬅️ Guruhlar ro'yxatiga", callback_data="panel:students"))
    
    text = "\n".join(lines)
    
    try:
        await cb.message.edit_text(text, reply_markup=kb)
        await cb.answer()
    except MessageNotModified:
        await cb.answer()

# ADD sync single group handler:
async def cb_sync_single_group(cb: types.CallbackQuery):
    """Sync a single group"""
    if not is_owner(cb.from_user.id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    
    data = cb.data or ""
    if not data.startswith("sync_group:"):
        return await cb.answer("Noto'g'ri format")
    
    try:
        group_id = int(data.replace("sync_group:", ""))
    except ValueError:
        return await cb.answer("Noto'g'ri guruh ID")
    
    await cb.answer("Sinxronlanmoqda...", show_alert=False)
    
    from utils import sync_group_members
    count = await sync_group_members(group_id)
    
    await cb.answer(f"✅ {count} a'zo sinxronlandi!", show_alert=True)
    
    # Refresh the display
    await cb_show_group_students(cb)

# ---------- Tests: list → select → manage (single-message UI) ----------

def _tests_list_kb():
    idx = load_tests_index().get("tests", {})
    kb = types.InlineKeyboardMarkup(row_width=1)
    if not idx:
        kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="panel:home"))
        return kb
    for tid, rec in idx.items():
        name = rec.get("name", "-")
        status = "🟢" if rec.get("active") else "🔴"
        kb.add(types.InlineKeyboardButton(f"{status} {name}", callback_data=f"t:view:{tid}"))
    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="panel:home"))
    return kb

def _test_actions_kb(tid: str, active: bool, is_admin_view: bool) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    if active:
        kb.add(types.InlineKeyboardButton("🔴 Faolsizlantirish", callback_data=f"t:deact:{tid}"))
    else:
        kb.add(types.InlineKeyboardButton("🟢 Faollashtirish", callback_data=f"t:act:{tid}"))
    kb.add(types.InlineKeyboardButton("📌 Guruhlarga tayinlash", callback_data=f"t:assign:{tid}"))
    kb.add(types.InlineKeyboardButton("🗑 O‘chirish", callback_data=f"t:del:{tid}"))

    back_to = "admin:tests" if is_admin_view else "panel:tests"
    kb.add(types.InlineKeyboardButton("⬅️ Ro‘yxatga", callback_data=back_to))
    return kb


async def cb_panel_tests(cb: types.CallbackQuery):
    """Show tests - filtered for admins"""
    user_id = cb.from_user.id
    
    # Check if this is from admin panel or owner panel
    is_admin_view = cb.data == "admin:tests"
    
    if not is_owner(user_id) and not is_admin(user_id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    
    from keyboards import back_kb
    
    # Get all tests
    idx = load_tests_index().get("tests", {})
    
    # Filter for admins
    if not is_owner(user_id) or is_admin_view:
        admin_groups = get_user_admin_groups(user_id)
        filtered_idx = {}
        
        for tid, rec in idx.items():
            # Check if test belongs to admin's groups
            test_groups = []
            for g in rec.get("groups", []):
                try:
                    test_groups.append(int(g))
                except:
                    pass
            
            # Also check test creator
            test_data = read_test(tid)
            created_by = test_data.get('created_by')
            
            # Include test if: created by this user OR assigned to their groups
            if created_by == user_id or any(g in admin_groups for g in test_groups):
                filtered_idx[tid] = rec
        
        idx = filtered_idx
    
    if not idx:
        back_to = "admin:home" if is_admin_view else "panel:home"
        try:
            await cb.message.edit_text(
                "Sizda testlar yo'q. DOCX fayl yuboring.", 
                reply_markup=back_kb(back_to)
            )
            await cb.answer()
        except MessageNotModified:
            await cb.answer()
    else:
        # Create test list keyboard
        kb = types.InlineKeyboardMarkup(row_width=1)
        for tid, rec in idx.items():
            name = rec.get("name", "-")
            status = "🟢" if rec.get("active") else "🔴"
            callback = f"admin_t:view:{tid}" if is_admin_view else f"t:view:{tid}"
            kb.add(types.InlineKeyboardButton(f"{status} {name}", callback_data=callback))
        
        back_to = "admin:home" if is_admin_view else "panel:home"
        kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data=back_to))
        
        try:
            await cb.message.edit_text("<b>Sizning testlaringiz</b> — birini tanlang:", reply_markup=kb)
            await cb.answer()
        except MessageNotModified:
            await cb.answer()

async def _open_test(cb: types.CallbackQuery, tid: str):
    idx = load_tests_index().get("tests", {})
    rec = idx.get(tid)
    if not rec:
        return await cb.answer("Test topilmadi")

    name = rec.get("name", "-")
    active = bool(rec.get("active"))
    # Show group names here if you like (see Fix 3)
    is_admin_view = (cb.data or "").startswith("admin_t:")

    text = f"<b>{name}</b>\n<code>{tid}</code>\n\n<b>Status:</b> {'🟢 FAOL' if active else '🔴 NOFAOL'}"
    try:
        await cb.message.edit_text(text, reply_markup=_test_actions_kb(tid, active, is_admin_view))
    except MessageNotModified:
        pass


# ---------- Create test via DOCX ----------

# IN admin_handlers.py, REPLACE owner_receive_docx function:

async def owner_receive_docx(message: types.Message, state: FSMContext):
    """Handle DOCX with group selection based on bot admin status"""
    if not can_user_create_test(message.from_user.id):
        return await message.reply("Sizda test yaratish huquqi yo'q.")
    
    if not message.document or not message.document.file_name.lower().endswith(".docx"):
        await message.reply("Iltimos .docx formatida test faylini yuboring.")
        return

    try:
        # Download and parse the file
        file = await bot.get_file(message.document.file_id)
        data = await bot.download_file(file.file_path)
        
        original_filename = message.document.file_name
        test_name = original_filename.replace('.docx', '').replace('.DOCX', '')
        
        _, content = parse_docx_bytes(data.read())
        content['test_name'] = test_name
        
    except Exception as e:
        await message.reply(f"Faylni o'qishda xatolik: {e}")
        return

    # Create test
    tid = str(uuid.uuid4())
    add_test_index(tid, test_name)
    save_test_content(tid, content)
    
    # Store creator info
    test_data = read_test(tid)
    test_data['created_by'] = message.from_user.id
    test_data['creator_name'] = message.from_user.full_name
    write_test(tid, test_data)
    
    await state.update_data(new_test_id=tid, new_test_name=test_name)
    
    # Get groups where BOT is admin (not where owner is admin)
    available_groups = await get_bot_admin_groups(message.from_user.id)
    
    if not available_groups:
        await message.reply(
            f"✅ Test yaratildi: <b>{test_name}</b>\n\n"
            f"⚠️ Lekin bot hech qanday guruhda admin emas!\n"
            f"Botni guruhga admin qilib qo'shing va qayta urinib ko'ring."
        )
        return
    
    # Get group titles
    items = []
    group_titles = load_group_titles()
    for gid in available_groups:
        title = group_titles.get(gid, f"Guruh {gid}")
        items.append((gid, title))
    
    # Create selection keyboard
    kb = types.InlineKeyboardMarkup(row_width=1)
    
    for gid, title in items:
        display_title = title[:30] + "..." if len(title) > 30 else title
        kb.add(types.InlineKeyboardButton(
            f"☐ {display_title}",
            callback_data=f"new_t:pick:{tid}:{gid}"
        ))
    
    kb.row(
        types.InlineKeyboardButton("✅ Hammasini", callback_data=f"new_t:all:{tid}"),
        types.InlineKeyboardButton("❌ Tozalash", callback_data=f"new_t:clear:{tid}")
    )
    kb.add(
        types.InlineKeyboardButton("🚀 TAYYOR - Faollashtirish", callback_data=f"new_t:activate:{tid}")
    )
    
    await state.update_data(new_test_sel=[])
    
    await message.reply(
        f"✅ Test yaratildi: <b>{test_name}</b>\n\n"
        f"📌 Qaysi guruhlarga tayinlansin?\n"
        f"Tanlang va TAYYOR tugmasini bosing:",
        reply_markup=kb
    )

# ADD this new callback handler:
async def cb_new_test_action(cb: types.CallbackQuery, state: FSMContext):
    """Handle new test group selection and activation"""
    if not can_user_create_test(cb.from_user.id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    
    data = cb.data or ""
    parts = data.split(":")
    
    if len(parts) < 3:
        return await cb.answer("Noto'g'ri format")
    
    action = parts[1]
    tid = parts[2]
    
    s = await state.get_data()
    selected = set(s.get("new_test_sel", []))
    
    # Get available groups
    available_groups = await get_bot_admin_groups(cb.from_user.id)
    
    items = []
    group_titles = load_group_titles()
    for gid in available_groups:
        title = group_titles.get(gid, f"Guruh {gid}")
        items.append((gid, title))
    
    if action == "pick":
        # Toggle group selection
        gid = int(parts[3])
        
        if gid in selected:
            selected.remove(gid)
        else:
            selected.add(gid)
        
        await state.update_data(new_test_sel=list(selected))
        
        # Update keyboard
        kb = types.InlineKeyboardMarkup(row_width=1)
        for g, title in items:
            mark = "☑" if g in selected else "☐"
            display = f"{title[:30]}..." if len(title) > 30 else title
            kb.add(types.InlineKeyboardButton(
                f"{mark} {display}",
                callback_data=f"new_t:pick:{tid}:{g}"
            ))
        
        kb.row(
            types.InlineKeyboardButton("✅ Hammasini", callback_data=f"new_t:all:{tid}"),
            types.InlineKeyboardButton("❌ Tozalash", callback_data=f"new_t:clear:{tid}")
        )
        kb.add(
            types.InlineKeyboardButton("🚀 TAYYOR - Faollashtirish", callback_data=f"new_t:activate:{tid}")
        )
        
        test_name = s.get("new_test_name", "Test")
        await cb.message.edit_text(
            f"✅ Test yaratildi: <b>{test_name}</b>\n\n"
            f"📌 Tanlangan guruhlar: {len(selected)} ta\n"
            f"TAYYOR tugmasini bosing:",
            reply_markup=kb
        )
        await cb.answer()
        
    elif action == "all":
        # Select all groups
        selected = set(g for g, _ in items)
        await state.update_data(new_test_sel=list(selected))
        
        kb = types.InlineKeyboardMarkup(row_width=1)
        for g, title in items:
            display = f"{title[:30]}..." if len(title) > 30 else title
            kb.add(types.InlineKeyboardButton(
                f"☑ {display}",
                callback_data=f"new_t:pick:{tid}:{g}"
            ))
        
        kb.row(
            types.InlineKeyboardButton("✅ Hammasini", callback_data=f"new_t:all:{tid}"),
            types.InlineKeyboardButton("❌ Tozalash", callback_data=f"new_t:clear:{tid}")
        )
        kb.add(
            types.InlineKeyboardButton("🚀 TAYYOR - Faollashtirish", callback_data=f"new_t:activate:{tid}")
        )
        
        test_name = s.get("new_test_name", "Test")
        await cb.message.edit_text(
            f"✅ Test yaratildi: <b>{test_name}</b>\n\n"
            f"📌 Barcha guruhlar tanlandi: {len(selected)} ta\n"
            f"TAYYOR tugmasini bosing:",
            reply_markup=kb
        )
        await cb.answer("Barcha guruhlar tanlandi")
        
    elif action == "clear":
        # Clear selection
        await state.update_data(new_test_sel=[])
        
        kb = types.InlineKeyboardMarkup(row_width=1)
        for g, title in items:
            display = f"{title[:30]}..." if len(title) > 30 else title
            kb.add(types.InlineKeyboardButton(
                f"☐ {display}",
                callback_data=f"new_t:pick:{tid}:{g}"
            ))
        
        kb.row(
            types.InlineKeyboardButton("✅ Hammasini", callback_data=f"new_t:all:{tid}"),
            types.InlineKeyboardButton("❌ Tozalash", callback_data=f"new_t:clear:{tid}")
        )
        kb.add(
            types.InlineKeyboardButton("🚀 TAYYOR - Faollashtirish", callback_data=f"new_t:activate:{tid}")
        )
        
        test_name = s.get("new_test_name", "Test")
        await cb.message.edit_text(
            f"✅ Test yaratildi: <b>{test_name}</b>\n\n"
            f"📌 Guruhlarni tanlang va TAYYOR tugmasini bosing:",
            reply_markup=kb
        )
        await cb.answer("Tanlov tozalandi")
        
    elif action == "activate":
        # Activate test for selected groups
        if not selected:
            return await cb.answer("Kamida bitta guruh tanlang!", show_alert=True)
        
        # Assign to groups
        assign_test_groups(tid, list(selected))
        
        # Activate test
        set_test_active(tid, True)
        
        test_name = s.get("new_test_name", "Test")
        
        # Start notification process
        await cb.message.answer(f"⏳ Test faollashtirilmoqda va xabarlar yuborilmoqda...")
        
        # Notify each group and its members
        notification_results = await notify_groups_and_members(list(selected), test_name, tid)
        
        # Clear state
        await state.finish()
        
        # Show results
        total_groups = len(selected)
        total_notified = notification_results['total_notified']
        total_failed = notification_results['total_failed']
        groups_notified = notification_results['groups_notified']
        
        result_message = (
            f"✅ <b>Test faollashtirildi!</b>\n\n"
            f"📚 Test: {test_name}\n"
            f"👥 Guruhlar: {total_groups} ta\n"
            f"📢 Guruhlarga xabar: {groups_notified}/{total_groups} ta\n"
            f"📨 Shaxsiy xabar yuborildi: {total_notified} talaba\n"
        )
        
        if total_failed > 0:
            result_message += f"⚠️ Xabar yetmadi: {total_failed} talaba\n"
        
        await cb.message.answer(result_message)
        await cb.answer("Test faollashtirildi!")

# ---------- Actions (tests + groups) ----------

async def _refresh_to_test(cb: types.CallbackQuery, tid: str, toast: str):
    try:
        await cb.answer(toast, show_alert=False)
    except Exception:
        pass
    await _open_test(cb, tid)

async def cb_test_action(cb: types.CallbackQuery, state: FSMContext):
    """Handle test actions with proper checkbox updates"""
    user_id = cb.from_user.id
    
    # Check permissions
    if not is_owner(user_id) and not is_admin(user_id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return

    data = (cb.data or "").strip()
    parts = data.split(":")

    if len(parts) < 3 or parts[0] != "t":
        return await cb.answer("Noto'g'ri buyruq", show_alert=True)

    action = parts[1]
    tid = parts[2]
    
    # Check if admin can manage this test
    if not is_owner(user_id):
        if not can_user_manage_test(user_id, tid):
            await cb.answer("Siz bu testni boshqara olmaysiz", show_alert=True)
            return

    try:
        # ----- view -----
        if action == "view":
            await cb.answer()
            return await _open_test(cb, tid)

        # ----- activate -----
        if action == "act":
            await cb.answer()
            set_test_active(tid, True)
            log_action(cb.from_user.id, "test_activate", ok=True, test_id=tid)
            
            # Get test info
            test_data = read_test(tid)
            test_name = test_data.get("test_name", "Test")
            assigned_groups = []
            for g in test_data.get("groups", []):
                try:
                    assigned_groups.append(int(g))
                except:
                    pass
                
            if assigned_groups:
                await cb.message.answer("⏳ Test faollashtirilmoqda va xabarlar yuborilmoqda...")
                
                # Notify groups and members
                notification_results = await notify_groups_and_members(assigned_groups, test_name, tid)
                
                # Show results
                total_notified = notification_results['total_notified']
                total_failed = notification_results['total_failed']
                groups_notified = notification_results['groups_notified']
                
                result_message = (
                    f"✅ Test faollashtirildi!\n\n"
                    f"📢 {groups_notified}/{len(assigned_groups)} guruhga xabar yuborildi\n"
                    f"📨 {total_notified} talabaga shaxsiy xabar\n"
                )
                
                if total_failed > 0:
                    result_message += f"⚠️ {total_failed} talabaga xabar yetmadi"
                
                await cb.message.answer(result_message)
            else:
                await cb.message.answer("⚠️ Test faollashtirildi, lekin guruh tayinlanmagan.")
            
            return await _refresh_to_test(cb, tid, "Faollashtirildi")

        # ----- deactivate -----
        if action == "deact":
            await cb.answer()
            set_test_active(tid, False)
            log_action(cb.from_user.id, "test_deactivate", ok=True, test_id=tid)
            return await _refresh_to_test(cb, tid, "O'chirildi")

        # ----- delete -----
        if action == "del":
            await cb.answer()
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton("❌ Ha, o'chirish", callback_data=f"t:delconfirm:{tid}"),
                types.InlineKeyboardButton("🔙 Bekor qilish", callback_data=f"t:view:{tid}")
            )
            try:
                await cb.message.edit_text(
                    f"⚠️ <b>Testni o'chirishni tasdiqlang</b>\n\nTest ID: <code>{tid}</code>\n\nBu amal qaytarib bo'lmaydi!",
                    reply_markup=kb
                )
            except MessageNotModified:
                pass
            return

        # ----- delete confirm -----
        if action == "delconfirm":
            await cb.answer()
            idx = load_tests_index()
            tests = idx.get("tests", {})
            rec = tests.pop(tid, None)
            save_tests_index(idx)
            
            try:
                p = test_path(tid)
                if p.exists():
                    os.remove(p)
            except Exception as e:
                log.warning(f"Could not delete test file: {e}")
            
            log_action(cb.from_user.id, "test_delete", ok=True, test_id=tid)
            await cb.message.answer("🗑 Test o'chirildi")
            return await cb_panel_tests(cb)

        # ----- assign: open group picker -----
        if action == "assign":
            await cb.answer()
            await state.finish()
            
            # Get available groups
            if is_owner(cb.from_user.id):
                gids = load_group_ids()
            else:
                gids = get_user_admin_groups(cb.from_user.id)
                
            if not gids:
                await cb.message.answer("❌ Sizda guruhlar yo'q.")
                return await _open_test(cb, tid)

            items = await _resolve_group_titles(gids)
            
            # Get current assigned groups
            test_data = read_test(tid)
            current_groups = test_data.get("groups", [])
            preselected = set()
            for g in current_groups:
                try:
                    preselected.add(int(g))
                except (ValueError, TypeError):
                    pass
            
            # Initialize state with preselected groups
            await state.update_data(assign_tid=tid, sel=list(preselected))
            
            txt = f"<b>Guruhlarga tayinlash</b>\nTest: <code>{tid}</code>\nGuruhlarni tanlash uchun bosing, keyin <b>Tayyor</b> tugmasini bosing."
            kb = _assign_groups_kb(tid, items, preselected)
            
            try:
                await cb.message.edit_text(txt, reply_markup=kb)
            except MessageNotModified:
                pass
            return

        # ----- pick: toggle group selection -----
        if action == "pick":
            if len(parts) < 4:
                return await cb.answer("Noto'g'ri guruh ID")
            
            try:
                gid = int(parts[3])
            except ValueError:
                return await cb.answer("Yaroqsiz guruh ID")

            # Get current state
            s = await state.get_data()
            
            # Ensure we're working with the right test
            if s.get("assign_tid") != tid:
                await state.update_data(assign_tid=tid, sel=[])
                s = await state.get_data()

            # Get current selection
            sel = set()
            try:
                current_sel = s.get("sel", [])
                if current_sel:
                    sel = set(map(int, current_sel))
            except (ValueError, TypeError):
                pass
            
            # Toggle selection
            if gid in sel:
                sel.remove(gid)
                await cb.answer(f"❌ Guruh {gid} olib tashlandi")
            else:
                sel.add(gid)
                await cb.answer(f"✅ Guruh {gid} tanlandi")
            
            # Update state
            await state.update_data(sel=list(sel))
            
            # Refresh UI with updated checkboxes
            if is_owner(cb.from_user.id):
                gids = load_group_ids()
            else:
                gids = get_user_admin_groups(cb.from_user.id)
            
            items = await _resolve_group_titles(gids)
            txt = f"<b>Guruhlarga tayinlash</b>\nTest: <code>{tid}</code>\nTanlangan: {len(sel)} ta guruh"
            
            # Update the keyboard with new selection
            kb = _assign_groups_kb(tid, items, sel)
            
            try:
                await cb.message.edit_text(txt, reply_markup=kb)
            except MessageNotModified:
                # If text didn't change, force update by adding a zero-width space
                txt += "​"  # Zero-width space
                try:
                    await cb.message.edit_text(txt, reply_markup=kb)
                except:
                    pass
            return

        # ----- pickall: select all groups -----
        if action == "pickall":
            await cb.answer("Barcha guruhlar tanlandi")
            
            if is_owner(cb.from_user.id):
                gids = load_group_ids()
            else:
                gids = get_user_admin_groups(cb.from_user.id)
            
            try:
                sel = list(map(int, gids))
            except (ValueError, TypeError):
                sel = []
            
            await state.update_data(assign_tid=tid, sel=sel)
            items = await _resolve_group_titles(gids)
            txt = f"<b>Guruhlarga tayinlash</b>\nTest: <code>{tid}</code>\nBarcha guruhlar tanlandi: {len(sel)} ta"
            
            try:
                await cb.message.edit_text(txt, reply_markup=_assign_groups_kb(tid, items, set(sel)))
            except MessageNotModified:
                pass
            return

        # ----- clear: deselect all -----
        if action == "clear":
            await cb.answer("Tanlov tozalandi")
            await state.update_data(assign_tid=tid, sel=[])
            
            if is_owner(cb.from_user.id):
                gids = load_group_ids()
            else:
                gids = get_user_admin_groups(cb.from_user.id)
            
            items = await _resolve_group_titles(gids)
            txt = f"<b>Guruhlarga tayinlash</b>\nTest: <code>{tid}</code>\nHech narsa tanlanmagan"
            
            try:
                await cb.message.edit_text(txt, reply_markup=_assign_groups_kb(tid, items, set()))
            except MessageNotModified:
                pass
            return

        # ----- assigndone: save the assignment -----
        if action == "assigndone":
            s = await state.get_data()
            
            # Verify we have the right test
            if s.get("assign_tid") != tid:
                await cb.answer("Sessiya topilmadi", show_alert=True)
                return await _open_test(cb, tid)

            # Get selected groups
            try:
                sel = list(map(int, s.get("sel", [])))
            except (ValueError, TypeError):
                sel = []
            
            if not sel:
                await cb.answer("❌ Kamida bitta guruhni tanlang!", show_alert=True)
                return

            # SAVE THE ASSIGNMENT
            assign_test_groups(tid, sel)
            log_action(cb.from_user.id, "test_assign_groups", ok=True, test_id=tid, extra={"groups": sel})
            
            # Clear state
            await state.finish()
            
            # Show success message
            await cb.answer("✅ Muvaffaqiyatli saqlandi!")
            await cb.message.answer(f"✅ Test {len(sel)} ta guruhga tayinlandi")
            
            # Return to test view
            return await _open_test(cb, tid)

        # Unknown action
        return await cb.answer(f"Noma'lum amal: {action}")

    except Exception as e:
        log.error(f"Error in test action {action}: {e}")
        await cb.answer(f"Xatolik: {e}", show_alert=True)

# ---------- Groups actions (callbacks) ----------

async def cb_groups_action(cb: types.CallbackQuery, state: FSMContext):
    if not is_owner(cb.from_user.id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    
    from keyboards import back_kb
    from utils import sync_all_groups
    
    data = cb.data or ""

    if data == "g:sync":
        gids = load_group_ids()
        if not gids:
            await cb.answer("Guruhlar ro'yxatdan o'tmagan.", show_alert=True)
            return await cb_panel_groups(cb)
        
        # Sync all groups and get member info
        await cb.answer("Guruhlar sinxronlanmoqda...", show_alert=False)
        sync_results = await sync_all_groups()
        
        lines = ["<b>Guruhlar (sinxronlangan):</b>"]
        for gid in gids:
            try:
                chat = await bot.get_chat(gid)
                total_count = await bot.get_chat_member_count(gid)
                synced_count = sync_results.get(gid, 0)
                title = chat.title or f"Group {gid}"
                lines.append(f"• <code>{gid}</code> — {title}")
                lines.append(f"  Jami: {total_count}, Sinxronlangan: {synced_count} a'zo")
            except Exception as e:
                lines.append(f"• <code>{gid}</code> — <i>kirish imkonsiz: {e}</i>")
        
        await safe_edit(cb.message, "\n".join(lines), _groups_manage_kb())
        return

    if data == "g:add":
        # Clear any existing state first
        await state.finish()
        await state.set_state(AdminStates.Confirming.state)
        await state.update_data(mode="add_group")
        txt = (
            "<b>Guruh qo'shish</b>\n"
            "Vergul bilan ajratilgan guruh ID larini yuboring (masalan: <code>-100123,-100456</code>),\n"
            "yoki maqsadli guruhda <code>/registergroup</code> buyrug'ini ishga tushiring."
        )
        await safe_edit(cb.message, txt, back_kb("panel:groups"))
        return

    if data == "g:remove":
        # Clear any existing state first
        await state.finish()
        await state.set_state(AdminStates.Confirming.state)
        await state.update_data(mode="remove_group")
        txt = "O'chirish uchun vergul bilan ajratilgan guruh ID larini yuboring (masalan: <code>-100123,-100456</code>)."
        await safe_edit(cb.message, txt, back_kb("panel:groups"))
        return

    # If anything else sneaks in:
    return await cb.answer("Noma'lum guruh amali")

# ---------- Confirming: multiplexed handler ----------

# --- Assign UI helpers ---

async def _resolve_group_titles(ids):
    """Return list[(gid, title_or_id)]"""
    out = []
    for gid in ids:
        try:
            chat = await bot.get_chat(gid)
            title = chat.title or str(gid)
        except Exception:
            title = str(gid)
        out.append((gid, title))
    return out

def _assign_groups_kb(tid: str, items: list, selected: set):
    kb = types.InlineKeyboardMarkup(row_width=1)
    # toggle buttons with checkmarks
    for gid, title in items:
        try:
            gid_int = int(gid)
            mark = "✅" if gid_int in selected else "☐"
            display_title = title[:30] + "..." if len(title) > 30 else title
            kb.add(types.InlineKeyboardButton(f"{mark} {display_title} ({gid})", callback_data=f"t:pick:{tid}:{gid}"))
        except (ValueError, TypeError):
            continue
    # actions
    row = [
        types.InlineKeyboardButton("Barchasini tanlash", callback_data=f"t:pickall:{tid}"),
        types.InlineKeyboardButton("Tozalash", callback_data=f"t:clear:{tid}"),
    ]
    kb.row(*row)
    kb.add(types.InlineKeyboardButton("✅ Tayyor", callback_data=f"t:assigndone:{tid}"))
    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="panel:tests"))
    return kb

async def msg_receive_group_ids(message: types.Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    text = (message.text or "").strip()

    # allow cancel by text
    if text.lower() in {"cancel", "back", "bekor", "orqaga"}:
        await state.finish()
        return await message.reply("Bekor qilindi. Panel ga qaytish uchun /start yuboring.")

    sdata = await state.get_data()
    mode = sdata.get("mode")
    assign_tid = sdata.get("assign_tid")

    # Helper to parse ids
    def parse_ids(s: str):
        raw = [x.strip() for x in s.split(",") if x.strip()]
        ids, bad = [], []
        for r in raw:
            try:
                ids.append(int(r))
            except Exception:
                bad.append(r)
        return ids, bad

    # --- Assign test to groups ---
    if mode == "assign_test_groups" or assign_tid:
        tid = assign_tid
        if not tid:
            await state.finish()
            await message.reply("Tayinlash uchun hech narsa yo'q. Panel → Testlar → Tayinlash ni qayta oching.")
            return
        if text.lower() == "all":
            groups = load_group_ids()
        else:
            groups, bad = parse_ids(text)
            if bad:
                return await message.reply(f"Yaroqsiz guruh ID(lar): {', '.join(bad)}")

        assign_test_groups(tid, groups)
        log_action(message.from_user.id, "test_assign_groups", ok=True, test_id=tid, extra={"groups": groups})
        await state.finish()
        return await message.reply(
            f"Test <code>{tid}</code> quyidagi guruhlarga tayinlandi: {', '.join(map(str, groups)) or '-'}\n"
            f"Faollashtirish/O'chirish uchun Panel → Testlar ga qayting."
        )

    # --- Add groups ---
    if mode == "add_group":
        ids, bad = parse_ids(text)
        if bad:
            return await message.reply(f"Yaroqsiz guruh ID(lar): {', '.join(bad)}")
        await _groups_append(ids)
        log_action(message.from_user.id, "group_add", ok=True, extra={"groups": ids})
        await state.finish()
        return await message.reply("Guruh(lar) qo'shildi. Tekshirish uchun Panel → Guruhlar ni oching.")

    # --- Remove groups ---
    if mode == "remove_group":
        ids, bad = parse_ids(text)
        if bad:
            return await message.reply(f"Yaroqsiz guruh ID(lar): {', '.join(bad)}")
        await _groups_remove(ids)
        log_action(message.from_user.id, "group_remove", ok=True, extra={"groups": ids})
        await state.finish()
        return await message.reply("Guruh(lar) o'chirildi. Tekshirish uchun Panel → Guruhlar ni oching.")

    # Fallback
    await state.finish()
    await message.reply("Hech narsa kutilmayapti. Panel tugmalarini qayta ishlating.")

# ---------- Backup (snapshot data/) ----------

async def cb_panel_backup(cb: types.CallbackQuery):
    if not is_owner(cb.from_user.id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    
    ts = time.strftime("%Y%m%d_%H%M%S")
    dst = f"backups/data_{ts}"
    try:
        os.makedirs("backups", exist_ok=True)
        shutil.copytree("data", dst)
        await cb.answer(f"Backup yaratildi: {dst}", show_alert=True)
    except Exception as e:
        await cb.answer(f"Backup xatolik: {e}", show_alert=True)

# ---------- Router (panel:*, g:*, t:*) ----------
async def callbacks_router(cb: types.CallbackQuery, state: FSMContext):
    if not is_owner(cb.from_user.id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    
    data = (cb.data or "").strip()
    log.info(f"Admin callback router: {data}")

    # Back / panel navigation
    if data in {"back", "panel:back"} or data.startswith("panel:"):
        cur = await state.get_state()
        if cur == AdminStates.Confirming.state:
            await state.finish()

        if data in {"back", "panel:back"}:
            return await cb_panel_groups(cb)

        if data == "panel:home":     return await cb_panel_home(cb)
        if data == "panel:admins":   return await cb_panel_admins(cb)
        if data == "panel:groups":   return await cb_panel_groups(cb)
        if data == "panel:students": return await cb_panel_students(cb)
        if data == "panel:tests":    return await cb_panel_tests(cb)
        if data == "panel:backup":   return await cb_panel_backup(cb)

    elif data.startswith("g:"):
        return await cb_groups_action(cb, state)

    elif data.startswith("t:"):
        return await cb_test_action(cb, state)

    else:
        await cb.answer("Noma'lum amal")

        