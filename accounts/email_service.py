import resend
from django.conf import settings

resend.api_key = settings.RESEND_API_KEY


def send_verification_otp(email: str, otp: str):
    resend.Emails.send({
        "from": settings.DEFAULT_FROM_EMAIL,
        "to": email,
        "subject": "Verify your email",
        "html": f"""
            <div style="font-family: sans-serif; max-width: 400px; margin: auto;">
                <h2>Email Verification</h2>
                <p>Enter this code to verify your email:</p>
                <h1 style="letter-spacing: 8px; color: #4F46E5;">{otp}</h1>
                <p style="color: #888;">Expires in 10 minutes. Do not share this code.</p>
            </div>
        """
    })


def send_password_reset_otp(email: str, otp: str):
    resend.Emails.send({
        "from": settings.DEFAULT_FROM_EMAIL,
        "to": email,
        "subject": "Password Reset Code",
        "html": f"""
            <div style="font-family: sans-serif; max-width: 400px; margin: auto;">
                <h2>Password Reset</h2>
                <p>Enter this code to reset your password:</p>
                <h1 style="letter-spacing: 8px; color: #4F46E5;">{otp}</h1>
                <p style="color: #888;">Expires in 10 minutes. Ignore if you didn't request this.</p>
            </div>
        """
    })