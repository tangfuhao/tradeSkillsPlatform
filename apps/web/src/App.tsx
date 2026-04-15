import { Suspense, lazy } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import ProductLayout from './layout/ProductLayout';
import ProductHomePage from './pages/ProductHomePage';
import ReplayHubPage from './pages/ReplayHubPage';
import ReplayPage from './pages/ReplayPage';
import SignalsPage from './pages/SignalsPage';
import StrategiesPage from './pages/StrategiesPage';
import StrategyProfilePage from './pages/StrategyProfilePage';

const ConsolePage = lazy(() => import('./console/ConsolePage'));

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<ProductLayout />}>
          <Route path="/" element={<ProductHomePage />} />
          <Route path="/replays" element={<ReplayHubPage />} />
          <Route path="/replays/:runId" element={<ReplayPage />} />
          <Route path="/signals" element={<SignalsPage />} />
          <Route path="/strategies" element={<StrategiesPage />} />
          <Route path="/strategies/:skillId" element={<StrategyProfilePage />} />
        </Route>
        <Route
          path="/console"
          element={
            <Suspense fallback={null}>
              <ConsolePage />
            </Suspense>
          }
        />
        <Route path="*" element={<Navigate replace to="/" />} />
      </Routes>
    </BrowserRouter>
  );
}
