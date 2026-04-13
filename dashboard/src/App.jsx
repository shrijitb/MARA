import { useArkaData } from './hooks/useArkaData.js';
import LoadingScreen from './components/LoadingScreen.jsx';
import SetupWizard from './pages/SetupWizard.jsx';
import Dashboard from './pages/Dashboard.jsx';

export default function App() {
  const { data, setupStatus, setupComplete, refresh } = useArkaData();

  // Show loader until we get at least the setup status
  if (!setupStatus && !data) return <LoadingScreen />;

  if (!setupComplete) {
    return <SetupWizard onComplete={refresh} setupStatus={setupStatus} />;
  }

  return <Dashboard data={data} />;
}
