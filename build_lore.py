import json
import re
import subprocess
import sys
from datetime import datetime
from html import escape as html_escape
from pathlib import Path


# =========================
# Project root resolution
# =========================
def find_project_root() -> Path:
    """
    Walk upward until we find a folder containing BOTH:
      - source-docx/
      - content/
    Avoids PyInstaller onefile temp/AppData path issues.
    """
    candidates = []
    try:
        candidates.append(Path.cwd().resolve())
    except Exception:
        pass

    if getattr(sys, "frozen", False):
        try:
            candidates.append(Path(sys.executable).resolve().parent)
        except Exception:
            pass

    try:
        candidates.append(Path(__file__).resolve().parent)
    except Exception:
        pass

    def is_root(p: Path) -> bool:
        return p.is_dir() and (p / "source-docx").is_dir() and (p / "content").is_dir()

    seen = set()
    for start in candidates:
        cur = start
        for _ in range(120):
            if cur in seen:
                break
            seen.add(cur)

            if is_root(cur):
                return cur

            if cur.parent == cur:
                break
            cur = cur.parent

    checked = "\n  - " + "\n  - ".join(str(c) for c in candidates)
    raise RuntimeError(
        "Could not locate StoryHub project root. Expected 'source-docx/' and 'content/' folders.\n"
        f"Checked starting points:{checked}"
    )


ROOT = find_project_root()

# =========================
# Paths
# =========================
PANDOC_EXE = "pandoc"

SOURCE_LORE_DIR = ROOT / "source-docx" / "lore"
OUT_LORE_DIR = ROOT / "content" / "lore"

MEDIA_DIR = ROOT / "media"
CSS_DIR = ROOT / "css"

BASE_CSS = CSS_DIR / "base.css"
LORE_CSS = CSS_DIR / "lore.css"
TERMS_CSS = CSS_DIR / "terms.css"

MANIFEST_PATH = ROOT / "manifest.json"
LOG_PATH = ROOT / "lore_build_log.txt"

# Optional: a lore index page you might generate later
LORE_MENU_PAGE = ROOT / "lore.html"  # if exists, we'll link back to it; else root index.html

IMG_EXT_PRIORITY = [".webp", ".png", ".jpg", ".jpeg", ".gif"]

# Image hook syntax:
#   @@IMG:key@@ -> center
#   @@IMG:key|left@@ / right / center / intro
IMG_HOOK_RE = re.compile(r"@@IMG:([a-zA-Z0-9_]+)(?:\|([^@]*?))?@@")

# Terms delimiter in DOCX:
# Each term begins with a paragraph "@Term Name"
# Pandoc commonly emits: <p>@Term Name</p>
TERMS_MARKER_P_RE = re.compile(
    r"(<p[^>]*>\s*@(?P<term>[^<]+?)\s*</p>)",
    flags=re.IGNORECASE | re.DOTALL
)

# Ignore drafts:
UNDERSCORE_PATH_SEG_RE = re.compile(r"(^_|/_|\\_)")  # any segment starting with "_"


# =========================
# Utils
# =========================
def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(line: str, fh):
    fh.write(line.rstrip() + "\n")
    fh.flush()


def relpath(from_dir: Path, to_path: Path) -> str:
    import os
    return Path(os.path.relpath(to_path, start=from_dir)).as_posix()


def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("_", " ")
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


def should_ignore_path(p: Path, root_dir: Path) -> bool:
    """
    Ignore any file/folder whose relative path contains a segment starting with "_",
    or the filename starts with "_".
    """
    try:
        rel = p.relative_to(root_dir)
    except Exception:
        rel = p

    # any segment begins with "_"
    if any(part.startswith("_") for part in rel.parts):
        return True
    if p.name.startswith("_"):
        return True
    return False


