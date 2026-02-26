// ═══════════════════════════════════════
// utils/mailer.js — Nodemailer email sender
// ═══════════════════════════════════════
const nodemailer = require('nodemailer');

const transporter = nodemailer.createTransport({
  service: 'gmail',
  auth: {
    user: process.env.SMTP_USER,   // jobs@printflowpro.in
    pass: process.env.SMTP_PASS    // Gmail App Password (16 chars, NOT login password)
  }
});

/**
 * Send a plain-text or HTML email.
 * Email failures are logged but do NOT throw — workflow continues.
 */
async function sendEmail({ to, subject, body, html }) {
  const mailOptions = {
    from:    `"PrintFlow Pro" <${process.env.SMTP_USER}>`,
    to,
    subject,
    text:    body,
    html:    html || body.replace(/\n/g, '<br/>')
  };
  try {
    const info = await transporter.sendMail(mailOptions);
    console.log(`✓ Email sent to ${to}: ${info.messageId}`);
    return info;
  } catch (err) {
    console.error(`✗ Email failed to ${to}:`, err.message);
    return null;
  }
}

/**
 * Send to multiple recipients via BCC.
 */
async function sendBulkEmail({ recipients, subject, body }) {
  return sendEmail({
    to:   process.env.SMTP_USER,
    subject,
    body,
    html: `<p>${body.replace(/\n/g,'<br/>')}</p><p><small>Recipients: ${recipients.join(', ')}</small></p>`
  });
}

module.exports = { sendEmail, sendBulkEmail };
