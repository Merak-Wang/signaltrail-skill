(() => {
  document.documentElement.classList.add("js");
  if (new URLSearchParams(location.search).get("embed") === "1") {
    document.documentElement.classList.add("embedded");
  }
  const slides = [...document.querySelectorAll(".slide")];
  const toc = [...document.querySelectorAll(".toc-item")];
  const current = document.querySelector("[data-current]");
  const nextTitle = document.querySelector("[data-next-title]");
  const menu = document.querySelector("[data-menu]");
  const contents = document.querySelector(".contents#contents");
  const closeMenu = contents?.querySelector("[data-close-menu]");
  const scrim = document.querySelector("[data-scrim]");
  let index = Math.max(0, slides.findIndex((slide) => slide.classList.contains("active")));
  let busy = false;
  let menuReturnFocus;
  let menuBackground = [];
  const viewer = document.querySelector(".image-viewer");
  const viewerImage = viewer.querySelector("[data-viewer-image]");
  const galleries = new Map();
  let viewedGallery;
  let imageReturnFocus;

  function updateViewer() {
    const state = galleries.get(viewedGallery);
    const figure = state.figures[state.current()];
    const sourceImage = figure.querySelector("img");
    viewerImage.src = sourceImage.currentSrc || sourceImage.src;
    viewerImage.alt = sourceImage.alt;
    viewer.querySelector("[data-viewer-caption]").textContent = figure.querySelector("figcaption")?.textContent || "";
    viewer.querySelector("[data-viewer-count]").textContent = `${state.current() + 1} / ${state.figures.length}`;
    const original = viewer.querySelector("[data-viewer-original]");
    original.href = figure.dataset.original || sourceImage.src;
    viewer.querySelectorAll("[data-viewer-prev], [data-viewer-next]").forEach((button) => {
      button.disabled = state.figures.length < 2;
    });
    updateResolution();
    viewer.querySelector(".viewer-canvas").scrollTo(0, 0);
  }

  function updateResolution() {
    viewer.querySelector("[data-viewer-resolution]").textContent = viewerImage.complete && viewerImage.naturalWidth
      ? `${viewerImage.naturalWidth} × ${viewerImage.naturalHeight}` : "";
  }

  function moveViewer(direction) {
    const state = galleries.get(viewedGallery);
    state.select(state.current() + direction);
  }

  viewerImage.addEventListener("load", updateResolution);
  viewerImage.addEventListener("error", updateResolution);
  viewer.querySelector("[data-viewer-prev]").addEventListener("click", () => moveViewer(-1));
  viewer.querySelector("[data-viewer-next]").addEventListener("click", () => moveViewer(1));
  viewer.querySelector("[data-close-image]").addEventListener("click", () => viewer.close());
  viewer.querySelector("[data-viewer-zoom]").addEventListener("click", (event) => {
    const zoomed = viewer.classList.toggle("zoomed");
    event.currentTarget.setAttribute("aria-pressed", String(zoomed));
  });
  function notifyViewer(open) {
    if (document.documentElement.classList.contains("embedded")) {
      parent.postMessage({type: "signaltrail-image-viewer", open}, "*");
    }
  }
  viewer.addEventListener("close", () => {
    notifyViewer(false);
    imageReturnFocus?.focus();
  });
  viewer.addEventListener("click", (event) => { if (event.target === viewer) viewer.close(); });

  function setMenu(open) {
    if (!contents) return;
    contents.classList.toggle("is-open", open);
    document.body.classList.toggle("contents-open", open);
    menu?.setAttribute("aria-expanded", String(open));
    if (open) {
      menuReturnFocus = document.activeElement;
      menuBackground = [...document.querySelectorAll(".stage, .masthead, .controls")]
        .filter((node) => !contents.contains(node))
        .map((node) => [node, node.inert]);
      menuBackground.forEach(([node]) => { node.inert = true; });
      closeMenu?.focus();
    } else if (menuReturnFocus) {
      menuBackground.forEach(([node, wasInert]) => { node.inert = wasInert; });
      menuBackground = [];
      menuReturnFocus.focus();
      menuReturnFocus = null;
    }
  }

  function updateChrome() {
    if (current) current.textContent = String(slides.length ? index + 1 : 0).padStart(2, "0");
    document.querySelectorAll("[data-prev], [data-next]").forEach((button) => {
      button.disabled = slides.length < 2;
    });
    if (!slides.length) {
      if (nextTitle) nextTitle.textContent = "";
      document.documentElement.style.setProperty("--progress", "0%");
      return;
    }
    if (nextTitle) nextTitle.textContent = slides[(index + 1) % slides.length]?.querySelector("h2")?.textContent || "";
    document.documentElement.style.setProperty("--progress", `${((index + 1) / slides.length) * 100}%`);
    [slides[index], slides[(index + 1) % slides.length]].forEach((slide) => {
      slide.querySelector("figure.active img")?.setAttribute("loading", "eager");
    });
  }

  function show(next) {
    if (!slides.length || busy) return;
    next = (next + slides.length) % slides.length;
    if (next === index) return;
    busy = true;
    document.documentElement.style.setProperty("--direction", next > index ? "1" : "-1");
    const old = slides[index];
    const target = slides[next];
    old.inert = true;
    old.classList.remove("active");
    old.classList.add("leaving");
    target.inert = false;
    target.classList.add("active");
    target.setAttribute("aria-hidden", "false");
    old.setAttribute("aria-hidden", "true");
    toc[index]?.classList.remove("active");
    toc[next]?.classList.add("active");
    index = next;
    updateChrome();
    setTimeout(() => {
      old.classList.remove("leaving");
      busy = false;
    }, matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 340);
    window.scrollTo({ top: 0, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }

  menu?.addEventListener("click", () => setMenu(true));
  closeMenu?.addEventListener("click", () => setMenu(false));
  scrim?.addEventListener("click", () => setMenu(false));
  document.querySelector("[data-prev]")?.addEventListener("click", () => show(index - 1));
  document.querySelector("[data-next]")?.addEventListener("click", () => show(index + 1));
  toc.forEach((button) => button.addEventListener("click", () => {
    show(Number(button.dataset.go));
    setMenu(false);
  }));
  document.addEventListener("keydown", (event) => {
    if (viewer.open) {
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        moveViewer(event.key === "ArrowRight" ? 1 : -1);
      }
      return;
    }
    if (event.key === "Escape" && contents?.classList.contains("is-open")) {
      setMenu(false);
      return;
    }
    if (contents?.classList.contains("is-open")) {
      if (event.key === "Tab") {
        const focusable = [...contents.querySelectorAll("button, a[href], [tabindex]:not([tabindex='-1'])")]
          .filter((node) => !node.disabled && !node.hidden);
        if (focusable.length) {
          const first = focusable[0];
          const last = focusable[focusable.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }
      }
      return;
    }
    const focusedGallery = event.target.closest("[data-gallery]");
    if (focusedGallery && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
      event.preventDefault();
      const state = galleries.get(focusedGallery);
      state.select(state.current() + (event.key === "ArrowRight" ? 1 : -1));
      if (event.target.closest(".gallery-thumbnail")) {
        focusedGallery.querySelector('.gallery-thumbnail[aria-pressed="true"]')?.focus();
      }
      return;
    }
    if (event.target.matches("input, textarea, select, [contenteditable='true']")) return;
    if (event.key === "ArrowRight" && slides.length > 1) { event.preventDefault(); show(index + 1); }
    if (event.key === "ArrowLeft" && slides.length > 1) { event.preventDefault(); show(index - 1); }
    if (event.key === "Home" && slides.length) { event.preventDefault(); show(0); }
    if (event.key === "End" && slides.length) { event.preventDefault(); show(slides.length - 1); }
    if (event.key.toLowerCase() === "f") document.querySelector("[data-fullscreen]")?.click();
  });
  document.querySelector("[data-fullscreen]")?.addEventListener("click", () => {
    const action = document.fullscreenElement
      ? document.exitFullscreen()
      : document.documentElement.requestFullscreen?.();
    action?.catch(() => {});
  });

  document.querySelectorAll("[data-gallery]").forEach((gallery) => {
    const figures = [...gallery.querySelectorAll("figure")];
    const count = gallery.querySelector(".image-count");
    let active = 0;
    const thumbnailList = gallery.querySelector("[data-thumbnails]");
    const thumbnails = figures.length > 1 ? figures.map((figure, position) => {
      const button = document.createElement("button");
      button.className = "gallery-thumbnail";
      button.setAttribute("aria-label", `${position + 1} / ${figures.length}`);
      button.title = figure.querySelector("figcaption")?.textContent || `${position + 1}`;
      const thumbnail = figure.querySelector("img").cloneNode();
      thumbnail.removeAttribute("class");
      thumbnail.alt = "";
      thumbnail.loading = "lazy";
      button.append(thumbnail);
      const number = document.createElement("span");
      number.textContent = String(position + 1).padStart(2, "0");
      button.append(number);
      button.addEventListener("click", () => selectImage(position));
      thumbnailList.append(button);
      return button;
    }) : [];
    function selectImage(next) {
      if (!figures.length) return;
      active = (next + figures.length) % figures.length;
      figures.forEach((figure, position) => {
        figure.classList.toggle("active", position === active);
        if (position === active && gallery.closest(".slide").classList.contains("active")) {
          figure.querySelector("img")?.setAttribute("loading", "eager");
        }
      });
      if (count) count.textContent = `${active + 1} / ${figures.length}`;
      thumbnails.forEach((button, position) => button.setAttribute("aria-pressed", String(position === active)));
      if (viewer.open && viewedGallery === gallery) updateViewer();
    }
    galleries.set(gallery, {figures, select: selectImage, current: () => active});
    gallery.querySelectorAll("[data-open-image]").forEach((button) => button.addEventListener("click", () => {
      viewedGallery = gallery;
      imageReturnFocus = button;
      viewer.classList.remove("zoomed");
      viewer.querySelector("[data-viewer-zoom]").setAttribute("aria-pressed", "false");
      updateViewer();
      viewer.showModal();
      notifyViewer(true);
    }));
    gallery.querySelector("[data-image-prev]")?.addEventListener("click", () => selectImage(active - 1));
    gallery.querySelector("[data-image-next]")?.addEventListener("click", () => selectImage(active + 1));
    selectImage(0);
  });

  slides.forEach((slide, position) => {
    slide.setAttribute("aria-hidden", String(position !== index));
    slide.inert = position !== index;
    slide.querySelectorAll("img").forEach((image) => {
      const markBroken = () => {
        image.classList.add("broken");
        image.closest(".image-frame")?.classList.add("has-error");
      };
      const setImageRatio = () => {
        if (image.naturalWidth > 0) {
          image.closest(".image-frame")?.style.setProperty(
            "--image-ratio", `${image.naturalWidth} / ${image.naturalHeight}`,
          );
        }
      };
      image.addEventListener("load", setImageRatio);
      image.addEventListener("error", markBroken);
      if (image.complete) setImageRatio();
      if (image.complete && image.naturalWidth === 0 && image.getAttribute("src")) markBroken();
    });
  });
  if (slides[index]) slides[index].classList.add("active");
  if (toc[index]) toc[index].classList.add("active");
  updateChrome();

  let touchStart;
  document.addEventListener("touchstart", (event) => {
    if (event.target.closest(".gallery-thumbnails")) { touchStart = null; return; }
    if (event.touches.length === 1) touchStart = [event.touches[0].clientX, event.touches[0].clientY];
  }, { passive: true });
  document.addEventListener("touchend", (event) => {
    if (!touchStart || viewer.open || contents?.classList.contains("is-open") || event.changedTouches.length !== 1) return;
    const dx = event.changedTouches[0].clientX - touchStart[0];
    const dy = event.changedTouches[0].clientY - touchStart[1];
    touchStart = null;
    if (Math.abs(dx) > 60 && Math.abs(dx) > 1.5 * Math.abs(dy)) show(index + (dx < 0 ? 1 : -1));
  }, { passive: true });
})();
