import { useState } from "react";

const sponsorName = String(import.meta.env.VITE_NEXORA_SPONSOR_NAME ?? "").trim();
const sponsorMessage = String(import.meta.env.VITE_NEXORA_SPONSOR_MESSAGE ?? "").trim();
const sponsorUrl = String(import.meta.env.VITE_NEXORA_SPONSOR_URL ?? "").trim();
const sponsorImage = String(import.meta.env.VITE_NEXORA_SPONSOR_IMAGE ?? "").trim();

export default function StudioSponsorSlot() {
  const [dismissed, setDismissed] = useState(false);
  let safeUrl = "";
  let safeImage = "";
  try {
    const parsed = new URL(sponsorUrl);
    if (parsed.protocol === "https:") safeUrl = parsed.toString();
  } catch { /* invalid or unconfigured sponsor URL stays hidden */ }
  try {
    const parsed = new URL(sponsorImage);
    if (parsed.protocol === "https:") safeImage = parsed.toString();
  } catch { /* optional image */ }

  if (dismissed || !sponsorName || !sponsorMessage || !safeUrl) return null;

  return <aside className="studio-sponsor-slot" aria-label="Sponsored placement">
    <div className="studio-sponsor-copy"><span className="studio-sponsored-label">SPONSORED</span><b>{sponsorName}</b><p>{sponsorMessage}</p><a href={safeUrl} target="_blank" rel="noopener noreferrer sponsored">Explore sponsor ↗</a></div>
    {safeImage && <img src={safeImage} alt="" loading="lazy" referrerPolicy="no-referrer"/>}
    <button type="button" aria-label="Dismiss sponsored placement" onClick={() => setDismissed(true)}>×</button>
  </aside>;
}
