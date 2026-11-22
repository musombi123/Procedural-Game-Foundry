type Props = { onClose: () => void };
export default function ShortcutsHelp({ onClose }: Props) {
  return <div className="command-overlay" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="shortcuts-dialog" role="dialog" aria-modal="true" aria-labelledby="shortcuts-title">
      <header><div><small>NEXORA HELP</small><h2 id="shortcuts-title">Keyboard shortcuts</h2></div><button onClick={onClose} aria-label="Close shortcuts">×</button></header>
      <div className="shortcuts-list">
        <div><span>Open command palette</span><kbd>Ctrl K</kbd></div>
        <div><span>Save current scene / IDE file</span><kbd>Ctrl S</kbd></div>
        <div><span>Undo scene edit</span><kbd>Ctrl Z</kbd></div>
        <div><span>Redo scene edit</span><kbd>Ctrl Y / Ctrl Shift Z</kbd></div>
        <div><span>Enter test preview</span><kbd>Ctrl Enter</kbd></div>
        <div><span>Move in play preview</span><kbd>W A S D</kbd></div>
        <div><span>Replay guided tour</span><kbd>Help → Take the tour</kbd></div>
      </div>
      <p>Create-level and export shortcuts are not assigned yet because those actions are not exposed in this workspace.</p>
      <div className="shortcuts-actions"><button className="button secondary" onClick={() => { onClose(); window.dispatchEvent(new Event("nexora:replay-tour")); }}>Take the tour</button><button className="button primary" onClick={onClose}>Done</button></div>
    </section>
  </div>;
}
