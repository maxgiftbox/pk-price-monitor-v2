import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';

import { Shell } from './app/Shell';
import { GapPage } from './routes/GapPage';
import { PricingDashboard } from './routes/PricingDashboard';
import { ConsumerVoiceDashboard } from './routes/ConsumerVoiceDashboard';
import { ProductIntelligencePage } from './routes/ProductIntelligencePage';
import { SocialIntelligenceDashboard } from './routes/SocialIntelligenceDashboard';
import { PricingAccessGate } from './routes/PricingAccessGate';
import { isRetryableApiError } from './lib/api';

import './styles.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        if (failureCount >= 1) return false;
        return isRetryableApiError(error);
      },
      retryDelay: 1_000,
      staleTime: 10 * 60_000,
      gcTime: 30 * 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

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
        element: <PricingAccessGate><PricingDashboard /></PricingAccessGate>,
      },
      {
        path: '/pricing/gap',
        element: <PricingAccessGate><GapPage /></PricingAccessGate>,
      },
      {
        path: '/consumer-voice',
        element: <ConsumerVoiceDashboard />,
      },
      {
        path: '/products',
        element: <ProductIntelligencePage />,
      },
      {
        path: '/social-intelligence',
        element: <SocialIntelligenceDashboard />,
      },
    ],
  },
]);


ReactDOM.createRoot(
  document.getElementById('root')!
).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>
);
