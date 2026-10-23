from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import Base, app, get_db


@pytest.fixture(autouse=True)
def isolate_application_startup(monkeypatch):
    @asynccontextmanager
    async def no_startup(_application):
        yield
    monkeypatch.setattr(app.router, "lifespan_context", no_startup)


@pytest.fixture()
def client():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_sessions = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = test_sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def signup(client, email="owner@example.com", org="Northstar Store"):
    response = client.post("/api/auth/signup", json={
        "email": email,
        "password": "correct-horse-123",
        "organization_name": org,
    })
    assert response.status_code == 201, response.text
    data = response.json()
    return data["access_token"], data["user"]


def auth(token):
    return {"Authorization": "Bearer " + token}


def make_product(client, token, **overrides):
    payload = {
        "name": "Organic Green Tea",
        "sku": "TEA-001",
        "quantity_on_hand": 3,
        "cost_price": 80,
        "selling_price": 125,
    }
    payload.update(overrides)
    response = client.post("/api/products", headers=auth(token), json=payload)
    assert response.status_code == 201, response.text
    return response.json()["item"]


def test_signup_login_me_and_passwords_are_not_returned(client):
    token, user = signup(client)
    assert user["email"] == "owner@example.com"
    assert user["organization_name"] == "Northstar Store"
    assert "password" not in user and "password_hash" not in user
    assert client.get("/api/me", headers=auth(token)).json()["user"]["id"] == user["id"]
    login = client.post("/api/auth/login", json={"email": "OWNER@example.com", "password": "correct-horse-123"})
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_duplicate_email_is_rejected(client):
    signup(client)
    response = client.post("/api/auth/signup", json={
        "email": "OWNER@example.com", "password": "another-password-456", "organization_name": "Other",
    })
    assert response.status_code == 409


def test_login_rejects_wrong_password_and_missing_auth_is_blocked(client):
    signup(client)
    wrong = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "wrong-password"})
    assert wrong.status_code == 401
    assert client.get("/api/products").status_code == 401


def test_product_crud_dashboard_and_low_stock(client):
    token, _ = signup(client)
    item = make_product(client, token)
    assert item["sku"] == "TEA-001"
    assert item["effective_low_stock_threshold"] == 5
    assert item["is_low_stock"] is True

    dashboard = client.get("/api/dashboard", headers=auth(token)).json()
    assert dashboard["total_products"] == 1
    assert dashboard["total_units"] == 3
    assert dashboard["low_stock_count"] == 1
    low_item = dashboard["low_stock_items"][0]
    assert low_item["name"] == "Organic Green Tea"
    assert low_item["sku"] == "TEA-001"
    assert low_item["quantity_on_hand"] == 3
    assert low_item["effective_low_stock_threshold"] == 5
    assert low_item["is_low_stock"] is True

    updated = client.patch("/api/products/" + str(item["id"]), headers=auth(token), json={"quantity_on_hand": 20})
    assert updated.status_code == 200
    assert updated.json()["item"]["is_low_stock"] is False
    assert client.get("/api/products/" + str(item["id"]), headers=auth(token)).status_code == 200
    assert client.delete("/api/products/" + str(item["id"]), headers=auth(token)).status_code == 204
    assert client.get("/api/products", headers=auth(token)).json()["count"] == 0


def test_products_can_share_sku_across_organizations_but_not_within_one(client):
    token_a, _ = signup(client, "owner-a@example.com", "Store A")
    token_b, _ = signup(client, "owner-b@example.com", "Store B")
    make_product(client, token_a, sku="COMMON-1")
    duplicate = client.post("/api/products", headers=auth(token_a), json={
        "name": "Duplicate", "sku": "common-1", "quantity_on_hand": 1,
    })
    assert duplicate.status_code == 409
    allowed = client.post("/api/products", headers=auth(token_b), json={
        "name": "Different tenant", "sku": "COMMON-1", "quantity_on_hand": 2,
    })
    assert allowed.status_code == 201


