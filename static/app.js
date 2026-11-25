document.addEventListener("submit", function (e) {
  var msg = e.target.dataset.confirm;
  if (msg && !window.confirm(msg)) e.preventDefault();
});

(function () {
  var container = document.querySelector(".snowfall");
  if (!container) return;

  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  var timer = null;
  var maxFlakes = 32;

  function addFlake(initial) {
    if (container.childElementCount >= maxFlakes) return;

    var flake = document.createElement("span");
    var duration = 9 + Math.random() * 7;
    flake.className = "snowflake";
    flake.style.setProperty("--flake-x", Math.random() * 100 + "%");
    flake.style.setProperty("--flake-size", 4 + Math.random() * 4 + "px");
    flake.style.setProperty("--flake-drift", (Math.random() * 60 - 30) + "px");
    flake.style.setProperty("--flake-duration", duration + "s");
    flake.style.setProperty("--flake-delay", (initial ? -Math.random() * duration : 0) + "s");
    flake.addEventListener("animationend", function () { flake.remove(); }, { once: true });
    container.appendChild(flake);
  }

  function updateSnowfall() {
    if (timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
    container.replaceChildren();
    if (document.hidden || reducedMotion.matches) return;

    for (var i = 0; i < 12; i++) addFlake(true);
    timer = window.setInterval(function () { addFlake(false); }, 600);
  }

  document.addEventListener("visibilitychange", updateSnowfall);
  reducedMotion.addEventListener("change", updateSnowfall);
  updateSnowfall();
})();
