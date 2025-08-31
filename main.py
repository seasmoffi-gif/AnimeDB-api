import os
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, Body
from pydantic import BaseModel, Field, HttpUrl

# --------------------------
# Config
# --------------------------
NOCODB_URL = os.getenv("NOCODB_URL", "http://nocodb.example.com")
PROJECT = os.getenv("NOCODB_PROJECT", "anime_db")   # NocoDB project
TABLE = os.getenv("NOCODB_TABLE", "anime")          # NocoDB table
API_TOKEN = os.getenv("NOCODB_TOKEN", "your_token") # NocoDB API token

headers = {"xc-token": API_TOKEN}

app = FastAPI(title="Anime API (NocoDB)")

# --------------------------
# Models
# --------------------------
class StreamLink(BaseModel):
    label: str
    url: HttpUrl

class Episode(BaseModel):
    number: int
    title: Optional[str] = None
    stream_links: Optional[List[StreamLink]] = None

class Season(BaseModel):
    season: int
    episodes: Optional[List[Episode]] = None

class Anime(BaseModel):
    title: str
    type: str
    year: Optional[int] = None
    synopsis: Optional[str] = None
    genres: Optional[str] = None  # comma separated
    poster_url: Optional[HttpUrl] = None
    movie_stream_links: Optional[str] = None  # JSON string
    seasons: Optional[str] = None             # JSON string

# --------------------------
# Helpers
# --------------------------
def nocodb_url(endpoint: str) -> str:
    return f"{NOCODB_URL}/api/v2/tables/{TABLE}/{endpoint}"

async def nocodb_request(method: str, endpoint: str, **kwargs):
    async with httpx.AsyncClient() as client:
        r = await client.request(method, nocodb_url(endpoint), headers=headers, **kwargs)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

# --------------------------
# Routes
# --------------------------

@app.get("/movies")
async def get_movies():
    data = await nocodb_request("GET", "records", params={"where": "(type,eq,movie)"})
    return data.get("list", [])

@app.get("/series")
async def get_series():
    data = await nocodb_request("GET", "records", params={"where": "(type,eq,series)"})
    return data.get("list", [])

@app.get("/latest")
async def get_latest():
    data = await nocodb_request("GET", "records", params={"sort": "-created_at", "limit": 20})
    return data.get("list", [])

@app.get("/getdetails")
async def get_details(id: str = Query(...)):
    data = await nocodb_request("GET", f"records/{id}")
    return data

@app.post("/addanime")
async def add_anime(payload: Anime = Body(...)):
    res = await nocodb_request("POST", "records", json=payload.dict())
    return res

@app.patch("/editanime/{id}")
async def edit_anime(id: str, payload: dict = Body(...)):
    res = await nocodb_request("PATCH", f"records/{id}", json=payload)
    return res
