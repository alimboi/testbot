"""
NEW COMPREHENSIVE ADMIN PANELS

This module contains all the new admin panels for enhanced functionality:
- Results Viewing Panel (view all student results with filters)
- Analytics Dashboard (comprehensive statistics and trends)
- Activity Logs Panel (audit trail of all actions)
- Student Profile View (complete history per student)
- Test Analytics (detailed test performance metrics)

These panels provide admins/owners with complete visibility and control.
"""

import logging
from aiogram import types
from aiogram.dispatcher import FSMContext
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pathlib import Path
import csv
import io

from activity_tracker import (
    get_recent_attempts,
    get_student_attempts,
    get_test_attempts,
    get_group_attempts,
    get_student_statistics,
    get_test_statistics,
    get_overall_statistics,
    get_recent_activity,
    export_attempts_to_csv,
    export_activity_logs_to_csv,
)

from utils import (
    is_owner,
    load_tests_index,
    load_group_titles,
    read_test,
    load_students,
)

from keyboards import (
    results_panel_kb,
    analytics_panel_kb,
    activity_logs_kb,
    student_profile_kb,
    test_details_kb,
    pagination_kb,
    back_kb,
)

log = logging.getLogger("new_panels")

# ==================================================================================
# RESULTS PANEL HANDLERS
# ==================================================================================

async def panel_results(cb: types.CallbackQuery):
    """Main Results Panel - Show all student test results"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    text = (
        "📊 <b>RESULTS PANEL</b>\n\n"
        "View and analyze student test results.\n"
        "Select an option below:"
    )

    await cb.message.edit_text(text, reply_markup=results_panel_kb())
    await cb.answer()


async def results_all(cb: types.CallbackQuery):
    """Show all recent test results"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    attempts = get_recent_attempts(limit=20)

    if not attempts:
        text = "📋 <b>Recent Results</b>\n\nNo test results found."
        await cb.message.edit_text(text, reply_markup=back_kb("panel:results"))
        return await cb.answer()

    # Build results text
    lines = ["📋 <b>RECENT TEST RESULTS</b> (Last 20)\n"]

    for i, attempt in enumerate(attempts, 1):
        student_name = attempt.get("student_name", "Unknown")
        test_name = attempt.get("test_name", "Unknown")[:30]
        score = attempt.get("score", 0)
        total = attempt.get("total_questions", 0)
        pct = attempt.get("percentage", 0)
        passed = "✅" if attempt.get("passed", False) else "❌"

        timestamp = attempt.get("finished_at", 0)
        date_str = datetime.fromtimestamp(timestamp).strftime("%m/%d %H:%M")

        lines.append(
            f"{i}. {passed} <b>{student_name}</b>\n"
            f"   Test: {test_name}\n"
            f"   Score: {score}/{total} ({pct:.1f}%)\n"
            f"   Date: {date_str}\n"
        )

    text = "\n".join(lines)

    kb = back_kb("panel:results")
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


