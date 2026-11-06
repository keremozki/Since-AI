import { MeshoptDecoder } from "meshoptimizer";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { acceleratedRaycast, computeBoundsTree } from "three-mesh-bvh";
import { Finding, Point, Status } from "./api";

THREE.BufferGeometry.prototype.computeBoundsTree = computeBoundsTree;

export const STATUS_COLOR: Record<Status, string> = {
  pass: "#2e8b57",
  fail: "#d13438",
  conflict: "#b8590a",
  cant_tell: "#6b7785",
};

const STATUS_HEX: Record<Status, number> = { pass: 0x2e8b57, fail: 0xd13438, conflict: 0xe07b12, cant_tell: 0x7d8894 };
const SHIP_CENTRE = new THREE.Vector3(-1000, 0, 400);
const FULL_CUT = 1300;
const CUT_ABOVE_FINDING_IN = 95;
const SNAP_IN = 4;
const MARKER_SIZE = 0.016;
const MARKER_SIZE_SELECTED = 0.04;
const MODEL_MUTE = 0.75;

let cachedDot: THREE.CanvasTexture | null = null;

/** A round marker with a white ring, tinted by each sprite's colour. */
function dotTexture(): THREE.CanvasTexture {
  if (cachedDot) return cachedDot;
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const context = canvas.getContext("2d")!;
  context.beginPath();
  context.arc(size / 2, size / 2, size / 2 - 3, 0, Math.PI * 2);
  context.fillStyle = "#ffffff";
  context.fill();
  context.lineWidth = 5;
  context.strokeStyle = "#ffffff";
  context.stroke();
  cachedDot = new THREE.CanvasTexture(canvas);
  return cachedDot;
}

export interface Measurement {
  a: Point;
  b: Point;
}

interface ModelMeta {
  q: number;
  ox: number;
  oy: number;
  oz: number;
  cats: { name: string; parts: number; verts: number; tris: number; sizes: [number, number, number] }[];
}

interface PickMesh {
  mesh: THREE.Mesh;
  name: string;
}

interface Props {
  findings: Finding[];
  selected: Finding | null;
  onSelect: (finding: Finding) => void;
  measuring: boolean;
  onMeasured: (measurement: Measurement | null) => void;
}

export default function ShipViewer({ findings, selected, onSelect, measuring, onMeasured }: Props) {
  const mount = useRef<HTMLDivElement>(null);
  const view = useRef<ViewerCore | null>(null);
  const [status, setStatus] = useState("Loading the 3D model");
  const [cut, setCut] = useState(FULL_CUT);
  const callbacks = useRef({ onSelect, onMeasured });
  callbacks.current = { onSelect, onMeasured };

  useEffect(() => {
    const core = new ViewerCore(mount.current!, {
      select: (finding) => callbacks.current.onSelect(finding),
      measured: (measurement) => callbacks.current.onMeasured(measurement),
      status: setStatus,
    });
    view.current = core;
    core.load();
    return () => core.dispose();
  }, []);

  useEffect(() => view.current?.setMarkers(findings), [findings]);
  useEffect(() => view.current?.setMeasuring(measuring), [measuring]);
  useEffect(() => view.current?.setCut(cut), [cut]);

  useEffect(() => {
    if (selected?.location) {
      const height = selected.location.z + CUT_ABOVE_FINDING_IN;
      setCut(Math.min(height, FULL_CUT));
      view.current?.flyTo(selected.location);
    }
    view.current?.highlight(selected);
  }, [selected]);

  return (
    <section className="viewer" aria-label="3D model of the ship">
      <div ref={mount} className="viewer-canvas" data-measuring={measuring} />
      {status && <p className="viewer-status">{status}</p>}
      <div className="viewer-controls">
        <label>
          Cut height
          <input type="range" min={60} max={FULL_CUT} step={6} value={cut} onChange={(e) => setCut(Number(e.target.value))} />
          <output>{cut >= FULL_CUT ? "off" : `${(cut / 12).toFixed(1)} ft`}</output>
        </label>
        <button type="button" onClick={() => { setCut(FULL_CUT); view.current?.home(); }}>Whole ship</button>
      </div>
    </section>
  );
}

class ViewerCore {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private clip = new THREE.Plane(new THREE.Vector3(0, 0, -1), FULL_CUT);
  private markers = new THREE.Group();
  private measureGroup = new THREE.Group();
  private picks: PickMesh[] = [];
  private pickBuilt = false;
  private meta: ModelMeta | null = null;
  private geometries: { name: string; geometry: THREE.BufferGeometry }[] = [];
  private measuring = false;
  private points: THREE.Vector3[] = [];
  private flight: { from: THREE.Vector3; to: THREE.Vector3; fromT: THREE.Vector3; toT: THREE.Vector3; start: number } | null = null;
  private frame = 0;
  private disposed = false;
  private pointerDown = { x: 0, y: 0 };
  private observer: ResizeObserver;

