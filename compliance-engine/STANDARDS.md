# The checklist

Everything this engine checks on a website, why each item matters, and what fixing it
involves. It is generated from `engine/standards/checks.py`, which is the same list the
scanner scores against and the fixer repairs from - so this document cannot drift away
from what the code actually does.

Use it two ways:

* **As a build standard.** Work down it when you make a site and it will score close to
  100% on both halves before anyone ever scans it. The reference implementation in
  `tests/fixtures/sites/good_site/` scores 100/100 and is worth reading alongside this.
* **As the scoring model.** Percentages are earned weight over applicable weight, so a
  site is only ever judged on the checks that apply to it.

## How the percentages work

```
score = sum(weight of checks that PASSED) / sum(weight of checks that PASSED or FAILED)
```

Three rules keep that number honest:

1. **Checks that don't apply are excluded.** No video means no captions check, and no
   penalty for it. The denominator is per-site, not a fixed total.
2. **Checks needing a person are never scored.** They are listed in the report as
   "needs a person to check" and excluded from both halves of the fraction.
3. **Checks the tools couldn't decide are excluded too.** Guessing and presenting it as a
   measurement would be dishonest.

So the headline number means *automated conformance against the checks that apply to this
site*. Automated testing catches roughly a third to a half of real accessibility problems;
the rest genuinely need a human with a keyboard and a screen reader. **A percentage here is
not a statement that a site is legally compliant, and the report never claims it is.**

### Bands

| Score | Band |
|---|---|
| 95-100% | excellent |
| 85-94% | good |
| 70-84% | fair |
| 50-69% | poor |
| under 50% | critical |

### How to read the columns

* **Weight** - how much the check moves the score, 1 to 10.
* **How it's checked** - `automated` (a tool decides), `heuristic` (our rule of thumb,
  usually right), `needs a person` (listed, never scored).
* **We fix it** - yes means the remediation bundle repairs it without the client doing
  anything.

## Editions

The checklist is versioned `YYYY.MM`, because clients on the monthly plan pay for it to stay
current. When the accessibility guidelines change, or search engines and AI assistants change
what they read, a check is added here and the version is bumped; every site on a care plan is
measured against the new list at its next monthly check and told in its report what changed.
Each check records the edition that introduced it.

| Edition | What changed |
|---|---|
| **2026.09** *(current)* | first published checklist: WCAG 2.2 A/AA plus the AI-search and structured-data items (80 checks) |

## Part 1 - Accessibility

Measured against **WCAG 2.2 Level A and AA**, the standard US courts and the Department of Justice's guidance point to. Organised by the four WCAG principles.

46 checks, 266 total weight. 24 of them we fix automatically; 14 need a person.

### Perceivable - can people take the information in?

| # | Check | Weight | How it's checked | We fix it | Standard |
|---|---|---|---|---|---|
| 1 | **Images have text alternatives**<br><span title='image-alt'>`image-alt`</span> | 10 | automated | yes | WCAG 2.2 SC 1.1.1 Non-text Content (A) |
| 2 | **Alt text is meaningful, not a filename**<br><span title='image-alt-quality'>`image-alt-quality`</span> | 4 | heuristic | yes | WCAG 2.2 SC 1.1.1 Non-text Content (A) |
| 3 | **Video has captions**<br><span title='video-captions'>`video-captions`</span> | 8 | needs a person | no | WCAG 2.2 SC 1.2.2 Captions (Prerecorded) (A) |
| 4 | **Video has audio description where needed**<br><span title='audio-description'>`audio-description`</span> | 4 | needs a person | no | WCAG 2.2 SC 1.2.5 Audio Description (Prerecorded) (AA) |
| 5 | **Headings, lists and tables use real markup**<br><span title='semantic-structure'>`semantic-structure`</span> | 9 | automated | yes | WCAG 2.2 SC 1.3.1 Info and Relationships (A) |
| 6 | **Form fields have labels**<br><span title='form-labels'>`form-labels`</span> | 10 | automated | yes | WCAG 2.2 SC 1.3.1 Info and Relationships (A), 3.3.2 Labels or Instructions (A) |
| 7 | **Common fields declare their purpose**<br><span title='input-purpose'>`input-purpose`</span> | 3 | automated | yes | WCAG 2.2 SC 1.3.5 Identify Input Purpose (AA) |
| 8 | **Reading order makes sense without styling**<br><span title='meaningful-sequence'>`meaningful-sequence`</span> | 5 | needs a person | no | WCAG 2.2 SC 1.3.2 Meaningful Sequence (A) |
| 9 | **Instructions don't rely on shape or position alone**<br><span title='sensory-characteristics'>`sensory-characteristics`</span> | 3 | needs a person | no | WCAG 2.2 SC 1.3.3 Sensory Characteristics (A) |
| 10 | **Colour is not the only way information is shown**<br><span title='color-not-alone'>`color-not-alone`</span> | 6 | heuristic | yes | WCAG 2.2 SC 1.4.1 Use of Color (A) |
| 11 | **Nothing plays sound automatically**<br><span title='audio-control'>`audio-control`</span> | 7 | automated | yes | WCAG 2.2 SC 1.4.2 Audio Control (A) |
| 12 | **Text has enough contrast against its background**<br><span title='color-contrast'>`color-contrast`</span> | 10 | automated | yes | WCAG 2.2 SC 1.4.3 Contrast (Minimum) (AA) |
| 13 | **Buttons, icons and form borders have enough contrast**<br><span title='non-text-contrast'>`non-text-contrast`</span> | 6 | heuristic | no | WCAG 2.2 SC 1.4.11 Non-text Contrast (AA) |
| 14 | **Text can be enlarged to 200% without breaking**<br><span title='resize-text'>`resize-text`</span> | 6 | heuristic | no | WCAG 2.2 SC 1.4.4 Resize Text (AA), 1.4.10 Reflow (AA) |
| 15 | **Pinch zoom is not disabled**<br><span title='zoom-enabled'>`zoom-enabled`</span> | 7 | automated | yes | WCAG 2.2 SC 1.4.4 Resize Text (AA) |
| 16 | **Text is real text, not pictures of text**<br><span title='images-of-text'>`images-of-text`</span> | 4 | needs a person | no | WCAG 2.2 SC 1.4.5 Images of Text (AA) |
| 17 | **Layout survives increased text spacing**<br><span title='text-spacing'>`text-spacing`</span> | 3 | needs a person | no | WCAG 2.2 SC 1.4.12 Text Spacing (AA) |
| 18 | **Tooltips and popovers can be dismissed and hovered**<br><span title='hover-content'>`hover-content`</span> | 3 | needs a person | no | WCAG 2.2 SC 1.4.13 Content on Hover or Focus (AA) |

