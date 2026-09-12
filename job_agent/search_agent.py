"""
search_agent.py - Stage 1: Search & Scrape
Navigates target job boards using Webcmd, enters search queries,
and extracts structured job cards (Title, Company, Location, Job URL).
"""

import json
import logging
from typing import Any, Dict, List, Optional
from config import SEARCH_CONFIG, AGENT_RULES
from webcmd_client import WebcmdClient

logger = logging.getLogger("SearchAgent")


class SearchAgent:
    """
    Automates job board discovery, query entry, and job card scraping
    using Webcmd as the browser automation engine.
    Supports running multiple real Chrome browser instances simultaneously in parallel.
    """

    def __init__(self, client: Optional[WebcmdClient] = None):
        self.client = client

    def scrape_site(self, site_info: Dict[str, Any], search_query: str) -> List[Dict[str, Any]]:
        """Scrape a single target job site using this agent's active browser client."""
        site_name = site_info.get("name", "Unknown")
        site_url = site_info.get("url")
        site_type = site_info.get("type", "generic")

        logger.info("[%s] Accessing job board: %s (%s)...", site_name, site_name, site_url)
        try:
            # 1. Navigate to target job board
            nav_info = self.client.navigate(site_url)
            logger.info("[%s] Arrived at '%s' (Title: %s)", site_name, nav_info.get("url"), nav_info.get("title"))

            # 2. Dismiss cookie banners or modal overlays
            self.client.dismiss_modals()

            # 3. Human-in-the-loop delay
            self.client.human_delay(
                AGENT_RULES["min_delay_seconds"],
                AGENT_RULES["max_delay_seconds"]
            )

            # 4. Search bar interaction (if on a search-capable landing page)
            self._attempt_search_bar_input(search_query)

            # 5. Scrape job listings based on site type
            jobs = self._scrape_site_listings(site_type, site_url=site_url)
            logger.info("[%s] Extracted %d jobs from %s", site_name, len(jobs), site_name)
            return jobs

        except Exception as exc:
            logger.error("[%s] Error scraping site %s: %s", site_name, site_name, exc)
            return []

    def search_and_scrape(self, query: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Execute Stage 1: Iterate over configured job boards in parallel,
        opening separate side-by-side Chrome browser windows for each site.
        """
        import concurrent.futures

        search_query = query or SEARCH_CONFIG["target_role"]
        target_sites = SEARCH_CONFIG.get("target_sites", [])
        logger.info("=== STAGE 1: PARALLEL SEARCH & SCRAPE for '%s' across %d boards ===", search_query, len(target_sites))

        # 1. Clean up any stale/dangling browser processes ONCE before launching workers
        WebcmdClient.close_stale_browsers()

        # Define side-by-side screen positioning for parallel windows:
        # Window 0 (Left side):  pos 0,50   size 950,900 (e.g. LinkedIn)
        # Window 1 (Right side): pos 960,50  size 950,900 (e.g. Naukri)
        layouts = [
            {"pos": "0,50", "size": "950,900"},
            {"pos": "960,50", "size": "950,900"},
            {"pos": "50,100", "size": "950,850"},
            {"pos": "900,100", "size": "950,850"},
        ]

        def _worker(idx: int, site_info: Dict[str, Any]) -> List[Dict[str, Any]]:
            layout = layouts[idx % len(layouts)]
            site_name = site_info.get("name", f"site-{idx}")
            session_name = f"job-pilot-{site_name.lower().replace(' ', '-')}"

            logger.info(">>> Launching parallel browser for [%s] at screen position %s...", site_name, layout["pos"])
            screenshot_name = f"live_screen_{site_name.lower().replace(' ', '_')}.png"
            worker_client = WebcmdClient(
                session_name=session_name,
                window_pos=layout["pos"],
                window_size=layout["size"],
                screenshot_file=screenshot_name
            )
            try:
                # Do NOT clean stale browsers inside worker - they would kill each other!
                worker_client.start_session(clean_stale=False)
                worker_agent = SearchAgent(client=worker_client)
                return worker_agent.scrape_site(site_info, search_query)
            except Exception as e:
                logger.error("Exception in parallel worker [%s]: %s", site_name, e)
                return []
            finally:
                logger.info("Closing parallel browser session for [%s]...", site_name)
                worker_client.close_session()

        all_scraped_jobs: List[Dict[str, Any]] = []

        # Run both scrapers concurrently in thread pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(target_sites))) as executor:
            future_map = {
                executor.submit(_worker, idx, site_info): site_info.get("name", f"Site-{idx}")
                for idx, site_info in enumerate(target_sites)
            }
            for future in concurrent.futures.as_completed(future_map):
                s_name = future_map[future]
                try:
                    site_jobs = future.result()
                    logger.info("Worker [%s] finished with %d jobs.", s_name, len(site_jobs))
                    all_scraped_jobs.extend(site_jobs)
                except Exception as exc:
                    logger.error("Worker [%s] generated an exception: %s", s_name, exc)

        # Deduplicate by URL in scraped batch
        seen_urls = set()
        unique_jobs: List[Dict[str, Any]] = []
        for job in all_scraped_jobs:
            url = job.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_jobs.append(job)

        logger.info("Stage 1 complete: Scraped %d unique jobs across all boards in parallel.", len(unique_jobs))
        return unique_jobs

    def _attempt_search_bar_input(self, query: str) -> None:
        """
        Detect search input fields on the page, type query, and submit.
        """
        script = """
const searchSelectors = [
    'input[type="search"]',
    'input[name*="search"]',
    'input[name*="query"]',
    'input[name*="keyword"]',
    'input[placeholder*="Search" i]',
    'input[placeholder*="Title" i]',
    'input[placeholder*="job" i]',
    '#search-input',
    '#search'
];

let inputEl = null;
for (const sel of searchSelectors) {
    const el = page.locator(sel).first;
    if (await el.isVisible({ timeout: 500 }).catch(() => false)) {
        inputEl = el;
        break;
    }
}

if (inputEl) {
    await inputEl.scrollIntoViewIfNeeded();
    await inputEl.fill(__QUERY_PLACEHOLDER__);
    await page.keyboard.press('Enter');
    return { searched: true };
}
return { searched: false };
""".replace("__QUERY_PLACEHOLDER__", json.dumps(query))
        try:
            res = self.client.run_script(script, timeout=12)
            if res.get("result", {}).get("searched"):
                logger.info("Typed search query into search bar.")
                self.client.human_delay(2.0, 4.0)
        except Exception as exc:
            logger.debug("Search input auto-fill skipped: %s", exc)

    def _scrape_site_listings(self, site_type: str, site_url: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Execute targeted scraping scripts in the QuickJS sandbox or real Chrome.
        """
        if site_type == "remoteok":
            return self._scrape_remoteok()
        elif site_type == "weworkremotely":
            return self._scrape_weworkremotely()
        elif site_type == "hn_jobs":
            return self._scrape_hn_jobs()
        elif site_type == "linkedin":
            return self._scrape_linkedin(site_url=site_url)
        elif site_type == "naukri":
            return self._scrape_naukri(site_url=site_url)
        else:
            return self._scrape_generic_listings()

    def _scrape_remoteok(self) -> List[Dict[str, Any]]:
        """Scrape jobs from RemoteOK listing table."""
        script = """
const jobs = await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('tr.job'));
    return rows.slice(0, 10).map(row => {
        const titleEl = row.querySelector('h2[itemprop="title"], .title');
        const companyEl = row.querySelector('h3[itemprop="name"], .company');
        const locationEl = row.querySelector('.location');
        const linkEl = row.querySelector('a.preventLink, a[itemprop="url"]');
        const tags = Array.from(row.querySelectorAll('.tag h3')).map(t => t.innerText.trim());

        const url = linkEl ? (linkEl.href.startsWith('http') ? linkEl.href : 'https://remoteok.com' + linkEl.getAttribute('href')) : '';
        return {
            title: titleEl ? titleEl.innerText.trim() : 'Software Developer',
            company: companyEl ? companyEl.innerText.trim() : 'RemoteOK Partner',
            location: locationEl ? locationEl.innerText.trim() : 'Remote (Worldwide)',
            url: url,
            snippet: tags.join(', '),
            source: 'RemoteOK'
        };
    }).filter(j => j.url && j.title);
});
return jobs;
"""
        res = self.client.run_script(script, timeout=20)
        return res.get("result", [])

    def _scrape_weworkremotely(self) -> List[Dict[str, Any]]:
        """Scrape jobs from WeWorkRemotely category listing."""
        script = """
const jobs = await page.evaluate(() => {
    const items = Array.from(document.querySelectorAll('section.jobs article li:not(.view-all)'));
    return items.slice(0, 10).map(item => {
        const titleEl = item.querySelector('.title');
        const companyEl = item.querySelector('.company');
        const regionEl = item.querySelector('.region');
        const linkEl = item.querySelector('a[href*="/remote-jobs/"]');

        const url = linkEl ? (linkEl.href.startsWith('http') ? linkEl.href : 'https://weworkremotely.com' + linkEl.getAttribute('href')) : '';
        return {
            title: titleEl ? titleEl.innerText.trim() : '',
            company: companyEl ? companyEl.innerText.trim() : '',
            location: regionEl ? regionEl.innerText.trim() : 'Remote',
            url: url,
            snippet: 'Backend programming opportunity from WeWorkRemotely',
            source: 'WeWorkRemotely'
        };
    }).filter(j => j.url && j.title);
});
return jobs;
"""
        res = self.client.run_script(script, timeout=20)
        return res.get("result", [])

    def _scrape_hn_jobs(self) -> List[Dict[str, Any]]:
        """Scrape jobs from Hacker News jobs board."""
        script = """
const jobs = await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('.athing'));
    return rows.slice(0, 10).map(row => {
        const titleEl = row.querySelector('.titleline > a');
        if (!titleEl) return null;
        const rawText = titleEl.innerText.trim();
        const url = titleEl.href;
        
        // Parse company & title format: "Company is hiring Title..."
        let company = 'YC Startup';
        let title = rawText;
        if (rawText.includes('Is Hiring') || rawText.includes('is hiring')) {
            const parts = rawText.split(/is hiring/i);
            company = parts[0].trim();
            title = parts[1] ? parts[1].trim() : rawText;
        }

        return {
            title: title,
            company: company,
            location: 'Remote / US',
            url: url,
            snippet: rawText,
            source: 'HackerNews'
        };
    }).filter(Boolean);
});
return jobs;
"""
        res = self.client.run_script(script, timeout=20)
        return res.get("result", [])

    def _scrape_generic_listings(self) -> List[Dict[str, Any]]:
        """Fallback scraper looking for standard job card patterns in DOM."""
        script = """
const jobs = await page.evaluate(() => {
    const jobLinks = Array.from(document.querySelectorAll('a[href*="job"], a[href*="career"], a[href*="position"]'));
    return jobLinks.slice(0, 8).map(a => ({
        title: a.innerText.trim() || 'Software Engineer',
        company: 'Online Hiring Company',
        location: 'Remote',
        url: a.href,
        snippet: a.innerText.trim(),
        source: 'WebSearch'
    })).filter(j => j.url && j.title.length > 5);
});
return jobs;
"""
        res = self.client.run_script(script, timeout=20)
        return res.get("result", [])

    def _scrape_linkedin(self, site_url: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Scrape jobs from LinkedIn with full browser movement:
        1. Cuts the sign-in modal overlay on the search results page.
        2. Visibly scrolls the search results to load candidate cards.
        3. For each candidate job:
           - Opens the individual job page.
           - Cuts the 'Sign in to view more jobs' modal immediately.
           - Clicks 'Show more' to expand the full description.
           - Visibly scrolls down & up through the job description and requirements.
           - Extracts full criteria badges, exact title, company, location, and description.
           - Navigates back to the search page so the user sees real webpage movement.
        """
        import time

        if hasattr(self.client, "scrape_linkedin_cards") and getattr(self.client, "use_real_chrome", False):
            # 1. Immediately cut sign-in modal on search page
            self.client.cut_modal()

            # 2. Visible scroll on search results page
            if self.client.page:
                try:
                    logger.info("Scrolling search results list to populate jobs...")
                    self.client.page.mouse.wheel(0, 500)
                    time.sleep(1.2)
                    self.client.cut_modal()
                    self.client.page.mouse.wheel(0, -200)
                    time.sleep(0.8)
                except Exception:
                    pass

            # 3. Extract candidate job cards from the search page
            cards = self.client.scrape_linkedin_cards(limit=5)
            if not cards:
                logger.warning("No LinkedIn job cards detected on search results page.")
                return []

            total_jobs = len(cards)
            logger.info("Found %d candidate listings. Now opening each job page individually to scrape data and navigate...", total_jobs)

            enriched_jobs: List[Dict[str, Any]] = []

            for idx, card in enumerate(cards, start=1):
                job_url = card.get("url")
                if not job_url:
                    continue

                logger.info("------------------------------------------------------------")
                logger.info(">>> [JOB %d/%d] Opening: '%s' at '%s'", idx, total_jobs, card.get("title"), card.get("company"))
                logger.info("Navigating to: %s", job_url)

                # Step A: Navigate to the individual job page
                self.client.navigate(job_url)
                time.sleep(1.2)

                # Step B: Immediately cut the sign-in modal if present
                self.client.cut_modal()

                # Step C: Click 'Show more' to expand the complete description
                if self.client.page:
                    try:
                        self.client.page.evaluate("""() => {
                            const moreBtns = [
                                'button.show-more-less-html__button--more',
                                'button[aria-label*="Show more" i]',
                                'button[data-tracking-control-name*="show_more"]',
                                '.show-more-less-html__button'
                            ];
                            for (const sel of moreBtns) {
                                const b = document.querySelector(sel);
                                if (b) { b.click(); break; }
                            }
                        }""")
                    except Exception:
                        pass

                    # Step D: Visible page movement & scrolling down through the job description
                    try:
                        logger.info("Scrolling job posting to inspect description & requirements...")
                        self.client.page.mouse.wheel(0, 450)
                        time.sleep(1.2)
                        self.client.cut_modal()
                        self.client.page.mouse.wheel(0, 300)
                        time.sleep(1.0)
                        self.client.cut_modal()
                        self.client.page.mouse.wheel(0, -250)
                        time.sleep(0.8)
                    except Exception:
                        pass

                    self.client.capture_screenshot()

                    # Step E: Extract comprehensive job details from open page
                    try:
                        details = self.client.page.evaluate("""() => {
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
                    except Exception as exc:
                        logger.warning("Error reading job DOM: %s", exc)
                        details = {}

                    # Merge full details
                    full_title = details.get("title") or card.get("title")
                    full_company = details.get("company") or card.get("company")
                    full_loc = details.get("location") or card.get("location")
                    full_desc = details.get("description") or card.get("snippet", "")
                    criteria = details.get("criteria", {})

                    enriched_job = {
                        **card,
                        "title": full_title,
                        "company": full_company,
                        "location": full_loc,
                        "criteria": criteria,
                        "description": full_desc,
                        "snippet": full_desc[:300] if full_desc else card.get("snippet", ""),
                        "source": "LinkedIn"
                    }
                    enriched_jobs.append(enriched_job)
                    logger.info("Scraped full details: '%s' (%d chars description, criteria: %s)",
                                full_title, len(full_desc), list(criteria.keys()))

                    # Step F: "and then get back like this":
                    # Navigate back to search results page so user sees browser return
                    logger.info("Getting back to search results page...")
                    self.client.go_back(fallback_url=site_url)
                    self.client.cut_modal()
                    time.sleep(1.5)
                else:
                    enriched_jobs.append(card)

            logger.info("Completed live page navigation and scraping for %d LinkedIn jobs.", len(enriched_jobs))
            return enriched_jobs

        # Fallback script for non-real Chrome
        script = """
const jobs = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll('ul.jobs-search__results-list li, .base-card, .job-search-card'));
    const results = [];
    for (const card of cards.slice(0, 10)) {
        const titleEl = card.querySelector('.base-search-card__title, h3');
        const companyEl = card.querySelector('.base-search-card__subtitle, h4');
        const locEl = card.querySelector('.job-search-card__location');
        const linkEl = card.querySelector('a.base-card__full-link, a');

        const title = titleEl ? titleEl.textContent.trim() : '';
        const company = companyEl ? companyEl.textContent.trim() : 'Company on LinkedIn';
        const location = locEl ? locEl.textContent.trim() : 'Remote';
        let url = linkEl ? linkEl.href : '';
        if (url && url.includes('?')) {
            url = url.split('?')[0];
        }

        if (title && url) {
            results.push({
                title: title,
                company: company,
                location: location,
                snippet: title + ' at ' + company + ' (' + location + ') - LinkedIn Jobs',
                url: url,
                source: 'LinkedIn'
            });
        }
    }
    return results;
});
return jobs;
"""
        try:
            res = self.client.run_script(script, timeout=20)
            return res.get("result", [])
        except Exception as exc:
            logger.warning("Error during LinkedIn scraping: %s", exc)
            return []

    def _scrape_naukri(self, site_url: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Scrape jobs from Naukri.com with full browser movement:
        1. Navigate to Naukri search results page.
        2. Dismiss any login/popup overlays.
        3. Scroll through listings to load job cards.
        4. For each job card:
           - Open the individual job page in the same tab.
           - Dismiss popups, expand full description.
           - Scroll visibly through the job content.
           - Extract title, company, location, experience, skills, and full description.
           - Navigate back to the search results.
        """
        import time

        # Helper to dismiss Naukri popups (login prompts, chatbots, etc.)
        def _dismiss_naukri_popups():
            if not self.client.page:
                return
            try:
                self.client.page.evaluate("""() => {
                    // Close login/signup popup
                    const closeBtns = document.querySelectorAll(
                        '.login-layer .crossIcon, [class*="CloseButton"], [class*="close-btn"], ' +
                        '#login_layer .cross-icon, .chatbot_closeButton, ' +
                        'button[title="Close"], [data-ga-track="close"], ' +
                        '.styles_closebtn__rQCKI'
                    );
                    closeBtns.forEach(b => { try { b.click(); } catch(e) {} });
                    
                    // Remove overlay/backdrop elements
                    const overlays = document.querySelectorAll(
                        '.login-layer, #login_layer, .chatbot_container, ' +
                        '[class*="LoginOverlay"], [class*="modal-overlay"], ' +
                        '.styles_overlay__XMRXv'
                    );
                    overlays.forEach(el => el.remove());
                    
                    // Restore body scrolling
                    document.body.style.overflow = 'auto';
                    document.body.style.position = '';
                    document.documentElement.style.overflow = 'auto';
                }""")
            except Exception:
                pass

        if hasattr(self.client, 'page') and self.client.page:
            # 1. Dismiss popups on search page
            time.sleep(1.5)
            _dismiss_naukri_popups()

            # 2. Scroll search results to load job cards
            try:
                logger.info("Scrolling Naukri search results to load job cards...")
                self.client.page.mouse.wheel(0, 600)
                time.sleep(1.5)
                _dismiss_naukri_popups()
                self.client.page.mouse.wheel(0, 400)
                time.sleep(1.0)
                _dismiss_naukri_popups()
            except Exception:
                pass

            # 3. Extract job cards from search results
            try:
                cards = self.client.page.evaluate("""() => {
                    const jobCards = Array.from(document.querySelectorAll(
                        'article.jobTuple, .srp-jobtuple-wrapper, [class*="jobTuple"], ' +
                        '.list .cust-job-tuple, .cust-job-tuple, [data-job-id]'
                    ));
                    
                    // Fallback: try broader selectors if no cards found
                    const allCards = jobCards.length > 0 ? jobCards : 
                        Array.from(document.querySelectorAll('.srp-jobtuple-wrapper a, .jobTupleHeader a'));
                    
                    return allCards.slice(0, 8).map(card => {
                        const titleEl = card.querySelector(
                            '.title, .jobTupleHeader a, [class*="title"], a.title, ' +
                            'a[class*="JobTitle"], .row1 a, h2 a'
                        );
                        const companyEl = card.querySelector(
                            '.comp-name, .subTitle, [class*="companyInfo"], ' +
                            '.row2 .comp-name, a.subTitle'
                        );
                        const locEl = card.querySelector(
                            '.loc, .locWdth, [class*="location"], .row3 .loc, .ni-job-tuple-icon-srp-location + span'
                        );
                        const expEl = card.querySelector(
                            '.exp, .expwdth, [class*="experience"], .row3 .exp, .ni-job-tuple-icon-srp-experience + span'
                        );
                        const salaryEl = card.querySelector(
                            '.sal, .ni-job-tuple-icon-srp-rupee + span, [class*="salary"]'
                        );
                        
                        let url = '';
                        const linkEl = titleEl && titleEl.tagName === 'A' ? titleEl : 
                            card.querySelector('a.title, a[class*="title"], a[href*="naukri.com/job-listings"]');
                        if (linkEl) url = linkEl.href || '';
                        
                        // Also try the card itself if it's a link
                        if (!url) {
                            const anyLink = card.querySelector('a[href*="job-listings"], a[href*="/job/"]');
                            if (anyLink) url = anyLink.href;
                        }

                        const snippet = card.querySelector('.job-desc, .ellipsis, [class*="description"]');
                        
                        return {
                            title: titleEl ? titleEl.textContent.trim() : '',
                            company: companyEl ? companyEl.textContent.trim() : '',
                            location: locEl ? locEl.textContent.trim() : '',
                            experience: expEl ? expEl.textContent.trim() : '',
                            salary: salaryEl ? salaryEl.textContent.trim() : '',
                            snippet: snippet ? snippet.textContent.trim() : '',
                            url: url,
                            source: 'Naukri'
                        };
                    }).filter(j => j.title && j.url);
                }""")
            except Exception as exc:
                logger.warning("Error extracting Naukri job cards: %s", exc)
                cards = []

            if not cards:
                logger.warning("No Naukri job cards detected on search results page.")
                return []

            total_jobs = len(cards)
            logger.info("Found %d Naukri listings. Now opening each job page...", total_jobs)

            enriched_jobs: List[Dict[str, Any]] = []

            for idx, card in enumerate(cards, start=1):
                job_url = card.get("url")
                if not job_url:
                    continue

                logger.info("------------------------------------------------------------")
                logger.info(">>> [NAUKRI JOB %d/%d] Opening: '%s' at '%s'", idx, total_jobs, card.get("title"), card.get("company"))
                logger.info("Navigating to: %s", job_url)

                # Step A: Navigate to job page
                self.client.navigate(job_url)
                time.sleep(1.5)

                # Step B: Dismiss popups
                _dismiss_naukri_popups()

                # Step C: Scroll through job details
                if self.client.page:
                    try:
                        logger.info("Scrolling job posting to inspect description & requirements...")
                        self.client.page.mouse.wheel(0, 500)
                        time.sleep(1.2)
                        _dismiss_naukri_popups()
                        self.client.page.mouse.wheel(0, 400)
                        time.sleep(1.0)
                        self.client.page.mouse.wheel(0, -200)
                        time.sleep(0.8)
                    except Exception:
                        pass

                    self.client.capture_screenshot()

                    # Step D: Extract full job details
                    try:
                        details = self.client.page.evaluate("""() => {
                            const titleEl = document.querySelector(
                                'h1.jd-header-title, .jd-header-title, h1[class*="title"], .styles_jd-header-title'
                            );
                            const companyEl = document.querySelector(
                                '.jd-header-comp-name a, .jd-header-comp-name, [class*="comp-name"] a'
                            );
                            const locEl = document.querySelector(
                                '.loc .locWdth, .location .locWdth, [class*="location"]'
                            );
                            const expEl = document.querySelector(
                                '.exp .exp-info, .experience, [class*="experience"]'
                            );
                            const salEl = document.querySelector(
                                '.sal .salary, .salary, [class*="salary"]'
                            );
                            
                            // Full description
                            const descEl = document.querySelector(
                                '.styles_JDC__dang-inner-html__h0K4t, .job-desc, .dang-inner-html, ' + 
                                '[class*="job-desc"], .styles_job-desc-container'
                            );
                            
                            // Key skills
                            const skills = Array.from(document.querySelectorAll(
                                '.key-skill a, .chip_chip, [class*="chip"] a, .styles_key-skill__GIPn_ a, ' +
                                '.key-skill .chip-body, a.styles_chip-body'
                            )).map(s => s.textContent.trim());
                            
                            // Other details (role, industry, etc.)
                            const otherDetails = {};
                            const detailRows = document.querySelectorAll(
                                '.other-details .details-body, .styles_details__Y424J, [class*="other-detail"]'
                            );
                            detailRows.forEach(row => {
                                const label = row.querySelector('.label, [class*="label"]');
                                const value = row.querySelector('.value, [class*="value"]');
                                if (label && value) {
                                    otherDetails[label.textContent.trim().toLowerCase()] = value.textContent.trim();
                                }
                            });
                            
                            return {
                                title: titleEl ? titleEl.textContent.trim() : '',
                                company: companyEl ? companyEl.textContent.trim() : '',
                                location: locEl ? locEl.textContent.trim() : '',
                                experience: expEl ? expEl.textContent.trim() : '',
                                salary: salEl ? salEl.textContent.trim() : '',
                                description: descEl ? descEl.textContent.trim() : '',
                                skills: skills,
                                other_details: otherDetails
                            };
                        }""")
                    except Exception as exc:
                        logger.warning("Error reading Naukri job DOM: %s", exc)
                        details = {}

                    # Merge details
                    full_title = details.get("title") or card.get("title")
                    full_company = details.get("company") or card.get("company")
                    full_loc = details.get("location") or card.get("location")
                    full_desc = details.get("description") or card.get("snippet", "")
                    skills = details.get("skills", [])

                    enriched_job = {
                        **card,
                        "title": full_title,
                        "company": full_company,
                        "location": full_loc,
                        "experience": details.get("experience") or card.get("experience", ""),
                        "salary": details.get("salary") or card.get("salary", ""),
                        "criteria": {
                            "skills": ", ".join(skills) if skills else "",
                            **details.get("other_details", {})
                        },
                        "description": full_desc,
                        "snippet": full_desc[:300] if full_desc else card.get("snippet", ""),
                        "source": "Naukri"
                    }
                    enriched_jobs.append(enriched_job)
                    logger.info("Scraped: '%s' @ %s (%d chars desc, %d skills)",
                                full_title, full_company, len(full_desc), len(skills))

                    # Step E: Navigate back to search results
                    logger.info("Getting back to Naukri search results...")
                    self.client.go_back(fallback_url=site_url)
                    _dismiss_naukri_popups()
                    time.sleep(1.5)
                else:
                    enriched_jobs.append(card)

            logger.info("Completed Naukri scraping: %d jobs collected.", len(enriched_jobs))
            return enriched_jobs

        # Fallback for non-real Chrome
        logger.warning("Naukri scraper requires real Chrome (headless=False). Skipping.")
        return []
