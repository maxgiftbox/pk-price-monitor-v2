import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';

import { Shell } from './app/Shell';
import { GapPage } from './routes/GapPage';
import { PricingDashboard } from './routes/PricingDashboard';
import { ComingSoon } from './routes/ComingSoon';
import { ConsumerVoiceDashboard } from './routes/ConsumerVoiceDashboard';

import './styles.css';


const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      {
        path: '/',
        element: <Navigate to="/pricing" replace />,
      },
      {
        path: '/pricing',
        element: <PricingDashboard />,
      },
      {
        path: '/pricing/gap',
        element: <GapPage />,
      },
      {
        path: '/consumer-voice',
        element: <ConsumerVoiceDashboard />,
      },
      {
        path: '/products',
        element: <ComingSoon />,
      },
    ],
  },
]);


ReactDOM.createRoot(
  document.getElementById('root')!
).render(
  <React.StrictMode>
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>
);
