// NextStep — shared 3D scene. One renderer, drawn in the right half of the screen (view offset),
// with one "stage" per slide. Models: TurtleBot3 Burger, the person (Walk/Idle clips) and the laser mount draft.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const V3 = THREE.Vector3;
const { clamp, lerp } = THREE.MathUtils;
const smooth = (t) => { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); };

const COLORS = {
  bg: '#ededed', marker: '#b8ed74', bone: '#8fc65a', foot: '#79a744',
  laser: '#ff5a2e', axis: '#1d6957', angle: '#c98a1c', deep: '#1d6957', mid: '#447e5b',
};

// Slide indices
const S = { INTRO: 0, UX: 1, PARTS: 2, VISION: 3, POSTURE: 4, DIFF: 5, FSM: 6, LASER: 7, ARCH: 8, CYCLE: 9, STATUS: 10, END: 11 };
const WALK_SLIDES = new Set([S.INTRO, S.UX, S.CYCLE]);

// Walking cycle timing (seconds inside one step segment)
const STEPS = 8;
const T = { back: 1.5, est: 2.7, choose: 3.2, mark: 3.9, step: 6.3, seg: 6.6 };
const TOTAL = STEPS * T.seg;

const ROBOT_H = 0.34;      // displayed robot height (same as presentation 1)
const MOUNT_S = 0.0014;    // laser mount: mm → scene units

