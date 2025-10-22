from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
import os.path
import json
import logging
from dotenv import load_dotenv
from typing import List, Dict, Optional, Tuple
import secrets

load_dotenv()
logger = logging.getLogger(__name__)


class GmailService:
    def __init__(self):
        # Define required permission - using readonly scope since we're not modifying
        self.SCOPES = [
            os.getenv("GMAIL_SCOPES", "https://www.googleapis.com/auth/gmail.readonly")
        ]

        # Get project root from environment or detect automatically
        project_root = os.getenv("PROJECT_ROOT")
        if not project_root:
            current_file_dir = os.path.dirname(os.path.abspath(__file__))

            # Check if we're in an 'app' subdirectory
            if os.path.basename(current_file_dir) == "app":
                project_root = os.path.dirname(current_file_dir)
            else:
                project_root = current_file_dir

            # Look for common project files to confirm we're in the right place
            potential_roots = [current_file_dir, os.path.dirname(current_file_dir)]
            for root in potential_roots:
                if any(
                    os.path.exists(os.path.join(root, file))
                    for file in ["credentials.json", "main.py", "README.md", ".env"]
                ):
                    project_root = root
                    break

        # Set up file paths for credentials
        self.CREDENTIALS_FILE = os.path.join(project_root, "credentials.json")
        self.REDIRECT_URI = os.getenv(
            "REDIRECT_URI", "http://localhost:8000/auth/gmail/callback"
        )

        logger.info(f"Project root detected as: {project_root}")
        logger.info(f"Looking for credentials at: {self.CREDENTIALS_FILE}")
        logger.info(f"Redirect URI: {self.REDIRECT_URI}")

        # Check if credentials file exists
        if not os.path.exists(self.CREDENTIALS_FILE):
            self.show_credentials_setup_instructions()
            raise FileNotFoundError(
                f"credentials.json not found at {self.CREDENTIALS_FILE}"
            )

        # Verify credentials file has web format
        self.verify_web_credentials()

    def verify_web_credentials(self):
        """Verify that the credentials file is in web application format"""
        try:
            with open(self.CREDENTIALS_FILE, "r") as f:
                creds_data = json.load(f)

            if "web" not in creds_data:
                logger.error("❌ Credentials file is not in web application format!")
                raise ValueError(
                    "Credentials file must be for Web Application, not Desktop Application"
                )

            # Check if redirect URI is configured
            redirect_uris = creds_data.get("web", {}).get("redirect_uris", [])
            if self.REDIRECT_URI not in redirect_uris:
                logger.warning(
                    f"⚠️  Redirect URI {self.REDIRECT_URI} not found in credentials"
                )
                logger.warning(
                    "Make sure to add it in Google Cloud Console OAuth settings"
                )

            logger.info("✅ Web application credentials format verified")

        except json.JSONDecodeError:
            logger.error("❌ Invalid JSON format in credentials file")
            raise
        except Exception as e:
            logger.error(f"❌ Error verifying credentials: {e}")
            raise

    def create_oauth_flow(self) -> Flow:
        """Create OAuth flow for web application"""
        try:
            flow = Flow.from_client_secrets_file(
                self.CREDENTIALS_FILE, scopes=self.SCOPES
            )
            flow.redirect_uris = self.REDIRECT_URI
            return flow
        except Exception as e:
            logger.error(f"Failed to create OAuth flow: {e}")
            raise

    @classmethod
    def get_authorization_url(cls) -> Tuple[str, str]:
        """Generate authorization URL for user to authenticate"""
        try:
            # Set up credentials path (same logic as __init__)
            project_root = os.getenv("PROJECT_ROOT")
            if not project_root:
                current_file_dir = os.path.dirname(os.path.abspath(__file__))
                if os.path.basename(current_file_dir) == "app":
                    project_root = os.path.dirname(current_file_dir)
                else:
                    project_root = current_file_dir

            credentials_file = os.path.join(project_root, "credentials.json")
            redirect_uri = os.getenv(
                "REDIRECT_URI", "http://localhost:8000/auth/gmail/callback"
            )
            scopes = [
                os.getenv(
                    "GMAIL_SCOPES", "https://www.googleapis.com/auth/gmail.readonly"
                )
            ]

            # Create flow
            flow = Flow.from_client_secrets_file(credentials_file, scopes=scopes)
            flow.redirect_uri = redirect_uri

            state = secrets.token_urlsafe(30)
            authorization_url, _ = flow.authorization_url(
                access_type="offline",
                include_granted_scopes="true",
                prompt="consent",
                state=state,
            )
            logger.info("✅ Authorization URL generated successfully")
            return authorization_url, state
        except Exception as e:
            logger.error(f"Failed to generate authorization URL: {e}")
            raise

    def handle_oauth_callback(
        self, authorization_code: str, state: str = None
    ) -> Optional[Credentials]:
        """
        Handle OAuth callback and exchange authorization code for tokens

        Args:
            authorization_code: The code returned by Google
            state: The state parameter for security validation

        Returns:
            Credentials object or None if failed
        """
        try:
            flow = self.create_oauth_flow()
            flow.redirect_uri = self.REDIRECT_URI
            # Exchange authorization code for tokens
            flow.fetch_token(code=authorization_code)
            credentials = flow.credentials

            logger.info("✅ OAuth callback handled successfully")
            logger.info(f"Token expires at: {credentials.expiry}")
            logger.info(f"Has refresh token: {bool(credentials.refresh_token)}")

            return credentials

        except Exception as e:
            logger.error(f"OAuth callback failed: {e}")
            return None

    def refresh_credentials(self, credentials: Credentials) -> Optional[Credentials]:
        """
        Refresh expired credentials using refresh token

        Args:
            credentials: Existing credentials with refresh token

        Returns:
            Refreshed credentials or None if failed
        """
        try:
            if not credentials.refresh_token:
                logger.error("No refresh token available")
                return None

            credentials.refresh(Request())
            logger.info("✅ Credentials refreshed successfully")
            return credentials

        except Exception as e:
            logger.error(f"Failed to refresh credentials: {e}")
            return None

    def credentials_to_dict(self, credentials: Credentials) -> Dict:
        """Convert credentials to dictionary for storage"""
        return {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes,
            "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
        }

    def credentials_from_dict(self, creds_dict: Dict) -> Credentials:
        """Create credentials from dictionary"""
        from datetime import datetime

        expiry = None
        if creds_dict.get("expiry"):
            expiry = datetime.fromisoformat(creds_dict["expiry"])

        return Credentials(
            token=creds_dict["token"],
            refresh_token=creds_dict.get("refresh_token"),
            token_uri=creds_dict["token_uri"],
            client_id=creds_dict["client_id"],
            client_secret=creds_dict["client_secret"],
            scopes=creds_dict["scopes"],
            expiry=expiry,
        )

    def build_service(self, credentials: Credentials):
        """Build Gmail service with given credentials"""
        try:
            # Refresh if expired
            if credentials.expired and credentials.refresh_token:
                credentials = self.refresh_credentials(credentials)
                if not credentials:
                    logger.error("Failed to refresh expired credentials")
                    return None

            # Build Gmail service
            service = build("gmail", "v1", credentials=credentials)

            # Test the service
            profile = service.users().getProfile(userId="me").execute()
            logger.info(
                f"✅ Gmail service built successfully for: {profile.get('emailAddress')}"
            )

            return service

        except HttpError as e:
            logger.error(f"Gmail service build failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to build Gmail service: {e}")
            return None

    async def get_emails(
        self, service, max_results: int = 50, query: Optional[str] = None
    ) -> List[Dict]:
        """
        Fetches emails from Gmail with optional search query

        Args:
            service: Gmail service object (built from user's credentials)
            max_results: Maximum number of emails to fetch (max 500)
            query: Optional Gmail search query (e.g., 'is:unread', 'from:example.com')

        Returns:
            List of email message objects with basic metadata
        """
        if not service:
            logger.error("Gmail service not provided")
            return []

        try:
            # Gmail API has a max limit of 500 per request
            if max_results > 500:
                logger.warning(
                    f"Requested {max_results} emails, but Gmail API max is 500. Using 500."
                )
                max_results = 500

            search_info = f" with query '{query}'" if query else ""
            logger.info(
                f"Fetching up to {max_results} emails from inbox{search_info}..."
            )

            # Build request parameters
            request_params = {"userId": "me", "maxResults": max_results}

            # Add search query if provided
            if query:
                request_params["q"] = query
            else:
                # Default to inbox if no query provided
                request_params["labelIds"] = ["INBOX"]

            # Make the API call
            results = service.users().messages().list(**request_params).execute()

            messages = results.get("messages", [])
            logger.info(
                f"Gmail API returned {len(messages)} email IDs (requested: {max_results})"
            )

            # Debug: Show if we got fewer emails than requested
            if len(messages) < max_results:
                logger.info(
                    f"Note: Only {len(messages)} emails available matching criteria (requested {max_results})"
                )

            return messages

        except HttpError as e:
            if e.resp.status == 403:
                logger.error(
                    "Permission denied. Check if Gmail API is enabled and credentials are correct."
                )
            elif e.resp.status == 401:
                logger.error("Authentication failed. Token may be expired.")
            else:
                logger.error(f"Gmail API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch emails: {str(e)}")
            return []

    def get_email_detail(self, service, message_id: str) -> Optional[Dict]:
        """
        Get full email details by message ID with enhanced error handling

        Args:
            service: Gmail service object
            message_id: Gmail message ID

        Returns:
            Full email message object or None if failed
        """
        if not service:
            logger.error("Gmail service not provided")
            return None

        try:
            email_detail = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            logger.debug(f"Successfully fetched email detail for ID: {message_id}")
            return email_detail

        except HttpError as e:
            if e.resp.status == 404:
                logger.warning(f"Email with ID {message_id} not found")
            elif e.resp.status == 403:
                logger.error(f"Permission denied for email ID {message_id}")
            else:
                logger.error(f"Gmail API error for email ID {message_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to get email detail for ID {message_id}: {str(e)}")
            return None

    def test_connection(self, service) -> bool:
        """Test if the Gmail service is working properly"""
        try:
            if not service:
                logger.error("Gmail service not provided")
                return False

            # Test with a simple profile call
            profile = service.users().getProfile(userId="me").execute()
            logger.info(
                f"✅ Connection test successful for: {profile.get('emailAddress')}"
            )
            return True

        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    def get_user_profile(self, service) -> Optional[Dict]:
        """Get user profile information"""
        try:
            if not service:
                return None

            profile = service.users().getProfile(userId="me").execute()
            return profile

        except Exception as e:
            logger.error(f"Failed to get user profile: {e}")
            return None