def run_pandoc_fragment(input_docx: Path) -> tuple[bool, str, str]:
    """
    Convert DOCX -> HTML fragment string.
    """
    args = [PANDOC_EXE, str(input_docx), "-f", "docx", "-t", "html5", "--wrap=none"]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0:
            return False, "", (proc.stderr or proc.stdout or "").strip()
        return True, proc.stdout or "", (proc.stderr or "").strip()
    except FileNotFoundError:
        return False, "", "Pandoc not found. Install pandoc and make sure it's on PATH."
    except Exception as e:
        return False, "", f"Exception running pandoc: {e!r}"


def build_media_index() -> dict[str, Path]:
    """
    Case-insensitive stem -> best match path in /media by extension priority.
    Lore uses flat keys.
    """
    idx: dict[str, Path] = {}
    best_rank: dict[str, int] = {}

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    for p in MEDIA_DIR.iterdir():
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext not in IMG_EXT_PRIORITY:
            continue

        key = p.stem.lower()
        rank = IMG_EXT_PRIORITY.index(ext)

        if key not in idx or rank < best_rank[key]:
            idx[key] = p
            best_rank[key] = rank

    return idx


def ensure_css_file(path: Path, stub: str):
    CSS_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(stub, encoding="utf-8")


# =========================
# Image hook injection
# =========================
def inject_img_hooks(html_fragment: str, media_index: dict[str, Path], output_html_path: Path) -> tuple[str, list[str]]:
    """
    Replace @@IMG:key@@ or @@IMG:key|layout@@ with inline figures.
    layout: intro / left / right / center
    Returns: (new_html, missing_keys)
    """
    missing: list[str] = []

    def resolve_key(key: str) -> Path | None:
        p = media_index.get(key.lower())
        if p:
            return p
        # fallback try direct key+ext
        for ext in IMG_EXT_PRIORITY:
            cand = MEDIA_DIR / f"{key}{ext}"
            if cand.exists():
                return cand
        return None

    def repl(m: re.Match) -> str:
        key = (m.group(1) or "").strip()
        layout = (m.group(2) or "").strip().lower()

        if not layout:
            layout = "center"
        if layout not in {"left", "right", "center", "intro"}:
            layout = "center"

        img_path = resolve_key(key)
        if not img_path:
            missing.append(key)
            return f"<span class='img-missing'>[missing image: {html_escape(key)}]</span>"

        src = relpath(output_html_path.parent, img_path)

        return f"""
<figure class="lore-img lore-img--{layout}">
  <a class="gallery-item" href="{src}">
    <img src="{src}" alt="{html_escape(key)}">
  </a>
</figure>
""".strip()

    out = IMG_HOOK_RE.sub(repl, html_fragment or "")
    return out, missing


# =========================
# Templates
# =========================
def lore_page_html(
    *,
    title: str,
    category_slug: str,
    content_html: str,
    output_html_path: Path,
    missing_images: list[str],
) -> str:
    css_href = relpath(output_html_path.parent, LORE_CSS)

    menu_target = LORE_MENU_PAGE if LORE_MENU_PAGE.exists() else (ROOT / "index.html")
    menu_href = relpath(output_html_path.parent, menu_target)

    missing_html = ""
    if missing_images:
        items = "".join(f"<li>{html_escape(x)}</li>" for x in missing_images)
        missing_html = f"""
<details class="lore-panel lore-missing">
  <summary class="lore-section-title">Missing images</summary>
  <div class="lore-subblock">
    <ul class="lore-list">{items}</ul>
  </div>
</details>
""".strip()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html_escape(title)}</title>
  <link rel="stylesheet" href="{css_href}" />
</head>

