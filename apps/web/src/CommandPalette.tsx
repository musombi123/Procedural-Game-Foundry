import { useEffect, useMemo, useState } from "react";

type View = "workspace" | "world" | "scene" | "ide" | "monetization";
type Props = { selected: boolean; onNavigate: (view: View) => void; onHelp: () => void; onClose: () => void };

export default function CommandPalette({ selected, onNavigate, onHelp, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const commands = useMemo(() => [
    { label: "Overview / Home", detail: "Open project workspace", run: () => onNavigate("workspace") },
    { label: "World Foundry", detail: "Terrain and environment tools", run: () => onNavigate("world") },
    { label: "Scene Editor", detail: "Place and edit scene objects", run: () => onNavigate("scene") },
    { label: "Internal IDE", detail: "Edit project source files", disabled: !selected, run: () => onNavigate("ide") },
    { label: "Monetization Center", detail: "Configure game add-ons", disabled: !selected, run: () => onNavigate("monetization") },
    { label: "Asset Collection Center", detail: "Jump to project assets", run: () => { onNavigate("workspace"); window.setTimeout(() => document.querySelector('[data-tour="asset-center"]')?.scrollIntoView({ behavior: "smooth", block: "start" }), 80); } },
    { label: "Shortcuts and help", detail: "Keyboard reference and guided tour", run: onHelp }
  ].filter(item => (item.label + " " + item.detail).toLowerCase().includes(query.toLowerCase())), [onHelp, onNavigate, query, selected]);
  useEffect(() => setActive(0), [query]);
  function onKey(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") { event.preventDefault(); setActive(value => Math.min(commands.length - 1, value + 1)); }
    if (event.key === "ArrowUp") { event.preventDefault(); setActive(value => Math.max(0, value - 1)); }
    if (event.key === "Enter" && commands[active] && !commands[active].disabled) { event.preventDefault(); commands[active].run(); onClose(); }
    if (event.key === "Escape") onClose();
  }
  return <div className="command-overlay" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="command-dialog" role="dialog" aria-modal="true" aria-label="NEXORA command palette">
      <input autoFocus value={query} onChange={event => setQuery(event.target.value)} onKeyDown={onKey} placeholder="Search tools, assets, levels or settings…" aria-label="Search commands"/>
      <div className="command-results">{commands.map((command, index) => <button key={command.label} disabled={command.disabled} className={index === active ? "active" : ""} onMouseEnter={() => setActive(index)} onClick={() => { command.run(); onClose(); }}><span><b>{command.label}</b><small>{command.detail}</small></span><kbd>↵</kbd></button>)}{!commands.length && <p>No matching commands.</p>}</div>
      <footer><span>↑ ↓ Navigate</span><span>Enter Open</span><span>Esc Close</span></footer>
    </section>
  </div>;
}