#### `image-alt` - Images have text alternatives

*WCAG 2.2 SC 1.1.1 Non-text Content (A)* &middot; weight 10 &middot; automated &middot; applies to pages containing images &middot; we fix this automatically

**Why it matters.** A screen reader announces nothing for an image with no alt text, so a blind visitor misses whatever it conveyed - often the product, the menu, or the phone number.

**How to fix it.** Add alt text describing what the image conveys; use empty alt for purely decorative images.

#### `image-alt-quality` - Alt text is meaningful, not a filename

*WCAG 2.2 SC 1.1.1 Non-text Content (A)* &middot; weight 4 &middot; heuristic &middot; applies to pages containing images &middot; we fix this automatically

**Why it matters.** Alt text like 'IMG_4821.jpg' or 'image' is technically present but tells a blind visitor nothing.

**How to fix it.** Replace placeholder alt text with a short description of what the image shows.

#### `video-captions` - Video has captions

*WCAG 2.2 SC 1.2.2 Captions (Prerecorded) (A)* &middot; weight 8 &middot; needs a person &middot; applies to pages containing video &middot; needs a decision or content from the owner

**Why it matters.** Deaf and hard-of-hearing visitors cannot use video without captions, and most people watch without sound anyway.

**How to fix it.** Upload a caption file, or use your video host's caption feature. Auto-captions must be corrected.

#### `audio-description` - Video has audio description where needed

*WCAG 2.2 SC 1.2.5 Audio Description (Prerecorded) (AA)* &middot; weight 4 &middot; needs a person &middot; applies to pages with video that conveys visual information &middot; needs a decision or content from the owner

**Why it matters.** Visual information shown but never spoken is lost to blind visitors.

**How to fix it.** Add an audio description track, or narrate the on-screen information in the video itself.

#### `semantic-structure` - Headings, lists and tables use real markup

*WCAG 2.2 SC 1.3.1 Info and Relationships (A)* &middot; weight 9 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Screen reader users navigate by heading and list. Text that only looks like a heading because it is big and bold is invisible to that navigation.

**How to fix it.** Use real <h1>-<h6>, <ul>/<ol> and table headers instead of styled paragraphs and divs.

#### `form-labels` - Form fields have labels

*WCAG 2.2 SC 1.3.1 Info and Relationships (A), 3.3.2 Labels or Instructions (A)* &middot; weight 10 &middot; automated &middot; applies to pages containing forms &middot; we fix this automatically

**Why it matters.** An unlabelled field is announced as just 'edit text'. A visitor cannot tell whether to type their name, email or postcode - so the contact form never gets submitted.

**How to fix it.** Give every field a visible <label> tied to it, or an aria-label where a visible one won't fit.

#### `input-purpose` - Common fields declare their purpose

*WCAG 2.2 SC 1.3.5 Identify Input Purpose (AA)* &middot; weight 3 &middot; automated &middot; applies to pages containing forms &middot; we fix this automatically

**Why it matters.** Autocomplete attributes let browsers and assistive tools fill in name, email and address automatically, which matters a great deal for people with motor or memory difficulties.

**How to fix it.** Add autocomplete="name", "email", "tel" and so on to the matching fields.

#### `meaningful-sequence` - Reading order makes sense without styling

*WCAG 2.2 SC 1.3.2 Meaningful Sequence (A)* &middot; weight 5 &middot; needs a person &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Screen readers follow the order of the markup, not the visual layout. CSS-positioned content can be read in a nonsensical order.

**How to fix it.** Order the markup to match the intended reading order and use CSS for placement.

#### `sensory-characteristics` - Instructions don't rely on shape or position alone

*WCAG 2.2 SC 1.3.3 Sensory Characteristics (A)* &middot; weight 3 &middot; needs a person &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** 'Click the round button on the right' is useless to someone who cannot see the layout.

**How to fix it.** Refer to controls by their visible name as well as their position.

#### `color-not-alone` - Colour is not the only way information is shown

*WCAG 2.2 SC 1.4.1 Use of Color (A)* &middot; weight 6 &middot; heuristic &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Around one in twelve men has some colour blindness. Required fields marked only in red, or links distinguished only by colour, disappear for them.

**How to fix it.** Add a second signal: an underline on links, an asterisk or text on required fields, an icon on errors.

#### `audio-control` - Nothing plays sound automatically

*WCAG 2.2 SC 1.4.2 Audio Control (A)* &middot; weight 7 &middot; automated &middot; applies to pages with audio or video &middot; we fix this automatically

**Why it matters.** Audio that starts on its own drowns out a screen reader, making the whole page unusable.

**How to fix it.** Remove autoplay, or start muted with a visible control to unmute.

#### `color-contrast` - Text has enough contrast against its background

*WCAG 2.2 SC 1.4.3 Contrast (Minimum) (AA)* &middot; weight 10 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Light grey on white is the single most common accessibility failure on small business sites, and it affects everyone reading on a phone in daylight, not just people with low vision.

**How to fix it.** Darken the text or lighten the background until normal text reaches a 4.5:1 ratio (3:1 for large text).

#### `non-text-contrast` - Buttons, icons and form borders have enough contrast

*WCAG 2.2 SC 1.4.11 Non-text Contrast (AA)* &middot; weight 6 &middot; heuristic &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** A pale grey input border or icon can be invisible to someone with low vision, so they cannot tell where to click or type.

**How to fix it.** Give interface components and their states at least a 3:1 contrast ratio against what surrounds them.

#### `resize-text` - Text can be enlarged to 200% without breaking

