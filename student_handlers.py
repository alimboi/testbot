import time
import logging
import asyncio
import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from functools import wraps
from aiogram import types
from aiogram.dispatcher import FSMContext
from states import StudentStates
from utils import (
    available_tests_for_user,
    read_test,
    score_user_answers,
    save_student_data,
    load_group_titles,
    get_user_groups,
    load_group_members,
    add_user_to_group,
    load_group_ids,
    save_test_session,
    load_test_session,
    delete_test_session,
    get_user_sessions,
    get_user_admin_groups,
    remove_user_admin_privileges, 
    get_student_admins,  
)
import html
import re
log = logging.getLogger("student_handlers")


# --- Markdown fenced code  ```lang ... ```  →  HTML <pre><code> normalizer ---

_FENCE_RE = re.compile(
    r"```([A-Za-z0-9_+\-]*)[ \t]*\n?([\s\S]*?)\n?```",
    re.MULTILINE
)

_CODEBLOCK_RE = re.compile(r'(<pre><code[^>]*>.*?</code></pre>)', re.IGNORECASE | re.DOTALL)

def _normalize_fenced_code_to_html(text: str) -> str:
    """
    Convert Markdown-style fenced blocks into Telegram-safe HTML:
        ```js console.log('hi') ```
        ```python
        print('x')
        ```
    becomes:
        <pre><code class="language-js">console.log('hi')</code></pre>
        <pre><code class="language-python">print(&#x27;x&#x27;)</code></pre>
    """
    if not text:
        return ""

    def _repl(m: re.Match) -> str:
        lang = (m.group(1) or "").strip()
        code = (m.group(2) or "")
        # Ensure code is on its own lines (handles one-line ```js console.log(...) ```)
        code = code.strip("\n")
        # Escape code content so it’s safe when we later skip re-escaping placeholders
        escaped = html.escape(code, quote=False)
        class_attr = f' class="language-{lang}"' if lang else ""
        return f"<pre><code{class_attr}>{escaped}</code></pre>"

    return _FENCE_RE.sub(_repl, text)


def sanitize_html_for_telegram(text: str) -> str:
    """
    Sanitize text for Telegram's HTML parser while preserving code blocks.
    - Normalizes ```lang fences → <pre><code class="language-...">...</code></pre>
    - Escapes dangerous chars outside allowed tags
    - Preserves whitespace/newlines inside code blocks
    Allowed tags: b, i, u, s, code, pre, a, tg-spoiler
    """
    if not text:
        return ""

    # 0) Normalize Markdown fences first (handles same-line code after ```lang and lone closing ```)
    text = _normalize_fenced_code_to_html(text)

    # 1) Temporarily extract code blocks to protect their content/whitespace
    code_blocks = {}
    def _stash_codeblock(m: re.Match) -> str:
        idx = len(code_blocks)
        key = f"__CODEBLOCK_{idx}__"
        code_blocks[key] = m.group(1)
        return key
    text = _CODEBLOCK_RE.sub(_stash_codeblock, text)

    # 2) Decode HTML entities
    text = html.unescape(text)

    # 3) Strip disallowed containers entirely
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'</?(?:html|head|body|meta|link)[^>]*>', '', text, flags=re.IGNORECASE)

    # 4) Keep only Telegram-supported tags (keep attributes as-is)
    allowed_tags = ['b', 'i', 'u', 's', 'code', 'pre', 'a', 'tg-spoiler']  # matches your previous allow-list :contentReference[oaicite:3]{index=3}
    def _strip_unallowed_tags(m: re.Match) -> str:
        tag = m.group(1).lower()
        return m.group(0) if tag in allowed_tags else ''
    text = re.sub(r'</?([a-zA-Z][a-zA-Z0-9]*)[^>]*>', _strip_unallowed_tags, text)

    # 5) Escape &, <, > outside allowed tags
    #    (Protect allowed tags with placeholders while escaping)
    tag_placeholders = {}
    ph_counter = 0
    for tag in allowed_tags:
        # opening
        for m in re.finditer(fr'<{tag}[^>]*>', text, flags=re.IGNORECASE):
            ph = f'__TAGPH_{ph_counter}__'; ph_counter += 1
            tag_placeholders[ph] = m.group(0)
            text = text.replace(m.group(0), ph, 1)
        # closing
        for m in re.finditer(fr'</{tag}>', text, flags=re.IGNORECASE):
            ph = f'__TAGPH_{ph_counter}__'; ph_counter += 1
            tag_placeholders[ph] = m.group(0)
            text = text.replace(m.group(0), ph, 1)

    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # Restore allowed tags
    for ph, original in tag_placeholders.items():
        text = text.replace(ph, original)

    # 6) Light whitespace normalization OUTSIDE code blocks (preserve newlines)
    #    - collapse runs of spaces/tabs
    text = re.sub(r'[ \t\f\v]+', ' ', text)
    #    - collapse 3+ blank lines to max 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    # 7) Restore code blocks (already escaped inside)
    for ph, block in code_blocks.items():
        text = text.replace(ph, block)

    return text



# Rate limiting
_user_rate_limits = {}

def rate_limit(max_calls=5, window_seconds=30):
    def decorator(func):
        @wraps(func)
        async def wrapper(message_or_cb, *args, **kwargs):
            user_id = (message_or_cb.from_user.id if hasattr(message_or_cb, 'from_user') 
                      else message_or_cb.message.from_user.id)
            
            now = time.time()
            user_calls = _user_rate_limits.get(user_id, [])
            
            # Remove old calls outside window
            user_calls = [call_time for call_time in user_calls if now - call_time < window_seconds]
            
            if len(user_calls) >= max_calls:
                if hasattr(message_or_cb, 'answer'):
                    await message_or_cb.answer("Test savollarini yaxshilab o'qib javob beramiz", show_alert=True)
                else:
                    await message_or_cb.reply("Test savollarini yaxshilab o'qib javob beramiz")
                return
            
            user_calls.append(now)
            _user_rate_limits[user_id] = user_calls
            
            return await func(message_or_cb, *args, **kwargs)
        return wrapper
    return decorator

