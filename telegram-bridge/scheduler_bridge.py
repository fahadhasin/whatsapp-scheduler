import json
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Path to the whatsapp-scheduler directory — override via WHATSAPP_SCHEDULER_DIR env var
SCHEDULER_DIR = Path(os.getenv('WHATSAPP_SCHEDULER_DIR', str(Path.home() / 'whatsapp-scheduler')))
SCHEDULES_PATH = SCHEDULER_DIR / 'schedules.json'
SERVICE_NAME = 'whatsapp-scheduler.service'


def read_schedules() -> list:
    if not SCHEDULES_PATH.exists():
        return []
    try:
        return json.loads(SCHEDULES_PATH.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to read schedules.json: {e}")
        return []


def _write_schedules(schedules: list) -> None:
    SCHEDULES_PATH.write_text(json.dumps(schedules, indent=2, ensure_ascii=False), encoding='utf-8')


def restart_service() -> bool:
    """Restart the whatsapp-scheduler service. Returns True on success."""
    try:
        result = subprocess.run(
            ['sudo', 'systemctl', 'restart', SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info(f"Restarted {SERVICE_NAME}")
            return True
        else:
            logger.error(f"Failed to restart {SERVICE_NAME}: {result.stderr.strip()}")
            return False
    except Exception as e:
        logger.error(f"Exception restarting service: {e}")
        return False


def cleanup_expired() -> int:
    """Remove tg-once-* entries whose scheduled date has already passed. Returns count removed."""
    schedules = read_schedules()
    now = datetime.now()
    to_remove = []

    for entry in schedules:
        entry_id = entry.get('id', '')
        if not entry_id.startswith('tg-once-'):
            continue
        target_str = entry.get('_scheduled_at', '')
        if not target_str:
            continue
        try:
            target = datetime.fromisoformat(target_str)
            if target < now:
                to_remove.append(entry_id)
        except ValueError:
            pass

    if to_remove:
        schedules = [s for s in schedules if s.get('id') not in to_remove]
        _write_schedules(schedules)
        logger.info(f"Cleaned up {len(to_remove)} expired one-time schedule(s): {to_remove}")

    return len(to_remove)


def datetime_to_cron(dt: datetime) -> str:
    """Convert a datetime to a cron expression (minute hour day month *)."""
    return f"{dt.minute} {dt.hour} {dt.day} {dt.month} *"


def add_schedule(to: str, message: str, schedule_type: str,
                 dt: datetime | None = None, cron_expr: str | None = None,
                 label: str = '') -> str:
    """
    Add a new schedule entry. Returns the generated ID.
    - schedule_type: 'once' or 'recurring'
    - dt: required for 'once'
    - cron_expr: required for 'recurring'
    """
    cleanup_expired()

    uid = str(int(time.time()))
    if schedule_type == 'once':
        if dt is None:
            raise ValueError("datetime required for one-time schedule")
        cron = datetime_to_cron(dt)
        entry_id = f"tg-once-{uid}"
    else:
        if not cron_expr:
            raise ValueError("cron expression required for recurring schedule")
        cron = cron_expr
        entry_id = f"tg-recur-{uid}"

    entry = {
        'id': entry_id,
        'to': to,
        'message': message,
        'cron': cron,
        'enabled': True,
    }
    if schedule_type == 'once' and dt:
        entry['_scheduled_at'] = dt.isoformat()

    schedules = read_schedules()
    schedules.append(entry)
    _write_schedules(schedules)
    logger.info(f"Added schedule {entry_id}: to={to}, cron={cron}")

    restart_service()
    return entry_id


def remove_schedule(entry_id: str) -> bool:
    """Remove a schedule by ID and restart service. Returns True if found."""
    schedules = read_schedules()
    original_len = len(schedules)
    schedules = [s for s in schedules if s.get('id') != entry_id]
    if len(schedules) == original_len:
        return False
    _write_schedules(schedules)
    restart_service()
    logger.info(f"Removed schedule {entry_id}")
    return True


def list_tg_schedules() -> list:
    """Return all schedules added by this bot (tg-once-* and tg-recur-*)."""
    cleanup_expired()
    schedules = read_schedules()
    return [s for s in schedules if s.get('id', '').startswith('tg-')]
