(function () {
  "use strict";

  /* ---- FAQ accordion ---- */
  var faqItems = document.querySelectorAll(".faq-item");
  faqItems.forEach(function (item) {
    var button = item.querySelector(".faq-question");
    var answer = item.querySelector(".faq-answer");
    if (!button || !answer) return;

    button.addEventListener("click", function () {
      var isOpen = button.getAttribute("aria-expanded") === "true";

      faqItems.forEach(function (other) {
        if (other === item) return;
        var otherButton = other.querySelector(".faq-question");
        var otherAnswer = other.querySelector(".faq-answer");
        if (otherButton) otherButton.setAttribute("aria-expanded", "false");
        if (otherAnswer) otherAnswer.style.maxHeight = "";
      });

      button.setAttribute("aria-expanded", String(!isOpen));
      answer.style.maxHeight = isOpen ? "" : answer.scrollHeight + "px";
    });
  });

  /* ---- Scroll reveal ---- */
  var revealEls = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && revealEls.length) {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    revealEls.forEach(function (el) {
      observer.observe(el);
    });
  } else {
    revealEls.forEach(function (el) {
      el.classList.add("is-visible");
    });
  }

  /* ---- Sticky mobile CTA hides once final CTA is in view ---- */
  var stickyCta = document.getElementById("stickyCta");
  var finalCta = document.querySelector(".section-final-cta");
  if (stickyCta && finalCta && "IntersectionObserver" in window) {
    var ctaObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          stickyCta.classList.toggle("is-hidden", entry.isIntersecting);
        });
      },
      { threshold: 0.05 }
    );
    ctaObserver.observe(finalCta);
  }
})();
