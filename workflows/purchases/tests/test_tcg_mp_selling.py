from workflows.purchases.tasks.tcg_mp_selling import (generate_tcg_mappings, generate_audit_for_tcg_orders,
                                                      download_scryfall_bulk_data, generate_tcg_listings,
                                                      update_tcg_listings_prices)


def test__generate_tcg_mappings():
    generate_tcg_mappings("TCG_MP","ECHO_MTG","ECHO_MTG_FE","SCRYFALL")

def test__generate_tcg_mappings_bulk():
    generate_tcg_mappings("TCG_MP","ECHO_MTG_BULK",
                          "ECHO_MTG_FE_BULK","SCRYFALL", force_generate=True)

def test__generate_tcg_listings():
    generate_tcg_listings("TCG_MP","ECHO_MTG_BULK","ECHO_MTG_FE_BULK")

def test__update_tcg_listings_prices():
    update_tcg_listings_prices("TCG_MP","ECHO_MTG_BULK","ECHO_MTG_FE_BULK")

def test__generate_audit_for_tcg_orders():
    generate_audit_for_tcg_orders("TCG_MP")

def test__download_scryfall_bulk_data():
    download_scryfall_bulk_data("SCRYFALL")