def test_tenant_isolation_for_listing_detail_update_and_delete(client):
    token_a, user_a = signup(client, "tenant-a@example.com", "Tenant A")
    token_b, user_b = signup(client, "tenant-b@example.com", "Tenant B")
    item = make_product(client, token_a)
    assert user_a["organization_id"] != user_b["organization_id"]
    assert client.get("/api/products", headers=auth(token_b)).json()["count"] == 0
    path = "/api/products/" + str(item["id"])
    assert client.get(path, headers=auth(token_b)).status_code == 404
    assert client.patch(path, headers=auth(token_b), json={"quantity_on_hand": 999}).status_code == 404
    assert client.delete(path, headers=auth(token_b)).status_code == 404
    assert client.get(path, headers=auth(token_a)).json()["item"]["quantity_on_hand"] == 3

    spoof_create = client.post("/api/products", headers=auth(token_b), json={
        "name": "Spoofed tenant product", "sku": "SPOOF-1", "quantity_on_hand": 1,
        "organization_id": user_a["organization_id"], "last_updated_by": user_a["id"],
    })
    assert spoof_create.status_code == 422
    spoof_update = client.patch(path, headers=auth(token_a), json={
        "organization_id": user_b["organization_id"], "last_updated_by": user_b["id"],
    })
    assert spoof_update.status_code == 422


def test_search_matches_name_and_sku_case_insensitively(client):
    token, _ = signup(client)
    make_product(client, token, name="Copper Water Bottle", sku="HOME-BOT-01", quantity_on_hand=14)
    make_product(client, token, name="Cotton Tote Bag", sku="BAG-42", quantity_on_hand=8)
    by_name = client.get("/api/products?q=water", headers=auth(token)).json()
    assert [item["sku"] for item in by_name["items"]] == ["HOME-BOT-01"]
    by_sku = client.get("/api/products?q=bag-42", headers=auth(token)).json()
    assert [item["name"] for item in by_sku["items"]] == ["Cotton Tote Bag"]

    make_product(client, token, name="fooXbar", sku="WILD-01", quantity_on_hand=1)
    underscore = client.get("/api/products?q=foo_bar", headers=auth(token)).json()
    percent = client.get("/api/products?q=foo%25bar", headers=auth(token)).json()
    assert underscore["count"] == 0
    assert percent["count"] == 0


def test_default_and_product_specific_thresholds(client):
    token, _ = signup(client)
    headers = auth(token)
    defaulted = make_product(client, token, name="Default item", sku="DEFAULT-1", quantity_on_hand=4)
    custom = make_product(client, token, name="Custom item", sku="CUSTOM-1", quantity_on_hand=4, low_stock_threshold=2)
    assert defaulted["is_low_stock"] is True
    assert custom["is_low_stock"] is False
    saved = client.patch("/api/settings", headers=headers, json={"default_low_stock_threshold": 2})
    assert saved.status_code == 200
    items = {p["sku"]: p for p in client.get("/api/products", headers=headers).json()["items"]}
    assert items["DEFAULT-1"]["is_low_stock"] is False
    assert items["CUSTOM-1"]["effective_low_stock_threshold"] == 2


def test_settings_are_scoped_to_each_organization(client):
    token_a, _ = signup(client, "settings-a@example.com", "Store A")
    token_b, _ = signup(client, "settings-b@example.com", "Store B")
    client.patch("/api/settings", headers=auth(token_a), json={"default_low_stock_threshold": 9})
    assert client.get("/api/settings", headers=auth(token_a)).json()["default_low_stock_threshold"] == 9
    assert client.get("/api/settings", headers=auth(token_b)).json()["default_low_stock_threshold"] == 5


def test_stock_adjustment_records_latest_note_and_rejects_negative_result(client):
    token, _ = signup(client)
    item = make_product(client, token, quantity_on_hand=10)
    path = "/api/products/" + str(item["id"]) + "/adjust-stock"
    response = client.post(path, headers=auth(token), json={"delta": 7, "note": "Delivery received"})
    assert response.status_code == 200
    assert response.json()["item"]["quantity_on_hand"] == 17
    assert response.json()["item"]["last_stock_note"] == "Delivery received"
    invalid = client.post(path, headers=auth(token), json={"delta": -99, "note": "Too much"})
    assert invalid.status_code == 422
    zero = client.post(path, headers=auth(token), json={"delta": 0, "note": "No change"})
    assert zero.status_code == 422
    short_note = client.post(path, headers=auth(token), json={"delta": 1, "note": "ok"})
    assert short_note.status_code == 422
    assert client.get("/api/products/" + str(item["id"]), headers=auth(token)).json()["item"]["quantity_on_hand"] == 17