<body class="lore-page" id="top">
  <header class="lore-hero">
    <div class="lore-wrap lore-hero-inner">
      <div class="lore-kicker">Lore</div>
      <h1 class="lore-title">{html_escape(title)}</h1>
      <div class="lore-meta">
        <span class="lore-tag">{html_escape(category_slug)}</span>
      </div>
    </div>
  </header>

  <main class="lore-wrap lore-main" role="main">
    {missing_html}
    <section class="lore-panel">
      <div class="lore-subblock">
        {content_html}
      </div>
    </section>
  </main>

  <a class="fab fab--menu" href="{menu_href}" title="Back to lore menu">Menu</a>
  <button class="fab fab--top is-hidden" id="backToTop" type="button" title="Back to top">Top</button>

  <script>
    (function () {{
      const btn = document.getElementById("backToTop");
      if (!btn) return;

      function onScroll() {{
        if (window.scrollY > 300) btn.classList.remove("is-hidden");
        else btn.classList.add("is-hidden");
      }}

      btn.addEventListener("click", () => {{
        window.scrollTo({{ top: 0, behavior: "smooth" }});
      }});

      window.addEventListener("scroll", onScroll, {{ passive: true }});
      onScroll();
    }})();
  </script>
</body>
</html>
"""


def terms_page_html(
    *,
    title: str,
    intro_html: str,
    terms_sorted: list[dict],
    output_html_path: Path,
) -> str:
    """
    terms_sorted items:
      {
        "term": "Aberration",
        "slug": "aberration",
        "body_html": "<p>...</p>..."
      }
    """
    css_href = relpath(output_html_path.parent, TERMS_CSS)
    menu_target = LORE_MENU_PAGE if LORE_MENU_PAGE.exists() else (ROOT / "index.html")
    menu_href = relpath(output_html_path.parent, menu_target)

    # A–Z jump bar (only letters that exist)
    letters = []
    seen = set()
    for t in terms_sorted:
        first = (t.get("term") or "").strip()[:1].upper()
        if not first:
            continue
        if not first.isalpha():
            first = "#"
        if first not in seen:
            seen.add(first)
            letters.append(first)

    jump_links = []
    for L in letters:
        jump_links.append(f'<a class="terms-jump-link" href="#jump-{html_escape(L)}">{html_escape(L)}</a>')

    # Render terms with letter anchors
    out_terms = []
    current_letter = None
    for t in terms_sorted:
        term = (t.get("term") or "").strip()
        slug = t.get("slug") or slugify(term) or "term"
        body = t.get("body_html") or ""

        first = term[:1].upper() if term else "#"
        if not first.isalpha():
            first = "#"

        if first != current_letter:
            current_letter = first
            out_terms.append(f'<div class="terms-jump-anchor" id="jump-{html_escape(current_letter)}"></div>')
            out_terms.append(f'<h2 class="terms-letter">{html_escape(current_letter)}</h2>')

        out_terms.append(f"""
<details class="term" data-term="{html_escape(slug)}" data-label="{html_escape(term.lower())}">
  <summary class="term-summary">
    <span class="term-name" id="{html_escape(slug)}">{html_escape(term)}</span>
    <a class="term-link" href="#{html_escape(slug)}" title="Link to this term">#</a>
  </summary>
  <div class="term-body">
    {body}
  </div>
</details>
""".strip())

    terms_html = "\n".join(out_terms) if out_terms else "<p class='terms-empty'>[No terms found]</p>"

    # Client-side search: term label + full text
    js = """
