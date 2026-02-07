from workflows.purchases.tasks.tcg_mp_selling import (generate_tcg_mappings, generate_audit_for_tcg_orders,
                                                      download_scryfall_bulk_data, generate_tcg_listings,
                                                      update_tcg_listings_prices)

def test__generate_tcg_mappings():
    generate_tcg_mappings(cfg_id__tcg_mp="TCG_MP",
                          cfg_id__echo_mtg="ECHO_MTG",
                          cfg_id__echo_mtg_fe="ECHO_MTG_FE",
                          cfg_id__scryfall="SCRYFALL"
                          )

def test__generate_tcg_mappings_force():
    generate_tcg_mappings(cfg_id__tcg_mp="TCG_MP",
                          cfg_id__echo_mtg="ECHO_MTG",
                          cfg_id__echo_mtg_fe="ECHO_MTG_FE",
                          cfg_id__scryfall="SCRYFALL",
                          force_generate=True
                          )

def test__generate_tcg_mappings_bulk():
    generate_tcg_mappings(cfg_id__tcg_mp="TCG_MP",
                          cfg_id__echo_mtg="ECHO_MTG_BULK",
                          cfg_id__echo_mtg_fe="ECHO_MTG_FE_BULK",
                          cfg_id__scryfall="SCRYFALL",
                          force_generate=True
                          )

def test__generate_tcg_listings():
    generate_tcg_listings(cfg_id__tcg_mp="TCG_MP",
                          cfg_id__echo_mtg="ECHO_MTG",
                          cfg_id__echo_mtg_fe="ECHO_MTG_FE"
                          )

def test__generate_tcg_listings_bulk():
    generate_tcg_listings(cfg_id__tcg_mp="TCG_MP",
                          cfg_id__echo_mtg="ECHO_MTG_BULK",
                          cfg_id__echo_mtg_fe="ECHO_MTG_FE_BULK"
                          )

def test__update_tcg_listings_prices():
    update_tcg_listings_prices(cfg_id__tcg_mp="TCG_MP",
                               cfg_id__echo_mtg="ECHO_MTG",
                               cfg_id__echo_mtg_fe="ECHO_MTG_FE"
                               )

def test__update_tcg_listings_prices_bulk():
    update_tcg_listings_prices(cfg_id__tcg_mp="TCG_MP",
                               cfg_id__echo_mtg="ECHO_MTG_BULK",
                               cfg_id__echo_mtg_fe="ECHO_MTG_FE_BULK"
                               )

def test__generate_audit_for_tcg_orders():
    generate_audit_for_tcg_orders(cfg_id__tcg_mp="TCG_MP")

def test__download_scryfall_bulk_data():
    download_scryfall_bulk_data(cfg_id__scryfall="SCRYFALL")