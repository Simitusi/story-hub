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
    Find the real project root by walking upward until we see BOTH:
      - source-docx/
      - content/
    This avoids PyInstaller --onefile temp folders and AppData nonsense.
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
        for _ in range(80):
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

PANDOC_EXE = "pandoc"  # assumes pandoc is on PATH

SOURCE_DIR = ROOT / "source-docx"
CONTENT_DIR = ROOT / "content"
MEDIA_DIR = ROOT / "media"

FLAME_DIR = CONTENT_DIR / "flame"
ORDER_DIR = CONTENT_DIR / "order"

BASE_CSS = ROOT / "css" / "base.css"
FLAME_CSS = ROOT / "css" / "flame.css"
ORDER_CSS = ROOT / "css" / "order.css"

JS_DIR = ROOT / "js"
LIGHTBOX_JS = JS_DIR / "lightbox.js"

MANIFEST_PATH = ROOT / "manifest.json"
MANIFEST_NEW_PATH = ROOT / "manifest.new.json"
LOG_PATH = ROOT / "log.txt"

# Global media gallery page (generated each build)
GALLERY_PAGE_PATH = ROOT / "gallery.html"

# Covers
FLAME_COVER_NAME = "hellfirefiends.webp"
ORDER_COVER_NAME = "ark.webp"

# Image hook marker:
#   @@IMG:key@@
#   @@IMG:key|caption@@
IMG_HOOK_RE = re.compile(r"@@IMG:([a-zA-Z0-9_]+)(?:\|([^@]*?))?@@")

# Preferred extensions (first match wins)
IMG_EXT_PRIORITY = [".webp", ".png", ".jpg", ".jpeg", ".gif"]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(line: str, fh):
    fh.write(line.rstrip() + "\n")
    fh.flush()


def safe_int(s: str, default: int = 0) -> int:
    try:
        return int(s)
    except Exception:
        return default


def slugify(s: str) -> str:
    s = s.replace("_", " ").strip().lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s


def run_pandoc_fragment(input_docx: Path) -> tuple[bool, str, str]:
    """
    Convert docx -> HTML fragment returned as a string (not a file).
    Returns (success, stdout_fragment, stderr).
    """
    args = [
        PANDOC_EXE,
        str(input_docx),
        "-f", "docx",
        "-t", "html5",
    ]

    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False
        )
        if proc.returncode != 0:
            return False, "", proc.stderr.strip() or f"Pandoc failed with code {proc.returncode}"
        return True, proc.stdout or "", proc.stderr.strip()
    except FileNotFoundError:
        return False, "", "Pandoc not found. Ensure pandoc is installed and on PATH."
    except Exception as e:
        return False, "", f"Exception running pandoc: {e!r}"


def relpath(from_dir: Path, to_path: Path) -> str:
    import os
    return Path(os.path.relpath(to_path, start=from_dir)).as_posix()


def build_media_index() -> dict[str, Path]:
    """
    Case-insensitive index: filename stem -> full path.
    Example: "f_01_blink_kiss" -> media/F_01_blink_kiss.webp
    """
    idx: dict[str, Path] = {}
    if not MEDIA_DIR.exists():
        return idx

    for p in MEDIA_DIR.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMG_EXT_PRIORITY:
            continue
        idx[p.stem.lower()] = p
    return idx


def parse_docx_name(docx_path: Path) -> tuple[str, str, str]:
    """
    For F_01_THRESHOLD.docx -> ("F", "01", "THRESHOLD")
    """
    stem = docx_path.stem
    parts = stem.split("_", 2)
    if len(parts) < 3:
        return parts[0][0].upper(), "00", stem
    return parts[0].upper(), parts[1], parts[2]


def build_cover_html(category: str, output_html_path: Path) -> str:
    if category == "flame":
        cover_file = MEDIA_DIR / FLAME_COVER_NAME
        label = "Flame cover"
    else:
        cover_file = MEDIA_DIR / ORDER_COVER_NAME
        label = "Order cover"

    if cover_file.exists():
        src = relpath(output_html_path.parent, cover_file)
        return f'<img class="chapter-cover" src="{src}" alt="{html_escape(label)}">'
    return f'<div class="cover-missing">[Missing cover: {html_escape(cover_file.name)}]</div>'


