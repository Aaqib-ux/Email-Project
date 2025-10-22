import psycopg2
import psycopg2.extras
from psycopg2.extras import Json
import os
from datetime import datetime
from dotenv import load_dotenv
import logging
from email.utils import parsedate_to_datetime

load_dotenv()
logger = logging.getLogger(__name__)


class EmailDatabase:
    def __init__(self):
        # Database connection parameters
        self.db_config = {
            "host": os.getenv("DB_HOST", "localhost"),
            "database": os.getenv("DB_NAME", "postgres"),
            "user": os.getenv("DB_USER", "postgres"),
            "password": os.getenv("DB_PASSWORD", "aaqib12345"),
            "port": os.getenv("DB_PORT", "5432"),
            "sslmode": "require",
        }

    def create_connection(self):
        """Create database connection"""
        try:
            conn = psycopg2.connect(**self.db_config)
            # Register array adapter
            psycopg2.extras.register_default_jsonb(conn_or_curs=conn)
            logger.info("Successfully connected to database")
            return conn
        except Exception as e:
            logger.error(f"Error connecting to database: {e}")
            raise

    def insert_email(
        self, gmail_id, sender, subject, body, date_received, ai_labels, user_id
    ):
        """Insert email into database table"""
        insert_query = """
        INSERT INTO emails (gmail_id, sender, subject, body, date_received, ai_labels, user_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (gmail_id) DO UPDATE SET
            sender = EXCLUDED.sender,
            subject = EXCLUDED.subject,
            body = EXCLUDED.body,
            date_received = EXCLUDED.date_received,
            ai_labels = EXCLUDED.ai_labels,
            user_id = EXCLUDED.user_id
        RETURNING id;
        """
        conn = None
        try:
            conn = self.create_connection()
            cur = conn.cursor()

            # Debug logging
            logger.info(f"DEBUG - ai_labels type: {type(ai_labels)}")
            logger.info(f"DEBUG - ai_labels value: {ai_labels}")

            # Ensure ai_labels is always in the correct PostgreSQL array format
            if isinstance(ai_labels, list):
                # Convert Python list to PostgreSQL array format
                if len(ai_labels) == 0:
                    ai_labels_pg = "{}"  # Empty array
                else:
                    # Escape quotes and format as PostgreSQL array
                    escaped_labels = [label.replace('"', '\\"') for label in ai_labels]
                    ai_labels_pg = (
                        "{" + ",".join(f'"{label}"' for label in escaped_labels) + "}"
                    )
            elif isinstance(ai_labels, str):
                # If it's a single string, convert to array format
                escaped_label = ai_labels.replace('"', '\\"')
                ai_labels_pg = f'{{"{escaped_label}"}}'
            else:
                # Fallback - convert to string and wrap in array
                ai_labels_pg = f'{{"{str(ai_labels)}"}}'

            logger.info(f"DEBUG - PostgreSQL array format: {ai_labels_pg}")

            cur.execute(
                insert_query,
                (gmail_id, sender, subject, body, date_received, ai_labels_pg, user_id),
            )
            email_id = cur.fetchone()[0]
            conn.commit()
            logger.info(f"Email inserted with ID: {email_id}")
            return email_id
        except Exception as e:
            logger.error(f"Error inserting email: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def get_email_count(self):
        """Get total number of emails in database"""
        conn = None
        try:
            conn = self.create_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM emails;")
            count = cur.fetchone()[0]
            return count
        except Exception as e:
            logger.error(f"Error getting email count: {e}")
            return 0
        finally:
            if conn:
                conn.close()

    def get_recent_emails(self, limit=5):
        """Get recent emails from database"""
        conn = None
        try:
            conn = self.create_connection()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """
                SELECT sender, subject, ai_labels, date_received
                FROM emails
                ORDER BY date_received DESC
                LIMIT %s;
                """,
                (limit,),
            )
            emails = cur.fetchall()
            return emails
        except Exception as e:
            logger.error(f"Error fetching recent emails: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def email_exists(self, gmail_id):
        """Check if email already exists in database"""
        conn = None
        try:
            conn = self.create_connection()
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM emails WHERE gmail_id = %s;", (gmail_id,))
            exists = cur.fetchone() is not None
            return exists
        except Exception as e:
            logger.error(f"Error checking if email exists: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def create_user(self, email: str, google_user_id: str = None):
        """Create or get existing user"""
        insert_query = """
        INSERT INTO users (email, google_user_id) 
        VALUES (%s, %s) 
        ON CONFLICT (email) DO UPDATE SET google_user_id = EXCLUDED.google_user_id
        RETURNING id;
        """
        conn = None
        try:
            conn = self.create_connection()
            cur = conn.cursor()
            cur.execute(insert_query, (email, google_user_id))
            user_id = cur.fetchone()[0]
            conn.commit()
            return user_id
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def save_user_credentials(self, user_id: int, credentials_dict: dict):
        """Save user credentials to database"""
        insert_query = """
        INSERT INTO user_credentials (user_id, access_token, refresh_token, token_expiry, scopes)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
        access_token = EXCLUDED.access_token,
        refresh_token = EXCLUDED.refresh_token,
        token_expiry = EXCLUDED.token_expiry,
        scopes = EXCLUDED.scopes;
        """
        conn = None
        try:
            conn = self.create_connection()
            cur = conn.cursor()
            cur.execute(
                insert_query,
                (
                    user_id,
                    credentials_dict["token"],
                    credentials_dict.get("refresh_token"),
                    credentials_dict.get("expiry"),
                    credentials_dict.get("scopes"),
                ),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Error saving credentials: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def load_credentials(self, user_id: int):
        """Load credential from database"""
        conn = None
        try:
            conn = self.create_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT access_token, refresh_token, token_expiry, scopes FROM user_credentials WHERE user_id = %s",
                (user_id,),
            )
            result = cur.fetchone()
            return result
        except Exception as e:
            logger.error(f"Error loading credentials: {e}")
            return None
        finally:
            if conn:
                conn.close()


def get_email_date(email_detail):
    """Extract date from email headers"""
    try:
        headers = email_detail.get("payload", {}).get("headers", [])
        date_header = next(
            (h["value"] for h in headers if h["name"].lower() == "date"), None
        )
        if date_header:
            return parsedate_to_datetime(date_header)
        else:
            return datetime.now()
    except Exception as e:
        logger.warning(f"Error parsing email date: {e}")
        return datetime.now()


def get_email_sender(email_detail):
    """Extract sender from email headers"""
    headers = email_detail.get("payload", {}).get("headers", [])
    sender = next(
        (h["value"] for h in headers if h["name"].lower() == "from"), "Unknown"
    )
    return sender


def test_connection():
    """Test if database connection works"""
    try:
        db = EmailDatabase()
        conn = db.create_connection()
        if conn:
            print("✅ Database connection successful!")
            conn.close()
            return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False


if __name__ == "__main__":
    test_connection()