  constructor(private host: HTMLElement, private events: {
    select: (finding: Finding) => void;
    measured: (measurement: Measurement | null) => void;
    status: (text: string) => void;
  }) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.localClippingEnabled = true;
    host.appendChild(this.renderer.domElement);
    this.scene.background = new THREE.Color(0xe9eef2);
    this.camera = new THREE.PerspectiveCamera(40, 1, 5, 50000);
    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a97a3, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(1500, -2500, 4000);
    this.scene.add(sun);
    this.scene.add(this.markers, this.measureGroup);
    this.home();
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(host);
    this.resize();
    const element = this.renderer.domElement;
    element.addEventListener("pointerdown", (e) => { this.pointerDown = { x: e.clientX, y: e.clientY }; });
    element.addEventListener("pointerup", (e) => this.handleClick(e));
    const loop = () => {
      if (this.disposed) return;
      this.frame = requestAnimationFrame(loop);
      this.updateFlight();
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    };
    loop();
    (window as unknown as { __viewer: ViewerCore }).__viewer = this;
  }

  async load() {
    try {
      const [meta, bytes] = await Promise.all([
        fetch("/model/meta").then((r) => { if (!r.ok) throw new Error("no model"); return r.json() as Promise<ModelMeta>; }),
        fetch("/model/bin").then((r) => { if (!r.ok) throw new Error("no model"); return r.arrayBuffer(); }),
      ]);
      await MeshoptDecoder.ready;
      this.meta = meta;
      const data = new Uint8Array(bytes);
      let offset = 0;
      for (const [index, category] of meta.cats.entries()) {
        if (this.disposed) return;
        this.events.status(`Decoding ${category.name.toLowerCase()} (${index + 1} of ${meta.cats.length})`);
        await new Promise((resolve) => setTimeout(resolve));
        const positions = new Uint16Array(category.verts * 4);
        const colours = new Uint8Array(category.verts * 4);
        const indices = new Uint32Array(category.tris * 3);
        MeshoptDecoder.decodeVertexBuffer(new Uint8Array(positions.buffer), category.verts, 8, data.subarray(offset, offset + category.sizes[0]));
        offset += category.sizes[0];
        MeshoptDecoder.decodeVertexBuffer(colours, category.verts, 4, data.subarray(offset, offset + category.sizes[1]));
        offset += category.sizes[1];
        MeshoptDecoder.decodeIndexBuffer(new Uint8Array(indices.buffer), indices.length, 4, data.subarray(offset, offset + category.sizes[2]));
        offset += category.sizes[2];
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute("position", new THREE.InterleavedBufferAttribute(new THREE.InterleavedBuffer(positions, 4), 3, 0, false));
        geometry.setAttribute("color", new THREE.InterleavedBufferAttribute(new THREE.InterleavedBuffer(colours, 4), 3, 0, true));
        geometry.setIndex(new THREE.BufferAttribute(indices, 1));
        const material = new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true, side: THREE.DoubleSide, clippingPlanes: [this.clip] });
        // Mute the model's bright system colours, so that result markers stand out.
        material.onBeforeCompile = (shader) => {
          shader.fragmentShader = shader.fragmentShader.replace(
            "#include <color_fragment>",
            `#include <color_fragment>
            diffuseColor.rgb = mix(diffuseColor.rgb, vec3(dot(diffuseColor.rgb, vec3(0.3, 0.59, 0.11))), ${MODEL_MUTE.toFixed(2)});`,
          );
        };
        const mesh = new THREE.Mesh(geometry, material);
        mesh.frustumCulled = false;
        mesh.scale.setScalar(meta.q);
        mesh.position.set(meta.ox, meta.oy, meta.oz);
        mesh.visible = category.name !== "Insulation";
        this.scene.add(mesh);
        this.geometries.push({ name: category.name, geometry });
      }
      this.events.status("");
    } catch {
      this.events.status("3D model not loaded. Set up ship-data as described in the README. Checks still work.");
    }
  }

  setMarkers(findings: Finding[]) {
    this.markers.clear();
    const seen = new Set<string>();
    for (const finding of findings) {
      if (!finding.location || finding.status === "pass") continue;
      const key = `${finding.rule_id}|${finding.subject}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const material = new THREE.SpriteMaterial({ map: dotTexture(), color: STATUS_HEX[finding.status], depthTest: false, sizeAttenuation: false, transparent: true });
      const sprite = new THREE.Sprite(material);
      sprite.position.set(finding.location.x, finding.location.y, finding.location.z);
      sprite.scale.setScalar(MARKER_SIZE);
      sprite.renderOrder = 10;
      sprite.userData.finding = finding;
      this.markers.add(sprite);
    }
  }

  highlight(finding: Finding | null) {
    for (const child of this.markers.children as THREE.Sprite[]) {
      const on = finding && child.userData.finding.rule_id === finding.rule_id && child.userData.finding.subject === finding.subject;
      child.scale.setScalar(on ? MARKER_SIZE_SELECTED : MARKER_SIZE);
      child.material.opacity = finding && !on ? 0.45 : 1;
      child.renderOrder = on ? 12 : 10;
    }
  }

  setCut(height: number) {
    this.clip.constant = height;
  }

  home() {
    this.flight = null;
    this.camera.position.set(-1000, -3600, 1500);
    this.controls.target.copy(SHIP_CENTRE);
  }

  flyTo(point: Point) {
    const target = new THREE.Vector3(point.x, point.y, point.z);
    this.flight = {
      from: this.camera.position.clone(),
      to: target.clone().add(new THREE.Vector3(-40, -170, 560)),
      fromT: this.controls.target.clone(),
      toT: target,
      start: performance.now(),
    };
  }

  private updateFlight() {
    if (!this.flight) return;
    const t = Math.min((performance.now() - this.flight.start) / 700, 1);
    const eased = t * t * (3 - 2 * t);
    this.camera.position.lerpVectors(this.flight.from, this.flight.to, eased);
    this.controls.target.lerpVectors(this.flight.fromT, this.flight.toT, eased);
    if (t === 1) this.flight = null;
  }

  setMeasuring(on: boolean) {
    this.measuring = on;
    this.points = [];
    this.measureGroup.clear();
    this.events.measured(null);
    if (on && !this.pickBuilt) {
      this.events.status("Preparing the model for measuring");
      setTimeout(() => this.buildPicking());
    }
  }

  /** Real positions in inches, plus a search tree, built only when measuring is first used. */
  private buildPicking() {
    if (!this.meta || this.pickBuilt) { this.events.status(""); return; }
    const { q, ox, oy, oz } = this.meta;
    for (const { name, geometry } of this.geometries) {
      if (name === "Insulation") continue;
      const source = geometry.getAttribute("position") as THREE.InterleavedBufferAttribute;
      const positions = new Float32Array(source.count * 3);
      for (let i = 0; i < source.count; i++) {
        positions[i * 3] = source.getX(i) * q + ox;
        positions[i * 3 + 1] = source.getY(i) * q + oy;
        positions[i * 3 + 2] = source.getZ(i) * q + oz;
      }
      const pickGeometry = new THREE.BufferGeometry();
      pickGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      pickGeometry.setIndex(geometry.getIndex());
      pickGeometry.computeBoundsTree();
      const mesh = new THREE.Mesh(pickGeometry, new THREE.MeshBasicMaterial({ side: THREE.DoubleSide }));
      mesh.raycast = acceleratedRaycast;
      this.picks.push({ mesh, name });
    }
    this.pickBuilt = true;
    this.events.status("");
  }

  private handleClick(event: PointerEvent) {
    if (Math.hypot(event.clientX - this.pointerDown.x, event.clientY - this.pointerDown.y) > 5) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(pointer, this.camera);
    if (this.measuring) {
      this.pickPoint(ray);
      return;
    }
    const hit = ray.intersectObjects(this.markers.children)[0];
    if (hit) this.events.select(hit.object.userData.finding);
  }

  private pickPoint(ray: THREE.Raycaster) {
    let best: THREE.Intersection | null = null;
    for (const { mesh } of this.picks) {
      for (const hit of ray.intersectObject(mesh)) {
        if (hit.point.z <= this.clip.constant && (!best || hit.distance < best.distance)) best = hit;
      }
    }
    if (!best?.face) return;
    const point = this.snap(best);
    if (this.points.length === 2) {
      this.points = [];
      this.measureGroup.clear();
      this.events.measured(null);
    }
    this.points.push(point);
    const dot = new THREE.Sprite(new THREE.SpriteMaterial({ color: 0x0b6e8f, depthTest: false, sizeAttenuation: false }));
    dot.position.copy(point);
    dot.scale.setScalar(0.012);
    dot.renderOrder = 11;
    this.measureGroup.add(dot);
    if (this.points.length === 2) {
      const [a, b] = this.points;
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), new THREE.LineBasicMaterial({ color: 0x0b6e8f, depthTest: false }));
      line.renderOrder = 11;
      this.measureGroup.add(line);
      this.events.measured({ a: { x: a.x, y: a.y, z: a.z }, b: { x: b.x, y: b.y, z: b.z } });
    }
  }

  /** Move a clicked point to the corner of the face it hit, if one is close. */
  private snap(hit: THREE.Intersection): THREE.Vector3 {
    const positions = (hit.object as THREE.Mesh).geometry.getAttribute("position");
    const { a, b, c } = hit.face!;
    let nearest = hit.point.clone();
    let distance = SNAP_IN;
    for (const index of [a, b, c]) {
      const corner = new THREE.Vector3().fromBufferAttribute(positions, index);
      const gap = corner.distanceTo(hit.point);
      if (gap < distance) { distance = gap; nearest = corner; }
    }
    return nearest;
  }

  private resize() {
    const { clientWidth, clientHeight } = this.host;
    if (!clientWidth || !clientHeight) return;
    this.renderer.setSize(clientWidth, clientHeight);
    this.camera.aspect = clientWidth / clientHeight;
    this.camera.updateProjectionMatrix();
  }

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    this.observer.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
