from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from backend.gmail_service import GmailService
from Database.database import EmailDatabase
from supabase import create_client, Client
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()
app = FastAPI()
gmail_service = GmailService()
db = EmailDatabase()

# Supabase setup
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


# Request models
class UserAuth(BaseModel):
    email: str
    password: str


@app.post("/auth/signup")
def signup(user_data: UserAuth):
    try:
        # supabase auth signup
        response = supabase.auth.sign_up(
            {"email": user_data.email, "password": user_data.password}
        )

        # create user in your Database too

        if response.user:
            db_user_id = db.create_user(email=response.user.email, google_user_id=None)

        if response.user and not response.user.confirmed_at:
            return {
                "message": "Signup successful, please confirm your email",
                "user": {
                    "id": response.user.id,
                    "db_user_id": db_user_id,
                    "email": response.user.email,
                    "confirmation_required": True,
                },
            }
        else:
            return {
                "message": "Signup successful",
                "user": {
                    "id": response.user.id,
                    "db_user_id": db_user_id,
                    "email": response.user.email,
                },
                "email_confirmed": True,
            }

    except Exception as e:
        error_message = str(e)

        if "already registered" in error_message.lower():
            raise HTTPException(status_code=409, detail="Email already registered")
        elif "password" in error_message.lower() and "weak" in error_message.lower():
            raise HTTPException(
                status_code=400,
                detail="Password too weak. Must be at least 8 characters.",
            )
        else:
            raise HTTPException(status_code=400, detail=error_message)


@app.post("/auth/login")
def login(user_data: UserAuth):

    try:
        response = supabase.auth.sign_in_with_password(
            {"email": user_data.email, "password": user_data.password}
        )

        user = response.user

        db.user.id = db.create_connection(email=user.email)

        return {
            "message": "Login successful",
            "user": {"id": user.id, "db_user_id": db.user.id, "email": user.email},
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/")
def root():
    return {"message": "Email Analyzer API"}


@app.get("/auth/gmail")
async def gmail_auth():
    """Start Gmail OAuth flow"""
    auth_url, state = gmail_service.get_authorization_url()
    return RedirectResponse(auth_url)


@app.get("/auth/gmail/callback")
async def gmail_callback(code: str, state: str):
    """Handle OAuth callback from Google"""
    credentials = gmail_service.handle_oauth_callback(code, state)
    if not credentials:
        return JSONResponse({"error": "Authentication failed"}, status_code=400)

    # Build service to get user email
    service = gmail_service.build_service(credentials)
    profile = gmail_service.get_user_profile(service)
    user_email = profile.get("emailAddress")
    google_user_id = profile.get("id")

    # Store credentials
    user_id = db.create_user(user_email, google_user_id=google_user_id)
    credentials_dict = gmail_service.credentials_to_dict(credentials)
    db.save_user_credentials(user_id, credentials_dict)

    return {"message": "Authentication successful", "user_email": user_email}
