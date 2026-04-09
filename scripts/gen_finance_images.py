#!/usr/bin/env python3
"""Generate 20 finance-themed PNG images (10 themes × 2 resolutions)."""

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
from matplotlib.colors import LinearSegmentedColormap, Normalize
import matplotlib.cm as cm
import os, zipfile, shutil
from io import BytesIO
from PIL import Image, PngImagePlugin

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "generated_finance_images")
os.makedirs(OUTPUT_DIR, exist_ok=True)

RESOLUTIONS = [(840, 478), (895, 200)]
MIN_BYTES = 1_048_576   # 1 MB
MAX_BYTES = 2_097_152   # 2 MB
DPI = 100
np.random.seed(2026)

# ── Palette ───────────────────────────────────────────────────────────────────
BG      = '#0d1117'
BG2     = '#161b22'
GRID    = '#21262d'
GREEN   = '#26a69a'
RED     = '#ef5350'
ACCENT  = '#f5a623'
BLUE    = '#58a6ff'
PURPLE  = '#bc8cff'
TEAL    = '#39d353'
TEXT    = '#e6edf3'
SUBTEXT = '#8b949e'

# ── Data helpers ──────────────────────────────────────────────────────────────

def gen_ohlc(n=60, start=100.0, vol=0.015):
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * np.exp(np.random.normal(0.0002, vol)))
    o, h, l, c = [], [], [], []
    for p in prices:
        op = p * np.exp(np.random.normal(0, vol / 3))
        cl = p * np.exp(np.random.normal(0, vol / 3))
        hi = max(op, cl) * np.exp(abs(np.random.normal(0, vol / 4)))
        lo = min(op, cl) * np.exp(-abs(np.random.normal(0, vol / 4)))
        o.append(op); h.append(hi); l.append(lo); c.append(cl)
    return np.array(o), np.array(h), np.array(l), np.array(c)

def moving_avg(arr, n):
    return np.convolve(arr, np.ones(n) / n, mode='valid')

def bollinger(arr, n=20, k=2):
    m = moving_avg(arr, n)
    std = np.array([arr[i:i+n].std() for i in range(len(arr) - n + 1)])
    return m, m + k * std, m - k * std

def gen_rsi(closes, period=14):
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.convolve(gains, np.ones(period) / period, mode='valid')
    avg_loss = np.convolve(losses, np.ones(period) / period, mode='valid')
    rs = np.where(avg_loss == 0, 100, avg_gain / (avg_loss + 1e-10))
    return 100 - 100 / (1 + rs)

def gen_macd(closes, fast=12, slow=26, signal=9):
    def ema(arr, n):
        result = np.zeros(len(arr))
        k = 2 / (n + 1)
        result[n - 1] = arr[:n].mean()
        for i in range(n, len(arr)):
            result[i] = arr[i] * k + result[i - 1] * (1 - k)
        return result[n - 1:]
    e_fast = ema(closes, fast)
    e_slow = ema(closes, slow)
    n = min(len(e_fast), len(e_slow))
    macd_line = e_fast[-n:] - e_slow[-n:]
    sig_line = moving_avg(macd_line, signal)
    hist = macd_line[signal - 1:] - sig_line
    return macd_line[signal - 1:], sig_line, hist

# ── Drawing helpers ───────────────────────────────────────────────────────────

def style_ax(ax, bg=BG):
    ax.set_facecolor(bg)
    ax.tick_params(colors=SUBTEXT, labelsize=6, length=3)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(True, color=GRID, linewidth=0.4, alpha=0.7, linestyle='--')

def draw_candles(ax, o, h, l, c, width=0.6):
    for i, (op, hi, lo, cl) in enumerate(zip(o, h, l, c)):
        color = GREEN if cl >= op else RED
        ax.plot([i, i], [lo, hi], color=color, lw=0.7, zorder=2, solid_capstyle='round')
        body_h = max(abs(cl - op), (hi - lo) * 0.01)
        rect = plt.Rectangle((i - width / 2, min(op, cl)), width, body_h,
                              facecolor=color, edgecolor='none', zorder=3, alpha=0.95)
        ax.add_patch(rect)
    ax.set_xlim(-1, len(o))

