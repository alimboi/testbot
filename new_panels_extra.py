"""
ADDITIONAL PANEL IMPLEMENTATIONS
These are the missing features that were showing "Coming soon"
"""

import logging
from aiogram import types
from datetime import datetime, timedelta
from typing import List, Dict
import io

from activity_tracker import (
    get_recent_attempts,
    get_student_attempts,
    get_test_attempts,
    get_student_statistics,
    get_recent_activity,
)

from utils import (
    is_owner,
    load_tests_index,
    load_group_titles,
    load_students,
)

from keyboards import back_kb

log = logging.getLogger("new_panels_extra")


# ==================================================================================
# ANALYTICS - TRENDS
# ==================================================================================

async def analytics_trends(cb: types.CallbackQuery):
    """Show performance trends over time"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    attempts = get_recent_attempts(limit=100)

    if not attempts:
        text = "📈 <b>TRENDS</b>\n\nNo data available yet."
        await cb.message.edit_text(text, reply_markup=back_kb("panel:analytics"))
        return await cb.answer()

    # Group by time periods
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    month_start = today_start - timedelta(days=30)

    today_attempts = []
    week_attempts = []
    month_attempts = []

    for attempt in attempts:
        timestamp = attempt.get("finished_at", attempt.get("timestamp", 0))
        attempt_date = datetime.fromtimestamp(timestamp)

        if attempt_date >= today_start:
            today_attempts.append(attempt)
        if attempt_date >= week_start:
            week_attempts.append(attempt)
        if attempt_date >= month_start:
            month_attempts.append(attempt)

    # Calculate stats
    def calc_avg(attempts_list):
        if not attempts_list:
            return 0
        return round(sum(a.get("percentage", 0) for a in attempts_list) / len(attempts_list), 1)

    today_avg = calc_avg(today_attempts)
    week_avg = calc_avg(week_attempts)
    month_avg = calc_avg(month_attempts)

    text = (
        "📈 <b>PERFORMANCE TRENDS</b>\n\n"
        f"<b>Today:</b>\n"
        f"  Attempts: {len(today_attempts)}\n"
        f"  Average: {today_avg}%\n\n"
        f"<b>Last 7 Days:</b>\n"
        f"  Attempts: {len(week_attempts)}\n"
        f"  Average: {week_avg}%\n\n"
        f"<b>Last 30 Days:</b>\n"
        f"  Attempts: {len(month_attempts)}\n"
        f"  Average: {month_avg}%\n\n"
    )

    # Trend indicator
    if week_avg > month_avg:
        text += "📈 <b>Trend:</b> Improving! ⬆️"
    elif week_avg < month_avg:
        text += "📉 <b>Trend:</b> Declining ⬇️"
    else:
        text += "➡️ <b>Trend:</b> Stable"

    await cb.message.edit_text(text, reply_markup=back_kb("panel:analytics"))
    await cb.answer()


# ==================================================================================
# ANALYTICS - LOW PERFORMERS
# ==================================================================================

async def analytics_low_performers(cb: types.CallbackQuery):
    """Show students who need help"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    students = load_students()

    if not students:
        text = "👥 No students found."
        await cb.message.edit_text(text, reply_markup=back_kb("panel:analytics"))
        return await cb.answer()

    lines = ["📉 <b>STUDENTS NEEDING HELP</b>\n"]

    # Get students with at least 2 attempts
    struggling_students = []
    for user_id, student_data in students.items():
        stats = get_student_statistics(int(user_id))
        if stats['total_attempts'] >= 2:  # At least 2 attempts
            # Students with avg score below 60% or pass rate below 50%
            if stats['average_score'] < 60 or stats['pass_rate'] < 50:
                struggling_students.append((
                    student_data.get('full_name', 'Unknown'),
                    stats
                ))

    # Sort by average score (lowest first)
    struggling_students.sort(key=lambda x: x[1]['average_score'])

    if not struggling_students:
        text = (
            "📉 <b>STUDENTS NEEDING HELP</b>\n\n"
            "✅ Great news! No students are currently struggling.\n\n"
            "All students with 2+ attempts have:\n"
            "• Average score ≥ 60%\n"
            "• Pass rate ≥ 50%"
        )
        await cb.message.edit_text(text, reply_markup=back_kb("panel:analytics"))
        return await cb.answer()

    for name, stats in struggling_students[:15]:  # Show up to 15
        indicator = "🚨" if stats['average_score'] < 40 else "⚠️"

        lines.append(
            f"{indicator} <b>{name[:25]}</b>\n"
            f"    Average: {stats['average_score']:.1f}% | "
            f"Tests: {stats['total_attempts']} | "
            f"Pass: {stats['pass_rate']:.1f}%\n"
        )

    lines.append("\n💡 <i>Tip: Reach out to these students for extra support</i>")

    text = "\n".join(lines)

    await cb.message.edit_text(text, reply_markup=back_kb("panel:analytics"))
    await cb.answer()


