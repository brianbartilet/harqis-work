from workflows.purchases.tasks.tcg_mp_selling import generate_tcg_mappings


def test__generate_tcg_mappings():
    generate_tcg_mappings("TCG_MP",
                          "ECHO_MTG",
                          "ECHO_MTG_FE",
                          "SCRYFALL")