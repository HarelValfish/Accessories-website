from __future__ import annotations

import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_sns = None


def _get_client():
    global _sns
    if _sns is None:
        _sns = boto3.client(
            "sns",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
    return _sns


def subscribe_phone(phone_number: str) -> str | None:
    """Subscribe a phone in E.164 format. Returns SubscriptionArn or None."""
    topic_arn = os.environ.get("SNS_PRICE_ALERTS_TOPIC_ARN")
    if not topic_arn:
        logger.warning("SNS_PRICE_ALERTS_TOPIC_ARN not set — skipping subscribe")
        return None
    try:
        response = _get_client().subscribe(
            TopicArn=topic_arn,
            Protocol="sms",
            Endpoint=phone_number,
        )
        return response["SubscriptionArn"]
    except ClientError as e:
        logger.error("SNS subscribe failed: %s", e)
        return None


def unsubscribe_phone(subscription_arn: str) -> bool:
    """Unsubscribe using a previously stored SubscriptionArn."""
    if not subscription_arn:
        return False
    try:
        _get_client().unsubscribe(SubscriptionArn=subscription_arn)
        return True
    except ClientError as e:
        logger.error("SNS unsubscribe failed: %s", e)
        return False


def notify_sale(item_name: str, original_price: float, sale_price: float, pct_off: float) -> bool:
    """Publish an SMS announcing a sale on an item."""
    topic_arn = os.environ.get("SNS_PRICE_ALERTS_TOPIC_ARN")
    if not topic_arn:
        logger.warning("SNS_PRICE_ALERTS_TOPIC_ARN not set — skipping notification")
        return False

    domain = os.environ.get("APP_DOMAIN", "")
    message = (
        f"TechDen Sale Alert!\n"
        f"{item_name} is now on sale: "
        f"${original_price:.2f} -> ${sale_price:.2f} ({pct_off:.0f}% off)"
        + (f"\nShop now: {domain}" if domain else "")
    )

    try:
        _get_client().publish(TopicArn=topic_arn, Message=message)
        logger.info("SNS sale alert sent for '%s'", item_name)
        return True
    except ClientError as e:
        logger.error("SNS publish failed: %s", e)
        return False


def notify_price_change(item_name: str, old_price: float, new_price: float) -> bool:
    """Publish an SMS to all topic subscribers announcing a price change."""
    topic_arn = os.environ.get("SNS_PRICE_ALERTS_TOPIC_ARN")
    if not topic_arn:
        logger.warning("SNS_PRICE_ALERTS_TOPIC_ARN not set — skipping notification")
        return False

    direction = "dropped" if new_price < old_price else "changed"
    domain = os.environ.get("APP_DOMAIN", "")
    message = (
        f"TechDen Price Alert!\n"
        f"{item_name} price {direction}: "
        f"${old_price:.2f} -> ${new_price:.2f}"
        + (f"\nShop now: {domain}" if domain else "")
    )

    try:
        _get_client().publish(TopicArn=topic_arn, Message=message)
        logger.info("SNS price alert sent for '%s'", item_name)
        return True
    except ClientError as e:
        logger.error("SNS publish failed: %s", e)
        return False
