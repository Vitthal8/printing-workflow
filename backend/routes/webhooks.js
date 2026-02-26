// ═══════════════════════════════════════
// routes/webhooks.js — Client approval via email link
// ═══════════════════════════════════════
const express = require('express');
const router  = express.Router();

// POST /api/webhooks/approve?job=JOB_ID&token=TOKEN
router.post('/approve', async (req, res) => {
  const { supabase } = req.app.locals;
  const { job, token } = req.query;
  const { remarks } = req.body;

  if (!job || !token)
    return res.status(400).json({ error: 'Missing job ID or token' });

  const { data: jobData, error } = await supabase
    .from('jobs')
    .select('id, job_number, status, approval_token, clients(contact_name, email)')
    .eq('id', job)
    .single();

  if (error || !jobData)
    return res.status(404).json({ error: 'Job not found' });
  if (jobData.approval_token !== token)
    return res.status(403).json({ error: 'Invalid approval token' });
  if (jobData.status !== 'approval')
    return res.status(400).json({ error: `Job is in '${jobData.status}' status, not pending approval` });

  await supabase.from('jobs').update({
    status: 'printing',
    approved_at: new Date().toISOString(),
    approved_by: jobData.clients?.contact_name || 'Client',
    notes: remarks || null
  }).eq('id', job);

  await supabase.from('activity_log').insert({
    job_id: job,
    action: 'client_approved',
    details: `Approved via email link. Remarks: ${remarks || 'None'}`
  });

  res.json({
    message: 'Job approved. Production will begin shortly.',
    job_number: jobData.job_number
  });
});

// POST /api/webhooks/reject?job=JOB_ID&token=TOKEN
router.post('/reject', async (req, res) => {
  const { supabase } = req.app.locals;
  const { job, token } = req.query;
  const { reason } = req.body;

  const { data: jobData } = await supabase
    .from('jobs').select('*').eq('id', job).single();

  if (!jobData || jobData.approval_token !== token)
    return res.status(403).json({ error: 'Invalid request' });

  await supabase.from('jobs').update({
    status: 'processing',
    notes:  `Revision requested: ${reason}`
  }).eq('id', job);

  await supabase.from('activity_log').insert({
    job_id: job,
    action: 'client_rejected',
    details: `Revision requested: ${reason}`
  });

  res.json({ message: 'Revision request recorded. Team will contact you shortly.' });
});

module.exports = router;
