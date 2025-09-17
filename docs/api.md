# API Overview

Welcome to the bytesophos API documentation related to backend (python modules). This short overview explains how the API is organized and how to authenticate. JWT authentication is needed for most requests. In left sidebar under Modules section you can find API documentation for each module of the backend.

---

## Base URL

- Frontend (Vite server): [`http://localhost:5173`](http://localhost:5173){target="\_blank" rel="noopener"}
- REST API server: [`http://localhost:3001`](http://localhost:3001){target="\_blank" rel="noopener"}
- Swagger UI: [`http://localhost:3001/docs`](http://localhost:3001/docs){target="\_blank" rel="noopener"}
- ReDoc: [`http://localhost:3001/redoc`](http://localhost:3001/redoc){target="\_blank" rel="noopener"}
- OpenAPI schema: [`http://localhost:3001/openapi.json`](http://localhost:3001/openapi.json){target="\_blank" rel="noopener"}

> Documentation site related to backend (MkDocs) runs at [`http://localhost:7000`](http://localhost:7000){target="\_blank" rel="noopener"}.

---

## Authentication

Most endpoints expect a JWT Bearer token.

- Header: `Authorization: Bearer <token>`
- Token issuing and refresh time: see `routes/auth` in the Modules section.

Example:

```bash
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:3001/api/health
```
