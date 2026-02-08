/* STORYHUB navgen.js
   Runtime navigation builder for static pages.
   Reads manifest.json (schema v2) and renders arc lists.

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

  // -------------------------
  // IMPORTANT: Site base resolver (GitHub Pages-safe)
  // -------------------------
  function getSiteBase() {
    // Goal: return a base URL that points to the repo root on GitHub Pages,
    // regardless of how deep we are in /content/... pages.
    //
    // Example:
    //   https://user.github.io/repo/content/lore/a/b.html
    // -> base: https://user.github.io/repo/
    //
    // If /content/ isn't in the path (e.g., you are on /repo/lore.html),
    // base becomes the current directory (which is still under /repo/).
    const p = window.location.pathname; // includes /repo/... on GH Pages
    const idx = p.indexOf("/content/");

    // If inside /content/... slice everything before it, keep trailing slash.
    if (idx >= 0) {
      const basePath = p.slice(0, idx + 1); // include trailing slash
      return window.location.origin + basePath;
    }

    // Otherwise, base is the directory of current page
    // e.g. /repo/lore.html -> /repo/
    const dir = p.endsWith("/") ? p : p.replace(/[^/]+$/, "");
    return window.location.origin + dir;
  }

  function toAbsoluteFromSiteBase(relativePath) {
    const base = getSiteBase();
    return new URL(relativePath, base).toString();
  }

  async function fetchManifest(manifestPath) {
    // FIX: don't resolve against document.baseURI (which changes on nested pages)
    // Resolve against repo/site base instead.
    const url = toAbsoluteFromSiteBase(manifestPath);
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      throw new Error(`Failed to load manifest (${res.status} ${res.statusText})`);
    }
    return await res.json();
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

  function humanizeSegment(seg) {
    // folder/file stem -> nicer label
    const s = safeText(seg)
      .replace(/\.html$/i, "")
      .replace(/[_-]+/g, " ")
      .trim();
    if (!s) return "";
    // light title case (keeps ALLCAPS readable enough)
    return s
      .split(" ")
      .filter(Boolean)
      .map(w => w.length <= 2 ? w.toUpperCase() : (w[0].toUpperCase() + w.slice(1).toLowerCase()))
      .join(" ");
  }

  function stripArcFromOutput(output, arc) {
    // "content/lore/ecology/fauna/X.html" -> "ecology/fauna/X.html"
    const out = normalizePath(output);
    const prefix = `content/${arc}/`;
    if (out.startsWith(prefix)) return out.slice(prefix.length);
    return out; // fallback
  }

  function leafTitleFromEntry(entry) {
    // Prefer entry.title but only show the final segment if it's a path-like title ("L a / b / c")
    const raw = safeText(entry.title || entry.title_text || entry.id || "");
    const cleaned = raw.replace(/^[CL]\s+/i, "").trim();

    // If it looks like our builder title format: "something / something / leaf"
    if (cleaned.includes(" / ")) {
      const parts = cleaned.split(" / ").map(p => p.trim()).filter(Boolean);
      if (parts.length) return parts[parts.length - 1];
    }

    // Fallback: use filename stem from output
    const out = normalizePath(entry.output);
    const name = out.split("/").pop() || out;
    return name.replace(/\.html$/i, "");
  }

  function makeRow(entry, options, currentPath) {
    const output = normalizePath(entry.output);

    // FIX: build absolute link from repo/site base (GH Pages-safe)
    const hrefAbs = toAbsoluteFromSiteBase(output);

    const row = el("a", "chapter-row");
    row.href = hrefAbs;

    // Active highlight: match by suffix so it still works under /<repo>/... on GitHub Pages
    // We compare normalized pathname (no origin) to output (also no origin).
    if (output && currentPath.endsWith(output)) {
      row.classList.add("active");
      row.setAttribute("aria-current", "page");
    }

    const left = el("div", "chapter-left");
    const titleText = humanizeSegment(leafTitleFromEntry(entry));
    const title = el(
      "div",
      "chapter-title",
      safeText(titleText || entry.title || entry.title_text || entry.id || output)
    );
    left.appendChild(title);

    const metaBits = [];
    if (entry.id) metaBits.push(entry.id);

    if (metaBits.length) {
      const meta = el("div", "chapter-meta", metaBits.join(" · "));
      left.appendChild(meta);
    }

    const right = el("div", "chapter-right");

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

    return row;
  }

  function renderList(mountEl, arc, entries, options) {
    const list = el("div", "chapter-list");
    const currentPath = getCurrentPathnameNormalized();

    for (const entry of entries) {
      list.appendChild(makeRow(entry, options, currentPath));
    }

    mountEl.appendChild(list);
  }

  // -------------------------
  // Tree nav for lore/characters
  // -------------------------

  function buildTree(entries, arc) {
    // Node shape:
    // { folders: Map<string, node>, pages: entry[] }
    const root = { folders: new Map(), pages: [] };

    for (const entry of entries) {
      const rel = stripArcFromOutput(entry.output, arc);
      const parts = normalizePath(rel).split("/").filter(Boolean);

      // If output is weird, just dump it at root
      if (parts.length === 0) {
        root.pages.push(entry);
        continue;
      }

      parts.pop(); // last is filename
      const folderParts = parts;

      let node = root;
      for (const folder of folderParts) {
        if (!node.folders.has(folder)) {
          node.folders.set(folder, { folders: new Map(), pages: [] });
        }
        node = node.folders.get(folder);
      }

      // Keep the entry; filename isn't needed because entry.output is already the link
      node.pages.push(entry);
    }

    return root;
  }

  function sortNode(node) {
    // Sort pages by title-ish
    node.pages.sort((a, b) => {
      const at = humanizeSegment(leafTitleFromEntry(a)).toLowerCase();
      const bt = humanizeSegment(leafTitleFromEntry(b)).toLowerCase();
      return at.localeCompare(bt);
    });

    // Sort folders by key
    const folderKeys = Array.from(node.folders.keys()).sort((a, b) => {
      return humanizeSegment(a).toLowerCase().localeCompare(humanizeSegment(b).toLowerCase());
    });

    // Rebuild map in sorted order
    const newMap = new Map();
    for (const k of folderKeys) {
      const child = node.folders.get(k);
      sortNode(child);
      newMap.set(k, child);
    }
    node.folders = newMap;
  }

  function renderTree(mountEl, arc, tree, options) {
    const wrap = el("div", "nav-tree");
    const currentPath = getCurrentPathnameNormalized();

    function renderNode(node, label, depth) {
      // Use <details> for collapsible groups; open top-level by default
      const details = document.createElement("details");
      details.className = "nav-group";
      if (depth <= 0) details.open = true;

      const summary = document.createElement("summary");
      summary.className = "nav-group-title";
      summary.textContent = humanizeSegment(label);
      details.appendChild(summary);

      const body = el("div", "nav-group-body");

      // Pages first
      if (node.pages.length) {
        const list = el("div", "chapter-list");
        for (const entry of node.pages) {
          list.appendChild(makeRow(entry, options, currentPath));
        }
        body.appendChild(list);
      }

      // Then folders
      for (const [folderName, child] of node.folders.entries()) {
        body.appendChild(renderNode(child, folderName, depth + 1));
      }

      details.appendChild(body);
      return details;
    }

    // Root pages (rare, but supported)
    if (tree.pages.length) {
      const rootList = el("div", "chapter-list");
      for (const entry of tree.pages) {
        rootList.appendChild(makeRow(entry, options, currentPath));
      }
      wrap.appendChild(rootList);
    }

    // Top folders
    for (const [folderName, child] of tree.folders.entries()) {
      wrap.appendChild(renderNode(child, folderName, 0));
    }

    mountEl.appendChild(wrap);
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

      // Lore/Characters: category tree from output paths
      if (arc === "lore" || arc === "characters") {
        const tree = buildTree(sorted, arc);
        sortNode(tree);
        renderTree(mountEl, arc, tree, options);
      } else {
        // Flame/Order: classic flat list
        renderList(mountEl, arc, sorted, options);
      }
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
