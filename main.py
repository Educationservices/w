from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional, List
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from bson.objectid import ObjectId
import random
import string
import os
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

load_dotenv()
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB connection
MONGODB_URI = os.getenv("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client["game_db"]
users_collection = db["users"]
games_collection = db["games"]
pokemon_collection = db["pokemons"]
verification_collection = db["verifications"]

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

class EmailVerificationModel(BaseModel):
    email: str
    username: Optional[str] = None

class GetCodeModel(BaseModel):
    email: str

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

@app.post("/send-verification-email")
async def send_verification_email(data: EmailVerificationModel):
    try:
        # Gmail SMTP configuration
        SMTP_SERVER = "smtp.gmail.com"
        SMTP_PORT = 587
        GMAIL_USER = os.getenv("GMAIL_USER")  # Your Gmail address
        GMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")  # Your Gmail App Password
        
        if not GMAIL_USER or not GMAIL_PASSWORD:
            return JSONResponse({"error": "Email configuration not found"}, status_code=500)
        
        # Generate verification code
        verification_code = generate_code(8)  # 8-character code
        
        # Store verification code in database with expiration
        expiration_time = datetime.utcnow() + timedelta(minutes=10)
        verification_collection.update_one(
            {"email": data.email},
            {"$set": {
                "email": data.email,
                "code": verification_code,
                "expires_at": expiration_time,
                "created_at": datetime.utcnow()
            }},
            upsert=True
        )
        
        # Create email content
        subject = "Email Verification - Game Account"
        
        # HTML email template
        html_body = f"""
        <html>
        <body>
            <h2>Welcome to the Pokemon Game!</h2>
            <p>Hi {data.username or 'Player'},</p>
            <p>Thank you for signing up! Please use the verification code below to verify your email address:</p>
            <div style="background-color: #f0f0f0; padding: 20px; text-align: center; margin: 20px 0;">
                <h1 style="color: #333; letter-spacing: 3px;">{verification_code}</h1>
            </div>
            <p>This code will expire in 10 minutes.</p>
            <p>If you didn't request this verification, please ignore this email.</p>
            <br>
            <p>Happy Gaming!</p>
            <p>The Pokemon Game Team</p>
        </body>
        </html>
        """
        
        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = GMAIL_USER
        message["To"] = data.email
        
        # Add HTML content
        html_part = MIMEText(html_body, "html")
        message.attach(html_part)
        
        # Send email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.send_message(message)
        
        return {"message": "Verification email sent successfully", "code_sent": True}
        
    except smtplib.SMTPAuthenticationError:
        return JSONResponse({"error": "Gmail authentication failed"}, status_code=500)
    except smtplib.SMTPException as e:
        return JSONResponse({"error": f"Failed to send email: {str(e)}"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": f"Unexpected error: {str(e)}"}, status_code=500)

@app.post("/codes/")
async def get_verification_code(data: GetCodeModel):
    try:
        # Clean up expired codes first
        verification_collection.delete_many({"expires_at": {"$lt": datetime.utcnow()}})
        
        # Find the verification code for this email
        verification = verification_collection.find_one({"email": data.email})
        
        if not verification:
            return JSONResponse({"error": "No verification code found for this email"}, status_code=404)
        
        # Check if code is expired
        if verification["expires_at"] < datetime.utcnow():
            verification_collection.delete_one({"email": data.email})
            return JSONResponse({"error": "Verification code has expired"}, status_code=410)
        
        # Calculate remaining time
        remaining_time = verification["expires_at"] - datetime.utcnow()
        remaining_minutes = int(remaining_time.total_seconds() / 60)
        
        return {
            "email": data.email,
            "code": verification["code"],
            "expires_in_minutes": remaining_minutes,
            "created_at": verification["created_at"].isoformat()
        }
    except Exception as e:
        return JSONResponse({"error": f"Database error: {str(e)}"}, status_code=500)

# Run with: uvicorn filename:app --host 0.0.0.0 --port 8000