*WCAG 2.2 SC 1.4.4 Resize Text (AA), 1.4.10 Reflow (AA)* &middot; weight 6 &middot; heuristic &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** People who need larger text zoom in. If the layout is fixed-width or clips, the content becomes unreadable or requires scrolling in two directions.

**How to fix it.** Use relative units and responsive layout so content reflows in a 320px-wide viewport.

#### `zoom-enabled` - Pinch zoom is not disabled

*WCAG 2.2 SC 1.4.4 Resize Text (AA)* &middot; weight 7 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Blocking zoom on mobile stops anyone who needs bigger text from reading the site at all.

**How to fix it.** Remove user-scalable=no and maximum-scale from the viewport meta tag.

#### `images-of-text` - Text is real text, not pictures of text

*WCAG 2.2 SC 1.4.5 Images of Text (AA)* &middot; weight 4 &middot; needs a person &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Text baked into an image cannot be resized, recoloured, translated, read aloud, or found by search engines and AI assistants.

**How to fix it.** Replace text images (menus, price lists, hours) with real HTML text styled with CSS.

#### `text-spacing` - Layout survives increased text spacing

*WCAG 2.2 SC 1.4.12 Text Spacing (AA)* &middot; weight 3 &middot; needs a person &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Some people with dyslexia increase line and letter spacing. Rigid layouts clip the text when they do.

**How to fix it.** Avoid fixed heights on text containers; let them grow.

#### `hover-content` - Tooltips and popovers can be dismissed and hovered

*WCAG 2.2 SC 1.4.13 Content on Hover or Focus (AA)* &middot; weight 3 &middot; needs a person &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Content that appears on hover and vanishes when the pointer moves is unusable for people using magnification.

**How to fix it.** Make hover content dismissible with Escape, hoverable, and persistent until dismissed.

### Operable - can people use it without a mouse or good eyesight?

| # | Check | Weight | How it's checked | We fix it | Standard |
|---|---|---|---|---|---|
| 1 | **Everything works with a keyboard**<br><span title='keyboard-access'>`keyboard-access`</span> | 10 | heuristic | no | WCAG 2.2 SC 2.1.1 Keyboard (A) |
| 2 | **Keyboard focus is never trapped**<br><span title='no-keyboard-trap'>`no-keyboard-trap`</span> | 8 | needs a person | no | WCAG 2.2 SC 2.1.2 No Keyboard Trap (A) |
| 3 | **Keyboard focus is clearly visible**<br><span title='focus-visible'>`focus-visible`</span> | 9 | heuristic | yes | WCAG 2.2 SC 2.4.7 Focus Visible (AA) |
| 4 | **Tab order follows the visual order**<br><span title='focus-order'>`focus-order`</span> | 6 | heuristic | yes | WCAG 2.2 SC 2.4.3 Focus Order (A) |
| 5 | **Focused elements are not hidden behind sticky bars**<br><span title='focus-not-obscured'>`focus-not-obscured`</span> | 4 | needs a person | no | WCAG 2.2 SC 2.4.11 Focus Not Obscured (Minimum) (AA) |
| 6 | **There is a way to skip repeated navigation**<br><span title='skip-link'>`skip-link`</span> | 6 | automated | yes | WCAG 2.2 SC 2.4.1 Bypass Blocks (A) |
| 7 | **Page regions are marked as landmarks**<br><span title='landmarks'>`landmarks`</span> | 6 | automated | yes | WCAG 2.2 SC 1.3.1 Info and Relationships (A) |
| 8 | **Every page has a unique, descriptive title**<br><span title='page-title'>`page-title`</span> | 8 | automated | yes | WCAG 2.2 SC 2.4.2 Page Titled (A) |
| 9 | **Links say where they go**<br><span title='link-purpose'>`link-purpose`</span> | 8 | automated | yes | WCAG 2.2 SC 2.4.4 Link Purpose (In Context) (A) |
| 10 | **Buttons have accessible names**<br><span title='button-name'>`button-name`</span> | 9 | automated | yes | WCAG 2.2 SC 4.1.2 Name, Role, Value (A) |
| 11 | **Embedded frames are labelled**<br><span title='frame-title'>`frame-title`</span> | 5 | automated | yes | WCAG 2.2 SC 2.4.1 Bypass Blocks (A), 4.1.2 Name, Role, Value (A) |
| 12 | **Heading levels don't skip**<br><span title='heading-order'>`heading-order`</span> | 5 | automated | yes | WCAG 2.2 SC 1.3.1 Info and Relationships (A) |
| 13 | **Tap targets are big enough**<br><span title='target-size'>`target-size`</span> | 5 | automated | yes | WCAG 2.2 SC 2.5.8 Target Size (Minimum) (AA) |
| 14 | **Gestures and dragging have simple alternatives**<br><span title='pointer-alternatives'>`pointer-alternatives`</span> | 4 | needs a person | no | WCAG 2.2 SC 2.5.1 Pointer Gestures (A), 2.5.7 Dragging Movements (AA) |
| 15 | **Visible labels match their accessible names**<br><span title='label-in-name'>`label-in-name`</span> | 4 | heuristic | no | WCAG 2.2 SC 2.5.3 Label in Name (A) |
| 16 | **Time limits and moving content can be controlled**<br><span title='timing-and-motion'>`timing-and-motion`</span> | 5 | automated | yes | WCAG 2.2 SC 2.2.1 Timing Adjustable (A), 2.2.2 Pause, Stop, Hide (A), 2.3.1 Three Flashes (A) |

#### `keyboard-access` - Everything works with a keyboard

*WCAG 2.2 SC 2.1.1 Keyboard (A)* &middot; weight 10 &middot; heuristic &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** People who cannot use a mouse - through motor disability, tremor, or simply a broken trackpad - navigate entirely by keyboard. A menu that only opens on hover locks them out.

**How to fix it.** Make every control reachable with Tab and operable with Enter or Space, using real buttons and links.

#### `no-keyboard-trap` - Keyboard focus is never trapped

*WCAG 2.2 SC 2.1.2 No Keyboard Trap (A)* &middot; weight 8 &middot; needs a person &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** If focus enters a widget or modal it cannot leave, the visitor has to close the browser tab.

**How to fix it.** Ensure Tab and Escape always move focus back out of dialogs, embeds and custom widgets.