# Enhanced error handling
async def safe_student_operation(operation, cb_or_msg, *args, **kwargs):
    """Wrapper for safe student operations with comprehensive error handling"""
    try:
        return await operation(cb_or_msg, *args, **kwargs)
    except Exception as e:
        log.error(f"Student operation failed: {e}", exc_info=True)
        
        # Handle specific callback errors
        if "Query is too old" in str(e) or "invalid" in str(e).lower():
            log.info(f"Callback query expired for user - this is normal after reconnection")
            try:
                if hasattr(cb_or_msg, 'message'):
                    await cb_or_msg.message.answer(
                        "Ulanish tiklandi. Iltimos /start yuboring yoki testni davom ettiring."
                    )
                else:
                    await cb_or_msg.reply(
                        "Ulanish tiklandi. Iltimos /start yuboring yoki testni davom ettiring."
                    )
            except Exception as notify_error:
                log.error(f"Failed to notify user of expired callback: {notify_error}")
            return
        
        # Other error types
        error_messages = {
            "Test topilmadi": "Test mavjud emas yoki o'chirilgan. /start buyrug'ini yuboring.",
            "permission": "Bu test uchun ruxsatingiz yo'q.",
            "session": "Sessiya xatoligi. /start buyrug'ini yuboring.",
            "network": "Tarmoq xatoligi. Qaytadan urinib ko'ring.",
        }
        
        user_message = "Xatolik yuz berdi. /start buyrug'ini yuboring."
        for error_key, message in error_messages.items():
            if error_key.lower() in str(e).lower():
                user_message = message
                break
        
        try:
            if hasattr(cb_or_msg, 'message'):  # CallbackQuery
                await cb_or_msg.message.answer(user_message)
            else:  # Message
                await cb_or_msg.reply(user_message)
        except Exception as notify_error:
            log.error(f"Failed to notify user of error: {notify_error}")

# Improved session management
def get_user_session_dir(user_id: int) -> Path:
    """Get session directory for a specific user"""
    session_dir = Path("data/sessions") / str(user_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir

def get_session_file_path(user_id: int, test_id: str) -> Path:
    """Get session file path for user and test"""
    return get_user_session_dir(user_id) / f"{test_id}.json"

async def write_json_atomic(file_path: Path, data: dict) -> bool:
    """Write JSON data atomically to prevent corruption"""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = file_path.with_suffix('.tmp')
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_path.replace(file_path)
        return True
    except Exception as e:
        log.error(f"Failed to write JSON to {file_path}: {e}")
        if temp_path.exists():
            temp_path.unlink()
        return False

async def read_json_safe(file_path: Path, default=None) -> dict:
    """Read JSON with error handling"""
    try:
        if not file_path.exists():
            return default or {}
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log.error(f"Failed to read JSON from {file_path}: {e}")
        return default or {}

# Input validation
def validate_question_index(qidx_str: str, max_questions: int = 1000) -> tuple:
    """Validate question index input"""
    try:
        qidx = int(qidx_str)
        if 1 <= qidx <= max_questions:
            return True, qidx
        return False, 0
    except (ValueError, TypeError):
        return False, 0

def validate_test_id(test_id: str) -> bool:
    """Validate test ID format"""
    if not test_id or len(test_id) > 100:
        return False
    return bool(re.match(r'^[a-zA-Z0-9\-_]+$', test_id))

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

def _format_question(q: dict, excluded_options: List[str] = None) -> str:
    """Format question with options, excluding specified ones — with HTML sanitization."""
    idx = q.get("index")
    text = q.get("text") or ""
    opts = q.get("options") or {}
    excluded_options = excluded_options or []

    # Sanitize question text (this will also normalize ``` fences to <pre><code>…</code></pre>)
    text = sanitize_html_for_telegram(text)

    # Put header on its own line to avoid jamming with a leading code block
    lines = [f"<b>Savol {idx}.</b>"]
    if text:
        lines.append(text)

    for key in ("A", "B", "C", "D"):
        if key in opts:
            option_text = sanitize_html_for_telegram(opts[key])
            if key not in excluded_options:
                lines.append(f"{key}) {option_text}")
            else:
                lines.append(f"<s>{key}) ❌ Noto'g'ri</s>")

    return "\n".join(lines)


def _get_question(test: dict, qidx: int) -> Optional[dict]:
    for q in (test.get("questions") or []):
        if int(q.get("index", 0)) == int(qidx):
            return q
    return None

def _create_answer_keyboard(qidx: int, excluded_options: List[str] = None) -> types.InlineKeyboardMarkup:
    """Create keyboard for answers, excluding specified options"""
    excluded_options = excluded_options or []
    kb = types.InlineKeyboardMarkup(row_width=2)
    
    available_options = []
    for opt in ["A", "B", "C", "D"]:
        if opt not in excluded_options:
            available_options.append(
                types.InlineKeyboardButton(opt, callback_data=f"ans:{qidx}:{opt}")
            )
    
    for i in range(0, len(available_options), 2):
        if i + 1 < len(available_options):
            kb.row(available_options[i], available_options[i+1])
        else:
            kb.row(available_options[i])
    
    return kb

def _create_understanding_keyboard() -> types.InlineKeyboardMarkup:
    """Create yes/no keyboard for understanding confirmation"""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Ha, tushundim", callback_data="understand:yes"),
        types.InlineKeyboardButton("❌ Yo'q, qayta", callback_data="understand:no")
    )
    return kb

def _create_tests_keyboard(tests: List[dict]) -> types.InlineKeyboardMarkup:
    """Create inline keyboard with clickable test buttons"""
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for test in tests:
        test_id = test.get("test_id", "")
        test_name = test.get("test_name", "Test")
        display_name = test_name[:50] + "..." if len(test_name) > 50 else test_name
        button = types.InlineKeyboardButton(
            text=f"🧪 {display_name}",
            callback_data=f"select_test:{test_id}"
        )
        keyboard.add(button)
    return keyboard



