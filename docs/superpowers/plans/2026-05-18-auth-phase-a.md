# Auth Phase A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single API Key auth with JWT-based user authentication: User model, login/register API, JWT middleware, LoginPage frontend, and CLI login.

**Architecture:** New `src/ainrf/auth/` package (models + service + middleware). auth.sqlite3 stores users + refresh_tokens. JWT HS256 with secret on disk. JWT middleware replaces existing X-API-Key middleware in a single switch. All existing routes get `request.state.current_user` transparently. Frontend adds AuthContext with token refresh interceptor.

**Tech Stack:** Python 3.13 dataclasses, bcrypt, PyJWT, SQLite3, FastAPI, React 19 + TanStack Query, Vitest

---

## File Structure

```
src/ainrf/auth/
    __init__.py              # re-exports
    models.py                # User, RefreshToken dataclasses + errors
    service.py               # AuthService (register, login, refresh, logout, me)
    middleware.py             # build_jwt_auth_middleware (replaces old middleware)
    jwt_utils.py             # create_access_token, decode_access_token, create_refresh_token

src/ainrf/api/
    middleware.py             # REMOVE old build_api_key_middleware (or keep as fallback)
    app.py                    # register auth_router, init AuthService, wire new middleware
    routes/auth.py            # auth routes (register, login, refresh, logout, me)
    schemas.py                # + login/register request/response schemas

src/ainrf/
    cli.py                    # + login command
    onboarding.py             # update: skip API key prompt, guide to user creation

frontend/src/
    types/index.ts            # + UserInfo, LoginRequest, RegisterRequest, ...
    api/endpoints.ts          # + login, register, refresh, logout, getMe
    api/client.ts             # + Authorization: Bearer header + refresh interceptor
    contexts/AuthContext.tsx  # NEW — user state, login/logout/register
    pages/LoginPage.tsx        # NEW
    pages/RegisterPage.tsx     # NEW
    pages/PendingPage.tsx      # NEW — "Awaiting Approval" screen
    components/common/Layout.tsx  # — API key removed, show username + logout
    App.tsx                   # + /login, /register routes + AuthProvider

tests/
    test_auth.py              # backend auth tests
```

---

## Task 1: auth.sqlite3 Schema + Auth Models + AuthService

**Files:**
- Create: `src/ainrf/auth/__init__.py`
- Create: `src/ainrf/auth/models.py`
- Create: `src/ainrf/auth/jwt_utils.py`
- Create: `src/ainrf/auth/service.py`

- [ ] **Step 1: Create package init**

```python
# src/ainrf/auth/__init__.py
"""Authentication and authorization service."""

from ainrf.auth.models import (
    AuthError,
    User,
    UserStatus,
    UserRole,
)
from ainrf.auth.service import AuthService

__all__ = [
    "AuthError",
    "AuthService",
    "User",
    "UserRole",
    "UserStatus",
]
```

- [ ] **Step 2: Write models**

```python
# src/ainrf/auth/models.py
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class UserStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DISABLED = "disabled"


class AuthError(RuntimeError):
    """Base error for auth operations."""


@dataclass(slots=True)
class User:
    id: str
    username: str
    password_hash: str
    display_name: str
    role: UserRole
    status: UserStatus
    created_at: str
    activated_at: str | None
    last_login_at: str | None
```

- [ ] **Step 3: Write JWT utilities**

```python
# src/ainrf/auth/jwt_utils.py
from __future__ import annotations

import hashlib
import os
import secrets
import time
from pathlib import Path

import jwt  # PyJWT

_SECRET_PATH = Path.home() / ".ainrf" / "jwt_secret"
_ALGORITHM = "HS256"
_ACCESS_TTL_SEC = 15 * 60       # 15 minutes
_REFRESH_TTL_SEC = 7 * 86400    # 7 days


def _ensure_secret() -> str:
    if _SECRET_PATH.exists():
        return _SECRET_PATH.read_text().strip()
    secret = secrets.token_hex(32)  # 64-char hex
    _SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SECRET_PATH.write_text(secret)
    return secret


def create_access_token(user_id: str, username: str, role: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + _ACCESS_TTL_SEC,
    }
    return jwt.encode(payload, _ensure_secret(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, _ensure_secret(), algorithms=[_ALGORITHM])


def create_refresh_token() -> tuple[str, str]:
    """Returns (plain_token, sha256_hash)."""
    plain = secrets.token_hex(32)
    return plain, hashlib.sha256(plain.encode()).hexdigest()
```

