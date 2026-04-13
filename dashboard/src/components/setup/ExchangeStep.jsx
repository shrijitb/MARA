import { useState } from 'react';
import { cn } from '../../utils/cn.js';

function SecretField({ label, placeholder, value, onChange }) {
  const [show, setShow] = useState(false);
  return (
    <div className="mb-3.5">
      <label className="block text-[10px] font-bold uppercase tracking-widest text-muted mb-1.5">{label}</label>
      <div className="relative">
        <input
          type={show ? 'text' : 'password'}
          placeholder={placeholder}
          value={value}
          onChange={e => onChange(e.target.value)}
          className="w-full px-4 py-2.5 pr-11 bg-black border border-edge rounded-xl text-cream text-sm font-jetbrains outline-none focus:border-warn/50 transition-colors placeholder:text-muted/30"
        />
        <button
          type="button"
          onClick={() => setShow(v => !v)}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-cream transition-colors text-base"
        >
          {show ? '🙈' : '👁'}
        </button>
      </div>
    </div>
  );
}

export default function ExchangeStep({ onNext, onBack, onSave }) {
  const [key, setKey]   = useState('');
  const [sec, setSec]   = useState('');
  const [pass, setPass] = useState('');
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    const creds = {};
    if (key.trim())  creds.OKX_API_KEY = key.trim();
    if (sec.trim())  creds.OKX_API_SECRET = sec.trim();
    if (pass.trim()) creds.OKX_API_PASSPHRASE = pass.trim();
    if (Object.keys(creds).length) await onSave(creds);
    setSaving(false);
    onNext();
  }

  return (
    <div className="anim-fade-in max-w-md mx-auto">
      <div className="bg-card border border-edge rounded-2xl p-6 mb-4">
        <p className="text-[10px] font-bold uppercase tracking-widest text-muted mb-1">Step 3 of 6</p>
        <h2 className="text-xl font-bold text-cream mb-1">Connect to OKX</h2>
        <p className="text-sm text-muted leading-relaxed mb-5">
          Arka needs API keys to read market data and trade.
          Everything runs in <span className="text-warn font-semibold">paper trading mode</span> now — skip this until you're ready to go live.
        </p>

        {/* Guide */}
        <div className="bg-warn/5 border border-warn/15 rounded-xl p-3.5 mb-5 text-xs text-muted leading-relaxed space-y-0.5">
          <p>1. Go to <span className="text-cream font-semibold">okx.com → Settings → API Keys</span></p>
          <p>2. Create a key with <span className="text-cream font-semibold">Trade</span> permissions</p>
          <p>3. Copy the three values below</p>
        </div>

        <SecretField label="API Key"    placeholder="Leave blank for paper trading" value={key}  onChange={setKey} />
        <SecretField label="Secret Key" placeholder="Leave blank for paper trading" value={sec}  onChange={setSec} />
        <SecretField label="Passphrase" placeholder="Leave blank for paper trading" value={pass} onChange={setPass} />

        <div className="flex items-start gap-2 mt-4 p-3 bg-profit/5 border border-profit/15 rounded-xl text-xs text-muted">
          <span className="shrink-0">🔒</span>
          <span>These never leave your device. Stored locally, never sent to any external server.</span>
        </div>
      </div>

      <div className="flex gap-2.5">
        <button onClick={onBack}  className={ghost}>← Back</button>
        <button onClick={onNext}  className={cn(ghost, 'text-muted/60 hover:text-muted')}>Skip</button>
        <button onClick={save} disabled={saving} className={cn(primary, saving && 'opacity-70')}>
          {saving ? 'Saving...' : 'Save & Next →'}
        </button>
      </div>
    </div>
  );
}

const primary = 'flex-1 py-3 bg-warn text-black font-bold text-sm rounded-xl hover:bg-warn/90 active:scale-[0.98] transition-all';
const ghost   = 'px-4 py-3 bg-transparent border border-edge text-muted text-sm rounded-xl hover:border-line hover:text-cream transition-all';
