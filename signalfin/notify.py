"""PushPlus WeChat notification."""

import requests


def send_pushplus(token: str, title: str, content: str) -> bool:
    """Send message via PushPlus API.

    Returns True on success.
    """
    resp = requests.post(
        "http://www.pushplus.plus/send",
        json={
            "token": token,
            "title": title,
            "content": content,
            "template": "markdown",
        },
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 200:
        print(f"PushPlus error: {data}")
        return False
    return True
