"""
email_service.py
────────────────
Email sending utilities for user verification and order confirmations.
"""

from flask import current_app, request
from flask_mail import Mail, Message


def _mail() -> Mail:
    return current_app.extensions["mail"]


def send_verification_email(email: str, token: str):
    verification_url = f"{request.url_root}verify-email/{token}"

    msg = Message(
        subject="Verify your TechDen account",
        recipients=[email],
        html=f"""
        <div style="font-family:sans-serif;max-width:480px;margin:auto">
          <h2 style="color:#ff6a00">Welcome to TechDen!</h2>
          <p>Click the button below to verify your email address.</p>
          <a href="{verification_url}"
             style="display:inline-block;padding:12px 24px;background:#ff6a00;
                    color:#fff;text-decoration:none;border-radius:8px;font-weight:600">
            Verify my email
          </a>
          <p style="color:#888;font-size:0.85rem;margin-top:1.5rem">
            This link expires in 24 hours. If you didn't create an account, ignore this email.
          </p>
        </div>
        """,
    )
    _mail().send(msg)


def send_order_confirmation(email: str, order: dict):
    items_html = "".join(
        f"<tr>"
        f"<td style='padding:6px 12px'>{item['name']}</td>"
        f"<td style='padding:6px 12px;text-align:center'>×{item['quantity']}</td>"
        f"<td style='padding:6px 12px;text-align:right'>${item['price'] * item['quantity']:.2f}</td>"
        f"</tr>"
        for item in order["items"]
    )

    msg = Message(
        subject=f"Order Confirmed — {order['order_number']}",
        recipients=[email],
        html=f"""
        <div style="font-family:sans-serif;max-width:520px;margin:auto">
          <h2 style="color:#ff6a00">Order Confirmed!</h2>
          <p>Thanks for your order. Here's your summary:</p>
          <p><strong>Order #:</strong> {order['order_number']}</p>
          <table style="width:100%;border-collapse:collapse;margin:1rem 0">
            <thead>
              <tr style="background:#f5f5f5">
                <th style="padding:6px 12px;text-align:left">Item</th>
                <th style="padding:6px 12px">Qty</th>
                <th style="padding:6px 12px;text-align:right">Price</th>
              </tr>
            </thead>
            <tbody>{items_html}</tbody>
            <tfoot>
              <tr>
                <td colspan="2" style="padding:8px 12px;font-weight:600">Total</td>
                <td style="padding:8px 12px;text-align:right;font-weight:600">${order['total']:.2f}</td>
              </tr>
            </tfoot>
          </table>
          <p style="color:#888;font-size:0.85rem">Thank you for shopping at TechDen!</p>
        </div>
        """,
    )
    _mail().send(msg)
