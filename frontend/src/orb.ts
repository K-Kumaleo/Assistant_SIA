// orb.ts — Three.js audio-reactive particle orb

import * as THREE from "three";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

const STATE_COLORS: Record<OrbState, number> = {
  idle:      0x1565c0,
  listening: 0x4fc3f7,
  thinking:  0xf0a830,
  speaking:  0x7ee8a2,
};

const PARTICLE_COUNT = 3000;

export class OrbVisualizer {
  private scene: THREE.Scene;
  private camera: THREE.PerspectiveCamera;
  private renderer: THREE.WebGLRenderer;
  private particles!: THREE.Points;
  private positions!: Float32Array;
  private velocities!: Float32Array;
  private basePositions!: Float32Array;
  private state: OrbState = "idle";
  private energyLevel = 0;
  private targetEnergy = 0;
  private clock = new THREE.Clock();
  private animFrame = 0;

  constructor(canvas: HTMLCanvasElement) {
    this.scene = new THREE.Scene();

    this.camera = new THREE.PerspectiveCamera(
      60,
      canvas.clientWidth / canvas.clientHeight,
      0.1,
      100
    );
    this.camera.position.z = 3;

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);

    this.buildParticles();
    this.addAmbientLight();
    this.bindResize(canvas);
    this.startLoop();
  }

  private buildParticles() {
    const geo = new THREE.BufferGeometry();
    this.positions = new Float32Array(PARTICLE_COUNT * 3);
    this.velocities = new Float32Array(PARTICLE_COUNT * 3);
    this.basePositions = new Float32Array(PARTICLE_COUNT * 3);

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const r = 0.9 + Math.random() * 0.15;

      const x = r * Math.sin(phi) * Math.cos(theta);
      const y = r * Math.sin(phi) * Math.sin(theta);
      const z = r * Math.cos(phi);

      this.positions[i * 3]     = x;
      this.positions[i * 3 + 1] = y;
      this.positions[i * 3 + 2] = z;

      this.basePositions[i * 3]     = x;
      this.basePositions[i * 3 + 1] = y;
      this.basePositions[i * 3 + 2] = z;

      this.velocities[i * 3]     = (Math.random() - 0.5) * 0.002;
      this.velocities[i * 3 + 1] = (Math.random() - 0.5) * 0.002;
      this.velocities[i * 3 + 2] = (Math.random() - 0.5) * 0.002;
    }

    geo.setAttribute("position", new THREE.BufferAttribute(this.positions, 3));

    const mat = new THREE.PointsMaterial({
      color: STATE_COLORS.idle,
      size: 0.012,
      transparent: true,
      opacity: 0.8,
      sizeAttenuation: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    this.particles = new THREE.Points(geo, mat);
    this.scene.add(this.particles);
  }

  private addAmbientLight() {
    const light = new THREE.PointLight(0x4fc3f7, 2, 10);
    light.position.set(0, 0, 2);
    this.scene.add(light);
  }

  private bindResize(canvas: HTMLCanvasElement) {
    const ro = new ResizeObserver(() => {
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(w, h, false);
    });
    ro.observe(canvas);
  }

  private startLoop() {
    const loop = () => {
      this.animFrame = requestAnimationFrame(loop);
      this.update();
      this.renderer.render(this.scene, this.camera);
    };
    loop();
  }

  private update() {
    const t = this.clock.getElapsedTime();
    this.energyLevel += (this.targetEnergy - this.energyLevel) * 0.06;

    const mat = this.particles.material as THREE.PointsMaterial;

    // Slow base rotation
    this.particles.rotation.y = t * 0.08;
    this.particles.rotation.x = Math.sin(t * 0.05) * 0.1;

    const energy = this.energyLevel;

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const i3 = i * 3;
      const bx = this.basePositions[i3];
      const by = this.basePositions[i3 + 1];
      const bz = this.basePositions[i3 + 2];

      // Noise displacement
      const noise =
        Math.sin(t * 1.5 + bx * 4) *
        Math.cos(t * 1.2 + by * 4) *
        Math.sin(t * 0.9 + bz * 4);

      const disp = 0.03 + energy * 0.28;
      const scale = 1 + noise * disp;

      this.positions[i3]     = bx * scale;
      this.positions[i3 + 1] = by * scale;
      this.positions[i3 + 2] = bz * scale;
    }

    (this.particles.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true;

    // Color + size based on state
    const targetColor = new THREE.Color(STATE_COLORS[this.state]);
    mat.color.lerp(targetColor, 0.04);
    mat.size = 0.010 + energy * 0.008;
    mat.opacity = 0.7 + energy * 0.25;
  }

  setState(state: OrbState, energy = 0) {
    this.state = state;
    this.targetEnergy = energy;

    if (state === "idle")      this.targetEnergy = 0.05;
    if (state === "listening") this.targetEnergy = 0.25;
    if (state === "thinking")  this.targetEnergy = 0.55;
    if (state === "speaking")  this.targetEnergy = 0.75;
  }

  setEnergy(level: number) {
    this.targetEnergy = Math.max(0, Math.min(1, level));
  }

  destroy() {
    cancelAnimationFrame(this.animFrame);
    this.renderer.dispose();
  }
}
