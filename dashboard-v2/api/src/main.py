import os
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.data_sources.google_sheets import DataSourceUnavailable, GoogleSheetsRepository
from src.services.pricing import filters, gap

app = FastAPI(title="Mob Price Monitor V2 API", docs_url=None, redoc_url=None)
origins=[x.strip() for x in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET"], allow_headers=["Accept","Content-Type"])
app.state.repository=GoogleSheetsRepository()

@app.exception_handler(DataSourceUnavailable)
def unavailable(_request: Request, _exc: DataSourceUnavailable):
    return JSONResponse(status_code=503, content={"error":{"code":"DATA_SOURCE_UNAVAILABLE","message":"Pricing data is temporarily unavailable."}})

@app.get("/api/health")
def health(): return {"status":"ok"}

@app.get("/api/pricing/filters")
def pricing_filters(country: list[str]=Query([]), brand: list[str]=Query([]), sku: list[str]=Query([]), memory: list[str]=Query([]), dateFrom: str|None=None, dateTo: str|None=None):
    return filters(app.state.repository.get(), country, brand, sku, memory, dateFrom, dateTo)

@app.get("/api/pricing/gap")
def pricing_gap(country:list[str]=Query([]),brand:list[str]=Query([]),sku:list[str]=Query([]),memory:list[str]=Query([]),competitor:list[str]=Query([]),alert:list[str]=Query([]),dateFrom:str|None=None,dateTo:str|None=None,page:int=Query(1,ge=1),pageSize:int=Query(100,ge=1,le=250),sort:str="date",direction:str=Query("desc",pattern="^(asc|desc)$")):
    return gap(app.state.repository.get(), {"country":country,"brand":brand,"sku":sku,"memory":memory,"competitor":competitor,"alert":alert,"date_from":dateFrom,"date_to":dateTo,"page":page,"page_size":pageSize,"sort":sort,"direction":direction})
