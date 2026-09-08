"""The checklist.

One declarative registry of everything we check on a website, for accessibility and for
search / AI discoverability. It is the single source of truth for four separate things:

* what the **scanner** looks for,
* how the **percentage scores** are computed (earned weight over applicable weight),
* what the **fixer** knows how to repair,
* and what the **report** shows the client, in plain language.

Adding a check here makes it appear in all four places at once. It is also usable on its
own as a build standard for sites you make yourself - see ``STANDARDS.md``, which is
generated from this file.

**Honesty about coverage.** Automated testing catches roughly a third to a half of real
WCAG problems; the rest need a person with a screen reader and a keyboard. Every check
records how it is detected:

``auto``       decided by a tool (axe-core or a deterministic parser); trustworthy.
``heuristic``  our own rule of thumb; usually right, occasionally wrong.
``manual``     genuinely needs a human. Listed and reported, never scored.

The score therefore describes *automated* conformance, and the report says so. Claiming a
percentage means "compliant" is exactly the overstatement that has drawn FTC action in
this industry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Area = Literal["ada", "seo"]
Detection = Literal["auto", "heuristic", "manual"]

# The checklist is versioned, in YYYY.MM, because clients pay monthly for it to stay
# current. When WCAG publishes new guidance, or the way assistants read sites changes, a
# check is added here and the version is bumped; every site on a care plan is then measured
# against the new list at its next monthly check and told, in the report, what changed and
# what we did about it. String comparison of these versions is chronological by design.
CHECKLIST_VERSION = "2026.09"

# What changed in each version, in one line, for the monthly email.
VERSION_NOTES: dict[str, str] = {
    "2026.09": "first published checklist: WCAG 2.2 A/AA plus the AI-search and structured-data items",
}


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    area: Area
    category: str
    weight: int                     # 1-10; relative importance within its area
    detection: Detection
    standard: str                   # WCAG success criterion, or the source for SEO checks
    why: str                        # why it matters, in words a business owner uses
    fix: str                        # what fixing it involves
    auto_fixable: bool = False      # our remediation bundle can do this unattended
    axe_rules: tuple[str, ...] = () # axe-core rule ids that decide this check
    applies: str = "every page"     # when the check is relevant at all
    since: str = "2026.09"          # checklist version that introduced it

    @property
    def level(self) -> str:
        """WCAG conformance level, where the standard names one."""
        if "(A)" in self.standard:
            return "A"
        if "(AA)" in self.standard:
            return "AA"
        return ""

    @property
    def failure_phrase(self) -> str:
        """How to name this check when it *fails*, in an email or a summary.

        Titles are written as things a good site does ("Form fields have labels"), which
        reads backwards in a list of problems. This is the same fact stated as the fault.
        """
        return FAIL_PHRASES.get(self.id, self.title.lower())


# Short, plain descriptions of each check in its failing state. Used wherever failures are
# listed to a business owner rather than to a developer.
FAIL_PHRASES: dict[str, str] = {
    # accessibility
    "image-alt": "images with no text alternative",
    "image-alt-quality": "alt text that is just a filename",
    "video-captions": "video without captions",
    "audio-description": "video with no audio description",
    "semantic-structure": "headings and lists that only look right visually",
    "form-labels": "form fields with no label",
    "input-purpose": "form fields with no autocomplete hints",
    "meaningful-sequence": "content that reads out of order",
    "sensory-characteristics": "instructions that rely on shape or position",
    "color-not-alone": "information shown only by colour",
    "audio-control": "media that plays sound automatically",
    "color-contrast": "text that is too low-contrast to read easily",
    "non-text-contrast": "buttons and form borders that are too faint",
    "resize-text": "text that clips when enlarged",
    "zoom-enabled": "pinch zoom disabled on mobile",
    "images-of-text": "text baked into images",
    "text-spacing": "layout that breaks with wider text spacing",
    "hover-content": "tooltips that cannot be dismissed",
    "keyboard-access": "controls that cannot be reached with a keyboard",
    "no-keyboard-trap": "places where keyboard focus gets stuck",
    "focus-visible": "no visible outline showing where the keyboard is",
    "focus-order": "a tab order that jumps around the page",
    "focus-not-obscured": "focused elements hidden behind sticky bars",
    "skip-link": "no way to skip past the navigation",
    "landmarks": "page regions that assistive tech cannot jump to",
    "page-title": "a page title that does not say what the page is",
    "link-purpose": "links that do not say where they go",
    "button-name": "buttons with no readable name",
    "frame-title": "embedded maps or videos with no label",
    "heading-order": "heading levels that skip",
    "target-size": "tap targets that are too small",
    "pointer-alternatives": "swipe or drag with no simple alternative",
    "label-in-name": "labels that do not match what voice control hears",
    "timing-and-motion": "moving content that cannot be paused",
    "page-language": "no declared page language",
    "language-of-parts": "foreign phrases that are not marked up",
    "consistent-navigation": "navigation that changes between pages",
    "no-surprise-changes": "things that change unexpectedly on focus",
    "error-identification": "form errors not explained in text",
    "consistent-help": "no obvious way to get help or make contact",
    "accessible-auth": "a login that depends on a memory test",
    "aria-valid": "ARIA that misdescribes elements to assistive tech",
    "unique-ids": "duplicate element IDs",
    "widget-names": "custom controls with no name or role",
    "status-messages": "updates that are never announced",
    "accessibility-statement": "no accessibility statement",
    # search and AI
    "robots-exists": "no robots.txt",
    "crawlers-allowed": "search crawlers blocked",
    "ai-crawlers-allowed": "AI assistants blocked from reading the site",
    "sitemap": "no sitemap",
    "indexable": "pages set to noindex",
    "https": "no HTTPS",
    "canonical": "no canonical URL",
    "broken-links": "broken internal links",
    "structured-data": "no structured data describing the business",
    "structured-data-valid": "structured data that does not parse",
    "nap-structured": "address and phone missing from the structured data",
    "opening-hours": "opening hours that machines cannot read",
    "faq-schema": "no FAQ markup",
    "breadcrumbs": "no breadcrumb markup",
    "social-profiles": "no links tying the site to its other profiles",
    "title-tag": "a weak or missing page title",
    "meta-description": "no meta description",
    "h1": "no single clear H1 heading",
    "content-depth": "too little readable text",
    "nap-visible": "phone or address missing from the page text",
    "descriptive-urls": "URLs that mean nothing to a reader",
    "internal-links": "pages that nothing links to",
    "open-graph": "shared links with no preview",
    "lcp": "slow loading of the main content",
    "cls": "layout that jumps while loading",
    "page-weight": "a needlessly heavy page",
    "mobile-friendly": "a site that does not work properly on a phone",
    "image-optimisation": "oversized, eagerly loaded images",
    "llms-txt": "no llms.txt summary for AI assistants",
    "server-rendered": "text that only exists after JavaScript runs",
    "answer-ready-content": "content too vague for an assistant to quote",
    "entity-clarity": "no plain statement of the trade and the town",
    "freshness": "content that looks abandoned",
    "no-ai-blocking-meta": "meta tags blocking AI from quoting the site",
}


# =============================================================================
# Accessibility - WCAG 2.2 Level A and AA
# =============================================================================

ADA_CHECKS: list[Check] = [
    # ---------------------------------------------------------------- perceivable
    Check(
        id="image-alt", title="Images have text alternatives", area="ada", category="perceivable",
        weight=10, detection="auto", standard="WCAG 2.2 SC 1.1.1 Non-text Content (A)",
        why="A screen reader announces nothing for an image with no alt text, so a blind visitor "
            "misses whatever it conveyed - often the product, the menu, or the phone number.",
        fix="Add alt text describing what the image conveys; use empty alt for purely decorative images.",
        auto_fixable=True, axe_rules=("image-alt", "input-image-alt", "area-alt", "object-alt", "svg-img-alt", "role-img-alt"),
        applies="pages containing images",
    ),
    Check(
        id="image-alt-quality", title="Alt text is meaningful, not a filename", area="ada", category="perceivable",
        weight=4, detection="heuristic", standard="WCAG 2.2 SC 1.1.1 Non-text Content (A)",
        why="Alt text like 'IMG_4821.jpg' or 'image' is technically present but tells a blind visitor nothing.",
        fix="Replace placeholder alt text with a short description of what the image shows.",
        auto_fixable=True, axe_rules=("image-redundant-alt",), applies="pages containing images",
    ),
    Check(
        id="video-captions", title="Video has captions", area="ada", category="perceivable",
        weight=8, detection="manual", standard="WCAG 2.2 SC 1.2.2 Captions (Prerecorded) (A)",
        why="Deaf and hard-of-hearing visitors cannot use video without captions, and most people "
            "watch without sound anyway.",
        fix="Upload a caption file, or use your video host's caption feature. Auto-captions must be corrected.",
        axe_rules=("video-caption",), applies="pages containing video",
    ),
    Check(
        id="audio-description", title="Video has audio description where needed", area="ada", category="perceivable",
        weight=4, detection="manual", standard="WCAG 2.2 SC 1.2.5 Audio Description (Prerecorded) (AA)",
        why="Visual information shown but never spoken is lost to blind visitors.",
        fix="Add an audio description track, or narrate the on-screen information in the video itself.",
        applies="pages with video that conveys visual information",
    ),
    Check(
        id="semantic-structure", title="Headings, lists and tables use real markup", area="ada", category="perceivable",
        weight=9, detection="auto", standard="WCAG 2.2 SC 1.3.1 Info and Relationships (A)",
        why="Screen reader users navigate by heading and list. Text that only looks like a heading "
            "because it is big and bold is invisible to that navigation.",
        fix="Use real <h1>-<h6>, <ul>/<ol> and table headers instead of styled paragraphs and divs.",
        auto_fixable=True,
        axe_rules=("list", "listitem", "definition-list", "dlitem", "p-as-heading", "td-has-header",
                   "th-has-data-cells", "td-headers-attr", "scope-attr-valid", "table-fake-caption",
                   "empty-table-header", "table-duplicate-name"),
    ),
    Check(
        id="form-labels", title="Form fields have labels", area="ada", category="perceivable",
        weight=10, detection="auto", standard="WCAG 2.2 SC 1.3.1 Info and Relationships (A), 3.3.2 Labels or Instructions (A)",
        why="An unlabelled field is announced as just 'edit text'. A visitor cannot tell whether to "
            "type their name, email or postcode - so the contact form never gets submitted.",
        fix="Give every field a visible <label> tied to it, or an aria-label where a visible one won't fit.",
        auto_fixable=True, axe_rules=("label", "select-name", "form-field-multiple-labels", "label-title-only",
                                      "aria-input-field-name", "aria-toggle-field-name"),
        applies="pages containing forms",
    ),
    Check(
        id="input-purpose", title="Common fields declare their purpose", area="ada", category="perceivable",
        weight=3, detection="auto", standard="WCAG 2.2 SC 1.3.5 Identify Input Purpose (AA)",
        why="Autocomplete attributes let browsers and assistive tools fill in name, email and address "
            "automatically, which matters a great deal for people with motor or memory difficulties.",
        fix="Add autocomplete=\"name\", \"email\", \"tel\" and so on to the matching fields.",
        auto_fixable=True, axe_rules=("autocomplete-valid",), applies="pages containing forms",
    ),
    Check(
        id="meaningful-sequence", title="Reading order makes sense without styling", area="ada", category="perceivable",
        weight=5, detection="manual", standard="WCAG 2.2 SC 1.3.2 Meaningful Sequence (A)",
        why="Screen readers follow the order of the markup, not the visual layout. CSS-positioned "
            "content can be read in a nonsensical order.",
        fix="Order the markup to match the intended reading order and use CSS for placement.",
    ),
    Check(
        id="sensory-characteristics", title="Instructions don't rely on shape or position alone",
        area="ada", category="perceivable", weight=3, detection="manual",
        standard="WCAG 2.2 SC 1.3.3 Sensory Characteristics (A)",
        why="'Click the round button on the right' is useless to someone who cannot see the layout.",
        fix="Refer to controls by their visible name as well as their position.",
    ),
    Check(
        id="color-not-alone", title="Colour is not the only way information is shown",
        area="ada", category="perceivable", weight=6, detection="heuristic",
        standard="WCAG 2.2 SC 1.4.1 Use of Color (A)",
        why="Around one in twelve men has some colour blindness. Required fields marked only in red, "
            "or links distinguished only by colour, disappear for them.",
        fix="Add a second signal: an underline on links, an asterisk or text on required fields, an icon on errors.",
        auto_fixable=True, axe_rules=("link-in-text-block",),
    ),
    Check(
        id="audio-control", title="Nothing plays sound automatically", area="ada", category="perceivable",
        weight=7, detection="auto", standard="WCAG 2.2 SC 1.4.2 Audio Control (A)",
        why="Audio that starts on its own drowns out a screen reader, making the whole page unusable.",
        fix="Remove autoplay, or start muted with a visible control to unmute.",
        auto_fixable=True, axe_rules=("no-autoplay-audio",), applies="pages with audio or video",
    ),
    Check(
        id="color-contrast", title="Text has enough contrast against its background",
        area="ada", category="perceivable", weight=10, detection="auto",
        standard="WCAG 2.2 SC 1.4.3 Contrast (Minimum) (AA)",
        why="Light grey on white is the single most common accessibility failure on small business "
            "sites, and it affects everyone reading on a phone in daylight, not just people with low vision.",
        fix="Darken the text or lighten the background until normal text reaches a 4.5:1 ratio (3:1 for large text).",
        auto_fixable=True, axe_rules=("color-contrast",),
    ),
    Check(
        id="non-text-contrast", title="Buttons, icons and form borders have enough contrast",
        area="ada", category="perceivable", weight=6, detection="heuristic",
        standard="WCAG 2.2 SC 1.4.11 Non-text Contrast (AA)",
        why="A pale grey input border or icon can be invisible to someone with low vision, so they "
            "cannot tell where to click or type.",
        fix="Give interface components and their states at least a 3:1 contrast ratio against what surrounds them.",
    ),
    Check(
        id="resize-text", title="Text can be enlarged to 200% without breaking",
        area="ada", category="perceivable", weight=6, detection="heuristic",
        standard="WCAG 2.2 SC 1.4.4 Resize Text (AA), 1.4.10 Reflow (AA)",
        why="People who need larger text zoom in. If the layout is fixed-width or clips, the content "
            "becomes unreadable or requires scrolling in two directions.",
        fix="Use relative units and responsive layout so content reflows in a 320px-wide viewport.",
    ),
    Check(
        id="zoom-enabled", title="Pinch zoom is not disabled", area="ada", category="perceivable",
        weight=7, detection="auto", standard="WCAG 2.2 SC 1.4.4 Resize Text (AA)",
        why="Blocking zoom on mobile stops anyone who needs bigger text from reading the site at all.",
        fix="Remove user-scalable=no and maximum-scale from the viewport meta tag.",
        auto_fixable=True, axe_rules=("meta-viewport", "meta-viewport-large"),
    ),
    Check(
        id="images-of-text", title="Text is real text, not pictures of text", area="ada", category="perceivable",
        weight=4, detection="manual", standard="WCAG 2.2 SC 1.4.5 Images of Text (AA)",
        why="Text baked into an image cannot be resized, recoloured, translated, read aloud, or found "
            "by search engines and AI assistants.",
        fix="Replace text images (menus, price lists, hours) with real HTML text styled with CSS.",
    ),
    Check(
        id="text-spacing", title="Layout survives increased text spacing", area="ada", category="perceivable",
        weight=3, detection="manual", standard="WCAG 2.2 SC 1.4.12 Text Spacing (AA)",
        why="Some people with dyslexia increase line and letter spacing. Rigid layouts clip the text when they do.",
        fix="Avoid fixed heights on text containers; let them grow.",
    ),
    Check(
        id="hover-content", title="Tooltips and popovers can be dismissed and hovered",
        area="ada", category="perceivable", weight=3, detection="manual",
        standard="WCAG 2.2 SC 1.4.13 Content on Hover or Focus (AA)",
        why="Content that appears on hover and vanishes when the pointer moves is unusable for people "
            "using magnification.",
        fix="Make hover content dismissible with Escape, hoverable, and persistent until dismissed.",
    ),

    # ------------------------------------------------------------------ operable
    Check(
        id="keyboard-access", title="Everything works with a keyboard", area="ada", category="operable",
        weight=10, detection="heuristic", standard="WCAG 2.2 SC 2.1.1 Keyboard (A)",
        why="People who cannot use a mouse - through motor disability, tremor, or simply a broken "
            "trackpad - navigate entirely by keyboard. A menu that only opens on hover locks them out.",
        fix="Make every control reachable with Tab and operable with Enter or Space, using real buttons and links.",
        axe_rules=("nested-interactive", "scrollable-region-focusable", "frame-focusable-content"),
    ),
    Check(
        id="no-keyboard-trap", title="Keyboard focus is never trapped", area="ada", category="operable",
        weight=8, detection="manual", standard="WCAG 2.2 SC 2.1.2 No Keyboard Trap (A)",
        why="If focus enters a widget or modal it cannot leave, the visitor has to close the browser tab.",
        fix="Ensure Tab and Escape always move focus back out of dialogs, embeds and custom widgets.",
    ),
    Check(
        id="focus-visible", title="Keyboard focus is clearly visible", area="ada", category="operable",
        weight=9, detection="heuristic", standard="WCAG 2.2 SC 2.4.7 Focus Visible (AA)",
        why="Removing the focus outline is a common 'tidy-up' that leaves keyboard users with no idea "
            "where they are on the page.",
        fix="Never set outline:none without an equally clear replacement; add a visible :focus-visible style.",
        auto_fixable=True,
    ),
    Check(
        id="focus-order", title="Tab order follows the visual order", area="ada", category="operable",
        weight=6, detection="heuristic", standard="WCAG 2.2 SC 2.4.3 Focus Order (A)",
        why="Positive tabindex values and reordered layouts send focus jumping around the page unpredictably.",
        fix="Remove positive tabindex values and let the document order carry the focus order.",
        auto_fixable=True, axe_rules=("tabindex",),
    ),
    Check(
        id="focus-not-obscured", title="Focused elements are not hidden behind sticky bars",
        area="ada", category="operable", weight=4, detection="manual",
        standard="WCAG 2.2 SC 2.4.11 Focus Not Obscured (Minimum) (AA)",
        why="Sticky headers and cookie banners frequently cover the element that just received focus.",
        fix="Add scroll padding so focused elements are never fully hidden by fixed overlays.",
    ),
    Check(
        id="skip-link", title="There is a way to skip repeated navigation", area="ada", category="operable",
        weight=6, detection="auto", standard="WCAG 2.2 SC 2.4.1 Bypass Blocks (A)",
        why="Without a skip link, a screen reader user hears the entire navigation menu again on every "
            "single page before reaching the content.",
        fix="Add a 'Skip to main content' link as the first focusable element, and a <main> landmark to skip to.",
        auto_fixable=True, axe_rules=("bypass", "skip-link"),
    ),
    Check(
        id="landmarks", title="Page regions are marked as landmarks", area="ada", category="operable",
        weight=6, detection="auto", standard="WCAG 2.2 SC 1.3.1 Info and Relationships (A)",
        why="Landmarks let screen reader users jump straight to the navigation, the search, or the main "
            "content instead of listening through the page.",
        fix="Wrap the page in <header>, <nav>, <main> and <footer> instead of anonymous <div>s.",
        auto_fixable=True,
        axe_rules=("region", "landmark-one-main", "landmark-banner-is-top-level", "landmark-complementary-is-top-level",
                   "landmark-contentinfo-is-top-level", "landmark-main-is-top-level", "landmark-no-duplicate-banner",
                   "landmark-no-duplicate-contentinfo", "landmark-no-duplicate-main", "landmark-unique"),
    ),
    Check(
        id="page-title", title="Every page has a unique, descriptive title", area="ada", category="operable",
        weight=8, detection="auto", standard="WCAG 2.2 SC 2.4.2 Page Titled (A)",
        why="The title is the first thing a screen reader announces and the label on every browser tab "
            "and bookmark. 'Home' or 'Untitled' tells nobody anything.",
        fix="Give each page a title naming the page and the business.",
        auto_fixable=True, axe_rules=("document-title",),
    ),
    Check(
        id="link-purpose", title="Links say where they go", area="ada", category="operable",
        weight=8, detection="auto", standard="WCAG 2.2 SC 2.4.4 Link Purpose (In Context) (A)",
        why="Screen reader users often pull up a list of links to navigate. A list reading 'click here, "
            "click here, read more' is useless.",
        fix="Write link text that describes the destination; give icon-only links an aria-label.",
        auto_fixable=True, axe_rules=("link-name", "identical-links-same-purpose"),
    ),
    Check(
        id="button-name", title="Buttons have accessible names", area="ada", category="operable",
        weight=9, detection="auto", standard="WCAG 2.2 SC 4.1.2 Name, Role, Value (A)",
        why="An icon-only button with no name is announced as just 'button'. The visitor cannot know it "
            "submits the form or opens the menu.",
        fix="Add visible text or an aria-label to every button.",
        auto_fixable=True, axe_rules=("button-name", "input-button-name", "aria-command-name"),
    ),
    Check(
        id="frame-title", title="Embedded frames are labelled", area="ada", category="operable",
        weight=5, detection="auto", standard="WCAG 2.2 SC 2.4.1 Bypass Blocks (A), 4.1.2 Name, Role, Value (A)",
        why="Embedded maps, videos and booking widgets are announced as 'frame' with no indication of "
            "what they contain.",
        fix="Add a title attribute to every iframe describing its contents.",
        auto_fixable=True, axe_rules=("frame-title", "frame-title-unique"),
        applies="pages containing iframes",
    ),
    Check(
        id="heading-order", title="Heading levels don't skip", area="ada", category="operable",
        weight=5, detection="auto", standard="WCAG 2.2 SC 1.3.1 Info and Relationships (A)",
        why="Heading level is how screen reader users understand the structure of a page. Jumping from "
            "an H1 straight to an H4 implies a hierarchy that isn't there.",
        fix="Step heading levels one at a time and use CSS for size.",
        auto_fixable=True, axe_rules=("heading-order", "page-has-heading-one", "empty-heading"),
    ),
    Check(
        id="target-size", title="Tap targets are big enough", area="ada", category="operable",
        weight=5, detection="auto", standard="WCAG 2.2 SC 2.5.8 Target Size (Minimum) (AA)",
        why="Small, tightly packed links are hard to hit for anyone with a tremor, and awkward for "
            "everyone on a phone.",
        fix="Give interactive elements at least a 24 by 24 pixel target, or enough spacing around them.",
        auto_fixable=True, axe_rules=("target-size",),
    ),
    Check(
        id="pointer-alternatives", title="Gestures and dragging have simple alternatives",
        area="ada", category="operable", weight=4, detection="manual",
        standard="WCAG 2.2 SC 2.5.1 Pointer Gestures (A), 2.5.7 Dragging Movements (AA)",
        why="Carousels that only respond to swipe, or sliders that only respond to drag, exclude people "
            "who cannot perform those movements.",
        fix="Provide buttons that do the same thing as the swipe or drag.",
    ),
    Check(
        id="label-in-name", title="Visible labels match their accessible names",
        area="ada", category="operable", weight=4, detection="heuristic",
        standard="WCAG 2.2 SC 2.5.3 Label in Name (A)",
        why="Voice control users say the visible label out loud. If the underlying name differs, nothing happens.",
        fix="Make the accessible name start with, or contain, the visible text.",
    ),
    Check(
        id="timing-and-motion", title="Time limits and moving content can be controlled",
        area="ada", category="operable", weight=5, detection="auto",
        standard="WCAG 2.2 SC 2.2.1 Timing Adjustable (A), 2.2.2 Pause, Stop, Hide (A), 2.3.1 Three Flashes (A)",
        why="Auto-advancing carousels and auto-refreshing pages steal focus and reading position. "
            "Flashing content can trigger seizures.",
        fix="Let people pause moving content; remove meta refresh and blinking or flashing elements.",
        auto_fixable=True, axe_rules=("meta-refresh", "blink", "marquee"),
    ),

    # ------------------------------------------------------------ understandable
    Check(
        id="page-language", title="The page declares its language", area="ada", category="understandable",
        weight=7, detection="auto", standard="WCAG 2.2 SC 3.1.1 Language of Page (A)",
        why="Without a language declaration a screen reader may read English with a French voice, "
            "rendering it incomprehensible.",
        fix="Add lang=\"en\" (or the right language) to the <html> element.",
        auto_fixable=True, axe_rules=("html-has-lang", "html-lang-valid", "html-xml-lang-mismatch", "valid-lang"),
    ),
    Check(
        id="language-of-parts", title="Foreign phrases are marked up", area="ada", category="understandable",
        weight=2, detection="manual", standard="WCAG 2.2 SC 3.1.2 Language of Parts (AA)",
        why="Passages in another language are mispronounced unless marked.",
        fix="Wrap foreign-language passages in an element with the right lang attribute.",
    ),
    Check(
        id="consistent-navigation", title="Navigation is consistent across pages",
        area="ada", category="understandable", weight=4, detection="heuristic",
        standard="WCAG 2.2 SC 3.2.3 Consistent Navigation (AA), 3.2.4 Consistent Identification (AA)",
        why="Menus that reorder themselves between pages force people to relearn the site on every page.",
        fix="Keep navigation in the same order and label the same things the same way throughout.",
    ),
    Check(
        id="no-surprise-changes", title="Nothing changes unexpectedly on focus or input",
        area="ada", category="understandable", weight=4, detection="manual",
        standard="WCAG 2.2 SC 3.2.1 On Focus (A), 3.2.2 On Input (A)",
        why="A form that submits itself when a dropdown changes, or a new window that opens on focus, "
            "disorients people using screen readers.",
        fix="Require an explicit button press for anything that navigates or submits.",
    ),
    Check(
        id="error-identification", title="Form errors are described in text",
        area="ada", category="understandable", weight=6, detection="heuristic",
        standard="WCAG 2.2 SC 3.3.1 Error Identification (A), 3.3.3 Error Suggestion (AA)",
        why="An error shown only as a red border tells a blind visitor nothing, and they cannot complete "
            "the contact form.",
        fix="Describe each error in text next to the field, and say how to fix it.",
        applies="pages containing forms",
    ),
    Check(
        id="consistent-help", title="Help and contact details are easy to find",
        area="ada", category="understandable", weight=3, detection="heuristic",
        standard="WCAG 2.2 SC 3.2.6 Consistent Help (A)",
        why="People who need help should find the contact route in the same place on every page.",
        fix="Put contact details or a help link in the same location site-wide.",
    ),
    Check(
        id="accessible-auth", title="Login doesn't depend on a memory test",
        area="ada", category="understandable", weight=3, detection="manual",
        standard="WCAG 2.2 SC 3.3.8 Accessible Authentication (Minimum) (AA)",
        why="Puzzle CAPTCHAs and transcription tests exclude people with cognitive disabilities.",
        fix="Allow password managers to paste, and offer an alternative to puzzle-based checks.",
        applies="sites with a login",
    ),

    # ------------------------------------------------------------------- robust
    Check(
        id="aria-valid", title="ARIA is used correctly", area="ada", category="robust",
        weight=8, detection="auto", standard="WCAG 2.2 SC 4.1.2 Name, Role, Value (A)",
        why="Broken ARIA is worse than none: it actively lies to assistive technology about what an "
            "element is and what it does.",
        fix="Correct invalid roles, attributes and values, or remove the ARIA and use native HTML.",
        auto_fixable=True,
        axe_rules=("aria-allowed-attr", "aria-allowed-role", "aria-required-attr", "aria-required-children",
                   "aria-required-parent", "aria-roles", "aria-valid-attr", "aria-valid-attr-value",
                   "aria-hidden-body", "aria-hidden-focus", "aria-conditional-attr", "aria-deprecated-role",
                   "aria-prohibited-attr", "aria-roledescription", "aria-text", "presentation-role-conflict"),
    ),
    Check(
        id="unique-ids", title="Element IDs used by ARIA are unique", area="ada", category="robust",
        weight=4, detection="auto", standard="WCAG 2.2 SC 4.1.2 Name, Role, Value (A)",
        why="Duplicate IDs make label and description references point at the wrong element.",
        fix="Make every ID on the page unique.",
        auto_fixable=True, axe_rules=("duplicate-id-aria", "duplicate-id", "duplicate-id-active"),
    ),
    Check(
        id="widget-names", title="Custom widgets expose a name and role",
        area="ada", category="robust", weight=6, detection="auto",
        standard="WCAG 2.2 SC 4.1.2 Name, Role, Value (A)",
        why="Custom dropdowns, dialogs and sliders built from divs are announced as nothing at all.",
        fix="Give custom widgets the right role and an accessible name, or use native elements.",
        axe_rules=("aria-dialog-name", "aria-meter-name", "aria-progressbar-name", "aria-tooltip-name",
                   "aria-treeitem-name", "server-side-image-map"),
    ),
    Check(
        id="status-messages", title="Dynamic updates are announced", area="ada", category="robust",
        weight=4, detection="manual", standard="WCAG 2.2 SC 4.1.3 Status Messages (AA)",
        why="'Message sent' or 'added to cart' shown only visually is never announced to a screen reader user.",
        fix="Put status messages in a live region (role=\"status\" or aria-live=\"polite\").",
    ),
    Check(
        id="accessibility-statement", title="The site has an accessibility statement",
        area="ada", category="robust", weight=5, detection="auto",
        standard="Best practice; expected by the DOJ's web accessibility guidance",
        why="A statement giving a contact route for access problems is the single cheapest thing that "
            "de-escalates a complaint before it becomes a demand letter.",
        fix="Publish a page stating your commitment, the standard you aim for, and how to report a problem.",
        auto_fixable=True,
    ),
]


# =============================================================================
# Search and AI discoverability
# =============================================================================

SEO_CHECKS: list[Check] = [
    # --------------------------------------------------------------- crawlability
    Check(
        id="robots-exists", title="robots.txt exists and is valid", area="seo", category="crawlability",
        weight=5, detection="auto", standard="Robots Exclusion Protocol (RFC 9309)",
        why="Without it, every crawler has to guess what it may read, and some guess conservatively.",
        fix="Publish a robots.txt at the site root that allows crawling and points to your sitemap.",
        auto_fixable=True,
    ),
    Check(
        id="crawlers-allowed", title="Search crawlers are not blocked", area="seo", category="crawlability",
        weight=10, detection="auto", standard="Robots Exclusion Protocol (RFC 9309)",
        why="A stray 'Disallow: /' is the fastest way to make a site vanish from Google entirely. It "
            "happens most often when a staging site goes live unchanged.",
        fix="Remove blanket Disallow rules for search crawlers.",
        auto_fixable=True,
    ),
    Check(
        id="ai-crawlers-allowed", title="AI assistants are allowed to read the site",
        area="seo", category="crawlability", weight=9, detection="auto",
        standard="Publisher controls for GPTBot, ClaudeBot, PerplexityBot, Google-Extended",
        why="If ChatGPT, Claude, Perplexity and Google's AI answers cannot read the site, the business "
            "simply cannot be recommended when someone asks an assistant for a local supplier.",
        fix="Remove Disallow rules aimed at AI crawler user agents in robots.txt.",
        auto_fixable=True,
    ),
    Check(
        id="sitemap", title="An XML sitemap exists and is referenced",
        area="seo", category="crawlability", weight=6, detection="auto",
        standard="sitemaps.org protocol 0.9",
        why="A sitemap is how crawlers find pages that are not well linked from the home page.",
        fix="Generate sitemap.xml, keep it current, and reference it from robots.txt.",
        auto_fixable=True,
    ),
    Check(
        id="indexable", title="Pages are not accidentally set to noindex",
        area="seo", category="crawlability", weight=10, detection="auto",
        standard="Google Search Central: robots meta tag",
        why="A leftover noindex tag removes a page from search results completely, however good it is.",
        fix="Remove noindex from pages that should be found.",
        auto_fixable=True,
    ),
    Check(
        id="https", title="The site is served over HTTPS", area="seo", category="crawlability",
        weight=8, detection="auto", standard="Google Search Central: HTTPS as a ranking signal",
        why="Browsers label plain HTTP sites 'Not secure', which costs trust and conversions, and it is "
            "a ranking signal.",
        fix="Install a TLS certificate (free with most hosts) and redirect HTTP to HTTPS.",
    ),
    Check(
        id="canonical", title="Pages declare a canonical URL", area="seo", category="crawlability",
        weight=4, detection="auto", standard="Google Search Central: canonicalization",
        why="Without one, the same page reachable at several addresses splits its ranking signals.",
        fix="Add a canonical link element naming the preferred address of each page.",
        auto_fixable=True,
    ),
    Check(
        id="broken-links", title="Internal links are not broken", area="seo", category="crawlability",
        weight=5, detection="auto", standard="Best practice",
        why="Dead internal links waste crawl budget and strand visitors.",
        fix="Fix or remove links that return an error.",
    ),

    # ------------------------------------------------------------ structured data
    Check(
        id="structured-data", title="The business is described in structured data",
        area="seo", category="structured_data", weight=10, detection="auto",
        standard="schema.org LocalBusiness / Organization",
        why="Structured data is how a search engine or AI assistant knows this is a dentist in "
            "Springfield rather than a page that happens to mention teeth. Without it the business is "
            "guessed at, and often guessed wrong.",
        fix="Add JSON-LD describing the business, its type, address, phone and hours.",
        auto_fixable=True,
    ),
    Check(
        id="structured-data-valid", title="Structured data parses and uses real types",
        area="seo", category="structured_data", weight=6, detection="auto",
        standard="schema.org vocabulary; JSON-LD 1.1",
        why="Malformed JSON-LD is silently ignored, so the effort is wasted without anyone noticing.",
        fix="Fix the JSON syntax and use a recognised @type from schema.org.",
        auto_fixable=True,
    ),
    Check(
        id="nap-structured", title="Name, address and phone are in the markup",
        area="seo", category="structured_data", weight=8, detection="auto",
        standard="schema.org PostalAddress; Google Business Profile consistency",
        why="Consistent name, address and phone across the web is the backbone of local search ranking, "
            "and it is what an assistant reads out when someone asks how to contact you.",
        fix="Include the full postal address and telephone in the LocalBusiness structured data.",
        auto_fixable=True,
    ),
    Check(
        id="opening-hours", title="Opening hours are machine readable",
        area="seo", category="structured_data", weight=5, detection="auto",
        standard="schema.org openingHoursSpecification",
        why="'Are they open now?' is one of the most common questions asked of assistants and search. "
            "Hours in an image or free text cannot answer it.",
        fix="Add openingHoursSpecification to the structured data.",
        auto_fixable=True, applies="businesses with premises or set hours",
    ),
    Check(
        id="faq-schema", title="Common questions are marked up as FAQs",
        area="seo", category="structured_data", weight=4, detection="auto",
        standard="schema.org FAQPage",
        why="FAQ markup gives assistants exact question-and-answer pairs to quote in your own words "
            "rather than paraphrasing or guessing.",
        fix="Add FAQPage structured data for the questions customers actually ask.",
        auto_fixable=True,
    ),
    Check(
        id="breadcrumbs", title="Page hierarchy is described", area="seo", category="structured_data",
        weight=3, detection="auto", standard="schema.org BreadcrumbList",
        why="Breadcrumbs help crawlers understand how pages relate, and show up in search results.",
        fix="Add BreadcrumbList structured data on inner pages.",
        auto_fixable=True, applies="sites with more than one level of pages",
    ),
    Check(
        id="social-profiles", title="Official profiles are linked from the markup",
        area="seo", category="structured_data", weight=3, detection="auto",
        standard="schema.org sameAs",
        why="sameAs links tie the website to the business's other profiles, which is how search engines "
            "confirm they are the same entity.",
        fix="Add sameAs entries for your Google Business Profile, Facebook, Yelp and similar.",
        auto_fixable=True,
    ),

    # ------------------------------------------------------------------- content
    Check(
        id="title-tag", title="Page titles are present and well formed",
        area="seo", category="content", weight=9, detection="auto",
        standard="Google Search Central: title links",
        why="The title is the headline in search results and the strongest on-page signal of what the "
            "page is about.",
        fix="Write a 30-60 character title naming the service and the location.",
        auto_fixable=True,
    ),
    Check(
        id="meta-description", title="Pages have a meta description",
        area="seo", category="content", weight=6, detection="auto",
        standard="Google Search Central: snippets",
        why="It is the sales pitch under the search result, and AI summaries often reuse it. Without one, "
            "search engines cut a random sentence from the page.",
        fix="Write a 120-160 character description of what the page offers.",
        auto_fixable=True,
    ),
    Check(
        id="h1", title="Each page has exactly one H1", area="seo", category="content",
        weight=6, detection="auto", standard="Google Search Central: heading structure",
        why="The H1 states the subject of the page. None leaves it ambiguous; several muddy it.",
        fix="Give each page a single H1 describing that page.",
        auto_fixable=True,
    ),
    Check(
        id="content-depth", title="Pages have enough readable text",
        area="seo", category="content", weight=7, detection="auto",
        standard="Google Search Central: helpful content",
        why="A home page with forty words gives search engines and assistants almost nothing to match a "
            "question against, so the business loses to competitors who wrote a few paragraphs.",
        fix="Add real descriptions of services, service area, and what makes the business different.",
    ),
    Check(
        id="nap-visible", title="Phone and address appear in the page text",
        area="seo", category="content", weight=7, detection="auto",
        standard="Local SEO best practice; Google Business Profile consistency",
        why="Contact details locked inside an image or a script cannot be read, indexed or quoted.",
        fix="Put the phone number and address in the page text, usually the footer.",
    ),
    Check(
        id="descriptive-urls", title="URLs are readable", area="seo", category="content",
        weight=3, detection="auto", standard="Google Search Central: URL structure",
        why="/services/emergency-plumbing tells a person and a crawler what the page is; /p?id=4192 does not.",
        fix="Use short, word-based paths.",
    ),
    Check(
        id="internal-links", title="Pages are linked to each other", area="seo", category="content",
        weight=4, detection="auto", standard="Google Search Central: link best practices",
        why="Orphan pages that nothing links to are rarely found or ranked.",
        fix="Link from the home page and navigation to every important page.",
    ),
    Check(
        id="open-graph", title="Shared links show a preview", area="seo", category="content",
        weight=3, detection="auto", standard="Open Graph protocol",
        why="Without Open Graph tags, a link shared on social or messaging apps renders as a bare URL "
            "and gets far fewer clicks.",
        fix="Add og:title, og:description, og:image and og:url.",
        auto_fixable=True,
    ),

    # --------------------------------------------------------------- performance
    Check(
        id="lcp", title="The main content loads quickly", area="seo", category="performance",
        weight=8, detection="auto", standard="Core Web Vitals: Largest Contentful Paint under 2.5s",
        why="Slow pages are ranked lower and abandoned sooner; most visitors leave before a slow page finishes.",
        fix="Compress and correctly size images, remove render-blocking scripts, enable caching.",
    ),
    Check(
        id="cls", title="The layout doesn't jump while loading",
        area="seo", category="performance", weight=5, detection="auto",
        standard="Core Web Vitals: Cumulative Layout Shift under 0.1",
        why="Content that shifts as it loads makes people tap the wrong thing, and it is a ranking signal.",
        fix="Set width and height on images and reserve space for ads and embeds.",
    ),
    Check(
        id="page-weight", title="The page isn't unnecessarily heavy",
        area="seo", category="performance", weight=5, detection="auto",
        standard="Best practice; web.dev performance budgets",
        why="Multi-megabyte pages cost mobile visitors real money and time, and many simply leave.",
        fix="Compress images, serve modern formats, and remove unused scripts.",
    ),
    Check(
        id="mobile-friendly", title="The site works on a phone", area="seo", category="performance",
        weight=9, detection="auto", standard="Google Search Central: mobile-first indexing",
        why="Google indexes the mobile version first, and most local searches happen on a phone.",
        fix="Add a responsive viewport meta tag and make the layout reflow.",
        auto_fixable=True,
    ),
    Check(
        id="image-optimisation", title="Images are sized and lazily loaded",
        area="seo", category="performance", weight=4, detection="auto",
        standard="web.dev image best practices",
        why="Full-resolution photos scaled down in the browser waste the visitor's data and slow the page.",
        fix="Serve appropriately sized images, add width and height, and lazy-load below-the-fold images.",
        auto_fixable=True,
    ),

    # -------------------------------------------------------------- ai readiness
    Check(
        id="llms-txt", title="There is an llms.txt summary for AI assistants",
        area="seo", category="ai_readiness", weight=6, detection="auto",
        standard="llmstxt.org proposal",
        why="A short, plain summary at /llms.txt gives assistants the business's own words about what it "
            "does, instead of leaving them to infer it from navigation and marketing copy.",
        fix="Publish an llms.txt naming the business, its services, area and contact details.",
        auto_fixable=True,
    ),
    Check(
        id="server-rendered", title="Content exists without running JavaScript",
        area="seo", category="ai_readiness", weight=9, detection="auto",
        standard="Google Search Central: JavaScript SEO; AI crawler behaviour",
        why="Most AI crawlers do not execute JavaScript. If the text only appears after scripts run, "
            "those assistants see an empty page and the business is invisible to them.",
        fix="Server-render or pre-render the content, or export a static version.",
    ),
    Check(
        id="answer-ready-content", title="The page answers real questions directly",
        area="seo", category="ai_readiness", weight=6, detection="heuristic",
        standard="Best practice for generative search and AI assistants",
        why="Assistants quote clear, self-contained statements. Vague marketing copy gives them nothing "
            "to lift, so a competitor's clearer page gets cited instead.",
        fix="State services, area served, hours, pricing approach and answers to common questions plainly.",
        auto_fixable=True,
    ),
    Check(
        id="entity-clarity", title="It is obvious what and where the business is",
        area="seo", category="ai_readiness", weight=7, detection="heuristic",
        standard="Best practice for entity recognition",
        why="If the trade and the town are not stated in plain text, an assistant asked for 'a plumber "
            "near Springfield' has no basis to suggest this one.",
        fix="Say the trade and the location explicitly in the title, the H1 and the opening paragraph.",
        auto_fixable=True,
    ),
    Check(
        id="freshness", title="Content shows signs of being current",
        area="seo", category="ai_readiness", weight=3, detection="heuristic",
        standard="Best practice; Google Search Central: freshness",
        why="Stale copyright years and years-old posts suggest a business that may not still be trading, "
            "which both people and assistants weigh.",
        fix="Keep the footer year current and update key pages periodically.",
        auto_fixable=True,
    ),
    Check(
        id="no-ai-blocking-meta", title="No meta tags block AI use of the content",
        area="seo", category="ai_readiness", weight=4, detection="auto",
        standard="Google Search Central: nosnippet, max-snippet, noai conventions",
        why="nosnippet and similar tags stop AI answers quoting the site, which usually is not what a "
            "small business wants.",
        fix="Remove nosnippet, noarchive and noai directives unless they are deliberate.",
        auto_fixable=True,
    ),
]

ALL_CHECKS: list[Check] = ADA_CHECKS + SEO_CHECKS
BY_ID: dict[str, Check] = {c.id: c for c in ALL_CHECKS}

# axe rule id -> the check it decides. Built once, used by the scanner.
AXE_RULE_TO_CHECK: dict[str, str] = {rule: c.id for c in ALL_CHECKS for rule in c.axe_rules}

CATEGORY_TITLES = {
    "perceivable": "Perceivable - can people take the information in?",
    "operable": "Operable - can people use it without a mouse or good eyesight?",
    "understandable": "Understandable - is it predictable and clear?",
    "robust": "Robust - does it work with assistive technology?",
    "crawlability": "Crawlability - can search engines and assistants reach it?",
    "structured_data": "Structured data - do machines know what the business is?",
    "content": "Content and metadata - is there something worth showing?",
    "performance": "Performance - is it fast enough on a phone?",
    "ai_readiness": "AI readiness - can an assistant read, understand and quote it?",
}


def checks_added_since(version: str | None) -> list[Check]:
    """Checks a site last measured at ``version`` has never been tested against.

    This is what turns "we keep up with the rules" from a sales line into something the
    monthly report can actually show.
    """
    if not version:
        return []
    return sorted((c for c in ALL_CHECKS if c.since > version), key=lambda c: (c.since, c.area, c.id))


def version_notes_since(version: str | None) -> list[tuple[str, str]]:
    """(version, what changed) for every checklist release after ``version``."""
    if not version:
        return []
    return [(v, note) for v, note in sorted(VERSION_NOTES.items()) if v > version]


def checks_for(area: Area) -> list[Check]:
    return [c for c in ALL_CHECKS if c.area == area]


def auto_fixable_ids(area: Area | None = None) -> set[str]:
    return {c.id for c in ALL_CHECKS if c.auto_fixable and (area is None or c.area == area)}
