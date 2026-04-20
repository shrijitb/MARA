import { useState } from 'react';
import { cn } from '../../utils/cn.js';

export default function TelegramStep({ onNext, onBack, onSave }) {
  const [token,  setToken]  = useState('');
  const [userId, setUserId] = useState('');
  const [ntfy,   setNtfy]   = useState('');
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    const creds = {};
    if (token.trim())  creds.TELEGRAM_BOT_TOKEN = token.trim();
    if (userId.trim()) creds.TELEGRAM_ALLOWED_USER_ID = userId.trim();
    if (ntfy.trim())   creds.NTFY_TOPIC = ntfy.trim();
    if (Object.keys(creds).length) await onSave(creds);
    setSaving(false);
    onNext();
  }

  return (
    <div className="anim-fade-in max-w-md mx-auto">
      <div className="bg-card border border-edge rounded-2xl p-6 mb-4 space-y-5">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-muted mb-1">Step 5 of 6</p>
          <div className="flex items-center gap-2 mb-1">
            <h2 className="text-xl font-bold text-cream">Phone Notifications</h2>
            <span className="text-[9px] font-bold uppercase tracking-wider bg-edge text-muted px-2 py-0.5 rounded-full">Optional</span>
          </div>
          <p className="text-sm text-muted leading-relaxed">
            Get alerts for regime changes, big trades, and risk events.
          </p>
        </div>

        {/* Telegram */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-base">📱</span>
            <span className="text-sm font-bold text-cream">Telegram Bot</span>
          </div>
          <div className="bg-warn/5 border border-warn/15 rounded-xl p-3 mb-3 text-xs text-muted leading-relaxed space-y-0.5">
            <p>1. Open Telegram → search <span className="text-cream font-semibold">@BotFather</span></p>
            <p>2. Send <span className="font-jetbrains bg-edge px-1 rounded">/newbot</span>, follow prompts</p>
            <p>3. Copy the token below</p>
            <p className="mt-1">4. Search <span className="text-cream font-semibold">@userinfobot</span> to get your User ID</p>
          </div>
          <div className="space-y-2">
            <Field label="Bot Token"       placeholder="Paste token from @BotFather" type="password" value={token}  onChange={setToken} />
            <Field label="Your User ID"    placeholder="Numeric ID from @userinfobot" type="text"    value={userId} onChange={setUserId} />
          </div>
        </div>

        {/* ntfy divider */}
        <div className="border-t border-edge pt-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-base">🔔</span>
            <span className="text-sm font-bold text-cream">ntfy Push Notifications</span>
            <span className="text-[9px] text-muted">— alternative to Telegram</span>
          </div>
          <p className="text-xs text-muted mb-2.5">
            Free push via <a href="https://ntfy.sh" target="_blank" rel="noopener noreferrer" className="text-warn/80 hover:text-warn">ntfy.sh</a> — iOS and Android, no account needed.
          </p>
          <Field label="ntfy Topic" placeholder="e.g. my-arca-alerts-abc123 (choose anything unique)" type="text" value={ntfy} onChange={setNtfy} />
        </div>
      </div>

      <div className="flex gap-2.5">
        <button onClick={onBack} className={ghost}>← Back</button>
        <button onClick={onNext} className={cn(ghost, 'text-muted/60 hover:text-muted')}>Skip</button>
        <button onClick={save} disabled={saving} className={cn(primary, saving && 'opacity-70')}>
          {saving ? 'Saving...' : 'Save & Next →'}
        </button>
      </div>
    </div>
  );
}

function Field({ label, placeholder, type, value, onChange }) {
  return (
    <div>
      <label className="block text-[10px] font-bold uppercase tracking-widest text-muted mb-1.5">{label}</label>
      <input type={type} placeholder={placeholder} value={value} onChange={e => onChange(e.target.value)}
        className="w-full px-3 py-2.5 bg-black border border-edge rounded-xl text-cream text-sm font-jetbrains outline-none focus:border-warn/50 transition-colors placeholder:text-muted/25" />
    </div>
  );
}

const primary = 'flex-1 py-3 bg-warn text-black font-bold text-sm rounded-xl hover:bg-warn/90 active:scale-[0.98] transition-all';
const ghost   = 'px-4 py-3 bg-transparent border border-edge text-muted text-sm rounded-xl hover:border-line hover:text-cream transition-all';
