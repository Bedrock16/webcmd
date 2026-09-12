"""
webcmd_client.py - Dual Browser Client supporting Playwright Real Chrome (Headed GUI)
and Webcmd CLI automation layer.
Guarantees clean browser session shutdown on fresh starts and opens a real visible Chrome window.
"""

import json
import logging
import os
import random
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import AGENT_RULES, find_chrome_executable

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s - %(message)s")
logger = logging.getLogger("WebcmdClient")


class WebcmdError(Exception):
    """Custom exception raised when a browser operation fails."""
    pass


class WebcmdClient:
    """
    Browser Client that manages real Chrome browser instances (visible headed GUI)
    via Playwright, with fallback to Webcmd CLI.
    Ensures that on fresh start, any lingering browser processes or sessions are terminated.
    """

    def __init__(self, session_name: str = "job-pilot-session", use_real_chrome: bool = True):
        self.session_name = session_name
        self.session_id: Optional[str] = None
        self.use_real_chrome = use_real_chrome and HAS_PLAYWRIGHT
        self.chrome_executable = AGENT_RULES.get("chrome_executable") or find_chrome_executable()

        # Playwright runtime handles
        self.playwright: Optional[Any] = None
        self.browser: Optional[Any] = None
        self.context: Optional[Any] = None
        self.page: Optional[Any] = None

        self._temp_files: List[str] = []

    @staticmethod
    def close_stale_browsers():
        """
        Guarantees that on a fresh start, any lingering browser sessions or
        orphaned Chrome processes are terminated cleanly before launching a new session.
        """
        logger.info("Fresh start check: ensuring all lingering browser instances and sessions are closed...")
        # 1. Close webcmd sessions if any exist
        try:
            res = subprocess.run(
                ["webcmd", "session", "list", "-f", "json"],
                capture_output=True, text=True, timeout=5, shell=(os.name == "nt")
            )
            if res.returncode == 0 and res.stdout.strip():
                try:
                    data = json.loads(res.stdout)
                    if isinstance(data, list):
                        for s in data:
                            sid = s.get("id")
                            if sid:
                                subprocess.run(
                                    ["webcmd", "session", "close", sid, "--force"],
                                    capture_output=True, timeout=5, shell=(os.name == "nt")
                                )
                except Exception:
                    pass
        except Exception:
            pass

        # 2. Terminate any dangling chrome automation processes on Windows
        if os.name == "nt":
            try:
                subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True, timeout=5)
            except Exception:
                pass
        time.sleep(0.8)
        logger.info("Stale browser instances closed. Clean-slate ready.")

    def _execute_cli(self, args: List[str], timeout: int = 45) -> str:
        """Execute a webcmd CLI command via subprocess."""
        cmd = ["webcmd"] + args
        logger.debug("Running command: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=(os.name == "nt"),
                timeout=timeout,
                check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise WebcmdError(f"Webcmd command timed out after {timeout}s: {' '.join(cmd)}") from exc
        except Exception as exc:
            raise WebcmdError(f"Failed to execute webcmd command: {exc}") from exc

        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or proc.stdout.strip()
            raise WebcmdError(f"Webcmd exited with code {proc.returncode}: {err_msg}")

        return proc.stdout.strip()

    def check_doctor(self) -> bool:
        """Verify environment readiness."""
        if self.use_real_chrome and self.chrome_executable and Path(self.chrome_executable).exists():
            logger.info("Real Chrome Engine ready at: %s", self.chrome_executable)
            return True
        logger.info("Verifying Webcmd environment with 'webcmd doctor'...")
        try:
            output = self._execute_cli(["doctor"], timeout=20)
            return "[OK] Daemon:" in output and "[OK] Connectivity:" in output
        except Exception as exc:
            logger.warning("Webcmd doctor check: %s", exc)
            return True

    def start_session(self) -> str:
        """
        Always close any lingering browser first on fresh start,
        then launch a real visible Chrome browser instance.
        """
        if self.page and not self.page.is_closed():
            logger.info("Reusing active browser session: %s", self.session_id)
            return self.session_id or "real-chrome-session"

        # 1. Enforce clean fresh start: close stale browsers
        self.close_stale_browsers()

        # 2. Launch real visible Chrome window
        if self.use_real_chrome:
            logger.info("Opening REAL Chrome browser instance (visible window on desktop)...")
            try:
                self.playwright = sync_playwright().start()
                launch_args = [
                    "--window-size=1280,850",
                    "--window-position=80,60",
                    "--disable-blink-features=AutomationControlled",
                    "--no-default-browser-check",
                    "--no-first-run",
                ]
                self.browser = self.playwright.chromium.launch(
                    headless=AGENT_RULES.get("headless", False),
                    executable_path=self.chrome_executable,
                    args=launch_args
                )
                self.context = self.browser.new_context(
                    viewport={"width": 1280, "height": 850},
                    extra_http_headers={
                        "referer": "https://www.google.com/",
                        "accept-language": "en-US,en;q=0.9",
                    },
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                self.page = self.context.new_page()
                self.session_id = f"real-chrome-{int(time.time())}"
                logger.info("Real Chrome browser window opened successfully (Session: %s)!", self.session_id)
                return self.session_id
            except Exception as exc:
                logger.warning("Failed launching real Chrome via Playwright (%s). Falling back to Webcmd CLI.", exc)
                self.use_real_chrome = False

        # Fallback to Webcmd CLI session
        logger.info("Creating Webcmd browser session '%s'...", self.session_name)
        raw_out = self._execute_cli(["session", "create", self.session_name, "-f", "json"])
        try:
            data = json.loads(raw_out)
            self.session_id = data.get("id")
            logger.info("Webcmd browser session active: %s", self.session_id)
            return self.session_id
        except Exception as exc:
            raise WebcmdError(f"Failed to create webcmd session: {raw_out} - {exc}") from exc

    def close_session(self) -> bool:
        """
        Close the active browser session cleanly so no window or process lingers.
        """
        logger.info("Closing browser session...")
        if self.use_real_chrome:
            try:
                if self.page and not self.page.is_closed():
                    self.page.close()
            except Exception:
                pass
            try:
                if self.context:
                    self.context.close()
            except Exception:
                pass
            try:
                if self.browser:
                    self.browser.close()
            except Exception:
                pass
            try:
                if self.playwright:
                    self.playwright.stop()
            except Exception:
                pass
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None
            self.session_id = None
            logger.info("Real Chrome browser closed cleanly.")
            return True

        if not self.session_id:
            return True

        logger.info("Closing Webcmd browser session %s...", self.session_id)
        try:
            self._execute_cli(["session", "close", self.session_id])
            logger.info("Session %s closed cleanly.", self.session_id)
            self.session_id = None
            return True
        except Exception as exc:
            logger.warning("Error closing session %s: %s", self.session_id, exc)
            self.session_id = None
            return False
        finally:
            self._cleanup_temp_files()

    def navigate(self, url: str, wait_until: str = "domcontentloaded") -> Dict[str, Any]:
        """Navigate the browser session to target URL."""
        if not self.session_id:
            self.start_session()

        logger.info("Navigating to: %s", url)
        if self.use_real_chrome and self.page:
            try:
                self.page.goto(url, wait_until=wait_until, timeout=35000)
            except Exception as exc:
                logger.warning("Navigation warning: %s", exc)
            self.capture_screenshot()
            return {"url": self.page.url, "title": self.page.title()}

        # Webcmd CLI fallback
        script = f"""
try {{
    await page.setExtraHTTPHeaders({{
        'referer': 'https://www.google.com/',
        'accept-language': 'en-US,en;q=0.9'
    }});
}} catch (e) {{}}
await page.goto('{url}', {{ waitUntil: '{wait_until}', timeout: 30000 }});
try {{
    await page.screenshot({{ path: 'live_screen.png' }});
}} catch (e) {{}}
return {{ url: page.url(), title: await page.title() }};
"""
        res = self.run_script(script)
        self._extract_live_screenshot(res)
        return res.get("result", {})

    def scrape_linkedin_cards(self, limit: int = 15) -> List[Dict[str, Any]]:
        """
        Scrape jobs directly from LinkedIn in the real Chrome instance.
        Performs natural mouse scrolls to trigger card population.
        """
        if self.use_real_chrome and self.page:
            try:
                # Natural human scroll to trigger dynamic job cards loading
                self.page.mouse.wheel(0, 600)
                time.sleep(1.0)
                self.page.mouse.wheel(0, -300)
                time.sleep(0.5)
                self.capture_screenshot()

                jobs = self.page.evaluate("""(maxCount) => {
                    const cards = Array.from(document.querySelectorAll('ul.jobs-search__results-list li, .base-card, .job-search-card'));
                    return cards.slice(0, maxCount).map(c => {
                        const t = c.querySelector('.base-search-card__title, h3');
                        const co = c.querySelector('.base-search-card__subtitle, h4');
                        const loc = c.querySelector('.job-search-card__location');
                        const a = c.querySelector('a.base-card__full-link, a');
                        const title = t ? t.textContent.trim() : '';
                        let url = a ? a.href : '';
                        if (url && url.includes('?')) url = url.split('?')[0];
                        return {
                            title: title,
                            company: co ? co.textContent.trim() : 'Company on LinkedIn',
                            location: loc ? loc.textContent.trim() : 'Remote',
                            url: url,
                            snippet: title + ' at ' + (co ? co.textContent.trim() : '') + ' - LinkedIn Jobs',
                            source: 'LinkedIn'
                        };
                    }).filter(j => j.title && j.url);
                }""", limit)
                return jobs
            except Exception as exc:
                logger.warning("Error scraping LinkedIn in real Chrome: %s", exc)
                return []
        return []

    def cut_modal(self) -> bool:
        """
        Immediately cut/dismiss LinkedIn's 'Sign in to view more jobs' modal overlay.
        Dispatches Escape key, clicks dismiss buttons, and removes blocking overlays from DOM.
        """
        if self.use_real_chrome and self.page:
            try:
                # 1. Dispatch Escape key
                try:
                    self.page.keyboard.press("Escape")
                except Exception:
                    pass

                # 2. Comprehensive DOM close click and element removal
                cut = self.page.evaluate("""() => {
                    let removed = false;
                    // 1. Try clicking dismiss/close buttons
                    const dismissSelectors = [
                        'button.modal__dismiss',
                        'button.contextual-sign-in-modal__modal-dismiss',
                        'button[data-tracking-control-name*="modal_dismiss"]',
                        'button[data-tracking-control-name*="sign-in-modal_dismiss"]',
                        'button[aria-label="Dismiss"]',
                        'button[aria-label="Fechar"]',
                        'button[aria-label="Close"]',
                        'button[aria-label*="Dismiss" i]',
                        'button[aria-label*="Close" i]',
                        'button.artdeco-modal__dismiss',
                        'button[data-test-modal-close-btn]',
                        'button[data-modal="close"]',
                        '.modal__dismiss-icon',
                        'button:has-text("Dismiss")',
                        'button:has-text("Got it")',
                        'button:has-text("Skip")'
                    ];
                    for (const sel of dismissSelectors) {
                        try {
                            const btns = Array.from(document.querySelectorAll(sel));
                            for (const b of btns) {
                                try { b.click(); removed = true; } catch(e){}
                            }
                        } catch(e){}
                    }

                    // Also search for any button inside any modal or overlay with an SVG/icon
                    try {
                        const modalContainers = document.querySelectorAll(
                            '.contextual-sign-in-modal, .modal__overlay, .sign-in-modal, [data-outlet="sign-in-modal"], [role="dialog"]'
                        );
                        modalContainers.forEach(container => {
                            const closeBtn = container.querySelector('button');
                            if (closeBtn) {
                                try { closeBtn.click(); removed = true; } catch(e){}
                            }
                        });
                    } catch(e){}

                    // 2. Force remove modal overlays and backdrops from DOM
                    const modalEls = document.querySelectorAll(
                        '.contextual-sign-in-modal, .modal__overlay, .sign-in-modal, [data-outlet="sign-in-modal"], .artdeco-modal-overlay, [role="dialog"], .modal-outlet, div.modal__backdrop, .modal-backdrop, [data-modal]'
                    );
                    modalEls.forEach(el => {
                        el.remove();
                        removed = true;
                    });

                    // 3. Unlock scrolling on body/html
                    document.body.style.overflow = 'auto';
                    document.documentElement.style.overflow = 'auto';
                    document.body.classList.remove('modal-open', 'overflow-hidden');
                    return removed;
                }""")
                if cut:
                    logger.info("Cut/dismissed LinkedIn sign-in modal overlay.")
                    self.capture_screenshot()
                return bool(cut)
            except Exception as exc:
                logger.debug("Modal cut check: %s", exc)
                return False
        return False

    def expand_and_scrape_job_details(self, url: str) -> Dict[str, Any]:
        """
        Open the individual job page, cut the sign-in modal, expand 'Show more',
        perform visible scrolling (real webpage movement), and scrape full job details.
        """
        logger.info("Opening job details page: %s", url)
        self.navigate(url)
        time.sleep(1.2)

        # 1. Cut the modal if present
        self.cut_modal()
        self.dismiss_modals()

        # 2. Click 'Show more' to expand complete description
        if self.use_real_chrome and self.page:
            try:
                self.page.evaluate("""() => {
                    const moreBtn = document.querySelector(
                        'button.show-more-less-html__button--more, button[aria-label*="Show more"], button[data-tracking-control-name*="show_more"]'
                    );
                    if (moreBtn) moreBtn.click();
                }""")
            except Exception:
                pass

            # 3. Visible page scrolling (movement of webpage)
            try:
                self.page.mouse.wheel(0, 450)
                time.sleep(1.0)
                self.cut_modal()
                self.page.mouse.wheel(0, -200)
                time.sleep(0.5)
            except Exception:
                pass

            self.capture_screenshot()

            # 4. Extract comprehensive job details
            try:
                details = self.page.evaluate("""() => {
                    const titleEl = document.querySelector('.top-card-layout__title, .topcard__title, h1');
                    const companyEl = document.querySelector('.topcard__org-name-link, .top-card-layout__first-subline a, .topcard__flavor--black-link');
                    const locEl = document.querySelector('.topcard__flavor--bullet, .top-card-layout__first-subline span:nth-child(2)');
                    const descEl = document.querySelector('.show-more-less-html__markup, .description__text, .decorated-job-posting__details');
                    
                    const criteria = {};
                    const items = Array.from(document.querySelectorAll('.description__job-criteria-list li'));
                    items.forEach(li => {
                        const header = li.querySelector('h3');
                        const val = li.querySelector('span');
                        if (header && val) {
                            criteria[header.textContent.trim().toLowerCase()] = val.textContent.trim();
                        }
                    });

                    return {
                        title: titleEl ? titleEl.textContent.trim() : '',
                        company: companyEl ? companyEl.textContent.trim() : '',
                        location: locEl ? locEl.textContent.trim() : 'Remote',
                        criteria: criteria,
                        description: descEl ? descEl.textContent.trim() : ''
                    };
                }""")
                return details
            except Exception as exc:
                logger.warning("Error extracting job page details: %s", exc)
                return {}
        return {}

    def go_back(self, fallback_url: Optional[str] = None) -> None:
        """Navigate back to previous page in browser history with optional fallback."""
        if self.use_real_chrome and self.page:
            try:
                logger.info("Navigating back to previous page...")
                self.page.go_back(wait_until="domcontentloaded", timeout=20000)
                time.sleep(1.0)
                self.cut_modal()
                self.capture_screenshot()
            except Exception as exc:
                logger.debug("Go back navigation exception: %s. Using fallback.", exc)
                if fallback_url:
                    self.navigate(fallback_url)

    def dismiss_modals(self) -> int:
        """Detect and dismiss common cookie banners, GDPR popups, and modal dialogs."""
        logger.info("Checking for blocking modals, cookie consents, and overlays...")
        if self.use_real_chrome and self.page:
            dismissed = 0
            common_selectors = [
                '#onetrust-accept-btn-handler',
                '#cookie-accept',
                '.cookie-banner button',
                'button[id*="accept"]',
                'button[class*="cookie"]',
                'button[class*="consent"]',
                'button[aria-label="Close"]',
                'button[aria-label="close"]',
                '.modal-close',
                '.close-modal',
                'button:has-text("Accept All")',
                'button:has-text("I Agree")',
                'button:has-text("Got it")',
                'button:has-text("Close")',
                'button:has-text("Dismiss")',
            ]
            for sel in common_selectors:
                try:
                    btn = self.page.locator(sel).first
                    if btn.is_visible(timeout=250):
                        btn.click(timeout=500)
                        dismissed += 1
                except Exception:
                    pass
            if dismissed > 0:
                logger.info("Dismissed %d modal/banner overlay(s).", dismissed)
            return dismissed

        # Webcmd fallback
        script = """
let dismissedCount = 0;
const commonSelectors = [
    '#onetrust-accept-btn-handler',
    '#cookie-accept',
    '.cookie-banner button',
    'button[id*="accept"]',
    'button[class*="cookie"]',
    'button[aria-label="Close"]',
    '.modal-close',
    'button:has-text("Accept All")',
    'button:has-text("I Agree")',
    'button:has-text("Got it")',
    'button:has-text("Close")'
];
for (const sel of commonSelectors) {
    try {
        const el = page.locator(sel).first;
        if (await el.isVisible({ timeout: 300 })) {
            await el.click({ timeout: 600 });
            dismissedCount++;
        }
    } catch (e) {}
}
return { dismissed: dismissedCount };
"""
        try:
            res = self.run_script(script, timeout=10)
            count = res.get("result", {}).get("dismissed", 0)
            if count > 0:
                logger.info("Dismissed %d modal/banner overlay(s).", count)
            return count
        except Exception:
            return 0

    def capture_screenshot(self) -> bool:
        """Capture current viewport to live_screen.png and update dashboard preview."""
        if self.use_real_chrome and self.page:
            try:
                dest_file = Path(AGENT_RULES.get("preview_file", "dashboard/live_screen.png"))
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                self.page.screenshot(path=str(dest_file))
                return True
            except Exception:
                return False

        if not self.session_id:
            return False
        script = """
try {
    await page.screenshot({ path: 'live_screen.png' });
    return { ok: true, url: page.url(), title: await page.title() };
} catch (e) {
    return { ok: false, error: String(e) };
}
"""
        res = self.run_script(script)
        self._extract_live_screenshot(res)
        return bool(res.get("ok"))

    def run_script(
        self,
        js_code: str,
        no_snapshot_diff: bool = True,
        timeout: int = 40
    ) -> Dict[str, Any]:
        """Execute script via Webcmd sandbox if using CLI fallback."""
        if not self.session_id:
            self.start_session()

        fd, temp_path = tempfile.mkstemp(suffix=".js", prefix="webcmd_run_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(js_code)
        self._temp_files.append(temp_path)

        args = [
            "--session", self.session_id,
            "browser", "run",
            "--file", temp_path,
            "-f", "json"
        ]
        if no_snapshot_diff:
            args.append("--no-snapshot-diff")

        raw_out = self._execute_cli(args, timeout=timeout)
        try:
            return json.loads(raw_out)
        except Exception as exc:
            raise WebcmdError(f"Failed to parse JSON result: '{raw_out}' - {exc}") from exc

    def _extract_live_screenshot(self, res: Dict[str, Any]) -> None:
        """Extract and persist live screenshot artifact from Webcmd run output."""
        try:
            artifacts = res.get("artifacts", [])
            for art in artifacts:
                if art.get("filename") == "live_screen.png":
                    art_id = art.get("artifactId")
                    src_file = Path.home() / ".webcmd" / "cache" / "browser-run" / art_id / "live_screen.png"
                    dest_file = Path(AGENT_RULES.get("preview_file", "dashboard/live_screen.png"))
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    if src_file.exists():
                        shutil.copyfile(src_file, dest_file)
        except Exception:
            pass

    def human_delay(self, min_s: float = 2.0, max_s: float = 5.0) -> None:
        """Pause execution for randomized interval to mimic human browsing behavior."""
        delay = round(random.uniform(min_s, max_s), 2)
        logger.info("Sleeping %.2fs (human-in-the-loop delay)...", delay)
        time.sleep(delay)

    def _cleanup_temp_files(self) -> None:
        """Clean up generated temporary JS script files."""
        for path in self._temp_files:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        self._temp_files.clear()

    def __enter__(self):
        self.start_session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_session()
