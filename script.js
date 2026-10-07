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

// ----- 데이터 처리: 전처리 단계 탐색기 -----
(() => {
  const track = document.getElementById("pipeTrack");
  const panel = document.getElementById("pipePanel");
  const tabs = [...document.querySelectorAll(".pipe-tabs__btn")];
  if (!track || !panel) return;

  const SCOPE = { train: ["scope--train", "학습"], both: ["scope--both", "공통"] };

  // report/preprocess.md 의 기법 · 적용 이유 · 추천 파라미터 · 순서 근거
  const STEPS = {
    clean: [
      {
        n: 1, name: "얼굴 필터", scope: "train",
        why: "위에서 아래로 찍어 얼굴은 거의 안 나오지만, 학습용 사진을 모으는 동안 개인정보를 지키는 안전망이 필요합니다.",
        how: "OpenCV DNN(res10 SSD)으로 얼굴 신뢰도가 <code>0.5</code> 이상이면 학습 데이터에서 제외합니다.",
        order: "사진이 복사되고 가공되기 전에 지워야 다른 단계로 퍼지지 않습니다.",
      },
      {
        n: 2, name: "품질 필터", scope: "train",
        why: "쓰레기를 던지듯 보여줘 흐린 사진이 생기고, 오후 2~4시 창가 역광에 노출이 날아갑니다.",
        how: "선명도(Laplacian 분산) <code>100</code> 미만, 밝기 평균 <code>40~220</code> 밖, 하얗게 날아간 픽셀 <code>5%</code> 초과면 제외합니다.",
        order: "흐린 사진을 먼저 버려야 비슷한 사진 묶음에서 선명한 사진이 남습니다.",
      },
      {
        n: 3, name: "중복 제거", scope: "train",
        why: "센서가 감지할 때마다 연속 촬영해서 거의 같은 사진이 여러 장 생깁니다.",
        how: "pHash 해밍 거리 <code>5</code> 이하이면 중복으로 보고, 더 선명한 한 장만 남깁니다.",
        order: "나누기 전에 해야 같은 사진이 학습용과 시험용에 나뉘어 점수가 부풀려지지 않습니다.",
      },
      {
        n: 4, name: "라벨 검수", scope: "train",
        why: "매점 플라스틱 컵, 빨대 꽂힌 페트병, 우유팩처럼 어느 칸인지 헷갈리는 쓰레기가 많습니다.",
        how: "애매한 사진은 따로 모아 <code>2인</code> 교차 검수하고, 같은 사진이 다른 칸에 있으면 자동으로 표시합니다.",
        order: "정답이 확정돼야 칸별 비율을 맞춰 데이터를 나눌 수 있습니다.",
      },
      {
        n: 5, name: "세션 단위 분할", scope: "train",
        why: "흐린 날 오전과 맑은 날 오후의 밝기 차이가 커서, 같은 시간대 사진이 섞이면 실제보다 점수가 높게 나옵니다.",
        how: "날짜·시간대 묶음 단위로 학습 <code>70</code> / 검증 <code>15</code> / 시험 <code>15</code>로 나누고, 공개 데이터셋은 학습에만 씁니다.",
        order: "증강과 가중치는 이 뒤에 학습용 데이터에만 적용해야 성능을 정직하게 잴 수 있습니다.",
      },
    ],
    input: [
      {
        n: 6, name: "ROI 크롭", scope: "both",
        why: "화면 가장자리에 쓰레기통 본체가 함께 찍히고, 실제로 필요한 건 회색 배경판 위뿐입니다.",
        how: "1280×720 화면에서 배경판 영역 <code>720×720</code>을 고정 좌표로 잘라냅니다.",
        order: "원본에서 먼저 잘라야 크기를 줄일 때 잃는 정보가 가장 적습니다.",
      },
      {
        n: 7, name: "리사이즈", scope: "both",
        why: "Raspberry Pi 4에서 2초 안에 안내를 끝내려면 모델 입력이 작아야 합니다.",
        how: "<code>224×224</code>로 줄이고, 축소에 유리한 INTER_AREA 방식을 씁니다.",
        order: "필요한 영역을 자른 다음에 줄입니다.",
      },
      {
        n: 8, name: "대비 보정 (CLAHE)", scope: "both",
        why: "형광등과 창문 빛이 섞여, 조명을 고정해도 밝기 차이가 조금 남을 수 있습니다.",
        how: "밝기 채널에만 <code>clipLimit 2.0</code>, <code>8×8</code>로 적용합니다. 켠 버전과 끈 버전을 둘 다 학습해 더 정확한 쪽을 씁니다.",
        order: "증강 전에 해야 합니다. 뒤에 하면 증강으로 만든 밝기 변화를 도로 지워버립니다.",
      },
      {
        n: 9, name: "데이터 증강", scope: "train",
        why: "시간대별 조명, 찌그러진 병과 캔, 손 가림, 빠른 동작, 제각각인 놓는 방향을 견디게 합니다.",
        how: "밝기·대비 <code>±30%</code>, 회전 <code>90°</code> 단위와 <code>±30°</code>, 모션 블러, 사진의 <code>9~15%</code> 가리기 등을 무작위로 섞습니다.",
        order: "학습용 데이터에만, 정규화 전 0~255 이미지에 적용합니다.",
      },
      {
        n: 10, name: "클래스 균형", scope: "train",
        why: "캔이 전체의 15%로 가장 적어 캔만 정확도 기준(85%)을 못 넘길 위험이 큽니다.",
        how: "적은 칸일수록 학습 가중치를 크게 주고, 찌그러진 캔을 포함해 실물 <code>300장</code> 이상을 더 찍습니다.",
        order: "학습용 데이터에만 적용합니다.",
      },
      {
        n: 11, name: "정규화", scope: "both",
        why: "사전학습된 MobileNetV3가 기대하는 입력 범위와 맞춰야 합니다.",
        how: "모델 안에 전처리 층이 있어 <code>0~255</code> 값을 그대로 넣습니다. 따로 255로 나누면 이중 정규화가 됩니다.",
        order: "맨 마지막입니다. 학습과 실시간 추론이 같은 코드로 처리해 입력이 어긋나지 않습니다.",
      },
    ],
  };

  let group = "clean";
  let current = STEPS.clean[0];

  const scopeChip = (s) => `<span class="scope ${SCOPE[s][0]}">${SCOPE[s][1]}</span>`;

  const renderDetail = (step) => {
    panel.innerHTML = `
      <div class="pipe-detail__head"><h3>${step.n}. ${step.name}</h3>${scopeChip(step.scope)}</div>
      <dl class="pipe-detail__grid">
        <div><dt>왜 필요한가</dt><dd>${step.why}</dd></div>
        <div><dt>설정값</dt><dd>${step.how}</dd></div>
        <div><dt>이 순서인 이유</dt><dd>${step.order}</dd></div>
      </dl>`;
  };

  const select = (step) => {
    current = step;
    track.querySelectorAll(".pipe-step").forEach((b) => {
      if (Number(b.dataset.n) === step.n) b.setAttribute("aria-current", "step");
      else b.removeAttribute("aria-current");
    });
    panel.classList.add("is-swapping");
    setTimeout(() => {
      renderDetail(step);
      panel.classList.remove("is-swapping");
    }, 160);
  };

  const renderTrack = () => {
    const steps = STEPS[group];
    track.style.setProperty("--n", steps.length);
    track.innerHTML = steps
      .map(
        (s) => `<li><button type="button" class="pipe-step" data-n="${s.n}">
          <span class="pipe-step__num">${s.n}</span>
          <span class="pipe-step__name">${s.name}</span>
          ${scopeChip(s.scope)}
        </button></li>`
      )
      .join("");
    track.querySelectorAll(".pipe-step").forEach((btn) =>
      btn.addEventListener("click", () => select(steps.find((s) => s.n === Number(btn.dataset.n))))
    );
  };

  tabs.forEach((tab) =>
    tab.addEventListener("click", () => {
      if (tab.dataset.group === group) return;
      group = tab.dataset.group;
      tabs.forEach((t) => {
        const on = t === tab;
        t.classList.toggle("is-active", on);
        t.setAttribute("aria-selected", String(on));
      });
      renderTrack();
      select(STEPS[group][0]);
    })
  );

  renderTrack();
  select(current);
})();
