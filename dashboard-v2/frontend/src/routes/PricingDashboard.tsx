import { TodayAction } from '../features/pricing/today-action/TodayAction';
import { GapPage } from './GapPage';
import { PriceTrend } from '../features/pricing/trend/PriceTrend';


export function PricingDashboard() {

  return (

    <div className="space-y-6">


      {/* Today Action SKU */}
      <section>

        <h2 className="mb-3 text-xl font-bold">
          Today Action SKU
        </h2>

        <TodayAction />

      </section>



      {/* Price Gap Analysis */}
      <section>

        <GapPage />

      </section>



      {/* Price Trend Chart */}
      <section>
       <PriceTrend />
      </section>


    </div>

  );

}
