import { SLIDES } from './slides.js';
import { createScene } from './scene.js';

const N = SLIDES.length;
const copy = document.getElementById('slide-copy');
const notes = document.getElementById('notes');
const vizTag = document.getElementById('viz-tag');
const bar = document.getElementById('progress-bar');
const tlCursor = document.getElementById('tl-cursor');
const tlCells = [...document.querySelectorAll('.timeline .tl-head b, .timeline .tl-row i')];

const fromHash = () => Math.max(0, Math.min(N - 1, (parseInt(location.hash.slice(1)) || 1) - 1));
let index = fromHash();
let scene = null;
let liveList = null;
let lastLive = -1;
let lastTl = -1;

function render() {
  const s = SLIDES[index];
  document.body.dataset.slide = index;
  copy.className = `slide-copy slide-${index}`;
  copy.innerHTML = `<p class="kicker"><b>${String(index + 1).padStart(2, '0')} / ${N}</b><span>${s.kicker}</span></p><h1>${s.title}</h1>${s.html}`;
  notes.innerHTML = `<h4>Speaker notes · ${index + 1}</h4>${s.notes}`;
  vizTag.textContent = s.tag || '';
  bar.style.width = `${((index + 1) / N) * 100}%`;
  document.title = `${s.title} — NextStep`;
  history.replaceState(null, '', `#${index + 1}`);
  liveList = copy.querySelector('ol.live');
  lastLive = -1; lastTl = -1;
  scene?.setSlide(index);
}

function go(i) {
  const next = Math.max(0, Math.min(N - 1, i));
  if (next === index && copy.innerHTML) return;
  index = next;
  render();
}

// Called every frame by the scene with the current animation phase.
function onTick(info) {
  if (liveList) {
    const key = liveList.dataset.live;
    const v = info[key] ?? -1;
    if (v !== lastLive) {
      lastLive = v;
      [...liveList.children].forEach((li, k) => li.classList.toggle('on', k === v));
    }
  }
  if (index === 9 && info.phase5 >= 0) {
    const x = (info.phase5 + info.phase5Frac) / 5;
    const head = tlCursor.parentElement.querySelector('.tl-head');
    const first = head.children[1].getBoundingClientRect();
    const last = head.children[5].getBoundingClientRect();
    const box = tlCursor.parentElement.getBoundingClientRect();
    tlCursor.style.left = `${first.left - box.left + x * (last.right - first.left)}px`;
    if (info.phase5 !== lastTl) {
      lastTl = info.phase5;
      tlCells.forEach((c, k) => c.classList.toggle('on', k % 5 === info.phase5));
    }
  }
}

async function fullscreen() {
  try { document.fullscreenElement ? await document.exitFullscreen() : await document.documentElement.requestFullscreen(); } catch {}
}

window.addEventListener('hashchange', () => go(fromHash()));
window.addEventListener('keydown', (e) => {
  if (e.altKey || e.ctrlKey || e.metaKey || /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
  if (['ArrowRight', 'ArrowDown', 'PageDown'].includes(e.code)) { e.preventDefault(); go(index + 1); }
  if (['ArrowLeft', 'ArrowUp', 'PageUp'].includes(e.code)) { e.preventDefault(); go(index - 1); }
  if (e.code === 'Home') { e.preventDefault(); go(0); }
  if (e.code === 'End') { e.preventDefault(); go(N - 1); }
  if (e.code === 'Space') { e.preventDefault(); scene?.toggle(); }
  if (e.code === 'KeyF') fullscreen();
  if (e.code === 'KeyR') scene?.restart();
  if (e.code === 'KeyN') notes.hidden = !notes.hidden;
});
let touchX;
copy.addEventListener('touchstart', (e) => { touchX = e.changedTouches[0].clientX; }, { passive: true });
copy.addEventListener('touchend', (e) => {
  const dx = e.changedTouches[0].clientX - touchX;
  if (Math.abs(dx) > 50) go(index + (dx < 0 ? 1 : -1));
}, { passive: true });
copy.addEventListener('click', (e) => {
  if (window.getSelection()?.toString()) return;
  const r = copy.getBoundingClientRect();
  go(index + (e.clientX < r.left + r.width * 0.2 || e.shiftKey ? -1 : 1));
});

render();
try {
  scene = createScene({ index, onTick });
} catch (err) {
  document.getElementById('loading').innerHTML = '<strong>3D is unavailable in this browser.</strong><span>Try a browser with WebGL enabled.</span>';
  console.error(err);
}
window.deck = { go, get index() { return index; }, get scene() { return scene; } };
