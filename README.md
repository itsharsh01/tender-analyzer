# Tender Analyzer - Operation Guide

This project is a FastAPI backend for:

- Tender PDF upload and parsing
- Canonical criteria extraction
- Submission upload and evaluation
- Comparison/report download
- Chatbot Q&A over tender + submission context

---

## Frontend Repository

- Frontend repo: [https://github.com/itsharsh01/tender-ui](https://github.com/itsharsh01/tender-ui)
- Frontend README: [https://github.com/itsharsh01/tender-ui/blob/main/README.md](https://github.com/itsharsh01/tender-ui/blob/main/README.md)

---

## 1) Prerequisites

- Python 3.11+ (project also runs on newer versions)
- MongoDB connection string
- Windows/Linux/macOS terminal

Optional but recommended:

- Groq API key (primary LLM)
- OpenRouter API key (fallback if Groq hits rate limits)

---

## 2) Project Setup

From project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## 3) Environment Variables

Create/update `.env` in root using keys below:

```env
APP_NAME=Tender Analyzer API
MONGODB_URI=<your_mongodb_uri>
MONGODB_DB=tender_analyzer
PDF_STORAGE_DIR=storage/tenders

GROQ_API_KEY=<optional_but_recommended>
GROQ_MODEL=llama-3.3-70b-versatile

OPENROUTER_API_KEY=<optional_fallback_key>
OPENROUTER_MODEL=openai/gpt-4.1-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_APP_NAME=tender-analyzer
OPENROUTER_SITE_URL=http://localhost

API_BASE_URL=http://127.0.0.1:8000
CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000,http://localhost:5173

AUTH_MIN_PASSWORD_LENGTH=8
ADMIN_APPROVAL_KEY=<admin_secret>
JWT_SECRET_KEY=<strong_secret>
JWT_ALGORITHM=HS256
JWT_EXP_HOURS=24
REQUEST_TIMEOUT_SECONDS=600
```

Notes:

- `JWT_SECRET_KEY` and `MONGODB_URI` are mandatory.
- If Groq rate-limits, backend auto-fallback uses OpenRouter (if configured).

---

## 4) Run the API

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.api.main:app --reload
```

Swagger:

- <http://127.0.0.1:8000/docs>

Health checks:

- `GET /health`
- `GET /health/db`

---

## 5) Auth Flow (required before protected APIs)

1. `POST /auth/register`
2. Admin approval: `POST /auth/approve/{username}` with header `x-admin-key`
3. `POST /auth/login` -> receive JWT token
4. Send token on all protected calls:
   - `Authorization: Bearer <JWT_TOKEN>`

---

## 6) End-to-End Operating Flow

### A. Tender side

1. Upload tender:
   - `POST /tender/upload` (multipart PDF)
2. Track processing:
   - `GET /tender/{tender_id}/status`
3. Tender details:
   - `GET /tenders`
   - `GET /tenders/{tender_id}/details/meta`
   - `GET /tenders/{tender_id}/details/items`
   - `GET /tenders/{tender_id}/pdf`

### B. Submission side

1. Upload bidder submission:
   - `POST /submission/upload`
2. Check status/report:
   - `GET /submission/{submission_id}/status`
   - `GET /submission/{submission_id}/report`
3. Comparison matrix:
   - `GET /tender/{tender_id}/submissions`
   - `GET /tender/{tender_id}/comparison/summary`
   - `GET /tender/{tender_id}/comparison/filters`
4. Submission detail tabs:
   - `GET /submission/{submission_id}/details/meta`
   - `GET /submission/{submission_id}/details/items`
5. Downloads:
   - `GET /submission/{submission_id}/report/download?format=xlsx|json|pdf`
   - `GET /tender/{tender_id}/report/download?format=xlsx|json`

### C. Chatbot

- `POST /chatbot/query`
  - inputs: `tender_id`, `submission_id`, `query`, `top_k`
  - current response: short plain-English answer only

---

## 7) Where Files Are Stored

Base storage directory: `storage/tenders`

Per tender:

- `storage/tenders/<tender_id>/original.pdf`
- `storage/tenders/<tender_id>/evidence_pool.json`
- `storage/tenders/<tender_id>/canonical.json`

Per submission:

- `storage/tenders/<tender_id>/submissions/<submission_id>/submission.pdf`
- `storage/tenders/<tender_id>/submissions/<submission_id>/evidence_pool.json`
- `storage/tenders/<tender_id>/submissions/<submission_id>/evaluation_report.json`

---

## 8) Common Issues & Quick Fixes

- **`ModuleNotFoundError: openpyxl`**
  - `pip install -r requirements.txt`

- **`ModuleNotFoundError: openai`**
  - `pip install -r requirements.txt`

- **Unauthorized (401)**
  - Missing/expired JWT header

- **Submission upload says no canonical embeddings**
  - Upload/process tender first until status becomes `READY_FOR_SUBMISSIONS`

- **PDF download/report problems**
  - Ensure submission status is `READY` and report exists

---

## 9) Minimal Test Sequence (Manual)

1. Register -> Approve -> Login
2. Upload tender PDF
3. Wait until tender status ready
4. Upload submission PDF
5. Open comparison endpoints
6. Download XLSX report
7. Ask chatbot query

---

If you want, next step is to add a `curl`/Postman collection section to this README for your frontend/dev team.
