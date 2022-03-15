from collections import Counter
from datetime import datetime, timedelta
from typing import Generator, TYPE_CHECKING

import numpy as np
import pandas as pd
import talib
from ibapi.contract import ContractDetails
from pandas import DataFrame, DatetimeIndex, Series, to_datetime
from scipy.signal import argrelextrema

from trade_ibkr.calc import analyze_extrema, calc_support_resistance_levels
from trade_ibkr.const import DIFF_TREND_WINDOW, DIFF_TREND_WINDOW_DEFAULT, MARKET_TREND_WINDOW, console
from trade_ibkr.enums import CandlePos, PxDataCol
from trade_ibkr.utils import closest_diff, get_detailed_contract_identifier, print_log, print_warning

if TYPE_CHECKING:
    from trade_ibkr.model import BarDataDict


class PxData:
    def _proc_df_date(self):
        self.dataframe[PxDataCol.DATE] = to_datetime(
            self.dataframe[PxDataCol.EPOCH_SEC], utc=True, unit="s"
        ).dt.tz_convert("America/Chicago").dt.tz_localize(None)
        self.dataframe.set_index(DatetimeIndex(self.dataframe[PxDataCol.DATE]), inplace=True)

        self.dataframe[PxDataCol.DATE_MARKET] = to_datetime(np.where(
            self.dataframe[PxDataCol.DATE].dt.hour < 17,
            self.dataframe[PxDataCol.DATE].dt.date,
            self.dataframe[PxDataCol.DATE].dt.date + timedelta(days=1)
        ))

    def _proc_df_ema120(self):
        self.dataframe[PxDataCol.EMA_120] = talib.EMA(self.dataframe[PxDataCol.CLOSE], timeperiod=120)
        if ema_diff_window := MARKET_TREND_WINDOW.get(self.period_sec):
            self.dataframe[PxDataCol.EMA_120_TREND] = (
                    self.dataframe[PxDataCol.CLOSE] - self.dataframe[PxDataCol.EMA_120]
            ) \
                .ewm(span=ema_diff_window, adjust=False) \
                .mean()
        else:
            self.dataframe[PxDataCol.EMA_120_TREND] = np.full(len(self.dataframe.index), np.nan)
            print_warning(
                f"PxData of {self.contract.underSymbol} @ {self.period_sec} is "
                f"not calculating EMA 120 trend (trend window unspecified)"
            )

    def _proc_df_amplitude(self):
        self.dataframe[PxDataCol.AMPLITUDE_HL] = abs(self.dataframe[PxDataCol.HIGH] - self.dataframe[PxDataCol.LOW])
        self.dataframe[PxDataCol.AMPLITUDE_HL_EMA_10] = talib.EMA(
            self.dataframe[PxDataCol.AMPLITUDE_HL], timeperiod=10
        )
        self.dataframe[PxDataCol.AMPLITUDE_OC_EMA_10] = talib.EMA(
            abs(self.dataframe[PxDataCol.OPEN] - self.dataframe[PxDataCol.CLOSE]),
            timeperiod=10
        )

    def _proc_df_diff(self):
        self.dataframe[PxDataCol.DIFF] = self.dataframe[PxDataCol.CLOSE] - self.dataframe[PxDataCol.OPEN]
        if diff_trend_window := DIFF_TREND_WINDOW.get(self.period_sec):
            self.dataframe[PxDataCol.DIFF_SMA] = abs(self.dataframe[PxDataCol.DIFF]) \
                .rolling(diff_trend_window) \
                .mean()
        else:
            self.dataframe[PxDataCol.DIFF_SMA] = abs(self.dataframe[PxDataCol.DIFF]) \
                .rolling(DIFF_TREND_WINDOW_DEFAULT) \
                .mean()
            print_warning(
                f"PxData of {self.contract.underSymbol} @ {self.period_sec} is "
                f"using default diff SMA window"
            )

        self.dataframe[PxDataCol.DIFF_SMA_TREND] = self.dataframe[PxDataCol.DIFF_SMA].diff()

    def _proc_df_extrema(self):
        self.dataframe[PxDataCol.LOCAL_MIN] = self.dataframe.iloc[
            argrelextrema(self.dataframe[PxDataCol.LOW].values, np.less_equal, order=7)[0]
        ][PxDataCol.LOW]
        self.dataframe[PxDataCol.LOCAL_MAX] = self.dataframe.iloc[
            argrelextrema(self.dataframe[PxDataCol.HIGH].values, np.greater_equal, order=7)[0]
        ][PxDataCol.HIGH]

    def _proc_df_vwap(self):
        # Don't calculate VWAP if period is 3600s+ (meaningless)
        if self.period_sec >= 3600:
            self.dataframe[PxDataCol.VWAP] = np.full(len(self.dataframe.index), np.nan)
        else:
            self.dataframe[PxDataCol.PRICE_TIMES_VOLUME] = np.multiply(
                self.dataframe[PxDataCol.CLOSE],
                self.dataframe[PxDataCol.VOLUME]
            )
            mkt_data_group = self.dataframe.groupby(PxDataCol.DATE_MARKET)
            self.dataframe[PxDataCol.VWAP] = np.divide(
                mkt_data_group[PxDataCol.PRICE_TIMES_VOLUME].transform(pd.Series.cumsum),
                mkt_data_group[PxDataCol.VOLUME].transform(pd.Series.cumsum),
            )

    def _proc_df(self):
        self._proc_df_date()
        self._proc_df_ema120()
        self._proc_df_amplitude()
        self._proc_df_diff()
        self._proc_df_extrema()
        self._proc_df_vwap()

        # Remove NaNs
        self.dataframe = self.dataframe.fillna(np.nan).replace([np.nan], [None])

    def __init__(
            self, *,
            contract: ContractDetails,
            period_sec: int,
            bars: list["BarDataDict"] | None = None,
            dataframe: DataFrame | None = None,
    ):
        self.contract: ContractDetails = contract
        self.period_sec: int = period_sec
        self.dataframe: DataFrame = DataFrame(bars) if bars else dataframe

        if self.dataframe is None:
            raise ValueError("Must specify either `bars` or `dataframe` for PxData")

        self._proc_df()

        self.sr_levels_data = calc_support_resistance_levels(self.dataframe)
        self.extrema = analyze_extrema(self.dataframe)

    def get_px_sr_score(self, px: float) -> float:
        if not self.sr_levels_data.levels["window"] or not self.sr_levels_data.levels["fractal"]:
            return float("NaN")

        fractal = closest_diff(self.sr_levels_data.levels["fractal"], px) / self.get_current()[PxDataCol.CLOSE]
        window = closest_diff(self.sr_levels_data.levels["window"], px) / self.get_current()[PxDataCol.CLOSE]

        return fractal * window * 1E8

    def get_current(self) -> Series:
        return self.dataframe.iloc[-1]

    def get_last_n(self, n: int) -> Series:
        return self.dataframe.iloc[-n]

    def get_last_day_close(self) -> float | None:
        market_dates = self.dataframe[PxDataCol.DATE_MARKET].unique()

        if len(market_dates) < 2:
            raise ValueError(
                f"Px data of {self.contract.underSymbol} ({self.contract.contract.conId} @ {self.period_sec}) "
                f"only has a single market date: {market_dates}"
            )

        market_date_prev = market_dates[-2]

        last_day_df = self.dataframe[self.dataframe[PxDataCol.DATE_MARKET] == market_date_prev]

        if not len(last_day_df.index):
            return None

        last_day_last_entry = last_day_df.iloc[-1]
        return last_day_last_entry[PxDataCol.CLOSE]

    @staticmethod
    def _get_series_at(original: Series, candle_pos: CandlePos) -> Series:
        series = original.copy()

        match candle_pos:
            case CandlePos.OPEN:
                series[PxDataCol.HIGH] = original[PxDataCol.OPEN]
                series[PxDataCol.LOW] = original[PxDataCol.OPEN]
                series[PxDataCol.CLOSE] = original[PxDataCol.OPEN]
            case CandlePos.HIGH:
                series[PxDataCol.CLOSE] = original[PxDataCol.HIGH]
            case CandlePos.LOW:
                series[PxDataCol.CLOSE] = original[PxDataCol.LOW]
            case CandlePos.CLOSE:
                pass

        return series

    def get_dataframes_backtest(self, *, min_data_rows: int) -> Generator[tuple[DataFrame, bool], None, None]:
        """Returns (price data, is new px data)."""
        for row_count in range(min_data_rows, len(self.dataframe.index)):
            sub_df: DataFrame = self.dataframe.iloc[:row_count]

            sub_df_modified = sub_df.copy()

            for idx, pos in enumerate((CandlePos.OPEN, CandlePos.HIGH, CandlePos.LOW, CandlePos.CLOSE)):
                sub_df_modified.iloc[-1] = self._get_series_at(sub_df.iloc[-1], pos)
                yield sub_df_modified, idx == 0

    def print_current_sr_level_position(self):
        current_datetime = datetime.now().strftime("%H:%M:%S")
        current_close = self.get_current()[PxDataCol.CLOSE]

        sr_levels = Counter(self.sr_levels_data.levels["window"] + self.sr_levels_data.levels["fractal"])
        sr_level_txt = " / ".join(f"{key}{' !' if sr_levels[key] > 1 else ''}" for key in sorted(sr_levels.keys()))

        console.print(current_datetime)
        console.print(
            f"{current_close:9.2f} | "
            # f"{executions_df.side:12} | "
            # f"{executions_df.avg_px:9.2f} | "
            # f"{px_diff:9.2f} | "
            f"\n{sr_level_txt}",
        )

    def save_to_file(self):
        file_path = f"data-{self.contract_identifier}@{self.period_sec}.csv"
        self.dataframe.to_csv(file_path)

        print_log(f"[yellow]Px data saved to {file_path}[/yellow]")

        return file_path

    @property
    def earliest_time(self) -> datetime:
        return self.dataframe[PxDataCol.DATE].min()

    @property
    def latest_time(self) -> datetime:
        return self.dataframe[PxDataCol.DATE].max()

    @property
    def current_close(self) -> float:
        return self.get_current()[PxDataCol.CLOSE]

    @property
    def current_ampl_hl_ema10(self) -> float:
        return self.get_current()[PxDataCol.AMPLITUDE_HL_EMA_10]

    @property
    def contract_identifier(self) -> int:
        return get_detailed_contract_identifier(self.contract)

    @property
    def unique_identifier(self) -> str:
        return f"{self.contract_identifier}@{self.period_sec}"
