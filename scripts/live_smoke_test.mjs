import { randomUUID } from "node:crypto";

const base = (process.env.STOCKFLOW_API_BASE_URL || "").replace(/\/+$/, "");
if (!base) throw new Error("STOCKFLOW_API_BASE_URL must be set");
const suffix = randomUUID().replaceAll("-", "").slice(0, 14);
const password = "Sf-" + randomUUID() + "-Long!";
const emailA = "stockflow-ci-" + suffix + "@example.com";
const emailB = "stockflow-ci-" + suffix + "-b@example.com";
const sku = "CI-" + suffix.toUpperCase();
const check = (condition, message) => { if (!condition) throw new Error(message); };
async function call(path, options = {}) {
  const method = options.method || "GET";
  const token = options.token;
  const body = options.body;
  const expected = options.expected === undefined ? 200 : options.expected;
  const headers = new Headers();
  const apiKey = process.env.STOCKFLOW_API_KEY || "";
  if (apiKey) headers.set("apikey", apiKey);
  if (body !== undefined) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", "Bearer " + token);
  const response = await fetch(base + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const contentType = response.headers.get("content-type") || "";
  const data = response.status === 204 ? null : contentType.includes("application/json") ? await response.json() : await response.text();
  if (response.status !== expected) throw new Error(method + " " + path + ": expected " + expected + ", received " + response.status + ": " + (typeof data === "string" ? data.slice(0,240) : JSON.stringify(data)));
  return { response, data };
}

const renderBase = (process.env.STOCKFLOW_RENDER_BASE_URL || "").replace(/\/+$/, "");
if (renderBase) {
  const renderPage = await fetch(renderBase + "/", { signal: AbortSignal.timeout(120000) });
  const renderHtml = await renderPage.text();
  check(renderPage.ok, "Render landing page returned HTTP " + renderPage.status);
  check(renderHtml.includes("StockFlow"), "Render landing page did not contain the StockFlow UI");
  const policy = renderPage.headers.get("content-security-policy") || "";
  check(policy.includes("https://citireafvqtqkuxvmail.supabase.co"), "Render CSP does not permit the configured Supabase API origin");
  check(policy.includes("images.unsplash.com"), "Render CSP does not permit the workspace background images");
  const cssPath = renderHtml.match(/href="(style\.css\?v=[^"]+)"/)?.[1];
  const jsPath = renderHtml.match(/src="(script\.js\?v=[^"]+)"/)?.[1];
  check(Boolean(cssPath && jsPath), "Render HTML is missing versioned CSS/JavaScript assets");
  const renderCssResponse = await fetch(renderBase + "/" + cssPath, { signal: AbortSignal.timeout(45000) });
  const renderCss = await renderCssResponse.text();
  check(renderCssResponse.ok, "Render stylesheet returned HTTP " + renderCssResponse.status);
  for (const selector of [".section-head-dashboard::before", ".section-head-products::before", ".section-head-settings::before"]) {
    check(renderCss.includes(selector), "Render stylesheet is missing " + selector);
  }
  check(renderCss.includes("photo-1586528116311-ad8dd3c8310d") && renderCss.includes("photo-1553413077-190dd305871c") && renderCss.includes("photo-1497366754035-f200968a6e72"), "Render stylesheet is missing one of the three background images");
  const renderJsResponse = await fetch(renderBase + "/" + jsPath, { signal: AbortSignal.timeout(45000) });
  const renderJs = await renderJsResponse.text();
  check(renderJsResponse.ok, "Render JavaScript returned HTTP " + renderJsResponse.status);
  check(renderJs.includes("Passwords do not match.") && renderJs.includes("Email or password is incorrect") === false, "Render JavaScript form validation bundle is unexpected");
  check(renderJs.includes("form.dataset.productId ? 'Save changes' : 'Create product'"), "Render JavaScript has stale product submit handling");
  const renderHealthResponse = await fetch(renderBase + "/api/health", { signal: AbortSignal.timeout(45000) });
  const renderHealth = await renderHealthResponse.json().catch(() => ({}));
  check(renderHealthResponse.status === 200, "Render health endpoint returned HTTP " + renderHealthResponse.status);
  check(renderHealth.status === "ok" && renderHealth.api_mode === "supabase", "Render health endpoint reported an unexpected mode");
  console.log("PASS: live Render page + versioned assets + section backgrounds + Supabase CSP + health endpoint");
}

const health = await call("/api/health");
check(health.data.status === "ok" && health.data.database === "ok", "Health endpoint did not report a healthy database");
const preflight = await fetch(base + "/api/auth/login", {
  method: "OPTIONS",
  headers: {
    Origin: "https://mahitech580.github.io",
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type,authorization,apikey",
  },
});
check(preflight.status === 204, "CORS preflight returned " + preflight.status);
check(preflight.headers.get("access-control-allow-origin") === "*", "CORS origin header missing");
check((preflight.headers.get("access-control-allow-headers") || "").toLowerCase().includes("authorization"), "CORS authorization header not allowed");
check((preflight.headers.get("access-control-allow-headers") || "").toLowerCase().includes("apikey"), "CORS API-key header not allowed");