def inject_hooks_and_gallery(
    html_fragment: str,
    media_index: dict[str, Path],
    initial: str,
    chapter_num: str,
    output_html_path: Path,
) -> tuple[str, list[Path], list[str]]:
    """
    Replace @@IMG hooks with <figure> blocks.
    Returns: (new_html, used_images, missing_stems)
    """
    if html_fragment is None:
        html_fragment = ""

    used_images: list[Path] = []
    missing: list[str] = []

    def repl(match: re.Match) -> str:
        key = match.group(1)
        caption = (match.group(2) or "").strip()

        stem = f"{initial}_{chapter_num}_{key}"
        stem_lc = stem.lower()

        found_path: Path | None = None

        # Prefer exact expected filenames (keeps extension priority)
        for ext in IMG_EXT_PRIORITY:
            expected = MEDIA_DIR / f"{stem}{ext}"
            if expected.exists():
                found_path = expected
                break

        # fallback: any matching stem case-insensitively
        if found_path is None:
            found_path = media_index.get(stem_lc)

        if found_path is None:
            missing.append(stem)
            return f'<div class="img-missing">[Missing image: {html_escape(stem)}]</div>'

        used_images.append(found_path)

        img_src = relpath(output_html_path.parent, found_path)
        alt_text = caption if caption else stem
        figcaption_html = f"<figcaption>{html_escape(caption)}</figcaption>" if caption else ""

        # NOTE: keep your original figure structure; CSS already knows it
        return (
            f'<figure class="inline-illustration">'
            f'<img src="{img_src}" alt="{html_escape(alt_text)}">'
            f'{figcaption_html}'
            f'</figure>'
        )

    new_fragment = IMG_HOOK_RE.sub(repl, html_fragment)

    # Unique used images, preserve order
    seen: set[str] = set()
    unique_used: list[Path] = []
    for p in used_images:
        k = p.as_posix().lower()
        if k not in seen:
            seen.add(k)
            unique_used.append(p)

    return new_fragment, unique_used, missing


def lightbox_block(output_html_path: Path) -> str:
    """
    Lightbox overlay + script include.
    IMPORTANT: script src must be relative to the chapter page location.
    """
    js_src = relpath(output_html_path.parent, LIGHTBOX_JS)

    return f"""
<div id="lightbox" class="lightbox" hidden>
  <div class="lightbox-backdrop" data-close="1"></div>

  <button class="lightbox-prev" type="button" aria-label="Previous">‹</button>
  <img id="lightboxImg" class="lightbox-img" alt="">
  <button class="lightbox-next" type="button" aria-label="Next">›</button>

  <button class="lightbox-close" type="button" aria-label="Close" data-close="1">×</button>
</div>

<script src="{js_src}"></script>
""".strip()


def chapter_template(
    *,
    title: str,
    category: str,
    content_html: str,
    output_html_path: Path,
    used_images: list[Path],
    missing_images: list[str],
) -> str:
    base_css_rel = relpath(output_html_path.parent, BASE_CSS)
    vibe_css_rel = relpath(output_html_path.parent, FLAME_CSS if category == "flame" else ORDER_CSS)

    list_target = ROOT / ("flame.html" if category == "flame" else "order.html")
    back_rel = relpath(output_html_path.parent, list_target)

    cover_html = build_cover_html(category, output_html_path)

    # Gallery thumbnails (click opens lightbox; no new tabs)
    gallery_items = []
    for p in used_images:
        src = relpath(output_html_path.parent, p)
        gallery_items.append(
            f'<a class="gallery-item" href="{src}">'
            f'<img src="{src}" alt="{html_escape(p.stem)}"></a>'
        )

    missing_html = ""
    if missing_images:
        missing_lines = "".join(f"<li>{html_escape(x)}</li>" for x in missing_images)
        missing_html = f"""
        <div class="gallery-missing">
          <div class="gallery-missing-title">Missing images referenced in this chapter:</div>
          <ul>{missing_lines}</ul>
        </div>
        """

    gallery_html = f"""
    <section class="chapter-gallery">
      <button id="galleryToggle" class="gallery-toggle" type="button">Show Gallery</button>
      <div id="galleryPanel" class="gallery-panel" hidden>
        {missing_html}
        <div class="gallery-grid">
          {"".join(gallery_items) if gallery_items else "<div class='gallery-empty'>[No images referenced]</div>"}
        </div>
      </div>
      <script>
        (function() {{
          var btn = document.getElementById('galleryToggle');
          var panel = document.getElementById('galleryPanel');
          if (!btn || !panel) return;
          btn.addEventListener('click', function() {{
            var isHidden = panel.hasAttribute('hidden');
            if (isHidden) {{
              panel.removeAttribute('hidden');
              btn.textContent = 'Hide Gallery';
            }} else {{
              panel.setAttribute('hidden', '');
              btn.textContent = 'Show Gallery';
            }}
          }});
        }})();
      </script>
    </section>
    """

    back_to_top_html = '<a class="back-to-top" href="#top" aria-label="Back to top">↑</a>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)}</title>
  <link rel="stylesheet" href="{base_css_rel}">
  <link rel="stylesheet" href="{vibe_css_rel}">
</head>
<body class="{category}" id="top">
  <header class="chapter-header">
    <a class="back-to-list" href="{back_rel}">← Back to chapter list</a>
    <div class="cover-wrap">{cover_html}</div>
  </header>

  <main class="chapter-content">
    {content_html}
  </main>

  {gallery_html}

  {lightbox_block(output_html_path)}

  {back_to_top_html}
