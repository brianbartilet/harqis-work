import pytest
from hamcrest import assert_that, equal_to, instance_of

from apps.mpc.references.dto.order import build_orders
from apps.mpc.references.web.constants import PROJECT_MAX_SIZE
from apps.mpc.references.xml.order_xml import read_order_xml, write_order_xml


@pytest.fixture()
def images(tmp_path):
    """A fake rendered-card directory: 5 fronts + a cardback."""
    paths = []
    for i in range(5):
        p = tmp_path / f"{i:04d}-pokemon.png"
        p.write_bytes(b"png-bytes-" + bytes([i]))
        paths.append(str(p))
    cardback = tmp_path / "cardback.png"
    cardback.write_bytes(b"cardback-bytes")
    return paths, str(cardback)


@pytest.mark.smoke
def test_build_orders_single(images):
    fronts, cardback = images
    orders = build_orders(fronts, cardback, name_prefix="Pokedex Proxies")
    assert_that(len(orders), equal_to(1))
    order = orders[0]
    assert_that(order.details.quantity, equal_to(5))
    assert order.name == "Pokedex Proxies"
    assert [c.slots for c in order.fronts] == [[0], [1], [2], [3], [4]]
    assert_that(order.validate(), equal_to([]))


@pytest.mark.smoke
def test_build_orders_splits_at_project_max(images):
    fronts, cardback = images
    # 1025 dex entries from 5 real files (existence isn't validated here).
    many = [fronts[i % len(fronts)] for i in range(1025)]
    orders = build_orders(many, cardback)
    assert_that(len(orders), equal_to(2))
    assert [o.details.quantity for o in orders] == [PROJECT_MAX_SIZE, 1025 - PROJECT_MAX_SIZE]
    assert orders[0].name == "Project 1 of 2"
    # Slots restart at 0 in every chunk.
    assert orders[1].fronts[0].slots == [0]


@pytest.mark.smoke
def test_order_xml_round_trip(images, tmp_path):
    fronts, cardback = images
    order = build_orders(fronts, cardback, name_prefix="RoundTrip")[0]
    xml_path = str(tmp_path / "order.xml")
    write_order_xml(order, xml_path)

    loaded = read_order_xml(xml_path)
    assert_that(loaded.details.quantity, equal_to(order.details.quantity))
    assert_that(loaded.details.stock, equal_to(order.details.stock))
    assert loaded.details.foil is False
    assert [c.file_path for c in loaded.fronts] == [c.file_path for c in order.fronts]
    assert [c.slots for c in loaded.fronts] == [c.slots for c in order.fronts]
    assert loaded.cardback.file_path == cardback
    assert_that(loaded.validate(), equal_to([]))


@pytest.mark.smoke
def test_pid_is_uppercase_sha1(images):
    import hashlib
    from pathlib import Path
    fronts, cardback = images
    order = build_orders(fronts, cardback)[0]
    card = order.fronts[0]
    expected = hashlib.sha1(Path(card.file_path).read_bytes()).hexdigest().upper()
    assert_that(card.generate_pid(), equal_to(expected))


@pytest.mark.smoke
def test_validate_flags_problems(tmp_path):
    fronts = [str(tmp_path / "missing.png")]
    orders = build_orders(fronts, str(tmp_path / "no-cardback.png"))
    problems = orders[0].validate()
    assert_that(problems, instance_of(list))
    assert any("missing front image" in p for p in problems)
    assert any("missing cardback" in p for p in problems)
