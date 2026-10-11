/* Slide-up-and-fade as blocks scroll into view (same feel as astrocentral.co.uk:
   0.65s ease, 0.1s delay). The <head> adds .rv only when motion is welcome; if this
   file never runs, a 2.5s fallback there removes .rv so nothing stays hidden. */
(function () {
  var root = document.documentElement;
  if (!root.classList.contains("rv")) return;
  window.__rv = true;
  var els = document.querySelectorAll(
    ".hero__text > *, main.page > *:not(.trips):not(.photos):not(script), .trips > li, .photos > a");
  var io = new IntersectionObserver(function (entries) {
    var n = 0;
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      e.target.style.transitionDelay = (0.1 + Math.min(n++, 6) * 0.08) + "s";
      e.target.classList.add("rv-in");
      io.unobserve(e.target);
    });
  }, { rootMargin: "0px 0px -8% 0px" });
  els.forEach(function (el) { el.classList.add("rv-el"); io.observe(el); });
})();
