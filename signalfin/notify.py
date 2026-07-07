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
    # Bark has payload size limit (~4KB). Split long messages.
    MAX_BODY_LEN = 3500
    if len(content.encode("utf-8")) <= MAX_BODY_LEN:
        return _send_one(server_url, title, content, group)

    # Split by stock blocks (separated by blank lines)
    blocks = content.split("\n\n")
    chunks = []
    current = []
    current_len = 0
    for block in blocks:
        block_len = len(block.encode("utf-8")) + 2  # +2 for \n\n
        if current and current_len + block_len > MAX_BODY_LEN:
            chunks.append("\n\n".join(current))
            current = [block]
            current_len = block_len
        else:
            current.append(block)
            current_len += block_len
    if current:
        chunks.append("\n\n".join(current))

    all_ok = True
    for i, chunk in enumerate(chunks):
        part_title = f"{title} ({i+1}/{len(chunks)})" if len(chunks) > 1 else title
        ok = _send_one(server_url, part_title, chunk, group)
        if not ok:
            all_ok = False
    return all_ok


def _send_one(server_url: str, title: str, content: str,
              group: str) -> bool:
    """Send a single Bark notification."""
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
    try:
        data = resp.json()
    except Exception:
        print(f"Bark error: HTTP {resp.status_code}, body={resp.text[:200]}")
        return False
    if data.get("code") != 200:
        print(f"Bark error: {data}")
        return False
    return True
