# DocuMate Auth Service

Independent FastAPI authentication service for DocuMate. User passwords are hashed
with Argon2id. Access tokens are short-lived RS256 JWTs and refresh tokens are opaque,
hashed in PostgreSQL, rotated on refresh, and revoked on logout.

Required environment variables:

- `DOCUMATE_DATABASE_URL`
- `DOCUMATE_JWT_PRIVATE_KEY_PATH`
- `DOCUMATE_JWT_PUBLIC_KEY_PATH`

