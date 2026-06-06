/**
 * bidi.js — framework-agnostic bidirectional (RTL/LTR) text direction.
 *
 * Sets `dir` per block by COUNTING strong characters, which is robust for
 * Arabic+English code-switching — unlike dir="auto" / unicode-bidi:plaintext,
 * which only read the FIRST strong character and mis-handle lines that start
 * with an English label, number, or timestamp.
 *
 * Usage (ES module):
 *   import { applyDirection, dirOf, observe } from './bidi.js';
 *   applyDirection(containerEl);   // one-shot after a render
 *   const mo = observe(containerEl); // live content (chat/stream); mo.disconnect() to stop
 *
 * Usage (plain <script>): call window.Bidi.applyDirection(el).
 *
 * Pair with bidi.css (text-align: start + logical list margins) on the same
 * container so the per-block dir also controls alignment and list-marker side.
 */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.Bidi = factory();
})(typeof window !== "undefined" ? window : this, function () {
  "use strict";

  // Strong RTL scripts: Hebrew, Arabic (+ supplement, extended-A, presentation
  // forms A/B), Syriac, Thaana, NKo. Strong LTR: Latin (+ extended), Greek,
  // Cyrillic. Digits and punctuation are intentionally NOT counted — they are
  // weak/neutral and should not decide a block's direction.
  var RTL = /[֐-׿؀-ۿ܀-ݏݐ-ݿ߀-߿ࡠ-ࣿיִ-﷿ﹰ-﻿]/g;
  var LTR = /[A-Za-zÀ-ʯͰ-ϿЀ-ӿ]/g;

  // Block + list elements that carry their own direction. Inline elements
  // (code, strong, em, a, span) are deliberately excluded: the Unicode bidi
  // algorithm handles embedded LTR inside an RTL block from the block's dir.
  var BLOCKS = "p,h1,h2,h3,h4,h5,h6,li,ul,ol,blockquote,td,th,dd,dt,figcaption,summary,div.line";

  function dirOf(text) {
    text = text || "";
    var r = (text.match(RTL) || []).length;
    var l = (text.match(LTR) || []).length;
    return r > l ? "rtl" : "ltr";
  }

  // Set dir on the container itself (covers single-paragraph content) and every
  // block/list descendant, based on each one's own text.
  function applyDirection(container) {
    if (!container || !container.setAttribute) return;
    try {
      container.setAttribute("dir", dirOf(container.textContent));
      var nodes = container.querySelectorAll(BLOCKS);
      for (var i = 0; i < nodes.length; i++) {
        nodes[i].setAttribute("dir", dirOf(nodes[i].textContent));
      }
    } catch (e) {
      /* non-DOM environment */
    }
  }

  // Re-apply whenever content changes (live chat, streaming tokens, async render).
  // Returns the MutationObserver — call .disconnect() to stop.
  function observe(container, opts) {
    opts = opts || {};
    var delay = opts.debounceMs == null ? 150 : opts.debounceMs;
    var timer = null;
    var mo = new MutationObserver(function () {
      if (timer) return;
      timer = setTimeout(function () {
        timer = null;
        applyDirection(container);
      }, delay);
    });
    mo.observe(container, { childList: true, subtree: true, characterData: true });
    applyDirection(container);
    return mo;
  }

  return { dirOf: dirOf, applyDirection: applyDirection, observe: observe, RTL: RTL, LTR: LTR, BLOCKS: BLOCKS };
});
