import requests


def chat_with_openrouter(api_key: str, url: str, model_name: str, messages: list, timeout: int = 60) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name,
        "messages": messages,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as e:
        print("OpenRouter request failed:", str(e))
        raise RuntimeError("LLM request failed")

    if resp.status_code != 200:
        print(f"OpenRouter provider error: status={resp.status_code}")
        raise RuntimeError("LLM provider error")

    data = resp.json()

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Invalid response format from OpenRouter")
