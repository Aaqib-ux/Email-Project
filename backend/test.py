import asyncio
import sys
import logging
from google.auth.exceptions import RefreshError

# importing models
from backend.gmail_service import GmailService
from backend.ai_analyzer import analyze_email_content, get_email_subject, get_email_body
from Database.database import EmailDatabase, get_email_date, get_email_sender
import secrets

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def save_user_credentials(db: EmailDatabase, user_id: int, credentials_dict: dict):
    """Save user credentials to database"""
    try:
        db.save_user_credentials(user_id, credentials_dict)
        logger.info(f"Credentials saved for user: {user_id}")
    except Exception as e:
        logger.error(f"Failed to save credentials: {e}")


def load_user_credentials(db: EmailDatabase, user_id: int) -> dict:
    """Load user credentials from database"""
    try:
        result = db.load_credentials(user_id)
        if result:
            return {
                "token": result[0],
                "refresh_token": result[1],
                "expiry": result[2],
                "scopes": result[3],
            }
        return None
    except Exception as e:
        logger.error(f"Failed to load credentials: {e}")
        return None


async def authenticate_user(
    gmail_service: GmailService, db: EmailDatabase, google_user_id: str
):
    """Handle user authentication for web application
    This simulates what happens in a web app but in a command line
    Interface
    """

    print(f"\n Starting Oauth authentiation for user:{google_user_id}")

    auth_url, state = gmail_service.get_authorization_url()

    print(f"\n" + "=" * 60)
    print("Authentication Required")
    print("=" * 60)
    print("1. Copy and paste this Url in your browser:")
    print(f" {auth_url}")
    print("\n2. Sign in to google and grant permission")
    print("3. After Authorization, you'll be redirected to a callback URL")
    print("4. Copy the 'code' parameter from the callback URL")
    print("=" * 60)

    auth_code = input("\nEnter the authorization code from callback: ").strip()

    if not auth_code:
        print("No authorization code provided")
        return None

    print("\n Exchanging authorization code provided")
    credentials = gmail_service.handle_oauth_callback(auth_code, state)

    if not credentials:
        print("Failed to get credentials from authorization code")
        return None

    credentials_dict = gmail_service.credentials_to_dict(credentials)
    # Create/get user from database first to get integer user_id
    user_id = db.create_user(google_user_id)  # This returns integer ID
    save_user_credentials(db, user_id, credentials_dict)  # Now using integer ID

    print("Authentication successful")
    return credentials


async def get_authenticated_service(
    gmail_service: GmailService,
    db: EmailDatabase,
    user_email: str,  # CHANGED: parameter should be user_email string, not user_id int
):
    """
    get an authentication Gmail service for a user
    This is what each web request would do to get the service
    """
    # CHANGED: Get integer user ID from database using email
    user_id = db.create_user(user_email)  # This returns the integer id from users table

    # Step 1: Try to load existing credentials
    credential_dict = load_user_credentials(
        db, user_id
    )  # FIXED: removed duplicate user_id assignment

    if credential_dict:
        print(
            f"Found existing creds for user : {user_email} (ID: {user_id})"
        )  # CHANGED: show both email and ID for clarity

        # Step 2: Convert back to credentials object
        credentials = gmail_service.credentials_from_dict(credential_dict)

        # step 3: Build and test services
        service = gmail_service.build_service(credentials)

        if service:
            print("successfully build gmail service from stored credentials")
            return service, credentials
        else:
            print(
                "Stored Credentials are invalid, need to re-authenticate"
            )  # FIXED: typo "Credntials"

    # step 4: if no valid credentials, start authentication
    print(f"No valid creds found for user: {user_email}")
    credentials = await authenticate_user(
        gmail_service, db, user_email
    )  # CHANGED: pass user_email, not user_id

    if credentials:
        service = gmail_service.build_service(credentials)
        return service, credentials

    return None, None


