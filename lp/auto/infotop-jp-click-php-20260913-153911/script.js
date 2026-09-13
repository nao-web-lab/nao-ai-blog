(function () {
  "use strict";

  var prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---- FAQ accordion ---- */
  var triggers = document.querySelectorAll(".accordion-trigger");
  triggers.forEach(function (trigger) {
    var panel = trigger.nextElementSibling;
    if (!panel) return;
    panel.style.maxHeight = "0px";
    trigger.addEventListener("click", function () {
      var expanded = trigger.getAttribute("aria-expanded") === "true";
      trigger.setAttribute("aria-expanded", String(!expanded));
      panel.style.maxHeight = expanded ? "0px" : panel.scrollHeight + "px";
    });
  });

  /* ---- Scroll reveal ---- */
  var revealEls = document.querySelectorAll(".reveal");
  if (prefersReducedMotion || !("IntersectionObserver" in window)) {
    revealEls.forEach(function (el) {
      el.classList.add("is-visible");
    });
  } else {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15 }
    );
    revealEls.forEach(function (el) {
      observer.observe(el);
    });
  }

  /* ---- Sticky CTA hides once final CTA section is visible ---- */
  var stickyCta = document.getElementById("stickyCta");
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
