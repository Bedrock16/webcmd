"""
main.py - Master Orchestrator for the Autonomous Job Hunting AI Agent.
Coordinates Stage 1 (Search & Scrape), Stage 2 (Smart Filter), and Stage 3 (Auto-Apply),
ensuring Webcmd session cleanup and complete state tracking.
"""

import argparse
import json
import logging
import sys
from typing import Optional

from config import SEARCH_CONFIG, AGENT_RULES, USER_PROFILE
from webcmd_client import WebcmdClient, WebcmdError
from search_agent import SearchAgent
from filter_agent import FilterAgent

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("JobAgentOrchestrator")


def run_pipeline(
    target_role: Optional[str] = None,
    dry_run: bool = False,
    skip_doctor: bool = False,
    reset_state: bool = False
) -> None:
    """
    Execute the 3-stage job hunting agent workflow.
    """
    role = target_role or SEARCH_CONFIG["target_role"]
    AGENT_RULES["dry_run"] = dry_run

    # Always rebuild the LinkedIn search URL AND scoring rules from the active role
    # so the dashboard input field actually controls what gets searched & how it's scored
    from urllib.parse import quote
    from config import _build_scoring_rules
    import config as _config_module

    SEARCH_CONFIG["target_role"] = role
    SEARCH_CONFIG["search_keywords"] = [kw.strip() for kw in role.split() if len(kw.strip()) > 2]
    for site in SEARCH_CONFIG["target_sites"]:
        if site.get("type") == "linkedin":
            site["url"] = f"https://www.linkedin.com/jobs/search?keywords={quote(role)}&location=Worldwide"
            logger.info("LinkedIn search URL: %s", site["url"])

    # Rebuild scoring rules to match the role (e.g. "Senior" search won't penalize Senior roles)
    new_rules = _build_scoring_rules(role)
    _config_module.SCORING_RULES = new_rules
    logger.info("Scoring rules rebuilt for role '%s' (is_senior=%s, is_junior=%s, wants_remote=%s, tech=%s)",
                role, new_rules["is_senior"], new_rules["is_junior"], new_rules["wants_remote"],
                new_rules.get("matched_tech", []))

    if reset_state:
        logger.info("Resetting state.json history for a clean-slate run...")
        try:
            with open(AGENT_RULES["state_file"], "w", encoding="utf-8") as f:
                json.dump({"applied": [], "skipped": [], "paused": []}, f, indent=2)
            logger.info("state.json reset to empty database.")
        except Exception as err:
            logger.warning("Could not reset state.json: %s", err)

    logger.info("==========================================================")
    logger.info("       AUTONOMOUS JOB HUNTING AI AGENT (WEBCMD + OPENAI)  ")
    logger.info("==========================================================")
    logger.info("Target Role:    %s", role)
    logger.info("Candidate:      %s (%s)", USER_PROFILE["full_name"], USER_PROFILE["email"])
    logger.info("Dry Run Mode:   %s", "ENABLED (No real form submissions)" if dry_run else "DISABLED (Live Submissions)")
    logger.info("State File:     %s", AGENT_RULES["state_file"])
    logger.info("==========================================================")

    # Initialize Webcmd browser client
    client = WebcmdClient(session_name="job-pilot-session")

    try:
        # Pre-flight: Webcmd Doctor check
        if not skip_doctor:
            if not client.check_doctor():
                logger.error("Webcmd environment check failed! Run 'webcmd doctor' to fix setup issues.")
                sys.exit(1)
        else:
            logger.info("Skipping doctor check as requested.")

        # Start browser session
        session_id = client.start_session()
        logger.info("Webcmd session established: %s", session_id)

        # ------------------------------------------------------------------
        # STAGE 1: Search & Scrape
        # ------------------------------------------------------------------
        searcher = SearchAgent(client)
        raw_jobs = searcher.search_and_scrape(role)
        logger.info("Stage 1 Output: Found %d candidate jobs.", len(raw_jobs))

        if not raw_jobs:
            logger.warning("No jobs found matching '%s'. Exiting pipeline.", role)
            return

        # ------------------------------------------------------------------
        # STAGE 2: Smart Filter & LLM-based Scoring
        # ------------------------------------------------------------------
        filterer = FilterAgent()
        approved_jobs = filterer.filter_and_score(raw_jobs)
        logger.info("Stage 2 Output: %d jobs qualified with Score >= 7.0.", len(approved_jobs))

        # ------------------------------------------------------------------
        # FINAL REPORT & METRICS SUMMARY (Scraping & Evaluation Complete)
        # ------------------------------------------------------------------
        logger.info("==========================================================")
        logger.info("       SCRAPING & EVALUATION PIPELINE SUMMARY             ")
        logger.info("==========================================================")
        logger.info("Total Jobs Scraped:        %d", len(raw_jobs))
        logger.info("Qualified Roles (Score>=7):%d", len(approved_jobs))
        logger.info("Filtered Roles (Score<7):  %d", len(raw_jobs) - len(approved_jobs))
        logger.info("State recorded to:         %s", AGENT_RULES["state_file"])
        logger.info("==========================================================")

    except KeyboardInterrupt:
        logger.warning("Pipeline interrupted by user.")
    except WebcmdError as we:
        logger.error("Webcmd browser error: %s", we)
    except Exception as e:
        logger.error("Unexpected error in pipeline: %s", e, exc_info=True)
    finally:
        # Guarantee browser session cleanup
        logger.info("Cleaning up Webcmd browser session...")
        client.close_session()
        logger.info("Browser session closed. Agent execution finished.")


def main():
    parser = argparse.ArgumentParser(description="Autonomous Job Hunting AI Agent with Webcmd and OpenAI")
    parser.add_argument("--role", type=str, default=None, help="Target job role (e.g., 'Remote Junior Python Developer')")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Run without clicking final application submit buttons")
    parser.add_argument("--skip-doctor", action="store_true", default=False, help="Skip preflight webcmd doctor check")
    parser.add_argument("--reset-state", action="store_true", default=False, help="Clear state.json history before running for a fresh test")

    args = parser.parse_args()
    run_pipeline(
        target_role=args.role,
        dry_run=args.dry_run,
        skip_doctor=args.skip_doctor,
        reset_state=args.reset_state
    )


if __name__ == "__main__":
    main()
