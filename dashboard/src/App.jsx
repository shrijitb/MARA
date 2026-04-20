import { useState } from 'react';
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

export default function App() {
  // Electron always has a URL (defaults to localhost:8000 via electron-store).
  // Web / Capacitor need the user to enter it once; we persist it in localStorage.
  const [connected, setConnected] = useState(() => isElectron() || Boolean(storedUrl()));

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
