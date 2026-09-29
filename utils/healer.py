"""
AI-Powered Self-Healing Layer
==============================
When a Playwright locator action times out, this module:

  1. Captures a trimmed snippet of the live DOM around the failure.
  2. Sends the failed selector + an intent description + that DOM snippet
     to a free LLM (Groq's hosted Llama 3) and asks for ONE corrected CSS
     selector, returned as strict JSON.
  3. Validates the suggested selector actually resolves to exactly one
     visible element on the current page (never trusts the LLM blindly).
  4. Re-runs the original action against the healed selector.
  5. Logs a formal "Self-Healed Event" to Allure — original selector,
     healed selector, LLM rationale, and a screenshot — so the healing is
     auditable, not silent magic.

If any step fails (no API key, malformed LLM response, healed selector
doesn't resolve), the ORIGINAL exception is re-raised with healing context
attached — a healer that hides real breakage is worse than no healer.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

import allure
from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from utils.config import settings

logger = logging.getLogger("qa_platform.healer")

_MAX_DOM_CHARS = 6000  # keep the LLM prompt small, fast, and cheap

_SYSTEM_PROMPT = (
    "You are a senior test automation engineer performing selector repair. "
    "Given a broken CSS selector, the intent it was meant to satisfy, and a "
    "snippet of the current page HTML, find the ONE element in the HTML that "
    "now matches that intent and return a precise CSS selector for it. "
    "Respond with ONLY a JSON object of the exact shape "
    '{"selector": "<css selector>", "confidence": <0.0-1.0>, "reasoning": "<one short sentence>"} '
    "and nothing else — no markdown, no prose outside the JSON."
)


class SelfHealingError(RuntimeError):
    """Raised when healing was attempted but could not produce a working selector."""


@dataclass
class HealResult:
    original_selector: str
    healed_selector: str
    confidence: float
    reasoning: str


class SelfHealer:
    """Stateful per-session healer so repeated failures reuse one LLM client."""

    def __init__(self) -> None:
        self._client = None
        if settings.self_healing_available:
            from groq import Groq  # imported lazily so the package is optional at runtime

            self._client = Groq(api_key=settings.groq_api_key)

    # ------------------------------------------------------------------
    # Public API used by BasePage
    # ------------------------------------------------------------------
    def run_with_healing(
        self,
        page: Page,
        selector: str,
        description: str,
        action: Callable[[Locator], None],
    ) -> None:
        """
        Attempts `action` against `selector` with a short timeout. On
        timeout, tries to heal the selector and re-runs `action` once
        against the healed locator.
        """
        locator = page.locator(selector)
        try:
            action(locator)
            return
        except PlaywrightTimeoutError as exc:
            logger.warning("Selector failed, attempting self-heal: %s", selector)
            self._attempt_heal_and_rerun(page, selector, description, action, exc)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _attempt_heal_and_rerun(
        self,
        page: Page,
        original_selector: str,
        description: str,
        action: Callable[[Locator], None],
        original_exc: Exception,
    ) -> None:
        if not settings.self_healing_available:
            allure.attach(
                f"Selector '{original_selector}' failed and self-healing is disabled "
                f"or GROQ_API_KEY is not set.",
                name="Self-Healing Skipped",
                attachment_type=allure.attachment_type.TEXT,
            )
            raise original_exc

        dom_snapshot = self._capture_relevant_dom(page)
        last_error: Exception = original_exc

        for attempt in range(1, settings.max_heal_retries + 1):
            try:
                heal_result = self._query_llm_for_selector(
                    original_selector, description, dom_snapshot
                )
            except Exception as llm_error:  # network / parsing / API errors
                last_error = llm_error
                logger.error("Heal attempt %d: LLM query failed: %s", attempt, llm_error)
                continue

            healed_locator = page.locator(heal_result.healed_selector)
            if healed_locator.count() != 1:
                last_error = SelfHealingError(
                    f"Healed selector '{heal_result.healed_selector}' resolved to "
                    f"{healed_locator.count()} elements (expected exactly 1)."
                )
                logger.error(str(last_error))
                continue

            try:
                action(healed_locator)
            except Exception as rerun_error:
                last_error = rerun_error
                continue

            self._log_heal_event(original_selector, heal_result, page, success=True)
            return

        # Every attempt failed — surface the ORIGINAL failure, with healing
        # context attached, rather than pretending nothing happened.
        allure.attach(
            f"Original selector: {original_selector}\n"
            f"Description: {description}\n"
            f"Heal attempts exhausted ({settings.max_heal_retries}).\n"
            f"Last error: {last_error}",
            name="Self-Healing Failed",
            attachment_type=allure.attachment_type.TEXT,
        )
        raise original_exc

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(2),
        wait=wait_fixed(1),
        reraise=True,
    )
    def _query_llm_for_selector(
        self, original_selector: str, description: str, dom_snapshot: str
    ) -> HealResult:
        if self._client is None:
            raise SelfHealingError("Groq client not initialised (missing GROQ_API_KEY).")

        user_prompt = (
            f"Broken selector: {original_selector}\n"
            f"Intent: {description}\n\n"
            f"Current page HTML snippet:\n{dom_snapshot}"
        )

        response = self._client.chat.completions.create(
            model=settings.groq_model,
            temperature=0,
            max_tokens=300,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw_content = response.choices[0].message.content.strip()
        raw_content = raw_content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        try:
            parsed = json.loads(raw_content)
            selector = str(parsed["selector"])
            confidence = float(parsed.get("confidence", 0.0))
            reasoning = str(parsed.get("reasoning", ""))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise SelfHealingError(f"Unparseable LLM response: {raw_content!r}") from exc

        if not selector:
            raise SelfHealingError("LLM returned an empty selector.")

        return HealResult(
            original_selector=original_selector,
            healed_selector=selector,
            confidence=confidence,
            reasoning=reasoning,
        )

    @staticmethod
    def _capture_relevant_dom(page: Page) -> str:
        """Grabs the body HTML, trimmed to keep the LLM prompt small and cheap."""
        try:
            html = page.locator("body").inner_html()
        except Exception:
            html = page.content()
        return html[:_MAX_DOM_CHARS]

    @staticmethod
    def _log_heal_event(
        original_selector: str, heal_result: HealResult, page: Page, *, success: bool
    ) -> None:
        allure.attach(
            json.dumps(
                {
                    "event": "Self-Healed Event",
                    "original_selector": original_selector,
                    "healed_selector": heal_result.healed_selector,
                    "confidence": heal_result.confidence,
                    "reasoning": heal_result.reasoning,
                    "success": success,
                },
                indent=2,
            ),
            name="Self-Healed Event",
            attachment_type=allure.attachment_type.JSON,
        )
        try:
            allure.attach(
                page.screenshot(),
                name="Post-Heal Screenshot",
                attachment_type=allure.attachment_type.PNG,
            )
        except Exception:
            pass  # screenshot is best-effort; never let reporting break the test
        logger.info(
            "Self-healed '%s' -> '%s' (confidence=%.2f): %s",
            original_selector,
            heal_result.healed_selector,
            heal_result.confidence,
            heal_result.reasoning,
        )