def _user_is_in_test_groups(user_id: int, test: dict) -> bool:
    """Check if user can access the test based on group membership"""
    test_groups = set()
    for g in (test.get("groups") or []):
        try:
            test_groups.add(int(g))
        except (ValueError, TypeError):
            pass
    
    if test.get("group_id"):
        try:
            test_groups.add(int(test["group_id"]))
        except (ValueError, TypeError):
            pass
    
    if not test_groups:
        log.info(f"Test has no groups assigned, allowing user {user_id}")
        return True
    
    user_groups = set()
    
    try:
        user_groups_list = get_user_groups(user_id)
        user_groups.update(user_groups_list)
        log.info(f"User {user_id} groups from user_groups.json: {user_groups_list}")
    except Exception as e:
        log.warning(f"Could not get user groups from user_groups.json: {e}")
    
    try:
        gm = load_group_members()
        for gid_str, rec in gm.items():
            try:
                gid = int(gid_str)
                members = set(int(x) for x in rec.get("members", []))
                if user_id in members:
                    user_groups.add(gid)
            except (ValueError, TypeError):
                continue
        log.info(f"User {user_id} groups from group_members.json: {user_groups}")
    except Exception as e:
        log.warning(f"Could not check group_members.json: {e}")
    
    common_groups = user_groups.intersection(test_groups)
    log.info(f"User {user_id} membership check:")
    log.info(f"  Test groups: {test_groups}")
    log.info(f"  User groups: {user_groups}")
    log.info(f"  Common groups: {common_groups}")
    log.info(f"  Access allowed: {bool(common_groups)}")
    
    if common_groups:
        return True
    
    if not user_groups:
        log.info(f"No group data found for user {user_id}, allowing access as fallback")
        return True
    
    return False

def _review_lines(answers: Dict[str,str], test: dict) -> Tuple[List[str], Tuple[int,int]]:
    """Generate review with detailed results - WITH HTML SANITIZATION"""
    correct = test.get("answers") or {}
    refs = test.get("references") or {}
    ok, total = score_user_answers(answers, correct)
    
    lines = [f"<b>📊 Yakuniy natija:</b> {ok}/{total}"]
    
    if total:
        percentage = round((ok / total) * 100, 1)
        lines.append(f"<b>📈 Foiz:</b> {percentage}%")
        
        if percentage >= 90:
            grade = "A'lo (5)"
            emoji = "🌟"
        elif percentage >= 75:
            grade = "Yaxshi (4)"
            emoji = "✨"
        elif percentage >= 60:
            grade = "Qoniqarli (3)"
            emoji = "👍"
        else:
            grade = "Qayta o'qish tavsiya etiladi"
            emoji = "📚"
        
        lines.append(f"<b>📝 Baho:</b> {grade} {emoji}")
    
    lines.append("")
    lines.append("<b>📋 Tafsilotlar:</b>")
    
    for i in range(1, total + 1):
        i_s = str(i)
        user_answer = answers.get(i_s, "—")
        correct_answer = correct.get(i_s, "—")
        mark = "✅" if user_answer == correct_answer else "❌"
        
        line = f"{i}. Sizning javobingiz: <b>{user_answer}</b> | To'g'ri javob: <b>{correct_answer}</b> {mark}"
        
        if user_answer != correct_answer and refs.get(i_s):
            # SANITIZE reference text
            ref_text = sanitize_html_for_telegram(refs[i_s])
            line += f"\n   💡 <i>{ref_text}</i>"
        
        lines.append(line)
    
    return lines, (ok, total)

async def _send_question(sender, test: dict, qidx: int, excluded_options: List[str] = None):
    """Send question with excluded options"""
    q = _get_question(test, qidx)
    if not q:
        log.error(f"Question {qidx} not found in test")
        return
    
    txt = _format_question(q, excluded_options)
    kb = _create_answer_keyboard(qidx, excluded_options)
    
    try:
        if isinstance(sender, types.CallbackQuery):
            await sender.message.answer(txt, reply_markup=kb)
        else:
            await sender.answer(txt, reply_markup=kb)
    except Exception as e:
        log.error(f"Failed to send question {qidx}: {e}")

async def _save_session(user_id: int, test_id: str, session_data: dict):
    """Save test session to persistent storage with improved error handling"""
    try:
        clean_data = session_data.copy()
        clean_data['last_updated'] = int(time.time())
        
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
        
        session_path = get_session_file_path(user_id, test_id)
        success = await write_json_atomic(session_path, clean_data)
        
        if not success:
            log.warning(f"Failed to save session for user {user_id}, test {test_id}")
            # Fallback to old method
            save_test_session(user_id, test_id, clean_data)
            
    except Exception as e:
        log.error(f"Session save error for user {user_id}, test {test_id}: {e}")
        # Fallback to old method
        try:
            save_test_session(user_id, test_id, session_data)
        except Exception as fallback_error:
            log.error(f"Fallback session save also failed: {fallback_error}")

async def _load_session(user_id: int, test_id: str) -> Optional[dict]:
    """Load test session from persistent storage with improved error handling"""
    try:
        session_path = get_session_file_path(user_id, test_id)
        session_data = await read_json_safe(session_path)
        
        if session_data:
            # Convert excluded_options back to expected format
            if 'excluded_options' in session_data:
                for k, v in session_data['excluded_options'].items():
                    if isinstance(v, list):
                        session_data['excluded_options'][k] = v
            return session_data
        
        # Fallback to old method
        return load_test_session(user_id, test_id)
        
    except Exception as e:
        log.error(f"Session load error for user {user_id}, test {test_id}: {e}")
        # Fallback to old method
        try:
            return load_test_session(user_id, test_id)
        except Exception as fallback_error:
            log.error(f"Fallback session load also failed: {fallback_error}")
            return None

