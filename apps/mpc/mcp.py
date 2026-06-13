import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("harqis-mcp.mpc")

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def register_mpc_tools(mcp: FastMCP):

    @mcp.tool()
    def build_mpc_order_xml(fronts_dir: str, cardback_path: str, output_path: str,
                            stock: str = "(S30) Standard Smooth",
                            name_prefix: str = "Project") -> list[dict]:
        """Build mpc-autofill-compatible order XML(s) from a directory of card fronts.

        Images are slotted in filename sort order; orders exceeding MPC's
        612-card cap are split automatically ('<output stem>_1.xml', …).

        Args:
            fronts_dir:    Directory of front images (.png/.jpg), one card per file.
            cardback_path: The single shared cardback image.
            output_path:   Target XML path (used as the stem when splitting).
            stock:         MPC cardstock — '(S30) Standard Smooth' (default),
                           '(S33) Superior Smooth', '(M31) Linen', '(P10) Plastic'.
            name_prefix:   MPC project name prefix (max 32 chars on site).
        """
        from apps.mpc.references.dto.order import build_orders
        from apps.mpc.references.xml.order_xml import write_order_xml

        logger.info("Tool called: build_mpc_order_xml fronts_dir=%s", fronts_dir)
        images = sorted(str(p) for p in Path(fronts_dir).iterdir()
                        if p.suffix.lower() in _IMAGE_EXTENSIONS)
        orders = build_orders(images, cardback_path, stock=stock, name_prefix=name_prefix)
        out = Path(output_path)
        results = []
        for n, order in enumerate(orders, start=1):
            path = str(out if len(orders) == 1
                       else out.with_name(f"{out.stem}_{n}{out.suffix or '.xml'}"))
            write_order_xml(order, path)
            results.append({"xml_path": path, "name": order.name,
                            "quantity": order.details.quantity,
                            "problems": order.validate()})
        logger.info("build_mpc_order_xml wrote %d order file(s)", len(results))
        return results

    @mcp.tool()
    def validate_mpc_order(xml_path: str) -> dict:
        """Validate an mpc-autofill order XML: slot coverage, image files on
        disk, cardback presence, and the 612-card cap.

        Args:
            xml_path: Path to the order XML file.
        """
        from apps.mpc.references.xml.order_xml import read_order_xml

        logger.info("Tool called: validate_mpc_order xml_path=%s", xml_path)
        order = read_order_xml(xml_path)
        problems = order.validate()
        result = {
            "name": order.name,
            "quantity": order.details.quantity,
            "stock": order.details.stock,
            "foil": order.details.foil,
            "fronts": len(order.fronts),
            "cardback": order.cardback.file_path if order.cardback else None,
            "valid": not problems,
            "problems": problems,
        }
        logger.info("validate_mpc_order: valid=%s (%d problem(s))", result["valid"], len(problems))
        return result
