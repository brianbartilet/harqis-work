"""Live driver tests against makeplayingcards.com.

These launch a real (headed) browser and touch the MPC account configured in
``apps_config.yaml`` — they are opt-in via ``MPC_DRIVER_LIVE_TEST=1`` so the
suite stays safe to run unattended. The full end-to-end order flow lives in
``workflows/tcg/tests`` (the user-triggered pipeline test).
"""
import os

import pytest
from hamcrest import assert_that, instance_of

from apps.mpc.references.web.driver import MpcAutofillDriver

requires_live = pytest.mark.skipif(
    os.environ.get("MPC_DRIVER_LIVE_TEST") != "1",
    reason="set MPC_DRIVER_LIVE_TEST=1 to run live MPC browser tests",
)


@pytest.mark.smoke
def test_driver_constructs_without_browser():
    driver = MpcAutofillDriver(config={"app_data": {}})
    assert_that(driver.headless, instance_of(bool))
    assert driver.page is None


@requires_live
@pytest.mark.integration
def test_driver_launches_and_loads_designer():
    from apps.mpc.config import CONFIG
    driver = MpcAutofillDriver(config=CONFIG, headless=False)
    try:
        driver.launch()
        driver.page.goto("https://www.makeplayingcards.com/design/custom-blank-card.html")
        driver.page.wait_for_load_state("domcontentloaded")
        assert "makeplayingcards" in driver.page.url
        # The project-definition dropdowns the driver depends on must exist.
        assert driver.page.locator("#dro_paper_type").count() == 1
        assert driver.page.locator("#dro_choosesize").count() == 1
    finally:
        driver.close()
