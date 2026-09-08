/* =========================================================
   NAO WEB LAB - Base Script
   現時点で必要な処理のみ実装:
   - モバイル用ナビゲーションの開閉トグル
   - フッター著作権表記の年を自動更新
   ※ 不要なライブラリ・外部スクリプトは導入しない方針。
   ========================================================= */
(function () {
  "use strict";

  var toggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("primary-nav");

  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var isOpen = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(isOpen));
    });
  }

  var yearEl = document.querySelector("[data-current-year]");
  if (yearEl) {
    yearEl.textContent = String(new Date().getFullYear());
  }
})();
