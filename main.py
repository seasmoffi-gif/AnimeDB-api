import os
from datetime import datetime
from typing import List, Optional, Literal, Any, Dict

from fastapi import FastAPI, HTTPException, Query, Body, Depends, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl
from bson import ObjectId
import motor.motor_asyncio

# ------------------------------
# Config
# ------------------------------
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "anime_db")
COLLECTION_NAME = "anime"

app = FastAPI(
    title="Anime API",
    version="1.1.0",
    description="Anime API with MongoDB, FastAPI. Supports edit and add links later.",
)

# ------------------------------
# Mongo helpers
# ------------------------------
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

def doc_to_json(d: Dict[str, Any]) -> Dict[str, Any]:
    if not d:
        return d
    d["id"] = str(d.pop("_id"))
    return d

client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
db = client[DB_NAME]
anime_col = db[COLLECTION_NAME]

# ------------------------------
# Models
# ------------------------------
class StreamLink(BaseModel):
    label: str = Field(..., example="1080p")
    url: HttpUrl

class Episode(BaseModel):
    number: int = Field(..., ge=1, example=1)
    title: Optional[str] = None
    stream_links: Optional[List[StreamLink]] = None   # not required

class Season(BaseModel):
    season: int = Field(..., ge=1, example=1)
    episodes: Optional[List[Episode]] = None          # not required

class AnimeBase(BaseModel):
    title: str
    alt_titles: List[str] = Field(default_factory=list)
    type: Literal["movie", "series"]
    year: Optional[int] = None
    synopsis: Optional[str] = None
    genres: List[str] = Field(default_factory=list)
    poster_url: Optional[HttpUrl] = None

class AnimeCreate(AnimeBase):
    movie_stream_links: Optional[List[StreamLink]] = None
    seasons: Optional[List[Season]] = None

class AnimeOut(AnimeBase):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="id")
    added_at: datetime
    movie_stream_links: Optional[List[StreamLink]] = None
    seasons: Optional[List[Season]] = None

    class Config:
        json_encoders = {ObjectId: str}
        allow_population_by_field_name = True

class AnimeUpdate(BaseModel):
    title: Optional[str] = None
    alt_titles: Optional[List[str]] = None
    type: Optional[Literal["movie", "series"]] = None
    year: Optional[int] = None
    synopsis: Optional[str] = None
    genres: Optional[List[str]] = None
    poster_url: Optional[HttpUrl] = None
    movie_stream_links: Optional[List[StreamLink]] = None
    seasons: Optional[List[Season]] = None

class AddLinkPayload(BaseModel):
    season: Optional[int] = None
    episode: Optional[int] = None
    links: List[StreamLink]

# ------------------------------
# Startup: indexes
# ------------------------------
@app.on_event("startup")
async def setup_indexes():
    await anime_col.create_index([("type", 1)])
    await anime_col.create_index([("added_at", -1)])
    await anime_col.create_index([("title", "text"), ("alt_titles", "text")])

# ------------------------------
# Dependencies
# ------------------------------
def pagination(limit: int = Query(24, ge=1, le=100), skip: int = Query(0, ge=0)):
    return {"limit": limit, "skip": skip}

# ------------------------------
# Routes
# ------------------------------
@app.get("/health")
async def health():
    return {"ok": True, "time": datetime.utcnow().isoformat()}

@app.get("/movies", response_model=List[AnimeOut])
async def get_movies(p: dict = Depends(pagination)):
    cursor = anime_col.find({"type": "movie"}).sort("added_at", -1).skip(p["skip"]).limit(p["limit"])
    return [doc_to_json(d) async for d in cursor]

@app.get("/series", response_model=List[AnimeOut])
async def get_series(p: dict = Depends(pagination)):
    cursor = anime_col.find({"type": "series"}).sort("added_at", -1).skip(p["skip"]).limit(p["limit"])
    return [doc_to_json(d) async for d in cursor]

@app.get("/latest", response_model=List[AnimeOut])
async def get_latest(p: dict = Depends(pagination)):
    cursor = anime_col.find({}).sort("added_at", -1).skip(p["skip"]).limit(p["limit"])
    return [doc_to_json(d) async for d in cursor]

@app.get("/getdetails", response_model=AnimeOut)
async def get_details(id: str = Query(...)):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid id")
    doc = await anime_col.find_one({"_id": ObjectId(id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Anime not found")
    return doc_to_json(doc)

@app.get("/stream")
async def get_stream(
    id: str = Query(...),
    season: Optional[int] = Query(None),
    bolum: Optional[int] = Query(None),
    episode: Optional[int] = Query(None),
):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid id")

    doc = await anime_col.find_one({"_id": ObjectId(id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Anime not found")

    if doc.get("type") == "movie":
        return {"type": "movie", "links": doc.get("movie_stream_links", [])}

    ep_num = episode or bolum
    if season is None or ep_num is None:
        raise HTTPException(status_code=400, detail="For series, season & episode required")

    for s in doc.get("seasons", []):
        if s.get("season") == season:
            for ep in s.get("episodes", []):
                if ep.get("number") == ep_num:
                    return {"type": "series", "season": season, "episode": ep_num, "links": ep.get("stream_links", [])}
    raise HTTPException(status_code=404, detail="Season/Episode not found")

@app.post("/addanime", response_model=AnimeOut, status_code=201)
async def add_anime(payload: AnimeCreate = Body(...)):
    data = payload.dict()
    data["added_at"] = datetime.utcnow()
    res = await anime_col.insert_one(data)
    saved = await anime_col.find_one({"_id": res.inserted_id})
    return doc_to_json(saved)

@app.patch("/editanime/{id}", response_model=AnimeOut)
async def edit_anime(id: str = Path(...), payload: AnimeUpdate = Body(...)):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid id")

    update_data = {k: v for k, v in payload.dict(exclude_unset=True).items()}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = await anime_col.update_one({"_id": ObjectId(id)}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Anime not found")

    doc = await anime_col.find_one({"_id": ObjectId(id)})
    return doc_to_json(doc)

@app.patch("/addlink/{id}", response_model=AnimeOut)
async def add_link(id: str, payload: AddLinkPayload):
    """Append links to movie or series episode without replacing full seasons array"""
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid id")

    doc = await anime_col.find_one({"_id": ObjectId(id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Anime not found")

    if doc["type"] == "movie":
        # Just append to movie_stream_links
        await anime_col.update_one(
            {"_id": ObjectId(id)},
            {"$push": {"movie_stream_links": {"$each": [l.dict() for l in payload.links]}}}
        )
    else:
        if payload.season is None or payload.episode is None:
            raise HTTPException(status_code=400, detail="Season & episode required for series")
        # Find and update specific episode
        await anime_col.update_one(
            {
                "_id": ObjectId(id),
                "seasons.season": payload.season,
                "seasons.episodes.number": payload.episode
            },
            {
                "$push": {"seasons.$[].episodes.$[ep].stream_links": {"$each": [l.dict() for l in payload.links]}}
            },
            array_filters=[{"ep.number": payload.episode}]
        )

    updated = await anime_col.find_one({"_id": ObjectId(id)})
    return doc_to_json(updated)

# ------------------------------
# Global 404 handler
# ------------------------------
@app.exception_handler(404)
async def not_found_handler(_, exc: HTTPException):
    return JSONResponse(status_code=404, content={"detail": exc.detail or "Not found"})
