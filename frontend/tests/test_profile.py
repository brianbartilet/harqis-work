from __future__ import annotations

import base64
import io

from PIL import Image

from modules.hfl_shares.security import make_csrf_token
from modules.profile.store import get_profile_store


def _profile_form(**overrides):
    values = {
        "csrf": make_csrf_token("frontend-test-user"),
        "first_name": "Sam",
        "last_name": "Rivera",
        "nickname": "Sami",
        "location": "Singapore",
        "phone": "+65 8123 4567",
        "bio": "I turn lived activity into useful systems.",
        "email": "sami@example.test",
        "linkedin_url": "https://linkedin.com/in/sami",
        "github_url": "https://github.com/sami",
        "website_url": "https://sami.example.test",
        "instagram_url": "https://instagram.com/sami",
    }
    values.update(overrides)
    return values


def _png(width=24, height=12) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "#38bdf8").save(output, format="PNG")
    return output.getvalue()


def test_profile_requires_authentication_and_header_uses_fallback(
    authenticated_client,
):
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as anonymous:
        response = anonymous.get("/profile", follow_redirects=False)
    page = authenticated_client.get("/profile")

    assert response.status_code == 302
    assert page.status_code == 200
    assert "Profile settings" in page.text
    assert 'href="/profile" aria-label="Profile"' in page.text
    assert '<span aria-hidden="true">P</span>' in page.text
    assert "Country-level inference" in page.text
    assert "new Intl.Locale" in page.text


def test_profile_saves_and_updates_authenticated_header(authenticated_client):
    saved = authenticated_client.post(
        "/profile",
        data=_profile_form(),
        follow_redirects=False,
    )
    profile = get_profile_store().get()
    home = authenticated_client.get("/home")

    assert saved.status_code == 303
    assert saved.headers["location"] == "/profile?saved=true"
    assert profile.display_name == "Sami"
    assert profile.email == "sami@example.test"
    assert "Active shares now use this identity." in authenticated_client.get(
        saved.headers["location"]
    ).text
    assert '<span aria-hidden="true">S</span>' in home.text


def test_profile_validation_preserves_draft_without_overwriting_saved_profile(
    authenticated_client,
):
    authenticated_client.post("/profile", data=_profile_form())

    invalid = authenticated_client.post(
        "/profile",
        data=_profile_form(
            nickname="Draft name",
            email="not-an-email",
            phone="81234567",
            website_url="javascript:alert(1)",
        ),
    )

    assert invalid.status_code == 422
    assert 'value="Draft name"' in invalid.text
    assert "Enter a valid email address." in invalid.text
    assert "beginning with +" in invalid.text
    assert "Enter a complete HTTPS URL." in invalid.text
    assert get_profile_store().get().nickname == "Sami"


def test_avatar_is_validated_cropped_and_stored_as_webp(authenticated_client):
    response = authenticated_client.post(
        "/profile",
        data=_profile_form(),
        files={"avatar": ("portrait.png", _png(), "image/png")},
        follow_redirects=False,
    )
    profile = get_profile_store().get()

    assert response.status_code == 303
    assert profile.avatar_content_type == "image/webp"
    with Image.open(io.BytesIO(profile.avatar)) as image:
        assert image.size == (256, 256)
    page = authenticated_client.get("/home")
    encoded = base64.b64encode(profile.avatar).decode("ascii")
    assert f"data:image/webp;base64,{encoded}" in page.text


def test_invalid_avatar_keeps_previous_avatar_and_shows_error(authenticated_client):
    authenticated_client.post(
        "/profile",
        data=_profile_form(),
        files={"avatar": ("portrait.png", _png(), "image/png")},
    )
    original = get_profile_store().get().avatar

    response = authenticated_client.post(
        "/profile",
        data=_profile_form(nickname="Draft"),
        files={"avatar": ("portrait.png", b"not-an-image", "image/png")},
    )

    assert response.status_code == 422
    assert "Choose a valid JPEG, PNG, or WebP image." in response.text
    assert get_profile_store().get().avatar == original
    assert get_profile_store().get().nickname == "Sami"


def test_avatar_removal_survives_other_validation_errors(authenticated_client):
    authenticated_client.post(
        "/profile",
        data=_profile_form(),
        files={"avatar": ("portrait.png", _png(), "image/png")},
    )

    invalid = authenticated_client.post(
        "/profile",
        data=_profile_form(email="invalid", remove_avatar="on"),
    )

    assert invalid.status_code == 422
    assert 'name="remove_avatar" checked' in invalid.text
    assert get_profile_store().get().avatar

    saved = authenticated_client.post(
        "/profile",
        data=_profile_form(remove_avatar="on"),
        follow_redirects=False,
    )

    assert saved.status_code == 303
    assert get_profile_store().get().avatar == b""


def test_profile_rejects_missing_csrf(authenticated_client):
    response = authenticated_client.post(
        "/profile",
        data=_profile_form(csrf=""),
    )

    assert response.status_code == 403
