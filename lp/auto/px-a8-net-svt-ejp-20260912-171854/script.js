(function () {
  "use strict";

  var prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- FAQ アコーディオン ---------- */
  var faqButtons = document.querySelectorAll(".faq-question");
  faqButtons.forEach(function (btn) {
    var panel = document.getElementById(btn.getAttribute("aria-controls"));
    if (!panel) return;
    btn.addEventListener("click", function () {
      var expanded = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", String(!expanded));
      if (expanded) {
        panel.style.maxHeight = null;
      } else {
        panel.style.maxHeight = panel.scrollHeight + "px";
      }
    });
  });

  /* ---------- スクロールリベール ---------- */
  var revealEls = document.querySelectorAll(".reveal");
  if (prefersReducedMotion || !("IntersectionObserver" in window)) {
    revealEls.forEach(function (el) { el.classList.add("is-visible"); });
  } else {
    var revealObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            revealObserver.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15 }
    );
    revealEls.forEach(function (el) { revealObserver.observe(el); });
  }

  /* ---------- スティッキーCTAの表示/非表示 ---------- */
  var stickyCta = document.querySelector(".sticky-cta");
  var finalCta = document.querySelector(".final-cta");
  if (stickyCta && finalCta && "IntersectionObserver" in window) {
    var stickyObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          stickyCta.classList.toggle("is-hidden", entry.isIntersecting);
        });
      },
      { threshold: 0.2 }
    );
    stickyObserver.observe(finalCta);
  }
})();