def label_price(ax, value, color=GREEN, fs=9):
    ax.text(0.98, 0.96, f'{value:,.2f}', transform=ax.transAxes,
            ha='right', va='top', fontsize=fs, color=color, fontweight='bold',
            bbox=dict(facecolor=BG2, edgecolor=GRID, boxstyle='round,pad=0.2', alpha=0.8))

def fig_ax(w, h, layout='single'):
    """Create figure with standard dark background."""
    fig = plt.figure(figsize=(w / DPI, h / DPI), dpi=DPI)
    fig.patch.set_facecolor(BG)
    return fig

# ── Theme 1: S&P 500 Candlestick ─────────────────────────────────────────────

def theme_sp500(w, h):
    fig = fig_ax(w, h)
    is_banner = h < 300
    n = 90 if not is_banner else 120

    o, hi, lo, c = gen_ohlc(n, 4800, 0.011)

    if is_banner:
        ax = fig.add_axes([0.04, 0.18, 0.94, 0.68])
    else:
        ax = fig.add_axes([0.06, 0.10, 0.91, 0.78])

    draw_candles(ax, o, hi, lo, c)
    style_ax(ax)

    if not is_banner:
        m20 = moving_avg(c, 20)
        m50 = moving_avg(c, 50)
        ax.plot(range(19, n), m20, color=ACCENT, lw=1.1, label='MA20', alpha=0.9)
        ax.plot(range(49, n), m50, color=BLUE, lw=1.1, label='MA50', alpha=0.9)
        ax.legend(loc='upper left', fontsize=6, facecolor=BG2, labelcolor=TEXT,
                  framealpha=0.8, edgecolor=GRID)

    ax.set_title('S&P 500  •  SPX  •  Daily', color=TEXT,
                 fontsize=7 if is_banner else 10, fontweight='bold', pad=3)
    label_price(ax, c[-1], GREEN if c[-1] > c[0] else RED, fs=7 if is_banner else 9)

    # Gradient fill under last close line
    ax.fill_between(range(n), lo.min(), c, alpha=0.04, color=GREEN)
    return fig

# ── Theme 2: EUR/USD Forex Candlestick ───────────────────────────────────────

def theme_eurusd(w, h):
    fig = fig_ax(w, h)
    is_banner = h < 300
    n = 80 if not is_banner else 110

    o, hi, lo, c = gen_ohlc(n, 1.0850, 0.004)

    if is_banner:
        ax = fig.add_axes([0.04, 0.18, 0.94, 0.68])
    else:
        gs = gridspec.GridSpec(2, 1, figure=fig, height_ratios=[3, 1],
                               hspace=0.05, left=0.07, right=0.97, top=0.93, bottom=0.06)
        ax = fig.add_subplot(gs[0])
        ax_vol = fig.add_subplot(gs[1], sharex=ax)

    draw_candles(ax, o, hi, lo, c)
    style_ax(ax)

    if not is_banner:
        mid, upper, lower = bollinger(c, 20, 2)
        xs = range(19, n)
        ax.plot(xs, upper, color=PURPLE, lw=0.8, alpha=0.7, linestyle='--', label='BB Upper')
        ax.plot(xs, mid,   color=PURPLE, lw=0.8, alpha=0.9, label='BB Mid')
        ax.plot(xs, lower, color=PURPLE, lw=0.8, alpha=0.7, linestyle='--', label='BB Lower')
        ax.fill_between(xs, lower, upper, alpha=0.05, color=PURPLE)
        ax.legend(loc='upper left', fontsize=5.5, facecolor=BG2, labelcolor=TEXT,
                  framealpha=0.8, edgecolor=GRID)

        # Volume bars
        vol = np.random.exponential(1e6, n)
        vol_colors = [GREEN if c[i] >= o[i] else RED for i in range(n)]
        ax_vol.bar(range(n), vol, color=vol_colors, alpha=0.7, width=0.6)
        style_ax(ax_vol)
        ax_vol.set_ylabel('Vol', color=SUBTEXT, fontsize=6)
        ax_vol.tick_params(axis='x', labelbottom=False)
        plt.setp(ax.get_xticklabels(), visible=False)

    ax.set_title('EUR/USD  •  Forex  •  4H', color=TEXT,
                 fontsize=7 if is_banner else 10, fontweight='bold', pad=3)
    label_price(ax, c[-1], GREEN if c[-1] > c[0] else RED, fs=7 if is_banner else 9)
    return fig

