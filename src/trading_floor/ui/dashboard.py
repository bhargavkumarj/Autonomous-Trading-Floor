"""The operator dashboard: four live panels, one per trader.

Reads the database directly, writes nothing. The trading floor is a separate
process, so you can start, stop and restart this without touching a run in
progress — and if it crashes, the traders keep trading.

Two refresh rates, deliberately:

* the **log panel** ticks twice a second, because the point of the dashboard is
  watching an agent think in something close to real time;
* everything else (valuation, chart, tables) ticks every two minutes, because
  each refresh re-prices the whole portfolio, and doing that twice a second would
  hammer the market data API for no benefit.

The log tick also compares against the previous render and returns
``gr.update()`` — a no-op — when nothing changed, so an idle floor costs almost
nothing to display.
"""

from __future__ import annotations

import gradio as gr
import pandas as pd
import plotly.express as px

from trading_floor.core.accounts import Account
from trading_floor.core.database import read_log
from trading_floor.floor import LASTNAMES, NAMES, SHORT_MODEL_NAMES
from trading_floor.ui.theme import CSS, JS, LOG_COLORS, Color

LOG_LINES = 13
LOG_REFRESH_SECONDS = 0.5
DATA_REFRESH_SECONDS = 120


class TraderPanel:
    """The data behind one trader's column, re-read from the database on refresh."""

    def __init__(self, name: str, lastname: str, model_name: str) -> None:
        self.name = name
        self.lastname = lastname
        self.model_name = model_name
        self.account = Account.get(name)

    def reload(self) -> None:
        self.account = Account.get(self.name)

    def title_html(self) -> str:
        return (
            f"<div style='text-align:center;font-size:34px;'>{self.name}"
            f"<span style='color:#ccc;font-size:24px;'> ({self.model_name}) - {self.lastname}</span></div>"
        )

    def strategy(self) -> str:
        return self.account.get_strategy()

    def portfolio_value_html(self) -> str:
        value = self.account.calculate_portfolio_value() or 0.0
        pnl = self.account.calculate_profit_loss(value) or 0.0
        color = "green" if pnl >= 0 else "red"
        sign = "+" if pnl >= 0 else "-"
        return (
            f"<div style='text-align:center;background-color:{color};'>"
            f"<span style='font-size:32px'>${value:,.0f}</span>"
            f"<span style='font-size:24px'>&nbsp;&nbsp;&nbsp;{sign}${abs(pnl):,.0f}</span></div>"
        )

    def equity_curve(self):
        df = pd.DataFrame(self.account.portfolio_value_time_series, columns=["datetime", "value"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        fig = px.line(df, x="datetime", y="value")
        fig.update_layout(
            height=300,
            margin=dict(l=40, r=20, t=20, b=40),
            xaxis_title=None,
            yaxis_title=None,
            paper_bgcolor="#bbb",
            plot_bgcolor="#dde",
        )
        fig.update_xaxes(tickformat="%m/%d", tickangle=45, tickfont=dict(size=8))
        fig.update_yaxes(tickfont=dict(size=8), tickformat=",.0f")
        return fig

    def holdings_df(self) -> pd.DataFrame:
        holdings = self.account.get_holdings()
        if not holdings:
            return pd.DataFrame(columns=["Symbol", "Quantity"])
        return pd.DataFrame(
            [{"Symbol": symbol, "Quantity": quantity} for symbol, quantity in holdings.items()]
        )

    def transactions_df(self) -> pd.DataFrame:
        transactions = self.account.list_transactions()
        if not transactions:
            return pd.DataFrame(columns=["Timestamp", "Symbol", "Quantity", "Price", "Rationale"])
        return pd.DataFrame(transactions)

    def logs_html(self, previous: str | None = None):
        """The tail of this trader's activity log, or a no-op if it is unchanged."""
        lines = "".join(
            f"<span style='color:{LOG_COLORS.get(kind, Color.WHITE).value}'>"
            f"{timestamp} : [{kind}] {message}</span><br/>"
            for timestamp, kind, message in read_log(self.name, last_n=LOG_LINES)
        )
        html = f"<div style='height:250px; overflow-y:auto;'>{lines}</div>"
        return html if html != previous else gr.update()


class TraderColumn:
    """One trader's Gradio column and the timers that keep it live."""

    def __init__(self, panel: TraderPanel) -> None:
        self.panel = panel

    def build(self) -> None:
        with gr.Column():
            gr.HTML(self.panel.title_html())
            with gr.Row():
                self.value = gr.HTML(self.panel.portfolio_value_html)
            with gr.Row():
                self.chart = gr.Plot(self.panel.equity_curve, container=True, show_label=False)
            with gr.Row(variant="panel"):
                self.log = gr.HTML(self.panel.logs_html)
            with gr.Row():
                self.holdings = gr.Dataframe(
                    value=self.panel.holdings_df,
                    label="Holdings",
                    headers=["Symbol", "Quantity"],
                    row_count=5,
                    column_count=2,
                    max_height=300,
                    elem_classes=["dataframe-fix-small"],
                )
            with gr.Row():
                self.transactions = gr.Dataframe(
                    value=self.panel.transactions_df,
                    label="Recent Transactions",
                    headers=["Timestamp", "Symbol", "Quantity", "Price", "Rationale"],
                    row_count=5,
                    column_count=5,
                    max_height=300,
                    elem_classes=["dataframe-fix"],
                )

        gr.Timer(DATA_REFRESH_SECONDS).tick(
            fn=self.refresh,
            outputs=[self.value, self.chart, self.holdings, self.transactions],
            show_progress="hidden",
            queue=False,
        )
        gr.Timer(LOG_REFRESH_SECONDS).tick(
            fn=self.panel.logs_html,
            inputs=[self.log],
            outputs=[self.log],
            show_progress="hidden",
            queue=False,
        )

    def refresh(self):
        self.panel.reload()
        return (
            self.panel.portfolio_value_html(),
            self.panel.equity_curve(),
            self.panel.holdings_df(),
            self.panel.transactions_df(),
        )


def create_ui() -> gr.Blocks:
    """The whole dashboard: one column per trader, side by side."""
    columns = [
        TraderColumn(TraderPanel(name, lastname, model_name))
        for name, lastname, model_name in zip(NAMES, LASTNAMES, SHORT_MODEL_NAMES)
    ]
    with gr.Blocks(title="Trading Floor", fill_width=True) as ui:
        with gr.Row():
            for column in columns:
                column.build()
    return ui


def main() -> None:
    create_ui().launch(
        theme=gr.themes.Default(primary_hue="sky"), css=CSS, js=JS, inbrowser=True
    )


if __name__ == "__main__":
    main()
