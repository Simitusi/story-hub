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
# Important: PyInstaller --onefile runs from a temp _MEI folder, so __file__ is not your project.
# Use sys.executable when frozen so outputs land next to converter.exe (your STORYHUB folder).
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent

PANDOC_EXE = "pandoc"  # assumes pandoc is on PATH

SOURCE_DIR = ROOT / "source-docx"
CONTENT_DIR = ROOT / "content"
MEDIA_DIR = ROOT / "media"

FLAME_DIR = CONTENT_DIR / "flame"
ORDER_DIR = CONTENT_DIR / "order"
CHAR_DIR = CONTENT_DIR / "characters"
LORE_DIR = CONTENT_DIR / "lore"

BASE_CSS = ROOT / "css" / "base.css"
FLAME_CSS = ROOT / "css" / "flame.css"
ORDER_CSS = ROOT / "css" / "order.css"

MANIFEST_PATH = ROOT / "manifest.json"
LOG_PATH = ROOT / "log.txt"

# Global media gallery page (generated each build)
GALLERY_PAGE_PATH = ROOT / "gallery.html"

# Covers
FLAME_COVER_NAME = "hellfirefiends.webp"
ORDER_COVER_NAME = "ark.webp"

# Image hook marker:
#   @@IMG:key@@
#   @@IMG:key|caption@@  (caption optional; may be empty)
IMG_HOOK_RE = re.compile(r"@@IMG:([a-zA-Z0-9_]+)(?:\|([^@]*?))?@@")

# Preferred extensions (first match wins)
IMG_EXT_PRIORITY = [".webp", ".png", ".jpg", ".jpeg", ".gif"]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(line: str, fh):
    fh.write(line.rstrip() + "\n")


def safe_int(s: str, default: int = 0) -> int:
    try:
        return int(s)
    except Exception:
        return default


def slugify(s: str) -> str:
    """
    Deterministic slug for URLs/UI keys.
    Example: "MY_TITLE" -> "my-title"
    """
    s = s.replace("_", " ").strip().lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s


def run_pandoc(input_docx: Path, output_html: Path, standalone: bool) -> tuple[bool, str]:
    """
    Convert docx -> html file via pandoc.
    Returns (success, stderr_or_message).
    """
    output_html.parent.mkdir(parents=True, exist_ok=True)

    args = [
        PANDOC_EXE,
        str(input_docx),
        "-f", "docx",
        "-t", "html5",
        "-o", str(output_html),
    ]

    # Standalone page (-s) vs fragment
    if standalone:
        args.insert(-2, "-s")

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
            return False, proc.stderr.strip() or f"Pandoc failed with code {proc.returncode}"
        return True, proc.stderr.strip()
    except FileNotFoundError:
        return False, "Pandoc not found. Ensure pandoc is installed and on PATH."
    except Exception as e:
        return False, f"Exception running pandoc: {e!r}"


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


def lightbox_block() -> str:
    """
    Lightbox overlay (markup only) + shared JS include.
    Requires js/lightbox.js to exist.
    """
    return """
<div id="lightbox" class="lightbox" hidden>
  <div class="lightbox-backdrop" data-close="1"></div>

  <button class="lightbox-prev" type="button" aria-label="Previous">‹</button>
  <img id="lightboxImg" class="lightbox-img" alt="">
  <button class="lightbox-next" type="button" aria-label="Next">›</button>

  <button class="lightbox-close" type="button" aria-label="Close" data-close="1">×</button>
</div>

<script src="js/lightbox.js"></script>
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

  {lightbox_block()}

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

  {lightbox_block()}

  <a class="back-to-top" href="#top" aria-label="Back to top">↑</a>
</body>
</html>
"""


