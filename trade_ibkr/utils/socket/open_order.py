import json
from typing import TYPE_CHECKING, TypeAlias, TypedDict

from trade_ibkr.enums import OrderSideConst
from ..contract import get_contract_identifier

if TYPE_CHECKING:
    from trade_ibkr.model import OpenOrder, OpenOrderBook


class OpenOrderData(TypedDict):
    identifier: int
    side: OrderSideConst
    quantity: float
    price: float


OpenOrderDict: TypeAlias = dict[int, list[OpenOrderData]]


def _from_open_orders(open_orders: list["OpenOrder"]) -> list[OpenOrderData]:
    return [
        {
            "identifier": get_contract_identifier(open_order.contract),
            "side": open_order.side,
            "quantity": float(open_order.quantity),
            "price": open_order.price,
        } for open_order in open_orders
    ]


def to_socket_message_open_order(open_order: "OpenOrderBook") -> str:
    data: OpenOrderDict = {
        identifier: _from_open_orders(open_orders)
        for identifier, open_orders in open_order.orders.items()
    }

    return json.dumps(data)
