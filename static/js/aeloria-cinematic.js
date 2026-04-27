/* ─────────────────────────────────────────────────────────────────────────
   AELORIA — Cinematic Atmosphere
   Layers a body-level "world stage" beneath all page content. Idempotent —
   safe to load on every page, will only attach once.

   Layers it injects (matching templates/menu.html):
     · .cine-stage-deep      static dark gradient
     · .cine-stage-rays      god-ray sheets that drift
     · .cine-stage-fog       low volumetric fog
     · .cine-stage-dust      golden dust-mote canvas (animated)
     · .cine-stage-vignette  edge falloff
     · .cine-stage-grain     vellum film grain
     · .cine-stage-torch     warm halo following the cursor
     · .cine-stage-flash     rare distant lightning flicker

   Respects prefers-reduced-motion. Pauses on tab hide.
   ───────────────────────────────────────────────────────────────────────── */

(function () {
  'use strict';

  if (window.__aeloriaCinematicLoaded) return;
  window.__aeloriaCinematicLoaded = true;

  var REDUCE = !!(window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  function ready(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn, { once: true });
    } else {
      fn();
    }
  }

  ready(function () {
    document.body.classList.add('cine');

    // ── 1. Stage scaffold ────────────────────────────────────────────
    var stage = document.querySelector('.cine-stage');
    if (!stage) {
      stage = document.createElement('div');
      stage.className = 'cine-stage';
      stage.setAttribute('aria-hidden', 'true');
      stage.innerHTML =
        '<div class="cine-stage-deep"></div>' +
        '<div class="cine-stage-rays"></div>' +
        '<div class="cine-stage-fog"></div>' +
        '<canvas class="cine-stage-dust"></canvas>' +
        '<div class="cine-stage-vignette"></div>' +
        '<div class="cine-stage-grain"></div>' +
        '<div class="cine-stage-flash"></div>';
      document.body.insertBefore(stage, document.body.firstChild);
    }

    var canvas  = stage.querySelector('.cine-stage-dust');
    var flashEl = stage.querySelector('.cine-stage-flash');

    // ── 2. Resolve hero `data-bg` images ─────────────────────────────
    document.querySelectorAll('.cine-hero[data-bg]').forEach(function (hero) {
      var bg = hero.querySelector('.cine-hero-bg');
      if (!bg) return;
      var src = hero.getAttribute('data-bg');
      if (!src) return;
      bg.style.backgroundImage = "url('" + src + "')";
    });

    if (REDUCE) return;

    // ── 3. Dust motes canvas ─────────────────────────────────────────
    if (canvas && canvas.getContext) {
      var ctx  = canvas.getContext('2d');
      var dpr  = Math.min(window.devicePixelRatio || 1, 2);
      var raf  = 0;
      var motes = [];

      function spawn() {
        return {
          x: Math.random() * window.innerWidth,
          y: Math.random() * window.innerHeight,
          r: 0.4 + Math.random() * 1.7,
          vx: -0.10 + Math.random() * 0.20,
          vy: -0.04 - Math.random() * 0.10,
          life: 0,
          ttl: 600 + Math.random() * 1100,
          a: 0.05 + Math.random() * 0.34,
          hue: 36 + Math.random() * 14
        };
      }

      function resize() {
        canvas.width  = Math.max(1, Math.floor(window.innerWidth  * dpr));
        canvas.height = Math.max(1, Math.floor(window.innerHeight * dpr));
        canvas.style.width  = window.innerWidth  + 'px';
        canvas.style.height = window.innerHeight + 'px';
        var density = Math.max(50, Math.min(130,
          Math.floor(window.innerWidth * window.innerHeight / 22000)));
        motes = [];
        for (var i = 0; i < density; i++) motes.push(spawn());
      }

      function tick() {
        var w = window.innerWidth, h = window.innerHeight;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);
        for (var i = 0; i < motes.length; i++) {
          var m = motes[i];
          m.x += m.vx + Math.sin((m.life + i) * 0.012) * 0.06;
          m.y += m.vy;
          m.life++;
          if (m.life > m.ttl || m.y < -10 || m.x < -10 || m.x > w + 10) {
            motes[i] = spawn();
            motes[i].y = h + 4;
            continue;
          }
          var fade = Math.min(1, Math.min(m.life, m.ttl - m.life) / 80);
          var alpha = m.a * fade;
          var grad = ctx.createRadialGradient(m.x, m.y, 0, m.x, m.y, m.r * 4);
          grad.addColorStop(0, 'hsla(' + m.hue + ', 72%, 80%, ' + alpha + ')');
          grad.addColorStop(1, 'hsla(' + m.hue + ', 72%, 60%, 0)');
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.arc(m.x, m.y, m.r * 4, 0, Math.PI * 2);
          ctx.fill();
        }
        raf = requestAnimationFrame(tick);
      }

      window.addEventListener('resize', resize, { passive: true });
      resize();
      raf = requestAnimationFrame(tick);

      document.addEventListener('visibilitychange', function () {
        if (document.hidden) {
          if (raf) { cancelAnimationFrame(raf); raf = 0; }
        } else if (!raf) {
          raf = requestAnimationFrame(tick);
        }
      });
    }

    // ── 4. Distant lightning ─────────────────────────────────────────
    if (flashEl) {
      function fire() {
        if (document.hidden) { schedule(); return; }
        flashEl.classList.remove('is-flashing');
        // restart animation
        // eslint-disable-next-line no-unused-expressions
        flashEl.offsetWidth;
        flashEl.classList.add('is-flashing');
        schedule();
      }
      function schedule() {
        var next = 38000 + Math.random() * 80000;
        setTimeout(fire, next);
      }
      schedule();
    }
  });
})();
