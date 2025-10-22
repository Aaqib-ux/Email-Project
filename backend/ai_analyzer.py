from openai import OpenAI
import os
import base64
import logging
import asyncio
from dotenv import load_dotenv
from typing import List, Dict

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure OpenAI client for OpenRouter
# Ensure OPENROUTER_API_KEY is in your .env file
try:
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1", api_key=os.getenv("OPENROUTER_API_KEY")
    )
    api_key = os.getenv("OPENROUTER_API_KEY")
    if api_key:
        print(f"AI Client ready. Using OpenRouter key prefix: {api_key[:10]}...")
    else:
        raise ValueError("OPENROUTER_API_KEY not found in environment variables")
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}")
    raise

# Define predefined labels (using set for faster lookup)
PREDEFINED_LABELS = {"Support", "Sales", "Urgent", "General"}


def get_email_body(email_detail: Dict[str, any]) -> str:
    """Extracts the plain text body from email details."""
    try:
        payload = email_detail.get("payload", {})
        body_data = ""

        if "parts" in payload:
            # Multi-part email
            body_data = _extract_from_parts(payload["parts"])
        else:
            # Simple message
            body_data = payload.get("body", {}).get("data", "")

        if body_data:
            try:
                decoded_body = base64.urlsafe_b64decode(body_data).decode("utf-8")
                return decoded_body
            except (base64.binascii.Error, UnicodeDecodeError) as e:
                logger.warning(f"Failed to decode email body: {e}")
                return "Failed to decode email body"
        else:
            return "[No plain text body found]"

    except Exception as e:
        logger.error(f"Unexpected error extracting email body: {e}")
        return "[Failed to extract email body]"


def _extract_from_parts(parts: List[Dict]) -> str:
    """Helper function to extract text from email parts recursively."""
    for part in parts:
        if part.get("mimeType") == "text/plain" and "data" in part.get("body", {}):
            return part["body"]["data"]
        elif "parts" in part:
            # Recursively check nested parts
            result = _extract_from_parts(part["parts"])
            if result:
                return result
    return ""


def get_email_subject(email_detail: Dict[str, any]) -> str:
    """Extract subject from email headers."""
    headers = email_detail.get("payload", {}).get("headers", [])
    return next(
        (h["value"] for h in headers if h["name"].lower() == "subject"), "No Subject"
    )


async def analyze_email_content(subject: str, body: str) -> List[str]:
    """
    Analyze email content using OpenRouter API and return categorized labels.
    """
    # Prepare the prompt
    prompt = f"""
You are an expert email categorization assistant. Analyze the following email and categorize it using ONLY these predefined labels: {', '.join(PREDEFINED_LABELS)}

RULES:
1. Use ONLY labels from the provided list: {', '.join(PREDEFINED_LABELS)}
2. You can assign multiple labels if they apply (e.g., "Support, Urgent")
3. If the email doesn't fit any specific category, use "General"
4. Consider urgency indicators like "ASAP", "urgent", "immediate", etc.
5. Sales emails include promotions, offers, product pitches
6. Support emails include help requests, complaints, technical issues
7. Respond with ONLY the label(s), separated by commas

Email Subject: {subject}

Email Body: {body[:2000]}...
"""

    try:
        logger.info(f"Analyzing email with subject: '{subject[:50]}...'")

        # Make API call to OpenRouter
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",  # Using a more reliable model
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise email categorization assistant. Follow the rules exactly and only return the specified labels.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=50,  # Reduced since we only need labels
            temperature=0.1,  # Lower temperature for more consistent results
        )

        ai_response = response.choices[0].message.content.strip()
        logger.info(f"AI response: '{ai_response}'")

        if ai_response:
            # Parse and validate labels
            suggested_labels = [label.strip() for label in ai_response.split(",")]
            valid_labels = [
                label for label in suggested_labels if label in PREDEFINED_LABELS
            ]

            if valid_labels:
                logger.info(f"Valid labels assigned: {valid_labels}")
                return valid_labels
            else:
                logger.warning(
                    f"AI returned invalid labels: {suggested_labels}. Defaulting to 'General'"
                )
                return ["General"]
        else:
            logger.warning("AI returned empty response. Defaulting to 'General'")
            return ["General"]

    except Exception as e:
        logger.error(f"Error during AI analysis: {e}")
        return ["General"]


def get_sender_email(email_detail: Dict[str, any]) -> str:
    """Extract sender email from headers."""
    headers = email_detail.get("payload", {}).get("headers", [])
    sender = next(
        (h["value"] for h in headers if h["name"].lower() == "from"), "Unknown Sender"
    )
    return sender


async def process_email(email_detail: Dict[str, any]) -> Dict[str, any]:
    """
    Process a single email and return categorization results.
    """
    subject = get_email_subject(email_detail)
    body = get_email_body(email_detail)
    sender = get_sender_email(email_detail)

    # Analyze content
    labels = await analyze_email_content(subject, body)

    return {
        "subject": subject,
        "sender": sender,
        "labels": labels,
        "body_preview": body[:200] + "..." if len(body) > 200 else body,
    }


async def main():
    """Example usage of the email classifier."""
    # Example email data structure (similar to Gmail API response)
    sample_email = {
        "payload": {
            "headers": [
                {"name": "Subject", "value": "URGENT: Account Payment Issue"},
                {"name": "From", "value": "support@example.com"},
            ],
            "body": {
                "data": base64.urlsafe_b64encode(
                    "Hello, we noticed an issue with your recent payment. Please contact us immediately to resolve this matter.".encode()
                ).decode()
            },
        }
    }

    result = await process_email(sample_email)
    print("Email Classification Result:")
    print(f"Subject: {result['subject']}")
    print(f"Sender: {result['sender']}")
    print(f"Labels: {result['labels']}")
    print(f"Preview: {result['body_preview']}")


if __name__ == "__main__":
    asyncio.run(main())
