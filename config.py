import os

base_dir = os.path.dirname(os.path.abspath(__file__))


class BaseConfig(object):
    """Base configuration."""

    BOT_TOKEN = os.environ.get("BOT_TOKEN", "Unknown bot token")
    CHAT_ID = os.environ.get("CHAT_ID", "Unknown chat ID")

    TZ = os.environ.get("TZ", "Unknown time zone")
    JSON_PATH = os.environ.get("JSON_PATH", "Unknown json path")

    POSTGRES_USER = os.environ.get("POSTGRES_USER", "Unknown postgres user")
    POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "Unknown postgres password")
    POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "Unknown postgres host")
    POSTGRES_DB = os.environ.get("POSTGRES_DB", "Unknown postgres db")

    POSTGRES_URL=f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}/{POSTGRES_DB}"