def test_stock_adjustment_cannot_cross_tenant_boundary(client):
    token_a, _ = signup(client, "adjust-a@example.com", "Store A")
    token_b, _ = signup(client, "adjust-b@example.com", "Store B")
    item = make_product(client, token_a)
    result = client.post("/api/products/" + str(item["id"]) + "/adjust-stock", headers=auth(token_b),
                         json={"delta": 5, "note": "Cross-tenant attempt"})
    assert result.status_code == 404


def test_validation_rejects_bad_product_values_and_does_not_echo_secret(client):
    token, _ = signup(client)
    invalid = client.post("/api/products", headers=auth(token), json={
        "name": "Invalid quantity", "sku": "BAD-1", "quantity_on_hand": -1,
    })
    assert invalid.status_code == 422
    bad_email = client.post("/api/auth/signup", json={
        "email": "not-an-email", "password": "correct-horse-123", "organization_name": "Store",
    })
    assert bad_email.status_code == 422

    blank_signup_password = client.post("/api/auth/signup", json={
        "email": "blank-password@example.com", "password": "        ", "organization_name": "Store",
    })
    assert blank_signup_password.status_code == 422
    blank_login_password = client.post("/api/auth/login", json={
        "email": "owner@example.com", "password": "   ",
    })
    assert blank_login_password.status_code == 422

    too_long = "sensitive-secret-value" * 8
    bad_login = client.post("/api/auth/login", json={"email": "owner@example.com", "password": too_long})
    assert bad_login.status_code == 422
    assert too_long not in bad_login.text

    boolean_quantity = client.post("/api/products", headers=auth(token), json={
        "name": "Boolean quantity", "sku": "BOOL-1", "quantity_on_hand": True,
    })
    assert boolean_quantity.status_code == 422
    boolean_price = client.post("/api/products", headers=auth(token), json={
        "name": "Boolean price", "sku": "BOOL-PRICE-1", "quantity_on_hand": 1, "cost_price": True,
    })
    assert boolean_price.status_code == 422

    item = make_product(client, token, sku="STRICT-1", quantity_on_hand=4)
    assert client.patch(
        "/api/products/" + str(item["id"]), headers=auth(token),
        json={"quantity_on_hand": True},
    ).status_code == 422
    assert client.patch(
        "/api/products/" + str(item["id"]), headers=auth(token),
        json={"selling_price": True},
    ).status_code == 422
    assert client.patch(
        "/api/products/" + str(item["id"]), headers=auth(token),
        json={"low_stock_threshold": True},
    ).status_code == 422
    assert client.patch(
        "/api/settings", headers=auth(token),
        json={"default_low_stock_threshold": True},
    ).status_code == 422
    assert client.post(
        "/api/products/" + str(item["id"]) + "/adjust-stock", headers=auth(token),
        json={"delta": True, "note": "Invalid boolean"},
    ).status_code == 422


