import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Path to the whatsapp-scheduler directory — override via WHATSAPP_SCHEDULER_DIR env var
SCHEDULER_DIR = Path(os.getenv('WHATSAPP_SCHEDULER_DIR', str(Path.home() / 'whatsapp-scheduler')))
CONTACTS_PATH = SCHEDULER_DIR / 'contacts.json'


def _load() -> dict:
    if CONTACTS_PATH.exists():
        try:
            return json.loads(CONTACTS_PATH.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to read contacts: {e}")
    return {}


def _save(contacts: dict) -> None:
    CONTACTS_PATH.write_text(json.dumps(contacts, indent=2, ensure_ascii=False), encoding='utf-8')


def resolve(name: str) -> str | None:
    """Return phone number / group:Name for a contact, or None if not found."""
    return _load().get(name.strip().lower())


def add(name: str, number: str) -> None:
    """Add or update a contact. Name is stored lowercase."""
    contacts = _load()
    contacts[name.strip().lower()] = number.strip()
    _save(contacts)


def remove(name: str) -> bool:
    """Remove a contact. Returns True if it existed."""
    contacts = _load()
    key = name.strip().lower()
    if key in contacts:
        del contacts[key]
        _save(contacts)
        return True
    return False


def list_all() -> dict:
    """Return all contacts (lowercase keys)."""
    return _load()
