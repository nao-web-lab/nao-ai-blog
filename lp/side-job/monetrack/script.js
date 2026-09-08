/* =========================================================
   LPページ専用スクリプト（副業ジャンル：Monetrack紹介ページ）
   実装内容:
   - FAQ（details/summary）のアコーディオン制御
     （1つ開いたら他を自動的に閉じる）
   - フッター著作権表記の年を自動更新
   外部ライブラリは使用していない。
   ========================================================= */
(function () {
  "use strict";

  var faqItems = document.querySelectorAll(".faq-item");

  faqItems.forEach(function (item) {
    item.addEventListener("toggle", function () {
      if (!item.open) {
        return;
      }
      faqItems.forEach(function (other) {
        if (other !== item) {
          other.open = false;
        }
      });
    });
  });

  var yearEl = document.querySelector("[data-current-year]");
  if (yearEl) {
    yearEl.textContent = String(new Date().getFullYear());
  }
})();
