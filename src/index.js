import { Command } from 'commander';
import { createClient, initClient, sendMessage, destroyClient } from './client.js';
import { startScheduler, stopScheduler, listSchedules } from './scheduler.js';
import { renderTemplate } from './templates.js';
import logger from './logger.js';
import cron from 'node-cron';

const program = new Command();

program.name('whatsapp-scheduler').description('WhatsApp message scheduler').version('1.0.0');

// ── start: run the scheduler daemon ──
program
  .command('start')
  .description('Start the scheduler daemon')
  .action(async () => {
    logger.info('Starting WhatsApp Scheduler...');

    const client = await createClient();

    // Graceful shutdown
    const shutdown = async (signal) => {
      logger.info(`Received ${signal}, shutting down gracefully...`);
      stopScheduler();
      await destroyClient();
      process.exit(0);
    };
    process.on('SIGTERM', () => shutdown('SIGTERM'));
    process.on('SIGINT', () => shutdown('SIGINT'));

    client.on('ready', () => {
      startScheduler(client);
    });

    await client.initialize();
    logger.info('WhatsApp client initializing... waiting for QR scan or session restore');
  });

// ── send: one-off message ──
program
  .command('send')
  .description('Send a one-off message immediately')
  .requiredOption('--to <number>', 'Recipient phone number (with country code) or group:Name')
  .requiredOption('--msg <message>', 'Message text')
  .action(async (opts) => {
    try {
      const client = await initClient();
      const rendered = renderTemplate(opts.msg);
      await sendMessage(client, opts.to, rendered);
      console.log(`Message sent to ${opts.to}: ${rendered}`);
      await destroyClient();
      process.exit(0);
    } catch (err) {
      logger.error(`Send failed: ${err.message}`);
      await destroyClient();
      process.exit(1);
    }
  });

// ── list: show scheduled jobs ──
program
  .command('list')
  .description('Show all scheduled jobs and next fire times')
  .action(() => {
    const schedules = listSchedules();

    if (schedules.length === 0) {
      console.log('No schedules found.');
      return;
    }

    console.log('\n  Scheduled Messages\n  ' + '─'.repeat(60));

    for (const s of schedules) {
      const status = s.enabled ? '\x1b[32mENABLED\x1b[0m' : '\x1b[90mDISABLED\x1b[0m';
      const preview = s.message.slice(0, 40) + (s.message.length > 40 ? '...' : '');
      const nextRun = getNextCronRun(s.cron);

      console.log(`\n  ${s.id}`);
      console.log(`    Status:   ${status}`);
      console.log(`    To:       ${s.to}`);
      console.log(`    Cron:     ${s.cron}`);
      console.log(`    Next run: ${nextRun}`);
      console.log(`    Message:  "${preview}"`);
    }
    console.log('\n');
  });

// ── status: show connection status ──
program
  .command('status')
  .description('Show connection status and uptime')
  .action(async () => {
    // For status, we just read the saved state file if it exists
    // Since we can't connect to a running daemon easily, show schedule info
    const schedules = listSchedules();
    const enabled = schedules.filter((s) => s.enabled).length;
    const total = schedules.length;

    console.log('\n  WhatsApp Scheduler Status\n  ' + '─'.repeat(40));
    console.log(`  Schedules:  ${enabled} enabled / ${total} total`);
    console.log(`  Config:     schedules.json`);
    console.log(`  Logs:       logs/messages.log`);

    // Check if systemd service is running (Linux only — silently skipped on other platforms)
    try {
      const { execSync } = await import('child_process');
      const result = execSync('systemctl is-active whatsapp-scheduler 2>/dev/null', {
        encoding: 'utf-8',
      }).trim();
      console.log(`  Service:    ${result === 'active' ? '\x1b[32mrunning\x1b[0m' : result}`);
    } catch {
      console.log(`  Service:    not installed or not running`);
    }

    console.log('');
  });

function getNextCronRun(cronExpr) {
  try {
    if (!cron.validate(cronExpr)) return 'invalid cron';

    // Parse cron fields to give a human-readable next-run estimate
    const parts = cronExpr.split(/\s+/);
    const [min, hour, dayMonth, month, dayWeek] = parts;
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

    let desc = '';
    if (dayWeek !== '*') {
      const dayNames = dayWeek.split(',').map((d) => days[parseInt(d)] || d);
      desc += dayNames.join(', ') + ' ';
    } else if (dayMonth !== '*') {
      desc += `Day ${dayMonth} `;
    } else {
      desc += 'Daily ';
    }
    desc += `at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`;
    return desc;
  } catch {
    return 'unknown';
  }
}

program.parse();
