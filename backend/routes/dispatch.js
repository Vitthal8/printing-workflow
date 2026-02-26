// ═══════════════════════════════════════
// routes/dispatch.js — Dispatch Entry API
// ═══════════════════════════════════════
const express = require('express');
const router  = express.Router();
const { generateDocketNumber } = require('../utils/generators');
const { sendEmail }            = require('../utils/mailer');

// ── POST /api/dispatch — record dispatch + generate docket ───
router.post('/', async (req, res) => {
  const { supabase } = req.app.locals;
  const {
    job_id, dispatch_mode, piece_count,
    fold_done = false, insert_done = false,
    sort_done = false,
    frank_amount, frank_confirmed, franked_at,
    tracking_reference, operator_id, dispatch_date
  } = req.body;

  // Validate required
  if (!job_id || !dispatch_mode || !piece_count || !frank_amount) {
    return res.status(400).json({
      error: 'Missing required: job_id, dispatch_mode, piece_count, frank_amount'
    });
  }

  // ── CRITICAL BUSINESS RULE ───────────────────────────────
  // Docket number is ONLY generated AFTER franking is confirmed
  if (!frank_confirmed || frank_confirmed === 'false') {
    return res.status(400).json({
      error: 'Franking must be confirmed before a docket can be generated.',
      rule:  'POST-PRINT → FRANK → DOCKET → DISPATCH'
    });
  }

  // Generate docket number AFTER franking confirmation
  const docket_number = await generateDocketNumber(supabase);

  // Create dispatch record
  const { data: dispatch, error: dErr } = await supabase
    .from('dispatches')
    .insert({
      job_id,
      dispatch_mode,
      piece_count: parseInt(piece_count),
      fold_done:   fold_done   === 'true' || fold_done   === true,
      insert_done: insert_done === 'true' || insert_done === true,
      sort_done:   sort_done   === 'true' || sort_done   === true,
      frank_amount: parseFloat(frank_amount),
      frank_confirmed: true,
      franked_at:  franked_at || new Date().toISOString(),
      tracking_reference,
      operator_id,
      dispatched_at: dispatch_date || new Date().toISOString(),
      delivery_status: 'pending'
    })
    .select()
    .single();

  if (dErr) return res.status(500).json({ error: dErr.message });

  // Create docket record (only possible because franking is confirmed)
  const { data: docket, error: docErr } = await supabase
    .from('dockets')
    .insert({
      docket_number,
      job_id,
      dispatch_id:   dispatch.id,
      total_pieces:  parseInt(piece_count),
      dispatch_mode,
      frank_amount:  parseFloat(frank_amount),
      franked_at:    franked_at || new Date().toISOString(),
      generated_at:  new Date().toISOString()
    })
    .select()
    .single();

  if (docErr) return res.status(500).json({ error: docErr.message });

  // Update dispatch record with docket reference
  await supabase
    .from('dispatches')
    .update({ docket_id: docket.id })
    .eq('id', dispatch.id);

  // Update job status to 'dispatch'
  await supabase
    .from('jobs')
    .update({ status: 'dispatch', updated_at: new Date().toISOString() })
    .eq('id', job_id);

  // Fetch job + client for notification
  const { data: job } = await supabase
    .from('jobs')
    .select('*, clients(company_name, contact_name, email)')
    .eq('id', job_id)
    .single();

  // Notify client about dispatch
  if (job?.clients?.email) {
    await sendEmail({
      to:      job.clients.email,
      subject: `Your Print Job Has Been Dispatched — Docket ${docket_number}`,
      body:    `Dear ${job.clients.contact_name},\n\nYour print job (${job.job_number}) has been dispatched.\n\nDocket Number: ${docket_number}\nDispatch Mode: ${dispatch_mode}\nTotal Pieces: ${parseInt(piece_count).toLocaleString('en-IN')}\nFrank Amount: ₹${parseFloat(frank_amount).toLocaleString('en-IN')}\n${tracking_reference ? 'Tracking Reference: ' + tracking_reference + '\n' : ''}\nDispatch Date: ${new Date().toLocaleDateString('en-IN')}\n\nRegards,\nPrintFlow Pro Team`
    });
  }

  // Log activity
  await supabase.from('activity_log').insert({
    job_id,
    action: 'dispatched',
    details: `Docket ${docket_number} generated. ${piece_count} pieces via ${dispatch_mode}. Frank: ₹${frank_amount}`
  });

  res.status(201).json({
    message:       'Dispatch recorded and docket generated',
    docket_number,
    dispatch,
    docket
  });
});

module.exports = router;
