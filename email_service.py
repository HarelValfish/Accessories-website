"""
email_service.py
────────────────
Email sending utilities for user verification and order confirmations.
Starts with mock mode (console output) for development.
Can be upgraded to real email sending via Flask-Mail.
"""

import os
from flask import request


# ══════════════════════════════════════════════════════════════════════════════
#  EMAIL SENDING (MOCK MODE)
# ══════════════════════════════════════════════════════════════════════════════

def send_verification_email(email: str, token: str):
    """
    Send email verification link to user.
    Currently in mock mode — prints to console instead of sending.
    """
    # Build verification URL
    verification_url = f"{request.url_root}verify-email/{token}"

    # Mock email (prints to console)
    print("\n" + "="*80)
    print("📧 VERIFICATION EMAIL (MOCK MODE)")
    print("="*80)
    print(f"To: {email}")
    print(f"Subject: Verify your TechDen account")
    print(f"\nClick the link below to verify your email address:")
    print(f"\n    {verification_url}")
    print(f"\nThis link expires in 24 hours.")
    print("="*80 + "\n")

    # TODO: Replace with real email sending using Flask-Mail
    # from flask_mail import Message, current_app
    # msg = Message(
    #     subject="Verify your TechDen account",
    #     recipients=[email],
    #     html=f"<p>Click <a href='{verification_url}'>here</a> to verify your email.</p>"
    # )
    # current_app.extensions['mail'].send(msg)


def send_order_confirmation(email: str, order):
    """
    Send order confirmation email to user.
    Currently in mock mode — prints to console instead of sending.
    """
    # Mock email (prints to console)
    print("\n" + "="*80)
    print("📧 ORDER CONFIRMATION EMAIL (MOCK MODE)")
    print("="*80)
    print(f"To: {email}")
    print(f"Subject: Order Confirmation - {order['order_number']}")
    print(f"\nOrder Number: {order['order_number']}")
    print(f"Total: ${order['total']:.2f}")
    print(f"Status: {order['status']}")
    print(f"\nItems:")
    for item in order["items"]:
        print(f"  - {item['name']} x{item['quantity']} = ${item['price'] * item['quantity']:.2f}")
    print("\nThank you for your order!")
    print("="*80 + "\n")

    # TODO: Replace with real email sending using Flask-Mail
