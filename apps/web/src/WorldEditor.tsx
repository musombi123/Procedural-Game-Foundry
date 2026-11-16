import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { PointerLockControls } from "three/addons/controls/PointerLockControls.js";
import type { ObjectKind, SceneObject, TerrainEdit } from "./types";

type Props = {
  seed: number; width: number; depth: number; amplitude: number; frequency: number;
  waterLevel: number; fog: boolean; sunAngle: number; resolution: number; terrainEdits: TerrainEdit[]; sculptMode: "raise" | "lower" | "smooth" | null;
  objects: SceneObject[]; selectedId: string; mode: "edit" | "play";
  placementType: ObjectKind | null;
  onPlace: (kind: ObjectKind, x: number, z: number) => void;
  onSelect: (id: string) => void;
  onSculpt: (x: number, z: number) => void;
};

const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));
const fract = (v: number) => v - Math.floor(v);
const hash = (x: number, z: number, seed: number) => fract(Math.sin(x * 127.1 + z * 311.7 + seed * 0.017) * 43758.5453) * 2 - 1;
const smooth = (v: number) => v * v * (3 - 2 * v);
function noise2(seed: number, x: number, z: number) {
  const x0 = Math.floor(x), z0 = Math.floor(z), tx = smooth(fract(x)), tz = smooth(fract(z));
  const a = hash(x0, z0, seed), b = hash(x0 + 1, z0, seed);
  const c = hash(x0, z0 + 1, seed), d = hash(x0 + 1, z0 + 1, seed);
  const top = a + (b - a) * tx, bottom = c + (d - c) * tx;
  return top + (bottom - top) * tz;
}
function heightAt(seed: number, x: number, z: number, amplitude: number, frequency: number) {
  const base = noise2(seed, x * frequency, z * frequency) * 0.72;
  const detail = noise2(seed + 101, x * frequency * 2.1, z * frequency * 2.1) * 0.35;
  const ridge = (1 - Math.abs(noise2(seed + 211, x * frequency * 0.55, z * frequency * 0.55))) * 0.18;
  return (base + detail + ridge) * amplitude;
}
function terrainHeight(seed: number, x: number, z: number, amplitude: number, frequency: number, edits: TerrainEdit[], width: number, depth: number, resolution: number) {
  let height = heightAt(seed, x, z, amplitude, frequency);
  const sx = width / resolution, sz = depth / resolution;
  for (const edit of edits) {
    const dx = x-edit.x, dz = z-edit.z, d2 = dx*dx+dz*dz;
    if (d2 >= edit.radius*edit.radius) continue;
    const weight = Math.exp(-4*d2/(edit.radius*edit.radius));
    if (edit.operation === "raise") height += edit.strength*weight;
    else if (edit.operation === "lower") height -= edit.strength*weight;
    else {
      const neighbors = [[-sx,-sz],[0,-sz],[sx,-sz],[-sx,0],[sx,0],[-sx,sz],[0,sz],[sx,sz]];
      const avg = neighbors.reduce((sum,[ox,oz])=>sum+heightAt(seed,x+ox,z+oz,amplitude,frequency),0)/8;
      const blend = Math.min(1,edit.strength/12)*weight;
      height = height*(1-blend)+avg*blend;
    }
  }
  return height;
}
function material(color: string, roughness = 0.84) {
  return new THREE.MeshStandardMaterial({ color, roughness, metalness: 0.08 });
}
function buildObject(item: SceneObject, ground: number) {
  const root = new THREE.Group();
  root.userData.objectId = item.id;
  root.position.set(item.x, ground + item.y, item.z);
  root.rotation.y = THREE.MathUtils.degToRad(item.rotation);
  root.scale.setScalar(item.scale);
  const base = material(item.color);
  const add = (geometry: THREE.BufferGeometry, mat: THREE.Material, y: number, sx = 1, sy = 1, sz = 1) => {
    const mesh = new THREE.Mesh(geometry, mat);
    mesh.position.y = y;
    mesh.scale.set(sx, sy, sz);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData.objectId = item.id;
    root.add(mesh);
  };
  if (item.kind === "outpost") {
    add(new THREE.BoxGeometry(8, 4, 8), base, 2);
    add(new THREE.BoxGeometry(8.6, 0.45, 8.6), material("#b5c7da", 0.55), 4.2);
    add(new THREE.BoxGeometry(1.2, 2.3, 0.18), material("#263a51"), 1.15);
  } else if (item.kind === "beacon") {
    add(new THREE.CylinderGeometry(0.55, 0.9, 3.6, 8), base, 1.8);
    const glow = new THREE.MeshStandardMaterial({ color: "#6bd9ff", emissive: "#42c8ff", emissiveIntensity: 1.4 });
    add(new THREE.SphereGeometry(0.55, 12, 10), glow, 3.85);
  } else if (item.kind === "tree") {
    add(new THREE.CylinderGeometry(0.25, 0.42, 3.2, 7), material("#71563e"), 1.6);
    add(new THREE.DodecahedronGeometry(1.65, 1), base, 3.55, 1, 1.25, 1);
  } else if (item.kind === "rock") {
    add(new THREE.DodecahedronGeometry(1.25, 1), base, 0.85, 1.25, 0.8, 1.05);
  } else {
    add(new THREE.BoxGeometry(1.8, 1.8, 1.8), base, 0.9);
    add(new THREE.BoxGeometry(1.92, 0.12, 1.92), material("#d3deea", 0.55), 1.55);
  }
  return root;
}

