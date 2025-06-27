from fastapi import FastAPI, Request
from pydantic import BaseModel, EmailStr
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
    email: str  # Using str instead of EmailStr for less strict validation
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
    email: str  # Using str instead of EmailStr for less strict validation
    username: Optional[str] = None

class GetCodeModel(BaseModel):
    email: str  # Changed from EmailStr to regular str

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
# Replace your html_body f-string with this corrected version:

html_body = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Minimon - Email Verification</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%%, #764ba2 100%%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .email-container {{
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 40px;
            max-width: 600px;
            width: 90%%;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
        }}
        .logo {{
            background: linear-gradient(45deg, #ff6b6b, #4ecdc4);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            font-size: 2.5em;
            font-weight: bold;
            margin-bottom: 10px;
            text-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}
        .subtitle {{
            color: #666;
            font-size: 1.1em;
            margin: 0;
        }}
        .greeting {{
            font-size: 1.3em;
            color: #333;
            margin-bottom: 20px;
            font-weight: 500;
        }}
        .message {{
            color: #555;
            line-height: 1.6;
            margin-bottom: 30px;
            font-size: 1.1em;
        }}
        .verification-box {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            border-radius: 15px;
            padding: 30px;
            text-align: center;
            margin: 30px 0;
            position: relative;
            overflow: hidden;
        }}
        .verification-box::before {{
            content: '';
            position: absolute;
            top: -50%%;
            left: -50%%;
            width: 200%%;
            height: 200%%;
            background: radial-gradient(circle, rgba(255, 255, 255, 0.1) 0%%, transparent 70%%);
            animation: shimmer 3s ease-in-out infinite;
        }}
        @keyframes shimmer {{
            0%%, 100%% {{ transform: rotate(0deg); }}
            50%% {{ transform: rotate(180deg); }}
        }}
        .verification-code {{
            background: rgba(255, 255, 255, 0.9);
            color: #333;
            font-size: 2.2em;
            font-weight: bold;
            letter-spacing: 8px;
            padding: 20px;
            border-radius: 10px;
            margin: 10px 0;
            font-family: 'Courier New', monospace;
            border: 2px solid rgba(255, 255, 255, 0.3);
            position: relative;
            z-index: 1;
        }}
        .code-label {{
            color: white;
            font-size: 1.1em;
            margin-bottom: 15px;
            font-weight: 500;
            position: relative;
            z-index: 1;
        }}
        .expiry-notice {{
            background: rgba(255, 193, 7, 0.1);
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin: 25px 0;
            border-radius: 0 8px 8px 0;
            color: #856404;
            font-weight: 500;
        }}
        .footer {{
            margin-top: 40px;
            text-align: center;
        }}
        .footer p {{
            color: #666;
            margin: 5px 0;
        }}
        .team-signature {{
            background: linear-gradient(45deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            font-weight: bold;
            font-size: 1.2em;
        }}
        .disclaimer {{
            font-size: 0.9em;
            color: #999;
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #eee;
        }}
        .sparkle {{
            display: inline-block;
            animation: sparkle 2s ease-in-out infinite;
        }}
        @keyframes sparkle {{
            0%%, 100%% {{ transform: scale(1) rotate(0deg); }}
            50%% {{ transform: scale(1.1) rotate(180deg); }}
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <h1 class="logo">Minimon <span class="sparkle">✨</span></h1>
            <p class="subtitle">Adventure Awaits!</p>
        </div>
        
        <div class="greeting">
            Hello {data.username or 'Adventurer'}! 🎮
        </div>
        
        <div class="message">
            Welcome to the world of Minimon! We're thrilled to have you join our community of explorers and collectors. 
            To complete your registration and start your epic journey, please verify your email address using the code below:
        </div>
        
        <div class="verification-box">
            <div class="code-label">Your Verification Code</div>
            <div class="verification-code">{verification_code}</div>
        </div>
        
        <div class="expiry-notice">
            ⏰ <strong>Important:</strong> This verification code will expire in 10 minutes for security purposes.
        </div>
        
        <div class="message">
            Once verified, you'll have access to all the exciting features that Minimon has to offer. 
            Get ready to embark on adventures, collect rare creatures, and become the ultimate Minimon master!
        </div>
        
        <div class="footer">
            <p>Happy adventuring! 🌟</p>
            <p class="team-signature">The Minimon Team</p>
            
            <div class="disclaimer">
                If you didn't create a Minimon account, please ignore this email. 
                No further action is required, and your email will not be added to our system.
            </div>
        </div>
    </div>
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

@app.post("/debug-request")
async def debug_request(request: Request):
    body = await request.body()
    return {
        "body": body.decode(),
        "content_type": request.headers.get("content-type"),
        "headers": dict(request.headers)
    }

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
