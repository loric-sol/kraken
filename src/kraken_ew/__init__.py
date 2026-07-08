"""kraken_ew package.

Load environment variables from a project-root .env file on import, so that
secrets like MASSIVE_API_KEY are available to os.environ everywhere (data
clients, CLI, scheduled tasks) without each entry point loading it manually.
"""

from pathlib import Path

try:
    from dotenv import load_dotenv

    _ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(_ENV_PATH)
except Exception:
    # dotenv is optional; if unavailable, rely on the real environment.
    pass
