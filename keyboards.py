from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def owner_home_kb():
    """
    ENHANCED Main owner panel keyboard with better organization
    """
    kb = InlineKeyboardMarkup(row_width=2)

    # Main Management Section
    kb.add(
        InlineKeyboardButton("👥 Groups", callback_data="panel:groups"),
        InlineKeyboardButton("🎓 Students", callback_data="panel:students"),
    )
    kb.add(
        InlineKeyboardButton("🧪 Tests", callback_data="panel:tests"),
        InlineKeyboardButton("👑 Admins", callback_data="panel:admins"),
    )

    # NEW: Monitoring & Analytics Section
    kb.add(
        InlineKeyboardButton("📊 Results", callback_data="panel:results"),
        InlineKeyboardButton("📈 Analytics", callback_data="panel:analytics"),
    )

    # NEW: Activity & Logs Section
    kb.add(
        InlineKeyboardButton("📋 Activity Logs", callback_data="panel:activity"),
        InlineKeyboardButton("💾 Backup", callback_data="panel:backup"),
    )

    return kb

def back_kb(to="panel:home"):
    """Simple back button keyboard"""
    return InlineKeyboardMarkup().add(
        InlineKeyboardButton("⬅️ Back", callback_data=to)
    )

def list_kb(items, prefix, back_to="panel:home"):
    """Generic list keyboard with items and back button"""
    kb = InlineKeyboardMarkup(row_width=1)
    for key, title in items:
        kb.add(InlineKeyboardButton(title, callback_data=f"{prefix}:{key}"))
    kb.add(InlineKeyboardButton("⬅️ Back", callback_data=back_to))
    return kb

def test_menu_kb(test_id, is_active):
    """Test management keyboard"""
    kb = InlineKeyboardMarkup(row_width=2)
    if is_active:
        kb.add(InlineKeyboardButton("⏸ Deactivate", callback_data=f"t:deact:{test_id}"))
    else:
        kb.add(InlineKeyboardButton("▶️ Activate", callback_data=f"t:act:{test_id}"))
    kb.add(
        InlineKeyboardButton("🗑 Delete", callback_data=f"t:del:{test_id}"),
        InlineKeyboardButton("⬅️ Back", callback_data="panel:tests")
    )
    return kb

def question_kb(qidx):
    """Create keyboard for question answers"""
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("A", callback_data=f"ans:{qidx}:A"),
        InlineKeyboardButton("B", callback_data=f"ans:{qidx}:B")
    )
    kb.add(
        InlineKeyboardButton("C", callback_data=f"ans:{qidx}:C"),
        InlineKeyboardButton("D", callback_data=f"ans:{qidx}:D")
    )
    return kb


# ==================================================================================
# NEW ENHANCED KEYBOARDS FOR IMPROVED FUNCTIONALITY
# ==================================================================================

def admin_home_kb(is_owner=False):
    """
    Enhanced admin panel keyboard
    - Owners get full access
    - Group admins get limited access
    """
    kb = InlineKeyboardMarkup(row_width=2)

    kb.add(
        InlineKeyboardButton("📚 My Tests", callback_data="admin:tests"),
        InlineKeyboardButton("👥 My Groups", callback_data="admin:groups"),
    )
    kb.add(
        InlineKeyboardButton("➕ New Test", callback_data="admin:new_test"),
        InlineKeyboardButton("📊 Statistics", callback_data="admin:stats"),
    )

    if is_owner:
        kb.add(
            InlineKeyboardButton("📊 View Results", callback_data="admin:results"),
            InlineKeyboardButton("📈 Analytics", callback_data="admin:analytics"),
        )

    return kb


def results_panel_kb():
    """Keyboard for Results Panel with filters"""
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📋 All Results", callback_data="results:all"),
        InlineKeyboardButton("🔍 By Test", callback_data="results:by_test"),
    )
    kb.add(
        InlineKeyboardButton("👤 By Student", callback_data="results:by_student"),
        InlineKeyboardButton("👥 By Group", callback_data="results:by_group"),
    )
    kb.add(
        InlineKeyboardButton("📥 Export CSV", callback_data="results:export"),
    )
    kb.add(
        InlineKeyboardButton("⬅️ Back", callback_data="panel:home"),
    )
    return kb


def analytics_panel_kb():
    """Keyboard for Analytics Dashboard"""
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📊 Overview", callback_data="analytics:overview"),
        InlineKeyboardButton("🧪 Test Stats", callback_data="analytics:tests"),
    )
    kb.add(
        InlineKeyboardButton("👥 Student Stats", callback_data="analytics:students"),
        InlineKeyboardButton("📈 Trends", callback_data="analytics:trends"),
    )
    kb.add(
        InlineKeyboardButton("🎯 Top Performers", callback_data="analytics:top"),
        InlineKeyboardButton("📉 Low Performers", callback_data="analytics:low"),
    )
    kb.add(
        InlineKeyboardButton("⬅️ Back", callback_data="panel:home"),
    )
    return kb


def activity_logs_kb():
    """Keyboard for Activity Logs Panel"""
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📋 Recent Activity", callback_data="activity:recent"),
        InlineKeyboardButton("🎓 Student Activity", callback_data="activity:students"),
    )
    kb.add(
        InlineKeyboardButton("🧪 Test Activity", callback_data="activity:tests"),
        InlineKeyboardButton("👑 Admin Activity", callback_data="activity:admins"),
    )
    kb.add(
        InlineKeyboardButton("📥 Export Logs", callback_data="activity:export"),
    )
    kb.add(
        InlineKeyboardButton("⬅️ Back", callback_data="panel:home"),
    )
    return kb


def student_profile_kb(student_id, back_to="panel:students"):
    """Keyboard for individual student profile view"""
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📊 All Tests", callback_data=f"student:{student_id}:tests"),
        InlineKeyboardButton("📈 Statistics", callback_data=f"student:{student_id}:stats"),
    )
    kb.add(
        InlineKeyboardButton("📥 Export History", callback_data=f"student:{student_id}:export"),
    )
    kb.add(
        InlineKeyboardButton("⬅️ Back", callback_data=back_to),
    )
    return kb


def test_details_kb(test_id, back_to="panel:tests"):
    """Enhanced test details keyboard with analytics"""
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("👁️ Preview", callback_data=f"test:{test_id}:preview"),
        InlineKeyboardButton("📊 Results", callback_data=f"test:{test_id}:results"),
    )
    kb.add(
        InlineKeyboardButton("📈 Analytics", callback_data=f"test:{test_id}:analytics"),
        InlineKeyboardButton("⚙️ Manage", callback_data=f"test:{test_id}:manage"),
    )
    kb.add(
        InlineKeyboardButton("⬅️ Back", callback_data=back_to),
    )
    return kb


def pagination_kb(current_page, total_pages, callback_prefix, back_to="panel:home"):
    """Generic pagination keyboard"""
    kb = InlineKeyboardMarkup(row_width=3)

    buttons = []
    if current_page > 1:
        buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{callback_prefix}:page:{current_page-1}"))

    buttons.append(InlineKeyboardButton(f"{current_page}/{total_pages}", callback_data="noop"))

    if current_page < total_pages:
        buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"{callback_prefix}:page:{current_page+1}"))

    kb.add(*buttons)
    kb.add(InlineKeyboardButton("⬅️ Back", callback_data=back_to))

    return kb