#### `focus-visible` - Keyboard focus is clearly visible

*WCAG 2.2 SC 2.4.7 Focus Visible (AA)* &middot; weight 9 &middot; heuristic &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Removing the focus outline is a common 'tidy-up' that leaves keyboard users with no idea where they are on the page.

**How to fix it.** Never set outline:none without an equally clear replacement; add a visible :focus-visible style.

#### `focus-order` - Tab order follows the visual order

*WCAG 2.2 SC 2.4.3 Focus Order (A)* &middot; weight 6 &middot; heuristic &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Positive tabindex values and reordered layouts send focus jumping around the page unpredictably.

**How to fix it.** Remove positive tabindex values and let the document order carry the focus order.

#### `focus-not-obscured` - Focused elements are not hidden behind sticky bars

*WCAG 2.2 SC 2.4.11 Focus Not Obscured (Minimum) (AA)* &middot; weight 4 &middot; needs a person &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Sticky headers and cookie banners frequently cover the element that just received focus.

**How to fix it.** Add scroll padding so focused elements are never fully hidden by fixed overlays.

#### `skip-link` - There is a way to skip repeated navigation

*WCAG 2.2 SC 2.4.1 Bypass Blocks (A)* &middot; weight 6 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Without a skip link, a screen reader user hears the entire navigation menu again on every single page before reaching the content.

**How to fix it.** Add a 'Skip to main content' link as the first focusable element, and a <main> landmark to skip to.

#### `landmarks` - Page regions are marked as landmarks

*WCAG 2.2 SC 1.3.1 Info and Relationships (A)* &middot; weight 6 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Landmarks let screen reader users jump straight to the navigation, the search, or the main content instead of listening through the page.

**How to fix it.** Wrap the page in <header>, <nav>, <main> and <footer> instead of anonymous <div>s.

#### `page-title` - Every page has a unique, descriptive title

*WCAG 2.2 SC 2.4.2 Page Titled (A)* &middot; weight 8 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** The title is the first thing a screen reader announces and the label on every browser tab and bookmark. 'Home' or 'Untitled' tells nobody anything.

**How to fix it.** Give each page a title naming the page and the business.

#### `link-purpose` - Links say where they go

*WCAG 2.2 SC 2.4.4 Link Purpose (In Context) (A)* &middot; weight 8 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Screen reader users often pull up a list of links to navigate. A list reading 'click here, click here, read more' is useless.

**How to fix it.** Write link text that describes the destination; give icon-only links an aria-label.

#### `button-name` - Buttons have accessible names

*WCAG 2.2 SC 4.1.2 Name, Role, Value (A)* &middot; weight 9 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** An icon-only button with no name is announced as just 'button'. The visitor cannot know it submits the form or opens the menu.

**How to fix it.** Add visible text or an aria-label to every button.

#### `frame-title` - Embedded frames are labelled

*WCAG 2.2 SC 2.4.1 Bypass Blocks (A), 4.1.2 Name, Role, Value (A)* &middot; weight 5 &middot; automated &middot; applies to pages containing iframes &middot; we fix this automatically

**Why it matters.** Embedded maps, videos and booking widgets are announced as 'frame' with no indication of what they contain.

**How to fix it.** Add a title attribute to every iframe describing its contents.

#### `heading-order` - Heading levels don't skip

*WCAG 2.2 SC 1.3.1 Info and Relationships (A)* &middot; weight 5 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Heading level is how screen reader users understand the structure of a page. Jumping from an H1 straight to an H4 implies a hierarchy that isn't there.

**How to fix it.** Step heading levels one at a time and use CSS for size.

#### `target-size` - Tap targets are big enough

*WCAG 2.2 SC 2.5.8 Target Size (Minimum) (AA)* &middot; weight 5 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Small, tightly packed links are hard to hit for anyone with a tremor, and awkward for everyone on a phone.

**How to fix it.** Give interactive elements at least a 24 by 24 pixel target, or enough spacing around them.

#### `pointer-alternatives` - Gestures and dragging have simple alternatives

*WCAG 2.2 SC 2.5.1 Pointer Gestures (A), 2.5.7 Dragging Movements (AA)* &middot; weight 4 &middot; needs a person &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Carousels that only respond to swipe, or sliders that only respond to drag, exclude people who cannot perform those movements.

**How to fix it.** Provide buttons that do the same thing as the swipe or drag.

#### `label-in-name` - Visible labels match their accessible names

*WCAG 2.2 SC 2.5.3 Label in Name (A)* &middot; weight 4 &middot; heuristic &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Voice control users say the visible label out loud. If the underlying name differs, nothing happens.

**How to fix it.** Make the accessible name start with, or contain, the visible text.

#### `timing-and-motion` - Time limits and moving content can be controlled

*WCAG 2.2 SC 2.2.1 Timing Adjustable (A), 2.2.2 Pause, Stop, Hide (A), 2.3.1 Three Flashes (A)* &middot; weight 5 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Auto-advancing carousels and auto-refreshing pages steal focus and reading position. Flashing content can trigger seizures.

**How to fix it.** Let people pause moving content; remove meta refresh and blinking or flashing elements.

### Understandable - is it predictable and clear?

| # | Check | Weight | How it's checked | We fix it | Standard |
|---|---|---|---|---|---|
| 1 | **The page declares its language**<br><span title='page-language'>`page-language`</span> | 7 | automated | yes | WCAG 2.2 SC 3.1.1 Language of Page (A) |
| 2 | **Foreign phrases are marked up**<br><span title='language-of-parts'>`language-of-parts`</span> | 2 | needs a person | no | WCAG 2.2 SC 3.1.2 Language of Parts (AA) |
| 3 | **Navigation is consistent across pages**<br><span title='consistent-navigation'>`consistent-navigation`</span> | 4 | heuristic | no | WCAG 2.2 SC 3.2.3 Consistent Navigation (AA), 3.2.4 Consistent Identification (AA) |
| 4 | **Nothing changes unexpectedly on focus or input**<br><span title='no-surprise-changes'>`no-surprise-changes`</span> | 4 | needs a person | no | WCAG 2.2 SC 3.2.1 On Focus (A), 3.2.2 On Input (A) |
| 5 | **Form errors are described in text**<br><span title='error-identification'>`error-identification`</span> | 6 | heuristic | no | WCAG 2.2 SC 3.3.1 Error Identification (A), 3.3.3 Error Suggestion (AA) |
| 6 | **Help and contact details are easy to find**<br><span title='consistent-help'>`consistent-help`</span> | 3 | heuristic | no | WCAG 2.2 SC 3.2.6 Consistent Help (A) |
| 7 | **Login doesn't depend on a memory test**<br><span title='accessible-auth'>`accessible-auth`</span> | 3 | needs a person | no | WCAG 2.2 SC 3.3.8 Accessible Authentication (Minimum) (AA) |