async def _finish_test(cb: types.CallbackQuery, state: FSMContext, test: dict):
    """Finish test and show results"""
    s = await state.get_data()
    answers = s.get("answers", {})
    wrong_attempts = s.get("wrong_attempts", {})
    test_id = s.get("active_test_id")
    
    review, (ok, total) = _review_lines(answers, test)
    
    review.append("")
    review.append("<b>📊 Urinishlar statistikasi:</b>")
    for q_idx, attempts in wrong_attempts.items():
        review.append(f"Savol {q_idx}: {attempts + 1} ta urinish")
    
    try:
        save_student_data(cb.from_user.id, {
            "full_name": s.get("student_name"),
            "last_test_id": test_id,
            "last_score": {"ok": ok, "total": total},
            "last_answers": answers,
            "wrong_attempts": wrong_attempts,
            "finished_at": int(time.time()),
        })
    except Exception as e:
        log.error(f"save_student_data failed: {e}")
    
    await cb.message.answer("\n".join(review))
    
    try:
        from config import bot, OWNER_ID
        s = await state.get_data()
        ok, total = score_user_answers(answers, test.get("answers", {}))
        pct = round((ok/total)*100, 1) if total else 0

        header = (
            "📊 <b>Test yakunlandi</b>\n\n"
            f"👤 Talaba: {s.get('student_name')} (@{cb.from_user.username or 'username_yoq'})\n"
            f"🧪 Test: {test.get('test_name')}\n"
            f"📈 Natija: {ok}/{total} ({pct}%)\n"
            f"⏱ Vaqt: {int((time.time() - s.get('started_at', 0)) / 60)} daqiqa\n\n"
            "<b>— Batafsil natijalar —</b>\n"
        )
        admin_detailed = header + "\n".join(review)

        # who to notify
        admin_ids = set(get_student_admins(cb.from_user.id) or [])  # admins of student's groups
        admin_ids.add(int(OWNER_ID))                                 # always include owner
        admin_ids.discard(cb.from_user.id)                           # never DM the student again

        # send (chunk if needed)
        async def _send_long(chat_id: int, text: str):
            if len(text) <= 3900:
                await bot.send_message(chat_id, text, disable_web_page_preview=True)
                return
            # split by lines to respect Telegram 4096 limit
            lines, chunk = text.splitlines(), []
            cur = 0
            for ln in lines:
                if cur + len(ln) + 1 > 3900:
                    await bot.send_message(chat_id, "\n".join(chunk), disable_web_page_preview=True)
                    chunk, cur = [ln], len(ln) + 1
                else:
                    chunk.append(ln); cur += len(ln) + 1
            if chunk:
                await bot.send_message(chat_id, "\n".join(chunk), disable_web_page_preview=True)

        for admin_id in admin_ids:
            try:
                await _send_long(admin_id, admin_detailed)
            except Exception as e:
                log.warning(f"Admin notify failed for {admin_id}: {e}")

    except Exception as e:
        log.error(f"Failed to notify admins/owner with full results: {e}")
    
    if test_id:
        try:
            session_path = get_session_file_path(cb.from_user.id, test_id)
            if session_path.exists():
                session_path.unlink()
        except:
            pass
        # Fallback cleanup
        delete_test_session(cb.from_user.id, test_id)
    
    await cb.answer("Test yakunlandi!")
    await state.finish()

# ------------------------------------------------------------------------------
# Main handlers
# ------------------------------------------------------------------------------

def safe_callback_answer(cb: types.CallbackQuery, message: str = None, show_alert: bool = False):
    """
    Safely answer callback query, ignoring InvalidQueryID errors
    """
    try:
        return cb.answer(message, show_alert=show_alert)
    except Exception as e:
        if "Query is too old" in str(e) or "invalid" in str(e).lower():
            log.debug(f"Callback query expired for user {cb.from_user.id}")
            return None
        raise e

async def student_start(message: types.Message, state: FSMContext):
    """Entry point with enhanced new user detection and sync"""
    user_id = message.from_user.id
    
    try:
        # Check if owner
        from utils import is_owner
        if is_owner(user_id):
            from admin_handlers import owner_panel
            return await owner_panel(message)
        
        # Check if admin
        current_admin_groups = await check_user_current_admin_status(user_id)
        if current_admin_groups:
            from admin_handlers import admin_panel
            return await admin_panel(message, current_admin_groups)
        
        # For regular users, show loading and validate
        loading_msg = await message.answer("🔍 Guruhlaringizni tekshiryapman...")
        
        try:
            # Use the new validation function that syncs for new users
            from utils import validate_and_sync_new_user
            has_valid_groups, valid_groups = await validate_and_sync_new_user(user_id)
            
            # Delete loading message
            try:
                await loading_msg.delete()
            except:
                pass
            
            if not has_valid_groups:
                # User is not in any groups
                return await message.answer(
                    "❌ Kechirasiz, siz hech qanday guruhimizning a'zosi emassiz.\n\n"
                    "Test olish uchun:\n"
                    "1. Bizning guruhlarimizdan biriga qo'shiling\n"
                    "2. Guruh admini sizni qo'shgandan keyin\n"
                    "3. /start ni qayta bosing\n\n"
                    "Agar hozirgina guruhga qo'shilgan bo'lsangiz, "
                    "iltimos bir oz kuting va qayta urinib ko'ring."
                )
            
            # User has valid groups, check for available tests
            tests = available_tests_for_user(user_id)
            
            if not tests:
                group_count = len(valid_groups)
                group_titles = load_group_titles()
                group_names = [group_titles.get(gid, f"Guruh {gid}") for gid in valid_groups]
                
                return await message.answer(
                    f"✅ Tabriklaymiz! Siz quyidagi guruhlarning a'zosisiz:\n"
                    + "\n".join([f"• {name}" for name in group_names]) + "\n\n"
                    f"📚 Ammo hozircha faol testlar yo'q.\n"
                    "Yangi test faollashtirilganda sizga xabar beramiz."
                )
            
            # Show available tests
            await show_available_tests(message, state)
            
        except Exception as e:
            try:
                await loading_msg.delete()
            except:
                pass
            log.error(f"Validation failed for user {user_id}: {e}")
            
            return await message.answer(
                "❌ Xatolik yuz berdi.\n"
                "Iltimos, keyinroq qaytadan urinib ko'ring."
            )
            
    except Exception as e:
        log.error(f"Error in student_start: {e}")
        await message.reply("Xatolik yuz berdi. Qaytadan /start buyrug'ini yuboring.")

        
