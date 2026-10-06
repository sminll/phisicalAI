// EcoSort AI — landing page interactions
(() => {
  const header = document.getElementById("header");
  const nav = document.getElementById("nav");
  const toggle = document.getElementById("menuToggle");
  const toTop = document.getElementById("toTop");
  const navLinks = [...document.querySelectorAll(".nav__link")];

  /* ----- Header shadow & back-to-top button ----- */
  const onScroll = () => {
    const y = window.scrollY;
    header.classList.toggle("is-scrolled", y > 10);
    toTop.classList.toggle("is-shown", y > 600);
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  toTop.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));

  /* ----- Mobile menu ----- */
  const setMenu = (open) => {
    nav.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "메뉴 닫기" : "메뉴 열기");
  };
  toggle.addEventListener("click", () => setMenu(!nav.classList.contains("is-open")));
  navLinks.forEach((link) => link.addEventListener("click", () => setMenu(false)));
  document.addEventListener("keydown", (e) => e.key === "Escape" && setMenu(false));

  /* ----- Active menu highlight (scroll spy) ----- */
  const sections = navLinks
    .map((link) => document.querySelector(link.getAttribute("href")))
    .filter(Boolean);

  const spy = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        navLinks.forEach((link) =>
          link.classList.toggle("is-active", link.getAttribute("href") === `#${entry.target.id}`)
        );
      });
    },
    { rootMargin: "-45% 0px -50% 0px" }
  );
  sections.forEach((s) => spy.observe(s));

  /* ----- Count-up numbers ----- */
  const countUp = (el) => {
    const target = Number(el.dataset.target);
    const duration = 1200;
    const start = performance.now();
    const tick = (now) => {
      const p = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(target * eased);
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };

  /* ----- Reveal on scroll + KPI animations ----- */
  const revealer = new IntersectionObserver(
    (entries, obs) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const el = entry.target;
        el.classList.add("is-visible");
        el.querySelectorAll(".count").forEach(countUp);
        el.querySelectorAll("[data-fill]").forEach((bar) => {
          bar.style.width = `${bar.dataset.fill}%`;
        });
        obs.unobserve(el);
      });
    },
    { threshold: 0.15 }
  );

  // Stagger cards inside the same grid
  document.querySelectorAll(".reveal").forEach((el) => {
    const siblings = [...el.parentElement.children].filter((c) => c.classList.contains("reveal"));
    const index = siblings.indexOf(el);
    if (index > 0) el.style.transitionDelay = `${Math.min(index, 5) * 80}ms`;
    revealer.observe(el);
  });

  /* ----- Hero demo: simulate AI classification ----- */
  const samples = [
    { bin: "pet", icon: "🧴", label: "PET", conf: 96, color: "var(--pet)" },
    { bin: "can", icon: "🥫", label: "CAN", conf: 93, color: "var(--can)" },
    { bin: "gen", icon: "🧻", label: "GENERAL", conf: 88, color: "var(--gen)" },
  ];
  const bbox = document.getElementById("bbox");
  const bboxTag = document.getElementById("bboxTag");
  const bboxIcon = document.getElementById("bboxIcon");
  const confFill = document.getElementById("confFill");
  const confValue = document.getElementById("confValue");
  const bins = document.querySelectorAll(".bin");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let i = 0;
  const showSample = (s) => {
    bbox.style.setProperty("--c", s.color);
    bboxIcon.textContent = s.icon;
    bboxTag.textContent = `${s.label} ${s.conf}%`;
    confFill.style.width = `${s.conf}%`;
    confValue.textContent = `${s.conf}%`;
    bins.forEach((b) => b.classList.toggle("is-active", b.dataset.bin === s.bin));
  };

  const cycle = () => {
    // "scanning" phase
    bbox.classList.add("is-scanning");
    bboxTag.textContent = "분석 중…";
    confFill.style.width = "0%";
    confValue.textContent = "—";
    bins.forEach((b) => b.classList.remove("is-active"));

    setTimeout(() => {
      bbox.classList.remove("is-scanning");
      showSample(samples[i]);
      i = (i + 1) % samples.length;
    }, 900);
  };

  showSample(samples[0]);
  i = 1;
  if (!reduceMotion) setInterval(cycle, 3600);
})();
