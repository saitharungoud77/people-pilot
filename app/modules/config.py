import os
from pathlib import Path


# ============================================================
# SECRETS / CONFIGURATION
# ============================================================
# API keys and other secrets live in a Streamlit secrets file
# instead of being hard-coded. Two locations are supported:
#
#   <project root>/.streamlit/secrets.toml   <- preferred
#   ~/.streamlit/secrets.toml                <- per-user fallback
#
# get_secret(name) resolves a value in this order:
#   1. the project secrets.toml
#   2. the user (~) secrets.toml
#   3. the OS environment variable of the same name
#
# So the file wins when present, and an environment variable
# still works as a fallback. Example secrets.toml:
#
#   OPENAI_API_KEY = "sk-proj-..."
#

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROJECT_SECRETS = PROJECT_ROOT / ".streamlit" / "secrets.toml"

USER_SECRETS = Path.home() / ".streamlit" / "secrets.toml"


def _load_toml(path):
    """Read a TOML file into a dict ({} when missing or invalid)."""

    if not path.exists():

        return {}

    try:

        import tomllib

    except ModuleNotFoundError:

        import tomli as tomllib

    try:

        with open(path, "rb") as handle:

            return tomllib.load(handle)

    except Exception:

        return {}


def get_secret(name, default=""):
    """Return a secret value, or default when it is not set anywhere."""

    for path in (PROJECT_SECRETS, USER_SECRETS):

        value = _load_toml(path).get(name)

        if value:

            return str(value).strip()

    value = os.environ.get(name)

    if value:

        return value.strip()

    return default


def has_secret(name):
    """True when a secret is set in a file or the environment."""

    return bool(get_secret(name))


def secrets_location():
    """Path where the project secret should be written."""

    return str(PROJECT_SECRETS)
