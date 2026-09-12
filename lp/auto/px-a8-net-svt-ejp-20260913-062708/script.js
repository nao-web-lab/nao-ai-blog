(function () {
  "use strict";

  var prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---- FAQ accordion ---- */
  var triggers = document.querySelectorAll(".accordion-trigger");
  triggers.forEach(function (trigger) {
    var panel = trigger.nextElementSibling;
    trigger.addEventListener("click", function () {
      var isOpen = trigger.getAttribute("aria-expanded") === "true";
      trigger.setAttribute("aria-expanded", String(!isOpen));
      panel.style.maxHeight = isOpen ? null : panel.scrollHeight + "px";
    });
  });

  /* ---- Sticky mobile CTA: hide once final CTA is in view ---- */
  var stickyCta = document.getElementById("stickyCta");
  var finalCta = document.querySelector(".final-cta");

  if (stickyCta && finalCta && "IntersectionObserver" in window) {
    var ctaObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          stickyCta.classList.toggle("is-hidden", entry.isIntersecting);
        });
      },
      { threshold: 0.15 }
    );
    ctaObserver.observe(finalCta);
  }

  /* ---- Scroll reveal ---- */
  var revealTargets = document.querySelectorAll(
    ".pain-card, .feature-card, .price-card, .flow-list li, .accordion-item, .banner-grid, .col-visual"
  );

  if (prefersReducedMotion || !("IntersectionObserver" in window)) {
    revealTargets.forEach(function (el) {
      el.classList.add("reveal", "is-visible");
    });
  } else {
    var revealObserver = new IntersectionObserver(
      function (entries, observer) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    revealTargets.forEach(function (el) {
      el.classList.add("reveal");
      revealObserver.observe(el);
    });
  }
})();
