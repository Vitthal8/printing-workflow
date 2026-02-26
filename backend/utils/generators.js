// ═══════════════════════════════════════
// utils/generators.js — Auto-number generators
// ═══════════════════════════════════════

/**
 * Generate unique job number: PRT-YYYY-NNNNN
 * Requires this Postgres function in Supabase SQL Editor:
 *   CREATE SEQUENCE IF NOT EXISTS job_seq START 1;
 *   CREATE OR REPLACE FUNCTION next_job_number()
 *   RETURNS integer LANGUAGE sql AS $$ SELECT nextval('job_seq')::integer $$;
 */
async function generateJobNumber(supabase) {
  const year = new Date().getFullYear();
  try {
    const { data } = await supabase.rpc('next_job_number');
    const seq = data || Math.floor(Math.random() * 99999);
    return `PRT-${year}-${String(seq).padStart(5, '0')}`;
  } catch {
    // Fallback if RPC not set up yet
    const { count } = await supabase.from('jobs').select('*', { count: 'exact', head: true });
    return `PRT-${year}-${String((count||0)+1).padStart(5,'0')}`;
  }
}

/**
 * Generate unique docket number: DKT-YYYYMMDD-XXXX
 * Sequential counter per day — resets each day
 */
async function generateDocketNumber(supabase) {
  const today   = new Date();
  const dateStr = today.getFullYear().toString() +
                  String(today.getMonth() + 1).padStart(2, '0') +
                  String(today.getDate()).padStart(2, '0');

  const startOfDay = new Date(today.setHours(0, 0, 0, 0)).toISOString();
  const { count } = await supabase
    .from('dockets')
    .select('*', { count: 'exact', head: true })
    .gte('generated_at', startOfDay);

  const seq = String((count || 0) + 1).padStart(4, '0');
  return `DKT-${dateStr}-${seq}`;
}

/**
 * Generate invoice number: INV-YYYY-NNNNN
 */
async function generateInvoiceNumber(supabase) {
  const year = new Date().getFullYear();
  const { count } = await supabase
    .from('invoices')
    .select('*', { count: 'exact', head: true });
  return `INV-${year}-${String((count || 0) + 1).padStart(5, '0')}`;
}

module.exports = { generateJobNumber, generateDocketNumber, generateInvoiceNumber };
