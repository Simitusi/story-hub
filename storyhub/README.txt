This document describes builder contracts, not usage tips.


# STORYHUB BUILDER — HARD RULES & CONTRACTS

This document lists **all standardized rules** enforced by the converter/builder.
Anything listed as *hard-coded* must NOT be changed unless the builder is modified.

---

## 1. DOCX SOURCE FILE RULES

### 1.1 Allowed prefixes (HARD-CODED)

Only these initials are recognized:

* `F_` → Flame chapters (full automation)
* `O_` → Order chapters (full automation)
* `C_` → Characters (Pandoc-only conversion)
* `L_` → Lore (Pandoc-only conversion)

Any other prefix → file is skipped.

---

### 1.2 DOCX filename format (HARD-CODED)

#### Chapters (F / O):

```
F_01_TITLE.docx
O_03_SOMETHING.docx
```

Rules:

* Initial is **UPPERCASE**
* Chapter number is **two digits**
* Title uses underscores instead of spaces
* File extension must be `.docx`

#### Characters / Lore (C / L):

```
C_LUCY.docx
L_ARK_HISTORY.docx
```

No chapter numbers required.

---

### 1.3 DOCX location (HARD-CODED)

All source files must be inside:

```
/source-docx/
```

---

## 2. OUTPUT STRUCTURE RULES

### 2.1 Chapter output paths (HARD-CODED)

* Flame chapters → `content/flame/`
* Order chapters → `content/order/`

Filename format:

```
01_TITLE.html
```

---

### 2.2 Character & Lore output (HARD-CODED)

Characters and Lore are converted with **Pandoc only**, no automation.

* Characters → `content/characters/`
* Lore → `content/lore/`

These files are meant to be **manually edited afterward**.

---

### 2.3 Manifest file (HARD-CODED)

* Path:

  ```
  /manifest.json
  ```
* Overwritten every build
* Used by navigation JS
* Do NOT edit manually

# `manifest.json` — Build Output Specification

`manifest.json` is generated **on every build** by `converter.py`.
It is the **single source of truth** for navigation, chapter listing, and metadata.

This file is **fully generated**.
Do **not** edit it manually.

---

## General Structure

```json
{
  "schema": 2,
  "generated_at": "YYYY-MM-DDTHH:MM:SS",
  "root": "STORYHUB",
  "arcs": {
    "flame": [],
    "order": [],
    "characters": [],
    "lore": []
  }
}
```

### Top-level fields

| Field          | Type   | Description                                                  |
| -------------- | ------ | ------------------------------------------------------------ |
| `schema`       | number | Manifest schema version. Incremented when structure changes. |
| `generated_at` | string | ISO timestamp of build time.                                 |
| `root`         | string | Name of the project root directory.                          |
| `arcs`         | object | Grouped chapter entries by category.                         |

---

## Arcs

The `arcs` object groups all generated content by logical section:

| Arc          | Description                    |
| ------------ | ------------------------------ |
| `flame`      | Flame chapters (`F_XX_*.docx`) |
| `order`      | Order chapters (`O_XX_*.docx`) |
| `characters` | Character pages (`C_*.docx`)   |
| `lore`       | Lore pages (`L_*.docx`)        |

Each arc contains an **array of entries**, already sorted deterministically by the builder.

---

## Flame / Order Chapter Entry

Entries inside `arcs.flame` and `arcs.order` follow this structure:

```json
{
  "id": "F_01",
  "type": "F",
  "arc": "flame",
  "index": 1,
  "title": "01 THRESHOLD",
  "title_text": "THRESHOLD",
  "slug": "threshold",
  "source": "source-docx/F_01_THRESHOLD.docx",
  "output": "content/flame/01_THRESHOLD.html",
  "images": [
    "media/F_01_key.webp"
  ],
  "missing_images": [],
  "counts": {
    "images_used": 1,
    "images_missing": 0
  }
}
```

### Field reference

| Field                   | Type   | Meaning                                      |
| ----------------------- | ------ | -------------------------------------------- |
| `id`                    | string | Stable chapter identifier (`F_01`, `O_03`).  |
| `type`                  | string | `"F"` or `"O"`.                              |
| `arc`                   | string | `"flame"` or `"order"`.                      |
| `index`                 | number | Numeric chapter index used for ordering.     |
| `title`                 | string | Display title including index.               |
| `title_text`            | string | Title without index.                         |
| `slug`                  | string | Lowercase, URL-safe slug derived from title. |
| `source`                | string | Path to the originating `.docx` file.        |
| `output`                | string | Path to the generated HTML file.             |
| `images`                | array  | List of image files successfully injected.   |
| `missing_images`        | array  | Image stems referenced but not found.        |
| `counts.images_used`    | number | Number of images injected.                   |
| `counts.images_missing` | number | Number of missing images.                    |

### Guarantees

