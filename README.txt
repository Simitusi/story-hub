# Chapter Builder (`build_chapters.py`)

This script builds **story chapters** from DOCX files.

It converts chapter DOCX files under `source-docx/` into fully styled HTML pages under `content/flame/` and `content/order/`, injects images, builds per-chapter galleries, generates a global media gallery, and updates the **chapter arcs** in `manifest.json`.

This is the loud, cinematic builder. It does the most work and touches the most moving parts. Respect it.

---

## What this builder does

### ✅ Builds story chapters

* One DOCX → one HTML page
* Supports Flame and Order arcs
* Injects inline illustrations
* Generates a per-chapter gallery
* Adds lightbox navigation
* Applies arc-specific CSS

### ✅ Builds a global media gallery

* Lists **every image** in `/media`
* Lightbox-enabled
* Generated on every build

### ✅ Updates:

```json
manifest.arcs.flame
manifest.arcs.order
```

---

## What this builder does NOT do

* ❌ Does not touch characters
* ❌ Does not touch lore
* ❌ Does not modify character or lore pages
* ❌ Does not overwrite CSS
* ❌ Does not assume anything about folders under `characters/` or `lore/`

It is arc-aware, not globally destructive.

---

## Chapter DOCX discovery rules

The builder scans **all DOCX files** under:

```
source-docx/
```

But it only builds files whose **filename starts with**:

* `F_` → Flame arc
* `O_` → Order arc

Everything else is skipped.

This is intentional. Chapters are discovered by **prefix**, not folder.

---

## Chapter filename format (mandatory)

```
F_01_THRESHOLD.docx
O_07_FALLING_APART.docx
```

Meaning:

* `F` / `O` = arc
* `01` = chapter number (used for sorting)
* `THRESHOLD` = chapter title

If you break this format, the builder will still try, but the results will look wrong and that will be on you.

---

## Output structure

### Flame chapters

```
content/
  flame/
    01_THRESHOLD.html
    02_SOMETHING.html
```

### Order chapters

```
content/
  order/
    01_BEGINNING.html
```

Arc determines:

* output folder
* CSS file
* cover image

---

## DOCX formatting rules (important)

Pandoc does not care about your feelings.

### Use these Word styles

* **Normal text** – story paragraphs
* **Heading 2 / 3** – optional internal section breaks
* Proper lists when needed

### Do NOT use

* Heading 1 for the chapter title (title comes from filename)
* Text boxes
* Columns
* WordArt
* Manual spacing hacks

Story flow comes from text, not layout tricks.

---

## Image hooks (chapter-specific)

Chapters use **indexed image hooks**:

```
@@IMG:key@@
@@IMG:key|caption@@
```

Resolution rule:

```
<ARC>_<CHAPTER>_<key>.<ext>
```

Example:

```
F_01_blink_kiss.webp
O_07_firestorm.png
```

Images live in:

```
/media/
```

---

## Inline illustrations

Each image hook becomes:

* an inline `<figure>`
* styled by CSS
* included automatically in the chapter gallery

Missing images:

* render as visible warnings in the chapter
* are listed in the gallery “Missing images” panel
* are logged during build

---

## Per-chapter gallery

Every chapter page includes:

* A **toggleable gallery section**
* Thumbnails of all images used in that chapter
* Missing image warnings
* Lightbox navigation (prev / next / close)

This is automatic. You don’t opt in.

---

## Global media gallery

The builder also generates:

```
gallery.html
```

Features:

* Lists every image in `/media`
* Sorted alphabetically
* Lightbox-enabled
* Independent of chapters

This page is regenerated on every build.

---

## Covers

Each arc has a fixed cover image:

* Flame: `media/hellfirefiends.webp`
* Order: `media/ark.webp`

If missing:

* a visible placeholder is rendered instead

Covers are injected automatically.

---

## CSS behavior

Chapter pages always link:

```
css/base.css
css/flame.css   (Flame arc)
css/order.css   (Order arc)
```

The builder:

* assumes these exist
* never creates or overwrites them

Styling is your responsibility.

---

## Manifest entries

Each chapter produces an entry like:

```json
{
  "id": "F_01",
  "type": "F",
  "arc": "flame",
  "index": 1,
  "title": "01 THRESHOLD",
  "output": "content/flame/01_THRESHOLD.html"
}
```

Entries are:

* rebuilt every run
* sorted by chapter number
* installed into their respective arc only

Characters and lore remain untouched.

---

## Discovery manifest

The builder also generates:

```
manifest.new.json
```

Purpose:

* lists chapter DOCX files not yet in `manifest.json`
* helps you discover unregistered chapters

This file is informational. Nothing reads from it automatically.

---

## Running the builder

```bash
python build_chapters.py
```

Requirements:

* Python 3.10+
* Pandoc installed and on PATH