async def results_by_test(cb: types.CallbackQuery):
    """Show list of tests to view results for"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    tests = load_tests_index()

    if not tests:
        text = "🧪 No tests found in the system."
        await cb.message.edit_text(text, reply_markup=back_kb("panel:results"))
        return await cb.answer()

    # Build keyboard with test list
    kb = types.InlineKeyboardMarkup(row_width=1)

    for test_id, test_data in tests.items():
        test_name = test_data.get("test_name", "Unknown")[:40]

        # Count attempts for this test
        attempts = get_test_attempts(test_id)
        count = len(attempts)

        kb.add(types.InlineKeyboardButton(
            f"🧪 {test_name} ({count} attempts)",
            callback_data=f"test_results:{test_id}"
        ))

    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="panel:results"))

    text = "🧪 <b>SELECT TEST</b>\n\nChoose a test to view its results:"
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


async def show_test_results(cb: types.CallbackQuery):
    """Show results for a specific test"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    # Extract test_id from callback_data (format: test_results:test_id)
    parts = cb.data.split(":")
    if len(parts) < 2:
        return await cb.answer("❌ Invalid test ID", show_alert=True)

    test_id = parts[1]

    # Get test info
    test = read_test(test_id)
    if not test:
        return await cb.answer("❌ Test not found", show_alert=True)

    # Get all attempts for this test
    attempts = get_test_attempts(test_id, limit=15)

    if not attempts:
        text = f"📊 <b>{test.get('test_name', 'Test')}</b>\n\nNo results yet."
        await cb.message.edit_text(text, reply_markup=back_kb("results:by_test"))
        return await cb.answer()

    # Get test statistics
    stats = get_test_statistics(test_id)

    # Build results text
    lines = [
        f"📊 <b>{test.get('test_name', 'Test')}</b>\n",
        f"📈 <b>Statistics:</b>",
        f"   Total Attempts: {stats['total_attempts']}",
        f"   Unique Students: {stats['unique_students']}",
        f"   Average Score: {stats['average_score']:.1f}%",
        f"   Pass Rate: {stats['pass_rate']:.1f}%",
        f"   Highest: {stats['highest_score']:.1f}%",
        f"   Lowest: {stats['lowest_score']:.1f}%\n",
        f"<b>Recent Results:</b>\n"
    ]

    for i, attempt in enumerate(attempts, 1):
        student_name = attempt.get("student_name", "Unknown")
        score = attempt.get("score", 0)
        total = attempt.get("total_questions", 0)
        pct = attempt.get("percentage", 0)
        passed = "✅" if attempt.get("passed", False) else "❌"

        timestamp = attempt.get("finished_at", 0)
        date_str = datetime.fromtimestamp(timestamp).strftime("%m/%d %H:%M")

        lines.append(
            f"{i}. {passed} {student_name}: {score}/{total} ({pct:.1f}%) - {date_str}"
        )

    text = "\n".join(lines)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        "📥 Export to CSV",
        callback_data=f"export_test:{test_id}"
    ))
    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="results:by_test"))

    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


async def results_by_student(cb: types.CallbackQuery):
    """Show list of students to view their results"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    # Get all students
    students = load_students()

    if not students:
        text = "👥 No students found in the system."
        await cb.message.edit_text(text, reply_markup=back_kb("panel:results"))
        return await cb.answer()

    # Build keyboard with student list
    kb = types.InlineKeyboardMarkup(row_width=1)

    for user_id, student_data in students.items():
        student_name = student_data.get("full_name", "Unknown")[:35]

        # Count attempts for this student
        attempts = get_student_attempts(int(user_id))
        count = len(attempts)

        if count > 0:  # Only show students with attempts
            kb.add(types.InlineKeyboardButton(
                f"👤 {student_name} ({count} attempts)",
                callback_data=f"student_results:{user_id}"
            ))

    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="panel:results"))

    text = "👤 <b>SELECT STUDENT</b>\n\nChoose a student to view their complete history:"
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


async def show_student_results(cb: types.CallbackQuery):
    """Show all results for a specific student"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    # Extract user_id from callback_data (format: student_results:user_id)
    parts = cb.data.split(":")
    if len(parts) < 2:
        return await cb.answer("❌ Invalid student ID", show_alert=True)

    user_id = int(parts[1])

    # Get student attempts
    attempts = get_student_attempts(user_id, limit=10)

    if not attempts:
        text = "📊 <b>Student Results</b>\n\nNo test attempts found."
        await cb.message.edit_text(text, reply_markup=back_kb("results:by_student"))
        return await cb.answer()

    # Get student statistics
    stats = get_student_statistics(user_id)
    student_name = attempts[0].get("student_name", "Unknown") if attempts else "Unknown"

    # Build results text
    lines = [
        f"👤 <b>{student_name}</b>\n",
        f"📈 <b>Overall Statistics:</b>",
        f"   Total Attempts: {stats['total_attempts']}",
        f"   Tests Taken: {stats['total_tests']}",
        f"   Average Score: {stats['average_score']:.1f}%",
        f"   Pass Rate: {stats['pass_rate']:.1f}%",
        f"   Best Score: {stats['best_score']:.1f}%\n",
        f"<b>Recent Tests:</b>\n"
    ]

    for i, attempt in enumerate(attempts, 1):
        test_name = attempt.get("test_name", "Unknown")[:30]
        score = attempt.get("score", 0)
        total = attempt.get("total_questions", 0)
        pct = attempt.get("percentage", 0)
        passed = "✅" if attempt.get("passed", False) else "❌"

        timestamp = attempt.get("finished_at", 0)
        date_str = datetime.fromtimestamp(timestamp).strftime("%m/%d %H:%M")

        lines.append(
            f"{i}. {passed} {test_name}\n"
            f"   Score: {score}/{total} ({pct:.1f}%) - {date_str}"
        )

    text = "\n".join(lines)

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        "📥 Export History",
        callback_data=f"export_student:{user_id}"
    ))
    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="results:by_student"))

    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


