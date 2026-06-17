/**
 * Twilio SMS + SendGrid email with simulated fallback and DB audit log.
 */
const https = require('https');

function twilioEnabled() {
  return Boolean(
    process.env.TWILIO_ACCOUNT_SID &&
    process.env.TWILIO_AUTH_TOKEN &&
    process.env.TWILIO_FROM_NUMBER
  );
}

function sendgridEnabled() {
  return Boolean(process.env.SENDGRID_API_KEY && process.env.SENDGRID_FROM_EMAIL);
}

function normalizePhone(phone) {
  const digits = String(phone || '').replace(/\D/g, '');
  if (digits.length === 10) return '+1' + digits;
  if (digits.length === 11 && digits.startsWith('1')) return '+' + digits;
  if (String(phone || '').startsWith('+')) return String(phone).trim();
  return digits ? '+' + digits : '';
}

async function logNotification(pool, row) {
  if (!pool) return;
  try {
    await pool.query(
      `INSERT INTO notification_log (channel, recipient, message, provider_ref, trip_id, status)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [
        row.channel,
        row.recipient,
        (row.message || '').slice(0, 2000),
        row.provider_ref || null,
        row.trip_id || null,
        row.status || 'sent',
      ]
    );
  } catch (_) {}
}

function twilioRequest(path, body) {
  const sid = process.env.TWILIO_ACCOUNT_SID;
  const token = process.env.TWILIO_AUTH_TOKEN;
  const auth = Buffer.from(`${sid}:${token}`).toString('base64');
  const payload = new URLSearchParams(body).toString();

  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        hostname: 'api.twilio.com',
        path: `/2010-04-01/Accounts/${sid}${path}`,
        method: 'POST',
        headers: {
          Authorization: `Basic ${auth}`,
          'Content-Type': 'application/x-www-form-urlencoded',
          'Content-Length': Buffer.byteLength(payload),
        },
      },
      (res) => {
        let data = '';
        res.on('data', (chunk) => { data += chunk; });
        res.on('end', () => {
          if (res.statusCode >= 400) reject(new Error(data || 'Twilio error'));
          else resolve(JSON.parse(data || '{}'));
        });
      }
    );
    req.on('error', reject);
    req.write(payload);
    req.end();
  });
}

async function sendSms(pool, { to, message, tripId }) {
  const recipient = normalizePhone(to);
  if (!recipient) throw new Error('Valid phone number required');
  const body = String(message || '').trim();
  if (!body) throw new Error('Message required');

  if (twilioEnabled()) {
    const result = await twilioRequest('/Messages.json', {
      To: recipient,
      From: process.env.TWILIO_FROM_NUMBER,
      Body: body,
    });
    await logNotification(pool, {
      channel: 'sms',
      recipient,
      message: body,
      provider_ref: result.sid,
      trip_id: tripId,
      status: 'sent',
    });
    return { ok: true, provider: 'twilio', reference: result.sid };
  }

  const reference = `sim_sms_${Date.now()}`;
  await logNotification(pool, {
    channel: 'sms',
    recipient,
    message: body,
    provider_ref: reference,
    trip_id: tripId,
    status: 'simulated',
  });
  return { ok: true, provider: 'simulated', reference };
}

async function sendEmail(pool, { to, subject, html, tripId }) {
  const recipient = String(to || '').trim();
  if (!recipient.includes('@')) throw new Error('Valid email required');

  if (sendgridEnabled()) {
    const payload = JSON.stringify({
      personalizations: [{ to: [{ email: recipient }] }],
      from: { email: process.env.SENDGRID_FROM_EMAIL, name: process.env.SENDGRID_FROM_NAME || 'Amicor Nova' },
      subject: subject || 'Amicor Nova Invoice',
      content: [{ type: 'text/html', value: html }],
    });

    await new Promise((resolve, reject) => {
      const req = https.request(
        {
          hostname: 'api.sendgrid.com',
          path: '/v3/mail/send',
          method: 'POST',
          headers: {
            Authorization: `Bearer ${process.env.SENDGRID_API_KEY}`,
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(payload),
          },
        },
        (res) => {
          if (res.statusCode >= 400) {
            let data = '';
            res.on('data', (c) => { data += c; });
            res.on('end', () => reject(new Error(data || 'SendGrid error')));
          } else resolve();
        }
      );
      req.on('error', reject);
      req.write(payload);
      req.end();
    });

    const reference = `sg_${Date.now()}`;
    await logNotification(pool, {
      channel: 'email',
      recipient,
      message: subject,
      provider_ref: reference,
      trip_id: tripId,
      status: 'sent',
    });
    return { ok: true, provider: 'sendgrid', reference };
  }

  const reference = `sim_email_${Date.now()}`;
  await logNotification(pool, {
    channel: 'email',
    recipient,
    message: subject,
    provider_ref: reference,
    trip_id: tripId,
    status: 'simulated',
  });
  return { ok: true, provider: 'simulated', reference };
}

function buildInvoiceHtml(trip, patient, payment) {
  const amount = trip.actual_fare || trip.estimated_fare || 0;
  return `
    <h2>Amicor Nova Transport Invoice</h2>
    <p>Trip ID: ${trip.id}</p>
    <p>Patient: ${patient?.name || 'N/A'}</p>
    <p>Route: ${trip.pickup} → ${trip.dropoff}</p>
    <p>Service: ${trip.type || 'medical'}</p>
    <p>Amount due: $${Number(amount).toFixed(2)}</p>
    <p>Payment reference: ${payment?.stripe_payment_id || 'pending'}</p>
    <p>Thank you for choosing Amicor Nova medical transportation.</p>
  `;
}

module.exports = {
  sendSms,
  sendEmail,
  buildInvoiceHtml,
  twilioEnabled,
  sendgridEnabled,
};