Logs are written to:

```
log.txt
```

---

## Design philosophy (read this before “improving” it)

* Chapters are **narrative**, not reference
* Filenames define identity and order
* Visual drama is allowed here, nowhere else
* The builder is allowed to be heavy
* Side effects are explicit, not hidden

If you want something quieter, cleaner, or more semantic, that’s lore or characters. Chapters are supposed to feel like they’re on fire.

---

## When to use this builder

Use it for:

* Main story chapters
* Ordered narrative content
* Anything that belongs in Flame or Order arcs

Do NOT use it for:

* Lore explanations
* Character profiles
* Glossaries
* Notes
* Experiments

That’s how you keep the project from collapsing into soup.










# Character Builder (`build_characters.py`)

This script builds **character profile pages** from DOCX files.

It converts DOCX files under `source-docx/characters/` into styled HTML pages under `content/characters/`, resolves image hooks, and updates **only** the characters section of `manifest.json`.

It is intentionally strict. Characters are not freeform notes.

---

## What this builder does

### ✅ Builds character pages

* One DOCX → one HTML page
* Folder structure is preserved
* Category-specific CSS is auto-created (once)
* Image hooks are resolved
* Hellhound-style layout is enforced

### ✅ Updates only:

```json
manifest.arcs.characters
```

---

## What this builder does NOT do

* ❌ Does not touch chapters
* ❌ Does not touch lore
* ❌ Does not build galleries
* ❌ Does not reorder flame/order arcs
* ❌ Does not overwrite CSS
* ❌ Does not scan outside `source-docx/characters/`

This builder is path-isolated. You cannot accidentally feed it lore or chapters unless you physically move files.

---

## Folder structure (required)

### Source

```
source-docx/
  characters/
    fiends/
      Lucy Moore.docx
      Blink.docx
    marauders/
      Nyx.docx
```

### Output

```
content/
  characters/
    fiends/
      lucy-moore.html
      blink.html
    marauders/
      nyx.html
```

* First folder under `characters/` = **category**
* Folder structure is mirrored exactly in output
* File name = character display title

No prefixes. Folder structure is law.

---

## Category CSS behavior (important)

For each category folder, the builder ensures:

```
css/<category>.css
```

Example:

```
css/fiends.css
css/marauders.css
```

If the file does not exist:

* It is created **once**
* Contains a comment stub
* Is never overwritten

You are expected to:

```css
@import url("./base.css");
/* then theme it */
```

Each character page links **only** its category CSS.

---

## DOCX formatting rules

Pandoc is literal. Follow these rules.

### Use these Word styles

* **Heading 1** – optional character name
* **Heading 2** – major sections (Overview, Personality, Combat, etc.)
* **Heading 3** – subsections
* Normal paragraphs
* Proper lists

### Do NOT use

* Text boxes
* Columns
* WordArt
* Manual spacing for layout
* Inline pasted images

Characters are content, not layout experiments.

---

## Image hooks

Supported syntax:

```
@@IMG:key@@
@@IMG:key|left@@
@@IMG:key|right@@
@@IMG:key|center@@
@@IMG:key|intro@@
```

Images are resolved from:

```
/media/<key>.(webp|png|jpg|jpeg|gif)
```

Resolution is:

* case-insensitive
* extension-priority based

Missing images:

* are shown inline as warnings
* are listed in a “Missing images” panel at the top
* are logged during build

---

## HTML structure (guaranteed)

Every character page uses the same skeleton:

* Hero header with name + category
* Metadata tags
* Content panel
* Floating menu button
* Back-to-top button

This is intentional. Characters must feel consistent.

If you want wildly different layouts, that’s lore or chapters, not characters.

---

## Ignored files

Anything starting with `_` is ignored.

Examples:

```
source-docx/characters/_drafts/
source-docx/characters/fiends/_Lucy_notes.docx
```

These will never be built.

---

## Manifest entries

Each character produces an entry like:

```json
{
  "type": "C",
  "arc": "characters",
  "category": "fiends",
  "title": "Lucy Moore",
  "slug": "lucy-moore",
  "output": "content/characters/fiends/lucy-moore.html"
}
```

Entries are sorted by:

* category
* title (alphabetical)

Only `manifest.arcs.characters` is replaced.

---

## Running the builder

```bash
python build_characters.py
```

Requirements:

* Python 3.10+
* Pandoc installed and on PATH

Logs are written to:

```
characters_build_log.txt
```

---

## Design philosophy (do not fight this)

* Characters are **entities**, not essays
* Consistency > creativity at the page level
* Categories control theme, not filenames
* Builders should be deterministic and boring
* Styling belongs in CSS, not DOCX

If you find yourself wanting to “just tweak one character’s layout”, you’re probably about to break consistency for no good reason.

---