def main():
    # Ensure folders exist
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    FLAME_DIR.mkdir(parents=True, exist_ok=True)
    ORDER_DIR.mkdir(parents=True, exist_ok=True)
    CHAR_DIR.mkdir(parents=True, exist_ok=True)
    LORE_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    with LOG_PATH.open("w", encoding="utf-8") as log_fh:
        log(f"STORYHUB build log — {now_iso()}", log_fh)
        log(f"ROOT: {ROOT}", log_fh)
        log(f"SOURCE_DIR: {SOURCE_DIR}", log_fh)
        log(f"CONTENT_DIR: {CONTENT_DIR}", log_fh)
        log(f"MEDIA_DIR: {MEDIA_DIR}", log_fh)
        log("", log_fh)

        media_index = build_media_index()

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

        converted = 0
        skipped = 0
        failed = 0

        for docx in sorted(SOURCE_DIR.glob("*.docx")):
            initial = docx.stem[:1].upper()

            if initial not in {"F", "O", "C", "L"}:
                skipped += 1
                log(f"[SKIP] {docx.name} (unknown initial)", log_fh)
                continue

            # F/O: full automation pipeline
            if initial in {"F", "O"}:
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
                chapter_id = f"{init}_{chapnum}"  # stable ID, e.g. F_01

                entry = {
                    "id": chapter_id,
                    "type": init,  # "F" or "O"
                    "arc": category,  # "flame" or "order"
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

                manifest["arcs"][category].append(entry)

                log(f"[OK] {docx.name} -> {out_path}", log_fh)
                log(f"     images used: {len(used_imgs)}, missing: {len(missing_imgs)}", log_fh)
                if err:
                    log(f"     pandoc stderr: {err}", log_fh)

            # C/L: pandoc-only conversion (standalone HTML), no hooks/template
            else:
                out_dir = CHAR_DIR if initial == "C" else LORE_DIR
                out_name = docx.stem[2:] + ".html" if docx.stem.startswith(f"{initial}_") else docx.stem + ".html"
                out_path = out_dir / out_name

                ok, err = run_pandoc(docx, out_path, standalone=True)
                if not ok:
                    failed += 1
                    log(f"[FAIL] {docx.name}: {err}", log_fh)
                    continue

                converted += 1

                arc = "characters" if initial == "C" else "lore"
                raw_title = docx.stem.replace("_", " ")
                slug_base = docx.stem[2:] if docx.stem.startswith(f"{initial}_") else docx.stem

                entry = {
                    "id": docx.stem,
                    "type": initial,  # "C" or "L"
                    "arc": arc,
                    "title": raw_title,
                    "slug": slugify(slug_base),
                    "source": str(docx.relative_to(ROOT)).replace("\\", "/"),
                    "output": str(out_path.relative_to(ROOT)).replace("\\", "/"),
                }

                manifest["arcs"][arc].append(entry)
                log(f"[OK] {docx.name} -> {out_path} (pandoc-only)", log_fh)

        # Deterministic arc ordering
        manifest["arcs"]["flame"].sort(key=lambda x: x.get("index", 0))
        manifest["arcs"]["order"].sort(key=lambda x: x.get("index", 0))
        manifest["arcs"]["characters"].sort(key=lambda x: x.get("title", ""))
        manifest["arcs"]["lore"].sort(key=lambda x: x.get("title", ""))

        MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        # Build global media gallery page
        gallery_html = build_global_gallery_page()
        GALLERY_PAGE_PATH.write_text(gallery_html, encoding="utf-8")
        log(f"[OK] gallery.html -> {GALLERY_PAGE_PATH}", log_fh)

        log("", log_fh)
        log("=== Summary ===", log_fh)
        log(f"Converted: {converted}", log_fh)
        log(f"Skipped:   {skipped}", log_fh)
        log(f"Failed:    {failed}", log_fh)

    print(f"[INFO] Done. Manifest: {MANIFEST_PATH}")
    print(f"[INFO] Gallery:  {GALLERY_PAGE_PATH}")
    print(f"[INFO] Log:      {LOG_PATH}")


if __name__ == "__main__":
    try:
        main()
        input("\nPress Enter to close...")
    except Exception as e:
        print("\n[FATAL]", repr(e))
        input("\nPress Enter to close...")
        raise
