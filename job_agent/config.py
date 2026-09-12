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
def _build_scoring_rules(role: str) -> dict:
    """Build a simple, generic scoring prompt from the target role. No hardcoded assumptions."""
    return {
        "min_passing_score": 7.0,
        "target_role": role,
        "scoring_criteria_prompt": f"""You are a job matching expert. The user is looking for: "{role}".

Score the job from 0 to 10 based on how well it matches what the user is looking for.
Consider title match, seniority fit, tech stack relevance, location compatibility, and overall alignment.
Use your own judgement — only penalize things that clearly conflict with the user's search intent.

Return valid JSON:
{{
  "score": float (0.0 to 10.0),
  "passed": boolean (true if score >= 7.0),
  "reasons": [short strings explaining each scoring factor]
}}"""
    }

SCORING_RULES = _build_scoring_rules(_TARGET_ROLE)

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