function disposeObject(root: THREE.Group) {
  root.traverse((node) => {
    if (node instanceof THREE.Mesh) {
      node.geometry.dispose();
      const mats = Array.isArray(node.material) ? node.material : [node.material];
      mats.forEach((mat) => mat.dispose());
    }
  });
}

export default function WorldEditor(props: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const liveProps = useRef(props);
  const stateRef = useRef<{
    scene: THREE.Scene; camera: THREE.PerspectiveCamera; renderer: THREE.WebGLRenderer;
    orbit: OrbitControls; pointer: PointerLockControls; terrain: THREE.Mesh;
    objects: THREE.Group[]; water: THREE.Mesh; grid: THREE.GridHelper;
    selectedRing: THREE.Mesh | null; animation: number; keys: Set<string>;
    verticalVelocity: number; lastTime: number; raycaster: THREE.Raycaster;
  } | null>(null);

  useEffect(() => { liveProps.current = props; }, [props]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#101d31");
    const camera = new THREE.PerspectiveCamera(58, 1, 0.1, 1200);
    camera.position.set(0, 24, 38);
    camera.lookAt(0, 0, 0);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.8));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);

    scene.add(new THREE.HemisphereLight("#b8d4ee", "#263626", 1.6));
    const sun = new THREE.DirectionalLight("#fff0d7", 2.2);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    scene.add(sun);

    const terrain = new THREE.Mesh(
      new THREE.PlaneGeometry(96, 96, 64, 64),
      new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 1, side: THREE.DoubleSide })
    );
    terrain.name = "Procedural terrain";
    terrain.receiveShadow = true;
    scene.add(terrain);

    const water = new THREE.Mesh(
      new THREE.PlaneGeometry(700, 700),
      new THREE.MeshPhysicalMaterial({ color: "#316987", roughness: 0.25, metalness: 0.1, transparent: true, opacity: 0.72 })
    );
    water.rotation.x = -Math.PI / 2;
    scene.add(water);
    const grid = new THREE.GridHelper(96, 24, "#7a9cbc", "#30465d");
    grid.position.y = 0.09;
    scene.add(grid);

    const orbit = new OrbitControls(camera, renderer.domElement);
    orbit.enableDamping = true;
    orbit.dampingFactor = 0.075;
    orbit.maxPolarAngle = Math.PI * 0.48;
    orbit.minDistance = 9;
    orbit.maxDistance = 220;
    orbit.target.set(0, 0, 0);
    const pointer = new PointerLockControls(camera, renderer.domElement);
    const raycaster = new THREE.Raycaster();
    const keys = new Set<string>();
    const state = {
      scene, camera, renderer, orbit, pointer, terrain, objects: [] as THREE.Group[],
      water, grid, selectedRing: null as THREE.Mesh | null, animation: 0,
      keys, verticalVelocity: 0, lastTime: 0, raycaster
    };
    stateRef.current = state;

    const resize = () => {
      const width = Math.max(1, host.clientWidth), height = Math.max(1, host.clientHeight);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      if (["w", "a", "s", "d", " ", "shift"].includes(key)) {
        keys.add(key);
        if (liveProps.current.mode === "play") event.preventDefault();
      }
    };
    const onKeyUp = (event: KeyboardEvent) => keys.delete(event.key.toLowerCase());
    const onCanvasClick = (event: MouseEvent) => {
      const current = liveProps.current;
      if (current.mode === "play") {
        if (!pointer.isLocked) pointer.lock();
        return;
      }
      const rect = renderer.domElement.getBoundingClientRect();
      const coords = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1
      );
      raycaster.setFromCamera(coords, camera);
      if (current.sculptMode) { const hit = raycaster.intersectObject(terrain, false)[0]; if (hit) current.onSculpt(hit.point.x, hit.point.z); return; }
      if (current.placementType) {
        const hit = raycaster.intersectObject(terrain, false)[0];
        if (hit) current.onPlace(current.placementType, hit.point.x, hit.point.z);
        return;
      }
      const hit = raycaster.intersectObjects(state.objects, true)[0];
      if (hit) {
        let node: THREE.Object3D | null = hit.object;
        while (node && !node.userData.objectId) node = node.parent;
        if (node?.userData.objectId) current.onSelect(String(node.userData.objectId));
      } else {
        current.onSelect("");
      }
    };
    renderer.domElement.addEventListener("click", onCanvasClick);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("resize", resize);
    resize();

    const rebuildWorld = (current: Props) => {
      const geometry = new THREE.PlaneGeometry(current.width, current.depth, 100, 100);
      geometry.rotateX(-Math.PI / 2);
      const positions = geometry.attributes.position as THREE.BufferAttribute;
      const colors: number[] = [];
      for (let i = 0; i < positions.count; i++) {
        const x = positions.getX(i), z = positions.getZ(i);
        const height = terrainHeight(current.seed, x, z, current.amplitude, current.frequency, current.terrainEdits, current.width, current.depth, current.resolution);
        positions.setY(i, height);
        const moisture = noise2(current.seed + 991, x * 0.12, z * 0.12);
        const color = height < -1.8 ? new THREE.Color("#315e78") :
          height > 5.5 ? new THREE.Color("#858c92") :
          moisture < -0.25 ? new THREE.Color("#a78a68") :
          moisture > 0.35 ? new THREE.Color("#477768") : new THREE.Color("#829172");
        colors.push(color.r, color.g, color.b);
      }
      geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
      geometry.computeVertexNormals();
      state.terrain.geometry.dispose();
      state.terrain.geometry = geometry;
      state.water.position.y = current.waterLevel;
      const size = Math.max(current.width, current.depth);
      state.grid.scale.set(size / 96, 1, size / 96);
      state.grid.position.y = current.waterLevel + 0.08;
      const angle = THREE.MathUtils.degToRad(current.sunAngle);
      sun.position.set(Math.cos(angle) * 75, 70, Math.sin(angle) * 75);
      state.scene.fog = current.fog ? new THREE.Fog("#172b40", size * 0.55, size * 2.7) : null;

      state.objects.forEach((item) => { state.scene.remove(item); disposeObject(item); });
      state.objects = current.objects.map((item) => buildObject(
        item, terrainHeight(current.seed, item.x, item.z, current.amplitude, current.frequency, current.terrainEdits, current.width, current.depth, current.resolution)
      ));
      state.objects.forEach((item) => state.scene.add(item));

      if (state.selectedRing) {
        state.scene.remove(state.selectedRing);
        disposeObject(state.selectedRing as unknown as THREE.Group);
      }
      state.selectedRing = null;
      const selected = state.objects.find((item) => item.userData.objectId === current.selectedId);
      if (selected) {
        const ring = new THREE.Mesh(
          new THREE.RingGeometry(2.2, 2.42, 48),
          new THREE.MeshBasicMaterial({ color: "#7bc8ff", side: THREE.DoubleSide })
        );
        ring.rotation.x = -Math.PI / 2;
        ring.position.set(selected.position.x, selected.position.y + 0.12, selected.position.z);
        ring.scale.setScalar(Math.max(0.55, selected.scale.x));
        state.scene.add(ring);
        state.selectedRing = ring;
      }
    };

    rebuildWorld(liveProps.current);
    const frame = (now: number) => {
      state.animation = requestAnimationFrame(frame);
      const delta = Math.min(0.05, state.lastTime ? (now - state.lastTime) / 1000 : 0.016);
      state.lastTime = now;
      if (liveProps.current.mode === "play" && pointer.isLocked) {
        const forward = new THREE.Vector3();
        camera.getWorldDirection(forward);
        forward.y = 0;
        forward.normalize();
        const right = new THREE.Vector3().crossVectors(forward, new THREE.Vector3(0, 1, 0)).negate().normalize();
        const move = new THREE.Vector3();
        if (keys.has("w")) move.add(forward);
        if (keys.has("s")) move.sub(forward);
        if (keys.has("d")) move.add(right);
        if (keys.has("a")) move.sub(right);
        if (move.lengthSq()) move.normalize();
        camera.position.addScaledVector(move, (keys.has("shift") ? 16 : 8) * delta);
        const halfWidth = liveProps.current.width / 2 - 1;
        const halfDepth = liveProps.current.depth / 2 - 1;
        camera.position.x = clamp(camera.position.x, -halfWidth, halfWidth);
        camera.position.z = clamp(camera.position.z, -halfDepth, halfDepth);
        const floor = terrainHeight(liveProps.current.seed, camera.position.x, camera.position.z, liveProps.current.amplitude, liveProps.current.frequency, liveProps.current.terrainEdits, liveProps.current.width, liveProps.current.depth, liveProps.current.resolution) + 1.7;
        if (keys.has(" ") && camera.position.y <= floor + 0.04) state.verticalVelocity = 6.4;
        state.verticalVelocity -= 18 * delta;
        camera.position.y += state.verticalVelocity * delta;
        if (camera.position.y < floor) { camera.position.y = floor; state.verticalVelocity = 0; }
      } else {
        orbit.update();
      }
      renderer.render(scene, camera);
    };
    state.animation = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(state.animation);
      renderer.domElement.removeEventListener("click", onCanvasClick);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("resize", resize);
      pointer.unlock();
      orbit.dispose();
      renderer.dispose();
      if (renderer.domElement.parentElement === host) host.removeChild(renderer.domElement);
      stateRef.current = null;
    };
  }, []);

  useEffect(() => {
    liveProps.current = props;
    const state = stateRef.current;
    if (!state) return;
    const current = props;
    const geometry = new THREE.PlaneGeometry(current.width, current.depth, 100, 100);
    geometry.rotateX(-Math.PI / 2);
    const positions = geometry.attributes.position as THREE.BufferAttribute;
    const colors: number[] = [];
    for (let i = 0; i < positions.count; i++) {
      const x = positions.getX(i), z = positions.getZ(i);
      const height = terrainHeight(current.seed, x, z, current.amplitude, current.frequency, current.terrainEdits, current.width, current.depth, current.resolution);
      positions.setY(i, height);
      const moisture = noise2(current.seed + 991, x * 0.12, z * 0.12);
      const color = height < -1.8 ? new THREE.Color("#315e78") :
        height > 5.5 ? new THREE.Color("#858c92") :
        moisture < -0.25 ? new THREE.Color("#a78a68") :
        moisture > 0.35 ? new THREE.Color("#477768") : new THREE.Color("#829172");
      colors.push(color.r, color.g, color.b);
    }
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    geometry.computeVertexNormals();
    state.terrain.geometry.dispose();
    state.terrain.geometry = geometry;
    state.water.position.y = current.waterLevel;
    const size = Math.max(current.width, current.depth);
    state.grid.scale.set(size / 96, 1, size / 96);
    state.grid.position.y = current.waterLevel + 0.08;
    const sun = state.scene.children.find((item) => item instanceof THREE.DirectionalLight);
    sun?.position.set(Math.cos(THREE.MathUtils.degToRad(current.sunAngle)) * 75, 70, Math.sin(THREE.MathUtils.degToRad(current.sunAngle)) * 75);
    state.scene.fog = current.fog ? new THREE.Fog("#172b40", size * 0.55, size * 2.7) : null;
    state.objects.forEach((item) => { state.scene.remove(item); disposeObject(item); });
    state.objects = current.objects.map((item) => buildObject(item, terrainHeight(current.seed, item.x, item.z, current.amplitude, current.frequency, current.terrainEdits, current.width, current.depth, current.resolution)));
    state.objects.forEach((item) => state.scene.add(item));
    if (state.selectedRing) {
      state.scene.remove(state.selectedRing);
      state.selectedRing.geometry.dispose();
      (state.selectedRing.material as THREE.Material).dispose();
    }
    state.selectedRing = null;
    const selected = state.objects.find((item) => item.userData.objectId === current.selectedId);
    if (selected) {
      const ring = new THREE.Mesh(new THREE.RingGeometry(2.2, 2.42, 48), new THREE.MeshBasicMaterial({ color: "#7bc8ff", side: THREE.DoubleSide }));
      ring.rotation.x = -Math.PI / 2;
      ring.position.set(selected.position.x, selected.position.y + 0.12, selected.position.z);
      ring.scale.setScalar(Math.max(0.55, selected.scale.x));
      state.scene.add(ring);
      state.selectedRing = ring;
    }
    if (current.mode === "play") {
      state.camera.position.set(0, terrainHeight(current.seed, 0, 18, current.amplitude, current.frequency, current.terrainEdits, current.width, current.depth, current.resolution) + 1.7, 18);
      state.camera.lookAt(0, terrainHeight(current.seed, 0, 0, current.amplitude, current.frequency, current.terrainEdits, current.width, current.depth, current.resolution), 0);
    } else {
      state.orbit.target.set(0, 0, 0);
    }
  }, [props.seed, props.width, props.depth, props.amplitude, props.frequency, props.waterLevel, props.fog, props.sunAngle, props.objects, props.selectedId, props.mode, props.terrainEdits, props.resolution]);

  useEffect(() => {
    const state = stateRef.current;
    if (!state) return;
    if (props.mode === "play") {
      state.orbit.enabled = false;
      state.pointer.unlock();
      const floor = terrainHeight(props.seed, 0, 18, props.amplitude, props.frequency, props.terrainEdits, props.width, props.depth, props.resolution);
      state.camera.position.set(0, floor + 1.7, 18);
      state.camera.lookAt(0, terrainHeight(props.seed, 0, 0, props.amplitude, props.frequency, props.terrainEdits, props.width, props.depth, props.resolution), 0);
    } else {
      state.pointer.unlock();
      state.orbit.enabled = true;
      state.camera.position.set(0, 24, 38);
      state.orbit.target.set(0, 0, 0);
      state.orbit.update();
    }
  }, [props.mode]);

  return <div className="world-canvas" ref={hostRef}>
    <div className="canvas-hud"><span className="canvas-dot" /> {props.mode === "play" ? "EXPLORATION MODE" : "LIVE PROCEDURAL PREVIEW"}
      {props.sculptMode && props.mode === "edit" ? <b>CLICK TO {props.sculptMode.toUpperCase()} TERRAIN</b> : props.placementType && props.mode === "edit" ? <b>CLICK THE TERRAIN TO PLACE {props.placementType.toUpperCase()}</b> : null}
    </div>
    {props.mode === "play" ? <div className="play-hud">W A S D · MOVE　 SHIFT · SPRINT　 SPACE · JUMP　 ESC · RELEASE MOUSE</div> : <div className="canvas-credit">SEEDED TERRAIN · REAL-TIME SCENE · NO GENERATIVE MODEL</div>}
  </div>;
}