# ==================================================================================
# RESULTS - BY GROUP
# ==================================================================================

async def results_by_group(cb: types.CallbackQuery):
    """Show results filtered by group"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    from activity_tracker import get_group_attempts

    group_titles = load_group_titles()

    if not group_titles:
        text = "👥 No groups found in the system."
        await cb.message.edit_text(text, reply_markup=back_kb("panel:results"))
        return await cb.answer()

    # Build keyboard with group list
    kb = types.InlineKeyboardMarkup(row_width=1)

    for group_id, title in group_titles.items():
        # Count attempts for this group
        attempts = get_group_attempts(group_id)
        count = len(attempts)

        if count > 0:  # Only show groups with activity
            kb.add(types.InlineKeyboardButton(
                f"👥 {title[:35]} ({count} attempts)",
                callback_data=f"group_results:{group_id}"
            ))

    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="panel:results"))

    text = "👥 <b>SELECT GROUP</b>\n\nChoose a group to view its results:"
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


async def show_group_results(cb: types.CallbackQuery):
    """Show results for a specific group"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    # Extract group_id from callback_data (format: group_results:group_id)
    parts = cb.data.split(":")
    if len(parts) < 2:
        return await cb.answer("❌ Invalid group ID", show_alert=True)

    try:
        group_id = int(parts[1])
    except ValueError:
        return await cb.answer("❌ Invalid group ID", show_alert=True)

    from activity_tracker import get_group_attempts

    # Get group title
    group_titles = load_group_titles()
    group_title = group_titles.get(group_id, f"Group {group_id}")

    # Get all attempts for this group
    attempts = get_group_attempts(group_id, limit=20)

    if not attempts:
        text = f"📊 <b>{group_title}</b>\n\nNo test attempts yet."
        await cb.message.edit_text(text, reply_markup=back_kb("results:by_group"))
        return await cb.answer()

    # Calculate group statistics
    total = len(attempts)
    avg_score = sum(a.get("percentage", 0) for a in attempts) / total if total > 0 else 0
    passed = sum(1 for a in attempts if a.get("passed", False))
    pass_rate = (passed / total * 100) if total > 0 else 0

    lines = [
        f"📊 <b>{group_title}</b>\n",
        f"<b>Group Statistics:</b>",
        f"  Total Attempts: {total}",
        f"  Average Score: {avg_score:.1f}%",
        f"  Pass Rate: {pass_rate:.1f}%\n",
        f"<b>Recent Attempts:</b>\n"
    ]

    for i, attempt in enumerate(attempts[:15], 1):
        student_name = attempt.get("student_name", "Unknown")
        test_name = attempt.get("test_name", "Unknown")[:25]
        score = attempt.get("score", 0)
        total_q = attempt.get("total_questions", 0)
        pct = attempt.get("percentage", 0)
        passed_ind = "✅" if attempt.get("passed", False) else "❌"

        timestamp = attempt.get("finished_at", 0)
        date_str = datetime.fromtimestamp(timestamp).strftime("%m/%d")

        lines.append(
            f"{i}. {passed_ind} {student_name[:20]} | {test_name}\n"
            f"   {score}/{total_q} ({pct:.0f}%) - {date_str}"
        )

    text = "\n".join(lines)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        "📥 Export Group Results",
        callback_data=f"export_group:{group_id}"
    ))
    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="results:by_group"))

    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


