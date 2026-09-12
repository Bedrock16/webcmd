"""
filter_agent.py - Stage 2: Smart Filter & LLM-based Scoring
Evaluates scraped jobs against user criteria from config.py using OpenAI LLM
(with an intelligent rule-based fallback). Prevents duplicate applications
by cross-referencing state.json.
"""

import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from config import OPENAI_CONFIG, SCORING_RULES, AGENT_RULES

logger = logging.getLogger("FilterAgent")


class FilterAgent:
    """
    Handles LLM-driven job scoring (0-10) and filtering based on user preferences.
    """

    def __init__(self, state_file_path: Optional[str] = None):
        self.state_file = Path(state_file_path or AGENT_RULES["state_file"])
        self.min_passing_score = SCORING_RULES["min_passing_score"]
        self.api_key = OPENAI_CONFIG.get("api_key")
        self.base_url = OPENAI_CONFIG.get("base_url")
        self.model = OPENAI_CONFIG.get("model", "qwen/qwen3.5-omni-plus:free")

    def load_state(self) -> Dict[str, Any]:
        """Load state.json tracking applied, skipped, and paused jobs."""
        if not self.state_file.exists():
            return {"applied": [], "skipped": [], "paused": []}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Could not read state.json: %s. Using blank state.", exc)
            return {"applied": [], "skipped": [], "paused": []}

    def save_state(self, state: Dict[str, Any]) -> None:
        """Persist state.json immediately."""
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as exc:
            logger.error("Failed to write to state.json: %s", exc)

    def get_known_urls(self) -> Set[str]:
        """Return all URLs that have already been applied to, skipped, or paused."""
        state = self.load_state()
        known = set()
        for item in state.get("applied", []):
            if isinstance(item, dict) and item.get("url"):
                known.add(item["url"])
        for item in state.get("skipped", []):
            if isinstance(item, dict) and item.get("url"):
                known.add(item["url"])
        for item in state.get("paused", []):
            if isinstance(item, dict) and item.get("url"):
                known.add(item["url"])
        return known

    def filter_and_score(self, raw_jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Stage 2 entry point: Filter out duplicates and score jobs with the LLM.
        Returns a list of approved jobs (score >= 7.0).
        """
        logger.info("=== STAGE 2: SMART FILTER & SCORING ===")
        known_urls = self.get_known_urls()
        logger.info("Total known URLs in state.json: %d", len(known_urls))

        # 1. Deduplication against state.json
        candidate_jobs = []
        for job in raw_jobs:
            url = job.get("url", "")
            if url in known_urls:
                logger.info("Skipping duplicate job already in state.json: %s", url)
            else:
                candidate_jobs.append(job)

        logger.info("Candidates to score after deduplication: %d", len(candidate_jobs))
        if not candidate_jobs:
            return []

        # 2. Score candidate jobs using OpenAI LLM (or fallback engine)
        scored_jobs = []
        state = self.load_state()

        for job in candidate_jobs:
            eval_result = self._score_job(job)
            job_with_score = {**job, **eval_result}

            score = eval_result.get("score", 0.0)
            passed = eval_result.get("passed", False)
            reasons = eval_result.get("reasons", [])

            logger.info(
                "Job '%s' at '%s' -> Score: %.1f | Passed: %s | Reasons: %s",
                job.get("title"), job.get("company"), score, passed, ", ".join(reasons)
            )

            if passed:
                scored_jobs.append(job_with_score)
                state.setdefault("applied", []).append({
                    "url": job.get("url"),
                    "title": job.get("title"),
                    "company": job.get("company"),
                    "location": job.get("location", "Remote"),
                    "score": score,
                    "reasons": reasons,
                    "status": "qualified",
                    "applied_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                })
            else:
                state.setdefault("skipped", []).append({
                    "url": job.get("url"),
                    "title": job.get("title"),
                    "company": job.get("company"),
                    "location": job.get("location", "Remote"),
                    "score": score,
                    "reasons": reasons,
                    "status": "skipped"
                })

        self.save_state(state)
        logger.info("Stage 2 complete: %d jobs approved (Score >= %.1f).", len(scored_jobs), self.min_passing_score)
        return scored_jobs

    def _score_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """
        Attempt scoring via OpenAI API; if unavailable, use deterministic scoring engine.
        """
        if self.api_key:
            try:
                return self._score_with_openai(job)
            except Exception as exc:
                logger.warning("OpenAI API call failed (%s). Using fallback rule-based evaluator.", exc)
        return self._score_with_fallback_rules(job)

    def _score_with_openai(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """
        Score job with xkiro Qwen LLM (qwen/qwen3.5-omni-plus:free).
        """
        from openai import OpenAI
        client_kwargs = {
            "api_key": self.api_key,
            "default_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        }
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        client = OpenAI(**client_kwargs)

        criteria_text = json.dumps(job.get('criteria', {}), indent=2) if job.get('criteria') else "N/A"
        desc_text = (job.get('description') or job.get('snippet') or '')[:1500]

        prompt = f"""
Evaluate this job opportunity:
Title: {job.get('title')}
Company: {job.get('company')}
Location: {job.get('location')}
Criteria Badges:
{criteria_text}
Full Job Description:
{desc_text}
URL: {job.get('url')}

Scoring Rules:
{SCORING_RULES['scoring_criteria_prompt']}
"""
        response = client.chat.completions.create(
            model=self.model,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "You are a precise job evaluation AI that returns strict JSON."},
                {"role": "user", "content": prompt}
            ]
        )
        content = response.choices[0].message.content.strip()
        # Clean potential markdown code fences from reasoning models
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content)
        score = float(data.get("score", 0.0))
        return {
            "score": score,
            "passed": score >= self.min_passing_score,
            "reasons": data.get("reasons", [])
        }

    def _score_with_fallback_rules(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """
        Simple keyword-overlap fallback scorer (used when LLM API is unavailable).
        Scores based on how many words from the user's target role appear in the job text.
        No hardcoded assumptions about remote, seniority, or tech stack.
        """
        target_role = SCORING_RULES.get("target_role", "Software Developer").lower()
        role_keywords = [kw for kw in target_role.split() if len(kw) > 2]

        text = f"{job.get('title', '')} {job.get('snippet', '')} {job.get('description', '')} {job.get('location', '')}".lower()
        score = 5.0
        reasons = ["Base score: 5.0"]

        # Score based on keyword overlap between target role and job
        matched = [kw for kw in role_keywords if kw in text]
        match_ratio = len(matched) / max(len(role_keywords), 1)

        if match_ratio >= 0.75:
            score += 4.0
            reasons.append(f"+4.0: Strong match — {len(matched)}/{len(role_keywords)} role keywords found ({', '.join(matched)})")
        elif match_ratio >= 0.5:
            score += 2.5
            reasons.append(f"+2.5: Moderate match — {len(matched)}/{len(role_keywords)} role keywords found ({', '.join(matched)})")
        elif match_ratio >= 0.25:
            score += 1.0
            reasons.append(f"+1.0: Partial match — {len(matched)}/{len(role_keywords)} role keywords found ({', '.join(matched)})")
        else:
            score -= 1.0
            reasons.append(f"-1.0: Weak match — only {len(matched)}/{len(role_keywords)} role keywords found")

        score = max(0.0, min(10.0, score))
        passed = score >= self.min_passing_score

        return {
            "score": score,
            "passed": passed,
            "reasons": reasons
        }
