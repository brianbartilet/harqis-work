"""MakePlayingCards.com site constants.

Ported from chilli-axe/mpc-autofill ``desktop-tool/src/constants.py`` —
URLs, element ids, and the JS entry points of MPC's legacy designer frontend.
Only makeplayingcards.com is targeted (upstream also supports the
PrinterStudio family; add a TargetSite-style mapping here if ever needed).
"""
from enum import Enum


class Cardstocks(str, Enum):
    S27 = "(S27) Smooth"
    S30 = "(S30) Standard Smooth"
    S33 = "(S33) Superior Smooth"
    M31 = "(M31) Linen"
    P10 = "(P10) Plastic"


#: MPC rejects projects larger than this (shared across the MPC site family).
PROJECT_MAX_SIZE = 612

#: MPC poker-size card upload spec: 2.72" x 3.7" (print + bleed) @ 300 DPI.
CARD_WIDTH_PX = 822
CARD_HEIGHT_PX = 1122

#: MPC project names cap out at 32 characters.
PROJECT_NAME_MAX_LENGTH = 32

BASE_URL = "https://www.makeplayingcards.com"

STARTING_URL = f"{BASE_URL}/design/custom-blank-card.html"
LOGIN_URL = f"{BASE_URL}/login.aspx"
LOGOUT_URL = f"{BASE_URL}/logout.aspx"
SAVED_PROJECTS_URL = f"{BASE_URL}/design/dn_temporary_designes.aspx"
ACCEPT_SETTINGS_URL = f"{BASE_URL}/products/pro_item_process_flow.aspx"

# region element ids / selectors (MPC designer frontend)
CARDSTOCK_DROPDOWN_ID = "dro_paper_type"
QUANTITY_DROPDOWN_ID = "dro_choosesize"
PRINT_TYPE_DROPDOWN_ID = "dro_product_effect"
FOIL_DROPDOWN_VALUE = "EF_055"
CARD_NUMBER_INPUT_ID = "txt_card_number"     # inside the sysifm_loginFrame iframe
UPLOAD_INPUT_ID = "uploadId"
LOADING_SPINNER_ID = "sysdiv_wait"
PROJECT_NAME_INPUT_ID = "txt_temporaryname"
SAVE_STATUS_DIV_ID = "div_temporarysavestatus"
CLOSE_BUTTON_ID = "closeBtn"
SETTINGS_IFRAME_NAME = "sysifm_loginFrame"
SAVED_SUCCESSFULLY_TEXT = "Saved successfully"
# endregion

# region JS entry points of the MPC designer
JS_NEXT_STEP = "oDesign.setNextStep();"
JS_TEMPORARY_SAVE = "oDesign.setTemporarySave();"
JS_DIFFERENT_IMAGES = "setMode('ImageText', 0);"
JS_SAME_IMAGES = "setMode('ImageText', 1);"
JS_UPLOAD_STATUS = "oDesignImage.UploadStatus"
JS_IMAGE_LIST = "oDesignImage.dn_getImageList()"
JS_RENDER_DESIGN_COUNT = "PageLayout.prototype.renderDesignCount()"


def js_element_for_slot(slot: int) -> str:
    return f'PageLayout.prototype.getElement3("dnImg", "{slot}")'


def js_insert_pid_into_slot(slot: int, pid: str) -> str:
    return f'PageLayout.prototype.applyDragPhoto({js_element_for_slot(slot)}, 0, "{pid}")'


def js_do_personalize() -> str:
    return f"doPersonalize('{ACCEPT_SETTINGS_URL}');"
# endregion
