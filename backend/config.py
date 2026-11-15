"""Global settings. Override with environment variables where noted."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
# Serverless hosting (Vercel sets VERCEL=1): only /tmp is writable, each instance has its own copy of it,
# and nothing may keep running after a response is sent.
SERVERLESS = bool(os.environ.get("VERCEL")) or os.environ.get("CVSCREEN_SERVERLESS", "") not in ("", "0", "false", "False")
DB_PATH = Path(os.environ.get("CVSCREEN_DB", "/tmp/cvscreen.sqlite3" if SERVERLESS else ROOT / "cvscreen.sqlite3"))
FRONTEND_DIR = ROOT / "frontend"
SYNTHETIC_DIR = DATA_DIR / "synthetic"
FIXTURES_PATH = DATA_DIR / "fixtures" / "verification_fixtures.json"

# Reference year used to compute "present" and recency windows.
# Fixed (not the system clock) so that scores are reproducible across runs and machines.
CURRENT_YEAR = int(os.environ.get("CVSCREEN_CURRENT_YEAR", "2026"))

# LLM providers. Keys can also be entered in the web interface (kept in server memory only).
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")

# Polite contact string sent to public scholarly APIs (Crossref and OpenAlex ask for one).
CONTACT_EMAIL = os.environ.get("CVSCREEN_CONTACT_EMAIL", "")

# Deployment ------------------------------------------------------------------------------------
# Password for the whole app (HTTP Basic auth, any user name). Leave empty for local use.
APP_PASSWORD = os.environ.get("CVSCREEN_PASSWORD", "")
# Public demo mode for hosting a showcase: no AI model calls (stored demo extractions and scripted workflows only),
# no uploads, no settings changes, no live internet lookups, so visitors cannot run up costs or upload personal data.
# On serverless hosting it is on unless CVSCREEN_PUBLIC_DEMO=0.
PUBLIC_DEMO = os.environ.get("CVSCREEN_PUBLIC_DEMO", "1" if SERVERLESS else "") not in ("", "0", "false", "False")
# Run "background" jobs inside the request instead (serverless platforms stop work after the response).
SYNC_JOBS = SERVERLESS
# Applications older than this many days are deleted at startup (0 = keep). Supports data-retention policies.
RETENTION_DAYS = int(os.environ.get("CVSCREEN_RETENTION_DAYS", "0"))
