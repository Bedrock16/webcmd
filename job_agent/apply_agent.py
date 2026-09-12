"""
apply_agent.py - Stage 3: Auto-Apply
Navigates to job application pages, maps user profile data to form fields,
handles resume upload, enforces critical safety rules (pauses on CAPTCHA / complex essays),
and logs completed applications to state.json.
"""

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from config import USER_PROFILE, AGENT_RULES
from webcmd_client import WebcmdClient

logger = logging.getLogger("ApplyAgent")


class ApplyAgent:
    """
    Automates the form-filling and submission process for approved job postings.
    """

    def __init__(self, client: WebcmdClient, state_file_path: Optional[str] = None):
        self.client = client
        self.state_file = Path(state_file_path or AGENT_RULES["state_file"])
        self.dry_run = AGENT_RULES.get("dry_run", False)

    def load_state(self) -> Dict[str, Any]:
        """Load state.json data."""
        if not self.state_file.exists():
            return {"applied": [], "skipped": [], "paused": []}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"applied": [], "skipped": [], "paused": []}

    def save_state(self, state: Dict[str, Any]) -> None:
        """Persist state.json immediately."""
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as exc:
            logger.error("Failed to write to state.json: %s", exc)

    def apply_to_jobs(self, approved_jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Execute Stage 3 for all pre-approved jobs.
        """
        logger.info("=== STAGE 3: AUTO-APPLY (%d jobs to process) ===", len(approved_jobs))
        results = []

        for idx, job in enumerate(approved_jobs, start=1):
            url = job.get("url")
            title = job.get("title", "Unknown Role")
            company = job.get("company", "Unknown Company")

            logger.info("--------------------------------------------------")
            logger.info("Processing Application [%d/%d]: %s at %s", idx, len(approved_jobs), title, company)
            logger.info("URL: %s", url)

            try:
                outcome = self._process_single_application(job)
                results.append(outcome)
            except Exception as exc:
                logger.error("Unexpected error applying to %s: %s", url, exc)
                self._record_paused(job, f"Execution error: {exc}")

            # Human-in-the-loop delay between jobs
            self.client.human_delay(
                AGENT_RULES["min_delay_seconds"],
                AGENT_RULES["max_delay_seconds"]
            )

        logger.info("Stage 3 complete. Applications processed: %d", len(results))
        return results

    def _process_single_application(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """
        Navigates to job page, locates application form, checks safety rules,
        fills fields, uploads resume, and records state.
        """
        url = job.get("url")
        self.client.navigate(url)
        self.client.dismiss_modals()
        self.client.human_delay(1.5, 3.0)

        # Check if we need to click an "Apply" button to reach the form
        self._navigate_to_application_form_if_needed()

        # Step 1: Safety Check - CAPTCHA and Complex Essay detection
        is_safe, safety_reason = self._check_safety_rules()
        if not is_safe:
            logger.warning("[SAFETY RULE TRIGGERED] %s", safety_reason)
            logger.warning("Agent will PAUSE on %s and alert the user.", url)
            self._record_paused(job, safety_reason)
            return {"job": job, "status": "paused", "reason": safety_reason}

        # Step 2: Form Analysis & Field Mapping
        form_info = self._analyze_form_fields()
        logger.info("Detected form elements: %d inputs, %d textareas, %d file uploads",
                    len(form_info.get("inputs", [])),
                    len(form_info.get("textareas", [])),
                    len(form_info.get("file_inputs", [])))

        # Step 3: Fill Input Fields
        fill_count = self._fill_form_fields(form_info)
        logger.info("Successfully filled %d form field(s).", fill_count)

        # Step 4: Resume File Upload
        if form_info.get("file_inputs"):
            file_selector = form_info["file_inputs"][0]["selector"]
            resume_path = USER_PROFILE["resume_path"]
            try:
                self.client.upload_file(file_selector, resume_path)
                logger.info("Resume file uploaded successfully.")
            except Exception as exc:
                logger.warning("Resume upload failed: %s", exc)

        self.client.human_delay(1.5, 2.5)

        # Step 5: Submit Form (Respecting Dry-Run)
        submitted = self._submit_form()

        # Step 6: Log state
        status = "applied" if submitted else "ready_for_submission (dry_run)"
        self._record_applied(job, status=status)

        return {"job": job, "status": status, "fields_filled": fill_count}

    def _navigate_to_application_form_if_needed(self) -> None:
        """
        If on a job landing page with an 'Apply' button, click it to reveal form.
        """
        script = """
const applyButtons = [
    'a:has-text("Apply for this job")',
    'button:has-text("Apply for this job")',
    'a:has-text("Apply on company website")',
    'a:has-text("Apply Now")',
    'button:has-text("Apply Now")',
    'a.apply-button',
    'button.apply-button',
    '#apply_button',
    'a[href*="externalApply"]',
    'a[href*="apply"]'
];

for (const sel of applyButtons) {
    const el = page.locator(sel).first;
    if (await el.isVisible({ timeout: 500 }).catch(() => false)) {
        await el.scrollIntoViewIfNeeded();
        await el.click({ timeout: 2000 }).catch(() => {});
        return { clicked: true, selector: sel };
    }
}
return { clicked: false };
"""
        try:
            res = self.client.run_script(script, timeout=10)
            if res.get("result", {}).get("clicked"):
                logger.info("Clicked 'Apply' button to open application form.")
                self.client.dismiss_modals()
                self.client.human_delay(2.0, 3.5)
        except Exception as exc:
            logger.debug("Apply button click skipped: %s", exc)

    def _check_safety_rules(self) -> Tuple[bool, str]:
        """
        Safety Rule:
        1. If CAPTCHA is detected, PAUSE and alert user.
        2. If complex custom essay questions are detected, PAUSE and alert user.
        """
        script = """
// 1. Check CAPTCHA
const captchaSelectors = [
    'iframe[src*="captcha"]',
    'iframe[src*="turnstile"]',
    'iframe[src*="recaptcha"]',
    'iframe[src*="hcaptcha"]',
    '.g-recaptcha',
    '.h-captcha',
    '#cf-turnstile',
    'div:has-text("Verify you are human")',
    'div:has-text("Security verification")'
];

for (const sel of captchaSelectors) {
    const el = page.locator(sel).first;
    if (await el.isVisible({ timeout: 400 }).catch(() => false)) {
        return { safe: false, reason: "CAPTCHA detected on page" };
    }
}

// 2. Check Complex Essay Textareas inside page context
const essayCheck = await page.evaluate(() => {
    const textareas = Array.from(document.querySelectorAll('textarea'));
    for (const ta of textareas) {
        const label = ta.labels && ta.labels[0] ? ta.labels[0].innerText : '';
        const placeholder = ta.placeholder || '';
        const prompt = (label + ' ' + placeholder).toLowerCase();

        // Look for essay indicators
        if (prompt.includes('why do you want') ||
            prompt.includes('describe a time') ||
            (prompt.includes('cover letter') && prompt.length > 50) ||
            prompt.includes('tell us about') ||
            prompt.length > 150) {
            return { safe: false, reason: `Complex essay question detected: "${prompt.slice(0, 80)}..."` };
        }
    }

    // 3. Check for Forced Authentication / Sign-in Wall
    if (document.title.includes("Sign In") || document.title.includes("Sign Up") || document.title.includes("AuthWall")) {
        return { safe: false, reason: "Authentication / Login Wall encountered (requires user login)" };
    }
    const loginModals = document.querySelector('.contextual-sign-in-modal, #sign-in-modal, .authwall');
    if (loginModals && loginModals.offsetParent !== null) {
        return { safe: false, reason: "LinkedIn login overlay detected" };
    }

    return { safe: true, reason: "" };
});

return essayCheck;
"""
        try:
            res = self.client.run_script(script, timeout=10)
            result = res.get("result", {})
            return result.get("safe", True), result.get("reason", "")
        except Exception as exc:
            logger.debug("Safety rule evaluation fallback: %s", exc)
            return True, ""

    def _analyze_form_fields(self) -> Dict[str, Any]:
        """
        Scan page for form inputs, textareas, and file upload selectors inside page context.
        """
        script = """
const formFields = await page.evaluate(() => {
    const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"])')).map(inp => {
        const label = inp.labels && inp.labels[0] ? inp.labels[0].innerText.trim() : '';
        return {
            id: inp.id,
            name: inp.name,
            type: inp.type || 'text',
            label: label,
            placeholder: inp.placeholder || '',
            autocomplete: inp.autocomplete || '',
            selector: inp.id ? '#' + CSS.escape(inp.id) : (inp.name ? `input[name="${CSS.escape(inp.name)}"]` : null)
        };
    }).filter(i => i.selector && i.type !== 'file');

    const fileInputs = Array.from(document.querySelectorAll('input[type="file"]')).map(inp => ({
        id: inp.id,
        name: inp.name,
        selector: inp.id ? '#' + CSS.escape(inp.id) : (inp.name ? `input[name="${CSS.escape(inp.name)}"]` : 'input[type="file"]')
    }));

    const textareas = Array.from(document.querySelectorAll('textarea')).map(ta => ({
        id: ta.id,
        name: ta.name,
        placeholder: ta.placeholder || '',
        selector: ta.id ? '#' + CSS.escape(ta.id) : (ta.name ? `textarea[name="${CSS.escape(ta.name)}"]` : 'textarea')
    }));

    return { inputs, fileInputs, textareas };
});

