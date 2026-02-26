// ═══════════════════════════════════════
// routes/notifications.js — Email notifications
// ═══════════════════════════════════════
const express     = require('express');
const router      = express.Router();
const crypto      = require('crypto');
const { sendEmail } = require('../utils/mailer');

// POST /api/notifications/send-proof
router.post('/send-proof', async (req, res) => {
  const { supabase } = req.app.locals;
  const { job_id } = req.body;

  const { data: job } = await supabase
    .from('jobs')
    .select('*, clients(company_name, contact_name, email)')
    .eq('id', job_id)
    .single();

  if (!job) return res.status(404).json({ error: 'Job not found' });

  const token   = crypto.randomBytes(32).toString('hex');
  const baseUrl = process.env.FRONTEND_URL || 'https://vitthal8.github.io/printing-workflow';
  const apiUrl  = process.env.API_URL       || 'https://printing-api.onrender.com';

  await supabase.from('jobs').update({
    approval_token: token,
    status:         'approval',
    proof_sent_at:  new Date().toISOString()
  }).eq('id', job_id);

  const approveUrl = `${baseUrl}/portal/?job=${job_id}&token=${token}&action=approve`;
  const rejectUrl  = `${apiUrl}/api/webhooks/reject?job=${job_id}&token=${token}`;

  await sendEmail({
    to:      job.clients.email,
    subject: `Proof Ready for Approval — Job ${job.job_number}`,
    body: `Dear ${job.clients.contact_name},

Your print proof is ready for review.

Job:      ${job.job_number}
Type:     ${job.job_type}
Quantity: ${job.quantity.toLocaleString('en-IN')} pieces
Mode:     ${job.dispatch_mode}

✅ APPROVE (start production):
${approveUrl}

❌ REQUEST CHANGES:
${rejectUrl}

This link expires in 48 hours.

Regards,
PrintFlow Pro Team`
  });

  res.json({
    message:    'Proof sent to client',
    email:      job.clients.email,
    job_number: job.job_number
  });
});

// POST /api/notifications/dispatch-alert
router.post('/dispatch-alert', async (req, res) => {
  const { supabase } = req.app.locals;
  const { job_id, docket_number } = req.body;

  const { data: job } = await supabase
    .from('jobs')
    .select('*, clients(company_name, contact_name, email), dockets(*)')
    .eq('id', job_id)
    .single();

  if (!job) return res.status(404).json({ error: 'Job not found' });

  await sendEmail({
    to:      job.clients.email,
    subject: `Your Job Has Been Dispatched — Docket ${docket_number}`,
    body: `Dear ${job.clients.contact_name},

Your print job has been dispatched.

Job Number:    ${job.job_number}
Docket Number: ${docket_number}
Pieces:        ${job.quantity.toLocaleString('en-IN')}
Dispatch Mode: ${job.dispatch_mode}
Date:          ${new Date().toLocaleDateString('en-IN')}

Track your job at: ${process.env.FRONTEND_URL}/portal/

Regards,
PrintFlow Pro Team`
  });

  res.json({ message: 'Dispatch alert sent', email: job.clients.email });
});

module.exports = router;