- [ ] **Step 4: Write AuthService**

```python
# src/ainrf/auth/service.py
from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import datetime, timezone

import bcrypt

from ainrf.auth.jwt_utils import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
)
from ainrf.auth.models import (
    AuthError,
    User,
    UserRole,
    UserStatus,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class AuthService:
    def __init__(self, *, state_root: Path) -> None:
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "auth.sqlite3"
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'member',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    activated_at TEXT,
                    last_login_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()
        self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level="IMMEDIATE")
        conn.row_factory = sqlite3.Row
        return conn

    # --- Registration ---

    def register(self, *, username: str, display_name: str, password: str) -> User:
        self.initialize()
        # Check username uniqueness
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
        if row is not None:
            raise AuthError(f"Username '{username}' already exists")

        uid = _new_id()
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, display_name, role, status, created_at) "
                "VALUES (?, ?, ?, ?, 'member', 'pending', ?)",
                (uid, username, password_hash, display_name, now),
            )
            conn.commit()
        return self._load_user(uid)

    # --- Login ---

    def login(self, *, username: str, password: str) -> dict:
        """Returns {access_token, refresh_token, user} or raises AuthError."""
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        if row is None:
            raise AuthError("Invalid username or password")
        user = _row_to_user(row)
        if user.status == UserStatus.PENDING:
            raise AuthError("Account is pending approval")
        if user.status == UserStatus.DISABLED:
            raise AuthError("Account is disabled")

        if not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            raise AuthError("Invalid username or password")

        # Update last_login_at
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?", (now, user.id)
            )
            conn.commit()

        access_token = create_access_token(user.id, user.username, user.role.value)
        plain_refresh, hashed_refresh = create_refresh_token()
        expires_at = (datetime.now(timezone.utc).timestamp() + 7 * 86400)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (_new_id(), user.id, hashed_refresh,
                 datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(), now),
            )
            conn.commit()

        return {
            "access_token": access_token,
            "refresh_token": plain_refresh,
            "user": _user_to_dict(user),
        }

    # --- Refresh ---

    def refresh(self, refresh_token: str) -> dict:
        """Returns {access_token} or raises AuthError."""
        self.initialize()
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM refresh_tokens WHERE token_hash = ?", (token_hash,)
            ).fetchone()
        if row is None:
            raise AuthError("Invalid refresh token")

        expires_at = datetime.fromisoformat(row["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            # Clean up expired token
            with self._connect() as conn:
                conn.execute("DELETE FROM refresh_tokens WHERE id = ?", (row["id"],))
                conn.commit()
            raise AuthError("Refresh token expired")

        user = self._load_user(row["user_id"])
        if user.status != UserStatus.ACTIVE:
            raise AuthError("Account is not active")

        access_token = create_access_token(user.id, user.username, user.role.value)
        return {"access_token": access_token}

    # --- Logout ---

    def logout(self, refresh_token: str) -> None:
        self.initialize()
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM refresh_tokens WHERE token_hash = ?", (token_hash,)
            )
            conn.commit()

    # --- Me ---

    def get_user(self, user_id: str) -> User:
        return self._load_user(user_id)

    def get_user_by_token(self, token: str) -> dict:
        """Validate access token and return user dict."""
        payload = decode_access_token(token)
        user = self._load_user(payload["sub"])
        if user.status != UserStatus.ACTIVE:
            raise AuthError("Account is not active")
        return _user_to_dict(user)

    # --- Internal ---

    def _load_user(self, user_id: str) -> User:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        if row is None:
            raise AuthError(f"User not found: {user_id}")
        return _row_to_user(row)


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        display_name=row["display_name"],
        role=UserRole(row["role"]),
        status=UserStatus(row["status"]),
        created_at=row["created_at"],
        activated_at=row["activated_at"],
        last_login_at=row["last_login_at"],
    )


def _user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role.value,
        "status": user.status.value,
    }
```