# ADD this function to student_handlers.py (it was referenced but missing):
async def check_user_current_admin_status(user_id: int) -> List[int]:
    """
    Check user's CURRENT admin status by validating with Telegram API.
    Returns list of groups where user is currently an admin.
    This ensures kicked admins lose access immediately.
    """
    try:
        from config import bot
        from utils import get_user_admin_groups, remove_user_admin_privileges
        
        # Get stored admin groups
        stored_admin_groups = get_user_admin_groups(user_id)
        current_admin_groups = []
        
        if not stored_admin_groups:
            return []
        
        for group_id in stored_admin_groups:
            try:
                # Check current status in Telegram
                member = await bot.get_chat_member(group_id, user_id)
                if member.status in ["administrator", "creator"]:
                    current_admin_groups.append(group_id)
                else:
                    log.warning(f"User {user_id} no longer admin in group {group_id}, current status: {member.status}")
                    # Remove admin privileges immediately
                    remove_user_admin_privileges(user_id, group_id)
                    
            except Exception as e:
                log.warning(f"Could not check admin status for user {user_id} in group {group_id}: {e}")
                # If we can't check, don't assume they're still admin for security
                remove_user_admin_privileges(user_id, group_id)
        
        if len(current_admin_groups) != len(stored_admin_groups):
            log.info(f"Admin groups updated for user {user_id}: {stored_admin_groups} -> {current_admin_groups}")
        
        return current_admin_groups
        
    except Exception as e:
        log.error(f"Error checking admin status for user {user_id}: {e}")
        return []
    

async def show_available_tests(message: types.Message, state: FSMContext):
    """Show available tests to user with improved group display"""
    await state.set_state(StudentStates.Choosing.state)
    
    try:
        tests = available_tests_for_user(message.from_user.id)
        titles = load_group_titles()
        
        # Debug info for troubleshooting
        user_groups = get_user_groups(message.from_user.id)
        log.info(f"User {message.from_user.id} - Groups from user_groups.json: {user_groups}")
        
        gm = load_group_members()
        groups_from_membership = []
        for gid_str, rec in gm.items():
            try:
                gid = int(gid_str)
                members = set(int(x) for x in rec.get("members", []))
                if message.from_user.id in members:
                    groups_from_membership.append(gid)
            except (ValueError, TypeError):
                continue
        log.info(f"User {message.from_user.id} - Groups from group_members.json: {groups_from_membership}")
        log.info(f"User {message.from_user.id} - Available tests: {len(tests)}")
        
        # Enhance test names with group info
        def _pretty_name(t):
            name = t.get("test_name") or "Test"
            test_groups = []
            for g in (t.get("groups") or []):
                try:
                    title = titles.get(int(g))
                    if title:
                        test_groups.append(title)
                except (ValueError, TypeError):
                    pass
            
            if test_groups:
                return f"{name} — <i>{', '.join(test_groups[:2])}</i>"
            return name
        
        for t in tests:
            t["test_name"] = _pretty_name(t)
        
        if not tests:
            # Provide more helpful message
            total_groups = len(user_groups + groups_from_membership)
            if total_groups > 0:
                await message.answer(
                    f"📚 Siz {total_groups} ta guruhning a'zosisiz, lekin hozircha faol testlar yo'q.\n\n"
                    "Testlar faollashtirilganida sizga xabar beriladi."
                )
            else:
                await message.answer(
                    "❌ Sizga tayinlangan testlar topilmadi.\n\n"
                    "Agar guruhimizga yangi qo'shilgan bo'lsangiz, guruhda xabar yuboring va /start ni qayta bosing."
                )
        else:
            keyboard = _create_tests_keyboard(tests)
            await message.answer(
                "<b>📚 Mavjud testlar:</b>\n"
                "Testni boshlash uchun quyidagi tugmalardan birini bosing:",
                reply_markup=keyboard
            )
    except Exception as e:
        log.error(f"Error in show_available_tests: {e}")
        await message.answer(f"Xatolik yuz berdi: {e}")


async def validate_user_access(user_id: int, test_id: str) -> Tuple[bool, str]:
    """
    Validate if user can access a specific test with real-time group membership check.
    Returns (can_access, reason)
    """
    try:
        test = read_test(test_id)
        if not test:
            return False, "Test topilmadi"
        
        # Check if test is active
        from utils import get_active_tests
        if test_id not in get_active_tests():
            return False, "Test faol emas"
        
        # First validate user's current group membership
        from utils import validate_user_still_in_groups
        has_valid_groups, valid_groups = await validate_user_still_in_groups(user_id)
        
        if not has_valid_groups:
            return False, "Siz hech qanday guruhning a'zosi emassiz"
        
        # Check if user's valid groups match test groups
        test_groups = set()
        for g in test.get("groups", []):
            try:
                test_groups.add(int(g))
            except:
                pass
        
        # Check if user has access through any of their valid groups
        if set(valid_groups).intersection(test_groups):
            return True, "OK"
        
        return False, "Bu test sizning guruhlaringiz uchun emas"
        
    except Exception as e:
        log.error(f"Error validating user access: {e}")
        return False, f"Tekshirishda xatolik: {e}"

async def handle_new_test(cb: types.CallbackQuery, state: FSMContext):
    """Handle new test selection when user has unfinished sessions"""
    await show_available_tests(cb.message, state)
    await cb.answer()

