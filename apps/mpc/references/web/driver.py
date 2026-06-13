"""Playwright port of the mpc-autofill Selenium driver for makeplayingcards.com.

Flow (faithful to chilli-axe/mpc-autofill desktop-tool ``driver.py``):

  1. open the blank-card designer, sign in (auto-fill creds, else wait for
     a manual sign-in — detected via the logout link appearing),
  2. define the project: cardstock + smallest quantity bracket (+ foil),
  3. page to fronts (``doPersonalize`` → quantity into the settings iframe →
     "a different image for each card"),
  4. upload each front through the ``#uploadId`` file input (identity =
     uppercase SHA-1 "pid"; already-uploaded pids are skipped) and assign it
     to its slots via ``PageLayout.prototype.applyDragPhoto`` JS injection,
  5. page to backs, switch to "same image for every card", upload + insert
     the single shared cardback into slot 0,
  6. page to review, save the project to the account.

The driver **never checks out** — it finishes on the review page with the
project saved, leaving the (headed) browser open for the user to add to cart
and pay manually.
"""
import logging
import time
from typing import List, Optional

from playwright.sync_api import Error as PlaywrightError, Frame, Page, sync_playwright

from apps.mpc.references.dto.order import DtoMpcCardImage, DtoMpcOrder
from apps.mpc.references.web import constants as c

logger = logging.getLogger(__name__)


class MpcDriverError(RuntimeError):
    pass