return formFields;
"""
        res = self.client.run_script(script, timeout=12)
        data = res.get("result", {})
        return {
            "inputs": data.get("inputs", []),
            "file_inputs": data.get("fileInputs", []),
            "textareas": data.get("textareas", [])
        }

    def _fill_form_fields(self, form_info: Dict[str, Any]) -> int:
        """
        Map USER_PROFILE data to matching inputs and fill them.
        """
        filled_count = 0
        inputs = form_info.get("inputs", [])

        for inp in inputs:
            identifier = f"{inp.get('name', '')} {inp.get('id', '')} {inp.get('label', '')} {inp.get('placeholder', '')} {inp.get('autocomplete', '')}".lower()
            selector = inp.get("selector")
            if not selector:
                continue

            val_to_type = None

            # First name
            if any(k in identifier for k in ["first_name", "firstname", "first name", "given-name"]):
                val_to_type = USER_PROFILE["first_name"]
            # Last name
            elif any(k in identifier for k in ["last_name", "lastname", "last name", "family-name"]):
                val_to_type = USER_PROFILE["last_name"]
            # Full name
            elif any(k in identifier for k in ["full_name", "fullname", "your name", "full name", "name"]):
                val_to_type = USER_PROFILE["full_name"]
            # Email
            elif inp.get("type") == "email" or any(k in identifier for k in ["email", "e-mail"]):
                val_to_type = USER_PROFILE["email"]
            # Phone
            elif inp.get("type") == "tel" or any(k in identifier for k in ["phone", "tel", "mobile"]):
                val_to_type = USER_PROFILE["phone"]
            # LinkedIn
            elif "linkedin" in identifier:
                val_to_type = USER_PROFILE["linkedin"]
            # GitHub
            elif "github" in identifier:
                val_to_type = USER_PROFILE["github"]
            # Portfolio / Website
            elif any(k in identifier for k in ["portfolio", "website", "url", "site"]):
                val_to_type = USER_PROFILE["portfolio"]

            if val_to_type:
                try:
                    self.client.type_text(selector, val_to_type)
                    filled_count += 1
                    self.client.human_delay(0.5, 1.2)
                except Exception as exc:
                    logger.debug("Failed filling field %s: %s", selector, exc)

        return filled_count

    def _submit_form(self) -> bool:
        """
        Submit form or simulate submission in dry-run mode.
        """
        if self.dry_run:
            logger.info("[DRY RUN ENABLED] Skipping final submit click. Form is prepared.")
            return True

        script = """
