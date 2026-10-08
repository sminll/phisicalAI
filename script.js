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
        why: "Raspberry Pi 4에서 2초 안에 안내를 끝내려면 모델 입력이 작아야 합니다. 쓰레기가 화면에 크게 찍혀 작게 줄여도 충분합니다.",
        how: "YOLO가 비율을 유지한 채 회색 여백을 붙여 <code>320×320</code>으로 맞춥니다(letterbox). 직접 줄이지 않습니다.",
        order: "필요한 영역을 자른 다음에 줄입니다. 추론도 같은 YOLO 방식으로 처리해야 입력이 어긋나지 않습니다.",
      },
      {
        n: 8, name: "대비 보정 (CLAHE)", scope: "both",
        why: "형광등과 창문 빛이 섞여, 조명을 고정해도 밝기 차이가 조금 남을 수 있습니다.",
        how: "밝기 채널에만 <code>clipLimit 2.0</code>, <code>8×8</code>로 적용합니다. 켠 버전과 끈 버전을 둘 다 학습해 더 정확한 쪽을 씁니다.",
        order: "증강 전에 해야 합니다. 뒤에 하면 증강으로 만든 밝기 변화를 도로 지워버립니다.",
      },
      {
        n: 9, name: "데이터 증강", scope: "train",
        why: "시간대별 조명, 찌그러진 병과 캔, 제각각인 놓는 방향, 여러 개를 함께 든 상황을 견디게 합니다.",
        how: "YOLO 학습 설정으로 색 변화 <code>0.3</code>, 회전 <code>±30°</code>, 상하·좌우 뒤집기, 크기 <code>±30%</code>, 사진 4장을 이어 붙이는 모자이크를 적용합니다.",
        order: "학습용 데이터에만, 학습 중에 매번 무작위로 적용합니다. 모자이크는 마지막 10에폭에서 끕니다.",
      },
      {
        n: 10, name: "클래스 균형", scope: "train",
        why: "캔이 전체의 15%로 가장 적어 캔만 정확도 기준(85%)을 못 넘길 위험이 큽니다.",
        how: "YOLO 검출 학습에는 클래스 가중치 옵션이 없어, 찌그러진 캔을 포함한 실물 사진을 <code>300장</code> 이상 더 찍어 해결합니다.",
        order: "학습용 데이터에만 적용합니다.",
      },
      {
        n: 11, name: "정규화", scope: "both",
        why: "사전학습된 YOLO26n이 기대하는 입력 범위와 맞춰야 합니다.",
        how: "YOLO가 내부에서 픽셀 값을 <code>0~1</code>로 나눕니다. 직접 나누면 이중 정규화가 되고, 색 순서(BGR)도 YOLO가 알아서 처리합니다.",
        order: "맨 마지막입니다. 학습과 실시간 추론이 같은 YOLO 처리를 거쳐 입력이 어긋나지 않습니다.",
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

// ----- AI 모델: 크기 5단계 비교 -----
(() => {
  const tabs = document.getElementById("sizeTabs");
  const body = document.getElementById("sizeBody");
  if (!tabs || !body) return;

  // 속도·정확도는 5단계 상대 비교 (실제 수치 아님)
  const SIZES = [
    { k: "n", name: "nano", speed: 5, acc: 1, use: "Raspberry Pi, 스마트폰처럼 GPU가 없거나 약한 소형 장치", ours: true,
      note: "이 제품의 기본 모델입니다. 쓰레기가 크게 찍히고 클래스가 3개뿐이라 nano로도 충분할 것으로 봅니다." },
    { k: "s", name: "small", speed: 4, acc: 2, use: "nano의 정확도가 부족한 소형 장치, 노트북 CPU",
      note: "nano가 정확도 기준을 못 넘으면 비교할 후보입니다 (비교 실험 C)." },
    { k: "m", name: "medium", speed: 3, acc: 3, use: "Jetson 같은 GPU 탑재 엣지 장치, 일반 PC GPU",
      note: "정확도와 속도의 균형형입니다. 라즈베리파이 CPU에서는 2초 목표를 맞추기 어렵습니다." },
    { k: "l", name: "large", speed: 2, acc: 4, use: "서버 GPU에서 정확도가 중요한 작업",
      note: "이 제품에는 과합니다." },
    { k: "x", name: "extra large", speed: 1, acc: 5, use: "서버 GPU에서 최고 정확도가 필요할 때",
      note: "이 제품에는 과합니다." },
  ];

  const dots = (n) => Array.from({ length: 5 }, (_, i) => `<i class="${i < n ? "on" : ""}"></i>`).join("");

  const show = (sz) => {
    tabs.querySelectorAll(".sizes__btn").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.k === sz.k)));
    body.classList.add("is-swapping");
    setTimeout(() => {
      body.innerHTML = `
        <p class="sizes__name">yolo26${sz.k}<small>${sz.name}</small></p>
        <p class="sizes__use">${sz.use}</p>
        <div class="meter"><span>속도</span><span class="meter__dots">${dots(sz.speed)}</span></div>
        <div class="meter meter--acc"><span>정확도</span><span class="meter__dots">${dots(sz.acc)}</span></div>
        <p>${sz.note}</p>`;
      body.classList.remove("is-swapping");
    }, 140);
  };

  tabs.innerHTML = SIZES.map(
    (sz) => `<button type="button" class="sizes__btn${sz.ours ? " is-ours" : ""}" data-k="${sz.k}" aria-pressed="false" aria-label="${sz.name}">${sz.k}</button>`
  ).join("");
  tabs.querySelectorAll(".sizes__btn").forEach((b) =>
    b.addEventListener("click", () => show(SIZES.find((sz) => sz.k === b.dataset.k)))
  );
  show(SIZES[0]);
})();
