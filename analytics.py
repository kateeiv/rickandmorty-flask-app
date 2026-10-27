"""Невеликий аналіз збережених персонажів з візуалізацією через matplotlib."""
import base64
import io
from collections import Counter

import matplotlib

matplotlib.use("Agg")  # без GUI - працює всередині веб-сервера
import matplotlib.pyplot as plt  # noqa: E402

GREEN, DARK = "#97ce4c", "#1b1f24"
STATUS_COLORS = {"Alive": "#55cc44", "Dead": "#d63d2e", "unknown": "#9e9e9e"}


def _to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _style(fig, ax, title):
    fig.patch.set_facecolor(DARK)
    ax.set_facecolor(DARK)
    ax.set_title(title, color="white", fontsize=13, pad=12)
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("#555")


def summary(characters):
    """Підрахунок для JSON/HTML: кількість за статусом, видом і статтю."""
    return {
        "total": len(characters),
        "by_status": dict(Counter(c["status"] for c in characters)),
        "by_species": dict(Counter(c["species"] for c in characters).most_common()),
        "by_gender": dict(Counter(c["gender"] for c in characters)),
        "avg_episodes": round(sum(c["episode_count"] for c in characters) / len(characters), 1)
        if characters else 0,
    }


def build_charts(characters):
    """Повертає {'status': b64, 'species': b64, 'episodes': b64} або {} якщо даних немає."""
    if not characters:
        return {}
    charts = {}

    # 1. Статуси - кругова діаграма
    by_status = Counter(c["status"] for c in characters)
    fig, ax = plt.subplots(figsize=(5, 4))
    _style(fig, ax, "Розподіл за статусом")
    ax.pie(by_status.values(), labels=by_status.keys(), autopct="%1.0f%%",
           colors=[STATUS_COLORS.get(k, GREEN) for k in by_status],
           textprops={"color": "white"}, wedgeprops={"edgecolor": DARK})
    charts["status"] = _to_base64(fig)

    # 2. Види - горизонтальна стовпчаста (топ-8)
    top = Counter(c["species"] for c in characters).most_common(8)[::-1]
    fig, ax = plt.subplots(figsize=(5, 4))
    _style(fig, ax, "Види персонажів (топ-8)")
    ax.barh([s for s, _ in top], [n for _, n in top], color=GREEN)
    ax.xaxis.get_major_locator().set_params(integer=True)
    charts["species"] = _to_base64(fig)

    # 3. Кількість епізодів - топ-10 персонажів
    top_ep = sorted(characters, key=lambda c: c["episode_count"], reverse=True)[:10][::-1]
    fig, ax = plt.subplots(figsize=(10, 4))
    _style(fig, ax, "Персонажі з найбільшою кількістю епізодів")
    ax.barh([c["name"] for c in top_ep], [c["episode_count"] for c in top_ep], color="#00b0c8")
    charts["episodes"] = _to_base64(fig)
    return charts