async def handle_resume(cb: types.CallbackQuery, state: FSMContext):
    """Handle test resume"""
    if not cb.data or not cb.data.startswith("resume:"):
        return await cb.answer("Noto'g'ri format")
    
    test_id = cb.data.replace("resume:", "")
    user_id = cb.from_user.id
    
    if not validate_test_id(test_id):
        return await cb.answer("Noto'g'ri test ID", show_alert=True)
    
    session = await _load_session(user_id, test_id)
    if not session:
        await cb.answer("Sessiya topilmadi", show_alert=True)
        return await show_available_tests(cb.message, state)
    
    test = read_test(test_id)
    if not test:
        await cb.answer("Test topilmadi", show_alert=True)
        try:
            session_path = get_session_file_path(user_id, test_id)
            if session_path.exists():
                session_path.unlink()
        except:
            pass
        delete_test_session(user_id, test_id)
        return await show_available_tests(cb.message, state)
    
    await state.update_data(**session)
    await StudentStates.Answering.set()
    
    current_q = session.get("current_q", 1)
    excluded_options = session.get("excluded_options", {})
    q_key = str(current_q)
    excluded_for_q = excluded_options.get(q_key, [])
    
    await cb.message.answer(f"Test davom ettirilmoqda: <b>{test.get('test_name')}</b>")
    await _send_question(cb, test, current_q, excluded_for_q)
    await cb.answer()

async def handle_test_selection(cb: types.CallbackQuery, state: FSMContext):
    """Handle test selection with enhanced validation"""
    if not cb.data or not cb.data.startswith("select_test:"):
        return await cb.answer("Noto'g'ri format")
    
    tid = cb.data.replace("select_test:", "")
    user_id = cb.from_user.id
    
    if not validate_test_id(tid):
        return await cb.answer("Noto'g'ri test ID", show_alert=True)
    
    # Enhanced validation
    can_access, reason = await validate_user_access(user_id, tid)
    if not can_access:
        return await cb.answer(reason, show_alert=True)
    
    existing_session = await _load_session(user_id, tid)
    if existing_session:
        kb = types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton("✅ Davom etish", callback_data=f"resume:{tid}"),
            types.InlineKeyboardButton("🔄 Qayta boshlash", callback_data=f"restart:{tid}")
        )
        
        current_q = existing_session.get("current_q", 1)
        total_q = existing_session.get("total_q", 0)
        progress = f"{current_q}/{total_q}"
        
        await cb.message.answer(
            f"Bu test uchun tugallanmagan sessiyangiz bor ({progress}).\nNima qilmoqchisiz?",
            reply_markup=kb
        )
        return await cb.answer()
    
    log.info(f"User {user_id} selected test {tid}")
    
    try:
        test = read_test(tid)
        if not test or not test.get("questions"):
            return await cb.answer("Test topilmadi yoki noto'g'ri fayl.", show_alert=True)
        
        await state.update_data(active_test_id=tid)
        await cb.message.answer("Iltimos, to'liq ismingizni kiriting:")
        await StudentStates.EnteringName.set()
        await cb.answer()
    except Exception as e:
        log.error(f"Error in handle_test_selection: {e}")
        await cb.answer(f"Xatolik: {e}", show_alert=True)

async def handle_restart(cb: types.CallbackQuery, state: FSMContext):
    """Handle test restart"""
    if not cb.data or not cb.data.startswith("restart:"):
        return await cb.answer("Noto'g'ri format")
    
    test_id = cb.data.replace("restart:", "")
    user_id = cb.from_user.id
    
    if not validate_test_id(test_id):
        return await cb.answer("Noto'g'ri test ID", show_alert=True)
    
    # Clean up existing session
    try:
        session_path = get_session_file_path(user_id, test_id)
        if session_path.exists():
            session_path.unlink()
    except:
        pass
    delete_test_session(user_id, test_id)
    
    try:
        test = read_test(test_id)
        if not test or not test.get("questions"):
            return await cb.answer("Test topilmadi yoki noto'g'ri fayl.", show_alert=True)
        
        if not _user_is_in_test_groups(cb.from_user.id, test):
            return await cb.answer("Siz ushbu test uchun ro'yxatdan o'tmaganga o'xshaysiz.", show_alert=True)
        
        await state.update_data(active_test_id=test_id)
        await cb.message.answer("Iltimos, to'liq ismingizni kiriting:")
        await StudentStates.EnteringName.set()
        await cb.answer()
    except Exception as e:
        log.error(f"Error in handle_restart: {e}")
        await cb.answer(f"Xatolik: {e}", show_alert=True)

async def student_entering_name(message: types.Message, state: FSMContext):
    """Handle name input with validation"""
    try:
        full_name = (message.text or "").strip()
        
        # Input validation
        if not full_name:
            return await message.reply("Iltimos, ismingizni kiriting.")
        
        if len(full_name) < 2:
            return await message.reply("Ism juda qisqa. Kamida 2 ta harf kiriting.")
        
        if len(full_name) > 100:
            return await message.reply("Ism juda uzun. 100 ta harfdan kam kiriting.")
        
        # Basic sanitization
        if not re.match(r'^[a-zA-ZА-Яа-яЁё\s\-\'\.]+$', full_name, re.UNICODE):
            return await message.reply("Iltimos, faqat harflar va bo'sh joylardan foydalaning.")
        
        await state.update_data(student_name=full_name)
        
        kb = types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton("✅ Tasdiqlash", callback_data="st:name_ok"),
            types.InlineKeyboardButton("🔄 Qayta kiritish", callback_data="st:name_re"),
        )
        await message.answer(f"Sizning ismingiz: <b>{full_name}</b>\nTasdiqlaysizmi?", reply_markup=kb)
        await StudentStates.ConfirmingName.set()
        
    except Exception as e:
        log.error(f"Error in student_entering_name: {e}")
        await message.reply("Xatolik yuz berdi. Qaytadan ismingizni kiriting.")

async def student_confirming_name(cb: types.CallbackQuery, state: FSMContext):
    """Handle name confirmation"""
    data = cb.data or ""
    
    try:
        if data == "st:name_re":
            await cb.message.answer("Iltimos, to'liq ismingizni qayta kiriting:")
            await StudentStates.EnteringName.set()
            return await cb.answer()
        
        if data == "st:name_ok":
            rules = (
                "📋 <b>Test qoidalari:</b>\n\n"
                "1️⃣ Har bir savolga birinchi javobingiz saqlanadi\n"
                "2️⃣ Noto'g'ri javob berganingizda izoh ko'rsatiladi\n"
                "3️⃣ Izohni o'qib, tushunganingizdan keyin davom etasiz\n"
                "4️⃣ Ortga qaytish imkoni yo'q\n"
                "5️⃣ Testni istalgan vaqt to'xtatib, keyinroq davom ettirishingiz mumkin\n\n"
                "Tayyor bo'lsangiz, boshlash tugmasini bosing!"
            )
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton("🚀 Boshlaymiz", callback_data="st:understood")
            )
            await cb.message.answer(rules, reply_markup=kb)
            await StudentStates.Understanding.set()
            return await cb.answer()
        
        await cb.answer("Noma'lum tanlov")
    except Exception as e:
        log.error(f"Error in student_confirming_name: {e}")
        await cb.answer("Xatolik yuz berdi")

