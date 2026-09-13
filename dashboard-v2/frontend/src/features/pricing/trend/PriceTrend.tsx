import {
  useEffect,
  useMemo,
  useState
} from "react";

import {
  useQuery
} from "@tanstack/react-query";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend
} from "recharts";

import {
  api
} from "../../../lib/api";



export function PriceTrend() {

const [country,setCountry] = useState("pk");
const [brand,setBrand] = useState("samsung");
const [sku,setSku] = useState("");
const [memory,setMemory] = useState("");


const getDefaultDateRange = () => {

  const today = new Date();

  const end =
    today.toISOString().slice(0,10);


  const startDate =
    new Date();

  startDate.setDate(
    today.getDate()-7
  );


  const start =
    startDate.toISOString().slice(0,10);


  return {
    start,
    end
  };

};


const defaultDateRange =
  getDefaultDateRange();


const [dateFrom,setDateFrom] =
  useState(defaultDateRange.start);


const [dateTo,setDateTo] =
  useState(defaultDateRange.end);

  const [
    selectedPlatforms,
    setSelectedPlatforms
  ] = useState<string[]>([]);


  const trend = useQuery({
    queryKey:[
      "price-trend"
    ],
    queryFn:()=>api.trend(new URLSearchParams())
  });


  const rows = trend.data?.rows ?? [];
  console.log("Trend API response:", trend.data);
  console.log("Trend full object:", trend);

  console.log("Trend rows:", rows.length);


  /*
   * Platform Configuration
   */

  const platformStyle:any = {


    daraz:{
      label:"Daraz",
      color:"#2563eb",
      dash:"0"
    },


    priceoye:{
      label:"Priceoye",
      color:"#16a34a",
      dash:"6 4"
    },


    pickaboo:{
      label:"Pickaboo",
      color:"#f97316",
      dash:"3 3"
    }


  };





  /*
   * Country Options
   */


  const countries = useMemo(()=>{


    return [
      ...new Set(
        rows
        .map((r:any)=>r.country)
        .filter(Boolean)
      )
    ];


  },[rows]);





  /*
   * Brand Options
   * Country dependent
   */


  const brandRows = useMemo(()=>{


    return rows.filter((r:any)=>{


      if(
        country &&
        r.country!==country
      ){
        return false;
      }


      return true;


    });


  },[
    rows,
    country
  ]);





  const brands = useMemo(()=>{


    return [
      ...new Set(
        brandRows
        .map((r:any)=>r.brand)
        .filter(Boolean)
      )
    ];


  },[
    brandRows
  ]);





  /*
   * SKU Options
   * Country + Brand dependent
   */


  const skuRows = useMemo(()=>{


    return rows.filter((r:any)=>{


      if(
        country &&
        r.country!==country
      ){
        return false;
      }


      if(
        brand &&
        r.brand!==brand
      ){
        return false;
      }


      return true;


    });


  },[
    rows,
    country,
    brand
  ]);





  const skus = useMemo(()=>{


    return [
      ...new Set(
        skuRows
        .map((r:any)=>r.sku)
        .filter(Boolean)
      )
    ];


  },[
    skuRows
  ]);





  /*
   * Memory Options
   * Country + Brand + SKU dependent
   */


  const memoryRows = useMemo(()=>{


    return rows.filter((r:any)=>{


      if(
        country &&
        r.country!==country
      ){
        return false;
      }


      if(
        brand &&
        r.brand!==brand
      ){
        return false;
      }


      if(
        sku &&
        r.sku!==sku
      ){
        return false;
      }


      return true;


    });


  },[
    rows,
    country,
    brand,
    sku
  ]);





  const memories = useMemo(()=>{


    return [
      ...new Set(
        memoryRows
        .map((r:any)=>r.memory)
        .filter(Boolean)
      )
    ];


  },[
    memoryRows
  ]);





  /*
   * Reset dependent dropdown
   */


  useEffect(()=>{

    setBrand("");
    setSku("");
    setMemory("");

  },[
    country
  ]);





  useEffect(()=>{

    setSku("");
    setMemory("");

  },[
    brand
  ]);





  useEffect(()=>{

    setMemory("");

  },[
    sku
  ]);




  /*
   * Init Date Range
   */



  /*
   * Main Filter Data
   */


  const filteredRows = useMemo(()=>{


    return rows.filter((r:any)=>{


      if(
        country &&
        r.country!==country
      ){

        return false;

      }



      if(
        brand &&
        r.brand!==brand
      ){

        return false;

      }



      if(
        sku &&
        r.sku!==sku
      ){

        return false;

      }




      if(
        memory &&
        r.memory!==memory
      ){

        return false;

      }





      if(
        dateFrom &&
        r.date < dateFrom
      ){

        return false;

      }





      if(
        dateTo &&
        r.date > dateTo
      ){

        return false;

      }



      return true;


    });


  },[
    rows,
    country,
    brand,
    sku,
    memory,
    dateFrom,
    dateTo
  ]);







  /*
   * Available Platforms
   */


  const availablePlatforms = useMemo(()=>{


    return [
      ...new Set(

        filteredRows
        .map((r:any)=>r.platform)
        .filter(Boolean)

      )
    ];


  },[
    filteredRows
  ]);







  /*
   * Sync Platform Selection
   */


  useEffect(()=>{


    setSelectedPlatforms(
      availablePlatforms
    );


  },[
    availablePlatforms.join(",")
  ]);







  const togglePlatform=(platform:string)=>{


    setSelectedPlatforms(prev=>{


      if(
        prev.includes(platform)
      ){

        return prev.filter(
          x=>x!==platform
        );

      }



      return [
        ...prev,
        platform
      ];


    });


  };







  /*
   * Chart Data
   */


  const chartData = useMemo(()=>{


    const result:any={};



    filteredRows.forEach((row:any)=>{


      if(
        !selectedPlatforms.includes(
          row.platform
        )
      ){

        return;

      }




      if(
        !result[row.date]
      ){


        result[row.date]={

          date:row.date

        };


      }




      result[row.date][row.platform]
        =
        row.price;



    });





    return Object.values(result)
      .sort(
        (a:any,b:any)=>
        a.date.localeCompare(
          b.date
        )
      );



  },[
    filteredRows,
    selectedPlatforms
  ]);








  if(trend.isLoading){


    return (

      <div
      className="
      rounded-xl
      border
      bg-white
      p-6
      "
      >

        Loading...

      </div>

    );


  }





  return (

<section
className="
rounded-xl
border
bg-white
p-6
"
>


<h3
className="
mb-4
font-bold
text-lg
"
>
Price Trend Chart
</h3>








<div
className="
grid
grid-cols-6
gap-4
mb-6
"
>






<div>

<label className="text-sm text-slate-500">
Country
</label>


<select

className="
mt-1
w-full
rounded-lg
border
p-2
"

value={country}

onChange={(e)=>
setCountry(
e.target.value
)
}

>


<option value="">
All
</option>


{
countries.map((x:any)=>(

<option
key={x}
value={x}
>

{x.toUpperCase()}

</option>

))
}


</select>


</div>








<div>

<label className="text-sm text-slate-500">
Brand
</label>


<select

className="
mt-1
w-full
rounded-lg
border
p-2
"

value={brand}

onChange={(e)=>
setBrand(
e.target.value
)
}

>


<option value="">
All
</option>


{
brands.map((x:any)=>(

<option
key={x}
value={x}
>

{x}

</option>

))
}


</select>


</div>








<div>

<label className="text-sm text-slate-500">
SKU
</label>


<select

className="
mt-1
w-full
rounded-lg
border
p-2
"

value={sku}

onChange={(e)=>
setSku(
e.target.value
)
}

>


<option value="">
All
</option>


{
skus.map((x:any)=>(

<option
key={x}
value={x}
>

{x}

</option>

))
}


</select>


</div>








<div>

<label className="text-sm text-slate-500">
Memory
</label>


<select

className="
mt-1
w-full
rounded-lg
border
p-2
"

value={memory}

onChange={(e)=>
setMemory(
e.target.value
)
}

>


<option value="">
All
</option>


{
memories.map((x:any)=>(

<option
key={x}
value={x}
>

{x}

</option>

))
}


</select>


</div>








<div
className="
col-span-2
"
>

<label className="text-sm text-slate-500">
Date Range
</label>



<div
className="
flex
gap-2
"
>


<input

type="date"

className="
mt-1
w-full
min-w-0
rounded-lg
border
p-2
"

value={dateFrom}

onChange={(e)=>
setDateFrom(
e.target.value
)
}

/>



<input

type="date"

className="
mt-1
w-full
min-w-0
rounded-lg
border
p-2
"

value={dateTo}

onChange={(e)=>
setDateTo(
e.target.value
)
}

/>


</div>


</div>







</div>








{/* Platform Filter */}


<div
className="
flex
gap-3
flex-wrap
mb-6
"
>


{
availablePlatforms.map((p:any)=>{


const active =
selectedPlatforms.includes(p);


const style =
platformStyle[p] || {

label:p,

color:"#64748b"

};



return (


<button

key={p}

onClick={()=>
togglePlatform(p)
}

className="
px-5
py-2
rounded-lg
border
text-sm
font-medium
transition-all
"

style={{

backgroundColor:
active
?
style.color
:
"white",


borderColor:
style.color,


color:
active
?
"white"
:
style.color

}}

>


{
active
?
"✓ "
:
""
}


{style.label}


</button>


)


})

}


</div>








<div

className="
h-[400px]
w-full
"

>


<ResponsiveContainer
width="100%"
height="100%"
>


<LineChart
data={chartData}
>


<CartesianGrid
strokeDasharray="3 3"
/>





<XAxis

dataKey="date"

tickFormatter={(v)=>{


const d =
new Date(v);


return `${d.toLocaleString(
"en-US",
{
month:"short"
}
)} ${d.getDate()}`;


}}

/>







<YAxis

tickFormatter={(value)=>{


if(
value>=1000
){

return `${Math.round(
value/1000
)}K`;

}


return value;


}}

/>







<Tooltip


formatter={
(value:any,name:any)=>[

`PKR ${Number(value).toLocaleString()}`,

platformStyle[name]?.label || name

]

}


/>






<Legend

verticalAlign="top"

align="right"

/>







{

availablePlatforms.map((p:any)=>{


const style =
platformStyle[p] || {

label:p,

color:"#64748b",

dash:"0"

};



return (

<Line

key={p}

type="monotone"

dataKey={p}

stroke={
style.color
}

strokeWidth={2}

strokeDasharray={
style.dash
}

dot={{

r:4,

strokeWidth:2

}}

activeDot={{

r:6

}}


/>

)


})

}





</LineChart>


</ResponsiveContainer>


</div>







</section>


  );


}
