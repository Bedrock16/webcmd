"""
config.py - Configuration settings for the Job Hunting AI Agent.
Includes User Profile, Search Criteria, Smart Scoring Rules, and xkiro / Qwen LLM Settings.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# ==========================================
# 1. USER PROFILE FOR AUTO-APPLY
# ==========================================
USER_PROFILE = {
    "first_name": "Alex",
    "last_name": "Mercer",
    "full_name": "Alex Mercer",
    "email": "alex.mercer.dev@example.com",
    "phone": "+1 (555) 234-5678",
    "linkedin": "https://www.linkedin.com/in/alex-mercer-dev",
    "github": "https://github.com/alexmercer-dev",
    "portfolio": "https://alexmercer.dev",
    "location": "Remote, US / Worldwide",
    "summary": (
        "Motivated Junior Python Developer with hands-on experience building REST APIs "
        "using FastAPI and Django, writing automated tests, and integrating databases. "
        "Passionate about clean code, async programming, and rapid problem-solving."
    ),
    # Path to resume file used for file input upload
    "resume_path": str(BASE_DIR / "sample_resume.pdf"),
}

# ==========================================
# 2. SEARCH INSTRUCTIONS & TARGET SITES
# ==========================================
from urllib.parse import quote as _url_quote

_TARGET_ROLE = "Remote Junior Python Developer"

SEARCH_CONFIG = {
    "target_role": _TARGET_ROLE,
    "search_keywords": [kw.strip() for kw in _TARGET_ROLE.split() if len(kw.strip()) > 2],
    "target_sites": [
        {
            "name": "LinkedIn",
            "url": f"https://www.linkedin.com/jobs/search?keywords={_url_quote(_TARGET_ROLE)}&location=Worldwide",
            "type": "linkedin"
        }
    ],
    "max_jobs_to_scrape": 15,
}

# ==========================================
# 3. SMART FILTERING & SCORING RULES
# ==========================================
SCORING_RULES = {
    "min_passing_score": 7.0,  # Only jobs scoring >= 7 will proceed to Stage 3
    "weights": {
        "remote": 3.0,          # +3 for 100% remote positions
        "junior_entry": 3.0,    # +3 for junior, entry-level, associate, or 0-2 yrs experience
        "python_stack": 2.0,    # +2 for core Python/Django/FastAPI tech stack
        "senior_penalty": -5.0, # -5 for Senior, Lead, Principal, Architect, or 5+ yrs exp
        "onsite_penalty": -5.0  # -5 for mandatory onsite or requiring immediate relocation
    },
    "scoring_criteria_prompt": """
You are a job evaluation expert. Score the given job opportunity from 0 to 10 based strictly on these rules:
- Base score starts at 5.0.
- If the role is clearly REMOTE: add +3.0
- If the role is explicitly JUNIOR, ENTRY-LEVEL, ASSOCIATE, or allows 0-2 years experience: add +3.0
- If the role focuses on PYTHON, FASTAPI, DJANGO, or BACKEND development: add +2.0
- If the role requires SENIOR, STAFF, LEAD, PRINCIPAL, or 5+ years experience: subtract -5.0
- If the role is strictly ONSITE or requires relocation: subtract -5.0
- Clamp final score between 0.0 and 10.0.

Return valid JSON with:
{
  "score": float,
  "passed": boolean (true if score >= 7.0 else false),
  "reasons": [list of strings explaining the score breakdown]
}
"""
}

# ==========================================
# 4. SAFETY & AGENT BEHAVIOR RULES
# ==========================================
import glob

def find_chrome_executable() -> Optional[str]:
    """Auto-detect real Google Chrome or Playwright Chromium binary on Windows."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    playwright_paths = glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-*\chrome-win64\chrome.exe"))
    candidates.extend(reversed(playwright_paths))
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None

AGENT_RULES = {
    "headless": False,               # Open real visible Chrome browser instance
    "chrome_executable": find_chrome_executable(),
    "min_delay_seconds": 2.0,       # Human-like delay minimum
    "max_delay_seconds": 5.0,       # Human-like delay maximum
    "dry_run": False,               # If True, fills form but does not click final Submit
    "pause_on_captcha": True,       # Safety stop if CAPTCHA detected
    "pause_on_complex_essay": True, # Safety stop if long essay answers required (>200 words)
    "state_file": str(BASE_DIR / "state.json"),
    "preview_file": str(BASE_DIR / "dashboard" / "live_screen.png"),
}

# ==========================================
# 5. OPENAI / XKIRO LLM SETTINGS
# ==========================================
OPENAI_CONFIG = {
    "api_key": os.getenv("OPENAI_API_KEY", ""),
    "base_url": os.getenv("OPENAI_BASE_URL", "https://api.xkiro.com/v1"),
    "model": os.getenv("OPENAI_MODEL", "qwen/qwen3.5-omni-plus:free"),
    "temperature": 0.1,
}