async def process_understanding(cb: types.CallbackQuery, state: FSMContext):
    """Start the test with improved error handling"""
    if (cb.data or "") != "st:understood":
        return await cb.answer("Noma'lum tanlov")
    
    try:
        s = await state.get_data()
        tid = s.get("active_test_id")
        if not tid:
            await state.finish()
            return await cb.answer("Sessiya topilmadi")
        
        test = read_test(tid)
        if not test or not test.get("questions"):
            await state.finish()
            return await cb.message.answer("Test topilmadi.")
        
        session_data = {
            "started_at": int(time.time()),
            "answers": {},
            "current_q": 1,
            "total_q": len(test.get("questions") or []),
            "wrong_attempts": {},
            "excluded_options": {},
            "student_name": s.get("student_name"),
            "active_test_id": tid,
        }
        
        await state.update_data(**session_data)
        await StudentStates.Answering.set()
        
        await _save_session(cb.from_user.id, tid, session_data)
        
        await cb.message.answer(f"Test boshlandi: <b>{test.get('test_name') or 'Test'}</b>\n\n")
        await _send_question(cb, test, 1)
        await cb.answer()
    except Exception as e:
        log.error(f"Error in process_understanding: {e}")
        await cb.answer("Xatolik yuz berdi")

async def on_answer(cb: types.CallbackQuery, state: FSMContext):
    """Handle answer selection with validation"""
    data = cb.data or ""
    if not data.startswith("ans:"):
        return
    
    parts = data.split(":")
    if len(parts) != 3:
        return await cb.answer("Noto'g'ri format")
    
    # Input validation
    valid, qidx = validate_question_index(parts[1])
    if not valid:
        return await cb.answer("Noto'g'ri savol raqami")
    
    opt = parts[2].upper()
    if opt not in ["A", "B", "C", "D"]:
        return await cb.answer("Noto'g'ri javob varianti")
    
    await _process_answer(cb, state, qidx, opt)

async def _process_answer(cb: types.CallbackQuery, state: FSMContext, qidx: int, opt: str):
    """
    Process answer with learning mode + robust HTML handling.
    - Sanitizes any explanation HTML to avoid Telegram parse errors
    - Stores sanitized reference in session
    - Falls back to plain text if HTML fails to send
    """
    try:
        s = await state.get_data()
        tid = s.get("active_test_id")
        if not tid:
            return await safe_callback_answer(cb, "Avval /start yuboring.", show_alert=True)

        test = read_test(tid)
        if not test or not test.get("questions"):
            await state.finish()
            return await safe_callback_answer(cb, "Test topilmadi yoki o'chirilgan.", show_alert=True)

        current_q = int(s.get("current_q", 1))
        total_q = int(s.get("total_q", len(test.get("questions") or [])))

        if qidx != current_q:
            return await safe_callback_answer(cb, "Bu savol uchun javob allaqachon tanlangan.", show_alert=True)

        answers: Dict[str, str] = s.get("answers", {})
        excluded_options: Dict[str, List[str]] = s.get("excluded_options", {})
        wrong_attempts: Dict[str, int] = s.get("wrong_attempts", {})

        correct_answers = test.get("answers") or {}
        correct_answer = correct_answers.get(str(qidx))

        refs = test.get("references") or {}
        reference_raw = refs.get(str(qidx), "Izoh mavjud emas")
        # 🔒 Sanitize reference to avoid "Can't parse entities" errors
        reference_sanitized = sanitize_html_for_telegram(reference_raw)

        q_key = str(qidx)
        if q_key not in excluded_options:
            excluded_options[q_key] = []
        if q_key not in answers:
            answers[q_key] = opt

        # ✅ Correct answer
        if opt == correct_answer:
            try:
                await cb.answer("✅ To'g'ri javob!")
            except Exception as e:
                if "Query is too old" not in str(e):
                    log.error(f"Callback answer error: {e}")

            if current_q < total_q:
                next_q = current_q + 1
                await state.update_data(
                    current_q=next_q,
                    answers=answers,
                    excluded_options=excluded_options,
                    waiting_understanding=False,
                    current_reference=None
                )
                await _save_session(cb.from_user.id, tid, await state.get_data())

                await cb.message.answer("── * 30")
                await _send_question(cb, test, next_q)
            else:
                await _finish_test(cb, state, test)
            return

        # ❌ Wrong answer
        if opt not in excluded_options[q_key]:
            excluded_options[q_key].append(opt)
        wrong_attempts[q_key] = wrong_attempts.get(q_key, 0) + 1

        await state.update_data(
            excluded_options=excluded_options,
            wrong_attempts=wrong_attempts,
            answers=answers,
            waiting_understanding=True,
            current_reference=reference_sanitized  # store sanitized
        )
        await _save_session(cb.from_user.id, tid, await state.get_data())

        try:
            await cb.answer("❌ Noto'g'ri javob")
        except Exception as e:
            if "Query is too old" not in str(e):
                log.error(f"Callback answer error: {e}")

        msg_html = (
            f"❌ <b>Noto'g'ri javob!</b>\n\n"
            f"📖 <b>Izoh:</b>\n{reference_sanitized}\n\n"
            f"Tushundingizmi?"
        )
        try:
            await cb.message.answer(msg_html, reply_markup=_create_understanding_keyboard())
        except Exception as send_err:
            # Final fallback: send as plain text (no HTML parsing)
            log.warning(f"HTML send failed, falling back to plain text: {send_err}")
            msg_plain = (
                "❌ Noto'g'ri javob!\n\n"
                "📖 Izoh:\n" + reference_raw + "\n\n"
                "Tushundingizmi?"
            )
            await cb.message.answer(
                msg_plain,
                reply_markup=_create_understanding_keyboard(),
                parse_mode=None
            )

    except Exception as e:
        log.error(f"Error in _process_answer: {e}", exc_info=True)
        try:
            await cb.message.answer("Xatolik yuz berdi. Iltimos /start yuboring.")
        except Exception as msg_error:
            log.error(f"Failed to send error message: {msg_error}")

