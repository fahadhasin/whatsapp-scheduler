import json
import logging
import re
import urllib.request
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)

OLLAMA_URL = 'http://localhost:11434/api/generate'
OLLAMA_MODEL = 'llama3.2:1b'


def _next_weekday(weekday: int) -> date:
    """Return the next occurrence of weekday (0=Mon … 6=Sun), at least tomorrow."""
    today = date.today()
    days_ahead = weekday - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def _build_prompt(user_text: str) -> str:
    today = datetime.now()
    tomorrow = (today + timedelta(days=1)).strftime('%Y-%m-%d')
    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    next_days = {name: _next_weekday(i).strftime('%Y-%m-%d') for i, name in enumerate(day_names)}

    return f"""Extract WhatsApp scheduling details from the request below.

Today: {today.strftime('%Y-%m-%d %A')}. Time: {today.strftime('%H:%M')}.
Dates: tomorrow={tomorrow}, {', '.join(f'{k}={v}' for k, v in next_days.items())}.

Output JSON with exactly these fields:
- recipient: name of person or group (string)
- message: the WhatsApp message text to send (string)
- datetime: ISO date+time for one-time sends e.g. "2026-02-27T09:00:00". Empty string if recurring.
- cron: 5-field cron for repeating e.g. "0 9 * * 1". Empty string if one-time.
- type: "once" or "recurring"

Request: {user_text}"""


def _ask_ollama(prompt: str) -> str:
    payload = json.dumps({
        'model': OLLAMA_MODEL,
        'prompt': prompt,
        'stream': False,
        'format': 'json',
        'keep_alive': '30m',
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data.get('response', '').strip()


def _parse_response(raw: str) -> dict | None:
    """Multi-stage JSON extraction handling llama3.2 quirks."""
    # Stage 1: direct parse
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    # Stage 2: strip markdown code fences
    stripped = re.sub(r'```(?:json)?\s*', '', raw).strip().rstrip('`').strip()
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass

    # Stage 3: extract first { ... } block
    match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            pass

    # Stage 4: manual key extraction via regex
    result = {}
    for key in ['recipient', 'message', 'datetime', 'cron', 'type']:
        m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', raw)
        if m:
            result[key] = m.group(1)
    return result if result else None


def parse(user_text: str) -> dict | None:
    """
    Parse a natural language scheduling request.
    Returns dict with keys: recipient, message, datetime, cron, type
    or None if parsing fails.
    """
    try:
        prompt = _build_prompt(user_text)
        raw = _ask_ollama(prompt)
        logger.info(f"Ollama raw response: {raw[:200]}")
        result = _parse_response(raw)
        if result:
            # Validate required fields
            if not result.get('recipient') or not result.get('message'):
                logger.warning(f"Parsed result missing required fields: {result}")
                return None
            if result.get('type') not in ('once', 'recurring'):
                result['type'] = 'once'
            result.setdefault('cron', '')
            result.setdefault('datetime', '')
        return result
    except Exception as e:
        logger.error(f"NLP parse failed: {e}")
        return None
