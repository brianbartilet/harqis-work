-- Schema bootstrap for tenant/, tenant_secrets/, tenant_usage.
-- Dialect is Postgres-first; the SQLite path in tenant.migrations.apply
-- adapts the type declarations at runtime.
--
-- Reversible via: drop table if exists tenant_usage, tenant_secrets, tenants cascade;
-- (kept out of this file to avoid foot-guns; apply.py exposes downgrade()).

CREATE TABLE IF NOT EXISTS tenants (
    id                     VARCHAR(36)  PRIMARY KEY,
    slug                   VARCHAR(64)  NOT NULL UNIQUE,
    clerk_org_id           VARCHAR(64)  UNIQUE,
    plan                   VARCHAR(32)  NOT NULL DEFAULT 'starter',
    base_cents             INTEGER      NOT NULL DEFAULT 4900,
    overage_cents_per_exec INTEGER      NOT NULL DEFAULT 1,
    stripe_customer_id     VARCHAR(64),
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at             TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tenant_secrets (
    id          SERIAL       PRIMARY KEY,
    tenant_id   VARCHAR(36)  NOT NULL,
    app_id      VARCHAR(64)  NOT NULL,
    key         VARCHAR(64)  NOT NULL,
    ciphertext  BYTEA        NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_secret UNIQUE (tenant_id, app_id, key)
);
CREATE INDEX IF NOT EXISTS ix_tenant_secrets_tenant_id ON tenant_secrets (tenant_id);

CREATE TABLE IF NOT EXISTS tenant_usage (
    id           SERIAL       PRIMARY KEY,
    tenant_id    VARCHAR(36)  NOT NULL,
    task_id      VARCHAR(64)  NOT NULL,
    task_name    VARCHAR(255) NOT NULL,
    queue        VARCHAR(64),
    status       VARCHAR(32)  NOT NULL,
    started_at   TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duration_ms  INTEGER,
    billed_at    TIMESTAMPTZ,
    CONSTRAINT uq_tenant_usage_exec UNIQUE (task_id, tenant_id)
);
CREATE INDEX IF NOT EXISTS ix_tenant_usage_tenant_id ON tenant_usage (tenant_id);