async def process_understanding_response(cb: types.CallbackQuery, state: FSMContext):
    """Handle understanding confirmation - WITH IMPROVED CALLBACK HANDLING"""
    data = cb.data or ""
    
    if not data.startswith("understand:"):
        return
    
    response = data.split(":")[1]
    
    s = await state.get_data()
    
    if response == "no":
        reference = s.get("current_reference", "Izoh mavjud emas")
        reference = sanitize_html_for_telegram(reference)
        msg = (
            f"❌ <b>Noto'g'ri javob!</b>\n\n"
            f"📖 <b>Izoh:</b>\n{reference}\n\n"
            f"Tushundingizmi?"
        )
        await cb.message.answer(msg, reply_markup=_create_understanding_keyboard())
        
        # Safe callback answer
        try:
            await cb.answer("Qayta o'qing")
        except Exception as e:
            if "Query is too old" not in str(e):
                log.error(f"Callback answer error: {e}")
    
    elif response == "yes":
        # Safe callback answer
        try:
            await cb.answer("Davom etamiz")
        except Exception as e:
            if "Query is too old" not in str(e):
                log.error(f"Callback answer error: {e}")
        
        tid = s.get("active_test_id")
        test = read_test(tid)
        current_q = s.get("current_q", 1)
        excluded_options = s.get("excluded_options", {})
        q_key = str(current_q)
        
        excluded_for_q = excluded_options.get(q_key, [])
        
        if len(excluded_for_q) >= 3:
            await cb.message.answer(
                "⚠️ Ushbu savol uchun ko'p urinishlar bo'ldi. Keyingi savolga o'tamiz.\n"
                "To'g'ri javobni test oxirida ko'rasiz."
            )
            
            total_q = s.get("total_q", len(test.get("questions") or []))
            if current_q < total_q:
                next_q = current_q + 1
                await state.update_data(
                    current_q=next_q,
                    waiting_understanding=False
                )
                await _save_session(cb.from_user.id, tid, await state.get_data())
                await cb.message.answer("── * 30")
                await _send_question(cb, test, next_q)
            else:
                await _finish_test(cb, state, test)
        else:
            await state.update_data(waiting_understanding=False)
            await _save_session(cb.from_user.id, tid, await state.get_data())
            await cb.message.answer("🔄 Qayta urinib ko'ring:")
            await _send_question(cb, test, current_q, excluded_for_q)

async def process_start_choice(cb: types.CallbackQuery, state: FSMContext):
    """Handle continue/restart choice from old session format"""
    data = cb.data or ""
    
    try:
        if data == "st:cont":
            s = await state.get_data()
            tid = s.get("active_test_id")
            test = read_test(tid) if tid else None
            
            if not test or not test.get("questions"):
                await state.finish()
                await cb.message.answer("Sessiya topilmadi yoki test o'chirilgan.")
                return await cb.answer()
            
            await StudentStates.Answering.set()
            await cb.message.answer("Davom etamiz.")
            
            current_q = int(s.get("current_q", 1))
            excluded_options = s.get("excluded_options", {})
            q_key = str(current_q)
            excluded_for_q = excluded_options.get(q_key, [])
            
            await _send_question(cb, test, current_q, excluded_for_q)
            return await cb.answer()
        
        if data == "st:restart":
            await state.finish()
            await StudentStates.Choosing.set()
            
            tests = available_tests_for_user(cb.from_user.id)
            titles = load_group_titles()
            
            def _pretty_name(t):
                name = t.get("test_name") or "Test"
                for g in (t.get("groups") or []):
                    try:
                        title = titles.get(int(g))
                        if title:
                            return f"{name} — <i>{title}</i>"
                    except (ValueError, TypeError):
                        pass
                return name
            
            for t in tests:
                t["test_name"] = _pretty_name(t)
            
            if not tests:
                await cb.message.answer(
                    "Hozircha siz uchun faollashtirilgan testlar yo'q.\n"
                    "Guruh admini testni guruhingiz uchun faollashtirishi kerak."
                )
            else:
                keyboard = _create_tests_keyboard(tests)
                await cb.message.answer(
                    "<b>📚 Mavjud testlar:</b>\n"
                    "Testni boshlash uchun quyidagi tugmalardan birini bosing:",
                    reply_markup=keyboard
                )
            
            return await cb.answer()
        
        await cb.answer("Noma'lum tanlov")
    except Exception as e:
        log.error(f"Error in process_start_choice: {e}")
        await cb.answer("Xatolik yuz berdi")

async def receive_test_id(message: types.Message, state: FSMContext):
    """Deprecated - kept for compatibility"""
    await message.reply("Iltimos, yuqoridagi tugmalardan testni tanlang.")

# Cleanup function
async def cleanup_old_user_sessions(user_id: int, max_age_hours: int = 24) -> int:
    """Clean up old session files for a user"""
    cleaned = 0
    try:
        user_session_dir = get_user_session_dir(user_id)
        cutoff_time = time.time() - (max_age_hours * 3600)
        
        for session_file in user_session_dir.glob("*.json"):
            try:
                if session_file.stat().st_mtime < cutoff_time:
                    session_file.unlink()
                    cleaned += 1
            except Exception as e:
                log.warning(f"Error cleaning session file {session_file}: {e}")
        
        # Remove empty directory
        try:
            if not any(user_session_dir.iterdir()):
                user_session_dir.rmdir()
        except:
            pass
            
    except Exception as e:
        log.error(f"Error cleaning user {user_id} sessions: {e}")
    
    return cleaned

