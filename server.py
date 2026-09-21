"""Servidor MCP para o Grand Exchange de RuneScape (OSRS e RS3).

OSRS: API de preços em tempo real da Wiki (preço de compra e de venda separados).
RS3:  API da Weird Gloop (um preço médio atualizado cerca de 1x por dia + volume).
      Não existe preço em tempo real nem spread compra/venda no RS3, por isso
      flip_finder e alch_profit são só para OSRS.

Ferramentas:
  - search_item      pesquisa itens por nome (OSRS e RS3)
  - get_price        preço atual (OSRS: com margem de flip; RS3: preço e imposto)
  - price_history    histórico de preços e resumo da tendência (OSRS e RS3)
  - flip_finder      melhores flips para um capital (só OSRS)
  - alch_profit      itens em que o high alch dá lucro (só OSRS)
  - calcular_flip    calculadora manual de lucro com imposto (OSRS e RS3)
"""

import os
import time
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastmcp import FastMCP

mcp = FastMCP("GE RuneScape")

# A Wiki pede um User-Agent descritivo. Troca pelo teu contacto.
HEADERS = {"User-Agent": "ge-runescape-mcp - projeto pessoal - o-teu-email@exemplo.com"}

OSRS = "https://prices.runescape.wiki/api/v1/osrs"  # tempo real, só OSRS
WG = "https://api.weirdgloop.org/exchange/history"  # Weird Gloop, RS3 e OSRS
RS3_MODULES = "https://runescape.wiki/w/Module:{}/data.json"  # dados em massa do RS3

Jogo = Literal["osrs", "rs3"]

# Bonds não pagam imposto. Existem outros itens isentos (ferramentas básicas, etc.)
# que não estão nesta lista, por isso o imposto pode estar ligeiramente
# sobrestimado nesses casos.
BONDS = {"osrs": {13190}, "rs3": {29492}}
NATURE_RUNE_ID = 561
TAX_CAP = 5_000_000  # confirmado para OSRS; assumido igual no RS3

# Cache simples em memória: (momento, dados)
_cache: dict[str, tuple[float, object]] = {}


async def _get(url: str, params: dict | None = None, ttl: int = 0):
    chave = f"{url}?{params}"
    agora = time.time()
    if ttl and chave in _cache and agora - _cache[chave][0] < ttl:
        return _cache[chave][1]
    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        dados = r.json()
    if ttl:
        _cache[chave] = (agora, dados)
    return dados


