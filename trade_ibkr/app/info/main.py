import time

from trade_ibkr.obj import start_app_info
from trade_ibkr.utils import make_futures_contract, print_log
from .handler import on_market_data_received, on_px_updated, register_handlers
from .socket import register_socket_endpoints


def prepare_info_app():
    app, _ = start_app_info(is_demo=True)

    contract_mnq = make_futures_contract("MNQH2", "GLOBEX")
    contract_mym = make_futures_contract("MYM  MAR 22", "ECBOT")

    px_data_req_ids: list[int] = [
        req_id_same_contract for req_ids_cross_contract
        in [
            app.get_px_data_keep_update(
                contract=contract_mnq,
                duration="86400 S",
                bar_sizes=["1 min"],
                period_secs=[60],
                on_px_data_updated=on_px_updated,
                on_market_data_received=on_market_data_received,
            ),
            app.get_px_data_keep_update(
                contract=contract_mym,
                duration="86400 S",
                bar_sizes=["1 min"],
                period_secs=[60],
                on_px_data_updated=on_px_updated,
                on_market_data_received=on_market_data_received,
            ),
        ]
        for req_id_same_contract in req_ids_cross_contract
    ]

    while not app.is_all_px_data_ready(px_data_req_ids):
        time.sleep(0.25)
        print_log("[System] Waiting the initial data to ready")

    register_socket_endpoints(app, px_data_req_ids)
    register_handlers(app, px_data_req_ids)
