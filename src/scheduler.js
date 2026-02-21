import cron from 'node-cron';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { sendMessage, setLastMessageSent } from './client.js';
import { renderTemplate } from './templates.js';
import logger from './logger.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SCHEDULES_PATH = join(__dirname, '..', 'schedules.json');
const MAX_RETRIES = 3;

const activeJobs = [];

function loadSchedules() {
  const raw = readFileSync(SCHEDULES_PATH, 'utf-8');
  return JSON.parse(raw);
}

async function sendWithRetry(client, to, message, retries = MAX_RETRIES) {
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const result = await sendMessage(client, to, message);
      return result;
    } catch (err) {
      if (attempt === retries) throw err;
      const delay = Math.pow(2, attempt) * 1000; // attempt 1 fails → wait 2s, attempt 2 fails → wait 4s, attempt 3 fails → give up
      logger.warn(
        `Send failed (attempt ${attempt}/${retries}): ${err.message}. Retrying in ${delay / 1000}s...`
      );
      await new Promise((r) => setTimeout(r, delay));
    }
  }
}

export function startScheduler(client) {
  const schedules = loadSchedules();
  const enabled = schedules.filter((s) => s.enabled);

  if (enabled.length === 0) {
    logger.warn('No enabled schedules found in schedules.json');
    return;
  }

  for (const schedule of enabled) {
    if (!cron.validate(schedule.cron)) {
      logger.error(`Invalid cron expression for "${schedule.id}": ${schedule.cron}`);
      continue;
    }

    const job = cron.schedule(schedule.cron, async () => {
      const renderedMessage = renderTemplate(schedule.message);
      const preview = renderedMessage.slice(0, 50) + (renderedMessage.length > 50 ? '...' : '');

      logger.info(`Firing scheduled message "${schedule.id}" to ${schedule.to}`);

      try {
        await sendWithRetry(client, schedule.to, renderedMessage);
        const sentInfo = {
          timestamp: new Date().toISOString(),
          to: schedule.to,
          scheduleId: schedule.id,
        };
        setLastMessageSent(sentInfo);
        logger.info(`Sent "${schedule.id}" to ${schedule.to}: ${preview}`);
      } catch (err) {
        logger.error(`Failed to send "${schedule.id}" to ${schedule.to}: ${err.message}`);
      }
    });

    activeJobs.push({ schedule, job });
    logger.info(`Scheduled "${schedule.id}" — cron: ${schedule.cron}`);
  }

  logger.info(`${activeJobs.length} schedule(s) active`);
}

export function getActiveJobs() {
  return activeJobs;
}

export function listSchedules() {
  return loadSchedules();
}

export function stopScheduler() {
  for (const { job } of activeJobs) {
    job.stop();
  }
  activeJobs.length = 0;
}