# ── Theme 3: BTC/USD Crypto ───────────────────────────────────────────────────

def theme_btcusd(w, h):
    fig = fig_ax(w, h)
    is_banner = h < 300
    n = 75 if not is_banner else 100

    o, hi, lo, c = gen_ohlc(n, 67000, 0.025)

    if is_banner:
        ax = fig.add_axes([0.05, 0.18, 0.93, 0.68])
    else:
        ax = fig.add_axes([0.08, 0.10, 0.89, 0.80])

    draw_candles(ax, o, hi, lo, c)
    style_ax(ax)

    # BTC-orange accent
    if not is_banner:
        m10 = moving_avg(c, 10)
        ax.plot(range(9, n), m10, color='#f7931a', lw=1.2, label='MA10', alpha=0.9)
        ax.fill_between(range(n), lo.min(), c, alpha=0.05, color='#f7931a')
        ax.legend(loc='upper left', fontsize=6, facecolor=BG2, labelcolor=TEXT,
                  framealpha=0.8, edgecolor=GRID)

    ax.set_title('BTC/USD  •  Bitcoin  •  1D', color='#f7931a',
                 fontsize=7 if is_banner else 10, fontweight='bold', pad=3)
    label_price(ax, c[-1], GREEN if c[-1] > c[0] else RED, fs=7 if is_banner else 9)
    return fig

# ── Theme 4: Multi-stock line comparison ─────────────────────────────────────

def theme_stocks_compare(w, h):
    fig = fig_ax(w, h)
    is_banner = h < 300
    n = 120

    stocks = {'AAPL': (182, 0.013, BLUE),
              'MSFT': (378, 0.012, GREEN),
              'NVDA': (875, 0.022, PURPLE),
              'AMZN': (185, 0.014, ACCENT),
              'TSLA': (245, 0.030, RED)}

    ax = fig.add_axes([0.06, 0.12, 0.91, 0.78] if not is_banner
                      else [0.04, 0.18, 0.94, 0.68])

    for name, (start, vol, color) in stocks.items():
        _, _, _, c = gen_ohlc(n, start, vol)
        normalized = (c / c[0] - 1) * 100  # % return
        ax.plot(normalized, color=color, lw=1.1 if not is_banner else 0.8,
                label=name, alpha=0.9)

    style_ax(ax)
    ax.axhline(0, color=SUBTEXT, lw=0.6, linestyle='--', alpha=0.5)
    ax.set_ylabel('Return %', color=SUBTEXT, fontsize=6)
    ax.set_title('Tech Stocks  •  Normalized Returns  •  YTD', color=TEXT,
                 fontsize=7 if is_banner else 10, fontweight='bold', pad=3)
    if not is_banner:
        ax.legend(loc='upper left', fontsize=6.5, facecolor=BG2, labelcolor=TEXT,
                  framealpha=0.8, edgecolor=GRID, ncol=2)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f'{v:+.1f}%'))
    return fig

# ── Theme 5: Forex Pairs Heatmap ─────────────────────────────────────────────