#### `page-language` - The page declares its language

*WCAG 2.2 SC 3.1.1 Language of Page (A)* &middot; weight 7 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Without a language declaration a screen reader may read English with a French voice, rendering it incomprehensible.

**How to fix it.** Add lang="en" (or the right language) to the <html> element.

#### `language-of-parts` - Foreign phrases are marked up

*WCAG 2.2 SC 3.1.2 Language of Parts (AA)* &middot; weight 2 &middot; needs a person &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Passages in another language are mispronounced unless marked.

**How to fix it.** Wrap foreign-language passages in an element with the right lang attribute.

#### `consistent-navigation` - Navigation is consistent across pages

*WCAG 2.2 SC 3.2.3 Consistent Navigation (AA), 3.2.4 Consistent Identification (AA)* &middot; weight 4 &middot; heuristic &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Menus that reorder themselves between pages force people to relearn the site on every page.

**How to fix it.** Keep navigation in the same order and label the same things the same way throughout.

#### `no-surprise-changes` - Nothing changes unexpectedly on focus or input

*WCAG 2.2 SC 3.2.1 On Focus (A), 3.2.2 On Input (A)* &middot; weight 4 &middot; needs a person &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** A form that submits itself when a dropdown changes, or a new window that opens on focus, disorients people using screen readers.

**How to fix it.** Require an explicit button press for anything that navigates or submits.

#### `error-identification` - Form errors are described in text

*WCAG 2.2 SC 3.3.1 Error Identification (A), 3.3.3 Error Suggestion (AA)* &middot; weight 6 &middot; heuristic &middot; applies to pages containing forms &middot; needs a decision or content from the owner

**Why it matters.** An error shown only as a red border tells a blind visitor nothing, and they cannot complete the contact form.

**How to fix it.** Describe each error in text next to the field, and say how to fix it.

#### `consistent-help` - Help and contact details are easy to find

*WCAG 2.2 SC 3.2.6 Consistent Help (A)* &middot; weight 3 &middot; heuristic &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** People who need help should find the contact route in the same place on every page.

**How to fix it.** Put contact details or a help link in the same location site-wide.

#### `accessible-auth` - Login doesn't depend on a memory test

*WCAG 2.2 SC 3.3.8 Accessible Authentication (Minimum) (AA)* &middot; weight 3 &middot; needs a person &middot; applies to sites with a login &middot; needs a decision or content from the owner

**Why it matters.** Puzzle CAPTCHAs and transcription tests exclude people with cognitive disabilities.

**How to fix it.** Allow password managers to paste, and offer an alternative to puzzle-based checks.

### Robust - does it work with assistive technology?

| # | Check | Weight | How it's checked | We fix it | Standard |
|---|---|---|---|---|---|
| 1 | **ARIA is used correctly**<br><span title='aria-valid'>`aria-valid`</span> | 8 | automated | yes | WCAG 2.2 SC 4.1.2 Name, Role, Value (A) |
| 2 | **Element IDs used by ARIA are unique**<br><span title='unique-ids'>`unique-ids`</span> | 4 | automated | yes | WCAG 2.2 SC 4.1.2 Name, Role, Value (A) |
| 3 | **Custom widgets expose a name and role**<br><span title='widget-names'>`widget-names`</span> | 6 | automated | no | WCAG 2.2 SC 4.1.2 Name, Role, Value (A) |
| 4 | **Dynamic updates are announced**<br><span title='status-messages'>`status-messages`</span> | 4 | needs a person | no | WCAG 2.2 SC 4.1.3 Status Messages (AA) |
| 5 | **The site has an accessibility statement**<br><span title='accessibility-statement'>`accessibility-statement`</span> | 5 | automated | yes | Best practice; expected by the DOJ's web accessibility guidance |

#### `aria-valid` - ARIA is used correctly

*WCAG 2.2 SC 4.1.2 Name, Role, Value (A)* &middot; weight 8 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Broken ARIA is worse than none: it actively lies to assistive technology about what an element is and what it does.

**How to fix it.** Correct invalid roles, attributes and values, or remove the ARIA and use native HTML.

#### `unique-ids` - Element IDs used by ARIA are unique

*WCAG 2.2 SC 4.1.2 Name, Role, Value (A)* &middot; weight 4 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Duplicate IDs make label and description references point at the wrong element.

**How to fix it.** Make every ID on the page unique.

#### `widget-names` - Custom widgets expose a name and role

*WCAG 2.2 SC 4.1.2 Name, Role, Value (A)* &middot; weight 6 &middot; automated &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Custom dropdowns, dialogs and sliders built from divs are announced as nothing at all.

**How to fix it.** Give custom widgets the right role and an accessible name, or use native elements.

#### `status-messages` - Dynamic updates are announced

*WCAG 2.2 SC 4.1.3 Status Messages (AA)* &middot; weight 4 &middot; needs a person &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** 'Message sent' or 'added to cart' shown only visually is never announced to a screen reader user.

**How to fix it.** Put status messages in a live region (role="status" or aria-live="polite").

#### `accessibility-statement` - The site has an accessibility statement

*Best practice; expected by the DOJ's web accessibility guidance* &middot; weight 5 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** A statement giving a contact route for access problems is the single cheapest thing that de-escalates a complaint before it becomes a demand letter.

**How to fix it.** Publish a page stating your commitment, the standard you aim for, and how to report a problem.

## Part 2 - Search and AI discoverability

Whether a search engine or an AI assistant can reach the site, read it, work out what the business is, and quote it accurately. Traditional SEO and AI readiness have converged: both now depend on machine-readable facts rather than keywords.