const submitSelectors = [
    'input[type="submit"]',
    'button[type="submit"]',
    'button:has-text("Submit Application")',
    'button:has-text("Submit")',
    'button:has-text("Apply")',
    '#submit_app'
];

for (const sel of submitSelectors) {
    const btn = page.locator(sel).first;
    if (await btn.isVisible({ timeout: 500 }).catch(() => false)) {
        await btn.scrollIntoViewIfNeeded();
        await btn.click({ timeout: 3000 }).catch(() => {});
        return { submitted: true, selector: sel };
    }
}
return { submitted: false };
"""
        try:
            res = self.client.run_script(script, timeout=10)
            if res.get("result", {}).get("submitted"):
                logger.info("Clicked final submit button.")
                self.client.human_delay(2.0, 4.0)
                return True
            else:
                logger.info("No distinct submit button found. Form state saved.")
                return True
        except Exception as exc:
            logger.warning("Error clicking submit button: %s", exc)
            return False

    def _record_applied(self, job: Dict[str, Any], status: str = "applied") -> None:
        """Record successfully applied job in state.json immediately."""
        state = self.load_state()
        existing_urls = {item.get("url") for item in state.get("applied", []) if isinstance(item, dict)}
        if job.get("url") not in existing_urls:
            state.setdefault("applied", []).append({
                "url": job.get("url"),
                "title": job.get("title"),
                "company": job.get("company"),
                "score": job.get("score"),
                "applied_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "status": status
            })
            self.save_state(state)

    def _record_paused(self, job: Dict[str, Any], reason: str) -> None:
        """Record paused job requiring human action in state.json."""
        state = self.load_state()
        existing_urls = {item.get("url") for item in state.get("paused", []) if isinstance(item, dict)}
        if job.get("url") not in existing_urls:
            state.setdefault("paused", []).append({
                "url": job.get("url"),
                "title": job.get("title"),
                "company": job.get("company"),
                "score": job.get("score"),
                "paused_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "reason": reason
            })
            self.save_state(state)
        logger.info("Recorded paused job in state.json: %s (Reason: %s)", job.get("url"), reason)