def test_health_static_files_and_security_headers(client):
    assert client.get("/api/health").json() == {"status": "ok", "service": "stockflow", "database": "ok"}
    home = client.get("/")
    assert home.status_code == 200 and "StockFlow" in home.text
    assert client.get("/style.css").status_code == 200
    js = client.get("/script.js")
    assert js.status_code == 200
    assert "function renderDashboard" in js.text
    assert "stock-adjust-form" in js.text
    assert 'aria-label="Adjust stock for ' in js.text
    assert 'aria-label="Edit ' in js.text
    assert 'aria-label="Delete ' in js.text
    assert "load-sample-data" in js.text
    headers = client.get("/").headers
    assert headers["x-frame-options"] == "DENY"
    assert headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in headers["content-security-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert client.get("/api/health").headers["cache-control"] == "no-store"

    docs = client.get("/api/docs")
    assert docs.status_code == 200
    assert "SwaggerUIBundle" in docs.text
    assert "content-security-policy" not in docs.headers


def test_theme_controls_and_search_have_no_command_k_hint(client):
    html = client.get("/").text
    assert 'href="./"' in html
    assert 'id="marketing-view" class="marketing-shell"' in html
    assert 'id="marketing-nav"' in html
    assert 'href="#features"' in html
    assert 'href="#workflow"' in html
    assert 'href="#preview"' in html
    assert 'href="#faq"' in html
    assert 'id="auth-view" class="auth-view hidden"' in html
    assert 'data-action="demo-access"' in html
    assert 'href="style.css?v=wexa-frontend-v1"' in html
    assert 'src="script.js?v=wexa-frontend-v1" defer' in html
    assert 'id="theme-toggle"' in html
    assert 'id="auth-theme-toggle"' in html
    assert 'id="mobile-menu-button"' in html
    assert 'aria-controls="sidebar"' in html
    assert 'aria-expanded="false"' in html
    assert 'id="page-content"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-busy="false"' in html
    assert 'placeholder="Search products..."' in html
    assert 'id="global-search-input"' in html
    assert 'maxlength="120"' in html
    assert "⌘ K" not in html
    css = client.get("/style.css").text
    assert 'data-theme="dark"' in css
    js = client.get("/script.js").text
    assert "function applyTheme(theme, persist = false)" in js
    assert 'name="stockflow-api-base-url"' not in html
    assert 'name="stockflow-api-key"' not in html
    assert 'meta[name="stockflow-api-base-url"]' in js
    assert 'meta[name="stockflow-api-key"]' in js
    assert "headers.set('apikey', API_PUBLIC_KEY)" in js
    assert "const requestUrl = API_BASE_URL && isApiRequest ? API_BASE_URL + path : path;" in js
    assert "fetch(requestUrl, { ...options, headers })" in js
    assert "function openDemoWorkspace()" in js
    assert "api('/api/auth/demo'" in js
    assert 'data-action="demo-access"' in js
    assert "apiError.status = response.status" in js
    # Authentication failures must remain in the requested form; demo access is explicit.
    assert "catch (demoError)" not in js
    assert "if ([401, 409, 422].includes(error.status))" not in js
    assert "if ([409, 422].includes(error.status))" not in js
    assert "Passwords do not match." in js
    assert "Password must be at least 8 characters." in js
    assert "stockflow_theme" in js
    assert "function renderAuth(mode, error = '', values = {})" in js
    assert "escapeHtml(values.organization_name || '')" in js
    assert "escapeHtml(values.email || '')" in js
    assert "renderAuth('login', error.message, { email: String(values.get('email') || '').trim() })" in js
    assert "renderAuth('signup', error.message, authValues)" in js
    assert "escapeHtml(values.password" not in js
    assert 'aria-labelledby="stock-adjust-modal-title"' in js
    assert 'id="stock-adjust-modal-title"' in js
    assert 'aria-labelledby="delete-product-modal-title"' in js
    assert 'id="delete-product-modal-title"' in js
    assert "modalTrigger = document.activeElement" in js
    assert "event.key !== 'Tab'" in js
    assert "modalRoot.contains(document.activeElement)" in js
    assert "trigger.focus()" in js
    assert "setAttribute('aria-expanded', 'true')" in js
    assert "setAttribute('aria-expanded', 'false')" in js
    assert "setAttribute('aria-label', 'Close navigation')" in js
    assert "setAttribute('aria-label', 'Open navigation')" in js
    assert "if ($('#sidebar').classList.contains('sidebar-open')) closeSidebar();" in js
    assert "else openSidebar();" in js
    assert "setAttribute('aria-busy', 'true')" in js
    assert "setAttribute('aria-busy', 'false')" in js
    assert "if (state.page !== 'products') return;" not in js
    assert "window.clearTimeout(state.searchTimer)" in js
    assert "renderPage('products')" in js
    assert "renderSequence: 0" in js
    assert js.count("if (renderId !== state.renderSequence) return;") >= 3
    assert "await renderProducts(state.query, renderId)" in js
    assert "await renderSettings(renderId)" in js
    assert "key.toLowerCase() === 'k'" not in js


def test_workspace_section_artwork_and_button_wiring(client):
    html = client.get('/').text
    assert 'href="#dashboard" data-page="dashboard"' in html
    assert 'style.css?v=wexa-frontend-v1' in html
    assert 'script.js?v=wexa-frontend-v1' in html

    css = client.get('/style.css').text
    assert '.section-head-dashboard::before' in css
    assert '.section-head-products::before' in css
    assert '.section-head-settings::before' in css
    assert css.count('https://images.unsplash.com/') >= 3
    assert 'prefers-reduced-motion: reduce' in css

    js = client.get('/script.js').text
    assert "section-head-' + view" in js
    assert "form.dataset.productId ? 'Save changes' : 'Create product'" in js
    assert "if (target.tagName === 'A') event.preventDefault();" in js
    assert "if (target.id === 'marketing-theme-toggle') { toggleTheme(); return; }" in js
    assert "$('#marketing-theme-toggle').addEventListener('click', toggleTheme);" not in js
    assert "$('#theme-toggle').addEventListener('click', toggleTheme);" in js
    actions = (
        'backdrop-close', 'clear-search', 'close-modal', 'confirm-delete',
        'delete-product', 'demo-access', 'edit-product', 'load-sample-data',
        'new-product', 'retry-page', 'review-low-stock', 'stock-adjust',
    )
    for action in actions:
        assert "action === '" + action + "'" in js, f'Missing click handler for {action}'
    for form_id in ('login-form', 'signup-form', 'product-form', 'stock-adjust-form', 'settings-form'):
        assert 'form.id === ' + repr(form_id) in js, f'Missing submit handler for {form_id}'

def test_tampered_and_expired_tokens_are_rejected(client, monkeypatch):
    import time
    import auth

    token, _ = signup(client)
    version, payload, signature = token.split(".")
    replacement = ("A" if signature[-1] != "A" else "B")
    tampered = version + "." + payload + "." + signature[:-1] + replacement
    assert client.get("/api/me", headers=auth_header(tampered)).status_code == 401

    # A legitimately signed token becomes invalid once its expiry is in the past.
    monkeypatch.setattr(auth, "TOKEN_TTL_HOURS", 1)
    token, _ = signup(client, "expiry@example.com", "Expiry Test Store")
    current_time = time.time()
    monkeypatch.setattr(auth.time, "time", lambda: current_time + 7200)
    assert client.get("/api/me", headers=auth_header(token)).status_code == 401


def auth_header(token):
    return {"Authorization": "Bearer " + token}


def test_update_rejects_null_required_fields_and_duplicate_sku(client):
    token, _ = signup(client)
    first = make_product(client, token, name="First item", sku="SKU-1")
    second = make_product(client, token, name="Second item", sku="SKU-2")
    url = "/api/products/" + str(first["id"])
    assert client.patch(url, headers=auth(token), json={"quantity_on_hand": None}).status_code == 422
    assert client.patch(url, headers=auth(token), json={"name": None}).status_code == 422
    assert client.patch(url, headers=auth(token), json={}).status_code == 422
    assert client.patch("/api/products/" + str(second["id"]), headers=auth(token), json={"sku": "SKU-1"}).status_code == 409


def test_threshold_equality_zero_quantity_and_empty_threshold(client):
    token, _ = signup(client)
    headers = auth(token)
    make_product(client, token, name="At threshold", sku="EQUAL-1", quantity_on_hand=5)
    make_product(client, token, name="Zero stock", sku="ZERO-1", quantity_on_hand=0)
    make_product(client, token, name="Custom threshold", sku="CUSTOM-7", quantity_on_hand=3, low_stock_threshold=2)
    response = client.get("/api/dashboard", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_products"] == 3
    assert data["total_units"] == 8
    assert data["low_stock_count"] == 2
    by_sku = {item["sku"]: item for item in client.get("/api/products", headers=headers).json()["items"]}
    assert by_sku["EQUAL-1"]["is_low_stock"] is True
    assert by_sku["ZERO-1"]["is_low_stock"] is True
    assert by_sku["CUSTOM-7"]["is_low_stock"] is False


def test_production_startup_rejects_placeholder_secret_key():
    import os
    import subprocess
    import sys

    environment = os.environ.copy()
    environment.update({
        "APP_ENV": "production",
        "SECRET_KEY": "replace-with-a-unique-random-secret-at-least-32-characters",
        "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/stockflow",
    })
    result = subprocess.run(
        [sys.executable, "-c", "import auth"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "Production requires a unique SECRET_KEY" in result.stderr


def test_clearing_product_threshold_falls_back_to_workspace_default(client):
    token, _ = signup(client)
    headers = auth(token)
    item = make_product(
        client, token,
        name="Custom threshold product", sku="THRESHOLD-RESET",
        quantity_on_hand=3, low_stock_threshold=2,
    )
    assert item["is_low_stock"] is False

    response = client.patch(
        "/api/products/" + str(item["id"]),
        headers=headers,
        json={"low_stock_threshold": None},
    )
    assert response.status_code == 200
    updated = response.json()["item"]
    assert updated["low_stock_threshold"] is None
    assert updated["effective_low_stock_threshold"] == 5
    assert updated["is_low_stock"] is True


def test_production_supabase_mode_serves_ui_without_local_database():
    import os
    import subprocess
    import sys

    environment = os.environ.copy()
    environment.update({
        "APP_ENV": "production",
        "STOCKFLOW_API_MODE": "supabase",
        "SUPABASE_API_ORIGIN": "https://citireafvqtqkuxvmail.supabase.co",
        "SECRET_KEY": "production-supabase-mode-test-secret-with-more-than-32-characters",
    })
    environment.pop("DATABASE_URL", None)
    smoke_code = "\n".join([
        "from fastapi.testclient import TestClient",
        "from app import app",
        "with TestClient(app) as client:",
        "    home = client.get(\"/\")",
        "    assert home.status_code == 200 and \"StockFlow\" in home.text",
        "    policy = home.headers[\"content-security-policy\"]",
        "    assert \"connect-src\" in policy and \"https://citireafvqtqkuxvmail.supabase.co\" in policy",
        "    health = client.get(\"/api/health\")",
        "    assert health.status_code == 200",
        "    assert health.json() == {\"status\": \"ok\", \"service\": \"stockflow\", \"api_mode\": \"supabase\"}",
        "    blocked = client.get(\"/api/dashboard\")",
        "    assert blocked.status_code == 503",
    ])
    result = subprocess.run(
        [sys.executable, "-c", smoke_code],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr

def test_production_startup_requires_explicit_database_url():
    import os
    import subprocess
    import sys

    environment = os.environ.copy()
    environment["APP_ENV"] = "production"
    environment.pop("DATABASE_URL", None)
    environment["SECRET_KEY"] = "production-test-secret-with-more-than-thirty-two-characters"
    result = subprocess.run(
        [sys.executable, "-c", "import db"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "DATABASE_URL must be configured in production" in result.stderr

    environment["DATABASE_URL"] = "sqlite:///:memory:"
    sqlite_result = subprocess.run(
        [sys.executable, "-c", "import db"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert sqlite_result.returncode != 0
    assert "SQLite is for local development only" in sqlite_result.stderr


def test_database_url_normalization_for_supported_sql_engines(monkeypatch):
    from db import configured_database_url

    monkeypatch.setenv("DATABASE_URL", "postgres://app_user:secret@db.example.test:5432/stockflow")
    assert configured_database_url() == "postgresql+psycopg://app_user:secret@db.example.test:5432/stockflow"

    monkeypatch.setenv("DATABASE_URL", "postgresql://app_user:secret@db.example.test:5432/stockflow")
    assert configured_database_url() == "postgresql+psycopg://app_user:secret@db.example.test:5432/stockflow"

    monkeypatch.setenv("DATABASE_URL", "mysql://app_user:secret@db.example.test:3306/stockflow")
    assert configured_database_url() == "mysql+pymysql://app_user:secret@db.example.test:3306/stockflow"

    monkeypatch.setenv("DATABASE_URL", "sqlite:///./stockflow.db")
    assert configured_database_url() == "sqlite:///./stockflow.db"


def test_database_initialization_creates_required_tables(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, inspect
    import db

    database_file = tmp_path / "stockflow-startup-test.db"
    startup_engine = create_engine(
        "sqlite:///" + str(database_file).replace("\\", "/"),
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(db, "engine", startup_engine)
    db.init_db()
    table_names = set(inspect(startup_engine).get_table_names())
    assert {"organizations", "organization_settings", "users", "products"} <= table_names
    assert database_file.exists()
    startup_engine.dispose()


def test_production_rejects_wildcard_cors_origins():
    import os
    import subprocess
    import sys

    environment = os.environ.copy()
    environment.update({
        "APP_ENV": "production",
        "SECRET_KEY": "production-cors-test-secret-with-more-than-thirty-two-characters",
        "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/stockflow",
        "CORS_ORIGINS": "*",
    })
    result = subprocess.run(
        [sys.executable, "-c", "import app"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "Production CORS_ORIGINS must list explicit origins" in result.stderr


def test_startup_rejects_out_of_range_token_lifetimes():
    import os
    import subprocess
    import sys

    base_environment = os.environ.copy()
    base_environment.update({
        "APP_ENV": "production",
        "SECRET_KEY": "production-ttl-test-secret-with-more-than-thirty-two-characters",
        "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/stockflow",
    })
    for ttl in ("0", "169"):
        environment = base_environment.copy()
        environment["TOKEN_TTL_HOURS"] = ttl
        result = subprocess.run(
            [sys.executable, "-c", "import auth"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode != 0
        assert "TOKEN_TTL_HOURS must be an integer between 1 and 168" in result.stderr


def test_password_verifier_rejects_malformed_and_extreme_iteration_counts():
    from auth import hash_password, verify_password

    encoded = hash_password("correct-horse-123")
    algorithm, iterations, salt, digest = encoded.split("$", 3)
    too_low = "$".join((algorithm, "1", salt, digest))
    too_high = "$".join((algorithm, "999999999", salt, digest))
    unsupported = "$".join(("unsupported", iterations, salt, digest))

    assert verify_password("correct-horse-123", encoded) is True
    assert verify_password("correct-horse-123", too_low) is False
    assert verify_password("correct-horse-123", too_high) is False
    assert verify_password("correct-horse-123", unsupported) is False
    assert verify_password("correct-horse-123", "not-a-valid-hash") is False


def test_docker_start_command_execs_uvicorn_for_signal_forwarding():
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parent / "Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]' in dockerfile


def test_postman_collection_covers_authentication_and_token_reuse():
    import json
    from pathlib import Path

    collection = json.loads(
        (Path(__file__).resolve().parent / "postman_collection.json").read_text(encoding="utf-8")
    )
    variables = {item["key"]: item.get("value", "") for item in collection["variable"]}
    assert {"baseUrl", "token", "email"} <= variables.keys()

    authentication = next(item for item in collection["item"] if item["name"] == "Authentication")
    signup = next(item for item in authentication["item"] if item["request"]["url"] == "{{baseUrl}}/api/auth/signup")
    login = next(item for item in authentication["item"] if item["request"]["url"] == "{{baseUrl}}/api/auth/login")

    signup_body = json.loads(signup["request"]["body"]["raw"])
    login_body = json.loads(login["request"]["body"]["raw"])
    assert signup_body["email"] == "{{email}}"
    assert login_body["email"] == "{{email}}"
    pre_request = "\\n".join(
        line
        for event in signup.get("event", [])
        if event["listen"] == "prerequest"
        for line in event["script"]["exec"]
    )
    assert "pm.collectionVariables.set('email'" in pre_request
    assert "{{$guid}}" in pre_request
    signup_tests = "\\n".join(
        line
        for event in signup.get("event", [])
        if event["listen"] == "test"
        for line in event["script"]["exec"]
    )
    assert "pm.collectionVariables.set('token'" in signup_tests
