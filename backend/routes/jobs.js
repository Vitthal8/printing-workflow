// ═══════════════════════════════════════
// routes/jobs.js — Job CRUD API
// ═══════════════════════════════════════
const express = require('express');
const router  = express.Router();
const { generateJobNumber } = require('../utils/generators');
const { uploadToStorage }   = require('../utils/storage');
const { sendEmail }         = require('../utils/mailer');

// ── GET /api/jobs — list all jobs (with filters) ──────────────
router.get('/', async (req, res) => {
  const { supabase } = req.app.locals;
  const { status, client_id, limit = 50, offset = 0 } = req.query;

  let query = supabase
    .from('jobs')
    .select(`
      *,
      clients ( company_name, contact_name, email )
    `)
    .order('created_at', { ascending: false })
    .range(offset, offset + limit - 1);

  if (status)    query = query.eq('status', status);
  if (client_id) query = query.eq('client_id', client_id);

  const { data, error } = await query;
  if (error) return res.status(500).json({ error: error.message });
  res.json({ jobs: data, count: data.length });
});

// ── GET /api/jobs/:id — get single job ────────────────────────
router.get('/:id', async (req, res) => {
  const { supabase } = req.app.locals;
  const { data, error } = await supabase
    .from('jobs')
    .select(`*, clients(*), dispatches(*), dockets(*)`)
    .eq('id', req.params.id)
    .single();

  if (error) return res.status(404).json({ error: 'Job not found' });
  res.json(data);
});

// ── POST /api/jobs — create new job ──────────────────────────
router.post('/', async (req, res) => {
  const { supabase, upload } = req.app.locals;

  // Handle multipart form (file upload) OR JSON
  upload.fields([
    { name: 'print_file', maxCount: 1 },
    { name: 'data_file',  maxCount: 1 }
  ])(req, res, async (err) => {
    if (err) return res.status(400).json({ error: err.message });

    const {
      client_id, job_type, quantity, pages_per_piece = 1,
      variable_data = false, dispatch_mode,
      fold = false, insert = false, sort = false,
      contact_name, contact_email, notes
    } = req.body;

    // Validate required fields
    if (!client_id || !job_type || !quantity || !dispatch_mode) {
      return res.status(400).json({
        error: 'Missing required fields: client_id, job_type, quantity, dispatch_mode'
      });
    }

    // Generate job number: PRT-YYYY-NNNNN
    const job_number = await generateJobNumber(supabase);

    // Upload print file to Supabase Storage
    let print_file_url = null;
    let data_file_url  = null;

    if (req.files?.print_file?.[0]) {
      print_file_url = await uploadToStorage(
        supabase, req.files.print_file[0], `jobs/${job_number}/print`
      );
    }
    if (req.files?.data_file?.[0]) {
      data_file_url = await uploadToStorage(
        supabase, req.files.data_file[0], `jobs/${job_number}/data`
      );
    }

    // Insert job record
    const { data: job, error } = await supabase
      .from('jobs')
      .insert({
        job_number,
        client_id,
        job_type,
        quantity: parseInt(quantity),
        pages_per_piece: parseInt(pages_per_piece),
        variable_data: variable_data === 'true' || variable_data === true,
        dispatch_mode,
        fold:   fold   === 'true' || fold   === true,
        insert: insert === 'true' || insert === true,
        sort:   sort   === 'true' || sort   === true,
        print_file_url,
        data_file_url,
        contact_name,
        contact_email,
        notes,
        status: 'new',
        received_at: new Date().toISOString()
      })
      .select()
      .single();

    if (error) return res.status(500).json({ error: error.message });

    // Send acknowledgement email to client
    if (contact_email) {
      await sendEmail({
        to:      contact_email,
        subject: `Job ${job_number} Received — PrintFlow Pro`,
        body:    `Dear ${contact_name || 'Team'},\n\nYour print job has been received and registered.\n\nJob Number: ${job_number}\nType: ${job_type}\nQuantity: ${parseInt(quantity).toLocaleString('en-IN')} pieces\n\nWe will begin processing and send you a proof for approval shortly.\n\nRegards,\nPrintFlow Pro Team`
      });
    }

    // Log activity
    await supabase.from('activity_log').insert({
      job_id: job.id,
      action: 'job_created',
      details: `Job ${job_number} created. Client: ${client_id}. Qty: ${quantity}`
    });

    res.status(201).json({ message: 'Job created', job });
  });
});

// ── PATCH /api/jobs/:id/status — update job status ────────────
router.patch('/:id/status', async (req, res) => {
  const { supabase } = req.app.locals;
  const { status, notes } = req.body;

  const VALID_STATUSES = [
    'new','processing','approval','printing',
    'postprint','franking','docket','dispatch','complete','error'
  ];
  if (!VALID_STATUSES.includes(status)) {
    return res.status(400).json({
      error: `Invalid status. Must be one of: ${VALID_STATUSES.join(', ')}`
    });
  }

  const update = { status, updated_at: new Date().toISOString() };
  if (status === 'complete')    update.completed_at = new Date().toISOString();
  if (status === 'approval')    update.proof_sent_at = new Date().toISOString();
  if (notes)                    update.notes = notes;

  const { data, error } = await supabase
    .from('jobs')
    .update(update)
    .eq('id', req.params.id)
    .select()
    .single();

  if (error) return res.status(500).json({ error: error.message });

  // Log status change
  await supabase.from('activity_log').insert({
    job_id: req.params.id,
    action: 'status_changed',
    details: `Status changed to: ${status}`
  });

  res.json({ message: `Status updated to ${status}`, job: data });
});

// ── PATCH /api/jobs/:id/approve — mark client approved ────────
router.patch('/:id/approve', async (req, res) => {
  const { supabase } = req.app.locals;
  const { approved_by, remarks } = req.body;

  const { data, error } = await supabase
    .from('jobs')
    .update({
      status:      'printing',
      approved_at: new Date().toISOString(),
      approved_by: approved_by || 'Client Portal',
      notes:       remarks || null,
      updated_at:  new Date().toISOString()
    })
    .eq('id', req.params.id)
    .select('*, clients(company_name, contact_name, email)')
    .single();

  if (error) return res.status(500).json({ error: error.message });

  // Notify internal team
  await supabase.from('activity_log').insert({
    job_id: req.params.id,
    action: 'client_approved',
    details: `Approved by ${approved_by}. Moving to print production.`
  });

  res.json({ message: 'Job approved. Production started.', job: data });
});

module.exports = router;