34 checks, 207 total weight. 24 of them we fix automatically; 0 need a person.

### Crawlability - can search engines and assistants reach it?

| # | Check | Weight | How it's checked | We fix it | Standard |
|---|---|---|---|---|---|
| 1 | **robots.txt exists and is valid**<br><span title='robots-exists'>`robots-exists`</span> | 5 | automated | yes | Robots Exclusion Protocol (RFC 9309) |
| 2 | **Search crawlers are not blocked**<br><span title='crawlers-allowed'>`crawlers-allowed`</span> | 10 | automated | yes | Robots Exclusion Protocol (RFC 9309) |
| 3 | **AI assistants are allowed to read the site**<br><span title='ai-crawlers-allowed'>`ai-crawlers-allowed`</span> | 9 | automated | yes | Publisher controls for GPTBot, ClaudeBot, PerplexityBot, Google-Extended |
| 4 | **An XML sitemap exists and is referenced**<br><span title='sitemap'>`sitemap`</span> | 6 | automated | yes | sitemaps.org protocol 0.9 |
| 5 | **Pages are not accidentally set to noindex**<br><span title='indexable'>`indexable`</span> | 10 | automated | yes | Google Search Central: robots meta tag |
| 6 | **The site is served over HTTPS**<br><span title='https'>`https`</span> | 8 | automated | no | Google Search Central: HTTPS as a ranking signal |
| 7 | **Pages declare a canonical URL**<br><span title='canonical'>`canonical`</span> | 4 | automated | yes | Google Search Central: canonicalization |
| 8 | **Internal links are not broken**<br><span title='broken-links'>`broken-links`</span> | 5 | automated | no | Best practice |

#### `robots-exists` - robots.txt exists and is valid

*Robots Exclusion Protocol (RFC 9309)* &middot; weight 5 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Without it, every crawler has to guess what it may read, and some guess conservatively.

**How to fix it.** Publish a robots.txt at the site root that allows crawling and points to your sitemap.

#### `crawlers-allowed` - Search crawlers are not blocked

*Robots Exclusion Protocol (RFC 9309)* &middot; weight 10 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** A stray 'Disallow: /' is the fastest way to make a site vanish from Google entirely. It happens most often when a staging site goes live unchanged.

**How to fix it.** Remove blanket Disallow rules for search crawlers.

#### `ai-crawlers-allowed` - AI assistants are allowed to read the site

*Publisher controls for GPTBot, ClaudeBot, PerplexityBot, Google-Extended* &middot; weight 9 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** If ChatGPT, Claude, Perplexity and Google's AI answers cannot read the site, the business simply cannot be recommended when someone asks an assistant for a local supplier.

**How to fix it.** Remove Disallow rules aimed at AI crawler user agents in robots.txt.

#### `sitemap` - An XML sitemap exists and is referenced

*sitemaps.org protocol 0.9* &middot; weight 6 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** A sitemap is how crawlers find pages that are not well linked from the home page.

**How to fix it.** Generate sitemap.xml, keep it current, and reference it from robots.txt.

#### `indexable` - Pages are not accidentally set to noindex

*Google Search Central: robots meta tag* &middot; weight 10 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** A leftover noindex tag removes a page from search results completely, however good it is.

**How to fix it.** Remove noindex from pages that should be found.

#### `https` - The site is served over HTTPS

*Google Search Central: HTTPS as a ranking signal* &middot; weight 8 &middot; automated &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Browsers label plain HTTP sites 'Not secure', which costs trust and conversions, and it is a ranking signal.

**How to fix it.** Install a TLS certificate (free with most hosts) and redirect HTTP to HTTPS.

#### `canonical` - Pages declare a canonical URL

*Google Search Central: canonicalization* &middot; weight 4 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Without one, the same page reachable at several addresses splits its ranking signals.

**How to fix it.** Add a canonical link element naming the preferred address of each page.

#### `broken-links` - Internal links are not broken

*Best practice* &middot; weight 5 &middot; automated &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Dead internal links waste crawl budget and strand visitors.

**How to fix it.** Fix or remove links that return an error.

### Structured data - do machines know what the business is?

| # | Check | Weight | How it's checked | We fix it | Standard |
|---|---|---|---|---|---|
| 1 | **The business is described in structured data**<br><span title='structured-data'>`structured-data`</span> | 10 | automated | yes | schema.org LocalBusiness / Organization |
| 2 | **Structured data parses and uses real types**<br><span title='structured-data-valid'>`structured-data-valid`</span> | 6 | automated | yes | schema.org vocabulary; JSON-LD 1.1 |
| 3 | **Name, address and phone are in the markup**<br><span title='nap-structured'>`nap-structured`</span> | 8 | automated | yes | schema.org PostalAddress; Google Business Profile consistency |
| 4 | **Opening hours are machine readable**<br><span title='opening-hours'>`opening-hours`</span> | 5 | automated | yes | schema.org openingHoursSpecification |
| 5 | **Common questions are marked up as FAQs**<br><span title='faq-schema'>`faq-schema`</span> | 4 | automated | yes | schema.org FAQPage |
| 6 | **Page hierarchy is described**<br><span title='breadcrumbs'>`breadcrumbs`</span> | 3 | automated | yes | schema.org BreadcrumbList |
| 7 | **Official profiles are linked from the markup**<br><span title='social-profiles'>`social-profiles`</span> | 3 | automated | yes | schema.org sameAs |

#### `structured-data` - The business is described in structured data

*schema.org LocalBusiness / Organization* &middot; weight 10 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Structured data is how a search engine or AI assistant knows this is a dentist in Springfield rather than a page that happens to mention teeth. Without it the business is guessed at, and often guessed wrong.

**How to fix it.** Add JSON-LD describing the business, its type, address, phone and hours.

#### `structured-data-valid` - Structured data parses and uses real types

*schema.org vocabulary; JSON-LD 1.1* &middot; weight 6 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Malformed JSON-LD is silently ignored, so the effort is wasted without anyone noticing.

**How to fix it.** Fix the JSON syntax and use a recognised @type from schema.org.

#### `nap-structured` - Name, address and phone are in the markup

