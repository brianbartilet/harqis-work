"""Shared TCG asking-price policy. All competitor prices are gross SGD prices."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


FX_CACHE_PATH = Path(__file__).resolve().parents[3] / "logs" / "tcg-pricing" / "usd-sgd.json"


def number(value, *, positive=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid pricing number") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError("Invalid pricing number")
    return result


def _utc(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("FX timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _valid_quote(quote, now):
    number(quote["rate"], positive=True)
    if quote["pair"] != "USD/SGD":
        raise ValueError("Wrong FX pair")
    for field in ("quoted_at", "fetched_at"):
        age = now - _utc(quote[field])
        if age < -timedelta(minutes=5) or age > timedelta(days=7):
            raise ValueError("FX quote is outside the seven-day validity window")
    return quote


def _fetch_usd_sgd(cfg_id):
    from apps.apps_config import CONFIG_MANAGER
    from apps.alpha_vantage.references.web.api.fx import ApiServiceAlphaVantageFx

    return ApiServiceAlphaVantageFx(CONFIG_MANAGER.get(cfg_id)).convert_currency(1, "USD", "SGD")


def resolve_fx(*, cache_path=FX_CACHE_PATH, now=None, fetch=None, cfg_id="ALPHA_VANTAGE"):
    """24-hour cache; on refresh failure use a valid quote no older than seven days."""
    now = now or datetime.now(timezone.utc)
    cache_path = Path(cache_path)
    cached = None
    try:
        cached = _valid_quote(json.loads(cache_path.read_text(encoding="utf-8")), now)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if cached and now - _utc(cached["fetched_at"]) < timedelta(hours=24):
        return {**cached, "source": "cache", "fallback_reason": None}

    try:
        data = fetch() if fetch else _fetch_usd_sgd(cfg_id)
        if data.get("time_zone") != "UTC":
            raise ValueError("Unexpected FX quote timezone")
        quoted_at = datetime.fromisoformat(data["last_refreshed"])
        if quoted_at.tzinfo is None:
            quoted_at = quoted_at.replace(tzinfo=timezone.utc)
        quote = _valid_quote({
            "pair": "USD/SGD", "rate": str(number(data["rate"], positive=True)),
            "quoted_at": quoted_at.isoformat(), "fetched_at": now.isoformat(),
        }, now)
    except Exception as exc:
        # Do not persist provider exception strings: request URLs may include API keys.
        if cached:
            return {**cached, "source": "stale_cache", "fallback_reason": type(exc).__name__}
        raise ValueError("No usable USD/SGD quote; price writes skipped") from None

    temporary = None
    cache_error = None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=cache_path.parent,
                                         delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(quote, handle)
        os.replace(temporary, cache_path)
    except OSError:
        cache_error = "cache_write_failed"
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return {**quote, "source": "alpha_vantage", "fallback_reason": cache_error}


def _flag(value):
    if str(value).lower() in {"1", "true", "foil"}:
        return True
    if str(value).lower() in {"0", "false", "nonfoil", "non-foil"}:
        return False
    return None


def competitor_sample(rows, *, product_id, foil, language, condition, own_user_id=None):
    """The endpoint is product-scoped; require explicit matching variant/ownership fields."""
    if not isinstance(rows, list):
        raise ValueError("Invalid competitor response")
    eligible = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid competitor row")
        if _flag(row.get("own_listing")) is not False:
            continue
        if own_user_id is not None and str(row.get("user_id")) == str(own_user_id):
            continue
        if row.get("product_id") is not None and str(row["product_id"]) != str(product_id):
            continue
        if _flag(row.get("crd_foil")) is None or _flag(row["crd_foil"]) != _flag(foil):
            continue
        if str(row.get("crd_language", "")).upper() != language.upper():
            continue
        if str(row.get("crd_condition", "")).upper() != condition.upper():
            continue
        if any(_flag(row.get(key, 0)) is not False for key in ("suspended", "crd_signed", "crd_altered")):
            continue
        try:
            price = number(row.get("price"), positive=True)
            number(row.get("quantity"), positive=True)
        except ValueError:
            continue
        listing_id = row.get("id", row.get("listing_id"))
        if listing_id is None or str(listing_id) in seen:
            continue
        seen.add(str(listing_id))
        eligible.append({"listing_id": str(listing_id), "price_sgd": str(price)})
    return sorted(eligible, key=lambda row: (number(row["price_sgd"]), row["listing_id"]))[:5]


def calculate_price(base_price_usd, change_7_day, usd_to_sgd_rate, *, platform_fee_pct=3.0,
                    sample=()):
    base = number(base_price_usd, positive=True)
    rate = number(usd_to_sgd_rate, positive=True)
    change = number(change_7_day)
    fee = number(platform_fee_pct)
    if not 0 <= fee < 100:
        raise ValueError("Platform fee must be between 0 (inclusive) and 100 (exclusive)")
    premium = max(Decimal(0), change - 8) / 100
    movement = base * rate * (1 + premium) / (1 - fee / 100)
    average = (sum(number(row["price_sgd"], positive=True) for row in sample) / len(sample)
               if sample else None)
    selected = min(movement, average) if average is not None else movement
    final = selected.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if final <= 0:
        raise ValueError("Price rounds to zero; skipping variant")
    return {
        "base_price_usd": str(base), "usd_to_sgd_rate": str(rate),
        "platform_fee_pct": str(fee), "change_7_day": str(change),
        "premium_pct": str(premium * 100), "movement_price_sgd": str(movement),
        "competitor_average_sgd": str(average) if average is not None else None,
        "competitors": list(sample), "final_price_sgd": float(final),
        "selection": "competitor_cap" if average is not None and average < movement else "movement",
    }


def price_variant(*, base_price_usd, change_7_day, fx, product_service,
                  product_id, foil, language, condition, platform_fee_pct=3.0):
    """Use movement pricing if competitor data is unavailable; never hide bad base/FX inputs."""
    fallback = None
    try:
        service = product_service() if callable(product_service) else product_service
        rows = service.get_pricing_listings(product_id, foil=foil)
        sample = competitor_sample(rows, product_id=product_id, foil=foil,
                                   language=language, condition=condition,
                                   own_user_id=getattr(service, "user_id", None))
        if not sample:
            fallback = "no_eligible_competitors"
    except Exception as exc:
        sample = []
        fallback = "competitor_lookup_failed:" + type(exc).__name__
    decision = calculate_price(base_price_usd, change_7_day, fx["rate"],
                               platform_fee_pct=platform_fee_pct, sample=sample)
    return {**decision, "fx": fx, "fallback_reason": fallback}
