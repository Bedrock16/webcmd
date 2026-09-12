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
    """Build scoring criteria dynamically based on the target role."""
    role_lower = role.lower()

    # Detect seniority level from role
    is_senior = any(kw in role_lower for kw in ["senior", "sr.", "lead", "principal", "staff", "architect", "head", "director", "manager"])
    is_junior = any(kw in role_lower for kw in ["junior", "jr.", "entry", "intern", "associate", "graduate", "fresher"])
    wants_remote = any(kw in role_lower for kw in ["remote", "worldwide", "anywhere"])

    # Extract tech keywords from the role
    all_tech_keywords = ["python", "javascript", "typescript", "react", "angular", "vue", "node", "java", "go",
                         "rust", "c++", "c#", ".net", "ruby", "php", "swift", "kotlin", "flutter", "dart",
                         "django", "fastapi", "flask", "spring", "express", "next.js", "nuxt",
                         "aws", "azure", "gcp", "devops", "docker", "kubernetes", "terraform",
                         "data", "ml", "machine learning", "ai", "deep learning", "nlp",
                         "sql", "postgres", "mongodb", "redis", "elasticsearch"]
    matched_tech = [kw for kw in all_tech_keywords if kw in role_lower]
    tech_label = ", ".join(matched_tech).upper() if matched_tech else "relevant tech stack"

    # Build seniority rule
    if is_senior:
        seniority_bonus = "If the role is SENIOR, LEAD, STAFF, PRINCIPAL, or requires 5+ years experience: add +3.0"
        seniority_penalty = "If the role is explicitly JUNIOR, ENTRY-LEVEL, or INTERN with no senior path: subtract -3.0"
    elif is_junior:
        seniority_bonus = "If the role is JUNIOR, ENTRY-LEVEL, ASSOCIATE, INTERN, or allows 0-2 years experience: add +3.0"
        seniority_penalty = "If the role requires SENIOR, STAFF, LEAD, PRINCIPAL, or 5+ years experience: subtract -5.0"
    else:
        seniority_bonus = "If the seniority level closely matches the target role: add +2.0"
        seniority_penalty = "If the seniority level is a clear mismatch (e.g. intern when looking for mid-level): subtract -3.0"

    prompt = f"""You are a job evaluation expert. The user is searching for: "{role}".
Score the given job opportunity from 0 to 10 based on how well it matches the user's target role. Apply these rules strictly:
- Base score starts at 5.0.
- {("If the role is clearly REMOTE or allows remote work: add +3.0" if wants_remote else "Remote/onsite is not a preference factor for this search.")}
- {seniority_bonus}
- If the role focuses on {tech_label} or closely related technologies: add +2.0
- {seniority_penalty}
- If the role is strictly ONSITE or requires relocation (and user wants remote): subtract -5.0
- Clamp final score between 0.0 and 10.0.

Return valid JSON with:
{{
  "score": float,
  "passed": boolean (true if score >= 7.0 else false),
  "reasons": [list of strings explaining the score breakdown]
}}"""

    return {
        "min_passing_score": 7.0,
        "matched_tech": matched_tech,
        "is_senior": is_senior,
        "is_junior": is_junior,
        "wants_remote": wants_remote,
        "scoring_criteria_prompt": prompt
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
