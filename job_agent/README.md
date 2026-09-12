# 🚀 Autonomous Job Hunting AI Agent (Webcmd JobPilot)

> **An intelligent, autonomous AI agent that searches job boards, scores candidate roles with an LLM, and automatically applies using Webcmd & Playwright as its browser automation layer.**

---

## 🏗️ 3-Stage Pipeline Architecture

```
[Candidate Profile & Settings (config.py)]
                   │
                   ▼
         STAGE 1: Search & Scrape (search_agent.py & webcmd_client.py)
         - Launches dual parallel browser sessions (LinkedIn & Naukri)
         - Navigates live job boards & dismisses cookie banners
         - Scrapes Title, Company, Location, Job URL, and Description
                   │
                   ▼
         STAGE 2: Smart Filter & LLM Scoring (filter_agent.py)
         - Deduplicates URLs against state.json (never reapplies)
         - Evaluates roles via LLM (OpenAI / OpenRouter / Qwen or rule engine)
         - Scores roles 0 to 10 (+3 Target keywords, -5 mismatches)
         - Keeps only qualified candidates (Score >= 7.0)
                   │
                   ▼
         STAGE 3: Autonomous Form Auto-Fill (apply_agent.py)
         - Navigates to application forms via Webcmd browser client
         - Injects profile info (Full name, Email, Phone, Social links)
         - Injects resume document buffer (sample_resume.pdf)
         - Safety Stop: Pauses and records to state.json on CAPTCHA / long essays
                   │
                   ▼
         REAL-TIME DASHBOARD (dashboard_server.py & dashboard/)
         - Local web server (http://localhost:8080)
         - Real-time live log streaming and browser URL tracker
         - Quick trigger for agent scans & state.json analytics
```

---

## ⚡ How Webcmd is Used

[Webcmd](https://webcmd.dev) provides the browser infrastructure that makes this agent reliable, fast, and token-efficient:
1. **Stealth Browser Sessions**: Manages browser sessions without triggering anti-bot heuristics, handling headless or visible Chrome processes cleanly.
2. **Dynamic SPA Navigation**: Overcomes complex single-page apps (SPAs) like LinkedIn and Naukri, waiting for dynamic DOM rendering and handling infinite scrolls.
3. **Session Lifecycle Control**: Implemented in [webcmd_client.py](file:///c:/Users/athar/.gemini/antigravity-ide/scratch/webcmd/job_agent/webcmd_client.py) to terminate orphaned processes and establish fresh, clean sessions on every run.
4. **Resilient Form Interaction**: Locates standard input selectors, selects files, and fills input trees reliably.

---

## 📁 File Structure

- [main.py](file:///c:/Users/athar/.gemini/antigravity-ide/scratch/webcmd/job_agent/main.py) — Master orchestrator running Stages 1, 2, and 3.
- [webcmd_client.py](file:///c:/Users/athar/.gemini/antigravity-ide/scratch/webcmd/job_agent/webcmd_client.py) — Browser abstraction wrapping Webcmd CLI and Playwright Chromium.
- [search_agent.py](file:///c:/Users/athar/.gemini/antigravity-ide/scratch/webcmd/job_agent/search_agent.py) — Multi-browser parallel search and card scraping engine.
- [filter_agent.py](file:///c:/Users/athar/.gemini/antigravity-ide/scratch/webcmd/job_agent/filter_agent.py) — LLM scoring engine and duplicate protection via `state.json`.
- [apply_agent.py](file:///c:/Users/athar/.gemini/antigravity-ide/scratch/webcmd/job_agent/apply_agent.py) — Form filling, resume upload, and safety rule enforcement.
- [config.py](file:///c:/Users/athar/.gemini/antigravity-ide/scratch/webcmd/job_agent/config.py) — Candidate profile, target criteria, scoring prompt builder, and API keys.
- [dashboard_server.py](file:///c:/Users/athar/.gemini/antigravity-ide/scratch/webcmd/job_agent/dashboard_server.py) — HTTP REST backend powering the real-time web UI.
- [dashboard/](file:///c:/Users/athar/.gemini/antigravity-ide/scratch/webcmd/job_agent/dashboard) — Glassmorphic frontend dashboard (`index.html`, `style.css`, `app.js`).
- [state.json](file:///c:/Users/athar/.gemini/antigravity-ide/scratch/webcmd/job_agent/state.json) — Persistent database of applied, skipped, and paused jobs.
- [sample_resume.pdf](file:///c:/Users/athar/.gemini/antigravity-ide/scratch/webcmd/job_agent/sample_resume.pdf) — Resume PDF payload uploaded to job forms.

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.10+
- Node.js 20.6+ (for `webcmd`)
- Google Chrome or Chromium

### 2. Verify Webcmd CLI
```bash
webcmd --version
webcmd doctor
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure `.env`
Create `.env` inside `job_agent/`:
```env
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=qwen/qwen3.5-omni-plus:free
```
*(If no API key is configured, an automatic rule-based rubric scoring system will be used seamlessly.)*

### 5. Customize Profile
Update your details in [config.py](file:///c:/Users/athar/.gemini/antigravity-ide/scratch/webcmd/job_agent/config.py):
- Name, contact info, LinkedIn URL
- Absolute path to your resume PDF

---

## 💻 Usage

### Web Dashboard (Interactive GUI)
Start the dashboard server:
```bash
python dashboard_server.py
```
Open [http://localhost:8080](http://localhost:8080) in your browser. From here you can:
- Trigger scans for any role
- Monitor live logs as browsers navigate
- Inspect job statistics and state history

### CLI Modes

#### Dry-Run Mode (Recommended for testing)
Performs discovery and fills fields without submitting:
```bash
python main.py --dry-run
```

#### Custom Target Role
Target any specific role dynamically:
```bash
python main.py --role "Full Stack Developer" --dry-run
```

#### Fresh Reset
Wipe `state.json` history for clean-slate testing:
```bash
python main.py --role "Python Developer" --dry-run --reset-state
```

#### Live Auto-Apply
Submits applications for qualifying roles:
```bash
python main.py --role "Backend Developer"
```

---

## 🛡️ Safety & Safeguards

- **Human Delays**: Employs random 2.0s–5.0s pauses between browser actions.
- **Anti-Bot / CAPTCHA Guard**: Pauses and marks the role as `paused` in `state.json` if a CAPTCHA or Cloudflare challenge is encountered.
- **Essay Question Protection**: Stops on lengthy open-ended essay questions to avoid hallucinated responses.
- **State Deduplication**: Prevents duplicate visits or applications by indexing every processed job in `state.json`.
