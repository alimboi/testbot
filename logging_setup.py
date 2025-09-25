import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

def setup_logging(log_dir: str = "logs", level: str = "INFO"):
    """Setup comprehensive logging for the bot"""
    # Ensure log directory exists
    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Warning: Could not create log directory {log_dir}: {e}", file=sys.stderr)
        log_dir = "."

    # Create formatter
    fmt = logging.Formatter(
        '%(asctime)s %(levelname)s %(name)s: %(message)s',
        '%Y-%m-%d %H:%M:%S'
    )

    # Clear existing handlers
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()

    # Set log level
    try:
        log_level = getattr(logging, level.upper(), logging.INFO)
    except AttributeError:
        log_level = logging.INFO

    root.setLevel(log_level)

    # Setup console handler
    try:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(fmt)
        console_handler.setLevel(log_level)
        root.addHandler(console_handler)
    except Exception as e:
        print(f"Warning: Could not setup console logging: {e}", file=sys.stderr)

    # Setup file handler
    try:
        log_file = os.path.join(log_dir, "bot.log")
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5*1024*1024,  # 5MB
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(log_level)
        root.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Could not setup file logging: {e}", file=sys.stderr)

    # Reduce noise from external libraries
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)