- [ ] **Step 5: Verify imports**

Run: `cd /home/xuyang/code/scholar-agent && uv run python -c "from ainrf.auth import AuthService; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/ainrf/auth/
git commit -m "feat: add AuthService with users + refresh_tokens tables and JWT utils"
```

---

## Task 2: Auth API Routes + JWT Middleware + app.py Wiring

**Files:**
- Create: `src/ainrf/api/routes/auth.py`
- Modify: `src/ainrf/api/middleware.py` (replace old middleware)
- Modify: `src/ainrf/api/app.py`
- Modify: `src/ainrf/api/schemas.py`

- [ ] **Step 1: Add API schemas**

Append to `src/ainrf/api/schemas.py`:

```python
class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=4)


class AuthTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: str
    refresh_token: str
    user: dict


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


class AccessTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: str


class UserInfoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    username: str
    display_name: str
    role: str
    status: str
```

- [ ] **Step 2: Create auth routes**

Create `src/ainrf/api/routes/auth.py`:

```python
"""Authentication API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ainrf.api.schemas import (
    AccessTokenResponse,
    AuthTokenResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    UserInfoResponse,
)
from ainrf.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="auth service not initialized")
    return service


@router.post("/register", status_code=201)
async def register(payload: RegisterRequest, request: Request) -> dict:
    service = _get_service(request)
    try:
        service.register(
            username=payload.username,
            display_name=payload.display_name,
            password=payload.password,
        )
    except Exception as exc:
        detail = str(exc)
        if "already exists" in detail:
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return {"message": "Registration submitted. Awaiting admin approval."}


@router.post("/login", response_model=AuthTokenResponse)
async def login(payload: LoginRequest, request: Request) -> AuthTokenResponse:
    service = _get_service(request)
    try:
        result = service.login(username=payload.username, password=payload.password)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return AuthTokenResponse.model_validate(result)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(payload: RefreshRequest, request: Request) -> AccessTokenResponse:
    service = _get_service(request)
    try:
        result = service.refresh(payload.refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return AccessTokenResponse.model_validate(result)


@router.post("/logout", status_code=204)
async def logout(payload: RefreshRequest, request: Request):
    service = _get_service(request)
    try:
        service.logout(payload.refresh_token)
    except Exception:
        pass  # best-effort
    return None


@router.get("/me", response_model=UserInfoResponse)
async def me(request: Request) -> UserInfoResponse:
    user = getattr(request.state, "current_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserInfoResponse.model_validate(user)
```

- [ ] **Step 3: Replace middleware**

Replace `src/ainrf/api/middleware.py`:

```python
"""JWT authentication middleware."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ainrf.auth.service import AuthService

_EXEMPT_PATH_PREFIXES = (
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/auth/login",
    "/auth/register",
    "/auth/refresh",
    "/v1/models",
    "/v1/messages",
)


def _is_exempt(path: str) -> bool:
    return any(path.startswith(p) for p in _EXEMPT_PATH_PREFIXES)


def build_jwt_auth_middleware(auth_service: AuthService):
    class JwtAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if _is_exempt(request.url.path):
                return await call_next(request)

            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)

            token = auth_header[7:]
            try:
                user = auth_service.get_user_by_token(token)
            except Exception:
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)

            request.state.current_user = user
            return await call_next(request)

    return JwtAuthMiddleware
```

- [ ] **Step 4: Wire into app.py**

Read `src/ainrf/api/app.py`. Make these changes:

A. Replace import:
```python
# Remove: from ainrf.api.middleware import build_api_key_middleware
# Add:
from ainrf.api.middleware import build_jwt_auth_middleware
```

B. Add auth import:
```python
from ainrf.auth import AuthService
```

C. In `create_app`, before other services:
```python
auth_service = AuthService(state_root=api_config.state_root)
app.state.auth_service = auth_service
```

D. In `lifespan`, after other initializations:
```python
await _run_sync_in_lifespan(auth_service.initialize)
```

E. Replace middleware:
```python
# Remove: app.middleware("http")(build_api_key_middleware(api_config))
# Add:
app.middleware("http")(build_jwt_auth_middleware(auth_service))
```

F. Add auth router to ROUTERS tuple:
```python
from ainrf.api.routes.auth import router as auth_router

ROUTERS = (
    auth_router,  # first, since /auth/* is exempt
    health_router,
    ...existing...
)
```

G. Add initial admin on startup (in lifespan, after auth_service.initialize):
```python
import secrets
from ainrf.auth.service import AuthService as _AuthSvc
# Check if any users exist
with _AuthSvc._connect(auth_service) as conn:
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
if count == 0:
    password = secrets.token_hex(12)
    auth_service.register(username="admin", display_name="Administrator", password=password)
    # Manually activate the admin
    with auth_service._connect() as conn:
        conn.execute("UPDATE users SET status = 'active', activated_at = ? WHERE username = 'admin'", (_now_iso(),))
        conn.commit()
    print(f"\n{'='*60}\nInitial admin created!\nUsername: admin\nPassword: {password}\n{'='*60}\n")
```

- [ ] **Step 5: Verify imports**

Run: `cd /home/xuyang/code/scholar-agent && uv run python -c "from ainrf.api.app import create_app; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Run existing tests (expect some 401 failures since API key is gone)**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q`

- [ ] **Step 7: Commit**

```bash
git add src/ainrf/api/routes/auth.py src/ainrf/api/middleware.py src/ainrf/api/app.py src/ainrf/api/schemas.py
git commit -m "feat: add auth API routes, JWT middleware, and initial admin creation"
```

---

## Task 3: Frontend — AuthContext + API Client Updates

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/endpoints.ts`
- Create: `frontend/src/contexts/AuthContext.tsx`

- [ ] **Step 1: Add types**

Append to `frontend/src/types/index.ts`:

```typescript
// ── Auth types ───────────────────────────────────────────

export interface UserInfo {
  id: string;
  username: string;
  display_name: string;
  role: string;
  status: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  display_name: string;
  password: string;
}

export interface AuthTokenResponse {
  access_token: string;
  refresh_token: string;
  user: UserInfo;
}

export interface AccessTokenResponse {
  access_token: string;
}
```

- [ ] **Step 2: Add auth API functions**

Append to `frontend/src/api/endpoints.ts`:

```typescript
import type { AccessTokenResponse, AuthTokenResponse, LoginRequest, RegisterRequest, UserInfo } from '../types';

export const login = (payload: LoginRequest): Promise<AuthTokenResponse> =>
  api.post<AuthTokenResponse>('/auth/login', payload);

export const register = (payload: RegisterRequest): Promise<{ message: string }> =>
  api.post<{ message: string }>('/auth/register', payload);

export const refreshToken = (refreshToken: string): Promise<AccessTokenResponse> =>
  api.post<AccessTokenResponse>('/auth/refresh', { refresh_token: refreshToken });

export const logoutApi = (refreshToken: string): Promise<void> =>
  api.post<void>('/auth/logout', { refresh_token: refreshToken });

export const getMe = (): Promise<UserInfo> =>
  api.get<UserInfo>('/auth/me');
```

- [ ] **Step 3: Update API client with token support**

Read `frontend/src/api/client.ts`. Modify to:

A. Remove `VITE_AINRF_API_KEY` usage from headers
B. Delete `X-API-Key` header from default headers
C. Add Authorization header support:

```typescript
// Near the top, add:
let _accessToken: string | null = null;

