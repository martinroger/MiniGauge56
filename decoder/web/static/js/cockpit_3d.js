/**
 * MiniGauge 3D Cyber-Cockpit & Drive Trajectory Replayer
 * =======================================================
 * Three.js WebGL trajectory visualizer, reactive vehicle particle streamers,
 * smoothed chase camera with strict Z-up, mathematically aligned SVG gauges,
 * vertical reference drop stanchions, G-vector helpers, and synchronized dual cluster.
 */

(function () {
  'use strict';

  // --- State Variables ---
  let trajectoryData = null;
  let points = [];
  let currentIndex = 0;
  let currentProgress = 0.0;
  let isPlaying = false;
  let playSpeed = 1.0;
  let zScale = 2.2;
  let particlesEnabled = true;
  let gVectorsEnabled = false;
  let cameraMode = 'chase'; // 'chase', 'hood', 'free', 'top'
  let hudVisible = true;

  // Camera smoothing & interactive zoom state
  let chaseDistance = 140;
  let topAltitude = 850;
  const smoothVehPos = new THREE.Vector3();
  const smoothDir = new THREE.Vector3(0, 1, 0);

  // --- Three.js Globals ---
  let scene, camera, renderer, controls;
  let trajectoryLine, stanchionsLine, vehicleMesh;
  let gArrowsGroup, arrowLon, arrowLat;
  let particleGeo, particleMat, particlePoints;
  const MAX_PARTICLES = 1200;
  const particlePool = [];
  const stanchionIndices = [];

  // DOM Elements
  const container = document.getElementById('viewport-container');
  const canvas = document.getElementById('canvas3d');
  const slider = document.getElementById('timeline-slider');
  const timeCurrentEl = document.getElementById('time-current');
  const timeTotalEl = document.getElementById('time-total');
  const btnPlay = document.getElementById('btn-play');
  const playIcon = document.getElementById('play-icon');
  const playText = document.getElementById('play-text');
  const zSlider = document.getElementById('z-scale-slider');
  const zVal = document.getElementById('z-scale-val');
  const btnParticles = document.getElementById('btn-particles');
  const chkGVectors = document.getElementById('chk-g-vectors');
  const toggleHudBtn = document.getElementById('toggle-hud-btn');
  const hudToggleLabel = document.getElementById('hud-toggle-label');
  const topBar = document.getElementById('top-bar');
  const bottomGroup = document.getElementById('bottom-group');
  const loadingOverlay = document.getElementById('loading-overlay');
  const logSelect = document.getElementById('log-select');
  const gMeterPod = document.getElementById('g-meter-pod');

  // --- Color Utilities for Speed Heatmap ---
  function speedToColor(spd) {
    // Speed range: 15 km/h to 120 km/h
    const s = Math.min(1.0, Math.max(0.0, (spd - 15) / 105));
    if (s < 0.33) {
      // Cyan (0, 240, 255) -> Emerald (0, 255, 102)
      const t = s / 0.33;
      return new THREE.Color(0, (240 + t * 15) / 255, (255 - t * 153) / 255);
    } else if (s < 0.66) {
      // Emerald (0, 255, 102) -> Amber (255, 170, 0)
      const t = (s - 0.33) / 0.33;
      return new THREE.Color((t * 255) / 255, (255 - t * 85) / 255, (102 - t * 102) / 255);
    } else {
      // Amber (255, 170, 0) -> Crimson / Neon Red (255, 42, 85)
      const t = (s - 0.66) / 0.34;
      return new THREE.Color(1.0, (170 - t * 128) / 255, (t * 85) / 255);
    }
  }

  // Pure white soft radial particle sprite
  function createParticleTexture() {
    const pCanvas = document.createElement('canvas');
    pCanvas.width = 64;
    pCanvas.height = 64;
    const ctx = pCanvas.getContext('2d');
    const grad = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0, 'rgba(255, 255, 255, 1.0)');
    grad.addColorStop(0.35, 'rgba(255, 255, 255, 0.85)');
    grad.addColorStop(0.7, 'rgba(255, 255, 255, 0.25)');
    grad.addColorStop(1, 'rgba(255, 255, 255, 0.0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 64, 64);
    const tex = new THREE.CanvasTexture(pCanvas);
    tex.needsUpdate = true;
    return tex;
  }

  // --- Initialize Three.js Scene ---
  function initThree() {
    scene = new THREE.Scene();
    // Vast linear fog to preserve distant trajectory without washing out near scene
    scene.fog = new THREE.Fog(0x05070c, 8000, 45000);

    const width = container.clientWidth || window.innerWidth;
    const height = container.clientHeight || window.innerHeight;

    // Significant render distance (up to 45,000 meters)
    camera = new THREE.PerspectiveCamera(55, width / height, 1, 45000);
    // STRICTLY MAINTAIN Z AS UP
    camera.up.set(0, 0, 1);
    camera.position.set(0, -300, 200);

    renderer = new THREE.WebGLRenderer({
      canvas: canvas,
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // Controls for Free Orbit mode
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.object.up.set(0, 0, 1);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.maxDistance = 15000;

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.75);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0x00f0ff, 0.9);
    dirLight.position.set(2000, 3000, 5000);
    scene.add(dirLight);

    // Expansive Ground Grid Helper (30,000 meters)
    const grid = new THREE.GridHelper(30000, 120, 0x00f0ff, 0x1e293b);
    grid.rotation.x = Math.PI / 2;
    grid.position.z = -1;
    scene.add(grid);

    // Vehicle Avatar: Forward-Facing 3D Cone (Apex points along motion direction)
    const vehGeo = new THREE.ConeGeometry(5.5, 18, 24);
    const vehMat = new THREE.MeshLambertMaterial({
      color: 0x00f0ff,
      emissive: 0x002233,
      emissiveIntensity: 0.35,
    });
    vehicleMesh = new THREE.Mesh(vehGeo, vehMat);
    scene.add(vehicleMesh);

    // Vehicle Frame G-Vector Arrows Group
    gArrowsGroup = new THREE.Group();
    gArrowsGroup.visible = false;
    scene.add(gArrowsGroup);

    // Longitudinal Arrow (Forward: Accel Green, Backward: Braking Red)
    arrowLon = new THREE.ArrowHelper(
      new THREE.Vector3(0, 1, 0),
      new THREE.Vector3(0, 0, 0),
      25,
      0x00ff66,
      12,
      8
    );
    // Lateral Arrow (Cornering: Amber)
    arrowLat = new THREE.ArrowHelper(
      new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(0, 0, 0),
      25,
      0xffaa00,
      12,
      8
    );
    arrowLon.line.material.depthTest = false;
    arrowLon.cone.material.depthTest = false;
    arrowLon.renderOrder = 999;
    arrowLat.line.material.depthTest = false;
    arrowLat.cone.material.depthTest = false;
    arrowLat.renderOrder = 999;
    gArrowsGroup.add(arrowLon);
    gArrowsGroup.add(arrowLat);

    // Particles System Emitted from Vehicle Dot
    initVehicleParticles();

    window.addEventListener('resize', onWindowResize);
  }

  // --- Particles Emitted from Vehicle Dot ---
  function initVehicleParticles() {
    particleGeo = new THREE.BufferGeometry();
    const positions = new Float32Array(MAX_PARTICLES * 3);
    const colors = new Float32Array(MAX_PARTICLES * 3);

    for (let i = 0; i < MAX_PARTICLES; i++) {
      particlePool.push({
        x: 0, y: 0, z: 0,
        vx: 0, vy: 0, vz: 0,
        r: 0, g: 0.94, b: 1.0,
        life: 0,
        maxLife: 1.5,
        active: false,
      });
      positions[i * 3] = 0;
      positions[i * 3 + 1] = 0;
      positions[i * 3 + 2] = 0;

      colors[i * 3] = 0;
      colors[i * 3 + 1] = 0;
      colors[i * 3 + 2] = 0;
    }

    particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    particleGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    particleMat = new THREE.PointsMaterial({
      size: 8.0,
      map: createParticleTexture(),
      vertexColors: true,
      transparent: true,
      opacity: 0.95,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    });

    particlePoints = new THREE.Points(particleGeo, particleMat);
    // CRITICAL: Disable frustum culling on dynamic particle pool
    particlePoints.frustumCulled = false;
    scene.add(particlePoints);
  }

  function updateVehicleParticles(interpPt, dt) {
    if (!particlesEnabled || !particlePoints) return;

    const pos = particleGeo.attributes.position.array;
    const col = particleGeo.attributes.color.array;

    // Spawn rate scales dynamically with RPM and vehicle speed
    const spawnCount = isPlaying
      ? Math.min(24, Math.floor(6 + (interpPt.rpm / 8000) * 10 + (interpPt.speed / 120) * 8))
      : 0;

    const spdFactor = Math.max(0.4, interpPt.speed / 35);
    const backDir = smoothDir.clone().multiplyScalar(-1);
    const speedCol = speedToColor(interpPt.speed);

    let spawned = 0;
    for (let i = 0; i < MAX_PARTICLES && spawned < spawnCount; i++) {
      const p = particlePool[i];
      if (!p.active) {
        p.active = true;
        p.life = 0;
        p.maxLife = 0.7 + Math.random() * 0.45;

        if (cameraMode === 'hood') {
          // Hood View: warp streaks stream past cockpit windshield
          const sideOffset = (Math.random() - 0.5) * 12;
          p.x = interpPt.x + smoothDir.x * 12 - smoothDir.y * sideOffset;
          p.y = interpPt.y + smoothDir.y * 12 + smoothDir.x * sideOffset;
          p.z = interpPt.z + 4 + (Math.random() - 0.5) * 2;

          p.vx = backDir.x * spdFactor * 60;
          p.vy = backDir.y * spdFactor * 60;
          p.vz = (Math.random() - 0.5) * 6;
        } else {
          // Chase / Orbit / Top: jet wake streaming from rear base of the cone
          p.x = interpPt.x - smoothDir.x * 8 + (Math.random() - 0.5) * 2;
          p.y = interpPt.y - smoothDir.y * 8 + (Math.random() - 0.5) * 2;
          p.z = interpPt.z + (Math.random() - 0.5) * 1.5;

          const spreadX = (Math.random() - 0.5) * 0.25;
          const spreadY = (Math.random() - 0.5) * 0.25;
          const spreadZ = (Math.random() - 0.5) * 0.15;

          p.vx = (backDir.x + spreadX) * spdFactor * 45;
          p.vy = (backDir.y + spreadY) * spdFactor * 45;
          p.vz = (backDir.z + spreadZ) * spdFactor * 25;
        }

        p.r = speedCol.r;
        p.g = speedCol.g;
        p.b = speedCol.b;

        spawned++;
      }
    }

    // Update existing particles
    for (let i = 0; i < MAX_PARTICLES; i++) {
      const p = particlePool[i];
      if (p.active) {
        p.life += dt;
        if (p.life >= p.maxLife) {
          p.active = false;
          col[i * 3] = 0;
          col[i * 3 + 1] = 0;
          col[i * 3 + 2] = 0;
        } else {
          p.x += p.vx * dt;
          p.y += p.vy * dt;
          p.z += p.vz * dt;

          pos[i * 3] = p.x;
          pos[i * 3 + 1] = p.y;
          pos[i * 3 + 2] = p.z;

          // Luminous fade
          const alpha = Math.pow(1.0 - (p.life / p.maxLife), 0.7);
          col[i * 3] = p.r * alpha;
          col[i * 3 + 1] = p.g * alpha;
          col[i * 3 + 2] = p.b * alpha;
        }
      }
    }

    particleGeo.attributes.position.needsUpdate = true;
    particleGeo.attributes.color.needsUpdate = true;
  }

  function onWindowResize() {
    const width = container.clientWidth || window.innerWidth;
    const height = container.clientHeight || window.innerHeight;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }

  // --- Gaussian Smoothing over Trajectory Coordinates ---
  function computeSmoothedCoordinates(pts) {
    const n = pts.length;
    if (n < 3) {
      for (let i = 0; i < n; i++) {
        pts[i].smoothX = pts[i].x;
        pts[i].smoothY = pts[i].y;
        pts[i].smoothZ = pts[i].z;
      }
      return;
    }

    const halfWin = 8;
    for (let i = 0; i < n; i++) {
      let sumX = 0, sumY = 0, sumZ = 0, sumW = 0;
      for (let j = Math.max(0, i - halfWin); j <= Math.min(n - 1, i + halfWin); j++) {
        const d = j - i;
        const w = Math.exp(-0.5 * (d * d) / 6.0);
        sumX += pts[j].x * w;
        sumY += pts[j].y * w;
        sumZ += pts[j].z * w;
        sumW += w;
      }
      pts[i].smoothX = sumX / sumW;
      pts[i].smoothY = sumY / sumW;
      pts[i].smoothZ = sumZ / sumW;
    }
  }

  // --- Build Trajectory Geometry & Vertical Stanchions ---
  function buildTrajectoryGeometry() {
    if (trajectoryLine) scene.remove(trajectoryLine);
    if (stanchionsLine) scene.remove(stanchionsLine);
    stanchionIndices.length = 0;

    if (points.length < 2) return;

    const n = points.length;
    const linePositions = new Float32Array((n - 1) * 2 * 3);
    const lineColors = new Float32Array((n - 1) * 2 * 3);

    let posIdx = 0;
    for (let i = 0; i < n - 1; i++) {
      const p1 = points[i];
      const p2 = points[i + 1];

      const sX1 = p1.smoothX !== undefined ? p1.smoothX : p1.x;
      const sY1 = p1.smoothY !== undefined ? p1.smoothY : p1.y;
      const sZ1 = (p1.smoothZ !== undefined ? p1.smoothZ : p1.z) * zScale;

      const sX2 = p2.smoothX !== undefined ? p2.smoothX : p2.x;
      const sY2 = p2.smoothY !== undefined ? p2.smoothY : p2.y;
      const sZ2 = (p2.smoothZ !== undefined ? p2.smoothZ : p2.z) * zScale;

      // Segment Start
      linePositions[posIdx] = sX1;
      linePositions[posIdx + 1] = sY1;
      linePositions[posIdx + 2] = sZ1;

      // Segment End
      linePositions[posIdx + 3] = sX2;
      linePositions[posIdx + 4] = sY2;
      linePositions[posIdx + 5] = sZ2;

      // Initial color: all greyed future
      lineColors[posIdx] = 0.58;
      lineColors[posIdx + 1] = 0.64;
      lineColors[posIdx + 2] = 0.72;

      lineColors[posIdx + 3] = 0.58;
      lineColors[posIdx + 4] = 0.64;
      lineColors[posIdx + 5] = 0.72;

      posIdx += 6;
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(linePositions, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(lineColors, 3));

    const mat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.9,
      linewidth: 2,
    });

    trajectoryLine = new THREE.LineSegments(geo, mat);
    scene.add(trajectoryLine);

    // --- Vertical Faint Reference Lines extending down to 0m Altitude Plane ---
    // Sample evenly spaced stanchions every ~20 meters along the track
    let accumDist = 0;
    const sampleIndices = [0];
    for (let i = 1; i < n; i++) {
      const dx = points[i].x - points[i - 1].x;
      const dy = points[i].y - points[i - 1].y;
      accumDist += Math.hypot(dx, dy);
      if (accumDist >= 25.0) {
        sampleIndices.push(i);
        accumDist = 0;
      }
    }
    if (sampleIndices[sampleIndices.length - 1] !== n - 1) {
      sampleIndices.push(n - 1);
    }

    const nStanchions = sampleIndices.length;
    const stanchionPos = new Float32Array(nStanchions * 2 * 3);
    let sIdx = 0;

    for (let k = 0; k < nStanchions; k++) {
      const idx = sampleIndices[k];
      stanchionIndices.push(idx);
      const pt = points[idx];
      const px = pt.smoothX !== undefined ? pt.smoothX : pt.x;
      const py = pt.smoothY !== undefined ? pt.smoothY : pt.y;
      const pz = (pt.smoothZ !== undefined ? pt.smoothZ : pt.z) * zScale;

      // Top vertex at trajectory line
      stanchionPos[sIdx] = px;
      stanchionPos[sIdx + 1] = py;
      stanchionPos[sIdx + 2] = pz;

      // Bottom vertex at 0m altitude plane
      stanchionPos[sIdx + 3] = px;
      stanchionPos[sIdx + 4] = py;
      stanchionPos[sIdx + 5] = 0.0;

      sIdx += 6;
    }

    const stanchionGeo = new THREE.BufferGeometry();
    stanchionGeo.setAttribute('position', new THREE.BufferAttribute(stanchionPos, 3));

    const stanchionMat = new THREE.LineBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.22,
      blending: THREE.AdditiveBlending,
    });

    stanchionsLine = new THREE.LineSegments(stanchionGeo, stanchionMat);
    scene.add(stanchionsLine);
  }

  // --- Dynamic Color Updating (Past: Heatmap, Future: Grey) ---
  function updateTrajectoryColors(activeIdx) {
    if (!trajectoryLine || points.length < 2) return;

    const colors = trajectoryLine.geometry.attributes.color.array;
    const n = points.length;

    let colIdx = 0;
    for (let i = 0; i < n - 1; i++) {
      if (i <= activeIdx) {
        // Driven / Present: Colored by vehicle speed
        const c1 = speedToColor(points[i].speed);
        const c2 = speedToColor(points[i + 1].speed);

        colors[colIdx] = c1.r;
        colors[colIdx + 1] = c1.g;
        colors[colIdx + 2] = c1.b;

        colors[colIdx + 3] = c2.r;
        colors[colIdx + 4] = c2.g;
        colors[colIdx + 5] = c2.b;
      } else {
        // Future / Ahead: Subdued greyed wireframe
        colors[colIdx] = 0.58;
        colors[colIdx + 1] = 0.64;
        colors[colIdx + 2] = 0.72;

        colors[colIdx + 3] = 0.58;
        colors[colIdx + 4] = 0.64;
        colors[colIdx + 5] = 0.72;
      }
      colIdx += 6;
    }

    trajectoryLine.geometry.attributes.color.needsUpdate = true;
  }

  // --- Update Z-Scale in Real Time ---
  function updateGeometryZScale() {
    if (!trajectoryLine || points.length < 2) return;

    const pos = trajectoryLine.geometry.attributes.position.array;
    let posIdx = 0;
    for (let i = 0; i < points.length - 1; i++) {
      const p1 = points[i];
      const p2 = points[i + 1];
      const sZ1 = p1.smoothZ !== undefined ? p1.smoothZ : p1.z;
      const sZ2 = p2.smoothZ !== undefined ? p2.smoothZ : p2.z;
      pos[posIdx + 2] = sZ1 * zScale;
      pos[posIdx + 5] = sZ2 * zScale;
      posIdx += 6;
    }
    trajectoryLine.geometry.attributes.position.needsUpdate = true;

    // Update stanchions top vertex
    if (stanchionsLine && stanchionIndices.length > 0) {
      const sPos = stanchionsLine.geometry.attributes.position.array;
      for (let k = 0; k < stanchionIndices.length; k++) {
        const idx = stanchionIndices[k];
        const pt = points[idx];
        const pz = (pt.smoothZ !== undefined ? pt.smoothZ : pt.z) * zScale;
        sPos[k * 6 + 2] = pz;
      }
      stanchionsLine.geometry.attributes.position.needsUpdate = true;
    }

    const curPt = getInterpolatedPoint(currentProgress) || points[currentIndex];
    if (curPt) updateCamera(curPt);
  }

  // --- Sub-Frame Interpolation for Continuous Smooth Gliding ---
  function getInterpolatedPoint(progress) {
    if (!points || points.length === 0) return null;
    if (points.length === 1) {
      const p = points[0];
      return {
        ...p,
        idx0: 0,
        x: p.smoothX !== undefined ? p.smoothX : p.x,
        y: p.smoothY !== undefined ? p.smoothY : p.y,
        z: (p.smoothZ !== undefined ? p.smoothZ : p.z) * zScale,
      };
    }

    const floatIdx = Math.max(0.0, Math.min(points.length - 1, progress * (points.length - 1)));
    const idx0 = Math.floor(floatIdx);
    const idx1 = Math.min(idx0 + 1, points.length - 1);
    const alpha = floatIdx - idx0;

    const p0 = points[idx0];
    const p1 = points[idx1];

    const sX0 = p0.smoothX !== undefined ? p0.smoothX : p0.x;
    const sY0 = p0.smoothY !== undefined ? p0.smoothY : p0.y;
    const sZ0 = p0.smoothZ !== undefined ? p0.smoothZ : p0.z;

    const sX1 = p1.smoothX !== undefined ? p1.smoothX : p1.x;
    const sY1 = p1.smoothY !== undefined ? p1.smoothY : p1.y;
    const sZ1 = p1.smoothZ !== undefined ? p1.smoothZ : p1.z;

    return {
      t: (1 - alpha) * p0.t + alpha * p1.t,
      x: (1 - alpha) * sX0 + alpha * sX1,
      y: (1 - alpha) * sY0 + alpha * sY1,
      z: ((1 - alpha) * sZ0 + alpha * sZ1) * zScale,
      speed: (1 - alpha) * p0.speed + alpha * p1.speed,
      rpm: (1 - alpha) * p0.rpm + alpha * p1.rpm,
      alt: (1 - alpha) * p0.alt + alpha * p1.alt,
      heading: (1 - alpha) * p0.heading + alpha * p1.heading,
      gear_txt: p0.gear_txt,
      coolant: (1 - alpha) * p0.coolant + alpha * p1.coolant,
      fuel: (1 - alpha) * p0.fuel + alpha * p1.fuel,
      battery: (1 - alpha) * p0.battery + alpha * p1.battery,
      g_lat: (1 - alpha) * p0.g_lat + alpha * p1.g_lat,
      g_lon: (1 - alpha) * p0.g_lon + alpha * p1.g_lon,
      idx0: idx0,
      alpha: alpha,
    };
  }

  // --- Camera Update Modes (Smoothed Lookahead & Strict Z-Up) ---
  function updateCamera(interpPt) {
    const curX = interpPt.x;
    const curY = interpPt.y;
    const curZ = interpPt.z;

    // Vehicle Avatar Placement & Dynamic Speed Color
    vehicleMesh.position.set(curX, curY, curZ);
    const speedCol = speedToColor(interpPt.speed);
    vehicleMesh.material.color.copy(speedCol);

    // Lookahead forward window (distance-based: 35-45m ahead on smoothed path)
    const curIdx = interpPt.idx0;
    let fwdIdx = curIdx + 1;
    let distAccum = 0;
    while (fwdIdx < points.length - 1 && distAccum < 40) {
      const pA = points[fwdIdx - 1];
      const pB = points[fwdIdx];
      distAccum += Math.hypot(pB.x - pA.x, pB.y - pA.y);
      fwdIdx++;
    }
    const forwardPt = points[fwdIdx];
    const fwdX = forwardPt.smoothX !== undefined ? forwardPt.smoothX : forwardPt.x;
    const fwdY = forwardPt.smoothY !== undefined ? forwardPt.smoothY : forwardPt.y;
    const targetDir = new THREE.Vector3(fwdX - curX, fwdY - curY, 0);

    if (targetDir.lengthSq() > 0.01) {
      targetDir.normalize();
      smoothDir.lerp(targetDir, 0.08).normalize();
    } else if (interpPt.heading !== undefined) {
      targetDir.set(Math.sin((interpPt.heading * Math.PI) / 180), Math.cos((interpPt.heading * Math.PI) / 180), 0);
      smoothDir.lerp(targetDir, 0.08).normalize();
    }

    // Orient forward-facing vehicle cone along tangent of motion
    const fwdVec = smoothDir.clone().normalize();
    if (fwdVec.lengthSq() > 0.001) {
      vehicleMesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), fwdVec);
    }

    smoothVehPos.lerp(new THREE.Vector3(curX, curY, curZ), 0.12);

    // G-Vector Arrows in Vehicle Referential
    if (gVectorsEnabled && gArrowsGroup && arrowLon && arrowLat) {
      gArrowsGroup.position.set(curX, curY, curZ);

      // Longitudinal axis in vehicle frame: forward along smoothDir
      const fwdDir = smoothDir.clone().normalize();
      // Lateral axis in vehicle frame: perpendicular right
      const rightDir = new THREE.Vector3(fwdDir.y, -fwdDir.x, 0).normalize();

      const lonG = interpPt.g_lon; // + accel, - brake
      const latG = interpPt.g_lat; // + right, - left

      // Longitudinal Arrow (at least 2x scale and enlarged head)
      const lonLen = Math.max(0.2, Math.min(140, Math.abs(lonG) * 110));
      if (lonG >= 0) {
        arrowLon.setDirection(fwdDir);
        arrowLon.setColor(0x00ff66); // Green forward
      } else {
        arrowLon.setDirection(fwdDir.clone().negate());
        arrowLon.setColor(0xff2a55); // Red backward
      }
      arrowLon.setLength(lonLen, Math.min(lonLen * 0.35, 14), Math.min(lonLen * 0.25, 9));

      // Lateral Arrow (at least 2x scale and enlarged head)
      const latLen = Math.max(0.2, Math.min(140, Math.abs(latG) * 110));
      if (latG >= 0) {
        arrowLat.setDirection(rightDir);
      } else {
        arrowLat.setDirection(rightDir.clone().negate());
      }
      arrowLat.setColor(0xffaa00); // Amber cornering
      arrowLat.setLength(latLen, Math.min(latLen * 0.35, 14), Math.min(latLen * 0.25, 9));
    }

    // STRICTLY MAINTAIN Z AS UP
    camera.up.set(0, 0, 1);

    if (cameraMode === 'chase') {
      controls.enabled = false;
      const followDist = chaseDistance;
      const followHeight = chaseDistance * 0.38;
      const targetCamPos = new THREE.Vector3(
        curX - smoothDir.x * followDist,
        curY - smoothDir.y * followDist,
        curZ + followHeight
      );
      camera.position.lerp(targetCamPos, 0.12);

      const lookTarget = new THREE.Vector3(
        curX + smoothDir.x * 40,
        curY + smoothDir.y * 40,
        curZ + 10
      );
      camera.lookAt(lookTarget);

    } else if (cameraMode === 'hood') {
      controls.enabled = false;
      const hoodCamPos = new THREE.Vector3(
        curX + smoothDir.x * 6,
        curY + smoothDir.y * 6,
        curZ + 5
      );
      camera.position.lerp(hoodCamPos, 0.2);
      const lookTarget = hoodCamPos.clone().add(smoothDir.clone().multiplyScalar(120));
      camera.lookAt(lookTarget);

    } else if (cameraMode === 'top') {
      controls.enabled = false;
      camera.position.set(curX, curY, curZ + topAltitude);
      camera.lookAt(curX, curY, curZ);

    } else if (cameraMode === 'free') {
      // Orbit Mode: centered on vehicle dot
      controls.enabled = true;
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.8;
      controls.target.set(curX, curY, curZ);
      controls.update();
    }
  }

  // --- Dual Screen SVG Dashboard Updating (Mathematically Aligned Arc Math) ---
  function updateHUD(pt) {
    // Both dials: Center=(130, 130), Radius=118, startAngle=135° (bottom-left), sweep=+270° clockwise to 405° (45°)
    const r = 118;
    const cx = 130, cy = 130;
    const startDeg = 135;
    const sweepTotal = 270;
    const x0 = cx + r * Math.cos((startDeg * Math.PI) / 180);
    const y0 = cy + r * Math.sin((startDeg * Math.PI) / 180);

    // 1. Tachometer Arc (0 to 8000 RPM)
    const rpm = Math.round(pt.rpm);
    const rpmFrac = Math.min(1.0, Math.max(0.001, rpm / 8000));
    const rpmDeg = startDeg + rpmFrac * sweepTotal;
    const rx = cx + r * Math.cos((rpmDeg * Math.PI) / 180);
    const ry = cy + r * Math.sin((rpmDeg * Math.PI) / 180);
    const rpmLargeArc = (rpmFrac * sweepTotal) > 180 ? 1 : 0;
    document.getElementById('arc-rpm').setAttribute(
      'd',
      `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${rpmLargeArc} 1 ${rx.toFixed(2)} ${ry.toFixed(2)}`
    );

    // Left Screen Center: Numerical RPM Readout
    document.getElementById('rpm-glyph').textContent = rpm;

    // 2. Speedometer Arc (0 to 240 KPH)
    const speed = Math.round(pt.speed);
    const spdFrac = Math.min(1.0, Math.max(0.001, speed / 240));
    const spdDeg = startDeg + spdFrac * sweepTotal;
    const sx = cx + r * Math.cos((spdDeg * Math.PI) / 180);
    const sy = cy + r * Math.sin((spdDeg * Math.PI) / 180);
    const spdLargeArc = (spdFrac * sweepTotal) > 180 ? 1 : 0;
    document.getElementById('arc-speed').setAttribute(
      'd',
      `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${spdLargeArc} 1 ${sx.toFixed(2)} ${sy.toFixed(2)}`
    );

    // Right Screen Center: Numerical Speed Readout
    document.getElementById('speed-glyph').textContent = speed;

    // Floating Gear Badge directly above replay bar
    document.getElementById('gear-glyph').textContent = pt.gear_txt;

    // Multi-line readouts
    document.getElementById('txt-cool').textContent = Math.round(pt.coolant) + 'c';
    document.getElementById('txt-fuel').textContent = Math.round(pt.fuel) + '%';
    document.getElementById('txt-volt').textContent = pt.battery.toFixed(1) + 'V';
    if (trajectoryData && trajectoryData.stats) {
      document.getElementById('txt-odo').textContent =
        `TRIP ${(trajectoryData.stats.distance_km * currentProgress).toFixed(1)} km`;
    }

    // Elevation & Grade in Upper HUD
    document.getElementById('center-alt').textContent = Math.round(pt.alt);
    const grade = (pt.z * 0.08).toFixed(1);
    document.getElementById('center-grade').textContent = (grade >= 0 ? '+' : '') + grade + '% GRADE';

    // Enlarger G-Meter with Dynamic Red Alert State
    const latG = pt.g_lat || 0;
    const lonG = pt.g_lon || 0;
    const gTotNum = Math.hypot(latG, lonG);
    const gTot = gTotNum.toFixed(2);
    document.getElementById('g-display').textContent = gTot;
    document.getElementById('g-sub').textContent = `Lat ${(latG >= 0 ? '+' : '') + latG.toFixed(2)}g`;

    // Red alert when G-vector norm is above 75% of normalized absolute maximum acceleration (Gmax) on whole drivecycle
    const gThresh = (trajectoryData && trajectoryData.stats && trajectoryData.stats.g_thresh) || 0.75;
    if (gMeterPod) {
      if (gTotNum >= gThresh) {
        gMeterPod.classList.add('alert-red');
      } else {
        gMeterPod.classList.remove('alert-red');
      }
    }

    const gDot = document.getElementById('g-dot');
    if (gDot) {
      const gBound = (trajectoryData && trajectoryData.stats && trajectoryData.stats.g_bound) || 1.1;
      const scale = 96.0 / gBound;
      let ox = latG * scale;
      let oy = -lonG * scale;
      const dist = Math.hypot(ox, oy);
      const maxTravel = 91; // 192px diameter: 96px radius - 4px radius for 8px ball - 1px border
      if (dist > maxTravel) {
        ox = (ox / dist) * maxTravel;
        oy = (oy / dist) * maxTravel;
      }
      gDot.style.transform = `translate(${ox.toFixed(1)}px, ${oy.toFixed(1)}px)`;
    }

    // Timeline Text
    timeCurrentEl.textContent = formatTime(pt.t);

    // Sparkline cursor
    const sparkCursor = document.getElementById('spark-cursor');
    if (sparkCursor) {
      sparkCursor.setAttribute('x1', currentProgress * 200);
      sparkCursor.setAttribute('x2', currentProgress * 200);
    }
  }

  function formatTime(sec) {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    const ms = Math.floor((sec % 1) * 10);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${ms}`;
  }

  // --- Update G-Meter Scale Labels & 50% Gmax Intermediate Ring ---
  function updateGScaleUI(stats) {
    if (!stats) return;
    const gBound = stats.g_bound || 1.1;
    const gMid = stats.g_mid || (gBound * 0.5 / 1.1);

    const gLblOuter = document.getElementById('g-lbl-outer');
    if (gLblOuter) gLblOuter.textContent = `${gBound.toFixed(2)}G`;

    const gMidRing = document.getElementById('g-mid-ring');
    const gLblMid = document.getElementById('g-lbl-mid');
    const midRadiusPx = (gMid / gBound) * 96;

    if (gMidRing) {
      gMidRing.style.width = `${(midRadiusPx * 2).toFixed(1)}px`;
      gMidRing.style.height = `${(midRadiusPx * 2).toFixed(1)}px`;
    }
    if (gLblMid) {
      gLblMid.textContent = `${gMid.toFixed(2)}G`;
      gLblMid.style.top = `${Math.max(4, Math.round(96 - midRadiusPx + 4))}px`;
    }
  }

  // --- Render Friction Circle Phantom Trace & Dwell-Time Heatmap ---
  function renderGHeatmap(pts, gBound) {
    const canvas = document.getElementById('g-heatmap-canvas');
    if (!canvas || !pts || pts.length === 0) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Enforce 50% overall transparency on the canvas layer
    canvas.style.opacity = '0.5';

    ctx.clearRect(0, 0, 192, 192);
    ctx.save();

    // Clip to circular G-meter perimeter (radius 95px)
    ctx.beginPath();
    ctx.arc(96, 96, 95, 0, Math.PI * 2);
    ctx.clip();

    // Set composition to additive blending / summing
    ctx.globalCompositeOperation = 'lighter';

    const scale = 96.0 / (gBound || 1.1);

    // 1. Draw faint connecting trajectory path of the G-meter ball (halved alpha: 0.08)
    ctx.lineWidth = 1.0;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i];
      const px = 96 + (p.g_lat || 0) * scale;
      const py = 96 - (p.g_lon || 0) * scale;
      if (!started) {
        ctx.moveTo(px, py);
        started = true;
      } else {
        ctx.lineTo(px, py);
      }
    }
    ctx.stroke();

    // 2. Accumulate dwell time in 2D density grid (96x96 cells, 2px each)
    const gridSize = 96;
    const grid = new Float32Array(gridSize * gridSize);
    let maxDensity = 0.0;

    for (let i = 0; i < pts.length; i++) {
      const p = pts[i];
      const dt = (i < pts.length - 1) ? Math.max(0.01, Math.min(1.0, pts[i + 1].t - p.t)) : 0.05;
      const px = 96 + (p.g_lat || 0) * scale;
      const py = 96 - (p.g_lon || 0) * scale;

      const gx = Math.floor(px / 2);
      const gy = Math.floor(py / 2);
      if (gx >= 0 && gx < gridSize && gy >= 0 && gy < gridSize) {
        const idx = gy * gridSize + gx;
        grid[idx] += dt;
        if (grid[idx] > maxDensity) maxDensity = grid[idx];
      }
    }

    // 3. Render dwell-time heatmap with glowing radial splats: White to Red Gradient with Blending/Summing
    if (maxDensity > 0) {
      for (let gy = 0; gy < gridSize; gy++) {
        for (let gx = 0; gx < gridSize; gx++) {
          const val = grid[gy * gridSize + gx];
          if (val <= 0) continue;

          // Non-linear perception scaling (gamma / power curve)
          const norm = Math.pow(val / maxDensity, 0.42);
          const cx = gx * 2 + 1;
          const cy = gy * 2 + 1;

          // Gradient from pure white (low dwell) to glowing red (peak dwell)
          // Power curve on G and B ensures high dwell clusters stay pure red when summing
          const r = 255;
          const gbFactor = Math.pow(Math.max(0, 1.0 - norm), 1.8);
          const g = Math.round(255 * gbFactor);
          const b = Math.round(255 * gbFactor);
          // Transparency scaled down by 50% relative to previous implementation
          const a = 0.11 + norm * 0.33;

          const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, 5.0);
          grad.addColorStop(0, `rgba(${r}, ${g}, ${b}, ${a.toFixed(2)})`);
          grad.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.arc(cx, cy, 5.0, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    ctx.restore();
  }

  // --- Load Trajectory from API ---
  async function loadTrajectory(filename, downsample = 1) {
    loadingOverlay.classList.remove('hidden');

    try {
      const url = `/api/trajectory?file=${encodeURIComponent(filename || '')}&downsample=${downsample}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);

      trajectoryData = await res.json();
      points = trajectoryData.points || [];

      if (points.length === 0) {
        alert('Log contains no valid GPS trajectory points.');
        loadingOverlay.classList.add('hidden');
        return;
      }

      // Update header info
      const logFilenameEl = document.getElementById('log-filename');
      if (logFilenameEl) logFilenameEl.textContent = trajectoryData.filename;

      const logMetaEl = document.getElementById('log-meta');
      if (logMetaEl) {
        logMetaEl.textContent = `${trajectoryData.stats.distance_km} km • Δ${trajectoryData.stats.total_gain}m • ${trajectoryData.point_count} pts`;
      }
      if (timeTotalEl) timeTotalEl.textContent = formatTime(trajectoryData.duration_s);

      const sparkMaxAltEl = document.getElementById('spark-max-alt');
      if (sparkMaxAltEl) sparkMaxAltEl.textContent = `↑ ${trajectoryData.stats.max_alt}m`;

      computeSmoothedCoordinates(points);
      buildTrajectoryGeometry();
      updateTrajectoryColors(0);

      // Update G-Meter UI scale & Phantom Trace Heatmap
      if (trajectoryData.stats) {
        updateGScaleUI(trajectoryData.stats);
        renderGHeatmap(points, trajectoryData.stats.g_bound);
      }

      currentProgress = 0.0;
      currentIndex = 0;
      slider.value = 0;

      const initialPt = getInterpolatedPoint(0.0) || points[0];
      updateHUD(initialPt);
      updateCamera(initialPt);
    } catch (err) {
      console.error('Failed to load trajectory:', err);
      alert('Error loading trajectory: ' + err.message);
    } finally {
      loadingOverlay.classList.add('hidden');
    }
  }

  // --- Populate Available Logs Dropdown ---
  async function fetchLogsList() {
    try {
      const res = await fetch('/api/logs');
      if (!res.ok) return;
      const logs = await res.json();

      logSelect.innerHTML = '';
      logs.forEach((log) => {
        const opt = document.createElement('option');
        opt.value = log.filename;
        opt.textContent = `${log.filename} (${(log.size / 1024).toFixed(0)} KB)`;
        if (log.is_initial) opt.selected = true;
        logSelect.appendChild(opt);
      });

      logSelect.addEventListener('change', (e) => {
        loadTrajectory(e.target.value);
      });

      // Load initial selected log
      const initialLog = logSelect.value;
      if (initialLog) {
        loadTrajectory(initialLog);
      }
    } catch (err) {
      console.error('Failed to fetch logs:', err);
    }
  }

  // --- Main Animation Loop ---
  let lastFrameTime = performance.now();

  function animate(now) {
    requestAnimationFrame(animate);

    const delta = (now - lastFrameTime) / 1000.0;
    lastFrameTime = now;
    const dt = Math.min(0.08, delta);

    if (isPlaying && points.length > 1) {
      const step = dt * playSpeed;
      const totalDuration = trajectoryData.duration_s || 1.0;
      currentProgress += step / totalDuration;

      if (currentProgress >= 1.0) {
        currentProgress = 0.0;
      }

      slider.value = Math.floor(currentProgress * 1000);
      currentIndex = Math.floor(currentProgress * (points.length - 1));

      const interpPt = getInterpolatedPoint(currentProgress);
      if (interpPt) {
        updateTrajectoryColors(currentIndex);
        updateVehicleParticles(interpPt, dt);
        updateCamera(interpPt);
        updateHUD(interpPt);
      }
    } else if (points.length > 0) {
      const interpPt = getInterpolatedPoint(currentProgress);
      if (interpPt) {
        updateCamera(interpPt);
      }
    }

    renderer.render(scene, camera);
  }

  // --- UI Event Listeners ---
  function setupEventListeners() {
    // Slider Scrubbing
    slider.addEventListener('input', (e) => {
      if (points.length === 0) return;
      currentProgress = parseFloat(e.target.value) / 1000.0;
      currentIndex = Math.floor(currentProgress * (points.length - 1));
      const interpPt = getInterpolatedPoint(currentProgress);
      if (interpPt) {
        updateTrajectoryColors(currentIndex);
        updateHUD(interpPt);
        updateCamera(interpPt);
      }
    });

    // Play / Pause
    btnPlay.addEventListener('click', togglePlay);

    function togglePlay() {
      isPlaying = !isPlaying;
      playIcon.textContent = isPlaying ? '⏸' : '▶';
      playText.textContent = isPlaying ? 'PAUSE' : 'PLAY';
    }

    // Speed Multipliers
    document.querySelectorAll('[data-speed]').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('[data-speed]').forEach((b) => {
          b.classList.remove('active');
        });
        btn.classList.add('active');
        playSpeed = parseFloat(btn.dataset.speed);
      });
    });

    // Vertical Exaggeration Slider
    zSlider.addEventListener('input', (e) => {
      zScale = parseFloat(e.target.value);
      zVal.textContent = zScale.toFixed(1) + 'x';
      updateGeometryZScale();
    });

    // Warp Particles Toggle
    btnParticles.addEventListener('click', () => {
      particlesEnabled = !particlesEnabled;
      btnParticles.classList.toggle('active', particlesEnabled);
      if (particlePoints) particlePoints.visible = particlesEnabled;
    });

    // G-Vectors Checkbox
    if (chkGVectors) {
      chkGVectors.addEventListener('change', (e) => {
        gVectorsEnabled = e.target.checked;
        if (gArrowsGroup) gArrowsGroup.visible = gVectorsEnabled;
      });
    }

    // Interactive Zoom for Chase and Top Views
    canvas.addEventListener('wheel', (e) => {
      if (cameraMode === 'chase') {
        e.preventDefault();
        chaseDistance = Math.max(30, Math.min(550, chaseDistance + e.deltaY * 0.25));
      } else if (cameraMode === 'top') {
        e.preventDefault();
        topAltitude = Math.max(120, Math.min(4500, topAltitude + e.deltaY * 0.85));
      }
    }, { passive: false });

    // Camera Mode Selectors
    const camBtns = {
      chase: document.getElementById('cam-chase'),
      hood: document.getElementById('cam-hood'),
      free: document.getElementById('cam-free'),
      top: document.getElementById('cam-top'),
    };
    Object.keys(camBtns).forEach((mode) => {
      camBtns[mode].addEventListener('click', () => {
        cameraMode = mode;
        Object.values(camBtns).forEach((b) => {
          b.classList.remove('active');
        });
        camBtns[mode].classList.add('active');

        if (mode === 'free') {
          // In orbit view: zoom in around vehicle dot
          camera.position.set(smoothVehPos.x - 220, smoothVehPos.y - 220, smoothVehPos.z + 160);
          controls.target.copy(vehicleMesh.position);
          controls.update();
        }
      });
    });

    // Collapsible Storytelling HUD Toggle
    function toggleHUD() {
      hudVisible = !hudVisible;
      topBar.classList.toggle('collapsed', !hudVisible);
      if (bottomGroup) bottomGroup.classList.toggle('collapsed', !hudVisible);
      hudToggleLabel.textContent = hudVisible ? "Hide UI (H)" : "Show UI (H)";
    }

    toggleHudBtn.addEventListener('click', toggleHUD);

    window.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

      if (e.key === 'h' || e.key === 'H') {
        toggleHUD();
      } else if (e.key === ' ') {
        e.preventDefault();
        togglePlay();
      } else if (e.key === '1') {
        camBtns.chase.click();
      } else if (e.key === '2') {
        camBtns.hood.click();
      } else if (e.key === '3') {
        camBtns.free.click();
      } else if (e.key === '4') {
        camBtns.top.click();
      }
    });
  }

  // --- Bootstrapping ---
  window.addEventListener('DOMContentLoaded', () => {
    initThree();
    setupEventListeners();
    fetchLogsList();
    requestAnimationFrame(animate);
  });
})();
