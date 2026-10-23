# StockFlow — Inventory Management MVP

**Wexa AI · Software Developer Intern technical assessment**

A scope-limited, multi-tenant inventory management app built with Python and a lightweight browser frontend. FastAPI serves the HTML/CSS/JavaScript and JSON API from one service.

## Features

- Signup/login with salted PBKDF2 password hashing and expiring signed bearer tokens.
- Signup creates an organization and a default low-stock setting.
- Server-side organization scoping for all product access.
- Create, list, search, detail, update, delete, and stock-adjust operations.
- Required product name and SKU; SKU unique per organization.
- Optional description/prices and product-specific low-stock threshold.
- Dashboard counts for products and total units, plus low-stock products.
- Settings page for the organization default threshold.
- Input validation, helpful errors, confirmation dialogs, and responsive layout.
- Automated API tests and Postman collection.

## Technology

- **Frontend:** HTML, CSS, vanilla JavaScript
- **Backend:** Python, FastAPI, Pydantic
- **Data:** SQLAlchemy; SQLite locally; PostgreSQL/MySQL through `DATABASE_URL`
- **Tests:** pytest, FastAPI TestClient
- **Deployment:** Render and Docker

## Run locally (Windows PowerShell)

Requires Python 3.11+.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app:app --reload
```

Open http://127.0.0.1:8000. API docs are at http://127.0.0.1:8000/api/docs and health status is at http://127.0.0.1:8000/api/health.

## Tests

```powershell
pytest -q
node --check script.js
```

The suite covers authentication, validation, tenant isolation, product CRUD, search, stock adjustments, dashboard summaries, threshold fallback, static assets, and application security headers.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Health and database connectivity |
| POST | `/api/auth/signup` | Create owner and organization |
| POST | `/api/auth/login` | Obtain bearer token |
| GET | `/api/me` | Current account and organization |
| GET / POST | `/api/products` | List/search or create products |
| GET / PATCH / DELETE | `/api/products/{product_id}` | Read/update/delete one product |
| POST | `/api/products/{product_id}/adjust-stock` | Adjust quantity with a note |
| GET / PATCH | `/api/settings` | Read/update default stock threshold |
| GET | `/api/dashboard` | Inventory totals and low-stock items |

Authenticated requests use `Authorization: Bearer <token>`. Organization IDs are derived from the authenticated account rather than trusted from request payloads.

## Deploy on Render

The supplied `render.yaml` configures a Python web service and requests a persistent external `DATABASE_URL` during Blueprint setup. Use a PostgreSQL/MySQL connection string or update the Blueprint to reference a managed database in your workspace. Never commit database credentials or signing secrets.

**Free-tier note:** Render's free web service has an ephemeral filesystem, and free Render Postgres expires 30 days after creation. Do not rely on a local SQLite file for persisted data on Render; use an appropriately managed persistent database. Check current limits at https://render.com/docs/free.

## Excluded from this MVP

Staff/invites/roles, multiple warehouses, variants, integrations, orders/reservations, purchase orders/suppliers, notifications, CSV import, billing, advanced analytics, and detailed stock movement history.
