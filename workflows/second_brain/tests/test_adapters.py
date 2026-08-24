from workflows.second_brain.adapters import client_items, render_text


def test__client_items_redacts_restricted_content():
    result = client_items(
        {
            "items": [
                {
                    "allowed_clients": ["telegram"],
                    "sensitivity": "restricted",
                    "summary": "Account 1234 balance 99",
                    "details": "raw detail",
                    "source_refs": ["secret"],
                    "links": {"account": "https://example.test"},
                }
            ]
        },
        client="telegram",
    )
    assert result[0]["details"] == ""
    assert result[0]["source_refs"] == []
    assert "Account 1234" not in result[0]["summary"]
    assert result[0]["links"] == {}


def test__render_text_is_concise_and_bounded():
    items = [
        {"category": "work", "title": f"Ticket {index}", "summary": "Changed"}
        for index in range(20)
    ]
    rendered = render_text(items, limit=3)
    assert rendered.count("[WORK]") == 3
    assert "Ticket 3" not in rendered
