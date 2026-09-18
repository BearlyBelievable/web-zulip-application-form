import requests


def verify_turnstile(secret, token, remote_ip):
    resp = requests.post(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data={
            "secret": secret,
            "response": token,
            "remoteip": remote_ip,
        },
        timeout=5,
    )
    return resp.json().get("success", False)