</body>
</html>
"""


def build_global_gallery_page() -> str:
    """
    Build-time generated page that lists EVERY image file in /media (flat folder).
    Uses lightbox zoom on click.
    """
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    images = [
        p for p in MEDIA_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in IMG_EXT_PRIORITY
    ]

    images.sort(key=lambda p: (p.stem.lower(), p.suffix.lower(), p.name.lower()))

    items_html = []
    for p in images:
        src = f"media/{p.name}"
        items_html.append(
            f"""
            <figure class="gallery-all-item">
              <a class="gallery-item" href="{src}">
                <img src="{src}" alt="{html_escape(p.stem)}">
              </a>
              <figcaption>{html_escape(p.name)}</figcaption>
            </figure>
            """.strip()
        )

    grid_html = "\n".join(items_html) if items_html else "<div class='gallery-empty'>[No images in /media]</div>"

    # gallery.html sits at ROOT, so script path is simply js/lightbox.js
    js_src = relpath(GALLERY_PAGE_PATH.parent, LIGHTBOX_JS)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Media Gallery</title>
  <link rel="stylesheet" href="css/base.css" />
</head>
<body class="gallery" id="top">
  <nav class="nav">
    <a href="index.html">Menu</a>
  </nav>

  <header class="topbar">
    <h1>Media Gallery</h1>
    <p class="sub">Everything in <code>/media</code>, generated at build time.</p>
  </header>

  <main class="gallery-all">
    <div class="gallery-all-grid">
      {grid_html}
    </div>
  </main>

  <footer class="footer">
    <a href="index.html">Back to menu</a>
  </footer>

  <div id="lightbox" class="lightbox" hidden>
    <div class="lightbox-backdrop" data-close="1"></div>
    <button class="lightbox-prev" type="button" aria-label="Previous">‹</button>
    <img id="lightboxImg" class="lightbox-img" alt="">
    <button class="lightbox-next" type="button" aria-label="Next">›</button>
    <button class="lightbox-close" type="button" aria-label="Close" data-close="1">×</button>
  </div>
  <script src="{js_src}"></script>

  <a class="back-to-top" href="#top" aria-label="Back to top">↑</a>
</body>
</html>
"""


def collect_known_ids(manifest: dict) -> set[str]:
    ids: set[str] = set()
    arcs = (manifest or {}).get("arcs", {})
    if not isinstance(arcs, dict):
        return ids
    for _, entries in arcs.items():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if isinstance(e, dict) and "id" in e:
                ids.add(str(e["id"]))
    return ids


def build_discovery_manifest(existing_manifest: dict) -> dict:
    """
    Writes manifest.new.json containing DOCX chapter items not represented in manifest.json yet.
    Chapters only (F/O).
    """
    known = collect_known_ids(existing_manifest)
    new_items: list[dict] = []

    # Chapters can live anywhere under source-docx now.
    for docx in sorted(SOURCE_DIR.rglob("*.docx")):
        initial = docx.stem[:1].upper()
        if initial not in {"F", "O"}:
            continue

        init, chapnum, rest = parse_docx_name(docx)
        doc_id = f"{init}_{chapnum}"
        arc = "flame" if init == "F" else "order"
        proposed_output = f"content/{arc}/{chapnum}_{rest}.html"
        title_text = rest.replace("_", " ")
        title = f"{chapnum} {title_text}"

        payload = {
            "id": doc_id,
            "type": init,
            "arc": arc,
            "index": safe_int(chapnum, 0),
            "title": title,
            "title_text": title_text,
            "slug": slugify(title_text),
            "source": str(docx.relative_to(ROOT)).replace("\\", "/"),
            "proposed_output": proposed_output,
        }

        if payload["id"] not in known:
            new_items.append(payload)

    return {
        "schema": 1,
        "generated_at": now_iso(),
        "root": str(ROOT.name),
        "new": new_items,
        "counts": {"new": len(new_items)},
    }


