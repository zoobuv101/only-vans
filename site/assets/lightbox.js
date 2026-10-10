/* Lightbox for adventure pages: tap a photo to open it full size, then swipe or use the arrows
   (or the keyboard ← → and Esc) to move through the post's photos. No dependencies. */
(function () {
  var links = Array.prototype.slice.call(document.querySelectorAll(".photos a"));
  var cover = document.querySelector("figure.wide img");
  var srcs = links.map(function (a) { return a.getAttribute("href"); });
  if (!srcs.length && cover) srcs = [cover.getAttribute("src")];
  if (!srcs.length) return;

  var box = document.createElement("div");
  box.className = "lb"; box.hidden = true;
  box.setAttribute("role", "dialog"); box.setAttribute("aria-modal", "true"); box.setAttribute("aria-label", "Photo viewer");
  box.innerHTML = '<img class="lb__img" alt="">' +
    '<button class="lb__btn lb__prev" type="button" aria-label="Previous photo">&#8249;</button>' +
    '<button class="lb__btn lb__next" type="button" aria-label="Next photo">&#8250;</button>' +
    '<button class="lb__btn lb__close" type="button" aria-label="Close">&times;</button>' +
    '<p class="lb__count" aria-live="polite"></p>';
  document.body.appendChild(box);
  var img = box.querySelector(".lb__img"), count = box.querySelector(".lb__count");
  var i = 0, last = null;

  function show(n) {
    i = (n + srcs.length) % srcs.length;
    img.src = srcs[i];
    count.textContent = (i + 1) + " / " + srcs.length;
    var many = srcs.length > 1;
    box.querySelector(".lb__prev").hidden = !many; box.querySelector(".lb__next").hidden = !many;
  }
  function open(n) { last = document.activeElement; show(n); box.hidden = false; document.body.style.overflow = "hidden"; box.querySelector(".lb__close").focus(); }
  function close() { box.hidden = true; document.body.style.overflow = ""; if (last) last.focus(); }

  links.forEach(function (a, n) { a.addEventListener("click", function (e) { e.preventDefault(); open(n); }); });
  if (cover) {
    cover.style.cursor = "zoom-in";
    cover.addEventListener("click", function () {
      var at = srcs.indexOf(cover.getAttribute("src")); open(at < 0 ? 0 : at);
    });
  }
  box.querySelector(".lb__prev").addEventListener("click", function () { show(i - 1); });
  box.querySelector(".lb__next").addEventListener("click", function () { show(i + 1); });
  box.querySelector(".lb__close").addEventListener("click", close);
  box.addEventListener("click", function (e) { if (e.target === box) close(); });
  document.addEventListener("keydown", function (e) {
    if (box.hidden) return;
    if (e.key === "Escape") close();
    else if (e.key === "ArrowLeft") show(i - 1);
    else if (e.key === "ArrowRight") show(i + 1);
  });
  var x0 = null, y0 = null;
  box.addEventListener("touchstart", function (e) { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
  box.addEventListener("touchend", function (e) {
    if (x0 === null) return;
    var dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
    if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) show(dx < 0 ? i + 1 : i - 1);
    x0 = null;
  });
})();