class MpcAutofillDriver:
    """Drives makeplayingcards.com's legacy designer with Playwright."""

    def __init__(self, config: Optional[dict] = None, headless: bool = False,
                 manual_login_timeout_s: int = 300):
        self.config = config or {}
        self.headless = headless
        self.manual_login_timeout_s = manual_login_timeout_s
        self._playwright = None
        self._browser = None
        self._context = None
        self.page: Optional[Page] = None

    # region lifecycle

    def launch(self) -> "MpcAutofillDriver":
        app_data = self.config.get("app_data") or {}
        user_data_dir = app_data.get("user_data_dir")
        self._playwright = sync_playwright().start()
        if user_data_dir and not str(user_data_dir).startswith("${"):
            # Persistent profile keeps the MPC session across runs.
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir, headless=self.headless, viewport={"width": 1280, "height": 900})
        else:
            self._browser = self._playwright.chromium.launch(headless=self.headless)
            self._context = self._browser.new_context(viewport={"width": 1280, "height": 900})
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self.page.set_default_timeout(30_000)
        return self

    def close(self) -> None:
        """Tear the browser down. NOT called after a successful run — the
        browser is intentionally left open for manual review/checkout."""
        for closer in (self._context, self._browser, self._playwright):
            try:
                if closer is not None:
                    closer.close() if not hasattr(closer, "stop") else closer.stop()
            except Exception:
                pass

    # endregion

    # region low-level helpers

    def js(self, script: str):
        """Evaluate a JS expression in the page, tolerating designer-frontend flakiness."""
        try:
            return self.page.evaluate(script)
        except PlaywrightError as e:
            logger.debug("JS '%s' raised: %s", script[:80], e)
            return None

    def wait_js_defined(self, symbol: str, timeout_s: float = 10) -> None:
        """Block until a designer JS object/function exists (they load late)."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.js(f"typeof {symbol} !== 'undefined'") is True:
                return
            time.sleep(0.5)
        logger.debug("Waited %ss for JS symbol %s — powering on regardless.", timeout_s, symbol)

    def wait_loading(self) -> bool:
        """Wait for MPC's loading overlay to clear. Returns True if the page
        had to be refreshed to unstick the frontend (mirrors upstream)."""
        try:
            spinner = self.page.locator(f"#{c.LOADING_SPINNER_ID}")
            if spinner.count():
                spinner.wait_for(state="hidden", timeout=30_000)
        except PlaywrightError:
            logger.info("MPC loading overlay stuck for 30s — refreshing the page...")
            self.page.reload()
            return True
        return False

    def next_step(self) -> None:
        self.wait_loading()
        self.wait_js_defined("oDesign.setNextStep")
        self.js(c.JS_NEXT_STEP)

    def settings_frame(self) -> Frame:
        frame = self.page.frame(name=c.SETTINGS_IFRAME_NAME)
        if frame is None:
            raise MpcDriverError(f"iframe '{c.SETTINGS_IFRAME_NAME}' not found")
        return frame

    def _set_image_mode(self, same: bool) -> None:
        self.wait_js_defined("setMode")
        self.wait_js_defined("oRenderFeature")
        # setMode lives in the settings iframe's document on some steps and
        # the top window on others — try both.
        script = c.JS_SAME_IMAGES if same else c.JS_DIFFERENT_IMAGES
        frame = self.page.frame(name=c.SETTINGS_IFRAME_NAME)
        try:
            (frame or self.page).evaluate(script)
        except PlaywrightError:
            self.js(script)

    # endregion

    # region authentication

    def is_authenticated(self) -> bool:
        return self.page.locator(f'a[href="{c.LOGOUT_URL}"]').count() >= 1

    def authenticate(self) -> None:
        """Sign in: try the configured credentials, else wait for a manual login."""
        self.page.goto(c.STARTING_URL)
        self.page.wait_for_load_state("domcontentloaded")
        if self.is_authenticated():
            return
        app_data = self.config.get("app_data") or {}
        email = app_data.get("email")
        password = app_data.get("password")
        self.page.goto(c.LOGIN_URL)
        self.page.wait_for_load_state("domcontentloaded")

        if email and password and not str(email).startswith("${"):
            try:
                email_input = self.page.locator(
                    'input[type="email"], input[id*="email" i], input[name*="email" i]').first
                password_input = self.page.locator('input[type="password"]').first
                email_input.fill(email)
                password_input.fill(password)
                password_input.press("Enter")
                self.page.wait_for_load_state("domcontentloaded")
            except PlaywrightError as e:
                logger.warning("Automatic MPC login failed (%s) — falling back to manual.", e)

        deadline = time.monotonic() + self.manual_login_timeout_s
        prompted = False
        while time.monotonic() < deadline:
            self.page.goto(c.STARTING_URL)
            self.page.wait_for_load_state("domcontentloaded")
            if self.is_authenticated():
                logger.info("Signed in to makeplayingcards.com.")
                return
            if not prompted:
                logger.info("Please sign in to makeplayingcards.com in the browser window — "
                            "the tool resumes automatically.")
                prompted = True
            self.page.goto(c.LOGIN_URL)
            time.sleep(3)
        raise MpcDriverError("Not signed in to makeplayingcards.com within the timeout.")

    # endregion

    # region project definition

    def define_project(self, order: DtoMpcOrder) -> None:
        self.page.goto(c.STARTING_URL)
        self.page.wait_for_load_state("domcontentloaded")
        logger.info("Configuring project: %s cards, stock '%s', foil=%s",
                    order.details.quantity, order.details.stock, order.details.foil)
        self.page.select_option(f"#{c.CARDSTOCK_DROPDOWN_ID}", label=order.details.stock)
        self._select_bracket(order.details.quantity, c.QUANTITY_DROPDOWN_ID)
        if order.details.foil:
            self.page.select_option(f"#{c.PRINT_TYPE_DROPDOWN_ID}", value=c.FOIL_DROPDOWN_VALUE)

    def _select_bracket(self, quantity: int, dropdown_id: str) -> int:
        values = self.page.eval_on_selector_all(
            f"#{dropdown_id} option", "opts => opts.map(o => parseInt(o.value))")
        brackets = sorted(v for v in values if v >= quantity)
        if not brackets:
            raise MpcDriverError(
                f"{quantity} cards does not fit any MPC bracket (max {max(values or [0])}).")
        bracket = brackets[0]
        logger.info("Project fits the up-to-%d-cards bracket.", bracket)
        self.page.select_option(f"#{dropdown_id}", value=str(bracket))
        return bracket

    def page_to_fronts(self, order: DtoMpcOrder) -> None:
        self.wait_js_defined("doPersonalize")
        self.js(c.js_do_personalize())
        self.wait_loading()
        frame = self.settings_frame()
        qty = frame.locator(f"#{c.CARD_NUMBER_INPUT_ID}")
        qty.fill(str(order.details.quantity))
        self._set_image_mode(same=False)
        self.wait_loading()

    # endregion

    # region image upload / insertion

    def uploaded_pids(self) -> List[str]:
        self.wait_js_defined("oDesignImage.dn_getImageList")
        pid_string = self.js(c.JS_IMAGE_LIST)
        return pid_string.split(";") if pid_string else []

    def _is_uploading(self) -> bool:
        return self.js(f"{c.JS_UPLOAD_STATUS} == 'Uploading'") is True

    def upload_image(self, image: DtoMpcCardImage, max_tries: int = 3) -> Optional[str]:
        """Upload one image; returns its pid (or None when every try failed)."""
        if not image.file_exists():
            logger.warning("Image missing on disk, skipping: %s", image.file_path)
            return None
        image.generate_pid()
        if image.pid in self.uploaded_pids():
            logger.debug("Already uploaded: %s", image.name)
            return image.pid

        for attempt in range(1, max_tries + 1):
            while self._is_uploading():
                time.sleep(0.5)
            before = len(self.uploaded_pids())
            self.page.set_input_files(f"#{c.UPLOAD_INPUT_ID}", image.file_path)
            time.sleep(1)
            while self._is_uploading():
                time.sleep(0.5)
            if len(self.uploaded_pids()) > before or image.pid in self.uploaded_pids():
                return image.pid
            logger.warning("Upload attempt %d/%d failed for %s.", attempt, max_tries, image.name)
        logger.warning("Giving up uploading %s after %d tries.", image.name, max_tries)
        return None

    def pid_in_slot(self, slot: int) -> Optional[str]:
        return self.js(f"{c.js_element_for_slot(slot)}?.getAttribute('pid')")

    def insert_image(self, image: DtoMpcCardImage, max_tries: int = 3) -> bool:
        """Assign an uploaded image's pid to each of its slots. Returns whether
        the project state changed (drives the auto-save cadence)."""
        if not image.pid:
            return False
        self.wait_js_defined("PageLayout.prototype.applyDragPhoto")
        valid_slots = [s for s in sorted(image.slots)
                       if self.js(f"{c.js_element_for_slot(s)} !== null")]
        mutated = False
        for slot in valid_slots:
            if self.pid_in_slot(slot) == image.pid:
                continue
            mutated = True
            for _ in range(max_tries):
                self.js(c.js_insert_pid_into_slot(slot, image.pid))
                if not self.wait_loading():
                    break
        return mutated

    def upload_and_insert_all(self, order: DtoMpcOrder, images: List[DtoMpcCardImage],
                              auto_save_threshold: Optional[int] = 5) -> None:
        total = len(images)
        for i, image in enumerate(images):
            self.upload_image(image)
            mutated = self.insert_image(image)
            if (auto_save_threshold and mutated
                    and (i % auto_save_threshold == auto_save_threshold - 1 or i == total - 1)):
                self.save_project(order)
            if (i + 1) % 10 == 0 or i == total - 1:
                logger.info("Inserted %d/%d images.", i + 1, total)

    # endregion

    # region backs / save / review

    def page_to_backs(self) -> None:
        self.next_step()
        self.wait_loading()
        close_btn = self.page.locator(f"#{c.CLOSE_BUTTON_ID}")
        try:
            if close_btn.count() and close_btn.is_visible():
                close_btn.click()
        except PlaywrightError:
            pass
        self.next_step()
        self.wait_loading()
        self.wait_js_defined("PageLayout.prototype.renderDesignCount")
        self.js(c.JS_RENDER_DESIGN_COUNT)
        # One shared cardback for every card.
        self._set_image_mode(same=True)
        self.wait_loading()

    def insert_cardback(self, order: DtoMpcOrder) -> None:
        if order.cardback is None:
            raise MpcDriverError("Order has no cardback image.")
        order.cardback.slots = [0]   # in same-image mode, slot 0 covers all
        self.upload_image(order.cardback)
        self.insert_image(order.cardback)

    def page_to_review(self) -> None:
        self.next_step()
        self.next_step()
        self.wait_loading()

    def save_project(self, order: DtoMpcOrder) -> None:
        name_input = self.page.locator(f"#{c.PROJECT_NAME_INPUT_ID}")
        project_name = (order.name or "Project")[:c.PROJECT_NAME_MAX_LENGTH]
        try:
            if name_input.count() and name_input.input_value() != project_name:
                name_input.fill(project_name)
        except PlaywrightError:
            pass
        self.wait_js_defined("oDesign.setTemporarySave")
        self.js(c.JS_TEMPORARY_SAVE)
        try:
            self.page.locator(f"#{c.SAVE_STATUS_DIV_ID}").get_by_text(
                c.SAVED_SUCCESSFULLY_TEXT).wait_for(timeout=30_000)
        except PlaywrightError:
            logger.info("Save confirmation not observed within 30s — refreshing.")
            self.page.reload()

    # endregion

    # region public

    def execute_order(self, order: DtoMpcOrder, auto_save_threshold: Optional[int] = 5) -> None:
        """Run the full autofill for one order, ending SAVED on the review page.

        The browser is left open — review the project, add it to the cart, and
        check out manually (identical to upstream mpc-autofill behaviour).
        """
        problems = order.validate()
        if problems:
            raise MpcDriverError("Order invalid: " + "; ".join(problems))
        if self.page is None:
            self.launch()
        self.authenticate()
        self.define_project(order)
        self.page_to_fronts(order)
        self.upload_and_insert_all(order, order.fronts, auto_save_threshold)
        self.page_to_backs()
        self.insert_cardback(order)
        self.page_to_review()
        self.save_project(order)
        logger.info(
            "Project '%s' saved. Review it in the browser, add to cart, and check out manually.",
            order.name)

    # endregion
