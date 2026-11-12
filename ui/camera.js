/* Independent, sequential JPEG requests: no overlapping downloads or frame backlog. */
(() => {
  "use strict";
  const image = document.querySelector("#cameraImage");
  const label = document.querySelector("#cameraStatus");
  const placeholder = document.querySelector("#cameraPlaceholder");
  const toggle = document.querySelector("#cameraToggle");
  let paused = false, controller = null, imageUrl = null;
  let status = null, statusAt = 0;

  function clear(message) {
    image.hidden = true;
    image.removeAttribute("src");
    if (imageUrl) URL.revokeObjectURL(imageUrl);
    imageUrl = null;
    placeholder.hidden = false;
    placeholder.textContent = message;
    label.textContent = message;
  }

  toggle.onclick = () => {
    paused = !paused;
    toggle.textContent = paused ? "Reprendre l’aperçu" : "Mettre en pause";
    toggle.setAttribute("aria-pressed", String(paused));
    if (controller) controller.abort();
    clear(paused ? "Aperçu en pause" : "Connexion…");
    statusAt = 0;
  };
  document.addEventListener("visibilitychange", () => {
    if (controller) controller.abort();
    clear(paused ? "Aperçu en pause" : "Connexion…");
    statusAt = 0;
  });

  async function poll() {
    let delay = 200;
    if (paused || document.hidden) {
      setTimeout(poll, delay);
      return;
    }
    controller = new AbortController();
    const deadline = setTimeout(() => controller.abort(), 1200);
    try {
      if (!status || performance.now() - statusAt > 1000) {
        const response = await fetch("/api/camera/status", { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error("Caméra indisponible — connexion au bridge à vérifier");
        status = await response.json();
        statusAt = performance.now();
      }
      if (!status.enabled) {
        clear("Caméra désactivée sur le robot");
        delay = 1000;
      } else {
        const response = await fetch("/api/camera/frame.jpg", { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error("Aucune image récente — caméra en attente ou déconnectée");
        const blob = await response.blob();
        if (blob.type !== "image/jpeg" || blob.size > 2 * 1024 * 1024) throw new Error("Image caméra invalide");
        if (paused || document.hidden) return;
        if (controller.signal.aborted) throw new DOMException("Timeout", "AbortError");
        const previous = imageUrl;
        imageUrl = URL.createObjectURL(blob);
        image.src = imageUrl;
        if (previous) URL.revokeObjectURL(previous);
        await image.decode();
        if (paused || document.hidden) return;
        if (controller.signal.aborted) throw new DOMException("Timeout", "AbortError");
        image.hidden = false;
        placeholder.hidden = true;
        label.textContent = "Caméra connectée · aperçu jusqu’à 5 images/s";
      }
    } catch (error) {
      if (!paused && !document.hidden) {
        clear(error.name === "AbortError" ? "Caméra indisponible — délai dépassé" : error.message);
      }
      statusAt = 0;
      delay = 1000;
    } finally {
      clearTimeout(deadline);
      controller = null;
      setTimeout(poll, delay);
    }
  }
  poll();
})();
