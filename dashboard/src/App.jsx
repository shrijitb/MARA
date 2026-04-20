import { useState, useEffect } from 'react';
import { useArcaData } from './hooks/useArcaData.js';
import LoadingScreen    from './components/LoadingScreen.jsx';
import ConnectionGate   from './components/ConnectionGate.jsx';
import SetupWizard      from './pages/SetupWizard.jsx';
import Dashboard        from './pages/Dashboard.jsx';

function isElectron() {
  return typeof window !== 'undefined' && window.arca?.platform === 'electron';
}

function storedUrl() {
  try { return localStorage.getItem('arca_hypervisor_url'); }
  catch { return null; }
}

// True when the page is served from the same host as the hypervisor (nginx proxy
// on port 3000 → hypervisor:8000), including VPS public IPs and localhost.
async function probeSameOrigin() {
  try {
    const r = await fetch('/api/health', { signal: AbortSignal.timeout(4000) });
    return r.ok;
  } catch {
    return false;
  }
}

export default function App() {
  // Electron always has a URL; stored URL means user already configured it.
  // Otherwise probe same-origin first so VPS / nginx setups skip ConnectionGate.
  const [connected, setConnected] = useState(() => isElectron() || Boolean(storedUrl()));

  useEffect(() => {
    if (connected) return;
    probeSameOrigin().then(ok => {
      if (ok) {
        // Same-origin proxy works — use relative paths, no URL needed.
        localStorage.setItem('arca_hypervisor_url', '');
        setConnected(true);
      }
    });
  }, []);

  const { data, setupStatus, setupComplete, refresh } = useArcaData();

  if (!connected) {
    return (
      <ConnectionGate
        onConnect={url => {
          localStorage.setItem('arca_hypervisor_url', url);
          setConnected(true);
        }}
      />
    );
  }

  if (!setupStatus && !data) return <LoadingScreen />;

  if (!setupComplete) {
    return <SetupWizard onComplete={refresh} setupStatus={setupStatus} />;
  }

  return <Dashboard data={data} />;
}
