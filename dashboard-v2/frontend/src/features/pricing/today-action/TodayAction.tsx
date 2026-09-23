import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../../lib/api";


type GapRow = {
  date?: string;
  country?: string;
  brand?: string;
  model?: string;
  memory?: string;

  drz_price?: number | null;
  lc_price?: number | null;
  gap_pct?: number | null;

  alert?: "Red" | "Orange";
};


const PAGE_SIZE = 8;



function formatPrice(
  value?: number | null
) {

  if (
    value === undefined ||
    value === null
  ) {
    return "-";
  }

  return value.toLocaleString();

}



function GapBadge({

  value

}: {

  value?: number | null;

}) {


  if (
    value === undefined ||
    value === null
  ) {

    return (
      <span>
        -
      </span>
    );

  }


  const pct = value * 100;


  return (

    <span

      className={

        pct >= 3

        ?

        `
        inline-flex
        rounded-full
        bg-red-100
        px-2
        py-1
        text-xs
        font-semibold
        text-red-700
        `

        :

        `
        inline-flex
        rounded-full
        bg-orange-100
        px-2
        py-1
        text-xs
        font-semibold
        text-orange-700
        `

      }

    >

      {pct.toFixed(2)}%

    </span>

  );

}




export function TodayAction(){


  const [
    country,
    setCountry
  ] = useState("PK");



  const [
    redPage,
    setRedPage
  ] = useState(1);



  const [
    orangePage,
    setOrangePage
  ] = useState(1);




  const {

    data,
    isLoading,
    isError,
    refetch

  } = useQuery({


    queryKey:[

      "pricing-gap",

      country

    ],



    queryFn:()=>{


      const params =
        new URLSearchParams();



      params.set(
        "page",
        "1"
      );



      params.set(
        "pageSize",
        "500"
      );

      params.set(
        "windowDays",
        "1"
      );



      if(
        country !== "All"
      ){

        params.set(
          "country",
          country.toLowerCase()
        );

      }


      return api.gap(params);


    }


  });





  const {

    rows,

    latestDate

  } = useMemo(()=>{


    if(!data){

      return {

        rows:[],

        latestDate:"-"

      };

    }



    const source =
      data.rows ?? [];



    if(
      source.length===0
    ){

      return {

        rows:[],

        latestDate:"-"

      };

    }




    const latest =

      source

      .map(
        (r:any)=>r.date
      )

      .sort()

      .reverse()[0];





    const filtered =

      source

      .filter(

        (r:any)=>
          r.date === latest

      )

      .filter(

        (r:any)=>

          r.darazPrice &&
          r.darazPrice > 0

      )

      .filter(

        (r:any)=>

          r.alert === "Red"

          ||

          (
            r.alert === "Orange"

            &&

            r.competitorPrice

            &&

            r.competitorPrice > 0
          )

      )

      .map(

        (r:any)=>(

          {

            date:
              r.date ?? "-",


            country:
              r.country ?? "-",


            brand:
              r.brand ?? "-",


            model:

              r.model ??
              r.sku ??
              "-",



            memory:

              r.memory ??
              "-",



            drz_price:

              r.darazPrice ??
              null,



            lc_price:

              r.competitorPrice ??
              null,



            gap_pct:

              r.gapPct ??
              null,



            alert:

              r.alert ??

              "Orange"


          }

        )

      );



    return {

      rows:filtered,

      latestDate:latest

    };



  },[data]);



const redRows = useMemo(
  () =>
    rows
      .filter(
        (r: GapRow) =>
          r.alert === "Red"
      )
      .sort(
        (a: GapRow, b: GapRow) =>
          (b.gap_pct ?? 0) -
          (a.gap_pct ?? 0)
      ),
  [rows]
);


const orangeRows = useMemo(
  () =>
    rows
      .filter(
        (r: GapRow) =>
          r.alert === "Orange"
      )
      .sort(
        (a: GapRow, b: GapRow) =>
          (b.gap_pct ?? 0) -
          (a.gap_pct ?? 0)
      ),
  [rows]
);




  const redPageRows = useMemo(

    ()=>redRows.slice(

      (redPage-1)*PAGE_SIZE,

      redPage*PAGE_SIZE

    ),

    [
      redRows,
      redPage
    ]

  );




  const orangePageRows = useMemo(

    ()=>orangeRows.slice(

      (orangePage-1)*PAGE_SIZE,

      orangePage*PAGE_SIZE

    ),

    [
      orangeRows,
      orangePage
    ]

  );

  if (isLoading) {
    return <div className="rounded-xl border bg-white p-6 text-slate-500">Loading today action SKUs…</div>;
  }

  if (isError) {
    return (
      <div className="rounded-xl border bg-white p-6 text-center">
        <h3 className="font-bold text-red-700">Today action data unavailable</h3>
        <button
          className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white"
          onClick={() => refetch()}
        >
          Retry
        </button>
      </div>
    );
  }
  return (

    <div>


      {/* Venture / Country Selector */}

      <div className="
        mb-4
        flex
        gap-4
      ">


        {[
          "PK",
          "BD",
          "NP",
          "All"
        ].map((item)=>(

          <button

            key={item}

            onClick={()=>{

              setCountry(item);

              setRedPage(1);

              setOrangePage(1);

            }}

            className={`
              rounded-xl
              border
              px-6
              py-3
              text-sm
              font-semibold
              ${
                country===item
                ?
                "bg-blue-50 border-blue-600 text-blue-700"
                :
                "bg-white text-slate-600"
              }
            `}

          >

            {item}

          </button>

        ))}


      </div>




      <div className="
        grid
        grid-cols-2
        gap-6
        items-start
      ">


        {/* ================= RED ================= */}


        <div>


          <div className="
            mb-3
            flex
            justify-between
            items-center
          ">


            <h2 className="
              text-xl
              font-bold
              text-slate-900
            ">

              🔴 Red SKU

            </h2>



            <span className="
              rounded-full
              bg-red-50
              px-4
              py-1
              text-sm
              font-semibold
              text-red-600
            ">

              {redRows.length} SKU

            </span>


          </div>





          <div className="
            rounded-xl
            border
            overflow-hidden
          ">


            <div className="
              overflow-x-auto
              max-h-[620px]
            ">



              <table className="
                w-full
                text-sm
              ">


                <thead className="
                  sticky
                  top-0
                  z-20
                  bg-red-50
                  shadow-sm
                ">


                  <tr>


                    <th className="
                      sticky
                      left-0
                      z-30
                      bg-red-50
                      px-4
                      py-3
                      text-left
                      w-[220px]
                      min-w-[220px]
                    ">

                      MODEL

                    </th>




                    <th className="
                      sticky
                      left-[220px]
                      z-30
                      bg-red-50
                      px-3
                      py-3
                      text-left
                      w-[80px]
                      min-w-[80px]
                    ">

                      MEMORY

                    </th>




                    <th className="
                      px-4
                      py-3
                      text-right
                    ">

                      DRZ PRICE

                    </th>




                    <th className="
                      px-4
                      py-3
                      text-right
                    ">

                      LC PRICE

                    </th>




                    <th className="
                      px-4
                      py-3
                      text-right
                    ">

                      GAP %

                    </th>



                  </tr>


                </thead>





                <tbody>


                  {redPageRows.map(

                    (row,index)=>(


                      <tr

                        key={index}

                        className="
                          border-t
                          hover:bg-slate-50
                        "

                      >




                        <td className="
                          sticky
                          left-0
                          z-10
                          bg-white
                          px-4
                          py-2.5
                          font-semibold
                          w-[220px]
                          min-w-[220px]
                        ">


                          {row.model}


                        </td>






                        <td className="
                          sticky
                          left-[220px]
                          z-10
                          bg-white
                          px-3
                          py-2.5
                        ">


                          {row.memory}


                        </td>






                        <td className="
                          px-4
                          py-2.5
                          text-right
                          font-semibold
                          whitespace-nowrap
                        ">


                          {formatPrice(row.drz_price)}


                        </td>






                        <td className="
                          px-4
                          py-2.5
                          text-right
                          whitespace-nowrap
                        ">


                          {formatPrice(row.lc_price)}


                        </td>






                        <td className="
                          px-4
                          py-2.5
                          text-right
                        ">


                          <GapBadge

                            value={row.gap_pct}

                          />


                        </td>



                      </tr>


                    )

                  )}



                </tbody>



              </table>



            </div>


          </div>





          <div className="
            mt-3
            flex
            justify-center
            gap-3
            text-sm
          ">


            <button

              disabled={redPage===1}

              onClick={()=>setRedPage(
                p=>p-1
              )}

              className="
                rounded
                border
                px-3
                py-1
              "

            >

              Prev

            </button>





            <span className="
              px-3
              py-1
            ">

              {redPage}

            </span>





            <button


              disabled={
                redPage * PAGE_SIZE >= redRows.length
              }


              onClick={()=>setRedPage(
                p=>p+1
              )}


              className="
                rounded
                border
                px-3
                py-1
              "

            >

              Next

            </button>



          </div>



        </div>

        {/* ================= ORANGE ================= */}


        <div>


          <div className="
            mb-3
            flex
            justify-between
            items-center
          ">


            <h2 className="
              text-xl
              font-bold
              text-slate-900
            ">


              🟠 Orange SKU


            </h2>




            <span className="
              rounded-full
              bg-orange-50
              px-4
              py-1
              text-sm
              font-semibold
              text-orange-600
            ">


              {orangeRows.length} SKU


            </span>



          </div>





          <div className="
            rounded-xl
            border
            overflow-hidden
          ">



            <div className="
              overflow-x-auto
              max-h-[620px]
            ">



              <table className="
                w-full
                text-sm
              ">



                <thead className="
                  sticky
                  top-0
                  z-20
                  bg-orange-50
                  shadow-sm
                ">



                  <tr>


                    <th className="
                      sticky
                      left-0
                      z-30
                      bg-orange-50
                      px-4
                      py-3
                      text-left
                      w-[220px]
                      min-w-[220px]
                    ">

                      MODEL

                    </th>




                    <th className="
                      sticky
                      left-[220px]
                      z-30
                      bg-orange-50
                      px-3
                      py-3
                      text-left
                      w-[80px]
                      min-w-[80px]
                    ">


                      MEMORY


                    </th>





                    <th className="
                      px-4
                      py-3
                      text-right
                    ">


                      DRZ PRICE


                    </th>





                    <th className="
                      px-4
                      py-3
                      text-right
                    ">


                      LC PRICE


                    </th>





                    <th className="
                      px-4
                      py-3
                      text-right
                    ">


                      GAP %


                    </th>



                  </tr>


                </thead>







                <tbody>



                  {orangePageRows.map(

                    (row,index)=>(


                      <tr

                        key={index}

                        className="
                          border-t
                          hover:bg-slate-50
                        "

                      >




                        <td className="
                          sticky
                          left-0
                          z-10
                          bg-white
                          px-4
                          py-2.5
                          font-semibold
                          w-[220px]
                          min-w-[220px]
                        ">



                          {row.model}



                        </td>







                        <td className="
                          sticky
                          left-[220px]
                          z-10
                          bg-white
                          px-3
                          py-2.5
                        ">



                          {row.memory}



                        </td>







                        <td className="
                          px-4
                          py-2.5
                          text-right
                          font-semibold
                          whitespace-nowrap
                        ">



                          {formatPrice(row.drz_price)}



                        </td>







                        <td className="
                          px-4
                          py-2.5
                          text-right
                          whitespace-nowrap
                        ">



                          {formatPrice(row.lc_price)}



                        </td>







                        <td className="
                          px-4
                          py-2.5
                          text-right
                        ">



                          <GapBadge

                            value={row.gap_pct}

                          />



                        </td>






                      </tr>


                    )

                  )}



                </tbody>



              </table>



            </div>



          </div>






          {/* ORANGE PAGINATION */}



          <div className="
            mt-3
            flex
            justify-center
            gap-3
            text-sm
          ">



            <button


              disabled={orangePage===1}


              onClick={()=>setOrangePage(
                p=>p-1
              )}


              className="
                rounded
                border
                px-3
                py-1
              "


            >


              Prev


            </button>






            <span className="
              px-3
              py-1
            ">


              {orangePage}


            </span>







            <button



              disabled={
                orangePage * PAGE_SIZE >= orangeRows.length
              }



              onClick={()=>setOrangePage(
                p=>p+1
              )}



              className="
                rounded
                border
                px-3
                py-1
              "



            >


              Next


            </button>




          </div>




        </div>



      </div>


    </div>


  );


}
