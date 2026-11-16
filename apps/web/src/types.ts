export type ObjectKind = "outpost" | "beacon" | "tree" | "rock" | "crate";
export type SceneObject = {
  id: string;
  name: string;
  kind: ObjectKind;
  x: number;
  y: number;
  z: number;
  rotation: number;
  scale: number;
  color: string;
};
export type WorldDocument = {
  seed: number;
  world: {
    width: number;
    depth: number;
    resolution: number;
    amplitude: number;
    frequency: number;
    biomes: string[];
    weather: boolean;
  };
  objects: SceneObject[];
  sun_angle: number;
  fog: boolean;
  water_level: number;
};