async def process_and_store_emails(
    user_email: str = "test_user@example.com", max_emails: int = 5
):
    """
    Main function to fetch emails, analyze them with AI, and store in database
    Updated for web application architecture
    Flow: User Auth -> Gmail API -> AI Analysis -> Database Storage
    """
    processed_count = 0
    skipped_count = 0
    error_count = 0

    try:
        # Initialize services
        logger.info("🔧 Initializing database connection...")
        db = EmailDatabase()

        logger.info("🔧 Initializing Gmail service...")
        gmail_service = GmailService()

        logger.info(f"Creating/getting user emails: {user_email}")

        # NEW: Get authenticated service for specific user
        logger.info(f"🔐 Getting authenticated service for user: {user_email}")
        service, credentials = await get_authenticated_service(
            gmail_service, db, user_email
        )

        if not service:
            logger.error("Failed to get authenticated Gmail service")
            print("❌ Gmail authentication failed. Please check your setup.")
            return

        # Test the service
        if not gmail_service.test_connection(service):
            logger.error("Gmail service connection test failed")
            print("❌ Gmail service not working properly.")
            return

        # Get user profile to show who we're authenticated as
        profile = gmail_service.get_user_profile(service)
        if profile:
            actual_email = profile.get("emailAddress")
            google_user_id = profile.get("id")
            db_user_id = db.create_user(actual_email, google_user_id)

            print(f"📧 Authenticated as: {actual_email}")
            print(
                f"📊 Total messages in account: {profile.get('messagesTotal', 'Unknown')}"
            )

        # Fetch emails (CHANGED: now requires service parameter)
        logger.info(f"📧 Fetching {max_emails} emails from inbox...")
        emails = await gmail_service.get_emails(
            service, max_results=max_emails, query=None
        )

        if not emails:
            logger.warning("No emails found in inbox")
            print("No emails found in inbox")
            return

        logger.info(f"📋 Found {len(emails)} emails to process")
        print(f"\n📋 Processing {len(emails)} emails...")
        print("=" * 50)

        # Process each email (same logic as before)
        for index, email_meta in enumerate(emails, 1):
            try:
                email_id = email_meta.get("id")
                if not email_id:
                    logger.warning(f"Email {index}: No ID found, skipping")
                    skipped_count += 1
                    continue

                # Check if email already exists in database
                if db.email_exists(email_id):
                    logger.debug(
                        f"Email {index} (ID: {email_id}) already exists, skipping"
                    )
                    skipped_count += 1
                    continue

                # Get full email details (CHANGED: now requires service parameter)
                logger.debug(f"Fetching details for email {index} (ID: {email_id})")
                email_detail = gmail_service.get_email_detail(service, email_id)

                if not email_detail:
                    logger.warning(f"Email {index}: Could not fetch details, skipping")
                    error_count += 1
                    continue

                # Extract email data (same as before)
                sender = get_email_sender(email_detail)
                subject = get_email_subject(email_detail)
                body = get_email_body(email_detail)
                date_received = get_email_date(email_detail)

                # Validate extracted data
                if not sender or not subject:
                    logger.warning(
                        f"Email {index}: Missing sender or subject, skipping"
                    )
                    error_count += 1
                    continue

                # AI Analysis with error handling (same as before)
                try:
                    logger.debug(f"Analyzing email {index} with AI...")
                    ai_labels = await analyze_email_content(subject, body)
                except Exception as ai_error:
                    logger.warning(f"AI analysis failed for email {index}: {ai_error}")
                    ai_labels = ["analysis_failed"]

                # Store in database (same as before)
                db_email_id = db.insert_email(
                    gmail_id=email_id,
                    sender=sender,
                    subject=subject,
                    body=body,
                    date_received=date_received,
                    ai_labels=ai_labels,
                    user_id=db_user_id,
                )

                processed_count += 1

                # Display progress (same as before)
                print(f"\n✅ Email {index}/{len(emails)} processed:")
                print(f"   📧 From: {sender}")
                print(
                    f"   📌 Subject: {subject[:60]}{'...' if len(subject) > 60 else ''}"
                )
                print(
                    f"   🏷️  AI Labels: {', '.join(ai_labels) if ai_labels else 'None'}"
                )
                print(f"   📅 Date: {date_received.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"   💾 DB ID: {db_email_id}")

                # Show progress every 5 emails
                if index % 5 == 0:
                    print(f"\n🔄 Progress: {index}/{len(emails)} emails processed")

                # Small delay to avoid overwhelming the system
                await asyncio.sleep(0.1)

            except Exception as email_error:
                error_count += 1
                email_id = email_meta.get("id", "Unknown ID")
                logger.error(
                    f"Error processing email {index} (ID: {email_id}): {email_error}"
                )
                print(
                    f"❌ Error processing email {index} (ID: {email_id}): {email_error}"
                )
                continue

        # Final summary (same as before)
        total_db_emails = db.get_email_count()

        print("\n" + "=" * 60)
        print(f"📊 PROCESSING SUMMARY - User: {db_user_id}")
        print("=" * 60)
        print(f"✅ Successfully processed: {processed_count} emails")
        print(f"⏭️  Skipped (already exists): {skipped_count} emails")
        print(f"❌ Errors encountered: {error_count} emails")
        print(f"📁 Total emails in database: {total_db_emails}")
        print("=" * 60)

        logger.info(
            f"Processing completed for user {db_user_id}: {processed_count} processed, {skipped_count} skipped, {error_count} errors"
        )

    except RefreshError as refresh_error:
        error_msg = "🔐 Authentication Error: Token refresh failed"
        logger.critical(error_msg)
        print(f"\n❌ {error_msg}")
        print("📋 This usually means you need to re-authenticate:")
        print("   1. Delete user_credentials.json")
        print("   2. Run the script again to re-authenticate")
        sys.exit(1)

    except FileNotFoundError as file_error:
        if "credentials.json" in str(file_error):
            error_msg = "🔐 Missing credentials.json file"
            logger.critical(error_msg)
            print(f"\n❌ {error_msg}")
            print("Make sure you have web application credentials.json file.")
        else:
            logger.critical(f"File not found: {file_error}")
            print(f"\n❌ File not found: {file_error}")
        sys.exit(1)

    except Exception as general_error:
        error_msg = f"❌ Unexpected error: {str(general_error)}"
        logger.critical(error_msg)
        print(f"\n{error_msg}")
        print("Please check your configuration and try again.")
        sys.exit(1)


async def show_recent_emails():
    """Display emails from database for varification"""

    try:
        db = EmailDatabase()
        recent_emails = db.get_recent_emails(limit=5)

        if recent_emails:
            print(f"\n Recent 5 emails from databse")
            print("-" * 50)
            for i, email in enumerate(recent_emails, 1):
                print(f"{i}. From: {email['sender']}")
                print(f" Subject: {email['subject'][:50]}")
                print(f" Labels: {email['ai_labels']}")
                print(f" Date: {email['date_received']}")
                print()
        else:
            print("No emails founc")

    except Exception as e:
        print(f"Error retriving recent emails")
        logger.error(f"Error Retrieving recent emails:{e}")


async def test_service():
    """Test Database Service (Gmail test is no done per user)"""

    try:
        print("Testing service")

        # test database
        print("Testing database connection")
        db = EmailDatabase()

        print(f"Database OK - {db.get_email_count()} emails currently stored")
        return True
    except Exception as e:
        print(f"Sevice test failed: {e}")
        logger.error(f"Service test failed:{e}")
        return False


def main():
    """Main entry point"""
    print("Gmail email processor - Web application Mode")
    print("Flow: user Auth -> Gmail Api -> Ai analyses-> database storage")

    try:
        print("Running Service Tests...")
        if not asyncio.run(test_service()):
            print("Service failed. please check your configuration")
            sys.exit(1)

        print("\n Database Working Fine")

        user_email = input("\n Enter user ID for testing or Enter: ")
        if not user_email:
            user_email = "test_user@example.com"

        print(f"Processing emails for user:{user_email}")
        print("Starting email procesing...")

        # run the processor now with user authentication
        asyncio.run(process_and_store_emails(user_email=user_email, max_emails=5))

        # Show recent emails for verfication
        print("\nShowing recents emails for verification...")
        asyncio.run(show_recent_emails())

        print(f"\n Gmail processing completed succeddfully for the user: {user_email}")

    except KeyboardInterrupt:
        print("\n Process interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n Fatal error:{e}")
        logger.critical(f"Fatal in error:{e}")
        sys.exit(0)


if __name__ == "__main__":
    main()
