import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

logger = logging.getLogger(__name__)


def send_tick_notification(world_state: dict, chronicle: str = ""):
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if webhook_url:
        _send_discord(world_state, webhook_url)

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    digest_email = os.getenv("DIGEST_EMAIL", "").strip()
    if smtp_host and digest_email:
        _send_email(world_state, chronicle)
    elif not webhook_url:
        _log_to_console(world_state)


def _send_discord(world_state: dict, webhook_url: str):
    try:
        events = world_state.get("recent_events", [])[:3]
        event_lines = "\n".join(f"• **{e['region']}** — {e['text']}" for e in events)

        critical = [f for f in world_state.get("faction_morale", []) if f.get("status") in ("Critical", "Declining")]
        faction_lines = "\n".join(f"• **{f['faction']}** [{f['status']}] — {f['reason']}" for f in critical)

        description = f"**{world_state.get('world_date', 'Unknown')}**\n\n"
        if event_lines:
            description += f"**Recent Events**\n{event_lines}\n\n"
        if faction_lines:
            description += f"**Faction Alerts**\n{faction_lines}"

        payload = {
            "embeds": [{
                "title": f"⚔️ Aeloria — Tick {world_state.get('tick', '?')}",
                "description": description,
                "color": 0x8b6fb3,
                "footer": {"text": "The world breathes on..."}
            }]
        }
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Discord notification sent.")
    except Exception as e:
        logger.error(f"Discord notification failed: {e}")


def _send_email(world_state: dict, chronicle: str):
    try:
        subject = f"Aeloria — {world_state.get('world_date', 'Unknown')} — {world_state.get('major_event', 'The world stirs')}"

        events_html = "".join(
            f"<li><strong>{e['region']}</strong> — {e['text']}</li>"
            for e in world_state.get("recent_events", [])[:3]
        )
        morale_html = "".join(
            f"<li><span style='color:{'#c84a4a' if f['status']=='Critical' else '#c87a4a'}'>{f['faction']}</span> [{f['status']}] — {f['reason']}</li>"
            for f in world_state.get("faction_morale", [])
            if f.get("status") in ("Critical", "Declining")
        )
        chronicle_html = f"<p style='font-style:italic;'>{chronicle}</p>" if chronicle else ""

        body = f"""
        <html><body style="background:#08080f;color:#d4d0c8;font-family:Georgia,serif;padding:24px;max-width:680px;">
        <h1 style="color:#c9a84c;font-size:28px;letter-spacing:4px;">AELORIA</h1>
        <h2 style="color:#9b7fd4;font-size:16px;">{world_state.get('world_date','')}</h2>
        {chronicle_html}
        <h3 style="color:#c9a84c;border-bottom:1px solid #2a2a45;padding-bottom:8px;">Recent Events</h3>
        <ul>{events_html}</ul>
        {"<h3 style='color:#c84a4a;'>Faction Alerts</h3><ul>" + morale_html + "</ul>" if morale_html else ""}
        <p style="color:#555;font-size:12px;margin-top:32px;">Tick {world_state.get('tick','?')} — Aeloria Living World</p>
        </body></html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = os.getenv("SMTP_USER", "aeloria@world.sim")
        msg["To"] = os.getenv("DIGEST_EMAIL", "")
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT", "587"))) as server:
            server.starttls()
            server.login(os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASS", ""))
            server.send_message(msg)
        logger.info("Digest email sent.")
    except Exception as e:
        logger.error(f"Email failed: {e}")


def _log_to_console(world_state: dict):
    logger.info(f"=== TICK {world_state.get('tick')} | {world_state.get('world_date')} ===")
    for event in world_state.get("recent_events", [])[:3]:
        if not isinstance(event, dict):
            continue
        region = event.get("region") or event.get("type") or "?"
        text   = event.get("text") or event.get("description") or event.get("summary") or str(event)
        logger.info(f"  [{region}] {text}")