def theme_forex_heatmap(w, h):
    fig = fig_ax(w, h)
    currencies = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'NZD']
    n = len(currencies)
    data = np.random.uniform(-1.5, 1.5, (n, n))
    np.fill_diagonal(data, 0)

    ax = fig.add_axes([0.10, 0.10, 0.86, 0.80] if h >= 300
                      else [0.08, 0.18, 0.90, 0.72])

    cmap = LinearSegmentedColormap.from_list('rg', [RED, BG2, GREEN])
    im = ax.imshow(data, cmap=cmap, vmin=-1.5, vmax=1.5, aspect='auto')

    ax.set_xticks(range(n)); ax.set_xticklabels(currencies, color=TEXT, fontsize=6.5)
    ax.set_yticks(range(n)); ax.set_yticklabels(currencies, color=TEXT, fontsize=6.5)
    ax.tick_params(colors=SUBTEXT, length=0)

    for i in range(n):
        for j in range(n):
            val = data[i, j]
            color = 'white' if abs(val) > 0.5 else SUBTEXT
            ax.text(j, i, f'{val:+.2f}', ha='center', va='center',
                    fontsize=5 if h >= 300 else 4.5, color=color, fontweight='bold')

    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02, format='%.1f%%')
    ax.set_title('Forex Pair Returns  •  24H Change %', color=TEXT,
                 fontsize=7 if h < 300 else 10, fontweight='bold', pad=3)
    ax.set_facecolor(BG)
    return fig

# ── Theme 6: RSI Indicator ───────────────────────────────────────────────────

def theme_rsi(w, h):
    fig = fig_ax(w, h)
    is_banner = h < 300
    n = 100

    _, _, _, c = gen_ohlc(n, 250, 0.015)
    rsi = gen_rsi(c, 14)
    xs = range(len(rsi))

    if is_banner:
        ax = fig.add_axes([0.05, 0.18, 0.93, 0.68])
    else:
        gs = gridspec.GridSpec(2, 1, figure=fig, height_ratios=[2, 1],
                               hspace=0.08, left=0.07, right=0.97, top=0.93, bottom=0.06)
        ax_price = fig.add_subplot(gs[0])
        ax = fig.add_subplot(gs[1])

        ax_price.plot(c, color=BLUE, lw=1.1)
        style_ax(ax_price)
        ax_price.set_title('Stock Price + RSI(14)', color=TEXT,
                           fontsize=10, fontweight='bold', pad=3)
        ax_price.fill_between(range(n), c.min(), c, alpha=0.08, color=BLUE)
        ax_price.set_ylabel('Price', color=SUBTEXT, fontsize=6)
        plt.setp(ax_price.get_xticklabels(), visible=False)

    ax.plot(xs, rsi, color=PURPLE, lw=1.1, label='RSI(14)')
    ax.axhline(70, color=RED, lw=0.8, linestyle='--', alpha=0.7, label='Overbought')
    ax.axhline(30, color=GREEN, lw=0.8, linestyle='--', alpha=0.7, label='Oversold')
    ax.fill_between(xs, 70, np.minimum(rsi, 100), where=rsi >= 70, alpha=0.15, color=RED)
    ax.fill_between(xs, rsi, 30, where=rsi <= 30, alpha=0.15, color=GREEN)
    ax.set_ylim(0, 100)
    style_ax(ax)
    ax.set_ylabel('RSI', color=SUBTEXT, fontsize=6)
    if is_banner:
        ax.set_title('RSI(14) — Relative Strength Index', color=TEXT,
                     fontsize=7, fontweight='bold', pad=3)
    ax.legend(loc='upper right', fontsize=5.5, facecolor=BG2, labelcolor=TEXT,
              framealpha=0.8, edgecolor=GRID)
    return fig

# ── Theme 7: MACD ────────────────────────────────────────────────────────────

