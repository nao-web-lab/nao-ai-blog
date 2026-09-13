(function () {
  'use strict';

  // FAQ accordion
  var faqButtons = document.querySelectorAll('.faq-question');
  faqButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var expanded = btn.getAttribute('aria-expanded') === 'true';
      var panel = document.getElementById(btn.getAttribute('aria-controls'));

      btn.setAttribute('aria-expanded', String(!expanded));

      if (panel) {
        if (expanded) {
          panel.style.maxHeight = '0px';
        } else {
          panel.style.maxHeight = panel.scrollHeight + 'px';
        }
      }
    });
  });

  // Scroll reveal
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var revealEls = document.querySelectorAll('.reveal');

  if (reduceMotion || !('IntersectionObserver' in window)) {
    revealEls.forEach(function (el) {
      el.classList.add('is-visible');
    });
  } else {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15, rootMargin: '0px 0px -40px 0px' }
    );

    revealEls.forEach(function (el) {
      observer.observe(el);
    });
  }

  // Sticky CTA: hide once final CTA section is in view
  var stickyCta = document.querySelector('.sticky-cta');
  var finalCtaSection = document.getElementById('final-cta');

  if (stickyCta && finalCtaSection && 'IntersectionObserver' in window) {
    var ctaObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          stickyCta.classList.toggle('is-hidden', entry.isIntersecting);
        });
      },
      { threshold: 0.2 }
    );
    ctaObserver.observe(finalCtaSection);
  }
})();
