import { useState } from 'react';
import { cn } from '../utils/cn.js';

export default function GlobalControls({ onOpenSettings }) {
  const [open, setOpen] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [stopping, setStopping] = useState(false);
  const [stopped, setStopped] = useState(false);

  const confirmed = confirmText === 'STOP';

  async function handleStop() {
    if (!confirmed) return;
    setStopping(true);
    try {
      await Promise.all([
        fetch('/api/pause', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ worker: 'all' }) }),
      ]);
      setStopped(true);
    } catch (e) {
      console.error('Stop failed:', e);
    } finally {
      setStopping(false);
    }
  }

  function closeModal() {
    setOpen(false);
    setConfirmText('');
    setStopped(false);
  }

  return (
    <>
      <div className="flex gap-2">
        {/* Settings */}
        <button
          onClick={onOpenSettings}
          className="flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border border-edge text-muted text-xs font-semibold hover:border-line hover:text-cream transition-all duration-200"
        >
          ⚙ Settings
        </button>

        {/* Emergency Stop */}
        <button
          onClick={() => setOpen(true)}
          className="flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-loss/10 border border-loss/30 text-loss text-xs font-bold hover:bg-loss/20 hover:border-loss/60 transition-all duration-200"
        >
          ⬛ Emergency Stop
        </button>
      </div>

      {/* Modal */}
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(8px)' }}
        >
          <div className="anim-slide-up w-full max-w-sm bg-modal border border-line rounded-2xl p-7 shadow-2xl">
            {stopped ? (
              <div className="text-center">
                <div className="text-4xl mb-4">✅</div>
                <h3 className="text-cream text-lg font-bold mb-2">All workers paused</h3>
                <p className="text-muted text-sm mb-6 leading-relaxed">
                  No new trades will be placed. Existing positions remain open.
                  Resume workers from their individual cards.
                </p>
                <button
                  onClick={closeModal}
                  className="w-full py-3 rounded-xl bg-surface border border-line text-muted font-semibold text-sm hover:text-cream transition-colors"
                >
                  Close
                </button>
              </div>
            ) : (
              <>
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-9 h-9 rounded-full bg-loss/10 border border-loss/30 flex items-center justify-center text-lg">⚠️</div>
                  <h3 className="text-cream text-base font-bold">Emergency Stop</h3>
                </div>

                <p className="text-muted text-sm leading-relaxed mb-5">
                  This will immediately halt all trading across every worker.
                  Open positions will remain open but no new trades will be placed.
                </p>

                <div className="mb-4">
                  <label className="block text-xs font-semibold text-muted uppercase tracking-widest mb-2">
                    Type <span className="text-loss font-jetbrains">STOP</span> to confirm
                  </label>
                  <input
                    type="text"
                    value={confirmText}
                    onChange={e => setConfirmText(e.target.value.toUpperCase())}
                    placeholder="STOP"
                    autoFocus
                    className="w-full px-4 py-2.5 bg-black border border-line rounded-lg text-cream text-sm font-jetbrains outline-none focus:border-loss/60 transition-colors placeholder:text-muted/40"
                  />
                </div>

                <div className="flex gap-2.5">
                  <button
                    onClick={closeModal}
                    className="flex-1 py-2.5 rounded-xl bg-surface border border-line text-muted text-sm font-semibold hover:text-cream transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleStop}
                    disabled={!confirmed || stopping}
                    className={cn(
                      'flex-1 py-2.5 rounded-xl font-bold text-sm transition-all duration-200',
                      confirmed
                        ? 'bg-loss text-black hover:bg-loss/90 cursor-pointer'
                        : 'bg-edge text-muted cursor-not-allowed'
                    )}
                  >
                    {stopping ? 'Stopping...' : 'Confirm Stop'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
