from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def owner_home_kb():
    """Main owner panel keyboard"""
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("👑 Admins", callback_data="panel:admins"),
        InlineKeyboardButton("👥 Groups", callback_data="panel:groups"),
    )
    kb.add(
        InlineKeyboardButton("🎓 Students", callback_data="panel:students"),
        InlineKeyboardButton("🧪 Tests", callback_data="panel:tests"),
    )
    kb.add(
        InlineKeyboardButton("🔄 Backup now", callback_data="panel:backup"),
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