const orgName = "CI " + suffix;
const a = await call("/api/auth/signup", { method:"POST", expected:201, body:{email:emailA,password,organization_name:orgName} });
const tokenA = a.data.access_token;
check(typeof tokenA === "string" && tokenA.length > 20, "Signup did not return a session token");
check(a.data.user.email === emailA, "Signup user email mismatch");
check(a.data.user.organization_name === orgName && Boolean(a.data.user.organization_id), "Signup did not create and link an organization");
const login = await call("/api/auth/login", {method:"POST",body:{email:emailA,password}});
const tokenLogin = login.data.access_token;
check(typeof tokenLogin === "string", "Login did not return an access token");
const me = await call("/api/me", {token:tokenLogin});
check(me.data.user.email === emailA && me.data.user.organization_id === a.data.user.organization_id, "Authenticated identity or organization link mismatch");
const wrongPassword = await call("/api/auth/login", {method:"POST",expected:401,body:{email:emailA,password:"wrong-" + password}});
check(wrongPassword.data.detail === "Email or password is incorrect", "Incorrect-password feedback changed unexpectedly");
await call("/api/auth/signup", {method:"POST",expected:409,body:{email:emailA,password,organization_name:orgName}});
await call("/api/auth/signup", {method:"POST",expected:422,body:{email:"short-pass-" + suffix + "@example.com",password:"123",organization_name:orgName}});

const created = await call("/api/products", {
  method:"POST", token:tokenLogin, expected:201,
  body:{name:"Live smoke " + suffix,sku,description:"Disposable live API smoke test",quantity_on_hand:4,cost_price:2.5,selling_price:4.5,low_stock_threshold:null},
});
const item = created.data.item;
check(item.sku === sku && item.quantity_on_hand === 4, "Product creation values mismatch");
await call("/api/products", {
  method:"POST", token:tokenLogin, expected:409,
  body:{name:"Duplicate SKU test",sku,quantity_on_hand:1},
});
const search = await call("/api/products?q=" + encodeURIComponent(sku), {token:tokenLogin});
check(search.data.count === 1 && search.data.items[0].id === item.id, "Product search failed");
const patched = await call("/api/products/" + item.id, {method:"PATCH",token:tokenLogin,body:{quantity_on_hand:10}});
check(patched.data.item.quantity_on_hand === 10, "Product update failed");
const adjusted = await call("/api/products/" + item.id + "/adjust-stock", {method:"POST",token:tokenLogin,body:{delta:-2,note:"Live smoke adjustment"}});
check(adjusted.data.item.quantity_on_hand === 8, "Stock adjustment failed");
await call("/api/settings", {method:"PATCH",token:tokenLogin,body:{default_low_stock_threshold:9}});
const dashboard = await call("/api/dashboard", {token:tokenLogin});
check(dashboard.data.total_products === 1 && dashboard.data.total_units === 8, "Dashboard totals are incorrect");
check(dashboard.data.low_stock_count === 1, "Low-stock threshold setting did not take effect");

const b = await call("/api/auth/signup", {method:"POST",expected:201,body:{email:emailB,password,organization_name:"CI B " + suffix}});
const tokenB = b.data.access_token;
const isolated = await call("/api/products/" + item.id, {token:tokenB,expected:404});
check(isolated.data.detail === "Product not found", "Cross-organization access was not blocked");
const bProducts = await call("/api/products", {token:tokenB});
check(bProducts.data.count === 0, "Organization B can see organization A products");
const bSettings = await call("/api/settings", {token:tokenB});
check(bSettings.data.default_low_stock_threshold === 5, "Settings leaked across organizations");
await call("/api/products/" + item.id, {method:"DELETE",token:tokenLogin,expected:204});
await call("/api/products/" + item.id, {token:tokenLogin,expected:404});

const demoSessionId = randomUUID();
const demo = await call("/api/auth/demo", {method:"POST",expected:201,body:{session_id:demoSessionId}});
check(demo.data.user.is_demo === true, "Demo access did not flag its session");
check(demo.data.user.organization_id !== a.data.user.organization_id, "Demo workspace must be isolated from registered accounts");
const demoMe = await call("/api/me", {token:demo.data.access_token});
check(demoMe.data.user.is_demo === true, "Demo mode label did not persist through /api/me");
const demoProducts = await call("/api/products", {token:demo.data.access_token});
check(demoProducts.data.count === 0, "Demo workspace unexpectedly includes another user's products");

console.log("PASS: live API health + database");
console.log("PASS: browser CORS preflight");
console.log("PASS: signup + login + authenticated identity");
console.log("PASS: create + duplicate SKU rejection + search + update");
console.log("PASS: stock adjustments + dashboard + threshold settings");
console.log("PASS: tenant isolation");
console.log("PASS: product deletion");
console.log("Two disposable CI accounts were created for this one-time run; their data remains isolated in StockFlow.");
