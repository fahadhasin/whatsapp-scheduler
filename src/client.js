import pkg from 'whatsapp-web.js';
const { Client, LocalAuth } = pkg;
import qrcode from 'qrcode-terminal';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import logger from './logger.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

let client = null;
let isReady = false;
let lastMessageSent = null;
const startTime = Date.now();

export function getStatus() {
  return {
    connected: isReady,
    uptime: Date.now() - startTime,
    lastMessageSent,
  };
}

export function setLastMessageSent(info) {
  lastMessageSent = info;
}

export async function createClient() {
  if (client) return client;

  client = new Client({
    authStrategy: new LocalAuth({
      dataPath: join(__dirname, '..', '.wwebjs_auth'),
    }),
    puppeteer: {
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--single-process',
      ],
    },
  });

  client.on('qr', (qr) => {
    logger.info('QR code received — scan with WhatsApp on your phone');
    qrcode.generate(qr, { small: true });
  });

  client.on('authenticated', () => {
    logger.info('WhatsApp authenticated successfully');
  });

  client.on('auth_failure', (msg) => {
    logger.error(`Authentication failed: ${msg}`);
  });

  client.on('ready', () => {
    isReady = true;
    logger.info('WhatsApp client is ready');
  });

  client.on('disconnected', (reason) => {
    isReady = false;
    logger.warn(`WhatsApp disconnected: ${reason}`);
    logger.info('Attempting to reconnect in 10 seconds...');
    setTimeout(() => {
      client.initialize().catch((err) => {
        logger.error(`Reconnect failed: ${err.message}`);
      });
    }, 10_000);
  });

  return client;
}

export async function initClient() {
  const c = await createClient();
  await c.initialize();

  // Wait for ready with timeout
  await new Promise((resolve, reject) => {
    if (isReady) return resolve();
    const timeout = setTimeout(() => reject(new Error('Client ready timeout (60s)')), 60_000);
    c.once('ready', () => {
      clearTimeout(timeout);
      resolve();
    });
  });

  return c;
}

export async function resolveRecipient(client, to) {
  // Group: "group:Group Name"
  if (to.startsWith('group:')) {
    const groupName = to.slice(6).trim();
    const chats = await client.getChats();
    const group = chats.find(
      (chat) => chat.isGroup && chat.name.toLowerCase() === groupName.toLowerCase()
    );
    if (!group) {
      throw new Error(`Group "${groupName}" not found`);
    }
    return group.id._serialized;
  }

  // Individual: phone number → chatId
  const chatId = `${to}@c.us`;
  const isRegistered = await client.isRegisteredUser(chatId);
  if (!isRegistered) {
    throw new Error(`Number ${to} is not registered on WhatsApp`);
  }
  return chatId;
}

export async function sendMessage(client, to, message) {
  const chatId = await resolveRecipient(client, to);
  const result = await client.sendMessage(chatId, message);
  return result;
}

export function destroyClient() {
  if (client) {
    isReady = false;
    return client.destroy();
  }
}
