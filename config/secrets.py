"""
config/secrets.py
-----------------
Centralized credential loader.

Priority order:
  1. AWS Secrets Manager  (if AWS_SECRET_NAME is set and reachable)
  2. .env file            (fallback via python-dotenv)

All other modules should import credentials from here instead of
reading os.environ directly.

Usage:
    from config.secrets import get_secret

    db_host     = get_secret("DB_HOST")
    aws_profile = get_secret("AWS_PROFILE")
"""

import os
import json
import logging
from functools import lru_cache
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Load .env as the baseline (values already in os.environ take priority)
# ---------------------------------------------------------------------------
# Try config/.env first, then root .env
_env_paths = [
    os.path.join(os.path.dirname(__file__), ".env"),          # config/.env
    os.path.join(os.path.dirname(__file__), "..", ".env"),     # root .env
]
for _path in _env_paths:
    if os.path.exists(_path):
        load_dotenv(dotenv_path=_path, override=True)   # .env values override stale env/SSO
        logger.debug(f"Loaded .env from {_path}")
        break


# ---------------------------------------------------------------------------
# 2. Attempt to pull secrets from AWS Secrets Manager
# ---------------------------------------------------------------------------
_secrets_cache: dict = {}
_secrets_loaded: bool = False


def _load_from_secrets_manager() -> dict:
    """
    Fetch all key-value pairs from AWS Secrets Manager.
    Returns an empty dict if unavailable or not configured.

    The secret is expected to be a JSON object, e.g.:
    {
        "AWS_PROFILE":        "my-sso-profile",
        "AWS_REGION":         "us-east-1",
        "BEDROCK_MODEL_ID":   "us.anthropic.claude-sonnet-4-5-20250514-v1:0",
        "DB_HOST":            "mydb.region.rds.amazonaws.com",
        "DB_PORT":            "5432",
        "DB_NAME":            "aws_pricing",
        "DB_USER":            "postgres",
        "DB_PASSWORD":        "s3cr3t",
        "ENABLE_CALCULATOR_LINKS": "true"
    }

    Set AWS_SECRET_NAME in your environment or .env to enable this.
    Optionally set AWS_SECRET_REGION (defaults to AWS_REGION or us-east-1).
    """
    secret_name = os.environ.get("AWS_SECRET_NAME", "cloud-migration-app/credentials")
    if not secret_name:
        logger.debug("AWS_SECRET_NAME not set — skipping Secrets Manager.")
        return {}

    region = (
        os.environ.get("AWS_SECRET_REGION")
        or os.environ.get("AWS_REGION")
        or "us-east-1"
    )

    try:
        import boto3

        # At this point .env is already loaded into os.environ (step 1 above).
        # Build a session using the same priority: profile → keys → default chain.
        profile       = os.environ.get("AWS_PROFILE", "").strip()
        access_key    = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
        secret_key    = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
        session_token = os.environ.get("AWS_SESSION_TOKEN", "").strip() or None

        if profile:
            session = boto3.Session(profile_name=profile, region_name=region)
        elif access_key and secret_key:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                aws_session_token=session_token,
                region_name=region,
            )
        else:
            # Production: rely on IAM Role attached to the compute resource
            session = boto3.Session(region_name=region)

        client = session.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_name)
        secret_string = response.get("SecretString", "{}")
        data = json.loads(secret_string)
        logger.info(
            f"✅ Loaded {len(data)} credential(s) from Secrets Manager "
            f"(secret: {secret_name})"
        )
        return data

    except Exception as exc:
        logger.warning(
            f"⚠️  Could not load from Secrets Manager ({secret_name}): {exc}. "
            "Falling back to .env."
        )
        return {}


def _ensure_loaded() -> None:
    """Load Secrets Manager once and inject values into os.environ."""
    global _secrets_cache, _secrets_loaded
    if _secrets_loaded:
        return

    _secrets_cache = _load_from_secrets_manager()

    # Inject into os.environ so boto3 / other libs pick them up automatically.
    # We only set values that are NOT already present (env vars win over secrets
    # if you want to override locally; change to override=True if you prefer
    # Secrets Manager to always win).
    for key, value in _secrets_cache.items():
        if key not in os.environ:
            os.environ[key] = str(value)

    _secrets_loaded = True


# ---------------------------------------------------------------------------
# 3. Public API
# ---------------------------------------------------------------------------

def get_secret(key: str, default: str = None) -> str:
    """
    Return the value for *key* using the priority chain:
      Secrets Manager  →  environment / .env  →  default

    Args:
        key:     Environment variable / secret key name (e.g. "DB_HOST").
        default: Value to return when the key is not found anywhere.

    Returns:
        String value or *default*.
    """
    _ensure_loaded()
    # After _ensure_loaded, os.environ already contains Secrets Manager values
    # (where not overridden locally), so a single os.environ lookup is enough.
    return os.environ.get(key, default)


def get_aws_session():
    """
    Build and return a boto3.Session using the resolved credentials.

    Precedence:
      1. AWS_PROFILE                                      → SSO / named profile
      2. AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY        → explicit keys
         (+ AWS_SESSION_TOKEN if present, for temporary credentials)
      3. Default boto3 credential chain                   → IAM Role (production)
    """
    _ensure_loaded()
    import boto3

    profile = get_secret("AWS_PROFILE")
    region  = get_secret("AWS_REGION", "us-east-1")

    # Blank string from .env means "don't use a profile"
    if profile and profile.strip():
        logger.debug(f"Creating boto3 session with profile: {profile}")
        return boto3.Session(profile_name=profile.strip(), region_name=region)

    access_key    = get_secret("AWS_ACCESS_KEY_ID")
    secret_key    = get_secret("AWS_SECRET_ACCESS_KEY")
    session_token = get_secret("AWS_SESSION_TOKEN")

    if access_key and secret_key:
        logger.debug(
            "Creating boto3 session with explicit access keys"
            + (" + session token" if session_token else "")
        )
        # Explicitly unset AWS_PROFILE in env so boto3 doesn't pick up stale SSO
        os.environ.pop("AWS_PROFILE", None)
        return boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            aws_session_token=session_token or None,
            region_name=region,
        )

    logger.debug("Creating boto3 session using default credential chain (IAM Role).")
    os.environ.pop("AWS_PROFILE", None)
    return boto3.Session(region_name=region)


def reload():
    """Force a fresh reload from Secrets Manager (clears cache)."""
    global _secrets_loaded, _secrets_cache
    _secrets_loaded = False
    _secrets_cache = {}
    _ensure_loaded()
