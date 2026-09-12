import logging
import os

import httpx

from ..models import Alert, Machine

logger = logging.getLogger(__name__)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")


def discord_payload(alert: Alert, machine: Machine) -> dict:
    return {
        "username": "PulseWatch",
        "embeds": [{
            "title": "PulseWatch alert",
            "description": alert.message,
            "color": 15158332 if alert.severity == "critical" else 15105570,
            "fields": [
                {"name": "Machine", "value": machine.name, "inline": True},
                {"name": "Severity", "value": alert.severity.upper(), "inline": True},
                {"name": "State", "value": alert.state.upper(), "inline": True},
            ],
        }],
    }


async def notify_discord(alert: Alert, machine: Machine) -> bool:
    if not DISCORD_WEBHOOK_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(DISCORD_WEBHOOK_URL, json=discord_payload(alert, machine))
            response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("discord_notification_failed alert_id=%s machine_id=%s", alert.id, machine.id)
        return False
    logger.info("discord_notification_sent alert_id=%s machine_id=%s", alert.id, machine.id)
    return True
