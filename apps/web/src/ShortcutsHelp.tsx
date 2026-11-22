type Props = { onClose: () => void };
export default function ShortcutsHelp({ onClose }: Props) {
  return <div className="command-overlay" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="shortcuts-dialog" role="dialog" aria-modal="true" aria-labelledby="shortcuts-title">
      <header><div><small>NEXORA HELP</small><h2 id="shortcuts-title">Keyboard shortcuts</h2></div><button onClick={onClose} aria-label="Close shortcuts">×</button></header>
      <div className="shortcuts-list">
        <div><span>Open command palette</span><kbd>Ctrl K</kbd></div>
        <div><span>Save current scene / IDE file</span><kbd>Ctrl S</kbd></div>
        <div><span>Enter test preview</span><kbd>Ctrl Enter</kbd></div>
        <div><span>Move in play preview</span><kbd>W A S D</kbd></div>
        <div><span>Replay guided tour</span><kbd>Help → Take the tour</kbd></div>
      </div>
      <p>Undo/redo, create-level and export shortcuts will be listed here when those actions are available in this workspace. They are not wired yet.</p>
      <button className="button primary" onClick={onClose}>Done</button>
    </section>
  </div>;
}
