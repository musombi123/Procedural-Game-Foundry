import { useEffect, useRef, useState } from "react";
import { NEXORA_TOUR } from "./nexoraTourConfig";
type Props = { open: boolean; onClose: (state: "completed" | "skipped") => void; onStart: () => void };
const STORAGE_KEY = "nexora_guided_tour_v1";
export default function NexoraGuidedTour({ open, onClose, onStart }: Props) {
  const [index, setIndex] = useState(0);
  const card = useRef<HTMLDivElement>(null);
  const [targetBox, setTargetBox] = useState<DOMRect | null>(null);
  useEffect(() => {
    if (!open) return;
    const step = NEXORA_TOUR[index];
    const el = document.querySelector(step.target);
    if (el) {
      (el as HTMLElement).scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
      const rect = el.getBoundingClientRect();
      setTargetBox(rect);
      el.classList.add("nexora-tour-highlight");
      (el as HTMLElement).setAttribute("data-tour-current", "true");
    } else setTargetBox(null);
    card.current?.focus();
    const clickAdvance = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (step.action && target?.closest(step.target)) setIndex(current => Math.min(current + 1, NEXORA_TOUR.length - 1));
    };
    document.addEventListener("click", clickAdvance, true);
    return () => {
      document.removeEventListener("click", clickAdvance, true);
      document.querySelectorAll(".nexora-tour-highlight").forEach(el => el.classList.remove("nexora-tour-highlight"));
      document.querySelectorAll("[data-tour-current]").forEach(el => el.removeAttribute("data-tour-current"));
    };
  }, [open, index]);
  useEffect(() => {
    if (!open) return;
    const keyHandler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose("skipped");
      if (event.key === "ArrowRight") setIndex(current => Math.min(current + 1, NEXORA_TOUR.length - 1));
      if (event.key === "ArrowLeft") setIndex(current => Math.max(current - 1, 0));
      if (event.key === "Tab" && card.current) {
        const focusables = card.current.querySelectorAll<HTMLElement>("button:not([disabled])");
        if (!focusables.length) return;
        const first = focusables[0], last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", keyHandler);
    return () => document.removeEventListener("keydown", keyHandler);
  }, [open, onClose]);
  if (!open) return null;
  const step = NEXORA_TOUR[index];
  const smallScreen = window.matchMedia("(max-width: 700px)").matches;
  return <div className="nexora-tour-scrim" role="presentation">
    {targetBox && !smallScreen && <div className="nexora-tour-arrow" style={{ left: Math.max(12, Math.min(targetBox.left + targetBox.width / 2 - 18, window.innerWidth - 44)), top: Math.max(12, targetBox.top - 54) }} aria-hidden="true">👉</div>}
    <div className={smallScreen ? "nexora-tour-card bottom-sheet" : "nexora-tour-card"} role="dialog" aria-modal="true" aria-labelledby="nexora-tour-title" aria-describedby="nexora-tour-body" tabIndex={-1} ref={card}>
      <div className="nexora-tour-step">STEP {index + 1} OF {NEXORA_TOUR.length}</div>
      <h2 id="nexora-tour-title">{step.title}</h2><p id="nexora-tour-body">{step.body}</p>
      <div className="nexora-tour-actions"><button onClick={() => onClose("skipped")}>Skip</button><button disabled={index === 0} onClick={() => setIndex(current => Math.max(0, current - 1))}>Back</button>{index < NEXORA_TOUR.length - 1 ? <button className="tour-next" onClick={() => setIndex(current => Math.min(current + 1, NEXORA_TOUR.length - 1))}>Next</button> : <button className="tour-next" onClick={() => { onClose("completed"); onStart(); }}>Start my first game</button>}</div>
    </div>
  </div>;
}
