"""
COMPREHENSIVE ACTIVITY TRACKING SYSTEM

This module tracks ALL student test attempts and activities.
Unlike the old system that only kept the last attempt, this stores complete history.

Features:
- Track every test attempt with full details
- Store activity logs for all actions
- Query by student, test, group, date range
- Calculate analytics and statistics
- Export data to CSV

Data Structure:
- data/activity/test_attempts.json - All test attempts
- data/activity/activity_logs.json - All system activities
- data/activity/student_history/ - Per-student history files
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging

log = logging.getLogger("activity_tracker")

# ==================================================================================
# DATA PATHS
# ==================================================================================

ACTIVITY_DIR = Path("data/activity")
TEST_ATTEMPTS_FILE = ACTIVITY_DIR / "test_attempts.json"
ACTIVITY_LOGS_FILE = ACTIVITY_DIR / "activity_logs.json"
STUDENT_HISTORY_DIR = ACTIVITY_DIR / "student_history"

# Ensure directories exist
ACTIVITY_DIR.mkdir(parents=True, exist_ok=True)
STUDENT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)


# ==================================================================================
# TEST ATTEMPT TRACKING
# ==================================================================================

def save_test_attempt(
    user_id: int,
    test_id: str,
    test_name: str,
    student_name: str,
    score: int,
    total_questions: int,
    percentage: float,
    answers: Dict[str, str],
    correct_answers: Dict[str, str],
    wrong_attempts: Dict[str, int],
    group_id: int = None,
    time_spent_seconds: int = None,
    started_at: float = None,
    finished_at: float = None
) -> str:
    """
    Save a complete test attempt record.

    Returns: attempt_id (unique identifier for this attempt)
    """
    attempt_id = f"{user_id}_{test_id}_{int(time.time())}"

    attempt_data = {
        "attempt_id": attempt_id,
        "user_id": user_id,
        "student_name": student_name,
        "test_id": test_id,
        "test_name": test_name,
        "group_id": group_id,
        "score": score,
        "total_questions": total_questions,
        "percentage": percentage,
        "passed": percentage >= 60,  # Configurable pass threshold
        "answers": answers,
        "correct_answers": correct_answers,
        "wrong_attempts": wrong_attempts,
        "time_spent_seconds": time_spent_seconds,
        "started_at": started_at or time.time(),
        "finished_at": finished_at or time.time(),
        "timestamp": time.time(),
    }

    # Save to master attempts file
    _append_to_attempts_file(attempt_data)

    # Save to student's personal history
    _save_to_student_history(user_id, attempt_data)

    # Log the activity
    log_activity(
        action="test_completed",
        user_id=user_id,
        details={
            "test_id": test_id,
            "test_name": test_name,
            "score": f"{score}/{total_questions}",
            "percentage": percentage,
            "passed": attempt_data["passed"]
        }
    )

    log.info(f"Saved test attempt: {attempt_id} - {student_name} - {test_name} - {score}/{total_questions}")

    return attempt_id


def _append_to_attempts_file(attempt_data: dict):
    """Append attempt to master file"""
    attempts = _load_attempts_file()
    attempts.append(attempt_data)

    # Keep only last 10000 attempts to prevent file bloat
    if len(attempts) > 10000:
        attempts = attempts[-10000:]

    _save_attempts_file(attempts)


def _save_to_student_history(user_id: int, attempt_data: dict):
    """Save to student's personal history file"""
    history_file = STUDENT_HISTORY_DIR / f"{user_id}.json"

    if history_file.exists():
        history = json.loads(history_file.read_text(encoding="utf-8"))
    else:
        history = {"user_id": user_id, "attempts": []}

    history["attempts"].append(attempt_data)
    history["last_updated"] = time.time()

    history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_attempts_file() -> List[dict]:
    """Load all test attempts"""
    if not TEST_ATTEMPTS_FILE.exists():
        return []

    try:
        return json.loads(TEST_ATTEMPTS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.error(f"Error loading attempts file: {e}")
        return []


def _save_attempts_file(attempts: List[dict]):
    """Save attempts file"""
    try:
        TEST_ATTEMPTS_FILE.write_text(
            json.dumps(attempts, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        log.error(f"Error saving attempts file: {e}")


# ==================================================================================
# ACTIVITY LOGGING
# ==================================================================================

def log_activity(action: str, user_id: int = None, details: dict = None):
    """
    Log any system activity

    Actions:
    - test_created, test_activated, test_deactivated, test_deleted
    - test_completed, test_started, test_resumed
    - admin_added, admin_removed
    - group_added, group_removed, group_synced
    - student_added, student_viewed
    - backup_created
    """
    activity = {
        "action": action,
        "user_id": user_id,
        "details": details or {},
        "timestamp": time.time(),
        "datetime": datetime.now().isoformat(),
    }

    logs = _load_activity_logs()
    logs.append(activity)

    # Keep only last 5000 logs
    if len(logs) > 5000:
        logs = logs[-5000:]

    _save_activity_logs(logs)


def _load_activity_logs() -> List[dict]:
    """Load activity logs"""
    if not ACTIVITY_LOGS_FILE.exists():
        return []

    try:
        return json.loads(ACTIVITY_LOGS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.error(f"Error loading activity logs: {e}")
        return []


def _save_activity_logs(logs: List[dict]):
    """Save activity logs"""
    try:
        ACTIVITY_LOGS_FILE.write_text(
            json.dumps(logs, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        log.error(f"Error saving activity logs: {e}")


# ==================================================================================
# QUERY FUNCTIONS
# ==================================================================================

def get_student_attempts(user_id: int, limit: int = None) -> List[dict]:
    """Get all attempts by a specific student"""
    history_file = STUDENT_HISTORY_DIR / f"{user_id}.json"

    if not history_file.exists():
        return []

    try:
        history = json.loads(history_file.read_text(encoding="utf-8"))
        attempts = history.get("attempts", [])

        # Sort by timestamp descending (most recent first)
        attempts.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

        if limit:
            attempts = attempts[:limit]

        return attempts
    except Exception as e:
        log.error(f"Error loading student history: {e}")
        return []


def get_test_attempts(test_id: str, limit: int = None) -> List[dict]:
    """Get all attempts for a specific test"""
    all_attempts = _load_attempts_file()

    test_attempts = [a for a in all_attempts if a.get("test_id") == test_id]
    test_attempts.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    if limit:
        test_attempts = test_attempts[:limit]

    return test_attempts


def get_recent_attempts(limit: int = 50) -> List[dict]:
    """Get most recent test attempts across all students"""
    all_attempts = _load_attempts_file()
    all_attempts.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return all_attempts[:limit]


def get_attempts_by_date_range(start_time: float, end_time: float) -> List[dict]:
    """Get attempts within a date range"""
    all_attempts = _load_attempts_file()
    return [
        a for a in all_attempts
        if start_time <= a.get("timestamp", 0) <= end_time
    ]


def get_group_attempts(group_id: int, limit: int = None) -> List[dict]:
    """Get all attempts from a specific group"""
    all_attempts = _load_attempts_file()

    group_attempts = [a for a in all_attempts if a.get("group_id") == group_id]
    group_attempts.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    if limit:
        group_attempts = group_attempts[:limit]

    return group_attempts


def get_recent_activity(limit: int = 50, action_filter: str = None) -> List[dict]:
    """Get recent activity logs"""
    logs = _load_activity_logs()

    if action_filter:
        logs = [l for l in logs if l.get("action") == action_filter]

    logs.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return logs[:limit]


# ==================================================================================
# ANALYTICS FUNCTIONS
# ==================================================================================

def get_student_statistics(user_id: int) -> dict:
    """Get comprehensive statistics for a student"""
    attempts = get_student_attempts(user_id)

    if not attempts:
        return {
            "total_attempts": 0,
            "total_tests": 0,
            "average_score": 0,
            "pass_rate": 0,
            "total_time_spent": 0,
        }

    total_attempts = len(attempts)
    unique_tests = len(set(a.get("test_id") for a in attempts))
    total_score = sum(a.get("percentage", 0) for a in attempts)
    passed_count = sum(1 for a in attempts if a.get("passed", False))
    total_time = sum(a.get("time_spent_seconds", 0) for a in attempts if a.get("time_spent_seconds"))

    return {
        "total_attempts": total_attempts,
        "total_tests": unique_tests,
        "average_score": round(total_score / total_attempts, 2) if total_attempts > 0 else 0,
        "pass_rate": round((passed_count / total_attempts) * 100, 2) if total_attempts > 0 else 0,
        "total_time_spent": total_time,
        "best_score": max((a.get("percentage", 0) for a in attempts), default=0),
        "worst_score": min((a.get("percentage", 0) for a in attempts), default=0),
        "recent_attempts": attempts[:5],  # Last 5 attempts
    }


def get_test_statistics(test_id: str) -> dict:
    """Get comprehensive statistics for a test"""
    attempts = get_test_attempts(test_id)

    if not attempts:
        return {
            "total_attempts": 0,
            "unique_students": 0,
            "average_score": 0,
            "pass_rate": 0,
            "completion_rate": 100,
        }

    total_attempts = len(attempts)
    unique_students = len(set(a.get("user_id") for a in attempts))
    total_score = sum(a.get("percentage", 0) for a in attempts)
    passed_count = sum(1 for a in attempts if a.get("passed", False))

    return {
        "total_attempts": total_attempts,
        "unique_students": unique_students,
        "average_score": round(total_score / total_attempts, 2) if total_attempts > 0 else 0,
        "pass_rate": round((passed_count / total_attempts) * 100, 2) if total_attempts > 0 else 0,
        "highest_score": max((a.get("percentage", 0) for a in attempts), default=0),
        "lowest_score": min((a.get("percentage", 0) for a in attempts), default=0),
        "recent_attempts": attempts[:10],  # Last 10 attempts
    }


def get_overall_statistics() -> dict:
    """Get overall system statistics"""
    all_attempts = _load_attempts_file()
    all_logs = _load_activity_logs()

    if not all_attempts:
        return {
            "total_attempts": 0,
            "total_students": 0,
            "total_tests": 0,
            "average_score": 0,
            "total_activities": len(all_logs),
        }

    unique_students = len(set(a.get("user_id") for a in all_attempts))
    unique_tests = len(set(a.get("test_id") for a in all_attempts))
    total_score = sum(a.get("percentage", 0) for a in all_attempts)
    passed_count = sum(1 for a in all_attempts if a.get("passed", False))

    # Get activity stats
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_timestamp = today.timestamp()

    attempts_today = sum(1 for a in all_attempts if a.get("timestamp", 0) >= today_timestamp)

    return {
        "total_attempts": len(all_attempts),
        "total_students": unique_students,
        "total_tests": unique_tests,
        "average_score": round(total_score / len(all_attempts), 2),
        "pass_rate": round((passed_count / len(all_attempts)) * 100, 2),
        "attempts_today": attempts_today,
        "total_activities": len(all_logs),
    }


# ==================================================================================
# CSV EXPORT FUNCTIONS
# ==================================================================================

def export_attempts_to_csv(attempts: List[dict]) -> str:
    """
    Export attempts to CSV format
    Returns: CSV string
    """
    if not attempts:
        return "No data to export"

    # CSV Header
    csv_lines = [
        "Student Name,Test Name,Score,Total Questions,Percentage,Passed,Date,Time Spent"
    ]

    for attempt in attempts:
        student_name = attempt.get("student_name", "Unknown")
        test_name = attempt.get("test_name", "Unknown")
        score = attempt.get("score", 0)
        total = attempt.get("total_questions", 0)
        percentage = attempt.get("percentage", 0)
        passed = "Yes" if attempt.get("passed", False) else "No"
        timestamp = attempt.get("finished_at", attempt.get("timestamp", 0))
        date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        time_spent = attempt.get("time_spent_seconds", 0)
        time_spent_min = round(time_spent / 60, 1) if time_spent else 0

        csv_lines.append(
            f'"{student_name}","{test_name}",{score},{total},{percentage:.2f},{passed},"{date_str}",{time_spent_min}'
        )

    return "\n".join(csv_lines)


def export_activity_logs_to_csv(logs: List[dict]) -> str:
    """Export activity logs to CSV format"""
    if not logs:
        return "No logs to export"

    csv_lines = ["Action,User ID,Details,DateTime"]

    for log_entry in logs:
        action = log_entry.get("action", "unknown")
        user_id = log_entry.get("user_id", "N/A")
        details = str(log_entry.get("details", {}))
        dt = log_entry.get("datetime", "N/A")

        csv_lines.append(f'"{action}",{user_id},"{details}","{dt}"')

    return "\n".join(csv_lines)