def theme_macd(w, h):
    fig = fig_ax(w, h)
    is_banner = h < 300
    n = 100

    _, _, _, c = gen_ohlc(n, 150, 0.013)
    macd_line, sig_line, hist = gen_macd(c)
    xs = range(len(hist))

    if is_banner:
        ax = fig.add_axes([0.05, 0.18, 0.93, 0.68])
    else:
        gs = gridspec.GridSpec(2, 1, figure=fig, height_ratios=[2, 1],
                               hspace=0.06, left=0.07, right=0.97, top=0.93, bottom=0.06)
        ax_price = fig.add_subplot(gs[0])
        ax = fig.add_subplot(gs[1])
        ax_price.plot(c, color=TEXT, lw=1, alpha=0.9)
        style_ax(ax_price)
        ax_price.fill_between(range(n), c.min(), c, alpha=0.08, color=BLUE)
        ax_price.set_title('Price + MACD (12,26,9)', color=TEXT,
                           fontsize=10, fontweight='bold', pad=3)
        plt.setp(ax_price.get_xticklabels(), visible=False)

    bar_colors = [GREEN if v >= 0 else RED for v in hist]
    ax.bar(xs, hist, color=bar_colors, alpha=0.75, width=0.7, label='Histogram')
    ax.plot(xs, macd_line[len(macd_line) - len(xs):], color=BLUE, lw=1, label='MACD')
    ax.plot(xs, sig_line, color=ACCENT, lw=1, linestyle='--', label='Signal')
    ax.axhline(0, color=SUBTEXT, lw=0.5)
    style_ax(ax)
    ax.set_ylabel('MACD', color=SUBTEXT, fontsize=6)
    if is_banner:
        ax.set_title('MACD (12,26,9)  •  Moving Average Convergence Divergence',
                     color=TEXT, fontsize=7, fontweight='bold', pad=3)
    ax.legend(loc='upper left', fontsize=5.5, facecolor=BG2, labelcolor=TEXT,
              framealpha=0.8, edgecolor=GRID)
    return fig

# ── Theme 8: Volume Profile ──────────────────────────────────────────────────

def theme_volume_profile(w, h):
    fig = fig_ax(w, h)
    is_banner = h < 300
    n = 80

    o, hi, lo, c = gen_ohlc(n, 320, 0.014)
    vol = np.random.exponential(2e6, n) * (1 + 0.5 * np.sin(np.linspace(0, 4 * np.pi, n)))

    if is_banner:
        ax = fig.add_axes([0.05, 0.18, 0.93, 0.68])
        bar_colors = [GREEN if c[i] >= o[i] else RED for i in range(n)]
        ax.bar(range(n), vol / 1e6, color=bar_colors, alpha=0.8, width=0.7)
        ax.plot(moving_avg(vol / 1e6, 10), color=ACCENT, lw=1.2, label='MA10 Vol')
        style_ax(ax)
        ax.set_title('Volume Profile  •  Daily', color=TEXT, fontsize=7,
                     fontweight='bold', pad=3)
        ax.set_ylabel('Vol (M)', color=SUBTEXT, fontsize=6)
        ax.legend(fontsize=5.5, facecolor=BG2, labelcolor=TEXT,
                  framealpha=0.8, edgecolor=GRID)
    else:
        gs = gridspec.GridSpec(2, 1, figure=fig, height_ratios=[3, 1],
                               hspace=0.05, left=0.07, right=0.97, top=0.93, bottom=0.06)
        ax_c = fig.add_subplot(gs[0])
        ax_v = fig.add_subplot(gs[1], sharex=ax_c)

        draw_candles(ax_c, o, hi, lo, c)
        style_ax(ax_c)
        ax_c.set_title('Volume Profile  •  OHLC + Volume', color=TEXT,
                       fontsize=10, fontweight='bold', pad=3)

        bar_colors = [GREEN if c[i] >= o[i] else RED for i in range(n)]
        ax_v.bar(range(n), vol / 1e6, color=bar_colors, alpha=0.75, width=0.7)
        ax_v.plot(moving_avg(vol / 1e6, 10), color=ACCENT, lw=1, label='Vol MA10')
        style_ax(ax_v)
        ax_v.set_ylabel('Vol M', color=SUBTEXT, fontsize=6)
        plt.setp(ax_c.get_xticklabels(), visible=False)
        ax_v.legend(fontsize=5.5, facecolor=BG2, labelcolor=TEXT,
                    framealpha=0.8, edgecolor=GRID)

    return fig

