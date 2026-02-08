import json
import re
import subprocess
import sys
from datetime import datetime
from html import escape as html_escape
from pathlib import Path


# =========================
# Project root resolution (Option B)
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

SOURCE_CHAR_DIR = ROOT / "source-docx" / "characters"
OUT_CHAR_DIR = ROOT / "content" / "characters"

MEDIA_DIR = ROOT / "media"
CSS_DIR = ROOT / "css"
BASE_CSS = CSS_DIR / "base.css"

MANIFEST_PATH = ROOT / "manifest.json"
LOG_PATH = ROOT / "characters_build_log.txt"

# Optional characters menu page (you can make this later)
CHARACTERS_MENU_PAGE = ROOT / "characters.html"

# Hook syntax:
#   @@IMG:key@@ -> center
#   @@IMG:key|left@@ / right / center / intro
IMG_HOOK_RE = re.compile(r"@@IMG:([a-zA-Z0-9_]+)(?:\|([^@]*?))?@@")
IMG_EXT_PRIORITY = [".webp", ".png", ".jpg", ".jpeg", ".gif"]


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
    Characters use flat keys (no F_01 prefix).
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


def ensure_category_css(category_slug: str):
    """
    Create css/<category>.css if missing, never overwrite.
    This file should @import base.css etc if you want.
    """
    if not category_slug:
        return
    CSS_DIR.mkdir(parents=True, exist_ok=True)
    target = CSS_DIR / f"{category_slug}.css"
    if not target.exists():
        target.write_text("/* auto-created; customize me */\n", encoding="utf-8")


# =========================
# Hook injection
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
<figure class="char-img char-img--{layout}">
  <a class="gallery-item" href="{src}">
    <img src="{src}" alt="{html_escape(key)}">
  </a>
</figure>
""".strip()

    out = IMG_HOOK_RE.sub(repl, html_fragment or "")
    return out, missing


# =========================
# HTML template (Hellhound-style skeleton)
# =========================
def character_page_html(
    *,
    title: str,
    category_slug: str,
    content_html: str,
    output_html_path: Path,
    missing_images: list[str],
) -> str:
    """
    Output uses the "hh-*" structural classes so you can reuse your existing character CSS theme.
    It links ONLY css/<category>.css, assuming it imports base.css etc inside.
    """
    css_path = CSS_DIR / f"{category_slug}.css"
    css_href = relpath(output_html_path.parent, css_path)

    # Menu link: prefer characters.html if it exists, else root index.html
    menu_target = CHARACTERS_MENU_PAGE if CHARACTERS_MENU_PAGE.exists() else (ROOT / "index.html")
    menu_href = relpath(output_html_path.parent, menu_target)

    missing_html = ""
    if missing_images:
        items = "".join(f"<li>{html_escape(x)}</li>" for x in missing_images)
        missing_html = f"""
<details class="hh-panel">
  <summary class="hh-section-title">Missing images</summary>
  <div class="hh-subblock">
    <ul class="hh-list">{items}</ul>
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

<body>
  <header class="hh-hero" id="top">
    <div class="hh-wrap hh-hero-inner">
      <h1 class="hh-title">{html_escape(title)}</h1>
      <div class="hh-meta">
        <span class="hh-meta-tag">Character</span>
        <span class="hh-dot" aria-hidden="true"></span>
        <span class="hh-meta-tag">{html_escape(category_slug)}</span>
      </div>
    </div>
  </header>

  <main class="hh-wrap hh-main" role="main">
    {missing_html}
    <section class="hh-panel">
      <div class="hh-subblock">
        {content_html}
      </div>
    </section>
  </main>

  <a class="fab fab--menu" href="{menu_href}" title="Back to characters menu">Menu</a>
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


# =========================
# Manifest handling (only rebuild arcs.characters)
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
        # If it’s corrupted, don’t nuke everything; recreate minimal.
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
    SOURCE_CHAR_DIR.mkdir(parents=True, exist_ok=True)
    OUT_CHAR_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    CSS_DIR.mkdir(parents=True, exist_ok=True)

    media_index = build_media_index()
    manifest = load_manifest()

    converted = 0
    failed = 0
    skipped = 0

    rebuilt_entries: list[dict] = []

    with LOG_PATH.open("w", encoding="utf-8") as log_fh:
        log(f"CHARACTERS build log — {now_iso()}", log_fh)
        log(f"ROOT: {ROOT}", log_fh)
        log(f"SOURCE_CHAR_DIR: {SOURCE_CHAR_DIR}", log_fh)
        log(f"OUT_CHAR_DIR: {OUT_CHAR_DIR}", log_fh)
        log("", log_fh)

        for docx in sorted(SOURCE_CHAR_DIR.rglob("*.docx")):
            rel = docx.relative_to(SOURCE_CHAR_DIR)
            parts = list(rel.parts)

            if not parts:
                skipped += 1
                continue

            # Category is first folder under /characters
            # If file is directly under characters/, category becomes "characters"
            category_folder = parts[0] if len(parts) > 1 else "characters"
            category_slug = slugify(category_folder) or "characters"
            ensure_category_css(category_slug)

            # Mirror folder structure under content/characters/
            rel_parent = Path(*parts[:-1])  # includes category folder
            out_dir = OUT_CHAR_DIR / rel_parent
            out_dir.mkdir(parents=True, exist_ok=True)

            name_slug = slugify(docx.stem) or "untitled"
            out_path = out_dir / f"{name_slug}.html"

            ok, fragment, err = run_pandoc_fragment(docx)
            if not ok:
                failed += 1
                log(f"[FAIL] {docx}: {err}", log_fh)
                continue

            injected, missing_imgs = inject_img_hooks(fragment, media_index, out_path)

            title = docx.stem.replace("_", " ").strip() or name_slug

            html = character_page_html(
                title=title,
                category_slug=category_slug,
                content_html=injected,
                output_html_path=out_path,
                missing_images=missing_imgs,
            )

            out_path.write_text(html, encoding="utf-8")
            converted += 1

            # Manifest entry
            entry = {
                "id": str(rel.with_suffix("")).replace("\\", "/"),  # stable id based on folder path
                "type": "C",
                "arc": "characters",
                "index": 0,
                "title": title,
                "title_text": title,
                "slug": name_slug,
                "category": category_slug,
                "source": str(docx.relative_to(ROOT)).replace("\\", "/"),
                "output": str(out_path.relative_to(ROOT)).replace("\\", "/"),
                "counts": {"images_missing": len(missing_imgs)},
            }
            rebuilt_entries.append(entry)

            log(f"[OK] {docx} -> {out_path}", log_fh)
            if missing_imgs:
                log(f"     missing images: {', '.join(missing_imgs)}", log_fh)

        rebuilt_entries.sort(key=lambda e: (str(e.get("category", "")), str(e.get("title", "")).lower()))

        # Replace only the characters arc
        manifest["generated_at"] = now_iso()
        manifest["root"] = str(ROOT.name)
        manifest["arcs"]["characters"] = rebuilt_entries

        MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        log("", log_fh)
        log("=== Summary ===", log_fh)
        log(f"Converted: {converted}", log_fh)
        log(f"Failed:    {failed}", log_fh)
        log(f"Skipped:   {skipped}", log_fh)
        log(f"Manifest:  {MANIFEST_PATH}", log_fh)

    print("[INFO] Done.")
    print(f"[INFO] ROOT: {ROOT}")
    print(f"[INFO] Wrote characters to: {OUT_CHAR_DIR}")
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