async def export_group_csv(cb: types.CallbackQuery):
    """Export results for a specific group"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    # Extract group_id (format: export_group:group_id)
    parts = cb.data.split(":")
    if len(parts) < 2:
        return await cb.answer("❌ Invalid group ID", show_alert=True)

    try:
        group_id = int(parts[1])
    except ValueError:
        return await cb.answer("❌ Invalid group ID", show_alert=True)

    await cb.answer("📥 Generating CSV...")

    from activity_tracker import get_group_attempts, export_attempts_to_csv

    attempts = get_group_attempts(group_id)

    if not attempts:
        return await cb.message.answer("No results to export for this group.")

    group_titles = load_group_titles()
    group_name = group_titles.get(group_id, f"group_{group_id}")

    csv_content = export_attempts_to_csv(attempts)

    filename = f"{group_name[:20]}_{datetime.now().strftime('%Y%m%d')}.csv"
    file_obj = io.BytesIO(csv_content.encode('utf-8'))
    file_obj.name = filename

    await cb.message.answer_document(
        types.InputFile(file_obj, filename=filename),
        caption=f"📊 Results for: {group_name}\n\nTotal attempts: {len(attempts)}"
    )


# ==================================================================================
# ACTIVITY - STUDENT ACTIVITY
# ==================================================================================

async def activity_students(cb: types.CallbackQuery):
    """Show student-specific activity"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    logs = get_recent_activity(limit=100, action_filter="test_completed")

    if not logs:
        text = "🎓 <b>STUDENT ACTIVITY</b>\n\nNo test completions yet."
        await cb.message.edit_text(text, reply_markup=back_kb("panel:activity"))
        return await cb.answer()

    lines = ["🎓 <b>STUDENT ACTIVITY</b>\n", "<i>Recent test completions:</i>\n"]

    for i, log_entry in enumerate(logs[:20], 1):
        details = log_entry.get("details", {})
        timestamp = log_entry.get("timestamp", 0)
        date_str = datetime.fromtimestamp(timestamp).strftime("%m/%d %H:%M")

        test_name = details.get("test_name", "Unknown")[:30]
        score = details.get("score", "N/A")
        passed = "✅" if details.get("passed", False) else "❌"

        lines.append(f"{i}. {passed} {test_name}\n   Score: {score} - {date_str}\n")

    text = "\n".join(lines)

    await cb.message.edit_text(text, reply_markup=back_kb("panel:activity"))
    await cb.answer()


# ==================================================================================
# ACTIVITY - TEST ACTIVITY
# ==================================================================================

async def activity_tests(cb: types.CallbackQuery):
    """Show test-specific activity"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    logs = get_recent_activity(limit=100)

    # Filter for test-related actions
    test_actions = [
        l for l in logs
        if l.get("action") in ["test_created", "test_activated", "test_deactivated", "test_deleted"]
    ]

    if not test_actions:
        text = "🧪 <b>TEST ACTIVITY</b>\n\nNo test management activity yet."
        await cb.message.edit_text(text, reply_markup=back_kb("panel:activity"))
        return await cb.answer()

    lines = ["🧪 <b>TEST ACTIVITY</b>\n", "<i>Recent test management actions:</i>\n"]

    action_icons = {
        "test_created": "➕",
        "test_activated": "✅",
        "test_deactivated": "⏸",
        "test_deleted": "🗑"
    }

    for i, log_entry in enumerate(test_actions[:20], 1):
        action = log_entry.get("action", "unknown")
        details = log_entry.get("details", {})
        timestamp = log_entry.get("timestamp", 0)
        date_str = datetime.fromtimestamp(timestamp).strftime("%m/%d %H:%M")

        icon = action_icons.get(action, "•")
        action_name = action.replace("_", " ").replace("test ", "").title()
        test_name = details.get("test_name", "Unknown")[:30]

        lines.append(f"{i}. {icon} {action_name}: {test_name}\n   {date_str}\n")

    text = "\n".join(lines)

    await cb.message.edit_text(text, reply_markup=back_kb("panel:activity"))
    await cb.answer()


# ==================================================================================
# ACTIVITY - ADMIN ACTIVITY
# ==================================================================================

async def activity_admins(cb: types.CallbackQuery):
    """Show admin activity tracking"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    logs = get_recent_activity(limit=100)

    # Filter for admin actions
    admin_actions = [
        l for l in logs
        if l.get("action") in ["admin_added", "admin_removed", "group_added", "group_removed", "backup_created"]
    ]

    if not admin_actions:
        text = "👑 <b>ADMIN ACTIVITY</b>\n\nNo admin management activity yet."
        await cb.message.edit_text(text, reply_markup=back_kb("panel:activity"))
        return await cb.answer()

    lines = ["👑 <b>ADMIN ACTIVITY</b>\n", "<i>Recent admin actions:</i>\n"]

    action_icons = {
        "admin_added": "➕👑",
        "admin_removed": "➖👑",
        "group_added": "➕👥",
        "group_removed": "➖👥",
        "backup_created": "💾"
    }

    for i, log_entry in enumerate(admin_actions[:20], 1):
        action = log_entry.get("action", "unknown")
        timestamp = log_entry.get("timestamp", 0)
        date_str = datetime.fromtimestamp(timestamp).strftime("%m/%d %H:%M")

        icon = action_icons.get(action, "•")
        action_name = action.replace("_", " ").title()

        lines.append(f"{i}. {icon} {action_name}\n   {date_str}\n")

    text = "\n".join(lines)

    await cb.message.edit_text(text, reply_markup=back_kb("panel:activity"))
    await cb.answer()
