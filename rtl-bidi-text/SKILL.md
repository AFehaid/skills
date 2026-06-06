---
name: rtl-bidi-text
description: >-
  Correctly render mixed right-to-left (Arabic, Hebrew, Farsi, Urdu) and
  left-to-right (English, numbers, code) text in any UI so it is not misaligned.
  Sets text direction PER BLOCK by counting strong characters (robust for
  code-switching, unlike the fragile dir="auto"), fixes Arabic list
  bullets/numbers landing on the wrong side, right-aligns RTL paragraphs, keeps
  embedded English/code readable, and never flips the whole app. Use this skill
  WHENEVER building or fixing any interface, web page, component, chat,
  dashboard, document, report, transcript, or rendered markdown that displays
  Arabic or other RTL text — especially mixed with English/numbers/code.
  Trigger on symptoms like "the Arabic looks wrong/ugly/misaligned", Arabic
  showing left-aligned, bullet points or list numbers on the wrong side,
  punctuation in the wrong place, messages/notes reading the wrong direction,
  or any request mentioning RTL, bidi, bidirectional, "right to left", "make it
  Arabic-friendly", or pasting mixed Arabic/English content into a UI. Applies
  to React, Vue, Svelte, vanilla JS/HTML/CSS, and rendered markdown.
---

# Bidirectional (RTL + LTR) text

Mixed Arabic/Hebrew + English content is one of the most commonly botched UI
details. The failures are predictable and avoidable. This skill encodes the
approach that actually works for **code-switched** content (text that flips
between scripts mid-message), plus drop-in helpers so you don't reinvent it.

## The core principle

Direction is a property of **each block of content**, not of the document, and
not of the first character. Decide it by which script **dominates** that block:
count strong RTL characters vs strong LTR characters — if RTL wins, the block is
`dir="rtl"`.

Why counting (not `dir="auto"`): `dir="auto"` and `unicode-bidi: plaintext` look
only at the **first** strong character. A line like `Speaker 1: مرحبا بكم` starts
with English, so they force the whole (mostly-Arabic) line left-to-right — wrong.
Counting handles both `Speaker 1: مرحبا` (English-dominant → ltr) and
`مرحبا بكم يا Speaker 1` (Arabic-dominant → rtl) correctly.

## Use the bundled helpers — don't rewrite them

- **`scripts/bidi.js`** — framework-agnostic. `dirOf(text)`, `applyDirection(container)`,
  and `observe(container)` for live/streaming content. Works as an ES module,
  CommonJS, or a plain `<script>` (exposes `window.Bidi`).
- **`assets/bidi.css`** — alignment + RTL-correct list indentation. Put content
  inside a `.bidi` container.

Minimal web setup:

```html
<div class="bidi" id="content"><!-- your rendered text / markdown HTML --></div>
<script type="module">
  import { applyDirection } from './bidi.js';
  applyDirection(document.getElementById('content'));
</script>
```

For **live or streaming** content (chat, async renders, markdown that updates),
use `observe(container)` instead — it re-applies direction (debounced) whenever
the text changes, so messages get their direction as they stream in.

## The five things that actually break (and why)

1. **List bullets/numbers on the wrong side** — the #1 bug. The marker sits on
   the side of the *list's* direction, so you must set `dir` on the `<ul>`/`<ol>`
   element itself, not just the `<li>` text. (`bidi.js` does this.) And the
   indent must be logical (`margin-inline-start`), or a physical `margin-left`
   keeps Arabic bullets pinned to the left even when the text is RTL.

2. **Hard-coded alignment & spacing** — `text-align: left`, `margin-left`,
   `padding-left` never flip. Use the logical equivalents: `text-align: start`,
   `margin-inline-start`, `padding-inline-start`. Then RTL blocks right-align and
   indent from the right automatically, while LTR blocks stay left.

3. **`dir="auto"` / `unicode-bidi: plaintext`** — first-strong-character only, so
   they break on lines that begin with an English label, timestamp, or number.
   Count strong characters instead. (Plaintext is an acceptable *no-JS fallback*
   for blocks that are each a single language — see `bidi.css`.)

4. **Flipping the whole document** — setting `direction: rtl` on `<html>`/`<body>`
   mirrors the entire app: sidebars, icons, layout. Don't. Direction belongs on
   the **content** blocks; the app chrome stays LTR. (If a product is genuinely
   RTL-first, that's a deliberate global decision — but it is not how you fix
   "the Arabic content looks wrong.")

5. **Inline code / emphasis** — do NOT set `dir` on `<code>`, `<strong>`, `<em>`,
   or links. Let the parent block's direction plus the Unicode bidi algorithm
   keep embedded English and code left-reading inside an Arabic paragraph.
   Setting `dir` on them fights the algorithm and mangles the wrapping.

## Frameworks & deeper patterns

Read **`references/web.md`** when wiring this into a specific stack — it has
ready-to-paste patterns for React (a `useBidi` ref/hook), rendered-markdown
integration, the streaming/MutationObserver pattern, a pure-CSS fallback, the
character ranges to recognize, and a full testing checklist.

## Beyond the web

The principle generalizes: pick direction per paragraph by dominant script,
align to the **start** edge, and mirror spacing **logically**. For documents/PDF,
set each paragraph's direction (most engines expose a paragraph-direction or
bidi setting). For terminals, rely on the terminal's own bidi but order
fields so the dominant script reads naturally. The `dirOf()` counter in
`bidi.js` is reusable anywhere you can read the text of a unit.

## Quick test before calling it done

- Arabic paragraph → right-aligned, sentence-ending punctuation at the left end. ✓
- Arabic bulleted/numbered list → markers on the **right**, indented from the right. ✓
- `Speaker 1: مرحبا`-style line → reads sensibly (label LTR, line not broken). ✓
- English paragraph in the same view → still left-aligned. ✓
- `inline code` inside Arabic → the code reads left-to-right. ✓
- The app's sidebar / header / icons did **not** mirror. ✓
