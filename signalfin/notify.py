"""Bark iOS push notification."""

import requests


def send_bark(server_url: str, title: str, content: str,
              group: str = "signalfin") -> bool:
    """Send notification via Bark.

    Args:
        server_url: Bark server URL with device key,
                    e.g. 'https://api.day.app/YOUR_KEY'
        title: notification title
        content: notification body
        group: notification group for iOS grouping

    Returns True on success.
    """
    resp = requests.post(
        f"{server_url.rstrip('/')}/",
        json={
            "title": title,
            "body": content,
            "group": group,
            "level": "timeSensitive",
            "isArchive": 1,
        },
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 200:
        print(f"Bark error: {data}")
        return False
    return True