export function createScene({ index = 0, onTick = () => {} } = {}) {
  const $ = (id) => document.getElementById(id);
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let slide = index;
  let playing = !reduced;
  let ready = false;
  let walkT = 0;      // time in the walking cycle
  let slideT = 0;     // time since the slide started
  const tickInfo = { phase4: -1, phase5: -1, phase5Frac: 0, vision: -1, fsm: -1 };

  // ---------- Renderer, scene, lights, floor ----------
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(COLORS.bg);
  scene.fog = new THREE.Fog(COLORS.bg, 14, 32);
  const camera = new THREE.PerspectiveCamera(35, 1, 0.05, 80);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.22;
  $('viewport').appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.enablePan = false;
  controls.minDistance = 0.8;
  controls.maxDistance = 13;
  controls.maxPolarAngle = Math.PI / 2 - 0.045;

  scene.add(new THREE.HemisphereLight(0xe9f3ff, 0x9cacc0, 2.7));
  const sun = new THREE.DirectionalLight(0xfff8ed, 3.5);
  sun.position.set(-3, 8, 5);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -8, right: 8, top: 6, bottom: -6, near: 0.5, far: 25 });
  sun.shadow.normalBias = 0.025; sun.shadow.bias = -0.00015; sun.shadow.radius = 3;
  scene.add(sun, sun.target);
  const rim = new THREE.DirectionalLight(0xbad2ff, 1.5);
  rim.position.set(2, 4, -5);
  scene.add(rim);

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(150, 150), new THREE.MeshBasicMaterial({ color: COLORS.bg, toneMapped: false }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -0.014;
  scene.add(floor);
  const shadowFloor = new THREE.Mesh(new THREE.PlaneGeometry(150, 150), new THREE.ShadowMaterial({ color: '#495058', opacity: 0.13 }));
  shadowFloor.rotation.x = -Math.PI / 2; shadowFloor.position.y = -0.013; shadowFloor.receiveShadow = true;
  scene.add(shadowFloor);
  const grid = new THREE.GridHelper(100, 200, 0xb9beb9, 0xb9beb9);
  grid.material.transparent = true; grid.material.opacity = 0.1; grid.position.y = -0.012;
  scene.add(grid);

  // ---------- Small helpers ----------
  const basic = (color, opacity = 1, extra = {}) => new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity, toneMapped: false, depthWrite: opacity >= 1, ...extra });
  const std = (color, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0.05, ...extra });

  function ring(r, color, opacity = 1, width = 0.009) {
    const m = new THREE.Mesh(new THREE.RingGeometry(r - width, r, 64), basic(color, opacity, { side: THREE.DoubleSide }));
    m.rotation.x = -Math.PI / 2;
    return m;
  }
  // Thin tube through points (used for lines that must stay visible: axis, arcs, arrows)
  function tube(points, radius, material, closed = false) {
    const curve = new THREE.CatmullRomCurve3(points, closed);
    return new THREE.Mesh(new THREE.TubeGeometry(curve, Math.max(8, points.length * 4), radius, 8, closed), material);
  }
  function setTube(mesh, points, radius) {
    mesh.geometry.dispose();
    mesh.geometry = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points), Math.max(8, points.length * 3), radius, 6, false);
  }
  // Orient a unit cylinder (height along +Y, base at origin) from a to b
  const UP = new V3(0, 1, 0);
  function stretch(mesh, a, b) {
    const d = new V3().subVectors(b, a);
    const len = d.length();
    mesh.position.copy(a);
    mesh.quaternion.setFromUnitVectors(UP, d.normalize());
    mesh.scale.set(1, Math.max(len, 1e-4), 1);
  }
  function unitCylinder(radius, material) {
    const g = new THREE.CylinderGeometry(radius, radius, 1, 10, 1, true);
    g.translate(0, 0.5, 0);
    return new THREE.Mesh(g, material);
  }
  function dashedEdges(geometry, color, dash = 0.035) {
    const l = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), new THREE.LineDashedMaterial({ color, dashSize: dash, gapSize: dash * 0.8, transparent: true, opacity: 0.9 }));
    l.computeLineDistances();
    return l;
  }
  function footShape() {
    const p = new THREE.Shape();
    p.moveTo(-0.045, -0.1); p.quadraticCurveTo(-0.07, -0.1, -0.07, -0.045); p.lineTo(-0.061, 0.105);
    p.quadraticCurveTo(0, 0.18, 0.061, 0.105); p.lineTo(0.07, -0.045); p.quadraticCurveTo(0.07, -0.1, 0.045, -0.1); p.closePath();
    return new THREE.ShapeGeometry(p);
  }
  const FOOT_GEO = footShape();
  function footprint(color, opacity) {
    const m = new THREE.Mesh(FOOT_GEO, basic(color, opacity, { side: THREE.DoubleSide }));
    m.rotation.set(-Math.PI / 2, 0, -Math.PI / 2); // toe towards +x
    m.position.y = 0.012;
    return m;
  }

  // ---------- HTML labels anchored in 3D ----------
  const labels = [];
  function label(html, { cls = '', slides = [], at = null, obj = null, offset = new V3(), anchor = 'bottom' } = {}) {
    const el = document.createElement('div');
    el.className = `tag3d ${cls}`;
    el.innerHTML = html;
    $('labels').appendChild(el);
    const L = { el, slides: new Set(slides), pos: at ? at.clone() : new V3(), obj, offset, anchor, on: true, shown: false };
    labels.push(L);
    return L;
  }
  const tmpV = new V3();
  function updateLabels() {
    const w = renderer.domElement.clientWidth, h = renderer.domElement.clientHeight;
    const portrait = w <= 760 && h > w;
    for (const L of labels) {
      let show = ready && L.on && L.slides.has(slide);
      if (show) {
        if (L.obj) L.obj.getWorldPosition(L.pos).add(L.offset);
        tmpV.copy(L.pos).project(camera);
        const x = (tmpV.x + 1) / 2 * w, y = (1 - tmpV.y) / 2 * h;
        show = tmpV.z < 1 && (portrait ? y > h * 0.56 : x > w / 2 + 8) && x < w + 40;
        if (show) {
          const ty = L.anchor === 'center' ? '-50%' : L.anchor === 'top' ? '0%' : '-100%';
          L.el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, ${ty})`;
        }
      }
      if (show !== L.shown) { L.el.classList.toggle('show', show); L.shown = show; }
    }
  }

  // ---------- Laser (beam + spot), shared by every stage ----------
  const laserMat = basic(COLORS.laser, 0.9);
  const beam = unitCylinder(0.0035, laserMat);
  const beamGlow = unitCylinder(0.011, basic(COLORS.laser, 0.16, { blending: THREE.AdditiveBlending }));
  const spot = new THREE.Group();
  const spotCore = new THREE.Mesh(new THREE.CircleGeometry(0.022, 32), basic(COLORS.laser, 1, { side: THREE.DoubleSide }));
  spotCore.rotation.x = -Math.PI / 2;
  const spotHalo = new THREE.Mesh(new THREE.CircleGeometry(0.07, 32), basic(COLORS.laser, 0.22, { side: THREE.DoubleSide, blending: THREE.AdditiveBlending }));
  spotHalo.rotation.x = -Math.PI / 2;
  const spotFoot = footprint(COLORS.laser, 0.22);
  spotFoot.position.y = -0.006;
  spot.add(spotHalo, spotCore, spotFoot);
  spotCore.position.y = 0.016; spotHalo.position.y = 0.015;
  scene.add(beam, beamGlow, spot);
  const aim = { cur: new V3(0, 0, 0), want: new V3(0, 0, 0), on: false };

  // ---------- Skeleton markers (MediaPipe-like illustration) ----------
  const BONES = ['Head_06', 'Neck_05', 'Spine2_04', 'Hips_01', 'LeftArm_09', 'LeftForeArm_010', 'LeftHand_011', 'RightArm_014', 'RightForeArm_015', 'RightHand_016', 'LeftUpLeg_019', 'LeftLeg_020', 'LeftFoot_00', 'RightUpLeg_023', 'RightLeg_024', 'RightFoot_025'];
  const LINKS = [[0, 1], [1, 2], [2, 3], [2, 4], [4, 5], [5, 6], [2, 7], [7, 8], [8, 9], [3, 10], [10, 11], [11, 12], [3, 13], [13, 14], [14, 15]];
  const skel = new THREE.Group();
  const markerMat = basic(COLORS.marker, 1, { depthTest: false });
  const markers = BONES.map(() => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.026, 12, 8), markerMat.clone()); m.renderOrder = 5; skel.add(m); return m; });
  const boneLines = new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(new Float32Array(LINKS.length * 6), 3)),
    new THREE.LineBasicMaterial({ color: COLORS.bone, transparent: true, opacity: 0.85, depthTest: false }));
  boneLines.renderOrder = 4;
  skel.add(boneLines);
  scene.add(skel);
  let bones = [];
  const J = BONES.map(() => new V3());
  function updateSkeleton(visibleCount = BONES.length, linesOn = true, opacity = 1) {
    bones.forEach((b, i) => b.getWorldPosition(J[i]));
    markers.forEach((m, i) => { m.position.copy(J[i]); m.visible = i < visibleCount; m.material.opacity = opacity; m.material.transparent = opacity < 1; });
    const a = boneLines.geometry.attributes.position;
    LINKS.forEach(([p, q], k) => { a.setXYZ(k * 2, ...J[p].toArray()); a.setXYZ(k * 2 + 1, ...J[q].toArray()); });
    a.needsUpdate = true;
    boneLines.geometry.computeBoundingSphere();
    boneLines.visible = linesOn;
    boneLines.material.opacity = 0.85 * opacity;
  }

  // ---------- Camera frustum (BRIO 105 field of view, illustrative) ----------
  const frustum = new THREE.Group();
  const frLines = new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(new Float32Array(8 * 6), 3)),
    new THREE.LineBasicMaterial({ color: COLORS.mid, transparent: true, opacity: 0.55 }));
  const frFaces = new THREE.Mesh(new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(new Float32Array(4 * 9), 3)),
    basic(COLORS.foot, 0.07, { side: THREE.DoubleSide }));
  const imgPlane = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), basic('#dfeccf', 0.35, { side: THREE.DoubleSide }));
  const imgGrid = new THREE.LineSegments(gridGeometry(8, 12), new THREE.LineBasicMaterial({ color: COLORS.mid, transparent: true, opacity: 0.35 }));
  const scanBar = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), basic(COLORS.foot, 0.28, { side: THREE.DoubleSide }));
  frustum.add(frLines, frFaces, imgPlane, imgGrid, scanBar);
  scene.add(frustum);
  function gridGeometry(nx, ny) {
    const pts = [];
    for (let i = 0; i <= nx; i++) { const x = i / nx - 0.5; pts.push(x, -0.5, 0, x, 0.5, 0); }
    for (let j = 0; j <= ny; j++) { const y = j / ny - 0.5; pts.push(-0.5, y, 0, 0.5, y, 0); }
    return new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
  }
  const camWorld = new V3();
  function updateFrustum(personX, { faces = true, image = 0, scan = -1 } = {}) {
    cameraBlock.getWorldPosition(camWorld);
    const x = personX - 0.18, y0 = 0.02, y1 = 1.92, z = 0.62;
    const c = [new V3(x, y0, -z), new V3(x, y0, z), new V3(x, y1, z), new V3(x, y1, -z)];
    const l = frLines.geometry.attributes.position;
    let k = 0;
    for (let i = 0; i < 4; i++) { l.setXYZ(k++, ...camWorld.toArray()); l.setXYZ(k++, ...c[i].toArray()); }
    for (let i = 0; i < 4; i++) { l.setXYZ(k++, ...c[i].toArray()); l.setXYZ(k++, ...c[(i + 1) % 4].toArray()); }
    l.needsUpdate = true; frLines.geometry.computeBoundingSphere();
    const f = frFaces.geometry.attributes.position;
    for (let i = 0; i < 4; i++) { f.setXYZ(i * 3, ...camWorld.toArray()); f.setXYZ(i * 3 + 1, ...c[i].toArray()); f.setXYZ(i * 3 + 2, ...c[(i + 1) % 4].toArray()); }
    f.needsUpdate = true; frFaces.geometry.computeBoundingSphere();
    frFaces.visible = faces;
    for (const m of [imgPlane, imgGrid]) {
      m.position.set(x - 0.002, (y0 + y1) / 2, 0); m.rotation.set(0, Math.PI / 2, 0); m.scale.set(2 * z, y1 - y0, 1);
    }
    imgPlane.visible = imgGrid.visible = image > 0;
    imgPlane.material.opacity = 0.35 * image; imgGrid.material.opacity = 0.4 * image;
    scanBar.visible = scan >= 0;
    if (scan >= 0) { scanBar.position.set(x + 0.001, y1 - (y1 - y0) * scan, 0); scanBar.rotation.set(0, Math.PI / 2, 0); scanBar.scale.set(2 * z, 0.05, 1); }
  }

  // ---------- Footprints for the walking cycle ----------
  const footprints = Array.from({ length: STEPS }, () => { const f = footprint(COLORS.foot, 0.28); scene.add(f); return f; });
  const robotHalo = ring(0.24, '#558353', 0.55);
  robotHalo.position.y = 0.009;
  scene.add(robotHalo);

  // ---------- Stage: posture angles (slide 5) ----------
  const posture = new THREE.Group();
  const axisMat = basic(COLORS.axis, 0.95);
  const axisMesh = unitCylinder(0.009, axisMat);
  const refMat = basic(COLORS.axis, 0.6, { depthTest: false });
  const refs = [0, 1, 2, 3].map(() => { const m = unitCylinder(0.0045, refMat); m.renderOrder = 6; posture.add(m); return m; });
  const angleMat = basic(COLORS.angle, 0.95, { depthTest: false });
  const arcs = [0, 1, 2, 3].map(() => { const m = tube([new V3(), new V3(0, 0.01, 0)], 0.005, angleMat); m.renderOrder = 6; posture.add(m); return m; });
  const arcFans = [0, 1, 2, 3].map(() => { const m = new THREE.Mesh(new THREE.BufferGeometry(), basic(COLORS.angle, 0.18, { side: THREE.DoubleSide, depthTest: false })); m.renderOrder = 5; posture.add(m); return m; });
  posture.add(axisMesh);
  scene.add(posture);
  const thetaLabels = ['θ₁', 'θ₂', 'θ₃', 'θ₄'].map((t) => label(t, { cls: 'theta', slides: [S.POSTURE], anchor: 'center' }));
  const axisLabel = label('Trunk axis <small>approximation · definition to choose</small>', { slides: [S.POSTURE] });
  const axisTop = new V3();
  function updatePosture() {
    const hips = J[3], neck = J[1];
    const up = new V3().subVectors(neck, hips).normalize();
    const down = up.clone().negate();
    const a = hips.clone().addScaledVector(up, -0.32), b = neck.clone().addScaledVector(up, 0.42);
    stretch(axisMesh, a, b);
    axisTop.copy(b);
    axisLabel.pos.copy(b).add(new V3(0, 0.05, 0));
    // angle between the (downward) axis and upper arms / thighs, drawn at the joint
    const pairs = [[4, 5, J[4]], [7, 8, J[7]], [10, 11, J[10]], [13, 14, J[13]]];
    pairs.forEach(([p, q, at], i) => {
      const limb = new V3().subVectors(J[q], J[p]).normalize();
      const r = 0.15;
      const quat = new THREE.Quaternion().setFromUnitVectors(down, limb);
      const pts = [], fan = [];
      const id = new THREE.Quaternion();
      for (let s = 0; s <= 16; s++) {
        const qs = id.clone().slerp(quat, s / 16);
        pts.push(down.clone().applyQuaternion(qs).multiplyScalar(r).add(at));
      }
      for (let s = 0; s < 16; s++) fan.push(...at.toArray(), ...pts[s].toArray(), ...pts[s + 1].toArray());
      setTube(arcs[i], pts, 0.0045);
      arcFans[i].geometry.dispose();
      arcFans[i].geometry = new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(fan, 3));
      const mid = down.clone().applyQuaternion(id.clone().slerp(quat, 0.5)).multiplyScalar(r * 1.75).add(at);
      thetaLabels[i].pos.copy(mid);
      // short segment parallel to the trunk axis at that joint: the reference for θ
      stretch(refs[i], at, at.clone().addScaledVector(down, r * 1.35));
    });
  }

  // ---------- Stage: adapting the difficulty (slide 6) ----------
  const diff = new THREE.Group();
  const ruleBox = new THREE.Mesh(new THREE.BoxGeometry(0.46, 0.24, 0.24), basic('#fbf6ec', 0.75));
  const ruleEdges = dashedEdges(ruleBox.geometry, '#b98a3c', 0.025);
  ruleBox.add(ruleEdges);
  diff.add(ruleBox);
  const ruleLabel = label('Adaptation rule <span class="pill tbd">To define</span><small>sets the current difficulty</small>', { slides: [S.DIFF], obj: ruleBox, offset: new V3(0, 0.17, 0) });
  const flowColors = [COLORS.foot, '#2f7f8a', COLORS.laser];
  const flows = flowColors.map((c) => Array.from({ length: 7 }, () => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.017, 10, 8), basic(c, 1, { depthTest: false })); m.renderOrder = 7; diff.add(m); return m; }));
  const flowCurves = [0, 1, 2].map(() => new THREE.QuadraticBezierCurve3(new V3(), new V3(), new V3()));
  const flowLines = flowColors.map((c) => { const l = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ color: c, dashSize: 0.03, gapSize: 0.03, transparent: true, opacity: 0.6 })); diff.add(l); return l; });
  const sensorBand = new THREE.Mesh(new THREE.TorusGeometry(0.035, 0.012, 8, 24), std('#2f7f8a'));
  scene.add(sensorBand);
  label('Posture estimate', { cls: 'marker', slides: [S.DIFF], obj: markers[0], offset: new V3(0, 0.12, 0) });
  label('Wearable sensors <small>BPM · SpO₂ · planned</small>', { slides: [S.DIFF, S.PARTS], obj: sensorBand, offset: new V3(0, -0.05, 0.12), anchor: 'top' });
  label('Next-step target', { cls: 'laser', slides: [S.DIFF], obj: spot, offset: new V3(0, 0.04, 0.16), anchor: 'top' });
  scene.add(diff);
  function setFlow(i, a, b, t) {
    const c = flowCurves[i];
    c.v0.copy(a); c.v2.copy(b); c.v1.copy(a).lerp(b, 0.5); c.v1.y = Math.max(a.y, b.y) + 0.25;
    flowLines[i].geometry.setFromPoints(c.getPoints(30));
    flowLines[i].computeLineDistances();
    flows[i].forEach((m, k) => { const u = ((t * 0.45 + k / flows[i].length) % 1); m.position.copy(c.getPoint(u)); m.scale.setScalar(Math.sin(u * Math.PI) * 0.9 + 0.2); });
  }

  // ---------- Stage: state machine (slide 7) ----------
  const fsm = new THREE.Group();
  const FSM_NODES = [
    { name: 'Back up', sub: '<code>moving_backward</code>', pos: new V3(-0.95, 0, -0.62), planned: false },
    { name: 'Estimate posture', sub: '<code>posture_checking</code>', pos: new V3(0.95, 0, -0.62), planned: false },
    { name: 'Aim the laser', sub: 'left foot', pos: new V3(0.95, 0, 0.72), planned: false },
    { name: 'Wait for the step', sub: '<span class="pill plan">Planned</span>', pos: new V3(-0.95, 0, 0.72), planned: true },
  ];
  const END_NODE = { name: 'End of session', sub: '<span class="pill plan">Planned</span>', pos: new V3(-0.95, 0, 1.75), planned: true };
  const pucks = [];
  const fsmLabels = [];
  [...FSM_NODES, END_NODE].forEach((n, i) => {
    const g = new THREE.Group();
    g.position.copy(n.pos);
    const puck = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.05, 48), n.planned ? basic('#f3f6ec', 0.55) : std('#dfeccf'));
    puck.position.y = 0.025; puck.castShadow = !n.planned; puck.receiveShadow = true;
    g.add(puck);
    if (n.planned) g.add(dashedEdges(new THREE.CylinderGeometry(0.2, 0.2, 0.05, 24), COLORS.mid, 0.03).translateY(0.025));
    const glow = ring(0.26, COLORS.deep, 0, 0.02); glow.position.y = 0.004; g.add(glow);
    fsm.add(g);
    pucks.push({ g, puck, glow });
    fsmLabels.push(label(`${i < 4 ? `${i + 1} · ` : ''}${n.name}<small>${n.sub}</small>`, { cls: `state${n.planned ? ' planned' : ''}`, slides: [S.FSM], at: n.pos.clone().add(new V3(0, 0.1, 0)) }));
  });
  const arrowMat = std(COLORS.mid);
  const plannedArrowMat = basic(COLORS.mid, 0.55);
  const fsmEdges = [];
  function arrow(from, to, bulge, planned) {
    const a = from.clone().add(new V3(0, 0.03, 0)), b = to.clone().add(new V3(0, 0.03, 0));
    const dir = new V3().subVectors(b, a).normalize();
    a.addScaledVector(dir, 0.27); b.addScaledVector(dir, -0.29);
    const mid = a.clone().lerp(b, 0.5).add(bulge);
    const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
    const mat = planned ? plannedArrowMat : arrowMat;
    const N = planned ? 9 : 1;
    for (let i = 0; i < N; i++) {
      const t0 = i / N, t1 = planned ? (i + 0.55) / N : 1;
      const pts = Array.from({ length: 8 }, (_, k) => curve.getPoint(lerp(t0, t1, k / 7)));
      fsm.add(tube(pts, 0.011, mat));
    }
    const head = new THREE.Mesh(new THREE.ConeGeometry(0.035, 0.08, 16), mat);
    head.position.copy(curve.getPoint(1));
    head.quaternion.setFromUnitVectors(UP, curve.getTangent(1).normalize());
    fsm.add(head);
    fsmEdges.push(curve);
    label('condition: to define', { cls: 'cond', slides: [S.FSM], at: curve.getPoint(0.5).add(new V3(0, 0.04, 0)), anchor: 'center' });
    return curve;
  }
  arrow(FSM_NODES[0].pos, FSM_NODES[1].pos, new V3(0, 0, -0.32), false);
  arrow(FSM_NODES[1].pos, FSM_NODES[2].pos, new V3(0.32, 0, 0), false);
  arrow(FSM_NODES[2].pos, FSM_NODES[3].pos, new V3(0, 0, 0.32), true);
  arrow(FSM_NODES[3].pos, FSM_NODES[0].pos, new V3(-0.32, 0, 0), true);
  arrow(FSM_NODES[3].pos, END_NODE.pos, new V3(-0.18, 0, 0), true);
  const token = new THREE.Mesh(new THREE.SphereGeometry(0.045, 20, 14), basic(COLORS.deep));
  const tokenHalo = new THREE.Mesh(new THREE.SphereGeometry(0.08, 20, 14), basic(COLORS.foot, 0.25));
  token.add(tokenHalo);
  fsm.add(token);
  scene.add(fsm);

  // ---------- Stage: architecture (slide 9) ----------
  const arch = new THREE.Group();
  function pad(x, w, d, color) {
    const s = new THREE.Shape();
    const r = 0.12, hw = w / 2, hd = d / 2;
    s.moveTo(-hw + r, -hd); s.lineTo(hw - r, -hd); s.quadraticCurveTo(hw, -hd, hw, -hd + r); s.lineTo(hw, hd - r); s.quadraticCurveTo(hw, hd, hw - r, hd);
    s.lineTo(-hw + r, hd); s.quadraticCurveTo(-hw, hd, -hw, hd - r); s.lineTo(-hw, -hd + r); s.quadraticCurveTo(-hw, -hd, -hw + r, -hd);
    const m = new THREE.Mesh(new THREE.ShapeGeometry(s), basic(color, 0.75, { side: THREE.DoubleSide }));
    m.rotation.x = -Math.PI / 2; m.position.set(x, 0.004, 0);
    arch.add(m);
    return m;
  }
  pad(-1.12, 1.55, 1.5, '#dfe3ea');
  pad(1.12, 1.55, 1.5, '#dfeccf');
  label('Mac', { cls: 'big', slides: [S.ARCH], at: new V3(-1.12, 0.02, 0.86), anchor: 'top' });
  label('Robot · Raspberry Pi', { cls: 'big', slides: [S.ARCH], at: new V3(1.12, 0.02, 0.86), anchor: 'top' });
  // laptop
  const laptop = new THREE.Group();
  const lapBase = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.018, 0.3), std('#b9bec6', { metalness: 0.4, roughness: 0.4 }));
  lapBase.position.y = 0.009;
  const lapScreen = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.29, 0.012), std('#b9bec6', { metalness: 0.4, roughness: 0.4 }));
  lapScreen.geometry.translate(0, 0.145, 0);
  lapScreen.position.set(0, 0.018, -0.15); lapScreen.rotation.x = -0.25;
  const lapGlass = new THREE.Mesh(new THREE.PlaneGeometry(0.4, 0.25), basic('#26302c'));
  lapGlass.position.set(0, 0.145, 0.0065);
  lapScreen.add(lapGlass);
  laptop.add(lapBase, lapScreen);
  laptop.traverse((o) => { if (o.isMesh) o.castShadow = true; });
  laptop.position.set(-1.12, 0, 0.12);
  laptop.rotation.y = 0.35;
  arch.add(laptop);
  function slab(pos, w, color, dashed = false) {
    const g = new THREE.BoxGeometry(w, 0.03, 0.22);
    const m = new THREE.Mesh(g, dashed ? basic('#fbf6ec', 0.45) : std(color));
    m.position.copy(pos); m.castShadow = !dashed;
    if (dashed) m.add(dashedEdges(g, '#b98a3c', 0.025));
    arch.add(m);
    return m;
  }
  const P = {
    py: new V3(-1.12, 0.95, 0), ui: new V3(-1.45, 0.55, 0.32), docker: new V3(-0.78, 0.55, -0.35),
    bridge: new V3(1.12, 1.05, 0), ros: new V3(1.12, 0.72, 0), hw: new V3(1.12, 0.36, 0.05), vision: new V3(0, 1.62, -0.25),
  };
  slab(P.py, 0.52, '#c9d7e6'); slab(P.ui, 0.4, '#e4e7ec'); slab(P.docker, 0.4, '#e4e7ec');
  slab(P.bridge, 0.52, '#b9d89a'); slab(P.ros, 0.52, '#cfe6b0');
  const visionSlab = slab(P.vision, 0.62, '#fff', true);
  const above = (p, dy = 0.04) => p.clone().add(new V3(0, dy, 0));
  label('Python client <small><code>Robot</code> · <code>BridgeClient</code></small>', { slides: [S.ARCH], at: above(P.py) });
  label('Local web UI <small>control · telemetry</small>', { slides: [S.ARCH], at: above(P.ui) });
  label('Docker <small>builds the ARM64 bridge</small>', { slides: [S.ARCH], at: above(P.docker) });
  label('Rust bridge <small>HTTP API ↔ ROS 2</small>', { slides: [S.ARCH], at: above(P.bridge) });
  label('ROS 2 Jazzy <small>Ubuntu 24.04 ARM64</small>', { slides: [S.ARCH], at: above(P.ros) });
  label('Motors · LiDAR · sensors', { cls: 'plain', slides: [S.ARCH], at: new V3(1.12, 0.02, 0.42), anchor: 'top' });
  label('Vision <span class="pill plan">Planned</span><small>BRIO 105 · OpenCV · MediaPipe<br>runs on Pi or Mac? <b>to decide</b></small>', { slides: [S.ARCH], at: above(P.vision) });
  const tunnelCurve = new THREE.QuadraticBezierCurve3(P.py.clone().add(new V3(0.27, 0, 0)), new V3(0, 1.2, 0), P.bridge.clone().add(new V3(-0.27, 0, 0)));
  const tunnel = new THREE.Mesh(new THREE.TubeGeometry(tunnelCurve, 48, 0.045, 16, false), basic('#9fb3a0', 0.22, { side: THREE.DoubleSide }));
  arch.add(tunnel);
  label('HTTP via SSH tunnel', { cls: 'plain', slides: [S.ARCH], at: new V3(0, 1.3, 0) });
  const dockerCurve = new THREE.CubicBezierCurve3(P.docker.clone().add(new V3(0.2, 0, 0)), new V3(-0.2, 0.45, -0.6), new V3(0.7, 0.85, -0.5), P.bridge.clone().add(new V3(-0.1, -0.02, -0.11)));
  const dockerLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints(dockerCurve.getPoints(50)), new THREE.LineDashedMaterial({ color: '#7d8796', dashSize: 0.04, gapSize: 0.03 }));
  dockerLine.computeLineDistances();
  arch.add(dockerLine);
  label('binary copied to the Pi', { cls: 'plain', slides: [S.ARCH], at: dockerCurve.getPoint(0.55).add(new V3(0, -0.02, 0)), anchor: 'top' });
  const visionLinks = [P.py, P.bridge].map((p) => {
    const c = new THREE.QuadraticBezierCurve3(P.vision.clone(), P.vision.clone().lerp(p, 0.5).add(new V3(0, 0.15, 0)), above(p, 0.17));
    const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(c.getPoints(30)), new THREE.LineDashedMaterial({ color: '#b98a3c', dashSize: 0.03, gapSize: 0.04 }));
    l.computeLineDistances(); arch.add(l); return l;
  });
  const cmdPath = new THREE.CurvePath();
  cmdPath.add(new THREE.LineCurve3(P.py.clone(), tunnelCurve.v0.clone()));
  cmdPath.add(tunnelCurve);
  cmdPath.add(new THREE.LineCurve3(tunnelCurve.v2.clone(), P.bridge.clone()));
  cmdPath.add(new THREE.LineCurve3(P.bridge.clone(), P.ros.clone()));
  cmdPath.add(new THREE.LineCurve3(P.ros.clone(), P.hw.clone()));
  const packets = Array.from({ length: 4 }, (_, i) => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.03, 14, 10), basic(i % 2 ? COLORS.foot : '#3d5a80')); arch.add(m); return m; });
  label('command', { cls: 'plain', slides: [S.ARCH], obj: packets[0], offset: new V3(0, 0.05, 0) });
  label('telemetry', { cls: 'plain', slides: [S.ARCH], obj: packets[1], offset: new V3(0, -0.05, 0), anchor: 'top' });
  scene.add(arch);

  // ---------- Stage: status blocks (slide 11) ----------
  const status = new THREE.Group();
  const COLS = [
    { x: -0.9, kind: 'ok', items: ['Rust bridge', 'Python client', 'Local web UI', 'Container + fake-robot tests'] },
    { x: 0, kind: 'plan', items: ['State machine (draft)', 'Vision chain', 'Laser + two-gear mount', 'Wearable sensors'] },
    { x: 0.9, kind: 'tbd', items: ['Angles · thresholds', 'Difficulty rule', 'Step detection · end', 'Laser mechanics', 'Image transport', 'Real-robot cycle'] },
  ];
  const blocks = [];
  const BW = 0.8, BH = 0.15, BD = 0.4;
  COLS.forEach((col, ci) => {
    col.items.forEach((name, ri) => {
      const g = new THREE.BoxGeometry(BW, BH, BD);
      let m;
      if (col.kind === 'ok') { m = new THREE.Mesh(g, std('#447e5b')); m.castShadow = true; }
      else if (col.kind === 'plan') { m = new THREE.Mesh(g, std('#f4f6ef')); m.castShadow = true; m.add(new THREE.LineSegments(new THREE.EdgesGeometry(g), new THREE.LineBasicMaterial({ color: '#7aa287' }))); }
      else { m = new THREE.Mesh(g, basic('#fbf6ec', 0.35)); m.add(dashedEdges(g, '#b98a3c', 0.03)); }
      const y = BH / 2 + ri * (BH + 0.012);
      m.position.set(col.x, y, 0);
      status.add(m);
      blocks.push({ m, y, delay: ci * 0.35 + ri * 0.14, kind: col.kind });
      label(name, { cls: `block${col.kind === 'ok' ? ' light' : ''}`, slides: [S.STATUS], obj: m, offset: new V3(0, 0, BD / 2 + 0.01), anchor: 'center' });
    });
    const top = col.items.length * (BH + 0.012) + 0.08;
    const pill = { ok: '<span class="pill ok">Existing</span>', plan: '<span class="pill plan">Planned</span>', tbd: '<span class="pill tbd">To define / validate</span>' }[col.kind];
    label(pill, { cls: 'plain', slides: [S.STATUS], at: new V3(col.x, Math.max(top, 0.75), 0) });
  });
  scene.add(status);

  // ---------- Robot extras: camera block + anchors ----------
  const cameraBlock = new THREE.Group();
  const camBody = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.03, 0.09), std('#1e2124', { roughness: 0.5 }));
  const camLens = new THREE.Mesh(new THREE.CircleGeometry(0.009, 24), basic('#3b4f63'));
  camLens.position.set(-0.0155, 0, 0); camLens.rotation.y = -Math.PI / 2;
  cameraBlock.add(camBody, camLens);
  cameraBlock.position.set(-0.15, 0.255, 0);
  const anchors = { lidar: new V3(0.0, 0.3, 0.05), boards: new V3(0.05, 0.19, -0.1), base: new V3(0.02, 0.05, 0.14), mount: new V3(-0.04, 0.47, 0) };

  // ---------- Model loading ----------
  let robot, person, mixer, actions = {}, currentAction, walkDur = 1, startPhase = 0, frames = [];
  let leftFoot, rightFoot, leftHand;
  let mount, ballPivot, gearA, gearB;
  const laserExit = new V3();

  function fit(obj, height) {
    obj.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(obj);
    const size = box.getSize(new V3());
    const s = height / size.y;
    obj.scale.multiplyScalar(s);
    obj.position.multiplyScalar(s);
    obj.position.y -= box.min.y * s;
    obj.position.x -= (box.min.x + box.max.x) * 0.5 * s;
    obj.position.z -= (box.min.z + box.max.z) * 0.5 * s;
    const g = new THREE.Group();
    g.add(obj);
    obj.traverse((n) => { if (n.isMesh) { n.castShadow = true; n.receiveShadow = true; n.frustumCulled = false; } });
    scene.add(g);
    return g;
  }

  // The mount GLB has 16 sibling meshes and no pivots: build them here.
  function setupMount(root) {
    const byName = (k) => { const out = []; root.traverse((o) => { if (o.isMesh && o.name.includes(k)) out.push(o); }); return out; };
    const base = root.children[0] || root;
    const pivot = (meshes, at) => {
      const p = new THREE.Group();
      p.position.copy(at);
      base.add(p);
      root.updateMatrixWorld(true);
      meshes.forEach((m) => p.attach(m));
      return p;
    };
    ballPivot = pivot([...byName('Demi-boule'), ...byName('Goupille')], new V3(0, 0, 0));
    ballPivot.rotation.order = 'YXZ';
    gearA = pivot(byName('Pignon_A'), new V3(0, 0, -40));
    gearB = pivot([...byName('Pignon_B'), ...byName('Plateau_B'), ...byName('Axe_hexagonal')], new V3(0, 0, 0));
    root.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.frustumCulled = false; } });
    root.scale.setScalar(MOUNT_S);
    root.rotation.y = -Math.PI / 2;               // laser (+z) towards the robot front (−x)
    root.position.set(-30.7 * MOUNT_S, ROBOT_H + 98 * MOUNT_S, 0); // footprint centred on the top plate
    robot.add(root);
    return root;
  }
  const local = new V3();
  function aimMount(world) {
    ballPivot.parent.worldToLocal(local.copy(world));
    const pan = Math.atan2(local.x, local.z);
    const tilt = Math.atan2(-local.y, Math.hypot(local.x, local.z));
    ballPivot.rotation.set(tilt, pan, 0);
    gearA.rotation.x = -tilt * 1.46;
    gearB.rotation.y = pan;
  }

  function pose(phase, action) {
    person.position.set(0, 0, 0);
    if (currentAction !== action) { currentAction?.stop(); action.reset().play(); currentAction = action; }
    const d = action.getClip().duration;
    action.time = ((phase % d) + d) % d;
    mixer.update(0);
    person.updateMatrixWorld(true);
    return { left: leftFoot.getWorldPosition(new V3()), right: rightFoot.getWorldPosition(new V3()) };
  }
  function personAt(x, z, action, t) { pose(t, action); person.position.set(x, 0, z); person.updateMatrixWorld(true); }

  // Port of presentation 1: footsteps are planned by sampling the walk clip, so feet land on the targets.
  function planWalk() {
    let best = -Infinity;
    for (let i = 0; i < 240; i++) {
      const ph = (i / 240) * walkDur;
      const p = pose(ph, actions.Walk);
      const d = p.left.x - p.right.x;
      if (d > best) { best = d; startPhase = ph; }
    }
    let rootX = -1.6;
    frames = [];
    for (let k = 0; k < STEPS; k++) {
      const from = startPhase + (k * walkDur) / 2, to = from + walkDur / 2;
      const a = pose(from, actions.Walk), b = pose(to, actions.Walk);
      const support = k % 2 === 0 ? 'left' : 'right', moving = k % 2 === 0 ? 'right' : 'left';
      const endX = rootX + a[support].x - b[support].x;
      const target = b[moving].clone(); target.x += endX; target.y = 0;
      const robotEnd = new V3(target.x + 0.95, 0, 0);
      const robotStart = k === 0 ? robotEnd.clone().add(new V3(-0.4, 0, 0)) : frames[k - 1].robotEnd.clone();
      frames.push({ from, to, support, moving, anchor: a[support].x + rootX, target, robotStart, robotEnd });
      footprints[k].position.set(target.x, 0.012, target.z);
      rootX = endX;
    }
  }

  // ---------- Camera presets ----------
  const focus = new V3();
  let follow = false;
  let camAnim = null;
  const PRESETS = {
    [S.INTRO]: { offset: new V3(2.9, 2.3, 5.6), follow: true },
    [S.UX]: { offset: new V3(0.6, 1.9, 6.0), follow: true },
    [S.PARTS]: { focus: new V3(-0.3, 0.72, 0), offset: new V3(1.5, 0.75, 4.1) },
    [S.VISION]: { focus: new V3(-0.1, 0.9, 0), offset: new V3(1.6, 1.25, 4.9) },
    [S.POSTURE]: { focus: new V3(-0.6, 0.98, 0), offset: new V3(3.6, 0.25, 1.15) },
    [S.DIFF]: { focus: new V3(0.0, 0.85, 0), offset: new V3(0.6, 1.1, 5.0) },
    [S.FSM]: { focus: new V3(0, 0, 0.5), offset: new V3(0, 4.4, 3.2) },
    [S.LASER]: { focus: new V3(0.1, 0.3, 0), offset: new V3(0.45, 0.4, 1.85) },
    [S.ARCH]: { focus: new V3(0, 0.62, 0.1), offset: new V3(0, 1.5, 6.2) },
    [S.CYCLE]: { offset: new V3(3.2, 3.0, 5.2), follow: true, lift: -0.35 },
    [S.STATUS]: { focus: new V3(0, 0.5, 0), offset: new V3(0, 0.95, 5.2) },
    [S.END]: { focus: new V3(-0.1, 0.62, 0), offset: new V3(2.2, 1.4, 3.9) },
  };
  const portraitScale = () => (innerWidth <= 760 && innerHeight > innerWidth ? 1.2 : 1);
  function presetFocus() {
    const p = PRESETS[slide];
    if (p.follow) return new V3(person ? person.position.x + 0.85 : 0, 0.7 + (p.lift || 0), 0);
    return p.focus.clone();
  }
  function moveCamera(animate) {
    const p = PRESETS[slide];
    follow = !!p.follow;
    // narrower right half (4:3 projectors): step back so the stage still fits
    const off = p.offset.clone().multiplyScalar(portraitScale() * Math.max(1, 0.89 / camera.aspect));
    const f = presetFocus();
    controls.autoRotate = slide === S.END && !reduced;
    controls.autoRotateSpeed = 0.5;
    if (!animate || reduced) {
      camAnim = null; focus.copy(f); controls.target.copy(f); camera.position.copy(f).add(off); controls.update();
      return;
    }
    const from = new THREE.Spherical().setFromVector3(camera.position.clone().sub(controls.target));
    const to = new THREE.Spherical().setFromVector3(off);
    to.theta = from.theta + Math.atan2(Math.sin(to.theta - from.theta), Math.cos(to.theta - from.theta));
    camAnim = { t: 0, from, to, target: controls.target.clone() };
  }
  controls.addEventListener('start', () => { camAnim = null; });
  function updateCamera(dt) {
    const f = presetFocus();
    if (camAnim) {
      camAnim.t = Math.min(1.25, camAnim.t + dt);
      const e = smooth(camAnim.t / 1.25);
      const sph = new THREE.Spherical(lerp(camAnim.from.radius, camAnim.to.radius, e), lerp(camAnim.from.phi, camAnim.to.phi, e), lerp(camAnim.from.theta, camAnim.to.theta, e));
      controls.target.lerpVectors(camAnim.target, f, e);
      camera.position.copy(controls.target).add(new V3().setFromSpherical(sph));
      focus.copy(f);
      if (camAnim.t >= 1.25) camAnim = null;
    } else if (follow) {
      const d = f.clone().sub(focus);
      camera.position.add(d); controls.target.add(d); focus.copy(f);
    }
  }

  function resize() {
    const { clientWidth: w, clientHeight: h } = $('viewport');
    renderer.setSize(w, h);
    if (w <= 760 && h > w) { camera.setViewOffset(w, h * 0.44, 0, -h * 0.56, w, h); camera.aspect = w / (h * 0.44); }
    else { camera.setViewOffset(w * 0.5, h, -w * 0.5, 0, w, h); camera.aspect = (w * 0.5) / h; }
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe($('viewport'));
  resize();

  // ---------- Per-slide updates ----------
  function hideAll() {
    skel.visible = false; frustum.visible = false; posture.visible = false; diff.visible = false; fsm.visible = false; arch.visible = false; status.visible = false;
    sensorBand.visible = false; cameraBlock.visible = true; robotHalo.visible = false;
    footprints.forEach((f) => { f.visible = false; });
    aim.on = false;
    if (person) person.visible = true;
    if (robot) { robot.visible = true; robot.rotation.set(0, 0, 0); }
    tickInfo.phase4 = tickInfo.phase5 = tickInfo.vision = tickInfo.fsm = -1;
  }

  function updateWalk() {
    const k = Math.min(STEPS - 1, Math.floor(walkT / T.seg));
    const t = walkT - k * T.seg;
    const f = frames[k];
    const s = smooth((t - T.mark) / (T.step - T.mark));
    const p = pose(lerp(f.from, f.to, s), actions.Walk);
    person.position.x = f.anchor - p[f.support].x;
    person.updateMatrixWorld(true);
    robot.position.lerpVectors(f.robotStart, f.robotEnd, smooth(t / T.back));
    robot.rotation.y = Math.sin(walkT * 0.9) * 0.03;
    robotHalo.visible = true; robotHalo.position.set(robot.position.x, 0.009, robot.position.z);
    footprints.forEach((fp, j) => { fp.visible = j < k || (j === k && s >= 0.98); });
    // estimate: landmarks + field of view
    const est = t >= T.back && t < T.est;
    const e = est ? Math.min(smooth((t - T.back) / 0.25), smooth((T.est - t) / 0.25)) : 0;
    if (e > 0) {
      skel.visible = true; updateSkeleton(BONES.length, true, e);
      frustum.visible = true; frFaces.material.opacity = 0.07 * e; frLines.material.opacity = 0.55 * e;
      updateFrustum(person.position.x + 0.05, { faces: true, image: 0, scan: (t - T.back) / (T.est - T.back) });
    }
    // mark: the beam sweeps from the robot to the target, and stays until the foot lands
    if (t >= T.choose && s < 0.98) {
      const u = smooth((t - T.choose) / ((T.mark - T.choose) * 0.8));
      const start = new V3(robot.position.x - 0.3, 0, 0);
      aim.on = true;
      aim.want.lerpVectors(start, f.target, u);
      aim.cur.copy(aim.want);
      spotFoot.visible = u > 0.95;
      spotFoot.rotation.set(-Math.PI / 2, 0, -Math.PI / 2);
    }
    const ph = t < T.back ? 0 : t < T.est ? 1 : t < T.choose ? 2 : t < T.mark ? 3 : 4;
    const bounds = [0, T.back, T.est, T.choose, T.mark, T.step];
    tickInfo.phase5 = ph;
    tickInfo.phase5Frac = clamp((t - bounds[ph]) / (bounds[ph + 1] - bounds[ph]), 0, 1);
    tickInfo.phase4 = [0, 1, 2, 2, 3][ph];
  }

  const vec = new V3();
  function update(dt) {
    hideAll();
    const t = slideT;
    switch (slide) {
      case S.INTRO: case S.UX: case S.CYCLE:
        updateWalk();
        break;

      case S.PARTS: {
        personAt(-1.0, 0, actions.Idle, t);
        robot.position.set(0.3, 0, 0);
        robot.rotation.y = Math.sin(t * 0.35) * 0.55;
        sensorBand.visible = true;
        leftHand.getWorldPosition(sensorBand.position);
        sensorBand.rotation.set(0, Math.PI / 2, 0);
        const tgt = new V3(-0.3, 0, 0.1 * Math.sign(Math.sin(t * 0.8)) || 0.1);
        aim.on = true; aim.want.copy(tgt);
        break;
      }

      case S.VISION: {
        personAt(-0.6, 0, actions.Idle, t);
        robot.position.set(0.55, 0, 0);
        const c = t % 8;
        const stage = Math.floor(c / 2);
        tickInfo.vision = stage;
        frustum.visible = true;
        frFaces.material.opacity = 0.07; frLines.material.opacity = 0.55;
        updateFrustum(-0.6, { faces: true, image: stage >= 1 ? 1 : 0, scan: stage === 0 ? (c / 2) : -1 });
        if (stage >= 2) {
          skel.visible = true;
          const n = stage === 2 ? Math.floor(((c - 4) / 2) * BONES.length) + 1 : BONES.length;
          updateSkeleton(n, stage === 3, 1);
        }
        break;
      }

      case S.POSTURE: {
        personAt(-0.6, 0, actions.Idle, t);
        robot.visible = false; // this slide focuses on the person
        skel.visible = true; updateSkeleton(BONES.length, true, 1);
        posture.visible = true; updatePosture();
        break;
      }

      case S.DIFF: {
        personAt(-0.75, 0, actions.Idle, t);
        robot.position.set(0.85, 0, 0);
        skel.visible = true; updateSkeleton(BONES.length, true, 0.55);
        sensorBand.visible = true; leftHand.getWorldPosition(sensorBand.position); sensorBand.rotation.set(0, Math.PI / 2, 0);
        diff.visible = true;
        ruleBox.position.set(0.0, 1.45, 0);
        const i = Math.floor(t / 3.2) % 4;
        const targets = [new V3(-0.38, 0, 0.1), new V3(-0.2, 0, -0.1), new V3(-0.32, 0, 0.1), new V3(-0.12, 0, -0.1)];
        aim.on = true; aim.want.copy(targets[i]);
        setFlow(0, J[2], ruleBox.position.clone().add(new V3(-0.2, 0, 0)), t);
        setFlow(1, sensorBand.position, ruleBox.position.clone().add(new V3(-0.2, -0.1, 0)), t + 0.3);
        setFlow(2, ruleBox.position.clone().add(new V3(0, -0.12, 0)), aim.cur, t + 0.6);
        ge(t);
        break;
      }

      case S.FSM: {
        person.visible = false;
        fsm.visible = true;
        const DWELL = 2.1, MOVE = 0.8, PER = DWELL + MOVE;
        const loop = Math.floor(t / (PER * 4));
        const u = t % (PER * 4);
        const st = Math.floor(u / PER), w = u % PER;
        tickInfo.fsm = st;
        pucks.forEach((p, i) => { const on = i === st; p.glow.material.opacity = on ? 0.9 : 0; p.glow.material.transparent = true; p.puck.position.y = on ? 0.045 : 0.025; });
        fsmLabels.forEach((L, i) => L.el.classList.toggle('active', i === st));
        const side = loop % 2 === 0 ? 'left' : 'right';
        fsmLabels[2].el.querySelector('small').textContent = `${side} foot`;
        if (w < DWELL) token.position.copy(FSM_NODES[st].pos).add(new V3(0, 0.13 + Math.sin(t * 4) * 0.01, 0));
        else { const c = fsmEdges[st]; token.position.copy(c.getPoint(smooth((w - DWELL) / MOVE))).add(new V3(0, 0.06, 0)); }
        // the robot in the middle acts out the current state
        robot.position.set(0.05, 0, 0.05);
        if (st === 0 && w < DWELL) robot.position.x += smooth(w / DWELL) * 0.18;
        if (st === 1 && w < DWELL) { robot.rotation.y = Math.sin(w * 3) * 0.12; }
        if (st === 2 || st === 3) {
          aim.on = true; aim.want.set(-0.5, 0, side === 'left' ? 0.11 : -0.11);
        }
        break;
      }

      case S.LASER: {
        personAt(-0.95, 0, actions.Idle, t);
        robot.position.set(0.42, 0, 0);
        const i = Math.floor(t / 2.6) % 4;
        const targets = [new V3(-0.32, 0, 0.1), new V3(-0.12, 0, -0.1), new V3(-0.42, 0, -0.1), new V3(-0.22, 0, 0.1)];
        aim.on = true; aim.want.copy(targets[i]);
        break;
      }

      case S.ARCH: {
        person.visible = false; arch.visible = true;
        robot.position.set(1.12, 0, 0.05);
        robot.rotation.y = -0.35;
        const L = cmdPath.getLength();
        packets.forEach((m, i) => {
          let u = ((t * 0.16 + i * 0.25) % 1);
          if (i % 2) u = 1 - u;          // telemetry flows back
          m.position.copy(cmdPath.getPointAt(u));
          m.scale.setScalar(L > 0 ? 1 : 0);
        });
        visionSlab.position.y = P.vision.y + Math.sin(t * 1.4) * 0.025;
        break;
      }

      case S.STATUS: {
        person.visible = false; robot.visible = false; status.visible = true; cameraBlock.visible = false;
        blocks.forEach((b) => {
          const k = smooth((t - b.delay) / 0.55);
          b.m.position.y = b.y + (1 - k) * 1.4;
          b.m.visible = t > b.delay - 0.02;
          if (b.kind === 'tbd') b.m.material.opacity = 0.25 + 0.15 * Math.sin(t * 2 + b.y * 8);
        });
        break;
      }

      case S.END: {
        personAt(-0.85, 0, actions.Idle, t);
        robot.position.set(0.55, 0, 0);
        const i = Math.floor(t / 2.4) % 2;
        aim.on = true; aim.want.set(-0.25 - (i ? 0.12 : 0), 0, i ? -0.1 : 0.1);
        break;
      }
    }

    // laser: smooth aim, beam from the mount's ball to the spot
    robot.updateMatrixWorld(true);
    beam.visible = beamGlow.visible = spot.visible = aim.on;
    if (aim.on) {
      if (!WALK_SLIDES.has(slide)) { aim.cur.lerp(aim.want, 1 - Math.exp(-dt * 5)); spotFoot.visible = aim.cur.distanceTo(aim.want) < 0.01; spotFoot.rotation.set(-Math.PI / 2, 0, -Math.PI / 2); }
      aimMount(aim.cur);
      mount.updateMatrixWorld(true);
      ballPivot.localToWorld(laserExit.set(0, 0, 27));
      stretch(beam, laserExit, aim.cur);
      stretch(beamGlow, laserExit, aim.cur);
      spot.position.set(aim.cur.x, 0, aim.cur.z);
      spotHalo.scale.setScalar(1 + 0.15 * Math.sin(performance.now() / 160));
    } else if (ballPivot) {
      ballPivot.rotation.set(0.35, 0, 0);
    }
  }

  // ---------- Vital signs canvas (simulated, as in presentation 1) ----------
  const wave = $('pulse-wave'), wctx = wave.getContext('2d');
  function ge(t) {
    $('pulse-bpm').textContent = String(78 + Math.round(Math.sin(t * 0.55)));
    const W = wave.width, H = wave.height;
    wctx.clearRect(0, 0, W, H);
    wctx.strokeStyle = '#d5ded5'; wctx.lineWidth = 1;
    wctx.beginPath(); wctx.moveTo(0, H * 0.6); wctx.lineTo(W, H * 0.6); wctx.stroke();
    const ecg = (x) => { const r = ((x % 1) + 1) % 1; const g = (c, w, a) => a * Math.exp(-(((r - c) / w) ** 2)); return g(0.17, 0.038, 0.1) - g(0.34, 0.018, 0.13) + g(0.39, 0.015, 0.85) - g(0.44, 0.024, 0.28) + g(0.65, 0.07, 0.17); };
    wctx.strokeStyle = '#447e5b'; wctx.lineWidth = 2.8; wctx.lineJoin = 'round';
    wctx.beginPath();
    for (let x = 0; x <= W; x++) { const y = H * 0.6 - ecg((x / W) * 3 - (t * 78) / 60) * H * 0.52; x === 0 ? wctx.moveTo(x, y) : wctx.lineTo(x, y); }
    wctx.stroke();
  }

  // ---------- Labels attached to the robot (slide 3, 8) ----------
  function robotAnchor(v) { const o = new THREE.Object3D(); o.position.copy(v); return o; }

  // ---------- Load ----------
  (async () => {
    try {
      const loader = new GLTFLoader();
      const detail = $('loading-detail');
      let loaded = 0;
      const progress = () => { detail.textContent = `${++loaded} / 3 models`; };
      const [pg, rg, mg] = await Promise.all(['models/person.glb', 'models/robot.glb', 'models/laser-mount.glb'].map((u) => loader.loadAsync(u).then((g) => { progress(); return g; })));
      person = fit(pg.scene, 1.72);
      person.rotation.y = Math.PI / 2;
      robot = fit(rg.scene, ROBOT_H);
      robot.add(cameraBlock);
      mount = setupMount(mg.scene);
      mixer = new THREE.AnimationMixer(pg.scene);
      for (const name of ['Walk', 'Idle', 'Run', 'Jump', 'Loose']) {
        const clip = THREE.AnimationClip.findByName(pg.animations, name);
        if (clip) actions[name] = mixer.clipAction(clip);
      }
      if (!actions.Walk || !actions.Idle) throw new Error('Walk/Idle animation missing.');
      walkDur = actions.Walk.getClip().duration;
      leftFoot = pg.scene.getObjectByName('LeftFoot_00');
      rightFoot = pg.scene.getObjectByName('RightFoot_025');
      leftHand = pg.scene.getObjectByName('LeftHand_011');
      bones = BONES.map((n) => pg.scene.getObjectByName(n));
      if (!leftFoot || !rightFoot || bones.some((b) => !b)) throw new Error('Body landmarks missing.');

      // anchors for labels on the robot
      const A = Object.fromEntries(Object.entries(anchors).map(([k, v]) => { const o = robotAnchor(v); robot.add(o); return [k, o]; }));
      const gA = new THREE.Object3D(); gA.position.set(0, 0, 0); gearA.add(gA);
      const gB = new THREE.Object3D(); gB.position.set(0, -40, 0); gearB.add(gB);
      label('Laser + two-gear mount <span class="pill plan">Planned</span>', { slides: [S.PARTS], obj: A.mount, offset: new V3(0, 0.06, 0) });
      label('LiDAR', { slides: [S.PARTS], obj: A.lidar, offset: new V3(0.05, 0, 0.12), anchor: 'center' });
      label('Raspberry Pi · OpenCR', { slides: [S.PARTS], obj: A.boards, offset: new V3(0.1, 0, -0.1), anchor: 'center' });
      label('TurtleBot3 Burger <span class="pill ok">Existing</span>', { slides: [S.PARTS], obj: A.base, offset: new V3(0, -0.02, 0.08), anchor: 'top' });
      label('BRIO 105 webcam <span class="pill plan">Planned</span>', { slides: [S.PARTS, S.VISION], obj: cameraBlock, offset: new V3(0, 0.05, 0) });
      label('Gear 1', { slides: [S.LASER], obj: gA, offset: new V3(0, 0.0, -0.04), anchor: 'center' });
      label('Gear 2', { slides: [S.LASER], obj: gB, offset: new V3(0, -0.02, 0.05), anchor: 'top' });
      label('Laser', { cls: 'laser', slides: [S.LASER], obj: ballPivot, offset: new V3(0, 0.06, 0) });
      label('Target on the floor', { cls: 'laser', slides: [S.LASER, S.END], obj: spot, offset: new V3(0, 0.02, 0.12), anchor: 'top' });
      label('Marker <small>digital point on the image</small>', { cls: 'marker', slides: [S.VISION], obj: markers[6], offset: new V3(0, -0.04, 0.05), anchor: 'top' });
      label('Image frame', { cls: 'plain', slides: [S.VISION], at: new V3(-0.78, 1.95, -0.62) });

      planWalk();
      ready = true;
      update(0);
      moveCamera(false);
      $('loading').hidden = true;
    } catch (err) {
      console.error(err);
      $('loading').querySelector('strong').textContent = 'The 3D scene could not be loaded';
      $('loading-detail').textContent = 'Reload the page to try again. You can still navigate the slides.';
      $('loading').querySelector('.loader').style.display = 'none';
    }
  })();

  let last = performance.now();
  renderer.setAnimationLoop((now) => {
    const dt = clamp((now - last) / 1000, 0, 0.1);
    last = now;
    if (ready) {
      if (playing && !document.hidden) { walkT = (walkT + dt) % (TOTAL + 1.0); slideT += dt; }
      update(dt);
      updateCamera(dt);
      onTick(tickInfo);
    }
    controls.update(dt);
    renderer.render(scene, camera);
    updateLabels();
  });

  return {
    setSlide(i) {
      slide = i; slideT = 0; walkT = 0;
      if (!reduced) playing = true;
      if (ready) { update(0); moveCamera(true); }
    },
    toggle() { playing = !playing; },
    restart() { slideT = 0; walkT = 0; playing = !reduced; },
    seek(s) { slideT = s; walkT = s % (TOTAL + 1); playing = false; if (ready) { update(0); moveCamera(false); } },
    get ready() { return ready; },
    get playing() { return playing; },
  };
}