async def export_results_csv(cb: types.CallbackQuery):
    """Export all results to CSV"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    await cb.answer("📥 Generating CSV export...")

    # Get recent attempts
    attempts = get_recent_attempts(limit=1000)

    if not attempts:
        return await cb.message.answer("No results to export.")

    # Generate CSV
    csv_content = export_attempts_to_csv(attempts)

    # Create file
    filename = f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    file_obj = io.BytesIO(csv_content.encode('utf-8'))
    file_obj.name = filename

    # Send file
    await cb.message.answer_document(
        types.InputFile(file_obj, filename=filename),
        caption=f"📊 Test Results Export\n\nTotal attempts: {len(attempts)}"
    )

    log.info(f"Exported {len(attempts)} results to CSV for user {cb.from_user.id}")


async def export_test_csv(cb: types.CallbackQuery):
    """Export results for a specific test"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    # Extract test_id (format: export_test:test_id)
    parts = cb.data.split(":")
    if len(parts) < 2:
        return await cb.answer("❌ Invalid test ID", show_alert=True)

    test_id = parts[1]

    await cb.answer("📥 Generating CSV...")

    attempts = get_test_attempts(test_id)

    if not attempts:
        return await cb.message.answer("No results to export for this test.")

    test = read_test(test_id)
    test_name = test.get('test_name', 'test') if test else 'test'

    csv_content = export_attempts_to_csv(attempts)

    filename = f"{test_name[:20]}_{datetime.now().strftime('%Y%m%d')}.csv"
    file_obj = io.BytesIO(csv_content.encode('utf-8'))
    file_obj.name = filename

    await cb.message.answer_document(
        types.InputFile(file_obj, filename=filename),
        caption=f"📊 Results for: {test_name}\n\nTotal attempts: {len(attempts)}"
    )


async def export_student_csv(cb: types.CallbackQuery):
    """Export history for a specific student"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    # Extract user_id (format: export_student:user_id)
    parts = cb.data.split(":")
    if len(parts) < 2:
        return await cb.answer("❌ Invalid student ID", show_alert=True)

    user_id = int(parts[1])

    await cb.answer("📥 Generating CSV...")

    attempts = get_student_attempts(user_id)

    if not attempts:
        return await cb.message.answer("No history to export for this student.")

    student_name = attempts[0].get("student_name", "student") if attempts else "student"

    csv_content = export_attempts_to_csv(attempts)

    filename = f"{student_name[:20]}_{datetime.now().strftime('%Y%m%d')}.csv"
    file_obj = io.BytesIO(csv_content.encode('utf-8'))
    file_obj.name = filename

    await cb.message.answer_document(
        types.InputFile(file_obj, filename=filename),
        caption=f"📊 History for: {student_name}\n\nTotal attempts: {len(attempts)}"
    )


# ==================================================================================
# ANALYTICS DASHBOARD HANDLERS
# ==================================================================================

async def panel_analytics(cb: types.CallbackQuery):
    """Main Analytics Dashboard"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    text = (
        "📈 <b>ANALYTICS DASHBOARD</b>\n\n"
        "Comprehensive analytics and insights.\n"
        "Select an option below:"
    )

    await cb.message.edit_text(text, reply_markup=analytics_panel_kb())
    await cb.answer()