*schema.org PostalAddress; Google Business Profile consistency* &middot; weight 8 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Consistent name, address and phone across the web is the backbone of local search ranking, and it is what an assistant reads out when someone asks how to contact you.

**How to fix it.** Include the full postal address and telephone in the LocalBusiness structured data.

#### `opening-hours` - Opening hours are machine readable

*schema.org openingHoursSpecification* &middot; weight 5 &middot; automated &middot; applies to businesses with premises or set hours &middot; we fix this automatically

**Why it matters.** 'Are they open now?' is one of the most common questions asked of assistants and search. Hours in an image or free text cannot answer it.

**How to fix it.** Add openingHoursSpecification to the structured data.

#### `faq-schema` - Common questions are marked up as FAQs

*schema.org FAQPage* &middot; weight 4 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** FAQ markup gives assistants exact question-and-answer pairs to quote in your own words rather than paraphrasing or guessing.

**How to fix it.** Add FAQPage structured data for the questions customers actually ask.

#### `breadcrumbs` - Page hierarchy is described

*schema.org BreadcrumbList* &middot; weight 3 &middot; automated &middot; applies to sites with more than one level of pages &middot; we fix this automatically

**Why it matters.** Breadcrumbs help crawlers understand how pages relate, and show up in search results.

**How to fix it.** Add BreadcrumbList structured data on inner pages.

#### `social-profiles` - Official profiles are linked from the markup

*schema.org sameAs* &middot; weight 3 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** sameAs links tie the website to the business's other profiles, which is how search engines confirm they are the same entity.

**How to fix it.** Add sameAs entries for your Google Business Profile, Facebook, Yelp and similar.

### Content and metadata - is there something worth showing?

| # | Check | Weight | How it's checked | We fix it | Standard |
|---|---|---|---|---|---|
| 1 | **Page titles are present and well formed**<br><span title='title-tag'>`title-tag`</span> | 9 | automated | yes | Google Search Central: title links |
| 2 | **Pages have a meta description**<br><span title='meta-description'>`meta-description`</span> | 6 | automated | yes | Google Search Central: snippets |
| 3 | **Each page has exactly one H1**<br><span title='h1'>`h1`</span> | 6 | automated | yes | Google Search Central: heading structure |
| 4 | **Pages have enough readable text**<br><span title='content-depth'>`content-depth`</span> | 7 | automated | no | Google Search Central: helpful content |
| 5 | **Phone and address appear in the page text**<br><span title='nap-visible'>`nap-visible`</span> | 7 | automated | no | Local SEO best practice; Google Business Profile consistency |
| 6 | **URLs are readable**<br><span title='descriptive-urls'>`descriptive-urls`</span> | 3 | automated | no | Google Search Central: URL structure |
| 7 | **Pages are linked to each other**<br><span title='internal-links'>`internal-links`</span> | 4 | automated | no | Google Search Central: link best practices |
| 8 | **Shared links show a preview**<br><span title='open-graph'>`open-graph`</span> | 3 | automated | yes | Open Graph protocol |

#### `title-tag` - Page titles are present and well formed

*Google Search Central: title links* &middot; weight 9 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** The title is the headline in search results and the strongest on-page signal of what the page is about.

**How to fix it.** Write a 30-60 character title naming the service and the location.

#### `meta-description` - Pages have a meta description

*Google Search Central: snippets* &middot; weight 6 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** It is the sales pitch under the search result, and AI summaries often reuse it. Without one, search engines cut a random sentence from the page.

**How to fix it.** Write a 120-160 character description of what the page offers.

#### `h1` - Each page has exactly one H1

*Google Search Central: heading structure* &middot; weight 6 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** The H1 states the subject of the page. None leaves it ambiguous; several muddy it.

**How to fix it.** Give each page a single H1 describing that page.

#### `content-depth` - Pages have enough readable text

*Google Search Central: helpful content* &middot; weight 7 &middot; automated &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** A home page with forty words gives search engines and assistants almost nothing to match a question against, so the business loses to competitors who wrote a few paragraphs.

**How to fix it.** Add real descriptions of services, service area, and what makes the business different.

#### `nap-visible` - Phone and address appear in the page text

*Local SEO best practice; Google Business Profile consistency* &middot; weight 7 &middot; automated &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Contact details locked inside an image or a script cannot be read, indexed or quoted.

**How to fix it.** Put the phone number and address in the page text, usually the footer.

#### `descriptive-urls` - URLs are readable

*Google Search Central: URL structure* &middot; weight 3 &middot; automated &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** /services/emergency-plumbing tells a person and a crawler what the page is; /p?id=4192 does not.

**How to fix it.** Use short, word-based paths.

#### `internal-links` - Pages are linked to each other

*Google Search Central: link best practices* &middot; weight 4 &middot; automated &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Orphan pages that nothing links to are rarely found or ranked.

**How to fix it.** Link from the home page and navigation to every important page.

#### `open-graph` - Shared links show a preview

*Open Graph protocol* &middot; weight 3 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Without Open Graph tags, a link shared on social or messaging apps renders as a bare URL and gets far fewer clicks.

**How to fix it.** Add og:title, og:description, og:image and og:url.

### Performance - is it fast enough on a phone?

| # | Check | Weight | How it's checked | We fix it | Standard |
|---|---|---|---|---|---|
| 1 | **The main content loads quickly**<br><span title='lcp'>`lcp`</span> | 8 | automated | no | Core Web Vitals: Largest Contentful Paint under 2.5s |
| 2 | **The layout doesn't jump while loading**<br><span title='cls'>`cls`</span> | 5 | automated | no | Core Web Vitals: Cumulative Layout Shift under 0.1 |
| 3 | **The page isn't unnecessarily heavy**<br><span title='page-weight'>`page-weight`</span> | 5 | automated | no | Best practice; web.dev performance budgets |
| 4 | **The site works on a phone**<br><span title='mobile-friendly'>`mobile-friendly`</span> | 9 | automated | yes | Google Search Central: mobile-first indexing |
| 5 | **Images are sized and lazily loaded**<br><span title='image-optimisation'>`image-optimisation`</span> | 4 | automated | yes | web.dev image best practices |

#### `lcp` - The main content loads quickly

