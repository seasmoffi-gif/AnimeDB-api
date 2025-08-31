import os
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, Body
from pydantic import BaseModel, Field, HttpUrl

# --------------------------
# Config
# --------------------------
POCKETBASE_URL = os.getenv("POCKETBASE_URL", "http://127.0.0.1:8090")
POCKETBASE_API_KEY = os.getenv("POCKETBASE_API_KEY", "your_api_key")
POCKETBASE_COLLECTION = os.getenv("POCKETBASE_COLLECTION", "anime")

HEADERS = {"Authorization": f"Bearer {POCKETBASE_API_KEY}"}

app = FastAPI(title="Anime API (PocketBase)")

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
# Helper
# --------------------------
async def pb_request(method: str, endpoint: str, **kwargs):
    url = f"{POCKETBASE_URL}/api/collections/{POCKETBASE_COLLECTION}/{endpoint}"
    async with httpx.AsyncClient() as client:
        r = await client.request(method, url, headers=HEADERS, **kwargs)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

# --------------------------
# Routes
# --------------------------
@app.get("/movies")
async def get_movies():
    res = await pb_request("GET", "records", params={"filter": "type = 'movie'"})
    return res.get("items", [])

@app.get("/series")
async def get_series():
    res = await pb_request("GET", "records", params={"filter": "type = 'series'"})
    return res.get("items", [])

@app.get("/latest")
async def get_latest():
    res = await pb_request("GET", "records", params={"sort": "-created"})
    return res.get("items", [])

@app.get("/getdetails")
async def get_details(id: str = Query(...)):
    res = await pb_request("GET", f"records/{id}")
    return res

@app.post("/addanime")
async def add_anime(payload: Anime = Body(...)):
    res = await pb_request("POST", "records", json=payload.model_dump(mode="json"))
    return res

@app.patch("/editanime/{id}")
async def edit_anime(id: str, payload: Anime = Body(...)):
    res = await pb_request("PATCH", f"records/{id}", json=payload.model_dump(mode="json", exclude_unset=True))
    return res

@app.get("/stream")
async def get_stream(id: str = Query(...), season: Optional[int] = None, bolum: Optional[int] = None):
    rec = await pb_request("GET", f"records/{id}")
    if rec["type"] == "movie":
        return {"type": "movie", "links": rec.get("movie_stream_links", [])}
    ep_num = bolum
    if season is None or ep_num is None:
        raise HTTPException(status_code=400, detail="For series, season & episode required")
    # seasons JSON parse
    import json
    seasons = json.loads(rec.get("seasons", "[]"))
    for s in seasons:
        if s.get("season") == season:
            for ep in s.get("episodes", []):
                if ep.get("number") == ep_num:
                    return {"type": "series", "season": season, "episode": ep_num, "links": ep.get("stream_links", [])}
    raise HTTPException(status_code=404, detail="Season/Episode not found")
