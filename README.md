# StockFlow — Inventory Management MVP

**Wexa AI · Software Developer Intern technical assessment**

A scope-limited, multi-tenant inventory management app, with a browser UI and a FastAPI backend.

## Features

- Email/password signup/login with salted PBKDF2 password hashing and expiring signed bearer tokens.
- Organization creation at signup and server-enforced tenant isolation.
- Product create, list, search, detail, update, stock adjustment, and delete.
- Required product name/SKU and per-organization SKU uniqueness.
- Quantity, optional description/prices, and custom low-stock threshold.
- Dashboard product count, unit totals, and low-stock items.
- Organization default low-stock threshold in Settings.
- Responsive interface, input validation, confirmation dialogs, and error/success feedback.
- 29 automated tests covering authentication, validation, CRUD, threshold behavior, and tenant isolation.
- Postman API collection and GitHub Actions CI.

## Stack

- **Frontend:** HTML, CSS, vanilla JavaScript
- **Backend:** Python, FastAPI, Pydantic
- **Data layer:** SQLAlchemy; SQLite locally and PostgreSQL/MySQL through `DATABASE_URL`
- **Deployment preview:** Render serves the app shell; its configured Supabase Edge API handles persistent demo data.
- **Tests:** pytest + FastAPI TestClient

## Run the FastAPI app locally (Windows PowerShell)

Requires Python 3.11+.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app:app --reload
```

Open http://127.0.0.1:8000. API docs: http://127.0.0.1:8000/api/docs. Health: http://127.0.0.1:8000/api/health.

## Tests

```powershell
pytest -q
node --check script.js
```

The tests use an isolated in-memory database. They do not read or modify any production or ORBIT database.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Health and DB status |
| POST | `/api/auth/signup` | Create owner and organization |
| POST | `/api/auth/login` | Obtain bearer token |
| GET | `/api/me` | Current account/workspace |
| GET / POST | `/api/products` | List/search or create |
| GET / PATCH / DELETE | `/api/products/{product_id}` | Read/update/delete |
| POST | `/api/products/{product_id}/adjust-stock` | Adjust quantity with note |
| GET / PATCH | `/api/settings` | Read/update default threshold |
| GET | `/api/dashboard` | Inventory totals and low-stock list |

Authenticated requests use `Authorization: Bearer <token>`. The backend derives organization ownership from the authenticated user, not from a client-supplied tenant ID.

## Deployment notes

The checked-in Render Blueprint uses the Supabase-backed API mode for the live preview so it can use the existing tenant-isolated API without provisioning or reusing a Render Postgres database. The Python FastAPI mode remains available for a self-hosted deployment: configure a dedicated persistent `DATABASE_URL`, set `STOCKFLOW_API_MODE=fastapi`, and keep `APP_ENV=production` with a generated unique `SECRET_KEY`.

Render free web services use an ephemeral filesystem, and free Render Postgres expires after 30 days. Do not use a local SQLite file for persistent production data on Render. See https://render.com/docs/free for current limitations.

## Out of scope

Staff invites/roles, multi-warehouse support, variants, channel integrations, order management, purchase orders, notifications, CSV imports, billing, advanced reporting, and a detailed stock movement ledger.
