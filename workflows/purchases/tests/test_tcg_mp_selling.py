from workflows.purchases.tasks.tcg_mp_selling import generate_tcg_mappings, generate_audit_for_tcg_orders


def test__generate_tcg_mappings():
    generate_tcg_mappings("TCG_MP","ECHO_MTG","ECHO_MTG_FE","SCRYFALL")

def test__generate_audit_for_tcg_orders():
    generate_audit_for_tcg_orders("TCG_MP")