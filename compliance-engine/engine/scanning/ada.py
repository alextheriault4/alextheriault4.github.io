"""Accessibility detection.

Two sources feed the checklist:

* **axe-core**, which reports every rule as violated, passed, incomplete or inapplicable.
  Mapping all four (not just violations) is what makes an honest percentage possible: we
  know the denominator, not just the failures.
* **our own probes** for things axe deliberately leaves alone - a removed focus outline
  with no replacement, a missing accessibility statement, colour used as the only signal.

Both emit ``CheckResult`` keyed to a check in ``engine/standards/checks.py``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from ..standards import AXE_RULE_TO_CHECK, BY_ID, CheckResult

AXE_PATH = Path(__file__).parent.parent / "vendor" / "axe.min.js"

AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa", "best-practice"]

# Kept so existing callers and stored scans keep working; impact is only used for display.
IMPACT_BY_WEIGHT = {10: "critical", 9: "critical", 8: "serious", 7: "serious", 6: "serious",
                    5: "moderate", 4: "moderate", 3: "minor", 2: "minor", 1: "minor"}


@dataclass
class PageAudit:
    """Raw per-page findings, before results are merged across the site."""

    url: str
    statuses: dict[str, str] = field(default_factory=dict)       # check id -> status
    counts: dict[str, int] = field(default_factory=dict)
    evidence: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)

    def record(self, check_id: str, status: str, *, count: int = 0, detail: str = "",
               evidence: list[dict[str, Any]] | None = None) -> None:
        if check_id not in BY_ID:
            return
        # Within one page, a failure always wins over a pass from a different rule that
        # maps to the same check.
        rank = {"fail": 3, "needs_review": 2, "pass": 1, "not_applicable": 0}
        if rank.get(status, 0) < rank.get(self.statuses.get(check_id, "not_applicable"), 0):
            return
        self.statuses[check_id] = status
        if count:
            self.counts[check_id] = self.counts.get(check_id, 0) + count
        if detail:
            self.details[check_id] = detail
        if evidence:
            self.evidence.setdefault(check_id, []).extend(evidence)


def run_axe(page: Page, page_url: str) -> PageAudit:
    """Run axe and fold every rule outcome into the checklist."""
    audit = PageAudit(url=page_url)
    page.add_script_tag(path=str(AXE_PATH))
    result = page.evaluate(
        """async (tags) => await axe.run(document, {
             runOnly: { type: 'tag', values: tags },
             resultTypes: ['violations']
           })""",
        AXE_TAGS,
    )
    for bucket, status in (("violations", "fail"), ("incomplete", "needs_review"),
                           ("passes", "pass"), ("inapplicable", "not_applicable")):
        for rule in result.get(bucket, []):
            check_id = AXE_RULE_TO_CHECK.get(rule["id"])
            if not check_id:
                continue
            nodes = rule.get("nodes", [])
            audit.record(
                check_id, status, count=len(nodes),
                detail=(rule.get("help") or "") if status == "fail" else "",
                evidence=[{
                    "rule": rule["id"],
                    "target": n.get("target"),
                    "html": (n.get("html") or "")[:300],
                    "data": ((n.get("any") or n.get("all") or [{}])[0] or {}).get("data"),
                } for n in nodes[:8]],
            )
    probe_page(page, audit)
    return audit


# ---------------------------------------------------------------------------
# Our own probes
# ---------------------------------------------------------------------------

PROBE_JS = r"""() => {
  const out = {};
  const links = [...document.querySelectorAll('a[href]')];
  out.linkCount = links.length;

  // Focus visibility: an outline removed on :focus with nothing put back in its place.
  let removed = false, replaced = false;
  try {
    for (const sheet of document.styleSheets) {
      let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
      for (const r of rules) {
        if (!r.selectorText || !r.style || !/:focus/.test(r.selectorText)) continue;
        const outline = (r.style.outline || r.style.outlineStyle || '').trim();
        const off = /^(none|0|0px)$/.test(outline);
        const visible = ['box-shadow','border','border-color','background','background-color','text-decoration','outline']
          .some(p => { const v = r.style.getPropertyValue(p);
                       return v && !/^(none|0|0px|initial|unset)$/.test(v.trim()) && !(p === 'outline' && off); });
        if (off && !visible) removed = true;
        if (visible) replaced = true;
      }
    }
  } catch (e) {}
  out.focusRemoved = removed; out.focusReplaced = replaced;

  out.positiveTabindex = [...document.querySelectorAll('[tabindex]')]
      .filter(e => parseInt(e.getAttribute('tabindex'), 10) > 0).length;

  out.genericLinks = links.filter(a => !a.getAttribute('aria-label') &&
      /^(click here|read more|learn more|here|more|link|this)$/i.test((a.textContent || '').trim())).length;

  out.hasSkip = links.some(a => /skip/i.test(a.textContent || '') && (a.getAttribute('href') || '').startsWith('#'));

  // Accessibility statement, by link text or destination.
  out.a11yStatement = links.some(a =>
      /accessibility/i.test((a.textContent || '') + ' ' + (a.getAttribute('href') || '')));

  // Hover-only menus: a submenu shown by :hover with no focus-within equivalent.
  let hoverOnly = false;
  try {
    for (const sheet of document.styleSheets) {
      let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
      for (const r of rules) {
        if (!r.selectorText) continue;
        if (/:hover\s/.test(r.selectorText) && /display\s*:\s*block|visibility\s*:\s*visible|opacity\s*:\s*1/.test(r.cssText)
            && !/:focus/.test(r.selectorText)) hoverOnly = true;
      }
    }
  } catch (e) {}
  out.hoverOnlyMenus = hoverOnly;

  // Colour as the only signal: required fields marked only by a red asterisk-free style,
  // and inline links in paragraphs with no underline.
  const paraLinks = links.filter(a => a.closest('p'));
  out.underlinedParaLinks = paraLinks.filter(a => {
    const s = getComputedStyle(a);
    return /underline/.test(s.textDecorationLine || s.textDecoration || '') ||
           (s.borderBottomWidth && s.borderBottomWidth !== '0px');
  }).length;
  out.paraLinks = paraLinks.length;

  const fields = [...document.querySelectorAll('input, select, textarea')]
      .filter(f => !['hidden','submit','button','image','reset'].includes((f.type || '').toLowerCase()));
  out.fieldCount = fields.length;
  out.fieldsWithAutocomplete = fields.filter(f => f.getAttribute('autocomplete')).length;
  out.requiredFields = fields.filter(f => f.required || f.getAttribute('aria-required') === 'true').length;

  // A placeholder is not a label: it vanishes the moment someone types, and voice-control
  // users cannot address the field by it. axe accepts it as an accessible name, so we look
  // for it ourselves.
  out.placeholderOnlyFields = fields.filter(f => {
    if (f.getAttribute('aria-label') || f.getAttribute('aria-labelledby')) return false;
    if (f.id && document.querySelector(`label[for="${CSS.escape(f.id)}"]`)) return false;
    if (f.closest('label')) return false;
    return !!f.getAttribute('placeholder');
  }).length;

  // Label in name: visible text of a control should appear in its accessible name.
  let mismatched = 0, checked = 0;
  for (const el of document.querySelectorAll('button, a[href], [role=button]')) {
    const visible = (el.textContent || '').trim().toLowerCase();
    const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
    if (visible && aria) { checked++; if (!aria.includes(visible)) mismatched++; }
  }
  out.labelInNameChecked = checked; out.labelInNameMismatched = mismatched;

  // Text that would clip if enlarged: fixed pixel heights on elements holding text.
  out.fixedHeightText = [...document.querySelectorAll('div,p,section,li,h1,h2,h3')].filter(e => {
    const s = getComputedStyle(e);
    return s.height !== 'auto' && /px$/.test(s.height) && parseFloat(s.height) > 0 &&
           s.overflow === 'hidden' && (e.textContent || '').trim().length > 40;
  }).length;

  out.navSignature = [...document.querySelectorAll('nav a, header a')]
      .map(a => (a.textContent || '').trim().toLowerCase()).filter(Boolean).join('|');

  out.title = (document.title || '').trim();

  const footer = document.querySelector('footer');
  out.footerText = footer ? (footer.textContent || '').slice(0, 2000) : '';
  out.bodyText = (document.body ? document.body.innerText || '' : '').slice(0, 40000);
  return out;
}"""


def probe_page(page: Page, audit: PageAudit) -> dict[str, Any]:
    facts = page.evaluate(PROBE_JS)

    # --- focus visible -----------------------------------------------------
    if facts["focusRemoved"] and not facts["focusReplaced"]:
        audit.record("focus-visible", "fail", count=1,
                     detail="the focus outline is removed in CSS and nothing visible replaces it")
    else:
        audit.record("focus-visible", "pass")

    # --- focus order -------------------------------------------------------
    if facts["positiveTabindex"]:
        audit.record("focus-order", "fail", count=facts["positiveTabindex"],
                     detail=f"{facts['positiveTabindex']} element(s) use a positive tabindex")
    else:
        audit.record("focus-order", "pass")

    # --- link purpose (generic link text) ----------------------------------
    if facts["genericLinks"] >= 2:
        audit.record("link-purpose", "fail", count=facts["genericLinks"],
                     detail=f"{facts['genericLinks']} links read only 'click here' or 'read more'")

    # --- skip link ---------------------------------------------------------
    if facts["linkCount"] > 15:
        audit.record("skip-link", "pass" if facts["hasSkip"] else "fail",
                     detail="" if facts["hasSkip"] else "no 'skip to content' link before the navigation")

    # --- keyboard access ---------------------------------------------------
    if facts["hoverOnlyMenus"]:
        audit.record("keyboard-access", "fail", count=1,
                     detail="a menu opens on hover with no keyboard-focus equivalent")
    else:
        audit.record("keyboard-access", "pass")

    # --- colour alone ------------------------------------------------------
    if facts["paraLinks"] >= 3:
        bare = facts["paraLinks"] - facts["underlinedParaLinks"]
        if bare >= 3:
            audit.record("color-not-alone", "fail", count=bare,
                         detail=f"{bare} in-paragraph links are distinguished only by colour")
        else:
            audit.record("color-not-alone", "pass")

    # --- input purpose -----------------------------------------------------
    if facts["fieldCount"]:
        if facts.get("placeholderOnlyFields"):
            audit.record("form-labels", "fail", count=facts["placeholderOnlyFields"],
                         detail=f"{facts['placeholderOnlyFields']} field(s) rely on a placeholder instead of a "
                                f"label, so the prompt disappears as soon as someone types")
        if facts["fieldsWithAutocomplete"] == 0 and facts["fieldCount"] >= 2:
            audit.record("input-purpose", "fail", count=facts["fieldCount"],
                         detail="form fields carry no autocomplete hints")
        else:
            audit.record("input-purpose", "pass")
        audit.record("error-identification", "needs_review",
                     detail="submit the form with bad input to confirm errors are described in text")
    else:
        audit.record("input-purpose", "not_applicable")
        audit.record("error-identification", "not_applicable")
        audit.record("form-labels", "not_applicable")

    # --- label in name -----------------------------------------------------
    if facts["labelInNameChecked"]:
        if facts["labelInNameMismatched"]:
            audit.record("label-in-name", "fail", count=facts["labelInNameMismatched"],
                         detail=f"{facts['labelInNameMismatched']} control(s) have an aria-label that omits their visible text")
        else:
            audit.record("label-in-name", "pass")

    # --- resize text -------------------------------------------------------
    if facts["fixedHeightText"]:
        audit.record("resize-text", "fail", count=facts["fixedHeightText"],
                     detail=f"{facts['fixedHeightText']} text container(s) have a fixed height with hidden overflow")
    else:
        audit.record("resize-text", "pass")

    # --- page title --------------------------------------------------------
    # axe only checks a <title> exists. WCAG 2.4.2 asks for one that describes the page,
    # which a generic placeholder does not.
    title = (facts.get("title") or "").strip()
    generic = title.lower() in ("", "home", "homepage", "welcome", "index", "untitled",
                                "new page", "page", "my site", "website")
    if generic or len(title) < 10:
        audit.record("page-title", "fail", count=1,
                     detail=f"the page title is {'empty' if not title else repr(title)}, which doesn't say what the page is")

    # --- accessibility statement ------------------------------------------
    audit.record("accessibility-statement", "pass" if facts["a11yStatement"] else "fail",
                 detail="" if facts["a11yStatement"] else "no accessibility statement is linked")

    # --- consistent help ---------------------------------------------------
    has_contact = bool(re.search(r"contact|call us|email us|\(\d{3}\)|\d{3}[.-]\d{3}[.-]\d{4}",
                                 facts.get("footerText", ""), re.I))
    audit.record("consistent-help", "pass" if has_contact else "fail",
                 detail="" if has_contact else "no contact route in the footer")

    audit.evidence.setdefault("_facts", []).append(facts)
    return facts


def merge_audits(audits: list[PageAudit]) -> list[CheckResult]:
    """Combine per-page audits into one result per check for the whole site.

    A check fails for the site if it fails anywhere; it passes only if it passed somewhere
    and failed nowhere. Consistency checks that need more than one page are decided here.
    """
    results: dict[str, CheckResult] = {}
    rank = {"fail": 3, "needs_review": 2, "pass": 1, "not_applicable": 0}
    for audit in audits:
        for check_id, status in audit.statuses.items():
            existing = results.get(check_id)
            if existing is None:
                results[check_id] = CheckResult(
                    check_id, status, count=audit.counts.get(check_id, 0),
                    detail=audit.details.get(check_id, ""), pages=[audit.url],
                    evidence=list(audit.evidence.get(check_id, [])),
                )
                continue
            if status == existing.status:
                existing.count += audit.counts.get(check_id, 0)
                existing.pages.append(audit.url)
                existing.evidence.extend(audit.evidence.get(check_id, []))
            elif rank[status] > rank[existing.status]:
                results[check_id] = CheckResult(
                    check_id, status, count=audit.counts.get(check_id, 0),
                    detail=audit.details.get(check_id, ""), pages=[audit.url],
                    evidence=list(audit.evidence.get(check_id, [])),
                )

    # Consistent navigation needs at least two pages to mean anything.
    signatures = [a.evidence.get("_facts", [{}])[0].get("navSignature", "") for a in audits
                  if a.evidence.get("_facts")]
    signatures = [s for s in signatures if s]
    if len(signatures) >= 2:
        consistent = len(set(signatures)) == 1
        results["consistent-navigation"] = CheckResult(
            "consistent-navigation", "pass" if consistent else "fail",
            detail="" if consistent else "the navigation differs between pages",
            pages=[a.url for a in audits],
        )
    return list(results.values())
