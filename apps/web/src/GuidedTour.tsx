import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NEXORA_TOUR, NEXORA_TOUR_VERSION, type TourStep } from "./nexoraTourConfig";

type TourRecord = { version: number; completed: boolean; skipped: boolean; last_step: number };
type Props = { onStart?: () => void };
const LOCAL_KEY = "nexora:guided-tour:v1";
const API = (import.meta.env.VITE_NEXORA_ACCOUNT_API ?? import.meta.env.VITE_PGF_API ?? "http://127.0.0.1:8765/engine").replace(/\/$/, "");
const TOKEN_KEY = "nexora_access_token";

function readLocal(): TourRecord {
  try {
    const value = JSON.parse(localStorage.getItem(LOCAL_KEY) ?? "null");
    if (value && value.version === NEXORA_TOUR_VERSION) return value as TourRecord;
  } catch { /* use first-run defaults */ }
  return { version: NEXORA_TOUR_VERSION, completed: false, skipped: false, last_step: 0 };
}

export default function GuidedTour({ onStart }: Props) {
  const [record, setRecord] = useState<TourRecord>(readLocal);
  const [active, setActive] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const step = NEXORA_TOUR[stepIndex];

  const persist = useCallback(async (next: TourRecord) => {
    setRecord(next);
    localStorage.setItem(LOCAL_KEY, JSON.stringify(next));
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) return;
    try {
      await fetch(API + "/api/v1/profile/tour", {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
        body: JSON.stringify(next)
      });
    } catch { /* browser copy remains available if the account service is offline */ }
  }, []);

  const begin = useCallback((resume = false) => {
    previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const nextIndex = resume ? Math.max(0, Math.min(NEXORA_TOUR.length - 1, record.last_step)) : 0;
    setStepIndex(nextIndex);
    setActive(true);
  }, [record.last_step]);

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      if (!record.completed && !record.skipped) begin(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch(API + "/api/v1/profile/tour", { headers: { Authorization: "Bearer " + token } });
        if (!response.ok) throw new Error("Tour profile unavailable");
        const payload = await response.json();
        const remote = payload.tour as TourRecord | undefined;
        if (cancelled || !remote || remote.version !== NEXORA_TOUR_VERSION) {
          if (!cancelled && !record.completed && !record.skipped) begin(false);
          return;
        }
        setRecord(remote);
        localStorage.setItem(LOCAL_KEY, JSON.stringify(remote));
        if (!remote.completed && !remote.skipped) begin(false);
      } catch {
        if (!cancelled && !record.completed && !record.skipped) begin(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!active) return;
    const update = () => {
      const target = step.target ? document.querySelector(step.target) as HTMLElement | null : null;
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
        setRect(target.getBoundingClientRect());
      } else setRect(null);
    };
    const timer = window.setTimeout(update, 80);
    const observer = new ResizeObserver(update);
    observer.observe(document.body);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => { window.clearTimeout(timer); observer.disconnect(); window.removeEventListener("resize", update); window.removeEventListener("scroll", update, true); };
  }, [active, step]);

  useEffect(() => {
    if (!active) return;
    cardRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); void finish(true); }
      if (event.key === "ArrowRight") { event.preventDefault(); next(); }
      if (event.key === "ArrowLeft") { event.preventDefault(); back(); }
      if (event.key === "Tab" && cardRef.current) {
        const items = Array.from(cardRef.current.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],[tabindex="0"]'));
        if (!items.length) return;
        const first = items[0], last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  useEffect(() => {
    if (!active || !step.target) return;
    const target = document.querySelector(step.target) as HTMLElement | null;
    if (!target) return;
    const onTarget = () => { if (stepIndex < NEXORA_TOUR.length - 1) next(); };
    target.addEventListener("click", onTarget, { once: true });
    return () => target.removeEventListener("click", onTarget);
  }, [active, step, stepIndex]);

  const finish = useCallback(async (skipped: boolean) => {
    const nextRecord = { version: NEXORA_TOUR_VERSION, completed: !skipped, skipped, last_step: stepIndex };
    await persist(nextRecord);
    setActive(false);
    previousFocus.current?.focus();
  }, [persist, stepIndex]);

  const next = useCallback(() => {
    if (stepIndex >= NEXORA_TOUR.length - 1) { void finish(false); return; }
    const nextIndex = stepIndex + 1;
    setStepIndex(nextIndex);
    void persist({ version: NEXORA_TOUR_VERSION, completed: false, skipped: false, last_step: nextIndex });
  }, [finish, persist, stepIndex]);

  const back = useCallback(() => {
    const nextIndex = Math.max(0, stepIndex - 1);
    setStepIndex(nextIndex);
    void persist({ version: NEXORA_TOUR_VERSION, completed: false, skipped: false, last_step: nextIndex });
  }, [persist, stepIndex]);

  const isSmall = typeof window !== "undefined" && window.matchMedia("(max-width: 700px)").matches;
  const position = useMemo(() => {
    if (!rect || isSmall) return undefined;
    const width = 340, left = Math.max(16, Math.min(window.innerWidth - width - 16, rect.left + rect.width / 2 - width / 2));
    const top = rect.bottom + 16 + 190 < window.innerHeight ? rect.bottom + 16 : Math.max(16, rect.top - 206);
    return { left, top };
  }, [rect, isSmall]);

  if (!active) return <button className="tour-replay" data-tour="help" onClick={() => begin(false)} aria-label="Take the NEXORA guided tour">Help · Take the tour</button>;
  return <div className="tour-overlay" role="presentation">
    {rect && !isSmall && <div className="tour-spotlight" style={{ left: rect.left - 7, top: rect.top - 7, width: rect.width + 14, height: rect.height + 14 }} />}
    {rect && <div className="tour-arrow" style={isSmall ? undefined : { left: Math.max(16, Math.min(window.innerWidth - 40, rect.left + rect.width / 2 - 18)), top: Math.max(12, rect.top - 42) }} aria-hidden="true">👉</div>}
    <section className={isSmall ? "tour-card mobile" : "tour-card"} ref={cardRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-description" style={position}>
      <div className="tour-card-top"><span>NEXORA QUICK TOUR</span><span>Step {stepIndex + 1} of {NEXORA_TOUR.length}</span></div>
      <h2 id="tour-title">{step.title}</h2>
      <p id="tour-description">{step.body}</p>
      <div className="tour-progress" aria-label={Math.round(((stepIndex + 1) / NEXORA_TOUR.length) * 100) + "% complete"}><span style={{ width: ((stepIndex + 1) / NEXORA_TOUR.length * 100) + "%" }} /></div>
      <div className="tour-controls">
        <button onClick={back} disabled={stepIndex === 0}>Back</button>
        <button onClick={() => void finish(true)} className="tour-skip">Skip</button>
        <button onClick={next} className="tour-next">{stepIndex === NEXORA_TOUR.length - 1 ? "Finish" : "Next"}</button>
      </div>
      {stepIndex === NEXORA_TOUR.length - 1 && <button className="tour-start" onClick={() => { void finish(false); onStart?.(); }}>Start my first game</button>}
    </section>
  </div>;
}
