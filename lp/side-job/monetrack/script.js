(function () {
  "use strict";

  /* ---- FAQ accordion ---- */
  var triggers = document.querySelectorAll(".accordion-trigger");
  triggers.forEach(function (btn) {
    var panel = btn.nextElementSibling;
    panel.style.maxHeight = "0px";
    btn.addEventListener("click", function () {
      var expanded = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", String(!expanded));
      panel.style.maxHeight = expanded ? "0px" : panel.scrollHeight + "px";
    });
  });

  /* ---- Scroll reveal ---- */
  var revealTargets = document.querySelectorAll(
    ".section .card, .section .section-title, .stat-card, .flow-list li, .empathy-lead"
  );
  revealTargets.forEach(function (el) {
    el.classList.add("reveal");
  });

  if ("IntersectionObserver" in window) {
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
    revealTargets.forEach(function (el) {
      observer.observe(el);
    });
  } else {
    revealTargets.forEach(function (el) {
      el.classList.add("is-visible");
    });
  }

  /* ---- Sticky mobile CTA: hide when final CTA is visible ---- */
  var finalCta = document.querySelector(".final-cta");
  var stickyCta = document.querySelector(".sticky-cta");
  if (finalCta && stickyCta && "IntersectionObserver" in window) {
    var ctaObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          stickyCta.style.opacity = entry.isIntersecting ? "0" : "1";
          stickyCta.style.pointerEvents = entry.isIntersecting ? "none" : "auto";
        });
      },
      { threshold: 0.2 }
    );
    ctaObserver.observe(finalCta);
  }

  /* ---- フッター著作権表記の年を自動更新 ---- */
  var yearEl = document.querySelector("[data-current-year]");
  if (yearEl) {
    yearEl.textContent = String(new Date().getFullYear());
  }
})();
