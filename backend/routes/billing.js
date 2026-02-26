// ═══════════════════════════════════════
// routes/billing.js — Invoice API
// ═══════════════════════════════════════
const express = require('express');
const router  = express.Router();

// GET /api/billing — list invoices
router.get('/', async (req, res) => {
  const { supabase } = req.app.locals;
  const { status, client_id } = req.query;
  let q = supabase
    .from('invoices')
    .select('*, clients(company_name), jobs(job_number)')
    .order('created_at', { ascending: false });
  if (status)    q = q.eq('status', status);
  if (client_id) q = q.eq('client_id', client_id);
  const { data, error } = await q;
  if (error) return res.status(500).json({ error: error.message });
  res.json({ invoices: data });
});

// POST /api/billing — create invoice
router.post('/', async (req, res) => {
  const { supabase } = req.app.locals;
  const {
    client_id, job_id, print_cost, data_cost = 0,
    dispatch_cost = 0, handling_cost = 0, gst_rate = 18
  } = req.body;

  const subtotal     = parseFloat(print_cost) + parseFloat(data_cost) +
                       parseFloat(dispatch_cost) + parseFloat(handling_cost);
  const gst_amount   = (subtotal * gst_rate) / 100;
  const total_amount = subtotal + gst_amount;

  const { count } = await supabase
    .from('invoices')
    .select('*', { count: 'exact', head: true });
  const invoice_number = `INV-${new Date().getFullYear()}-${String((count||0)+1).padStart(5,'0')}`;

  const { data, error } = await supabase
    .from('invoices')
    .insert({
      invoice_number, client_id, job_id,
      print_cost:          parseFloat(print_cost),
      data_processing_cost: parseFloat(data_cost),
      dispatch_cost:        parseFloat(dispatch_cost),
      handling_cost:        parseFloat(handling_cost),
      subtotal, gst_rate, gst_amount, total_amount,
      status: 'draft',
      due_date: new Date(Date.now() + 30*24*60*60*1000).toISOString().slice(0,10)
    })
    .select()
    .single();

  if (error) return res.status(500).json({ error: error.message });
  res.status(201).json({ message: 'Invoice created', invoice: data });
});

// PATCH /api/billing/:id/send — mark invoice as sent
router.patch('/:id/send', async (req, res) => {
  const { supabase } = req.app.locals;
  const { data, error } = await supabase
    .from('invoices')
    .update({ status: 'sent', sent_at: new Date().toISOString() })
    .eq('id', req.params.id)
    .select()
    .single();
  if (error) return res.status(500).json({ error: error.message });
  res.json({ message: 'Invoice marked as sent', invoice: data });
});

// PATCH /api/billing/:id/paid — mark invoice as paid
router.patch('/:id/paid', async (req, res) => {
  const { supabase } = req.app.locals;
  const { data, error } = await supabase
    .from('invoices')
    .update({ status: 'paid', paid_at: new Date().toISOString() })
    .eq('id', req.params.id)
    .select()
    .single();
  if (error) return res.status(500).json({ error: error.message });
  res.json({ message: 'Invoice marked as paid', invoice: data });
});

module.exports = router;
