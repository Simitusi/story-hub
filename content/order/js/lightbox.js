/* STORYHUB lightbox.js
   - Click any <a class="gallery-item" href="..."><img ...></a> to open.
   - Supports:
     - Clickable prev/next arrows
     - Keyboard: Left/Right/Escape
     - Click backdrop or × to close
*/

(function () {
  "use strict";

  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  var lb = qs("#lightbox");
  var lbImg = qs("#lightboxImg");
  var btnPrev = qs(".lightbox-prev", lb);
  var btnNext = qs(".lightbox-next", lb);
  var btnClose = qs(".lightbox-close", lb);

  // If the page doesn't include the overlay, do nothing.
  if (!lb || !lbImg) return;

  var items = [];
  var index = -1;

  function refreshItems() {
    items = qsa("a.gallery-item");
  }

  function setNoScroll(on) {
    if (on) document.body.classList.add("no-scroll");
    else document.body.classList.remove("no-scroll");
  }

  function openAt(i) {
    refreshItems();
    if (!items.length) return;

    // clamp / wrap
    index = ((i % items.length) + items.length) % items.length;

    var a = items[index];
    var src = a.getAttribute("href") || "";
    var im = a.querySelector("img");
    var alt = im ? (im.getAttribute("alt") || "") : "";

    lbImg.src = src;
    lbImg.alt = alt;

    lb.hidden = false;
    setNoScroll(true);

    // Optional: focus close button so keyboard users aren’t stranded
    if (btnClose) btnClose.focus();
  }

  function close() {
    lb.hidden = true;
    lbImg.src = "";
    lbImg.alt = "";
    setNoScroll(false);
    index = -1;
  }

  function next() {
    if (index < 0) return;
    openAt(index + 1);
  }

  function prev() {
    if (index < 0) return;
    openAt(index - 1);
  }

  // Click handling:
  // - clicking thumbnail opens
  // - clicking backdrop or × closes
  // - clicking arrows navigates
  document.addEventListener("click", function (e) {
    // open from thumbnail
    var a = e.target && e.target.closest ? e.target.closest("a.gallery-item") : null;
    if (a) {
      e.preventDefault();
      refreshItems();
      var i = items.indexOf(a);
      openAt(i >= 0 ? i : 0);
      return;
    }

    // arrows
    var p = e.target && e.target.closest ? e.target.closest(".lightbox-prev") : null;
    if (p) { e.preventDefault(); prev(); return; }

    var n = e.target && e.target.closest ? e.target.closest(".lightbox-next") : null;
    if (n) { e.preventDefault(); next(); return; }

    // close targets
    var closeTarget = e.target && e.target.closest ? e.target.closest("[data-close='1']") : null;
    if (closeTarget) { e.preventDefault(); close(); return; }
  });

  // Keyboard
  document.addEventListener("keydown", function (e) {
    if (lb.hidden) return;

    if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      next();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      prev();
    }
  });

  // Expose tiny API if you ever want it (optional)
  window.STORYHUB_LIGHTBOX = {
    openAt: openAt,
    close: close,
    next: next,
    prev: prev
  };
})();
