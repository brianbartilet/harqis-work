# Moo (Futu/Moo Trading)

## Description

- Integration stub for [Moo Moo / Futu](https://www.futunn.com/) stock trading platform.
- Futu provides a local trading API (OpenD gateway) that accepts connections on a local socket.
- This app is a **work in progress** — directory structure exists but no services are implemented.

## Supported Automations

- [ ] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Configuration (`apps_config.yaml`)

```yaml
MOO:
  app_id: 'moo'
  app_data:
    host: 127.0.0.1
    port: 11111
    trd_env: SIMULATE       # SIMULATE or REAL
    acc_id: 0
    security_firm: FUTUSECURITIES
    pwd_md5: ${MOO_PWD_MD5}
```

`.env/apps.env`:

```env
MOO_PWD_MD5=<md5_hash_of_trading_password>
```

## Directory Structure

```
apps/moo/
├── config.py
├── references/
│   ├── base_api_service.py     # Stub — not implemented
│   ├── constants/              # Empty
│   ├── dto/                    # Empty
│   └── web/                    # Empty
└── tests/
```

## Notes

- The Futu OpenD gateway must be running locally (default port 11111) for any real integration.
- `trd_env: SIMULATE` uses the paper trading environment — change to `REAL` for live trading.
- No tests exist for this app.
- No workflow tasks consume this app yet.