# ── Theme 9: Market Sector Heatmap ───────────────────────────────────────────

def theme_sector_heatmap(w, h):
    fig = fig_ax(w, h)
    is_banner = h < 300

    sectors = {
        'Technology': 28, 'Healthcare': 12, 'Financials': 13,
        'Consumer\nDiscret.': 10, 'Industrials': 9, 'Energy': 4,
        'Utilities': 3, 'Materials': 3, 'Real Estate': 3,
        'Consumer\nStaples': 6, 'Comms': 9
    }
    names = list(sectors.keys())
    weights = np.array(list(sectors.values()), dtype=float)
    changes = np.random.normal(0, 1.2, len(names))

    # Treemap-like grid
    ax = fig.add_axes([0.02, 0.10, 0.96, 0.82] if not is_banner
                      else [0.02, 0.08, 0.96, 0.84])
    ax.set_facecolor(BG)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.axis('off')

    cmap = LinearSegmentedColormap.from_list('rg', [RED, BG2, GREEN])
    norm = Normalize(vmin=-2, vmax=2)

    cols = 4 if not is_banner else 6
    rows = int(np.ceil(len(names) / cols))
    cell_w = 1.0 / cols
    cell_h = 1.0 / rows
    pad = 0.01

    for idx, (name, chg) in enumerate(zip(names, changes)):
        row, col = divmod(idx, cols)
        x0 = col * cell_w + pad
        y0 = 1 - (row + 1) * cell_h + pad
        bw = cell_w - 2 * pad
        bh = cell_h - 2 * pad
        color = cmap(norm(chg))
        rect = plt.Rectangle((x0, y0), bw, bh, facecolor=color,
                              edgecolor=BG, linewidth=1.5, zorder=1)
        ax.add_patch(rect)
        fs = 7 if not is_banner else 5.5
        ax.text(x0 + bw / 2, y0 + bh * 0.62, name, ha='center', va='center',
                fontsize=fs, color=TEXT, fontweight='bold', zorder=2,
                wrap=True, multialignment='center')
        ax.text(x0 + bw / 2, y0 + bh * 0.28, f'{chg:+.2f}%', ha='center', va='center',
                fontsize=fs - 0.5, color=TEXT, zorder=2)

    ax.set_title('S&P 500 Sector Heatmap  •  Daily Change', color=TEXT,
                 fontsize=7 if is_banner else 10, fontweight='bold', pad=3,
                 x=0.5, y=0.99)
    return fig

# ── Theme 10: Portfolio Donut + Bar ──────────────────────────────────────────

def theme_portfolio(w, h):
    fig = fig_ax(w, h)
    is_banner = h < 300

    assets = ['Stocks', 'Bonds', 'Crypto', 'Real Est.', 'Commodities', 'Cash']
    alloc = np.array([45, 20, 10, 12, 8, 5], dtype=float)
    colors = [BLUE, GREEN, ACCENT, PURPLE, TEAL, SUBTEXT]

    if is_banner:
        ax = fig.add_axes([0.05, 0.15, 0.42, 0.75])
        ax_b = fig.add_axes([0.55, 0.15, 0.40, 0.75])
    else:
        ax = fig.add_axes([0.03, 0.08, 0.42, 0.84])
        ax_b = fig.add_axes([0.52, 0.10, 0.44, 0.80])

    wedges, texts, autotexts = ax.pie(
        alloc, labels=assets, autopct='%1.1f%%',
        colors=colors, startangle=140,
        wedgeprops=dict(width=0.55, edgecolor=BG, linewidth=1.5),
        textprops=dict(color=TEXT, fontsize=6 if is_banner else 7.5)
    )
    for at in autotexts:
        at.set_fontsize(5.5 if is_banner else 7)
        at.set_color(BG)
        at.set_fontweight('bold')

    ax.set_facecolor(BG)

    # Simulated returns per asset
    returns = np.random.uniform(-5, 18, len(assets))
    bar_colors = [GREEN if r >= 0 else RED for r in returns]
    ax_b.barh(assets, returns, color=bar_colors, alpha=0.85, height=0.6)
    ax_b.axvline(0, color=SUBTEXT, lw=0.6)
    style_ax(ax_b)
    ax_b.set_xlabel('YTD Return %', color=SUBTEXT, fontsize=6)
    ax_b.tick_params(axis='y', labelsize=6, colors=TEXT)
    ax_b.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f'{v:+.0f}%'))

    fig.text(0.5, 0.97, 'Portfolio Allocation  •  YTD Performance',
             ha='center', va='top', fontsize=7 if is_banner else 10,
             color=TEXT, fontweight='bold')
    return fig

