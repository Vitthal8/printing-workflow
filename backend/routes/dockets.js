// ═══════════════════════════════════════
// routes/dockets.js — Docket API
// ═══════════════════════════════════════
const express = require('express');
const router  = express.Router();

// GET /api/dockets — list all dockets
router.get('/', async (req, res) => {
  const { supabase } = req.app.locals;
  const { limit = 50, offset = 0, job_id } = req.query;
  let q = supabase
    .from('dockets')
    .select('*, jobs(job_number, job_type, clients(company_name))')
    .order('generated_at', { ascending: false })
    .range(offset, offset + limit - 1);
  if (job_id) q = q.eq('job_id', job_id);
  const { data, error } = await q;
  if (error) return res.status(500).json({ error: error.message });
  res.json({ dockets: data });
});

// GET /api/dockets/:number — get docket by number
router.get('/:number', async (req, res) => {
  const { supabase } = req.app.locals;
  const { data, error } = await supabase
    .from('dockets')
    .select('*, jobs(*, clients(*))')
    .eq('docket_number', req.params.number)
    .single();
  if (error) return res.status(404).json({ error: 'Docket not found' });
  res.json(data);
});

// PATCH /api/dockets/:number/void — void a docket
router.patch('/:number/void', async (req, res) => {
  const { supabase } = req.app.locals;
  const { void_reason } = req.body;
  const { data, error } = await supabase
    .from('dockets')
    .update({ is_voided: true, void_reason })
    .eq('docket_number', req.params.number)
    .select()
    .single();
  if (error) return res.status(500).json({ error: error.message });
  res.json({ message: 'Docket voided', docket: data });
});

module.exports = router;