<script>
(function () {
  const input = document.getElementById("termSearch");
  const terms = Array.from(document.querySelectorAll(".term"));
  const count = document.getElementById("termCount");
  const jump = document.getElementById("termsJump");

  function norm(s) {
    return (s || "").toLowerCase().trim();
  }

  function applyFilter() {
    const q = norm(input.value);
    let visible = 0;

    for (const el of terms) {
      const label = norm(el.getAttribute("data-label"));
      const full = norm(el.textContent);
      const match = !q || label.includes(q) || full.includes(q);
      el.hidden = !match;
      if (match) visible++;
    }

    if (count) count.textContent = `${visible} / ${terms.length}`;

    // Hide jump bar while filtering, because it becomes misleading.
    if (jump) {
      if (q) jump.setAttribute("hidden", "");
      else jump.removeAttribute("hidden");
    }
  }

  if (input) input.addEventListener("input", applyFilter, { passive: true });
  applyFilter();
})();
</script>
""".strip()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html_escape(title)}</title>
  <link rel="stylesheet" href="{css_href}" />
</head>

<body class="terms-page" id="top">
  <header class="terms-hero">
    <div class="terms-wrap terms-hero-inner">
      <div class="terms-kicker">Lore</div>
      <h1 class="terms-title">{html_escape(title)}</h1>
      <div class="terms-tools">
        <input id="termSearch" class="terms-search" type="search" placeholder="Search terms…" autocomplete="off" />
        <div class="terms-count" id="termCount"></div>
      </div>
      <nav class="terms-jump" id="termsJump">
        {''.join(jump_links)}
      </nav>
    </div>
  </header>

  <main class="terms-wrap terms-main" role="main">
    <section class="terms-panel">
      <div class="terms-subblock">
        {intro_html}
      </div>
    </section>

    <section class="terms-panel">
      <div class="terms-subblock">
        {terms_html}
      </div>
    </section>
  </main>

  <a class="fab fab--menu" href="{menu_href}" title="Back to lore menu">Menu</a>
  <button class="fab fab--top is-hidden" id="backToTop" type="button" title="Back to top">Top</button>

  <script>
    (function () {{
      const btn = document.getElementById("backToTop");
      if (!btn) return;

      function onScroll() {{
        if (window.scrollY > 300) btn.classList.remove("is-hidden");
        else btn.classList.add("is-hidden");
      }}

      btn.addEventListener("click", () => {{
        window.scrollTo({{ top: 0, behavior: "smooth" }});
      }});

      window.addEventListener("scroll", onScroll, {{ passive: true }});
      onScroll();
    }})();
  </script>

  {js}
</body>
</html>
"""


# =========================
# Terms parsing
# =========================
def split_terms_from_fragment(fragment_html: str) -> tuple[str, list[dict]]:
    """
    Given a Pandoc fragment, split into:
      - intro_html: everything before the first @Term marker
      - terms: list of {"term", "slug", "body_html"}
    Marker expected as paragraph: <p>@Term</p>
    """
    html = fragment_html or ""

    # Find all marker matches
    matches = list(TERMS_MARKER_P_RE.finditer(html))
    if not matches:
        # no terms markers; treat entire doc as intro
        return html, []

    intro_end = matches[0].start()
    intro_html = html[:intro_end].strip()

    terms = []
    for i, m in enumerate(matches):
        term_raw = (m.group("term") or "").strip()
        term = html_escape(term_raw)  # for safety in display
        slug = slugify(term_raw) or "term"

        body_start = m.end()
        body_end = matches[i + 1].start() if (i + 1) < len(matches) else len(html)
        body_html = (html[body_start:body_end] or "").strip()

        # Clean up: sometimes there are leading empty paragraphs, keep it simple
        body_html = re.sub(r"^\s*(<p>\s*</p>\s*)+", "", body_html, flags=re.IGNORECASE)

        terms.append({
            "term": term_raw.strip(),
            "slug": slug,
            "body_html": body_html
        })

    # Sort alphabetically ignoring case
    terms.sort(key=lambda d: (d.get("term") or "").casefold())
    return intro_html, terms


# =========================
# Manifest handling
# =========================
def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {
            "schema": 2,
            "generated_at": now_iso(),
            "root": str(ROOT.name),
            "arcs": {"flame": [], "order": [], "characters": [], "lore": []},
        }
    try:
        m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if not isinstance(m, dict) or m.get("schema") != 2:
            raise ValueError("manifest schema mismatch")
        m.setdefault("arcs", {})
        for arc in ("flame", "order", "characters", "lore"):
            m["arcs"].setdefault(arc, [])
        return m
    except Exception:
        return {
            "schema": 2,
            "generated_at": now_iso(),
            "root": str(ROOT.name),
            "arcs": {"flame": [], "order": [], "characters": [], "lore": []},
        }


