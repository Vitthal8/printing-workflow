// ═══════════════════════════════════════════════════════════
// PrintFlow Pro — Backend API Server
// Stack: Node.js + Express + Supabase
// Deploy: Render.com (free tier)
// ═══════════════════════════════════════════════════════════

require('dotenv').config();
const express    = require('express');
const cors       = require('cors');
const multer     = require('multer');
const path       = require('path');
const { createClient } = require('@supabase/supabase-js');

const app  = express();
const PORT = process.env.PORT || 3000;

// ── Supabase client ──────────────────────────────────────────
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_KEY   // service key for server-side ops
);

// ── Middleware ───────────────────────────────────────────────
app.use(cors({
  origin: [
    'https://vitthal8.github.io',
    'http://localhost:5500',
    'http://127.0.0.1:5500'
  ]
}));
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ── File upload config (temp storage before Supabase upload) ─
const storage = multer.diskStorage({
  destination: '/tmp/printflow-uploads/',
  filename: (req, file, cb) => {
    const unique = Date.now() + '-' + Math.round(Math.random() * 1e6);
    cb(null, unique + path.extname(file.originalname));
  }
});
const upload = multer({
  storage,
  limits: { fileSize: 50 * 1024 * 1024 },          // 50MB max
  fileFilter: (req, file, cb) => {
    const allowed = ['.pdf', '.xlsx', '.xls', '.csv'];
    const ext = path.extname(file.originalname).toLowerCase();
    if (allowed.includes(ext)) cb(null, true);
    else cb(new Error(`File type ${ext} not allowed`));
  }
});

// ── Route imports ────────────────────────────────────────────
const jobsRouter     = require('./routes/jobs');
const dispatchRouter = require('./routes/dispatch');
const docketRouter   = require('./routes/dockets');
const billingRouter  = require('./routes/billing');
const webhookRouter  = require('./routes/webhooks');
const notifyRouter   = require('./routes/notifications');

// ── Attach supabase + upload to all routes via app.locals ────
app.locals.supabase = supabase;
app.locals.upload   = upload;

// ── Mount routes ─────────────────────────────────────────────
app.use('/api/jobs',          jobsRouter);
app.use('/api/dispatch',      dispatchRouter);
app.use('/api/dockets',       docketRouter);
app.use('/api/billing',       billingRouter);
app.use('/api/webhooks',      webhookRouter);
app.use('/api/notifications', notifyRouter);

// ── Health check ─────────────────────────────────────────────
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    service: 'PrintFlow Pro API',
    version: '1.0.0',
    timestamp: new Date().toISOString()
  });
});

// ── 404 handler ──────────────────────────────────────────────
app.use((req, res) => {
  res.status(404).json({ error: 'Route not found', path: req.path });
});

// ── Global error handler ─────────────────────────────────────
app.use((err, req, res, next) => {
  console.error('[ERROR]', err.message);
  res.status(err.status || 500).json({
    error: err.message || 'Internal server error'
  });
});

// ── Start ────────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log(`✓ PrintFlow API running on port ${PORT}`);
  console.log(`  Health: http://localhost:${PORT}/health`);
});