def _imposto(preco_venda: int, jogo: str, item_id: int | None = None) -> int:
    """Imposto do GE: 2% por item, arredondado para baixo, máximo 5M.
    Isentos: bonds e preços abaixo de 50 gp (no RS3, 50 gp ou menos)."""
    if item_id in BONDS[jogo]:
        return 0
    if preco_venda < 50 or (jogo == "rs3" and preco_venda == 50):
        return 0
    return min(preco_venda * 2 // 100, TAX_CAP)


def _resumo(precos: list[float]) -> dict:
    if len(precos) < 2:
        return {}
    return {
        "minimo": round(min(precos)),
        "maximo": round(max(precos)),
        "media": round(sum(precos) / len(precos)),
        "variacao_pct": round((precos[-1] - precos[0]) / precos[0] * 100, 2),
    }


# ---------------------------------------------------------------- RS3 (Weird Gloop)


async def _rs3_ids() -> dict[str, int]:
    """Mapa nome -> id de todos os itens do GE do RS3."""
    dados = await _get(RS3_MODULES.format("GEIDs"), {"action": "raw"}, ttl=3600)
    return {n: i for n, i in dados.items() if isinstance(i, int)}


async def _rs3_limites() -> dict[str, int]:
    """Mapa nome -> limite de compra (melhor esforço; vazio se falhar)."""
    try:
        dados = await _get(RS3_MODULES.format("GELimits"), {"action": "raw"}, ttl=3600)
        return {n: v for n, v in dados.items() if isinstance(v, int)}
    except httpx.HTTPError:
        return {}


async def _rs3_latest(item_id: int) -> dict | None:
    d = await _get(f"{WG}/rs/latest", {"id": item_id}, ttl=300)
    p = d.get(str(item_id)) if isinstance(d, dict) else None
    return p if p and p.get("price") is not None else None


async def _rs3_search(nome: str, limite: int) -> list[dict]:
    try:
        ids = await _rs3_ids()
    except (httpx.HTTPError, ValueError):
        # Plano B: procura pelo nome exato (sensível a maiúsculas) na Weird Gloop.
        d = await _get(f"{WG}/rs/latest", {"name": nome}, ttl=300)
        return [
            {"name": n, "id": int(v["id"]), "price": v.get("price")}
            for n, v in d.items()
            if isinstance(v, dict) and "id" in v
        ]
    alvo = nome.lower()
    limites = await _rs3_limites()
    return [
        {"name": n, "id": i, "limit": limites.get(n)}
        for n, i in ids.items()
        if alvo in n.lower()
    ][:limite]


# ---------------------------------------------------------------- Ferramentas


@mcp.tool()
async def search_item(nome: str, jogo: Jogo = "osrs", limite: int = 10) -> list[dict]:
    """Procura itens pelo nome (parte do nome chega). Devolve id e limite de
    compra. No OSRS também devolve members e valores de alch. No RS3, se a lista
    de itens não estiver acessível, só funciona com o nome exato."""
    if jogo == "rs3":
        return await _rs3_search(nome, limite)
    mapping = await _get(f"{OSRS}/mapping", ttl=3600)
    alvo = nome.lower()
    return [i for i in mapping if alvo in i["name"].lower()][:limite]


@mcp.tool()
async def get_price(item_id: int, jogo: Jogo = "osrs") -> dict:
    """Preço atual de um item.
    OSRS: insta-buy (high), insta-sell (low) e margem de flip líquida (compra
      ao 'low', vende ao 'high', com imposto descontado).
    RS3: preço médio do GE (atualizado cerca de 1x por dia), volume e o valor
      líquido depois de imposto. O RS3 não tem spread compra/venda."""
    if jogo == "rs3":
        p = await _rs3_latest(item_id)
        if not p:
            return {"erro": "Sem dados de preço para este item."}
        preco = int(p["price"])
        imposto = _imposto(preco, "rs3", item_id)
        return {
            "preco": preco,
            "volume": p.get("volume"),
            "atualizado_em": p.get("timestamp"),
            "imposto_ao_vender": imposto,
            "liquido_ao_vender": preco - imposto,
            "nota": "RS3 só tem um preço médio por dia, sem preço de compra/venda separados.",
        }

    latest = (await _get(f"{OSRS}/latest", {"id": item_id}, ttl=30))["data"]
    p = latest.get(str(item_id))
    if not p or p["high"] is None or p["low"] is None:
        return {"erro": "Sem dados de preço para este item."}

    mapping = await _get(f"{OSRS}/mapping", ttl=3600)
    info = next((i for i in mapping if i["id"] == item_id), {})

    compra, venda = p["low"], p["high"]
    imposto = _imposto(venda, "osrs", item_id)
    margem = venda - imposto - compra
    return {
        "nome": info.get("name"),
        "compra_instantanea": p["high"],
        "venda_instantanea": p["low"],
        "margem_bruta": venda - compra,
        "imposto": imposto,
        "margem_liquida": margem,
        "roi_pct": round(margem / compra * 100, 2) if compra else None,
        "limite_compra_4h": info.get("limit"),
        "high_alch": info.get("highalch"),
    }


@mcp.tool()
async def price_history(
    item_id: int,
    jogo: Jogo = "osrs",
    intervalo: Literal["5m", "1h", "6h", "24h"] = "1h",
    pontos: int = 24,
) -> dict:
    """Histórico de preços de um item, com resumo da tendência.
    OSRS: 'intervalo' é o tamanho de cada ponto e 'pontos' quantos devolver.
    RS3: os dados são diários (últimos 90 dias); 'intervalo' é ignorado e
      'pontos' é o número de dias mais recentes."""
    if jogo == "rs3":
        d = await _get(f"{WG}/rs/last90d", {"id": item_id}, ttl=600)
        bruto = d.get(str(item_id)) if isinstance(d, dict) else None
        if not bruto:
            return {"erro": "Sem histórico para este item."}
        serie = []
        for ponto in bruto[-pontos:]:
            ts = ponto[0] / 1000 if ponto[0] > 1e11 else ponto[0]  # ms ou s
            serie.append(
                {
                    "data_utc": datetime.fromtimestamp(ts, timezone.utc).date().isoformat(),
                    "preco": ponto[1],
                    "volume": ponto[2] if len(ponto) > 2 else None,
                }
            )
        return {"resumo": _resumo([s["preco"] for s in serie if s["preco"]]), "serie": serie}

    dados = (
        await _get(
            f"{OSRS}/timeseries", {"timestep": intervalo, "id": item_id}, ttl=60
        )
    )["data"][-pontos:]
    serie = [
        {
            "hora_utc": datetime.fromtimestamp(d["timestamp"], timezone.utc).isoformat(),
            "high": d["avgHighPrice"],
            "low": d["avgLowPrice"],
            "volume": (d["highPriceVolume"] or 0) + (d["lowPriceVolume"] or 0),
        }
        for d in dados
    ]
    medios = [(d["high"] + d["low"]) / 2 for d in serie if d["high"] and d["low"]]
    return {"resumo": _resumo(medios), "serie": serie}


@mcp.tool()
async def flip_finder(
    capital: int = 1_000_000,
    volume_minimo: int = 1000,
    top: int = 10,
    preco_min: int = 0,
    preco_max: int | None = None,
    so_members: bool | None = None,
    margem_min: int = 1,
    roi_min: float = 0.0,
    ordenar_por: Literal["lucro_potencial", "margem_liquida", "roi", "volume"] = "lucro_potencial",
) -> list[dict]:
    """Procura os melhores flips no OSRS (o RS3 não tem preços de compra e venda
    separados, por isso não dá para fazer isto lá). Compra ao preço 'low', vende
    ao 'high', com imposto descontado.

    capital: gp disponíveis (define quantas unidades dá para comprar).
    volume_minimo: volume mínimo na última hora no LADO MAIS FRACO (compra ou
      venda), para evitar itens que só se mexem num sentido.
    preco_min / preco_max: intervalo do preço de compra.
    so_members: True só members, False só free-to-play, None ambos.
    margem_min: margem líquida mínima por unidade (gp).
    roi_min: retorno mínimo em % (margem / preço de compra).
    ordenar_por: lucro_potencial, margem_liquida, roi ou volume.
    """
    mapping = await _get(f"{OSRS}/mapping", ttl=3600)
    latest = (await _get(f"{OSRS}/latest", ttl=30))["data"]
    hora = (await _get(f"{OSRS}/1h", ttl=60))["data"]
    teto = preco_max if preco_max is not None else capital

    resultados = []
    for item in mapping:
        id_ = str(item["id"])
        p, h = latest.get(id_), hora.get(id_)
        if not p or not h or p["high"] is None or p["low"] is None:
            continue
        if so_members is not None and bool(item.get("members")) != so_members:
            continue

        compra, venda = p["low"], p["high"]
        if compra <= 0 or compra < preco_min or compra > min(teto, capital):
            continue

        vol_compra = h["lowPriceVolume"] or 0  # quem vende-nos itens
        vol_venda = h["highPriceVolume"] or 0  # quem nos compra itens
        volume = min(vol_compra, vol_venda)
        if volume < volume_minimo:
            continue

        margem = venda - _imposto(venda, "osrs", item["id"]) - compra
        roi = margem / compra * 100
        if margem < margem_min or roi < roi_min:
            continue

        qtd = min(item.get("limit") or 1, capital // compra)
        resultados.append(
            {
                "nome": item["name"],
                "id": item["id"],
                "compra": compra,
                "venda": venda,
                "margem_liquida": margem,
                "roi": round(roi, 2),
                "limite_4h": item.get("limit"),
                "volume_compra_1h": vol_compra,
                "volume_venda_1h": vol_venda,
                "volume": volume,
                "unidades_sugeridas": qtd,
                "lucro_potencial": margem * qtd,
            }
        )

    resultados.sort(key=lambda r: r[ordenar_por], reverse=True)
    return resultados[:top]


@mcp.tool()
async def alch_profit(
    capital: int = 1_000_000,
    volume_minimo: int = 100,
    top: int = 10,
    preco_max: int | None = None,
    so_members: bool | None = None,
) -> list[dict]:
    """Itens em que o High Level Alchemy dá lucro (só OSRS).
    Lucro por cast = valor do high alch - preço de compra (insta-buy) - nature
    rune. Não conta com fire runes (assume staff of fire).

    volume_minimo: volume de compras na última hora.
    preco_max: preço máximo de compra por item.
    so_members: True só members, False só free-to-play, None ambos.
    """
    mapping = await _get(f"{OSRS}/mapping", ttl=3600)
    latest = (await _get(f"{OSRS}/latest", ttl=30))["data"]
    hora = (await _get(f"{OSRS}/1h", ttl=60))["data"]

    nature = (latest.get(str(NATURE_RUNE_ID)) or {}).get("high")
    if not nature:
        return [{"erro": "Não consegui obter o preço da nature rune."}]

    resultados = []
    for item in mapping:
        alch = item.get("highalch")
        id_ = str(item["id"])
        p, h = latest.get(id_), hora.get(id_)
        if not alch or not p or not h or p["high"] is None:
            continue
        if so_members is not None and bool(item.get("members")) != so_members:
            continue

        custo = p["high"]
        if custo <= 0 or (preco_max is not None and custo > preco_max):
            continue
        volume = h["highPriceVolume"] or 0
        if volume < volume_minimo:
            continue

        lucro = alch - custo - nature
        if lucro <= 0 or custo + nature > capital:
            continue

        qtd = min(item.get("limit") or 1, capital // (custo + nature))
        resultados.append(
            {
                "nome": item["name"],
                "id": item["id"],
                "preco_compra": custo,
                "high_alch": alch,
                "nature_rune": nature,
                "lucro_por_cast": lucro,
                "limite_4h": item.get("limit"),
                "volume_compra_1h": volume,
                "unidades_sugeridas": qtd,
                "lucro_potencial": lucro * qtd,
            }
        )

    resultados.sort(key=lambda r: r["lucro_potencial"], reverse=True)
    return resultados[:top]


@mcp.tool()
def calcular_flip(
    preco_compra: int,
    preco_venda: int,
    quantidade: int = 1,
    jogo: Jogo = "osrs",
    item_id: int | None = None,
) -> dict:
    """Calculadora manual: lucro de um flip com o imposto do GE descontado
    (OSRS e RS3). Passa item_id se o item puder ser um bond (isento)."""
    imposto = _imposto(preco_venda, jogo, item_id)
    margem = preco_venda - imposto - preco_compra
    return {
        "imposto_por_unidade": imposto,
        "margem_liquida_por_unidade": margem,
        "roi_pct": round(margem / preco_compra * 100, 2) if preco_compra else None,
        "custo_total": preco_compra * quantidade,
        "lucro_total": margem * quantidade,
    }


if __name__ == "__main__":
    # PORT vem do serviço de alojamento quando o pões online; localmente usa 8000.
    mcp.run(transport="http", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))