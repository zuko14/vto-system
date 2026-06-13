"""
ZukoLabs VTO — Privacy Policy Page

DPDP-compliant privacy policy served as an HTML page.
Linked in the WhatsApp consent message.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>ZukoLabs VTO - Privacy Policy</title></head>
    <body style="font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px;">
        <h1>Privacy Policy</h1>
        <p><strong>Last updated:</strong> June 2026</p>

        <h2>1. Data We Collect</h2>
        <p>We collect your WhatsApp phone number (stored as a hash), photos you send for virtual try-on, and your consent timestamp.</p>

        <h2>2. How We Use Your Data</h2>
        <p>Your photos are used solely to generate virtual try-on images. They are never used for training AI models or shared with third parties.</p>

        <h2>3. Data Retention</h2>
        <p>Selfie photos are deleted immediately after try-on generation. Output images are deleted after 48 hours.</p>

        <h2>4. Your Rights</h2>
        <p>You can request deletion of all your data at any time by sending DELETE to our WhatsApp bot. We will process your request within 5 seconds.</p>

        <h2>5. Contact</h2>
        <p>For privacy concerns, contact us at: zukolabs14@gmail.com</p>
    </body>
    </html>
    """
