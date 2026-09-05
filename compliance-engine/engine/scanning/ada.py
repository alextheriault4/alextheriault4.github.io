"""Accessibility audit: axe-core (WCAG 2.x) injected into the rendered page, plus a
few checks axe leaves to humans."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

AXE_PATH = Path(__file__).parent.parent / "vendor" / "axe.min.js"

# Plain-English explanations for the rules small-business sites most often fail.
PLAIN: dict[str, str] = {
    "image-alt": "images have no text alternative, so screen-reader users hear nothing for them",
    "color-contrast": "text is too low-contrast against its background for people with low vision",
    "link-name": "links have no readable name (icon-only or empty links)",
    "button-name": "buttons have no readable name",
    "label": "form fields have no label, so assistive tech can't say what to type",
    "html-has-lang": "the page doesn't declare its language, so screen readers may mispronounce it",
    "document-title": "the page has no title",
    "heading-order": "headings skip levels, which breaks navigation by heading",
    "page-has-heading-one": "the page has no main heading",
    "landmark-one-main": "the page has no main landmark region",
    "region": "content sits outside any landmark region, so it can't be skipped to",
    "bypass": "there is no way to skip repeated navigation with a keyboard",
    "frame-title": "embedded frames (maps, videos) have no title",
    "meta-viewport": "zooming is disabled, which blocks people who need to enlarge text",
    "list": "lists are built with the wrong markup",
    "duplicate-id": "duplicate element IDs confuse assistive technology",
    "tabindex": "tab order is manipulated in a way that traps keyboard users",
    "aria-allowed-attr": "ARIA attributes are used incorrectly",
    "aria-required-attr": "ARIA roles are missing required attributes",
    "aria-valid-attr-value": "ARIA attributes have invalid values",
    "empty-heading": "some headings are empty",
    "link-in-text-block": "links in paragraphs are distinguishable only by colour",
    "select-name": "dropdowns have no accessible name",
    "input-image-alt": "image buttons have no text alternative",
    "video-caption": "videos have no captions",
    "autocomplete-valid": "form fields have invalid autocomplete hints",
    "nested-interactive": "interactive controls are nested inside each other",
    "scrollable-region-focusable": "scrollable areas can't be reached by keyboard",
    "target-size": "tap targets are too small",
}

IMPACT_WEIGHT = {"critical": 10, "serious": 6, "moderate": 3, "minor": 1}


@dataclass
class Finding:
    kind: str                      # "ada" | "aiseo"
    rule_id: str
    impact: str                    # critical | serious | moderate | minor
    description: str
    page_url: str
    help_url: str | None = None
    count: int = 1
    sample: list[dict[str, Any]] = field(default_factory=list)

    @property
    def plain(self) -> str:
        return PLAIN.get(self.rule_id, self.description)

    def as_row(self, scan_id: int) -> dict[str, Any]:
        return {
            "scan_id": scan_id, "kind": self.kind, "rule_id": self.rule_id, "impact": self.impact,
            "description": self.description, "help_url": self.help_url, "page_url": self.page_url,
            "count": self.count, "sample": self.sample[:5],
        }


def run_axe(page: Page, page_url: str) -> list[Finding]:
    page.add_script_tag(path=str(AXE_PATH))
    result = page.evaluate(
        """async () => await axe.run(document, {
             runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] },
             resultTypes: ['violations']
           })"""
    )
    findings: list[Finding] = []
    for v in result.get("violations", []):
        nodes = v.get("nodes", [])
        findings.append(
            Finding(
                kind="ada", rule_id=v["id"], impact=v.get("impact") or "minor",
                description=v.get("help") or v.get("description", ""), page_url=page_url,
                help_url=v.get("helpUrl"), count=len(nodes),
                sample=[{"target": n.get("target"), "html": (n.get("html") or "")[:300],
                         "data": ((n.get("any") or n.get("all") or [{}])[0] or {}).get("data")} for n in nodes[:8]],
            )
        )
    findings += manual_checks(page, page_url)
    return findings


def manual_checks(page: Page, page_url: str) -> list[Finding]:
    """Checks axe doesn't fully cover but that turn up in demand letters constantly."""
    out: list[Finding] = []
    facts = page.evaluate(
        """() => {
          const links = [...document.querySelectorAll('a[href]')];
          const skip = links.some(a => /skip/i.test(a.textContent || '') && (a.getAttribute('href')||'').startsWith('#'));
          const focusInfo = (() => {
            let removed = false, replaced = false;
            try {
              for (const ss of document.styleSheets) {
                let rules; try { rules = ss.cssRules; } catch (e) { continue; }
                for (const r of rules) {
                  if (!r.selectorText || !/:focus/.test(r.selectorText) || !r.style) continue;
                  const outlineOff = /^(none|0|0px)$/.test((r.style.outline || r.style.outlineStyle || '').trim());
                  const visible = ['box-shadow','border','border-color','background','background-color','text-decoration','outline']
                    .some(p => { const v = r.style.getPropertyValue(p); return v && !/^(none|0|0px|initial|unset)$/.test(v.trim()) && !(p === 'outline' && outlineOff); });
                  if (outlineOff && !visible) removed = true;
                  if (visible) replaced = true;
                }
              }
            } catch (e) {}
            return { removed, replaced };
          })();
          const pdfs = links.filter(a => /\\.pdf(\\?|$)/i.test(a.href)).length;
          const genericLinks = links.filter(a => !a.getAttribute('aria-label') && /^(click here|read more|learn more|here|more)$/i.test((a.textContent||'').trim())).length;
          const autoplay = [...document.querySelectorAll('video[autoplay], audio[autoplay]')].filter(v => !v.muted).length;
          const forms = document.querySelectorAll('form').length;
          return { skip, focusRemoved: focusInfo.removed, focusReplaced: focusInfo.replaced, pdfs, genericLinks, autoplay, forms, links: links.length };
        }"""
    )
    if facts["links"] > 15 and not facts["skip"]:
        out.append(Finding("ada", "skip-link", "moderate", "No 'skip to content' link for keyboard users", page_url,
                           help_url="https://www.w3.org/WAI/WCAG21/Techniques/general/G1"))
    if facts["focusRemoved"] and not facts["focusReplaced"]:
        out.append(Finding("ada", "focus-visible", "serious", "Keyboard focus outline is removed and never replaced", page_url,
                           help_url="https://www.w3.org/WAI/WCAG21/Understanding/focus-visible.html"))
    if facts["genericLinks"] >= 3:
        out.append(Finding("ada", "generic-link-text", "minor", "Several links read only 'click here' / 'read more'", page_url,
                           count=facts["genericLinks"], help_url="https://www.w3.org/WAI/WCAG21/Understanding/link-purpose-in-context.html"))
    if facts["autoplay"]:
        out.append(Finding("ada", "autoplay-media", "serious", "Media autoplays with sound", page_url, count=facts["autoplay"],
                           help_url="https://www.w3.org/WAI/WCAG21/Understanding/audio-control.html"))
    return out


def ada_score(findings: list[Finding]) -> int:
    """0-100. Each distinct rule costs by impact; repeated nodes cost a little more, capped."""
    penalty = 0.0
    seen: dict[str, float] = {}
    for f in findings:
        if f.kind != "ada":
            continue
        w = IMPACT_WEIGHT.get(f.impact, 1)
        extra = min(f.count - 1, 10) * w * 0.15
        seen[f.rule_id] = max(seen.get(f.rule_id, 0), w + extra)
    penalty = sum(seen.values())
    return max(0, int(round(100 - penalty)))
