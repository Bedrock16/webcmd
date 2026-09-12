# Autonomous Job Hunting AI Agent

An intelligent, autonomous AI agent that searches job boards, scores candidate roles with an LLM, and automatically applies using **Webcmd** as its browser automation layer.

---

## Architecture Overview

The system follows a modular 3-stage pipeline:

```
[User Instructions & Profile (config.py)]
                │
                ▼
      STAGE 1: Search & Scrape (search_agent.py)
      - Navigates live job boards (RemoteOK, WeWorkRemotely, HackerNews)
      - Types queries & dismisses cookie banners
      - Scrapes Title, Company, Location, and Job URL
                │
                ▼
      STAGE 2: Smart Filter (filter_agent.py)
      - Deduplicates URLs against state.json
      - Evaluates roles via OpenAI LLM (or fallback rubric engine)
      - Scores roles 0 to 10 (+3 Remote, +3 Junior, -5 Senior, -5 Onsite)
      - Keeps only high-match candidates (Score >= 7.0)
                │
                ▼
      STAGE 3: Auto-Apply (apply_agent.py)
      - Navigates to application forms via Webcmd
      - Maps profile fields (Name, Email, Phone, Links)
      - Uploads resume document (in-memory buffer payload)
      - Safety Stop: Pauses and alerts on CAPTCHA or custom essays
      - Records results to state.json
```

---

## File Structure

- `main.py` — Orchestrator loop connecting all 3 stages with guaranteed session cleanup.
- `webcmd_client.py` — High-level Python abstraction over Webcmd CLI (sessions, scripts, snapshots, file uploads).
- `search_agent.py` — Job board scrapers and search bar interaction.
- `filter_agent.py` — LLM scoring engine and duplicate protection via `state.json`.
- `apply_agent.py` — Form filling, resume upload, and safety rule enforcement.
- `config.py` — User profile, target criteria, scoring weights, and API keys.
- `state.json` — Persistent database of applied, skipped, and paused jobs.
- `sample_resume.pdf` — Sample PDF file used for file input upload.

---

## Prerequisites

1. **Python 3.10+**: Ensure Python is installed (`python --version`).
2. **Webcmd CLI**: Must be installed and healthy:
   ```bash
   webcmd --version
   webcmd doctor
   ```
   Ensure `webcmd doctor` reports green status for the browser runtime and daemon.

---

## Installation & Setup

1. Navigate to the project directory:
   ```bash
   cd C:\Users\athar\.gemini\antigravity-ide\scratch\job_agent
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure your environment variables:
   Create a `.env` file in the project folder:
   ```env
   OPENAI_API_KEY=your_openai_api_key_here
   OPENAI_MODEL=gpt-4o-mini
   ```
   *(Note: If no OpenAI key is set, the agent automatically falls back to an internal deterministic rubric matching the scoring rules in `config.py`.)*

4. Personalize `config.py`:
   - Edit `USER_PROFILE` with your name, contact info, LinkedIn, and resume path.
   - Adjust `SCORING_RULES` weights if you have different preferences.

---

## Running the Agent

### Dry-Run Mode (Recommended for testing)
Fills in form fields and tests the pipeline without clicking the final submit button:
```bash
python main.py --dry-run
```

### Live Auto-Apply Mode
Runs end-to-end and submits applications for qualifying roles:
```bash
python main.py
```

### Custom Role Search
Target a specific role:
```bash
python main.py --role "Remote Junior Backend Engineer" --dry-run
```

---

## Safety Features

- **Human-in-the-Loop Delays**: Injects random 2.0s–5.0s pauses between browser actions to avoid bot triggers.
- **CAPTCHA Detection**: If a CAPTCHA or Cloudflare Turnstile challenge is detected, the agent immediately pauses, logs the job to `state.json` under `"paused"`, and outputs an alert.
- **Essay Protection**: If a job form requires long, custom essay responses (>150 characters), the agent pauses instead of hallucinating answers.
- **Deduplication**: Never applies to the same job URL twice by checking `state.json`.
