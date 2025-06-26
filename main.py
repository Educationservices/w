from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional, List
from fastapi.responses import JSONResponse
from pymongo import MongoClient
from bson.objectid import ObjectId
import random
import string
import os

from dotenv import load_dotenv
load_dotenv()

app = FastAPI()

# MongoDB connection
MONGODB_URI = os.getenv("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client["game_db"]
users_collection = db["users"]
games_collection = db["games"]
pokemon_collection = db["pokemons"]

# Pokémon list from image
POKEMON_NAMES = [
    "Blazuma", "Cryospike", "Thornzilla", "Grimjaw",
    "Spherex", "Voltrune", "Aquabeast"
]

# Models
class SignupModel(BaseModel):
    email: str
    username: str
    password: str
    gender: str

class StartGameModel(BaseModel):
    user1: str
    user2: str

class EndGameModel(BaseModel):
    code: str
    show_pokemon: Optional[bool] = False

class PokemonActionModel(BaseModel):
    username: str
    pokemon: str

class PokemonDataModel(BaseModel):
    username: str
    pokemon: str
    key: str
    value: int

# Utilities
def generate_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# Routes
@app.post("/signup")
async def signup(data: SignupModel):
    if users_collection.find_one({"email": data.email}):
        return JSONResponse({"error": "Email already exists"}, status_code=400)
    if users_collection.find_one({"username": data.username}):
        return JSONResponse({"error": "Username already exists"}, status_code=400)
    users_collection.insert_one(data.dict())
    return {"message": "Signup successful"}

@app.get("/allusers/{username}")
async def check_user(username: str):
    exists = users_collection.find_one({"username": username})
    return {"exists": bool(exists)}

@app.post("/start_game")
async def start_game(data: StartGameModel):
    code = generate_code()
    games_collection.insert_one({
        "code": code,
        "players": [data.user1, data.user2],
        "status": "active"
    })
    return {"code": code}

@app.post("/end_game")
async def end_game(data: EndGameModel):
    game = games_collection.find_one({"code": data.code})
    if not game:
        return JSONResponse({"error": "Game not found"}, status_code=404)
    games_collection.update_one({"code": data.code}, {"$set": {"status": "ended"}})
    if data.show_pokemon:
        pokes = {}
        for user in game["players"]:
            entry = pokemon_collection.find_one({"username": user})
            pokes[user] = entry["pokemons"] if entry else []
        return {"message": "Game ended", "pokemons": pokes}
    return {"message": "Game ended"}

@app.get("/pokemons/{username}")
async def get_pokemons(username: str):
    user_pokes = pokemon_collection.find_one({"username": username})
    return {"pokemons": user_pokes["pokemons"] if user_pokes else []}

@app.post("/pokemons/add")
async def add_pokemon(data: PokemonActionModel):
    pokemon_collection.update_one(
        {"username": data.username},
        {"$push": {"pokemons": {"name": data.pokemon, "level": 1, "health": 100, "power": 10}}},
        upsert=True
    )
    return {"message": "Pokemon added"}

@app.post("/pokemons/remove")
async def remove_pokemon(data: PokemonActionModel):
    pokemon_collection.update_one(
        {"username": data.username},
        {"$pull": {"pokemons": {"name": data.pokemon}}}
    )
    return {"message": "Pokemon removed"}

@app.post("/pokemons/data")
async def update_pokemon_data(data: PokemonDataModel):
    pokemon_collection.update_one(
        {"username": data.username, "pokemons.name": data.pokemon},
        {"$set": {f"pokemons.$.{data.key}": data.value}}
    )
    return {"message": f"{data.key} updated for {data.pokemon}"}

# Run with: uvicorn filename:app --host 0.0.0.0 --port 8000
