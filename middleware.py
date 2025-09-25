import logging
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.types import Update

logger = logging.getLogger("bot.audit")

class AuditMiddleware(BaseMiddleware):
    """Middleware for auditing user interactions with the bot"""
    
    async def on_pre_process_update(self, update: Update, data: dict):
        """Log incoming updates for audit purposes"""
        user = None
        update_type = "unknown"
        
        try:
            if update.message:
                user = update.message.from_user
                update_type = "message"
            elif update.callback_query:
                user = update.callback_query.from_user
                update_type = "callback"
            elif update.edited_message:
                user = update.edited_message.from_user
                update_type = "edit"
            elif update.my_chat_member:
                user = update.my_chat_member.from_user
                update_type = "membership"

            if user:
                username = f"@{user.username}" if user.username else "no_username"
                logger.info(
                    "Update [%s] from user %s (%s) - ID: %s",
                    update_type,
                    user.id,
                    username,
                    user.first_name or "no_name"
                )
            else:
                logger.info("Update [%s] with no user info", update_type)
                
        except Exception as e:
            logger.warning("Error in audit middleware: %s", e)

    async def on_post_process_update(self, update: Update, result, data: dict):
        """Log any errors that occurred during update processing"""
        if isinstance(result, Exception):
            logger.error("Update processing failed: %s", result)