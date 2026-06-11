# AINRF Agent E2E Test Checklist

This document defines the test scenarios a coding agent (via Oh-My-Pi)
executes against a running AINRF E2E container using Playwright MCP.

## Pre-conditions

- E2E environment is running (`testing/e2e/run.sh up`)
- Agent has Playwright MCP configured
- Agent has read credentials from the container

## Smoke Tests (run every time)

### S-01: Health endpoint returns 200
- `GET /health` → 200, body contains `"status": "healthy"` or `"degraded"`

### S-02: Frontend loads
- Navigate to `http://localhost:8198/`
- Verify page title contains "AINRF"
- No console errors within 5 seconds

### S-03: Login flow
- Navigate to `/login`
- Fill username "admin", password from credentials
- Submit form
- Verify redirect away from `/login`
- Verify user menu or avatar visible

### S-04: API authentication
- `POST /api/auth/login` with admin credentials → 200, `access_token` present
- `GET /api/auth/me` with token → 200, username matches
- `POST /api/auth/logout` → 200

## Core Feature Tests

### F-01: Project CRUD
1. `POST /api/projects` → create project "E2E Test Project"
2. `GET /api/projects` → verify new project in list
3. `GET /api/projects/{id}` → verify fields match
4. `PUT /api/projects/{id}` → update title
5. `DELETE /api/projects/{id}` → 200
6. `GET /api/projects/{id}` → 404

### F-02: Workspace management
1. `POST /api/projects/{pid}/workspaces` → create workspace
2. `GET /api/projects/{pid}/workspaces` → verify list
3. Verify workspace directory structure

### F-03: Task lifecycle
1. Create project + workspace + environment
2. `POST /api/tasks` → create task
3. `GET /api/tasks/{id}` → verify initial status "queued"
4. Poll task status (may remain queued if no real agent key)
5. Verify task appears in task list

### F-04: File browser
1. Navigate browser to project workspace
2. `GET /api/files/browse?path=/` → verify directory listing
3. Upload a small test file
4. Verify file appears in listing
5. Download file → verify content matches

### F-05: Literature subscriptions (if search backend configured)
1. `POST /api/literature/subscriptions` → create subscription
2. `GET /api/literature/subscriptions` → verify list
3. `DELETE /api/literature/subscriptions/{id}` → 200

### F-06: User management (admin only)
1. `GET /api/admin/users` → list users
2. Verify admin, alice, bob exist
3. `PATCH /api/admin/users/alice/status` → suspend
4. Verify alice cannot login
5. `PATCH /api/admin/users/alice/status` → reactivate

### F-07: Settings
1. `GET /api/settings` → verify response
2. `PUT /api/settings/search-backend` → update setting
3. `GET /api/settings` → verify updated value

## Frontend UI Tests (Playwright MCP)

### UI-01: Login page validation
- Submit empty form → error messages visible
- Submit wrong password → error visible
- Submit correct credentials → redirected to dashboard

### UI-02: Navigation
- After login, verify sidebar/navigation present
- Click each nav item → verify page loads without errors
- Verify breadcrumbs or page titles update

### UI-03: Project creation flow
- Navigate to projects page
- Click "New Project" button
- Fill form fields
- Submit → project appears in list

### UI-04: Responsive layout
- Set viewport to 1280x720 → verify layout
- Set viewport to 375x812 (mobile) → verify layout adapts
- No horizontal scroll on mobile

### UI-05: WebSocket terminal
- Navigate to terminal page
- Verify terminal container renders
- (If SSH available) Verify connection attempt visible

## Performance Checks

### P-01: Page load timing
- Navigate to login page → measure time to interactive
- Navigate to dashboard (authenticated) → measure time
- Flag if any page > 3 seconds

### P-02: API response times
- `GET /api/health` → should be < 100ms
- `GET /api/projects` (with 0 projects) → < 200ms
- `POST /api/auth/login` → < 500ms

### P-03: Frontend bundle size
- Check network tab for JS bundle sizes
- Flag if total JS > 2MB uncompressed

### P-04: Memory under load
- Create 50 projects via API
- List projects → measure response time
- Verify no memory leak indicators in /health

## Security Spot Checks

### SEC-01: Unauthenticated access denied
- `GET /api/projects` without token → 401
- `GET /api/admin/users` without token → 401

### SEC-02: Role enforcement
- Login as "alice" (member)
- `GET /api/admin/users` → should be 403
- `DELETE /api/projects/{not-yours}` → should be 403

### SEC-03: SQL injection attempt
- `POST /api/auth/login` with username `"admin' OR 1=1--"` → 401

### SEC-04: XSS in project name
- Create project with title `<script>alert(1)</script>`
- View project in browser → verify script does NOT execute
- Verify title is escaped in DOM
