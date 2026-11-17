import { useEffect, useRef } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

export default function AvatarPreview({src}:{src:string}){
 const host=useRef<HTMLDivElement|null>(null);
 useEffect(()=>{
  const root=host.current;if(!root)return;
  const scene=new THREE.Scene();scene.background=new THREE.Color("#101b2a");
  const camera=new THREE.PerspectiveCamera(35,1,.01,100);camera.position.set(0,1.1,3.5);
  const renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));renderer.outputColorSpace=THREE.SRGBColorSpace;root.appendChild(renderer.domElement);
  const controls=new OrbitControls(camera,renderer.domElement);controls.target.set(0,.9,0);controls.enableDamping=true;
  scene.add(new THREE.HemisphereLight(0xffffff,0x26364a,2));
  const key=new THREE.DirectionalLight(0xffffff,2.2);key.position.set(3,5,4);scene.add(key);
  const floor=new THREE.GridHelper(4,20,0x42566e,0x26384d);floor.position.y=0;scene.add(floor);
  const resize=()=>{const w=Math.max(1,root.clientWidth),h=Math.max(220,root.clientHeight);camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h);};resize();
  const observer=new ResizeObserver(resize);observer.observe(root);
  let disposed=false;let frame=0;
  new GLTFLoader().load(src,gltf=>{if(disposed)return;scene.add(gltf.scene);const box=new THREE.Box3().setFromObject(gltf.scene);const center=box.getCenter(new THREE.Vector3());controls.target.copy(center);camera.position.set(center.x,center.y+.45,center.z+Math.max(2.5,box.getSize(new THREE.Vector3()).y*1.8));controls.update();},undefined,()=>{});
  const animate=()=>{if(disposed)return;frame=requestAnimationFrame(animate);controls.update();renderer.render(scene,camera);};animate();
  return()=>{disposed=true;cancelAnimationFrame(frame);observer.disconnect();controls.dispose();renderer.dispose();root.removeChild(renderer.domElement);};
 },[src]);
 return <div ref={host} aria-label="Interactive 3D player avatar preview" style={{width:"100%",height:340,borderRadius:10,overflow:"hidden",border:"1px solid #334b66"}}/>;
}
