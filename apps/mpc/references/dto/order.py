import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from apps.mpc.references.web.constants import Cardstocks, PROJECT_MAX_SIZE


@dataclass
class DtoMpcCardImage:
    """One local image and the project slot(s) it fills.

    ``pid`` is MPC's image identity: the uppercase SHA-1 of the file bytes
    (their frontend computes the same hash), which lets the driver skip
    re-uploads and verify slot assignments.
    """
    file_path: Optional[str] = None
    slots: List[int] = field(default_factory=list)
    name: Optional[str] = None
    query: Optional[str] = None
    pid: Optional[str] = None

    def file_exists(self) -> bool:
        return bool(self.file_path) and Path(self.file_path).is_file()

    def generate_pid(self) -> Optional[str]:
        if self.pid or not self.file_exists():
            return self.pid
        self.pid = hashlib.sha1(Path(self.file_path).read_bytes()).hexdigest().upper()
        return self.pid


@dataclass
class DtoMpcOrderDetails:
    quantity: int = 0
    stock: str = Cardstocks.S30.value
    foil: bool = False


@dataclass
class DtoMpcOrder:
    """A complete MPC project definition: fronts by slot + one shared cardback."""
    name: Optional[str] = None
    details: DtoMpcOrderDetails = field(default_factory=DtoMpcOrderDetails)
    fronts: List[DtoMpcCardImage] = field(default_factory=list)
    cardback: Optional[DtoMpcCardImage] = None

    def validate(self) -> List[str]:
        """Return a list of problems (empty = valid)."""
        problems: List[str] = []
        if not 0 < self.details.quantity <= PROJECT_MAX_SIZE:
            problems.append(
                f"quantity {self.details.quantity} outside 1..{PROJECT_MAX_SIZE}")
        if self.details.stock not in {s.value for s in Cardstocks}:
            problems.append(f"unknown cardstock '{self.details.stock}'")
        slots = sorted(s for c in self.fronts for s in c.slots)
        if slots != list(range(self.details.quantity)):
            problems.append(
                f"front slots {slots[:5]}…{slots[-3:] if len(slots) > 5 else ''} "
                f"do not exactly cover 0..{self.details.quantity - 1}")
        problems.extend(
            f"missing front image: {c.file_path}" for c in self.fronts if not c.file_exists())
        if self.cardback is None or not self.cardback.file_exists():
            problems.append(
                f"missing cardback image: {self.cardback.file_path if self.cardback else None}")
        return problems


def build_orders(image_paths: Sequence[str],
                 cardback_path: str,
                 stock: str = Cardstocks.S30.value,
                 foil: bool = False,
                 name_prefix: str = "Project") -> List[DtoMpcOrder]:
    """Pack one image per slot into as many ≤612-card orders as needed.

    Images are taken in the given sequence order; each chunk's slots restart
    at 0 (every MPC project is independent). Returns orders named
    '<prefix> 1 of N', … when a split occurs, else just '<prefix>'.
    """
    chunks = [list(image_paths[i:i + PROJECT_MAX_SIZE])
              for i in range(0, len(image_paths), PROJECT_MAX_SIZE)]
    orders: List[DtoMpcOrder] = []
    for n, chunk in enumerate(chunks, start=1):
        name = f"{name_prefix} {n} of {len(chunks)}" if len(chunks) > 1 else name_prefix
        orders.append(DtoMpcOrder(
            name=name,
            details=DtoMpcOrderDetails(quantity=len(chunk), stock=stock, foil=foil),
            fronts=[DtoMpcCardImage(file_path=p, slots=[slot], name=Path(p).name)
                    for slot, p in enumerate(chunk)],
            cardback=DtoMpcCardImage(file_path=cardback_path, slots=[0], name=Path(cardback_path).name),
        ))
    return orders
