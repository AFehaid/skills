# Bidirectional text on the web — patterns by stack

Read this when wiring RTL/LTR handling into a specific framework. The core logic
(`dirOf`, `applyDirection`, `observe`) lives in `scripts/bidi.js`; the CSS lives
in `assets/bidi.css`. This file shows how to apply them in real codebases and the
exact details that matter.

## Table of contents
- [Character ranges](#character-ranges)
- [Vanilla JS / rendered markdown](#vanilla-js--rendered-markdown)
- [Streaming / live content](#streaming--live-content)
- [React](#react)
- [Vue / Svelte](#vue--svelte)
- [Reusing the host app's markdown renderer](#reusing-the-host-apps-markdown-renderer)
- [Pure-CSS-only approach](#pure-css-only-approach)
- [Pitfalls table](#pitfalls-table)
- [Testing checklist](#testing-checklist)

## Character ranges

Direction is decided by counting **strong** characters. Digits and punctuation
are weak/neutral and must not be counted (e.g. `123 مرحبا` is Arabic-dominant).

- Strong RTL: Hebrew `U+0590–05FF`, Arabic `U+0600–06FF`, Arabic Supplement
  `U+0750–077F`, Arabic Extended-A `U+08A0–08FF`, Syriac `U+0700–074F`, Thaana
  `U+0780–07BF`, NKo `U+07C0–07FF`, Arabic Presentation Forms `U+FB50–FDFF` /
  `U+FE70–FEFF`.
- Strong LTR: Latin `A–Z a–z` + Latin Extended, Greek, Cyrillic.

`bidi.js` already encodes these in its `RTL` / `LTR` regexes.

## Vanilla JS / rendered markdown

After you render text or markdown-to-HTML into a container, apply direction once:

```js
import { applyDirection } from "./bidi.js";

container.innerHTML = renderMarkdown(text); // your renderer
applyDirection(container);                  // sets dir per block + list
```

Add `class="bidi"` to the container and include `bidi.css` so alignment and list
indentation follow the per-block `dir`.

For a **plain transcript** (not markdown), render one element per line and let
each line get its own direction — important because lines often start with an
English speaker label then switch to Arabic:

```js
import { dirOf } from "./bidi.js";
container.innerHTML = "";
for (const line of text.split("\n")) {
  const row = document.createElement("div");
  row.className = "line";
  row.textContent = line || " ";
  row.setAttribute("dir", dirOf(line));
  container.appendChild(row);
}
```

## Streaming / live content

Chat messages and any content that updates after first paint need direction
re-applied as it changes. Use `observe` (debounced MutationObserver):

```js
import { observe } from "./bidi.js";
const mo = observe(document.querySelector("#messages")); // re-applies on changes
// later: mo.disconnect();
```

This is the right tool when you don't control the renderer (e.g. you're improving
an existing app's chat that sets no direction). Scope the observer to the message
list, debounce ~150ms, and it stays cheap even during token streaming.

## React

A tiny hook that direction-marks a container after each render:

```jsx
import { useRef, useEffect } from "react";
import { applyDirection } from "./bidi";

export function useBidi(deps) {
  const ref = useRef(null);
  useEffect(() => { if (ref.current) applyDirection(ref.current); }, deps);
  return ref;
}

function Note({ html }) {
  const ref = useBidi([html]);
  return <div className="bidi" ref={ref} dangerouslySetInnerHTML={{ __html: html }} />;
}
```

For per-line plain text, compute `dir` inline with `dirOf` and avoid a ref:

```jsx
import { dirOf } from "./bidi";
{text.split("\n").map((ln, i) => (
  <div key={i} className="line" dir={dirOf(ln)}>{ln || " "}</div>
))}
```

## Vue / Svelte

Same idea — bind `:dir` / `dir` with `dirOf(text)` on each rendered block, or call
`applyDirection(el)` in `mounted`/`onMount` (and re-run on content change). Import
`dirOf`/`applyDirection` from `bidi.js`.

## Reusing the host app's markdown renderer

If you're adding RTL to an existing app that already renders markdown (so notes
match its chat styling), reuse its renderer rather than shipping your own, then
direction-mark the output:

```js
container.className = "msg-body bidi";       // app's content class + ours
container.innerHTML = window.renderMd(text); // the app's renderer, if exposed
applyDirection(container);
// if the renderer needs post-passes (math/highlighting), call them too:
try { window.renderKatexBlocks?.(container); } catch {}
try { window.highlightCode?.(container); } catch {}
```

This keeps the notes visually identical to the app's own messages while fixing
direction.

## Pure-CSS-only approach

When you can't run JS on the content, use the `.bidi-auto` rules in `bidi.css`
(`unicode-bidi: plaintext`). Each block picks direction from its first strong
character. Good for messages that are each one language; it will mis-handle a
line like `Speaker 1: عربي` (forced LTR). Prefer the JS approach when you can.

## Pitfalls table

| Symptom | Cause | Fix |
|---|---|---|
| Arabic bullets/numbers on the left | `dir` only on `<li>`, not the list; physical `margin-left` | set `dir` on `<ul>`/`<ol>`; use `margin-inline-start` |
| Arabic paragraph left-aligned | `text-align: left` or no direction | `dir="rtl"` on the block + `text-align: start` |
| Line with English label forced LTR | `dir="auto"` / `unicode-bidi: plaintext` (first-char) | count strong chars (`dirOf`) |
| Whole UI mirrored (sidebar/icons) | `direction: rtl` on `<html>`/`<body>` | put direction on content blocks only |
| `inline code` reversed in Arabic | `dir` set on the inline `<code>` | don't set `dir` on inline elements |
| Direction wrong after streaming | applied once before content arrived | `observe()` / re-run on update |

## Testing checklist

Test with genuinely mixed content, not just pure Arabic:
- `"مرحبا بكم في الاجتماع"` → rtl, right-aligned.
- `"Speaker 1: مرحبا"` → ltr (the English label dominates a short Arabic word); line not broken.
- `"مرحبا بكم يا Speaker 1"` → rtl (Arabic dominates).
- `"123 مرحبا"` → rtl (digits are weak; Arabic wins).
- `"OK تمام"` → rtl (2 Latin < 4 Arabic). Counting is by letters, so a longer
  Arabic phrase with a short English token reads RTL — usually what you want.
- An Arabic `- bulleted` and `1. numbered` list → markers on the right.
- `` `const x = 5` `` embedded in an Arabic sentence → code stays LTR.
- An English paragraph beside an Arabic one → each aligned to its own side.
- Confirm the app's chrome (nav, header, buttons) did not mirror.