## When to use this builder

Use it for:

* Named characters
* Factions leaders
* Recurring NPCs
* Robots, creatures, or entities treated as “characters”

Do NOT use it for:

* Lore explanations
* Systems
* Timelines
* Glossaries
* Chapters

That’s what the other builders are for.









# Lore Builder (`build_lore.py`)

This script builds **lore pages** and the **Terms & Labels glossary** for the project.

It converts DOCX files under `source-docx/lore/` into static HTML pages under `content/lore/`, updates the lore section of `manifest.json`, and does **nothing else**.

If you’re worried it might touch chapters or characters: it won’t. Ever.

---

## What this builder does

### ✅ Builds standard lore pages

* One DOCX → one HTML page
* Folder structure is preserved
* Image hooks are resolved
* Clean, documentation-style layout

### ✅ Builds the Terms & Labels mega-page

* One growing DOCX → one searchable HTML glossary
* Terms are alphabetized automatically
* Built-in client-side search
* Deep links for every term
* A–Z jump navigation

### ✅ Updates only:

```json
manifest.arcs.lore
```

---

## What this builder does NOT do

* ❌ Does not touch chapters
* ❌ Does not touch characters
* ❌ Does not touch galleries
* ❌ Does not modify flame/order content
* ❌ Does not overwrite CSS files
* ❌ Does not assume prefixes exist

This builder is sandboxed by path. Folder law is absolute.

---

## Folder structure (required)

### Source

```
source-docx/
  lore/
    eden/
      Project Eden.docx
    wasteland/
      Aberration.docx
    economy/
      Economy.docx
```

### Output

```
content/
  lore/
    eden/
      project-eden.html
    wasteland/
      aberration.html
    economy/
      economy.html
```

Folder names define **categories**.
File names define **page titles**.

No prefixes. No numbering. No arc logic.

---

## Ignored files and folders

Anything starting with `_` is ignored.

Examples:

```
source-docx/lore/_drafts/
source-docx/lore/_notes.docx
```

These will never be built.

---

## DOCX formatting rules (important)

Pandoc is literal. Follow these or accept chaos.

### Use these Word styles

* **Heading 1** – optional page title
* **Heading 2** – main sections
* **Heading 3** – subsections
* Normal paragraphs
* Proper bullet / numbered lists

### Do NOT use

* Text boxes
* Columns
* Manual spacing as layout
* WordArt
* Inline pasted images (use image hooks)

---

## Image hooks

Supported everywhere in lore:

```
@@IMG:key@@
@@IMG:key|left@@
@@IMG:key|right@@
@@IMG:key|center@@
@@IMG:key|intro@@
```

Images are resolved from:

```
/media/<key>.(webp|png|jpg|jpeg|gif)
```

Missing images are reported visibly in the output page and logged.

---

## Terms & Labels (Glossary)

The glossary is a **single DOCX file** that grows forever.

### Accepted locations

```
source-docx/lore/terms.docx
```

or

```
source-docx/lore/terms/terms.docx
```

### DOCX convention (mandatory)

Each term starts with a line beginning with `@`.

Example:

```
@Aberration
A non-contagious condition caused by prolonged neurochemical dependency.

@Resurgents
Aberrants who maintain cognition by consuming human flesh.
```

Rules:

* `@Term` must be on its own line
* Everything until the next `@` belongs to that term
* Order in DOCX does not matter

---

## Glossary HTML features

The generated page:

```
content/lore/terms.html
```

Includes:

* Alphabetical ordering
* Client-side search (term name + body)
* A–Z jump navigation
* Collapsible entries
* Deep links (`#aberration`)

Search hides the jump bar automatically to avoid lying to the user.

---

## CSS

This builder expects:

```
css/lore.css
css/terms.css
```

If missing, it will create **empty stub files** once.

It will **never overwrite existing CSS**.

You are expected to `@import base.css` yourself.

---

## Manifest entries

Standard lore pages:

```json
{
  "type": "L",
  "arc": "lore",
  "kind": "page",
  "category": "wasteland",
  "title": "Aberration",
  "output": "content/lore/wasteland/aberration.html"
}
```

Terms page:

```json
{
  "type": "L",
  "arc": "lore",
  "kind": "terms",
  "category": "terms",
  "title": "Terms & Labels",
  "output": "content/lore/terms.html"
}
```

Only `manifest.arcs.lore` is replaced.

---

## Running the builder

```bash
python build_lore.py
```

Requirements:

* Python 3.10+
* Pandoc installed and on PATH

The script logs to:

```
lore_build_log.txt
```

---

## Design philosophy (so you don’t “optimize” it to death)

* Lore is infrastructure, not narrative
* Folder structure > filenames
* Builders should be dumb and deterministic
* Sorting happens at build time, not runtime
* Search is client-side and disposable
