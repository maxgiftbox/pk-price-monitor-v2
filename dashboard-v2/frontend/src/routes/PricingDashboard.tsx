import { useQuery } from '@tanstack/react-query';

import { api } from '../lib/api';
import { TodayAction } from '../features/pricing/today-action/TodayAction';
import { GapPage } from './GapPage';
import { PriceTrend } from '../features/pricing/trend/PriceTrend';


export function PricingDashboard() {

  const dashboard = useQuery({
    queryKey: ['pricing-dashboard'],
    queryFn: api.dashboard,
  });

  if (dashboard.isLoading) {
    return <div className="rounded-xl border bg-white p-12 text-center text-slate-500">Loading pricing dashboard…</div>;
  }

  if (dashboard.isError && !dashboard.data) {
    return <div className="rounded-xl border bg-white p-12 text-center"><h2 className="font-bold text-red-700">Pricing dashboard unavailable</h2><button className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white" onClick={() => dashboard.refetch()}>Retry</button></div>;
  }

  return (

    <div className="space-y-6">


      {/* Today Action SKU */}
      <section>

        <h2 className="mb-3 text-xl font-bold">
          Today Action SKU
        </h2>

        <TodayAction initialData={dashboard.data?.todayAction} />

      </section>



      {/* Price Gap Analysis */}
      <section>

        <GapPage initialFilters={dashboard.data?.filters} initialGap={dashboard.data?.gap} />

      </section>



      {/* Price Trend Chart */}
      <section>
       <PriceTrend initialData={dashboard.data?.trend} />
      </section>


    </div>

  );

}