# ── Image generation ──────────────────────────────────────────────────────────

THEMES = [
    ('sp500_candlestick',   theme_sp500),
    ('eurusd_candlestick',  theme_eurusd),
    ('btcusd_candlestick',  theme_btcusd),
    ('stocks_compare',      theme_stocks_compare),
    ('forex_heatmap',       theme_forex_heatmap),
    ('rsi_indicator',       theme_rsi),
    ('macd_chart',          theme_macd),
    ('volume_profile',      theme_volume_profile),
    ('sector_heatmap',      theme_sector_heatmap),
    ('portfolio_chart',     theme_portfolio),
]

def render_and_save(theme_fn, w, h, path):
    fig = theme_fn(w, h)
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=DPI, bbox_inches='tight',
                pad_inches=0.05, facecolor=fig.get_facecolor())
    plt.close(fig)
    raw = buf.getvalue()

    # Open with PIL, resize exactly to target px
    img = Image.open(BytesIO(raw)).convert('RGB')
    img = img.resize((w, h), Image.LANCZOS)

    # Save uncompressed to maximise file size
    buf2 = BytesIO()
    img.save(buf2, format='PNG', compress_level=0)
    data = buf2.getvalue()

    # Pad with metadata if still under 1 MB
    if len(data) < MIN_BYTES:
        needed = MIN_BYTES - len(data) + 4096
        info = PngImagePlugin.PngInfo()
        info.add_text("Software", "HARQIS Finance Image Generator v1.0")
        info.add_text("Description", f"Finance theme {path} at {w}x{h}px high-res")
        info.add_text("RenderPad", "0" * needed)
        buf3 = BytesIO()
        img.save(buf3, format='PNG', pnginfo=info, compress_level=0)
        data = buf3.getvalue()

    with open(path, 'wb') as f:
        f.write(data)

    size_kb = len(data) / 1024
    print(f"  {'OK' if len(data) >= MIN_BYTES else 'SMALL':4s}  {size_kb:7.1f} KB  {path}")
    return len(data)

def main():
    generated = []
    print(f"Generating {len(THEMES) * len(RESOLUTIONS)} images...\n")

    for name, fn in THEMES:
        for (w, h) in RESOLUTIONS:
            suffix = f'{w}x{h}'
            filename = f'{name}_{suffix}.png'
            out_path = os.path.join(OUTPUT_DIR, filename)
            size = render_and_save(fn, w, h, out_path)
            generated.append(out_path)

    # ── Zip ───────────────────────────────────────────────────────────────────
    zip_path = os.path.join(OUTPUT_DIR, 'finance_images.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
        for p in generated:
            zf.write(p, os.path.basename(p))
    print(f"\nZip created: {zip_path}  ({os.path.getsize(zip_path)/1e6:.1f} MB)")

    # ── Move to /data (Windows: /c/data) ─────────────────────────────────────
    data_dir = '/c/data'
    dest = os.path.join(data_dir, 'finance_images.zip')
    os.makedirs(data_dir, exist_ok=True)
    shutil.copy2(zip_path, dest)
    print(f"Moved to:   {dest}")

    print(f"\nDone. {len(generated)} images generated.")

if __name__ == '__main__':
    main()
