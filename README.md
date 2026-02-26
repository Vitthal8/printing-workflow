# PrintFlow Pro 🖨️

Complete print workflow management system — 5 phases.

## Live URLs (after deploy)
| Page | URL |
|---|---|
| Website | `vitthal8.github.io/printing-workflow/` |
| Staff Dashboard | `vitthal8.github.io/printing-workflow/dashboard/` |
| Client Portal | `vitthal8.github.io/printing-workflow/portal/` |
| MIS Reports | `vitthal8.github.io/printing-workflow/reports/` |
| API Health | `your-api.onrender.com/health` |

## Quick Start (local)
```bash
# HTML pages — just open in browser:
python3 -m http.server 8000

# Backend API:
cd backend && npm install && cp .env.example .env
# fill in .env values, then:
node server.js

# Python scripts:
cd automation && pip install -r requirements.txt
python3 pdf_validator.py yourfile.pdf
python3 excel_processor.py data.xlsx 14820
```

## Structure
```
printing-workflow/
├── index.html              Phase 1 — Public website
├── dashboard/index.html    Phase 2 — Staff dashboard
├── portal/index.html       Phase 4 — Client portal
├── reports/index.html      Phase 5 — MIS reports
├── exports/                Excel MIS reports
├── backend/                Phase 3 — Node.js API
│   ├── server.js
│   ├── routes/             6 route modules
│   └── utils/              generators, storage, mailer
├── automation/             Phase 3 — Python scripts
│   ├── email_parser.py
│   ├── pdf_validator.py
│   └── excel_processor.py
└── .github/workflows/      GitHub Actions cron
    └── automation.yml
```

## Critical Business Rule
Docket number is generated **ONLY after franking is confirmed**.
Enforced at 3 levels: Dashboard UI → API → Database.

## Deploy
1. **Supabase**: Create project, run SQL schema from setup-guide.html
2. **Render.com**: Connect GitHub repo, root=`backend`, `node server.js`
3. **GitHub Pages**: Settings → Pages → Branch: main → / (root)
4. **GitHub Actions**: Add secrets (SUPABASE_URL, SMTP_USER, SMTP_PASS, etc.)