async def analytics_overview(cb: types.CallbackQuery):
    """Show overall system analytics"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    stats = get_overall_statistics()

    # Get recent activity counts
    logs = get_recent_activity(limit=100)
    test_completed_today = sum(1 for l in logs if l.get("action") == "test_completed")

    text = (
        "📊 <b>SYSTEM OVERVIEW</b>\n\n"
        f"<b>Overall Statistics:</b>\n"
        f"📝 Total Test Attempts: {stats['total_attempts']}\n"
        f"👥 Total Students: {stats['total_students']}\n"
        f"🧪 Total Tests: {stats['total_tests']}\n"
        f"📈 Average Score: {stats['average_score']:.1f}%\n"
        f"✅ Pass Rate: {stats['pass_rate']:.1f}%\n\n"
        f"<b>Today's Activity:</b>\n"
        f"📝 Tests Completed: {stats['attempts_today']}\n"
        f"🔔 Total Activities: {stats['total_activities']}\n"
    )

    await cb.message.edit_text(text, reply_markup=back_kb("panel:analytics"))
    await cb.answer()


async def analytics_tests(cb: types.CallbackQuery):
    """Show analytics for all tests"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    tests = load_tests_index()

    if not tests:
        text = "🧪 No tests found in the system."
        await cb.message.edit_text(text, reply_markup=back_kb("panel:analytics"))
        return await cb.answer()

    lines = ["🧪 <b>TEST ANALYTICS</b>\n"]

    # Calculate stats for each test
    test_stats = []
    for test_id, test_data in tests.items():
        stats = get_test_statistics(test_id)
        if stats['total_attempts'] > 0:
            test_stats.append((test_data.get('test_name', 'Unknown'), stats))

    # Sort by total attempts (most popular first)
    test_stats.sort(key=lambda x: x[1]['total_attempts'], reverse=True)

    for test_name, stats in test_stats[:10]:  # Show top 10
        lines.append(
            f"<b>{test_name[:30]}</b>\n"
            f"  Attempts: {stats['total_attempts']} | "
            f"Avg: {stats['average_score']:.1f}% | "
            f"Pass: {stats['pass_rate']:.1f}%\n"
        )

    text = "\n".join(lines)

    await cb.message.edit_text(text, reply_markup=back_kb("panel:analytics"))
    await cb.answer()


