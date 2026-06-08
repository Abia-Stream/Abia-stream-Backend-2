from django.core.mail import send_mail
from django.conf import settings


def send_verification_otp(email: str, otp: str):
    send_mail(
        subject='Verify your email',
        message=f'Your verification code is: {otp}\n\nExpires in {settings.OTP_EXPIRY_MINUTES} minutes.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        html_message=f"""
            <div style="font-family: sans-serif; max-width: 400px; margin: auto;">
                <h2>Email Verification</h2>
                <p>Enter this code to verify your email:</p>
                <h1 style="letter-spacing: 8px; color: #4F46E5;">{otp}</h1>
                <p style="color: #888;">Expires in {settings.OTP_EXPIRY_MINUTES} minutes. Do not share this code.</p>
            </div>
        """,
        fail_silently=False,
    )


def send_password_reset_otp(email: str, otp: str):
    send_mail(
        subject='Password Reset Code',
        message=f'Your password reset code is: {otp}\n\nExpires in {settings.OTP_EXPIRY_MINUTES} minutes.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        html_message=f"""
            <div style="font-family: sans-serif; max-width: 400px; margin: auto;">
                <h2>Password Reset</h2>
                <p>Enter this code to reset your password:</p>
                <h1 style="letter-spacing: 8px; color: #4F46E5;">{otp}</h1>
                <p style="color: #888;">Expires in {settings.OTP_EXPIRY_MINUTES} minutes. Ignore if you didn't request this.</p>
            </div>
        """,
        fail_silently=False,
    )