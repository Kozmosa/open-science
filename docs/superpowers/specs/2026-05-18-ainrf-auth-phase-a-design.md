# AINRF Multi-User Auth — Phase A Design Spec

Date: 2026-05-18 | Session: `ainrf-h2` | Status: draft
Part of: Multi-User Auth (Phase A/3) | Next: Phase B (Resource Isolation), Phase C (Admin UI + Collaborators)

## Phase A Scope

User authentication foundation — no resource scoping yet. All existing resources remain global.

- **auth.sqlite3** + User table + refresh_tokens table
- **AuthService** — register, login, refresh, logout, me
- **JWT middleware** — replaces existing X-API-Key middleware
- **Frontend** — LoginPage, RegisterPage, AuthContext, layout protection
- **CLI** — `ainrf login` command
- **Initial admin** — auto-created on first startup

## Data Model

### users table (auth.sqlite3)

```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,       -- bcrypt
    display_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member', -- 'admin' | 'member'
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'active' | 'disabled'
    created_at TEXT NOT NULL,
    activated_at TEXT,
    last_login_at TEXT
);
```

### refresh_tokens table

```sql
CREATE TABLE refresh_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

## JWT Design

- **Access Token**: HS256, 15min TTL. Payload: `{sub: user_id, username, role, exp, iat}`
- **Refresh Token**: Random UUID → SHA256 hash stored in refresh_tokens table. 7 day TTL
- **Secret**: `~/.ainrf/jwt_secret` — auto-generated 64-byte random hex on first startup

## Auth API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /auth/register | None | Register new user (status=pending) |
| POST | /auth/login | None | Login → returns access + refresh token |
| POST | /auth/refresh | Refresh Token | Returns new access token |
| POST | /auth/logout | Access Token | Deletes refresh token |
| GET | /auth/me | Access Token | Returns current user info |

All five endpoints are in the middleware exempt list.

## Middleware

Replace `build_api_key_middleware` with `build_jwt_auth_middleware`:

```python
# Exempt paths
_EXEMPT_PREFIXES = (
    "/health", "/docs", "/openapi.json", "/redoc",
    "/auth/login", "/auth/register", "/auth/refresh",
    "/v1/models", "/v1/messages",
)

# Flow:
# 1. Check exempt → pass through
# 2. Extract Bearer token from Authorization header
# 3. Decode & verify JWT (HS256, check exp)
# 4. Look up user, verify status == 'active' (not pending/disabled)
# 5. Inject request.state.current_user = {id, username, display_name, role}
# 6. On failure → 401
```

## Frontend

### LoginPage (`/login`)

- Username + password form
- On success: store accessToken in AuthContext (memory), refreshToken in localStorage
- Redirect to `/` after login
- Link to RegisterPage

### RegisterPage (`/register`)

- Username + display_name + password + confirm password
- On success: show "Account created. Awaiting admin approval." message
- Registration doesn't auto-login (account is pending)

### AuthContext

```typescript
interface AuthState {
  user: { id: string; username: string; display_name: string; role: string } | null;
  accessToken: string | null;
  isPending: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (...) => Promise<void>;
  logout: () => void;
}
```

- Refresh logic: axios interceptor catches 401 → tries /auth/refresh → retries original request → on failure redirects to /login
- On app load: check localStorage for refreshToken → call /auth/refresh → restore session

### Layout Protection

- If no user → redirect to `/login`
- If user.status === 'pending' → show "Pending Approval" screen (not `/login`)
- Logged in → show username + logout button in header

## CLI

### `ainrf login`

```bash
$ ainrf login
Username: alice
Password: ******
Logged in as alice (member). Token saved.
```

Token stored at `~/.ainrf/token` (JSON: `{access_token, refresh_token, expires_at}`). CLI commands auto-load and refresh.

### Initial Admin

On first startup (users table empty):
```python
password = secrets.token_hex(12)  # random 24-char
create_user(username="admin", display_name="Administrator",
            password=password, role="admin", status="active")
print(f"Initial admin created. Username: admin, Password: {password}")
```

Also available via: `ainrf admin create <username> --role admin` (after first admin exists since it requires auth).

## Implementation Order

1. auth.sqlite3 schema + AuthService (register/login/refresh/logout/me)
2. JWT middleware replacement + app.py wiring + initial admin
3. Frontend: LoginPage + RegisterPage + AuthContext + Layout integration
4. CLI: `ainrf login` command
5. Tests + Integration verification

## Testing

### Backend
- User CRUD (register / login / refresh / logout / me)
- JWT encode/decode/expire/tamper
- bcrypt password verification
- Pending user cannot login
- Disabled user cannot login
- Refresh token rotation
- Admin auto-creation on empty DB
- Middleware exempt paths pass through
- Invalid/expired token returns 401

### Frontend
- LoginPage form submission
- RegisterPage → pending message
- AuthContext login/logout state transitions
- Unauthenticated redirect to /login
- Pending user sees "Awaiting Approval" screen
- Token refresh on 401 with valid refresh token
- Logout clears tokens and redirects
