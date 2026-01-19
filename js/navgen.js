/* STORYHUB navgen.js
   Runtime navigation builder for static pages.
   Reads /manifest.json (schema v2) and renders arc lists.

   Public API:
     buildNav(arc, mountId, options?)

   Example:
     buildNav("flame", "chapterList");
*/

(function () {
  "use strict";

  const DEFAULTS = {
    manifestPath: "manifest.json",
    showCounts: true,          // show image counts if present
    showMissingBadge: true,    // show missing-image badge if any
    emptyMessage: "No chapters yet.",
    loadingMessage: "Loading chapters…",
  };

  function normalizePath(p) {
    // Normalize to a comparable forward-slash path without leading "./"
    if (!p) return "";
    return String(p)
      .replace(/\\/g, "/")
      .replace(/^\.\//, "")
      .replace(/\/{2,}/g, "/");
  }

  function getCurrentPathnameNormalized() {
    // Compare against manifest output paths.
    // Works for GitHub Pages subpaths because pathname includes repo name, so we match by suffix.
    return normalizePath(window.location.pathname);
  }

  function safeText(s) {
    return s == null ? "" : String(s);
  }

  function clearEl(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function makeBadge(text, className) {
    return el("span", className || "badge", text);
  }

  async function fetchManifest(manifestPath) {
    const url = new URL(manifestPath, document.baseURI).toString();
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      throw new Error(`Failed to load manifest (${res.status} ${res.statusText})`);
    }
    const data = await res.json();
    return data;
  }

  function pickArcEntries(manifest, arc) {
    if (!manifest || typeof manifest !== "object") return null;
    if (manifest.schema !== 2) return null;

    const arcs = manifest.arcs;
    if (!arcs || typeof arcs !== "object") return null;

    const entries = arcs[arc];
    if (!Array.isArray(entries)) return null;

    return entries;
  }

  function renderList(mountEl, arc, entries, options) {
    const list = el("div", "chapter-list");

    const currentPath = getCurrentPathnameNormalized();

    for (const entry of entries) {
      const output = normalizePath(entry.output);
      const href = output; // output is already a web path like "content/flame/01_X.html"

      const row = el("a", "chapter-row");
      row.href = href;

      // Active highlight: match by suffix so it still works under /<repo>/... on GitHub Pages
      // Example current: "/STORYHUB/content/flame/01_THRESHOLD.html"
      // output: "content/flame/01_THRESHOLD.html"
      if (output && currentPath.endsWith(output)) {
        row.classList.add("active");
        row.setAttribute("aria-current", "page");
      }

      const left = el("div", "chapter-left");
      const title = el("div", "chapter-title", safeText(entry.title || entry.title_text || entry.id || href));
      left.appendChild(title);

      // Optional subtitle line (source or id). Keep it minimal.
      const metaBits = [];
      if (entry.id) metaBits.push(entry.id);
      if (typeof entry.index === "number" && entry.index > 0 && (entry.type === "F" || entry.type === "O")) {
        // index is already in title usually, but id+index can help debugging
        // no need to repeat if you hate it; it’s subtle.
      }

      if (metaBits.length) {
        const meta = el("div", "chapter-meta", metaBits.join(" · "));
        left.appendChild(meta);
      }

      const right = el("div", "chapter-right");

      // Counts / missing badges (optional)
      const counts = entry.counts || {};
      const missingCount = Number(counts.images_missing || 0);

      if (options.showCounts && entry.counts && typeof counts.images_used === "number") {
        right.appendChild(makeBadge(`${counts.images_used} img`, "badge badge-img"));
      }

      if (options.showMissingBadge && missingCount > 0) {
        right.appendChild(makeBadge(`${missingCount} missing`, "badge badge-missing"));
      }

      row.appendChild(left);
      row.appendChild(right);

      list.appendChild(row);
    }

    mountEl.appendChild(list);
  }

  async function buildNav(arc, mountId, opts) {
    const options = Object.assign({}, DEFAULTS, opts || {});
    const mountEl = typeof mountId === "string" ? document.getElementById(mountId) : mountId;

    if (!mountEl) {
      console.error(`[navgen] mount element not found: ${mountId}`);
      return;
    }

    // Loading state
    clearEl(mountEl);
    mountEl.appendChild(el("div", "nav-loading", options.loadingMessage));

    try {
      const manifest = await fetchManifest(options.manifestPath);
      const entries = pickArcEntries(manifest, arc);

      clearEl(mountEl);

      if (!entries) {
        mountEl.appendChild(el("div", "nav-error", "Manifest format mismatch (expected schema 2)."));
        return;
      }

      if (entries.length === 0) {
        mountEl.appendChild(el("div", "nav-empty", options.emptyMessage));
        return;
      }

      // Builder already sorts deterministically; we still sort defensively for sanity.
     const sorted = entries.slice().sort((a, b) => {
  const ai = typeof a.index === "number" ? a.index : null;
  const bi = typeof b.index === "number" ? b.index : null;

  // If both have numeric index, sort by that (F/O chapters)
  if (ai !== null && bi !== null) return ai - bi;

  // Otherwise sort by title (Characters/Lore)
  const at = String(a.title || a.title_text || a.id || "").toLowerCase();
  const bt = String(b.title || b.title_text || b.id || "").toLowerCase();
  return at.localeCompare(bt);
});


      renderList(mountEl, arc, sorted, options);
    } catch (err) {
      clearEl(mountEl);
      const msg = err && err.message ? err.message : String(err);
      mountEl.appendChild(el("div", "nav-error", `Couldn’t load chapters. ${msg}`));
      console.error("[navgen] Error:", err);
    }
  }

  // Expose API
  window.buildNav = buildNav;
})();