export function setAccessToken(token: string | null) {
  _accessToken = token;
}

export function getStoredRefreshToken(): string | null {
  return localStorage.getItem('ainrf.refresh_token');
}

export function setStoredRefreshToken(token: string | null) {
  if (token) {
    localStorage.setItem('ainrf.refresh_token', token);
  } else {
    localStorage.removeItem('ainrf.refresh_token');
  }
}
```

D. In the `api` object methods, add Authorization header when `_accessToken` is set:

```typescript
const headers: Record<string, string> = { ... };
if (_accessToken) {
  headers['Authorization'] = `Bearer ${_accessToken}`;
}
```

E. Also remove `X-AINRF-User-Id` header (replaced by JWT identity).

- [ ] **Step 4: Create AuthContext**

Create `frontend/src/contexts/AuthContext.tsx`:

```tsx
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { login as apiLogin, register as apiRegister, refreshToken, logoutApi, getMe } from '../api/endpoints';
import { setAccessToken, getStoredRefreshToken, setStoredRefreshToken } from '../api/client';
import type { UserInfo } from '../types';

interface AuthState {
  user: UserInfo | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, displayName: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [loading, setLoading] = useState(true);

  // Try to restore session on mount
  useEffect(() => {
    const stored = getStoredRefreshToken();
    if (!stored) {
      setLoading(false);
      return;
    }
    refreshToken(stored)
      .then((res) => {
        setAccessToken(res.access_token);
        return getMe();
      })
      .then((u) => setUser(u))
      .catch(() => {
        setStoredRefreshToken(null);
        setAccessToken(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await apiLogin({ username, password });
    setAccessToken(res.access_token);
    setStoredRefreshToken(res.refresh_token);
    setUser(res.user);
  }, []);

  const register = useCallback(async (username: string, displayName: string, password: string) => {
    await apiRegister({ username, display_name: displayName, password });
  }, []);

  const logout = useCallback(async () => {
    const stored = getStoredRefreshToken();
    if (stored) {
      try { await logoutApi(stored); } catch {}
    }
    setStoredRefreshToken(null);
    setAccessToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
```

- [ ] **Step 5: Type-check**

Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Fix any errors.

- [ ] **Step 6: Run frontend tests**

Run: `cd /home/xuyang/code/scholar-agent/frontend && npm run test:run`
Expected: Existing tests pass (some may need updating since API key header changed).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts frontend/src/api/endpoints.ts frontend/src/contexts/
git commit -m "feat: add AuthContext, auth API functions, and token-based client"
```

---

## Task 4: Frontend — LoginPage + RegisterPage + Layout Protection

**Files:**
- Create: `frontend/src/pages/LoginPage.tsx`
- Create: `frontend/src/pages/RegisterPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/common/Layout.tsx`
- Modify: `frontend/src/i18n/messages.ts`

- [ ] **Step 1: Create LoginPage**

Create `frontend/src/pages/LoginPage.tsx`:

```tsx
import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useT } from '../i18n';

export default function LoginPage() {
  const t = useT();
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await login(username, password);
      navigate('/');
    } catch (err: any) {
      setError(err.message || 'Login failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form onSubmit={handleSubmit} className="bg-white p-8 rounded-xl shadow-sm border w-full max-w-sm">
        <h1 className="text-xl font-semibold mb-6">AINRF</h1>
        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}
        <div className="flex flex-col gap-4">
          <input
            className="px-3 py-2 border rounded-lg text-sm"
            placeholder={t('auth.username')}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
          />
          <input
            type="password"
            className="px-3 py-2 border rounded-lg text-sm"
            placeholder={t('auth.password')}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button
            type="submit"
            disabled={submitting || !username || !password}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium disabled:opacity-50"
          >
            {submitting ? t('common.loading') : t('auth.login')}
          </button>
        </div>
        <p className="text-xs text-gray-400 mt-4 text-center">
          <Link to="/register" className="text-blue-600 hover:underline">
            {t('auth.registerLink')}
          </Link>
        </p>
      </form>
    </div>
  );
}
```

- [ ] **Step 2: Create RegisterPage**

Create `frontend/src/pages/RegisterPage.tsx`:

```tsx
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useT } from '../i18n';

export default function RegisterPage() {
  const t = useT();
  const { register } = useAuth();
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password !== confirm) {
      setError('Passwords do not match');
      return;
    }
    setSubmitting(true);
    try {
      await register(username, displayName, password);
      setSuccess(true);
    } catch (err: any) {
      setError(err.message || 'Registration failed');
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="bg-white p-8 rounded-xl shadow-sm border text-center max-w-sm">
          <h1 className="text-lg font-semibold mb-4">Registration Submitted</h1>
          <p className="text-sm text-gray-500">Your account is pending admin approval. You will be able to log in once approved.</p>
          <Link to="/login" className="text-blue-600 text-sm hover:underline mt-4 inline-block">Back to Login</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form onSubmit={handleSubmit} className="bg-white p-8 rounded-xl shadow-sm border w-full max-w-sm">
        <h1 className="text-xl font-semibold mb-6">Register</h1>
        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}
        <div className="flex flex-col gap-4">
          <input className="px-3 py-2 border rounded-lg text-sm" placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          <input className="px-3 py-2 border rounded-lg text-sm" placeholder="Display Name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          <input type="password" className="px-3 py-2 border rounded-lg text-sm" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <input type="password" className="px-3 py-2 border rounded-lg text-sm" placeholder="Confirm Password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          <button type="submit" disabled={submitting || !username || !displayName || !password || !confirm} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium disabled:opacity-50">
            {submitting ? 'Loading...' : 'Register'}
          </button>
        </div>
        <p className="text-xs text-gray-400 mt-4 text-center">
          Already have an account? <Link to="/login" className="text-blue-600 hover:underline">Log in</Link>
        </p>
      </form>
    </div>
  );
}
```

- [ ] **Step 3: Add i18n keys**

In `frontend/src/i18n/messages.ts`, add to both en and zh:

```typescript
// en.auth
auth: {
  login: 'Log in',
  logout: 'Log out',
  username: 'Username',
  password: 'Password',
  registerLink: "Don't have an account? Register",
  loginLink: 'Already have an account? Log in',
  register: 'Register',
  pendingApproval: 'Your account is pending admin approval.',
},

// zh.auth
auth: {
  login: '登录',
  logout: '退出',
  username: '用户名',
  password: '密码',
  registerLink: '没有账号？注册',
  loginLink: '已有账号？登录',
  register: '注册',
  pendingApproval: '账号等待管理员审批中。',
},
```

- [ ] **Step 4: Update Layout.tsx**

Read `frontend/src/components/common/Layout.tsx`. Remove the `X-API-Key` related code. Add username + logout button in the sidebar header:

After the existing brand line, add:
```tsx
{user && (
  <div className="flex items-center gap-2 px-3 py-2 text-xs">
    <span className="text-gray-600 truncate">{user.display_name}</span>
    <button type="button" onClick={logout} className="text-gray-400 hover:text-gray-600">
      {t('auth.logout')}
    </button>
  </div>
)}
```

Import `useAuth` and use it.

- [ ] **Step 5: Update App.tsx**

Read `frontend/src/App.tsx`. Add AuthProvider wrapping. Add `/login` and `/register` routes WITHOUT Layout wrapper:

```tsx
const LoginPage = lazy(() => import('./pages/LoginPage'));
const RegisterPage = lazy(() => import('./pages/RegisterPage'));
import { AuthProvider, useAuth } from './contexts/AuthContext';

function AppRoutes() {
  const { user, loading } = useAuth();

  if (loading) return <div className="flex items-center justify-center min-h-screen">Loading...</div>;

  if (!user) {
    return (
      <Suspense fallback={null}>
        <Routes>
          <Route path="/register" element={<RegisterPage />} />
          <Route path="*" element={<LoginPage />} />
        </Routes>
      </Suspense>
    );
  }

  return (
    <Layout>
      <Suspense fallback={null}>
        <Routes>
          {/* existing routes */}
        </Routes>
      </Suspense>
    </Layout>
  );
}

export default function App() {
  return (
    <ErrorBoundary fallback={...}>
      <QueryClientProvider client={queryClient}>
        <SettingsProvider>
          <ToastProvider>
            <BrowserRouter>
              <AuthProvider>
                <AppRoutes />
              </AuthProvider>
            </BrowserRouter>
          </ToastProvider>
        </SettingsProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
```

- [ ] **Step 6: Type-check + tests**

Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Run: `cd /home/xuyang/code/scholar-agent/frontend && npm run test:run`

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/LoginPage.tsx frontend/src/pages/RegisterPage.tsx frontend/src/App.tsx frontend/src/components/common/Layout.tsx frontend/src/i18n/messages.ts
git commit -m "feat: add LoginPage, RegisterPage, AuthProvider, and layout protection"
```

---

## Task 5: CLI `ainrf login` Command

**Files:**
- Modify: `src/ainrf/cli.py`

- [ ] **Step 1: Add login command to CLI**

Read `src/ainrf/cli.py`. Add after existing commands:

```python
import json as json_mod
from pathlib import Path as _Path

_TOKEN_FILE = Path.home() / ".ainrf" / "token"


@app.command()
def login(
    server: Annotated[
        str, typer.Option("--server", help="AINRF server URL")
    ] = "http://localhost:8000",
) -> None:
    """Log in to AINRF and cache the token locally."""
    import getpass

    import requests

    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")

    try:
        resp = requests.post(
            f"{server}/auth/login",
            json={"username": username, "password": password},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"Login failed: {exc}")
        raise typer.Exit(code=1)

    data = resp.json()
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(json_mod.dumps({
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
    }))
    user = data["user"]
    print(f"Logged in as {user['username']} ({user['role']}). Token saved.")
```

- [ ] **Step 2: Verify command exists**

Run: `cd /home/xuyang/code/scholar-agent && uv run ainrf login --help`
Expected: Help text shows the login command.

- [ ] **Step 3: Commit**

```bash
git add src/ainrf/cli.py
git commit -m "feat: add ainrf login CLI command"
```

---

## Task 6: Backend Tests

**Files:**
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write auth tests**

Create `tests/test_auth.py`:

```python
"""Tests for authentication service."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


class TestAuthService:
    @pytest.fixture
    def service(self):
        from ainrf.auth import AuthService
        with tempfile.TemporaryDirectory() as td:
            svc = AuthService(state_root=Path(td))
            svc.initialize()
            yield svc

    def test_register_user(self, service):
        user = service.register(username="alice", display_name="Alice", password="secret123")
        assert user.username == "alice"
        assert user.status.value == "pending"
        assert user.role.value == "member"

    def test_register_duplicate_fails(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        with pytest.raises(Exception):
            service.register(username="alice", display_name="Alice2", password="other")

    def test_login_pending_fails(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        with pytest.raises(Exception) as exc:
            service.login(username="alice", password="secret")
        assert "pending" in str(exc.value).lower()

    def test_login_active_succeeds(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        # Manually activate
        with service._connect() as conn:
            conn.execute("UPDATE users SET status = 'active' WHERE username = 'alice'")
            conn.commit()
        result = service.login(username="alice", password="secret")
        assert "access_token" in result
        assert "refresh_token" in result
        assert result["user"]["username"] == "alice"

    def test_login_wrong_password_fails(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        with service._connect() as conn:
            conn.execute("UPDATE users SET status = 'active' WHERE username = 'alice'")
            conn.commit()
        with pytest.raises(Exception):
            service.login(username="alice", password="wrongpass")

    def test_refresh_token(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        with service._connect() as conn:
            conn.execute("UPDATE users SET status = 'active' WHERE username = 'alice'")
            conn.commit()
        login_result = service.login(username="alice", password="secret")
        refresh_result = service.refresh(login_result["refresh_token"])
        assert "access_token" in refresh_result

    def test_refresh_invalid_token_fails(self, service):
        with pytest.raises(Exception):
            service.refresh("invalid-token")

    def test_logout(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        with service._connect() as conn:
            conn.execute("UPDATE users SET status = 'active' WHERE username = 'alice'")
            conn.commit()
        result = service.login(username="alice", password="secret")
        service.logout(result["refresh_token"])
        # Refresh should now fail
        with pytest.raises(Exception):
            service.refresh(result["refresh_token"])

    def test_get_user_by_token(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        with service._connect() as conn:
            conn.execute("UPDATE users SET status = 'active' WHERE username = 'alice'")
            conn.commit()
        result = service.login(username="alice", password="secret")
        user = service.get_user_by_token(result["access_token"])
        assert user["username"] == "alice"

    def test_disabled_user_login_fails(self, service):
        service.register(username="alice", display_name="Alice", password="secret")
        with service._connect() as conn:
            conn.execute("UPDATE users SET status = 'disabled' WHERE username = 'alice'")
            conn.commit()
        with pytest.raises(Exception) as exc:
            service.login(username="alice", password="secret")
        assert "disabled" in str(exc.value).lower()


class TestJwtUtils:
    def test_create_and_decode_token(self):
        from ainrf.auth.jwt_utils import create_access_token, decode_access_token
        token = create_access_token("user1", "alice", "member")
        payload = decode_access_token(token)
        assert payload["sub"] == "user1"
        assert payload["username"] == "alice"
        assert payload["role"] == "member"

    def test_create_refresh_token(self):
        from ainrf.auth.jwt_utils import create_refresh_token
        plain, hashed = create_refresh_token()
        assert len(plain) == 64
        assert len(hashed) == 64

    def test_expired_token(self):
        import time
        import jwt as pyjwt
        from ainrf.auth.jwt_utils import _ensure_secret, _ALGORITHM
        secret = _ensure_secret()
        token = pyjwt.encode(
            {"sub": "u1", "username": "a", "role": "member", "exp": int(time.time()) - 3600},
            secret, algorithm=_ALGORITHM,
        )
        from ainrf.auth.jwt_utils import decode_access_token
        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_access_token(token)
```

- [ ] **Step 2: Run tests**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/test_auth.py -v`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_auth.py
git commit -m "test: add auth service unit tests"
```

---

## Task 7: Frontend Tests + Integration Verification

**Files:**
- Create: `frontend/src/pages/LoginPage.test.tsx`

- [ ] **Step 1: Create LoginPage test**

Create `frontend/src/pages/LoginPage.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../test/render';
import LoginPage from './LoginPage';
import * as api from '../api';

vi.mock('../api', () => ({
  login: vi.fn(),
  register: vi.fn(),
  refreshToken: vi.fn(),
  getMe: vi.fn(),
}));

const mockLogin = vi.mocked(api.login);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe('LoginPage', () => {
  it('renders login form', () => {
    renderWithProviders(<LoginPage />);
    expect(screen.getByPlaceholderText('Username')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Password')).toBeInTheDocument();
  });

  it('submits login credentials', async () => {
    mockLogin.mockResolvedValue({
      access_token: 'at',
      refresh_token: 'rt',
      user: { id: '1', username: 'alice', display_name: 'Alice', role: 'member', status: 'active' },
    });

    renderWithProviders(<LoginPage />);
    fireEvent.change(screen.getByPlaceholderText('Username'), { target: { value: 'alice' } });
    fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'secret' } });
    fireEvent.click(screen.getByText('Log in'));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith({ username: 'alice', password: 'secret' });
    });
  });
});
```

- [ ] **Step 2: Run all tests**

Run: `cd /home/xuyang/code/scholar-agent/frontend && npm run test:run`
Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q`
Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`

Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/LoginPage.test.tsx
git commit -m "test: add LoginPage rendering test"
```
