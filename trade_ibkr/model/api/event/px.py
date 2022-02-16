from dataclasses import dataclass
from typing import Any, Callable, Coroutine, TypeAlias

from ibapi.contract import Contract, ContractDetails

from ...account import Account
from ...px_data import PxData


@dataclass(kw_only=True)
class OnPxDataUpdatedEvent:
    px_data: PxData
    account: Account
    contract: Contract

    is_new_bar: bool


OnPxDataUpdated: TypeAlias = Callable[[OnPxDataUpdatedEvent], None]


@dataclass(kw_only=True)
class OnPxDataUpdatedEventNoAccount:
    contract: ContractDetails
    px_data: PxData

    proc_sec: float

    def __str__(self):
        return f"({self.contract.underSymbol} {self.px_data.current_close:.2f} @ {self.proc_sec:.3f} s)"


OnPxDataUpdatedNoAccount: TypeAlias = Callable[[OnPxDataUpdatedEventNoAccount], Coroutine[Any, Any, None]]


@dataclass(kw_only=True)
class OnMarketDataReceivedEvent:
    contract: ContractDetails
    px: float

    def __str__(self):
        return f"({self.contract.underSymbol} - {self.px:.2f})"


OnMarketDataReceived: TypeAlias = Callable[[OnMarketDataReceivedEvent], Coroutine[Any, Any, None]]
