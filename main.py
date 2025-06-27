from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, EmailStr, ValidationError
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
import json
import re

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

def validate_email(email: str) -> bool:
    """Simple email validation"""
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(email_pattern, email) is not None

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

# FIXED EMAIL VERIFICATION ENDPOINTS

@app.post("/send-verification-email")
async def send_verification_email(request: Request):
    """
    Robust email verification endpoint that handles various request formats
    """
    try:
        # Get raw body and content type
        body = await request.body()
        content_type = request.headers.get("content-type", "").lower()
        
        print(f"Content-Type: {content_type}")
        print(f"Raw body: {body}")
        
        # Handle different content types
        if "application/json" in content_type:
            try:
                if isinstance(body, bytes):
                    body_str = body.decode('utf-8').strip()
                else:
                    body_str = str(body).strip()
                
                # Parse JSON
                data_dict = json.loads(body_str)
                print(f"Parsed JSON: {data_dict}")
                
            except json.JSONDecodeError as e:
                return JSONResponse(
                    {"error": f"Invalid JSON format: {str(e)}", "received_body": body.decode('utf-8')[:200]}, 
                    status_code=400
                )
        else:
            return JSONResponse({"error": "Content-Type must be application/json"}, status_code=400)
        
        # Validate required fields
        if not isinstance(data_dict, dict):
            return JSONResponse({"error": "Request body must be a JSON object"}, status_code=400)
        
        if "email" not in data_dict:
            return JSONResponse({"error": "Email field is required"}, status_code=400)
        
        email = data_dict["email"]
        username = data_dict.get("username", "Adventurer")
        
        # Validate email format
        if not validate_email(email):
            return JSONResponse({"error": "Invalid email format"}, status_code=400)
        
        # Check environment variables
        GMAIL_USER = os.getenv("GMAIL_USER")
        GMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
        
        if not GMAIL_USER or not GMAIL_PASSWORD:
            return JSONResponse({"error": "Email configuration not found"}, status_code=500)
        
        # Generate verification code
        verification_code = generate_code(8)
        
        # Store verification code in database
        expiration_time = datetime.utcnow() + timedelta(minutes=10)
        verification_collection.update_one(
            {"email": email},
            {"$set": {
                "email": email,
                "code": verification_code,
                "expires_at": expiration_time,
                "created_at": datetime.utcnow()
            }},
            upsert=True
        )
        
        # Create email content
        subject = "Email Verification - Minimon Account"
        html_body = create_email_template(username, verification_code)
        
        # Send email
        await send_email(GMAIL_USER, GMAIL_PASSWORD, email, subject, html_body)
        
        return {
            "message": "Verification email sent successfully",
            "code_sent": True,
            "email": email,
            "expires_in_minutes": 10
        }
        
    except Exception as e:
        print(f"Error in send_verification_email: {str(e)}")
        return JSONResponse({"error": f"Unexpected error: {str(e)}"}, status_code=500)

@app.post("/send-verification-email-v2")
async def send_verification_email_v2(data: EmailVerificationModel):
    """
    Pydantic model-based email verification endpoint
    """
    try:
        print(f"Received data: email={data.email}, username={data.username}")
        
        # Validate email format
        if not validate_email(data.email):
            raise HTTPException(status_code=400, detail="Invalid email format")
        
        # Check environment variables
        GMAIL_USER = os.getenv("GMAIL_USER")
        GMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
        
        if not GMAIL_USER or not GMAIL_PASSWORD:
            raise HTTPException(status_code=500, detail="Email configuration not found")
        
        # Generate verification code
        verification_code = generate_code(8)
        
        # Store verification code in database
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
        
        # Create and send email
        subject = "Email Verification - Minimon Account"
        html_body = create_email_template(data.username or "Adventurer", verification_code)
        
        await send_email(GMAIL_USER, GMAIL_PASSWORD, data.email, subject, html_body)
        
        return {
            "message": "Verification email sent successfully",
            "code_sent": True,
            "email": data.email,
            "expires_in_minutes": 10
        }
        
    except ValidationError as e:
        return JSONResponse({"error": f"Validation error: {str(e)}"}, status_code=400)
    except HTTPException as e:
        return JSONResponse({"error": e.detail}, status_code=e.status_code)
    except Exception as e:
        print(f"Error in send_verification_email_v2: {str(e)}")
        return JSONResponse({"error": f"Unexpected error: {str(e)}"}, status_code=500)

async def send_email(gmail_user: str, gmail_password: str, to_email: str, subject: str, html_body: str):
    """
    Helper function to send email
    """
    try:
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = gmail_user
        message["To"] = to_email
        
        html_part = MIMEText(html_body, "html")
        message.attach(html_part)
        
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_password)
            server.send_message(message)
            
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=500, detail="Gmail authentication failed")
    except smtplib.SMTPException as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

def create_email_template(username: str, verification_code: str) -> str:
    """
    Creates HTML email template
    """
    return f"""
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
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
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
                width: 90%;
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
            }}
            .verification-code {{
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
                font-size: 2.2em;
                font-weight: bold;
                letter-spacing: 8px;
                padding: 20px;
                border-radius: 10px;
                margin: 20px 0;
                text-align: center;
                font-family: 'Courier New', monospace;
            }}
            .message {{
                color: #555;
                line-height: 1.6;
                margin-bottom: 20px;
                font-size: 1.1em;
            }}
            .footer {{
                margin-top: 30px;
                text-align: center;
                color: #666;
            }}
        </style>
    </head>
    <body>
        <div class="email-container">
            <div class="header">
                <h1 class="logo">Minimon ✨</h1>
                <p>Adventure Awaits!</p>
            </div>
            
            <div class="message">
                <h2>Hello {username}! 🎮</h2>
                <p>Welcome to Minimon! Please use this verification code to complete your registration:</p>
            </div>
            
            <div class="verification-code">{verification_code}</div>
            
            <div class="message">
                <p><strong>⏰ Important:</strong> This code expires in 10 minutes.</p>
                <p>Once verified, you'll be ready to start your Minimon adventure!</p>
            </div>
            
            <div class="footer">
                <p>Happy gaming! 🌟</p>
                <p><strong>The Minimon Team</strong></p>
            </div>
        </div>
    </body>
    </html>
    """

@app.post("/codes/")
async def get_verification_code(data: GetCodeModel):
    """
    Retrieve verification code for debugging/testing
    """
    try:
        # Clean up expired codes
        verification_collection.delete_many({"expires_at": {"$lt": datetime.utcnow()}})
        
        # Find verification code
        verification = verification_collection.find_one({"email": data.email})
        
        if not verification:
            raise HTTPException(status_code=404, detail="No verification code found for this email")
        
        # Check if expired
        if verification["expires_at"] < datetime.utcnow():
            verification_collection.delete_one({"email": data.email})
            raise HTTPException(status_code=410, detail="Verification code has expired")
        
        # Calculate remaining time
        remaining_time = verification["expires_at"] - datetime.utcnow()
        remaining_minutes = int(remaining_time.total_seconds() / 60)
        
        return {
            "email": data.email,
            "code": verification["code"],
            "expires_in_minutes": remaining_minutes,
            "created_at": verification["created_at"].isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/debug-request")
async def debug_request(request: Request):
    """
    Debug endpoint to inspect request format
    """
    body = await request.body()
    return {
        "body": body.decode() if body else None,
        "content_type": request.headers.get("content-type"),
        "headers": dict(request.headers),
        "method": request.method,
        "url": str(request.url)
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