* Entries are **already sorted** by `index`
* Paths use **forward slashes**
* Missing images **do not fail the build**
* `output` paths are safe to use directly as `<a href>`

---

## Characters / Lore Entry

Entries inside `arcs.characters` and `arcs.lore` are simpler:

```json
{
  "id": "C_LUCY",
  "type": "C",
  "arc": "characters",
  "title": "C LUCY",
  "slug": "lucy",
  "source": "source-docx/C_LUCY.docx",
  "output": "content/characters/LUCY.html"
}
```

### Notes

* These files are generated via **Pandoc standalone conversion**
* No image hook processing is applied
* Styling is handled manually after generation

---

## Intended Usage

* `navgen.js` reads `manifest.json` to build navigation
* No filesystem scanning is required at runtime
* Consumers should rely on:

  * `arc` for filtering
  * `index` for ordering
  * `output` for linking

---

## Stability Rules

* Generated HTML files are **immutable outputs**
* All structural changes happen **at build time**
* Runtime JavaScript must treat the manifest as read-only data
* If the schema changes, `schema` will increment

---

## Do Not

* Manually edit `manifest.json`
* Derive metadata by parsing filenames
* Assume filesystem order equals chapter order
* Store state in generated HTML

---

### 2.4 Log file (HARD-CODED)

* Path:

  ```
  /log.txt
  ```
* Overwritten every run
* Contains:

  * timestamps
  * converted files
  * missing images
  * Pandoc errors
  * summary

---

## 3. IMAGE SYSTEM RULES

### 3.1 Media folder (HARD-CODED)

All images must be placed in:

```
/media/
```

No subfolders. Flat structure.

---

### 3.2 Image filename format (HARD-CODED)

For chapter illustrations:

```
F_01_key.webp
O_03_key.png
```

Rules:

* Initial matches DOCX (`F` or `O`)
* Chapter number matches DOCX
* `key` matches image hook key exactly
* Case sensitive on GitHub (use uppercase consistently)

---

### 3.3 Allowed image formats (HARD-CODED, priority order)

1. `.webp`
2. `.png`
3. `.jpg`
4. `.jpeg`
5. `.gif`

First match wins.

---

## 4. IMAGE HOOK SYNTAX (HARD-CODED)

### 4.1 Valid hook formats

#### No caption:

```
@@IMG:key@@
```

#### With caption:

```
@@IMG:key|Caption text here@@
```

Rules:

* No spaces inside `@@IMG: ... @@`
* `key` may contain only:

  * letters
  * numbers
  * underscores
* Caption is optional and may contain spaces

---

### 4.2 Hook placement rules (REQUIRED)

* Hook **must be on its own line**
* Use **Normal** paragraph style
* No bold, italics, font changes, or formatting
* Do not embed hooks inline with text

Correct:

```
@@IMG:blink_kiss@@
```

Incorrect:

```
Some text @@IMG:blink_kiss@@ more text
```

---

### 4.3 Missing images (HARD-CODED BEHAVIOR)

If an image is not found:

* A visible placeholder is inserted into the chapter
* Missing image is listed in:

  * the chapter gallery
  * `log.txt`

Build **does not fail**.

---

## 5. COVER IMAGE RULES (HARD-CODED)

### 5.1 Flame cover

```
media/hellfirefiends.webp
```

### 5.2 Order cover

```
media/ark.webp
```

If missing:

* Placeholder block is rendered instead
* Logged as missing

---

## 6. GALLERY RULES (HARD-CODED)

* Gallery is generated **only** from images referenced by hooks
* No unused images are shown
* Gallery is:

  * collapsed by default
  * revealed via “Show Gallery” button
* Missing images appear in gallery as warnings

No manual gallery editing allowed.

---

## 7. CSS & NAVIGATION RULES

### 7.1 CSS loading (HARD-CODED)

All chapters load:

```
css/base.css
```

Additionally:

* Flame → `css/flame.css`
* Order → `css/order.css`

---

### 7.2 Back-to-list button (HARD-CODED)

Every chapter includes:

```
← Back to chapter list
```

Targets:

* Flame → `flame.html`
* Order → `order.html`

Button text is identical everywhere.

---

## 8. WHAT IS ALLOWED TO CHANGE (SAFE)

* Chapter text content
* Chapter order
* Adding/removing hooks
* Replacing images without changing filenames
* CSS styling
* JS behavior (navigation, gallery visuals)
* Adding new DOCX files that follow naming rules

---

## 9. WHAT MUST NEVER BE DONE

* Editing generated chapter HTML manually
* Renaming images without updating hooks
* Changing filename case inconsistently
* Adding spaces or formatting to hook lines
* Mixing generated and handwritten HTML
* Moving files out of defined folders

---

## 10. CORE PRINCIPLE (DO NOT VIOLATE)

**All change happens at build time.**
Generated HTML is immutable output.

If you feel tempted to “just tweak the HTML once,”
the system is working and your impulse is the bug.