# =========================
# Main build
# =========================
def main():
    SOURCE_LORE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_LORE_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    CSS_DIR.mkdir(parents=True, exist_ok=True)

    ensure_css_file(
        LORE_CSS,
        "/* lore.css (auto-created)\n"
        "   Tip: @import url('./base.css'); then style .lore-page etc.\n"
        "*/\n"
    )
    ensure_css_file(
        TERMS_CSS,
        "/* terms.css (auto-created)\n"
        "   Tip: @import url('./base.css'); then style .terms-page and .term blocks.\n"
        "*/\n"
    )

    media_index = build_media_index()
    manifest = load_manifest()

    converted = 0
    failed = 0
    skipped = 0

    rebuilt_entries: list[dict] = []

    # Detect the single Terms mega-doc:
    # Accept either:
    #   source-docx/lore/terms.docx
    #   source-docx/lore/terms/terms.docx
    terms_candidates = [
        SOURCE_LORE_DIR / "terms.docx",
        SOURCE_LORE_DIR / "terms" / "terms.docx",
    ]
    terms_docx: Path | None = None
    for cand in terms_candidates:
        if cand.exists():
            terms_docx = cand
            break

    with LOG_PATH.open("w", encoding="utf-8") as log_fh:
        log(f"LORE build log — {now_iso()}", log_fh)
        log(f"ROOT: {ROOT}", log_fh)
        log(f"SOURCE_LORE_DIR: {SOURCE_LORE_DIR}", log_fh)
        log(f"OUT_LORE_DIR: {OUT_LORE_DIR}", log_fh)
        if terms_docx:
            log(f"TERMS_DOCX: {terms_docx}", log_fh)
        log("", log_fh)

        # 1) Build standard lore pages (everything except the terms mega-doc)
        for docx in sorted(SOURCE_LORE_DIR.rglob("*.docx")):
            if should_ignore_path(docx, SOURCE_LORE_DIR):
                skipped += 1
                continue

            if terms_docx and docx.resolve() == terms_docx.resolve():
                # We'll handle it in the special pass
                continue

            rel = docx.relative_to(SOURCE_LORE_DIR)
            parts = list(rel.parts)
            if not parts:
                skipped += 1
                continue

            # Category is first folder under /lore
            # If file is directly under lore/, category becomes "lore"
            category_folder = parts[0] if len(parts) > 1 else "lore"
            category_slug = slugify(category_folder) or "lore"

            # Mirror folder structure under content/lore/
            rel_parent = Path(*parts[:-1])  # includes category folder if present
            out_dir = OUT_LORE_DIR / rel_parent
            out_dir.mkdir(parents=True, exist_ok=True)

            title = docx.stem.replace("_", " ").strip() or "Untitled"
            name_slug = slugify(docx.stem) or "untitled"
            out_path = out_dir / f"{name_slug}.html"

            ok, fragment, err = run_pandoc_fragment(docx)
            if not ok:
                failed += 1
                log(f"[FAIL] {docx}: {err}", log_fh)
                continue

            injected, missing_imgs = inject_img_hooks(fragment, media_index, out_path)

            html = lore_page_html(
                title=title,
                category_slug=category_slug,
                content_html=injected,
                output_html_path=out_path,
                missing_images=missing_imgs,
            )

            out_path.write_text(html, encoding="utf-8")
            converted += 1

            entry = {
                "id": str(rel.with_suffix("")).replace("\\", "/"),
                "type": "L",
                "arc": "lore",
                "kind": "page",
                "category": category_slug,
                "title": title,
                "title_text": title,
                "slug": name_slug,
                "source": str(docx.relative_to(ROOT)).replace("\\", "/"),
                "output": str(out_path.relative_to(ROOT)).replace("\\", "/"),
                "counts": {"images_missing": len(missing_imgs)},
            }
            rebuilt_entries.append(entry)

            log(f"[OK] {docx} -> {out_path}", log_fh)
            if missing_imgs:
                log(f"     missing images: {', '.join(missing_imgs)}", log_fh)
            if err:
                log(f"     pandoc stderr: {err}", log_fh)

        # 2) Build Terms mega-doc (special page)
        if terms_docx and not should_ignore_path(terms_docx, SOURCE_LORE_DIR):
            # output always to content/lore/terms.html for stability
            out_path = OUT_LORE_DIR / "terms.html"
            out_path.parent.mkdir(parents=True, exist_ok=True)

            ok, fragment, err = run_pandoc_fragment(terms_docx)
            if not ok:
                failed += 1
                log(f"[FAIL] TERMS {terms_docx}: {err}", log_fh)
            else:
                intro_html, terms = split_terms_from_fragment(fragment)

                # Inject image hooks into intro + each term body (rare, but allowed)
                intro_injected, intro_missing = inject_img_hooks(intro_html, media_index, out_path)

                missing_total = list(intro_missing)
                for t in terms:
                    body = t.get("body_html") or ""
                    body_injected, miss = inject_img_hooks(body, media_index, out_path)
                    t["body_html"] = body_injected
                    missing_total.extend(miss)

                title = "Terms & Labels"
                html = terms_page_html(
                    title=title,
                    intro_html=intro_injected,
                    terms_sorted=terms,
                    output_html_path=out_path,
                )
                out_path.write_text(html, encoding="utf-8")
                converted += 1

                # Add manifest entry
                rel_id = "terms"
                entry = {
                    "id": rel_id,
                    "type": "L",
                    "arc": "lore",
                    "kind": "terms",
                    "category": "terms",
                    "title": title,
                    "title_text": title,
                    "slug": "terms",
                    "source": str(terms_docx.relative_to(ROOT)).replace("\\", "/"),
                    "output": str(out_path.relative_to(ROOT)).replace("\\", "/"),
                    "counts": {
                        "terms": len(terms),
                        "images_missing": len([x for x in missing_total if x]),
                    },
                }
                rebuilt_entries.append(entry)

                log(f"[OK] TERMS {terms_docx} -> {out_path}", log_fh)
                log(f"     terms: {len(terms)}", log_fh)
                if missing_total:
                    uniq = sorted(set(x for x in missing_total if x))
                    if uniq:
                        log(f"     missing images: {', '.join(uniq)}", log_fh)
                if err:
                    log(f"     pandoc stderr: {err}", log_fh)
        else:
            log("[INFO] No terms mega-doc found. Looked for lore/terms.docx or lore/terms/terms.docx", log_fh)

        # Sort manifest entries: category then title
        rebuilt_entries.sort(key=lambda e: (str(e.get("category", "")), str(e.get("title", "")).casefold()))

        # Replace only lore arc
        manifest["generated_at"] = now_iso()
        manifest["root"] = str(ROOT.name)
        manifest["arcs"]["lore"] = rebuilt_entries

        MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        log("", log_fh)
        log("=== Summary ===", log_fh)
        log(f"Converted: {converted}", log_fh)
        log(f"Failed:    {failed}", log_fh)
        log(f"Skipped:   {skipped}", log_fh)
        log(f"Manifest:  {MANIFEST_PATH}", log_fh)

    print("[INFO] Done.")
    print(f"[INFO] ROOT: {ROOT}")
    print(f"[INFO] Wrote lore to: {OUT_LORE_DIR}")
    print(f"[INFO] Updated manifest: {MANIFEST_PATH}")
    print(f"[INFO] Log: {LOG_PATH}")


if __name__ == "__main__":
    try:
        main()
        input("\nPress Enter to close...")
    except Exception as e:
        print("\n[FATAL]", repr(e))
        input("\nPress Enter to close...")
        raise