async def analytics_students(cb: types.CallbackQuery):
    """Show analytics for all students"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    students = load_students()

    if not students:
        text = "👥 No students found."
        await cb.message.edit_text(text, reply_markup=back_kb("panel:analytics"))
        return await cb.answer()

    lines = ["👥 <b>STUDENT ANALYTICS</b>\n"]

    # Calculate stats for active students
    student_stats = []
    for user_id, student_data in students.items():
        stats = get_student_statistics(int(user_id))
        if stats['total_attempts'] > 0:
            student_stats.append((
                student_data.get('full_name', 'Unknown'),
                stats
            ))

    # Sort by average score (best first)
    student_stats.sort(key=lambda x: x[1]['average_score'], reverse=True)

    for name, stats in student_stats[:15]:  # Show top 15
        lines.append(
            f"<b>{name[:25]}</b>\n"
            f"  Tests: {stats['total_attempts']} | "
            f"Avg: {stats['average_score']:.1f}% | "
            f"Pass: {stats['pass_rate']:.1f}%\n"
        )

    text = "\n".join(lines)

    await cb.message.edit_text(text, reply_markup=back_kb("panel:analytics"))
    await cb.answer()


async def analytics_top_performers(cb: types.CallbackQuery):
    """Show top performing students"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    students = load_students()

    if not students:
        text = "👥 No students found."
        await cb.message.edit_text(text, reply_markup=back_kb("panel:analytics"))
        return await cb.answer()

    lines = ["🎯 <b>TOP PERFORMERS</b>\n"]

    # Get students with at least 3 attempts
    qualified_students = []
    for user_id, student_data in students.items():
        stats = get_student_statistics(int(user_id))
        if stats['total_attempts'] >= 3:  # At least 3 attempts to qualify
            qualified_students.append((
                student_data.get('full_name', 'Unknown'),
                stats
            ))

    # Sort by average score
    qualified_students.sort(key=lambda x: x[1]['average_score'], reverse=True)

    if not qualified_students:
        text = "🎯 No qualified students yet.\n\n(Students need at least 3 test attempts)"
        await cb.message.edit_text(text, reply_markup=back_kb("panel:analytics"))
        return await cb.answer()

    for rank, (name, stats) in enumerate(qualified_students[:10], 1):
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"{rank}."

        lines.append(
            f"{medal} <b>{name[:25]}</b>\n"
            f"    Average: {stats['average_score']:.1f}% | "
            f"Tests: {stats['total_attempts']} | "
            f"Pass Rate: {stats['pass_rate']:.1f}%\n"
        )

    text = "\n".join(lines)

    await cb.message.edit_text(text, reply_markup=back_kb("panel:analytics"))
    await cb.answer()


# ==================================================================================
# ACTIVITY LOGS HANDLERS
# ==================================================================================

async def panel_activity(cb: types.CallbackQuery):
    """Main Activity Logs Panel"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    text = (
        "📋 <b>ACTIVITY LOGS</b>\n\n"
        "View system activity and audit trail.\n"
        "Select an option below:"
    )

    await cb.message.edit_text(text, reply_markup=activity_logs_kb())
    await cb.answer()


async def activity_recent(cb: types.CallbackQuery):
    """Show recent system activity"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    logs = get_recent_activity(limit=20)

    if not logs:
        text = "📋 No recent activity."
        await cb.message.edit_text(text, reply_markup=back_kb("panel:activity"))
        return await cb.answer()

    lines = ["📋 <b>RECENT ACTIVITY</b> (Last 20)\n"]

    for log_entry in logs:
        action = log_entry.get("action", "unknown")
        timestamp = log_entry.get("timestamp", 0)
        date_str = datetime.fromtimestamp(timestamp).strftime("%m/%d %H:%M")

        # Format action nicely
        action_display = action.replace("_", " ").title()

        details = log_entry.get("details", {})
        detail_str = ""
        if details:
            # Show key details
            if "test_name" in details:
                detail_str = f" - {details['test_name'][:25]}"
            elif "score" in details:
                detail_str = f" - Score: {details['score']}"

        lines.append(f"• {action_display}{detail_str}\n  {date_str}\n")

    text = "\n".join(lines)

    await cb.message.edit_text(text, reply_markup=back_kb("panel:activity"))
    await cb.answer()


async def activity_export(cb: types.CallbackQuery):
    """Export activity logs to CSV"""
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Access denied", show_alert=True)

    await cb.answer("📥 Generating activity log export...")

    logs = get_recent_activity(limit=1000)

    if not logs:
        return await cb.message.answer("No activity logs to export.")

    csv_content = export_activity_logs_to_csv(logs)

    filename = f"activity_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    file_obj = io.BytesIO(csv_content.encode('utf-8'))
    file_obj.name = filename

    await cb.message.answer_document(
        types.InputFile(file_obj, filename=filename),
        caption=f"📋 Activity Logs Export\n\nTotal entries: {len(logs)}"
    )

    log.info(f"Exported {len(logs)} activity logs for user {cb.from_user.id}")