*Core Web Vitals: Largest Contentful Paint under 2.5s* &middot; weight 8 &middot; automated &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Slow pages are ranked lower and abandoned sooner; most visitors leave before a slow page finishes.

**How to fix it.** Compress and correctly size images, remove render-blocking scripts, enable caching.

#### `cls` - The layout doesn't jump while loading

*Core Web Vitals: Cumulative Layout Shift under 0.1* &middot; weight 5 &middot; automated &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Content that shifts as it loads makes people tap the wrong thing, and it is a ranking signal.

**How to fix it.** Set width and height on images and reserve space for ads and embeds.

#### `page-weight` - The page isn't unnecessarily heavy

*Best practice; web.dev performance budgets* &middot; weight 5 &middot; automated &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Multi-megabyte pages cost mobile visitors real money and time, and many simply leave.

**How to fix it.** Compress images, serve modern formats, and remove unused scripts.

#### `mobile-friendly` - The site works on a phone

*Google Search Central: mobile-first indexing* &middot; weight 9 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Google indexes the mobile version first, and most local searches happen on a phone.

**How to fix it.** Add a responsive viewport meta tag and make the layout reflow.

#### `image-optimisation` - Images are sized and lazily loaded

*web.dev image best practices* &middot; weight 4 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Full-resolution photos scaled down in the browser waste the visitor's data and slow the page.

**How to fix it.** Serve appropriately sized images, add width and height, and lazy-load below-the-fold images.

### AI readiness - can an assistant read, understand and quote it?

| # | Check | Weight | How it's checked | We fix it | Standard |
|---|---|---|---|---|---|
| 1 | **There is an llms.txt summary for AI assistants**<br><span title='llms-txt'>`llms-txt`</span> | 6 | automated | yes | llmstxt.org proposal |
| 2 | **Content exists without running JavaScript**<br><span title='server-rendered'>`server-rendered`</span> | 9 | automated | no | Google Search Central: JavaScript SEO; AI crawler behaviour |
| 3 | **The page answers real questions directly**<br><span title='answer-ready-content'>`answer-ready-content`</span> | 6 | heuristic | yes | Best practice for generative search and AI assistants |
| 4 | **It is obvious what and where the business is**<br><span title='entity-clarity'>`entity-clarity`</span> | 7 | heuristic | yes | Best practice for entity recognition |
| 5 | **Content shows signs of being current**<br><span title='freshness'>`freshness`</span> | 3 | heuristic | yes | Best practice; Google Search Central: freshness |
| 6 | **No meta tags block AI use of the content**<br><span title='no-ai-blocking-meta'>`no-ai-blocking-meta`</span> | 4 | automated | yes | Google Search Central: nosnippet, max-snippet, noai conventions |

#### `llms-txt` - There is an llms.txt summary for AI assistants

*llmstxt.org proposal* &middot; weight 6 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** A short, plain summary at /llms.txt gives assistants the business's own words about what it does, instead of leaving them to infer it from navigation and marketing copy.

**How to fix it.** Publish an llms.txt naming the business, its services, area and contact details.

#### `server-rendered` - Content exists without running JavaScript

*Google Search Central: JavaScript SEO; AI crawler behaviour* &middot; weight 9 &middot; automated &middot; applies to every page &middot; needs a decision or content from the owner

**Why it matters.** Most AI crawlers do not execute JavaScript. If the text only appears after scripts run, those assistants see an empty page and the business is invisible to them.

**How to fix it.** Server-render or pre-render the content, or export a static version.

#### `answer-ready-content` - The page answers real questions directly

*Best practice for generative search and AI assistants* &middot; weight 6 &middot; heuristic &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Assistants quote clear, self-contained statements. Vague marketing copy gives them nothing to lift, so a competitor's clearer page gets cited instead.

**How to fix it.** State services, area served, hours, pricing approach and answers to common questions plainly.

#### `entity-clarity` - It is obvious what and where the business is

*Best practice for entity recognition* &middot; weight 7 &middot; heuristic &middot; applies to every page &middot; we fix this automatically

**Why it matters.** If the trade and the town are not stated in plain text, an assistant asked for 'a plumber near Springfield' has no basis to suggest this one.

**How to fix it.** Say the trade and the location explicitly in the title, the H1 and the opening paragraph.

#### `freshness` - Content shows signs of being current

*Best practice; Google Search Central: freshness* &middot; weight 3 &middot; heuristic &middot; applies to every page &middot; we fix this automatically

**Why it matters.** Stale copyright years and years-old posts suggest a business that may not still be trading, which both people and assistants weigh.

**How to fix it.** Keep the footer year current and update key pages periodically.

#### `no-ai-blocking-meta` - No meta tags block AI use of the content

*Google Search Central: nosnippet, max-snippet, noai conventions* &middot; weight 4 &middot; automated &middot; applies to every page &middot; we fix this automatically

**Why it matters.** nosnippet and similar tags stop AI answers quoting the site, which usually is not what a small business wants.

**How to fix it.** Remove nosnippet, noarchive and noai directives unless they are deliberate.

## Building to this standard

If you are making a site rather than fixing one, the short version:

1. Real HTML: headings in order, lists as lists, buttons as `<button>`, one `<h1>`.
2. Landmarks (`header`, `nav`, `main`, `footer`) and a skip link.
3. Alt text on every image; empty `alt=""` for decoration.
4. Visible labels tied to every form field. A placeholder is not a label.
5. Text contrast at least 4.5:1, and never remove the focus outline without replacing it.
6. A viewport meta tag, no `user-scalable=no`, and a layout that reflows at 320px.
7. `lang` on `<html>`, a descriptive `<title>` and meta description on every page.
8. LocalBusiness JSON-LD with name, address, phone, hours and `sameAs`, plus FAQ markup.
9. `robots.txt` that allows AI crawlers, a `sitemap.xml`, and an `llms.txt` summary.
10. Server-rendered text, the trade and the town in plain words, and an accessibility statement.

`tests/fixtures/sites/good_site/` is a complete worked example that scores 100/100.

---

*Generated from `engine/standards/checks.py` - 80 checks, edition 2026.09. Run `python tools/generate_standards.py` after changing the registry.*
