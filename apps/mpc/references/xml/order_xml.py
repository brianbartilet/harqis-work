"""Read/write mpc-autofill-compatible order XML files.

The schema mirrors chilli-axe/mpc-autofill's desktop-tool order format so
orders produced here can also be fed to the upstream tool (and vice versa for
local-file orders):

    <order>
      <details>
        <quantity>612</quantity>
        <stock>(S30) Standard Smooth</stock>
        <foil>false</foil>
      </details>
      <fronts>
        <card>
          <id>./cards/0001-bulbasaur.png</id>
          <sourceType>Local File</sourceType>
          <slots>0</slots>
          <name>0001-bulbasaur.png</name>
          <query></query>
        </card>
        ...
      </fronts>
      <cardback>./cards/cardback.png</cardback>
    </order>

Local files carry their path in ``<id>`` with ``sourceType`` "Local File";
the upstream tool skips its Google Drive download when the file already
exists on disk, which is exactly this case.
"""
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from apps.mpc.references.dto.order import DtoMpcCardImage, DtoMpcOrder, DtoMpcOrderDetails

SOURCE_TYPE_LOCAL = "Local File"


def write_order_xml(order: DtoMpcOrder, output_path: str) -> str:
    """Serialise ``order`` to ``output_path`` and return the path."""
    root = ET.Element("order")

    details = ET.SubElement(root, "details")
    ET.SubElement(details, "quantity").text = str(order.details.quantity)
    ET.SubElement(details, "stock").text = order.details.stock
    ET.SubElement(details, "foil").text = "true" if order.details.foil else "false"

    fronts = ET.SubElement(root, "fronts")
    for card in order.fronts:
        el = ET.SubElement(fronts, "card")
        ET.SubElement(el, "id").text = card.file_path
        ET.SubElement(el, "sourceType").text = SOURCE_TYPE_LOCAL
        ET.SubElement(el, "slots").text = ",".join(str(s) for s in sorted(card.slots))
        ET.SubElement(el, "name").text = card.name or Path(card.file_path or "").name
        ET.SubElement(el, "query").text = card.query or ""

    ET.SubElement(root, "cardback").text = order.cardback.file_path if order.cardback else ""

    ET.indent(root)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)
    return output_path


def read_order_xml(xml_path: str) -> DtoMpcOrder:
    """Parse an order XML back into a :class:`DtoMpcOrder`."""
    root = ET.parse(xml_path).getroot()

    details_el = root.find("details")
    details = DtoMpcOrderDetails(
        quantity=int(details_el.findtext("quantity", "0")),
        stock=details_el.findtext("stock", DtoMpcOrderDetails().stock),
        foil=details_el.findtext("foil", "false").strip().lower() == "true",
    )

    fronts: List[DtoMpcCardImage] = []
    for el in root.findall("fronts/card"):
        slots_text = (el.findtext("slots") or "").strip()
        fronts.append(DtoMpcCardImage(
            file_path=el.findtext("id"),
            slots=[int(s) for s in slots_text.split(",") if s != ""],
            name=el.findtext("name"),
            query=el.findtext("query") or None,
        ))

    cardback_path = (root.findtext("cardback") or "").strip()
    cardback = DtoMpcCardImage(file_path=cardback_path, slots=[0]) if cardback_path else None

    return DtoMpcOrder(name=Path(xml_path).stem, details=details, fronts=fronts, cardback=cardback)