def main():
    # Ensure folders exist
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    FLAME_DIR.mkdir(parents=True, exist_ok=True)
    ORDER_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    JS_DIR.mkdir(parents=True, exist_ok=True)

    with LOG_PATH.open("w", encoding="utf-8") as log_fh:
        log(f"STORYHUB build log — {now_iso()}", log_fh)
        log(f"ROOT: {ROOT}", log_fh)
        log(f"SOURCE_DIR: {SOURCE_DIR}", log_fh)
        log(f"CONTENT_DIR: {CONTENT_DIR}", log_fh)
        log(f"MEDIA_DIR: {MEDIA_DIR}", log_fh)
        log("", log_fh)

        media_index = build_media_index()

        # Load existing manifest if it exists (non-destructive)
        manifest: dict
        if MANIFEST_PATH.exists():
            try:
                manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
                if not isinstance(manifest, dict) or manifest.get("schema") != 2:
                    raise ValueError("manifest schema mismatch")
            except Exception:
                manifest = {}
        else:
            manifest = {}

        if not manifest:
            manifest = {
                "schema": 2,
                "generated_at": now_iso(),
                "root": str(ROOT.name),
                "arcs": {
                    "flame": [],
                    "order": [],
                    "characters": [],
                    "lore": [],
                }
            }

        # Always update timestamp
        manifest["generated_at"] = now_iso()
        manifest["root"] = str(ROOT.name)

        converted = 0
        skipped = 0
        failed = 0

        rebuilt_flame: list[dict] = []
        rebuilt_order: list[dict] = []

        # Chapters-only: process F_/O_ docx anywhere under source-docx
        for docx in sorted(SOURCE_DIR.rglob("*.docx")):
            initial = docx.stem[:1].upper()
            if initial not in {"F", "O"}:
                skipped += 1
                continue

            init, chapnum, rest = parse_docx_name(docx)
            category = "flame" if init == "F" else "order"

            out_dir = FLAME_DIR if category == "flame" else ORDER_DIR
            out_name = f"{chapnum}_{rest}.html"
            out_path = out_dir / out_name

            ok, fragment, err = run_pandoc_fragment(docx)
            if not ok:
                failed += 1
                log(f"[FAIL] {docx.name}: {err}", log_fh)
                continue

            injected_fragment, used_imgs, missing_imgs = inject_hooks_and_gallery(
                fragment, media_index, init, chapnum, out_path
            )

            title_text = rest.replace("_", " ")
            title = f"{chapnum} {title_text}"

            final_html = chapter_template(
                title=title,
                category=category,
                content_html=injected_fragment,
                output_html_path=out_path,
                used_images=used_imgs,
                missing_images=missing_imgs,
            )

            out_path.write_text(final_html, encoding="utf-8")
            converted += 1

            chapter_index = safe_int(chapnum, 0)
            chapter_id = f"{init}_{chapnum}"

            entry = {
                "id": chapter_id,
                "type": init,
                "arc": category,
                "index": chapter_index,
                "title": title,
                "title_text": title_text,
                "slug": slugify(title_text),
                "source": str(docx.relative_to(ROOT)).replace("\\", "/"),
                "output": str(out_path.relative_to(ROOT)).replace("\\", "/"),
                "images": [str(p.relative_to(ROOT)).replace("\\", "/") for p in used_imgs],
                "missing_images": missing_imgs,
                "counts": {
                    "images_used": len(used_imgs),
                    "images_missing": len(missing_imgs),
                },
            }

            (rebuilt_flame if category == "flame" else rebuilt_order).append(entry)

            log(f"[OK] {docx.name} -> {out_path}", log_fh)
            log(f"     images used: {len(used_imgs)}, missing: {len(missing_imgs)}", log_fh)
            if err:
                log(f"     pandoc stderr: {err}", log_fh)

        # Install rebuilt F/O into manifest, preserve characters/lore as-is
        rebuilt_flame.sort(key=lambda x: x.get("index", 0))
        rebuilt_order.sort(key=lambda x: x.get("index", 0))
        manifest["arcs"]["flame"] = rebuilt_flame
        manifest["arcs"]["order"] = rebuilt_order

        MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        discovery = build_discovery_manifest(manifest)
        MANIFEST_NEW_PATH.write_text(json.dumps(discovery, ensure_ascii=False, indent=2), encoding="utf-8")

        gallery_html = build_global_gallery_page()
        GALLERY_PAGE_PATH.write_text(gallery_html, encoding="utf-8")
        log(f"[OK] gallery.html -> {GALLERY_PAGE_PATH}", log_fh)

        log("", log_fh)
        log("=== Summary ===", log_fh)
        log(f"Converted:  {converted}", log_fh)
        log(f"Skipped:    {skipped}", log_fh)
        log(f"Failed:     {failed}", log_fh)
        log(f"Manifest:   {MANIFEST_PATH}", log_fh)
        log(f"Discovery:  {MANIFEST_NEW_PATH}", log_fh)

    print(f"[INFO] Done.")
    print(f"[INFO] ROOT:       {ROOT}")
    print(f"[INFO] Manifest:   {MANIFEST_PATH}")
    print(f"[INFO] Discovery:  {MANIFEST_NEW_PATH}")
    print(f"[INFO] Gallery:    {GALLERY_PAGE_PATH}")
    print(f"[INFO] Log:        {LOG_PATH}")


if __name__ == "__main__":
    try:
        main()
        input("\nPress Enter to close...")
    except Exception as e:
        print("\n[FATAL]", repr(e))
        input("\nPress Enter to close...")
        raise
