"""Insumos do fósforo: enxofre e rocha fosfática importados, a rocha contra a Pink Sheet e o custo
de insumo por tonelada de MAP.

Para cada mês e insumo (data/raw_insumos, via ingest.ler_insumos; o produto sai do SH4, em
config.INSUMOS_POR_SH4):

    FOB, CIF e frete (US$/t)        = valor ÷ toneladas importadas (média ponderada pelo peso)
    rocha: spread (US$/t)           = FOB Brasil − Pink Sheet "Phosphate rock" (FOB Norte da
                                      África), FOB×FOB; vazio em amostra pequena
    rocha: spread (%)               = spread ÷ Pink Sheet × 100
    custo de insumo (US$/t de MAP)  = CIF do enxofre × INSUMOS_COEF_ENXOFRE
                                      + CIF da rocha × INSUMOS_COEF_ROCHA
    razão                           = custo de insumo ÷ CIF do MAP importado (31054000, o mesmo
                                      NCM dos blocos "nutrientes" e "benchmark")

Os coeficientes (config.py) são uma aproximação técnica, as toneladas de enxofre e de rocha por
tonelada de MAP: não é o custo de nenhuma empresa. Fica de fora o nitrogênio do MAP, a energia, a
conversão, os impostos e o frete interno, e o insumo de origem nacional não entra no preço médio.
É o preço no porto (CIF), não o preço ao produtor.

A Pink Sheet é uma referência de outro lugar e de outro momento de contrato: o spread da rocha
mistura origem, teor da rocha, prazo de contrato e defasagem, e não é ágio.

Mês com menos de INSUMOS_CORTE_AMOSTRA_T toneladas do insumo (ou CORTE_AMOSTRA_T de MAP) é
amostra pequena: um navio decide o preço.

Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet).
"""

from __future__ import annotations

import pandas as pd

from . import comparacao, config, ingest

PRODUTOS = {
    "enxofre": {"nome": "Enxofre", "descricao": "enxofre a granel e outras formas"},
    "rocha": {"nome": "Rocha fosfática", "descricao": "fosfatos de cálcio naturais, não moídos e moídos"},
}
# Rocha fosfática na Pink Sheet (coluna gravada por src/benchmark.py) e a base dela (CLAUDE.md).
ROCHA_SERIE = "Phosphate rock"
ROCHA_COLUNA = config.PINK_SERIES[ROCHA_SERIE]
ROCHA_BASE = "FOB Norte da África"
ROCHA_COMPARACAO = comparacao.COMPARACAO["FOB"]
MAP = comparacao.PRODUTOS["map"]  # NCMs do MAP, os mesmos dos blocos "benchmark" e "nutrientes"
TOP_ORIGENS = 8  # origens por ano e insumo no dashboard.json; o resto vira "Outros"
FONTE = "Comex Stat/MDIC; Banco Mundial (Pink Sheet)"
VALORES = ["toneladas", "vl_fob", "vl_cif", "vl_frete"]

COLUNAS = [
    "periodo",
    "ano",
    "mes",
    "produto",
    "ncms",
    "toneladas",
    "vl_fob",
    "vl_cif",
    "vl_frete",
    "preco_fob_usd_t",
    "preco_cif_usd_t",
    "frete_usd_t",
    "amostra_pequena",
    "serie_bm",
    "base_bm",
    "comparacao",
    "benchmark_usd_t",
    "spread_usd_t",
    "spread_pct",
]
COLUNAS_CUSTO = [
    "periodo",
    "ano",
    "mes",
    "coef_enxofre",
    "coef_rocha",
    "toneladas_enxofre",
    "cif_enxofre_usd_t",
    "toneladas_rocha",
    "cif_rocha_usd_t",
    "toneladas_map",
    "cif_map_usd_t",
    "custo_enxofre_usd_t",
    "custo_rocha_usd_t",
    "custo_insumo_usd_t",
    "razao_custo_cif_map",
    "amostra_pequena_enxofre",
    "amostra_pequena_rocha",
    "amostra_pequena_map",
    "amostra_pequena",
]


def preparar(insumos: pd.DataFrame) -> pd.DataFrame:
    """Importações de insumos (colunas de ingest.ler_raw) com o produto e o peso em toneladas."""
    df = insumos.copy()
    df["co_ncm"] = df["co_ncm"].astype(str)
    df["produto"] = df["co_ncm"].str[:4].map(config.INSUMOS_POR_SH4)
    fora = sorted(df.loc[df["produto"].isna(), "co_ncm"].unique())
    if fora:
        raise ValueError(f"NCMs fora de config.INSUMOS_POR_SH4 nos dados de insumos: {fora}")
    df[VALORES[1:]] = df[VALORES[1:]].astype("float64")
    df["toneladas"] = df["kg_liquido"].astype("float64") / 1000
    return df


def nos_meses(insumos: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    """preparar(), só nos meses das importações de fertilizantes (os períodos do dashboard)."""
    return preparar(insumos).merge(base[["ano", "mes"]].drop_duplicates().astype("int64"), on=["ano", "mes"])


def ncms_por_produto(ncm_csv=config.NCM_INSUMOS_CSV) -> dict[str, list[str]]:
    """NCMs monitorados de cada insumo (data/ncm_insumos.csv), em ordem."""
    ncms = ingest.carregar_ncms(ncm_csv)["ncm"].astype(str).sort_values()
    return {p: [n for n in ncms if config.INSUMOS_POR_SH4.get(n[:4]) == p] for p in PRODUTOS}


def _periodo(df: pd.DataFrame) -> pd.Series:
    return df["ano"].astype(int).astype(str) + "-" + df["mes"].astype(int).astype(str).str.zfill(2)


def _grade(meses: pd.DataFrame) -> pd.DataFrame:
    """Meses (ano, mes) únicos e ordenados, com o período AAAA-MM."""
    grade = meses[["ano", "mes"]].drop_duplicates().astype("int64").sort_values(["ano", "mes"], ignore_index=True)
    return grade.assign(periodo=_periodo(grade))


def mensal(insumos: pd.DataFrame, meses: pd.DataFrame, pink: pd.DataFrame | None = None, ncms: dict | None = None) -> pd.DataFrame:
    """Uma linha por mês × insumo, nos meses de `meses` (os das importações de fertilizantes).

    `insumos`: preparar(); `pink`: benchmark.ler_pink(). Dentro do período ingerido, mês sem
    importação do insumo tem zero toneladas e preço vazio; fora dele, tudo fica vazio.
    """
    ncms = ncms if ncms is not None else ncms_por_produto()
    grade = _grade(meses)
    df = grade.merge(pd.DataFrame({"produto": list(PRODUTOS)}), how="cross")
    imp = insumos.groupby(["ano", "mes", "produto"], as_index=False)[VALORES].sum()
    df = df.merge(imp.astype({"ano": "int64", "mes": "int64"}), on=["ano", "mes", "produto"], how="left")
    if insumos.empty:
        coberto = pd.Series(False, index=df.index)
    else:
        chave, ingerido = df["ano"] * 100 + df["mes"], insumos["ano"].astype(int) * 100 + insumos["mes"].astype(int)
        coberto = chave.between(ingerido.min(), ingerido.max())
    df[VALORES] = df[VALORES].astype("float64")
    df.loc[coberto, VALORES] = df.loc[coberto, VALORES].fillna(0.0)
    df["ncms"] = df["produto"].map(lambda p: "|".join(ncms.get(p, [])))

    com_volume = df["toneladas"] > 0
    for valor, coluna in (("vl_fob", "preco_fob_usd_t"), ("vl_cif", "preco_cif_usd_t"), ("vl_frete", "frete_usd_t")):
        df[coluna] = (df[valor] / df["toneladas"]).where(com_volume)
    corte = df["produto"].map(config.INSUMOS_CORTE_AMOSTRA_T).astype("float64")
    df["amostra_pequena"] = com_volume & (df["toneladas"] < corte)

    rocha = df["produto"].eq("rocha")
    df["serie_bm"] = pd.Series(ROCHA_SERIE, index=df.index).where(rocha)
    df["base_bm"] = pd.Series(ROCHA_BASE, index=df.index).where(rocha)
    df["comparacao"] = pd.Series(ROCHA_COMPARACAO, index=df.index).where(rocha)
    if pink is not None and not pink.empty and ROCHA_COLUNA in pink.columns:
        bm = pink[["mes", ROCHA_COLUNA]].rename(columns={"mes": "periodo", ROCHA_COLUNA: "benchmark_usd_t"})
        bm["periodo"] = bm["periodo"].astype(str)
        bm["benchmark_usd_t"] = pd.to_numeric(bm["benchmark_usd_t"], errors="coerce").astype("float64")
        df = df.merge(bm.drop_duplicates("periodo"), on="periodo", how="left")
        df["benchmark_usd_t"] = df["benchmark_usd_t"].where(rocha)
    else:
        df["benchmark_usd_t"] = float("nan")
    bm = df["benchmark_usd_t"].where(df["benchmark_usd_t"] > 0)
    comparavel = rocha & ~df["amostra_pequena"]
    df["spread_usd_t"] = (df["preco_fob_usd_t"] - bm).where(comparavel)
    df["spread_pct"] = 100 * df["spread_usd_t"] / bm

    ordem = {p: i for i, p in enumerate(PRODUTOS)}
    df = df.assign(_ordem=df["produto"].map(ordem)).sort_values(["ano", "mes", "_ordem"], kind="mergesort")
    return df[COLUNAS].reset_index(drop=True)


def custo_map(tabela: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    """Custo de insumo por tonelada de MAP e razão sobre o CIF do MAP, uma linha por mês.

    `tabela`: mensal(); `base`: importações de fertilizantes (transform.carregar_base).
    """
    grade = _grade(base)
    df = grade.copy()
    df["coef_enxofre"], df["coef_rocha"] = float(config.INSUMOS_COEF_ENXOFRE), float(config.INSUMOS_COEF_ROCHA)
    for produto in PRODUTOS:
        p = tabela[tabela["produto"] == produto].set_index("periodo").reindex(df["periodo"])
        df[f"toneladas_{produto}"] = p["toneladas"].to_numpy()
        df[f"cif_{produto}_usd_t"] = p["preco_cif_usd_t"].to_numpy()
        df[f"amostra_pequena_{produto}"] = p["amostra_pequena"].eq(True).to_numpy()

    m = base[base["co_ncm"].isin(MAP["ncms"])].groupby(["ano", "mes"], as_index=False)[["toneladas", "vl_cif"]].sum()
    m = df[["ano", "mes"]].merge(m.astype({"ano": "int64", "mes": "int64"}), on=["ano", "mes"], how="left")
    t_map = m["toneladas"].astype("float64").fillna(0.0)
    df["toneladas_map"] = t_map.to_numpy()
    df["cif_map_usd_t"] = (m["vl_cif"].astype("float64") / t_map).where(t_map > 0).to_numpy()
    df["amostra_pequena_map"] = ((t_map > 0) & (t_map < comparacao.CORTE_AMOSTRA_T)).to_numpy()

    df["custo_enxofre_usd_t"] = df["cif_enxofre_usd_t"] * df["coef_enxofre"]
    df["custo_rocha_usd_t"] = df["cif_rocha_usd_t"] * df["coef_rocha"]
    df["custo_insumo_usd_t"] = df["custo_enxofre_usd_t"] + df["custo_rocha_usd_t"]
    df["razao_custo_cif_map"] = (df["custo_insumo_usd_t"] / df["cif_map_usd_t"]).where(df["cif_map_usd_t"] > 0)
    df["amostra_pequena"] = df["amostra_pequena_enxofre"] | df["amostra_pequena_rocha"] | df["amostra_pequena_map"]
    return df[COLUNAS_CUSTO].reset_index(drop=True)


def origens(insumos: pd.DataFrame, num) -> dict:
    """Maiores origens por ano e insumo: [codigo, nome, t, share_pct, var_t_pct], mais "Outros".

    A mesma base do share_origem_ano: share das toneladas do ano e variação sobre os mesmos meses
    do ano anterior (vazia se o ano anterior não tiver todos esses meses; quem deixou de importar
    entra no "Outros").
    """
    if insumos.empty:
        return {}
    meses = {int(a): set(int(m) for m in ms) for a, ms in insumos.groupby("ano")["mes"].unique().items()}
    chaves = ["produto", "co_pais", "no_pais"]
    saida = {}
    for ano in sorted(meses):
        atual = insumos[insumos["ano"] == ano].groupby(chaves, as_index=False, dropna=False)["toneladas"].sum()
        comparavel = ano - 1 in meses and meses[ano] <= meses[ano - 1]
        if comparavel:
            periodo = insumos[(insumos["ano"] == ano - 1) & insumos["mes"].isin(meses[ano])]
            anterior = periodo.groupby(chaves, as_index=False, dropna=False)["toneladas"].sum()
            atual = atual.merge(anterior.rename(columns={"toneladas": "t_ant"}), on=chaves, how="outer")
            atual[["toneladas", "t_ant"]] = atual[["toneladas", "t_ant"]].fillna(0.0)
        else:
            atual["t_ant"] = float("nan")
        por_produto = {}
        for produto in PRODUTOS:
            g = atual[atual["produto"] == produto]
            g = g.sort_values(["toneladas", "co_pais"], ascending=[False, True], kind="mergesort")
            total = g["toneladas"].sum()
            if total <= 0:
                por_produto[produto] = []
                continue
            top = g[g["toneladas"] > 0].head(TOP_ORIGENS)
            resto = g.drop(top.index)
            linhas = [_origem(_texto(r.co_pais), _texto(r.no_pais), r.toneladas, r.t_ant, total, num) for r in top.itertuples()]
            if resto["toneladas"].sum() > 0:
                linhas.append(_origem(None, "Outros", resto["toneladas"].sum(), resto["t_ant"].sum(min_count=1), total, num))
            por_produto[produto] = linhas
        saida[str(ano)] = por_produto
    return saida


def _texto(valor):
    return None if valor is None or pd.isna(valor) else str(valor)


def _origem(codigo, nome, t: float, t_ant: float, total: float, num) -> list:
    var = 100 * (t / t_ant - 1) if pd.notna(t_ant) and t_ant > 0 else None
    return [codigo, nome, num(t, 0), num(100 * t / total, 3), num(var, 1)]


def _decimal(valor: float) -> str:
    """Número curto em pt-BR, para as notas (0.45 -> "0,45")."""
    return f"{valor:g}".replace(".", ",")


def _toneladas(valor: int) -> str:
    return f"{valor // 1000} mil t" if valor >= 1000 and valor % 1000 == 0 else f"{valor:,} t".replace(",", ".")


def notas() -> list[str]:
    """Notas do bloco para o Método, com os coeficientes e cortes tirados do config."""
    ce, cr = _decimal(config.INSUMOS_COEF_ENXOFRE), _decimal(config.INSUMOS_COEF_ROCHA)
    cortes = [f"{_toneladas(config.INSUMOS_CORTE_AMOSTRA_T[p])} de {PRODUTOS[p]['nome'].lower()}" for p in PRODUTOS]
    cortes.append(f"{_toneladas(comparacao.CORTE_AMOSTRA_T)} de MAP")
    return [
        f"Custo de insumo por tonelada de MAP = CIF do enxofre × {ce} + CIF da rocha fosfática × {cr}, em US$ por"
        " tonelada de MAP, com o preço médio de cada insumo importado no mês.",
        f"Coeficientes: {ce} t de enxofre e {cr} t de rocha fosfática por tonelada de MAP, uma aproximação técnica:"
        " o consumo real muda com o teor da rocha e o processo de cada fábrica. É uma aproximação, não o custo de"
        " nenhuma empresa: ficam de fora o nitrogênio do MAP, a energia, a conversão, os impostos e o frete interno.",
        f"Razão = custo de insumo ÷ CIF do MAP importado (NCM {', '.join(MAP['ncms'])}) no mesmo mês.",
        "Preços CIF no porto (produto, frete e seguro até o Brasil), antes de impostos, frete interno e margens: não"
        " são o preço ao produtor. Só as importações entram: o insumo de origem nacional fica de fora.",
        f"Rocha fosfática: FOB do Brasil x Pink Sheet do Banco Mundial ({ROCHA_SERIE}, {ROCHA_BASE}), {ROCHA_COMPARACAO}."
        " A Pink Sheet é uma referência de outro lugar e de outro momento de contrato: o spread mistura origem,"
        " teor da rocha, prazo de contrato e defasagem. Não é ágio.",
        f"Amostra pequena: mês com menos de {', '.join(cortes[:-1])} ou {cortes[-1]}; um navio decide o preço. Nesses"
        " meses o spread da rocha fica vazio e o custo de insumo fica marcado.",
    ]


def bloco_dashboard(
    tabela: pd.DataFrame,
    custo: pd.DataFrame,
    periodos: list[str],
    num,
    por_origem: dict | None = None,
    fonte_pink: dict | None = None,
    ncms: dict | None = None,
) -> dict:
    """Bloco "insumos" do dashboard.json, alinhado aos períodos da série mensal.

    `num(valor, casas)` é o formatador do transform. Seis casas nos US$/t, como nos blocos
    "benchmark" e "troca": o site arredonda uma vez só, na exibição.
    """
    ncms = ncms if ncms is not None else ncms_por_produto()
    produtos = {}
    for chave, info in PRODUTOS.items():
        p = tabela[tabela["produto"] == chave].set_index("periodo").reindex(periodos)
        produtos[chave] = {
            "nome": info["nome"],
            "descricao": f"{info['descricao']} (NCM {_posicoes(ncms.get(chave, []))})",
            "ncms": ncms.get(chave, []),
            "corte_amostra_t": int(config.INSUMOS_CORTE_AMOSTRA_T[chave]),
            "t": [num(v, 0) for v in p["toneladas"]],
            "fob_musd": [num(v / 1e6, 3) for v in p["vl_fob"]],
            "cif_musd": [num(v / 1e6, 3) for v in p["vl_cif"]],
            "frete_musd": [num(v / 1e6, 3) for v in p["vl_frete"]],
            "fob": [num(v, 6) for v in p["preco_fob_usd_t"]],
            "cif": [num(v, 6) for v in p["preco_cif_usd_t"]],
            "frete": [num(v, 6) for v in p["frete_usd_t"]],
            "amostra_pequena": [bool(v) if pd.notna(v) else False for v in p["amostra_pequena"]],
        }
        if chave == "rocha":
            produtos[chave]["benchmark"] = {
                "serie": ROCHA_SERIE,
                "base": ROCHA_BASE,
                "comparacao": ROCHA_COMPARACAO,
                "bm": [num(v, 6) for v in p["benchmark_usd_t"]],
                "spread_usd_t": [num(v, 6) for v in p["spread_usd_t"]],
                "spread_pct": [num(v, 6) for v in p["spread_pct"]],
                "pink_atualizado_em": (fonte_pink or {}).get("atualizado_em"),
            }
    c = custo.set_index("periodo").reindex(periodos)
    com_pink = tabela["benchmark_usd_t"].notna().any()
    return {
        "periodos": periodos,
        "fonte": FONTE if com_pink else "Comex Stat/MDIC",
        "produtos": produtos,
        "origens": por_origem or {},
        "custo_map": {
            "coef_enxofre": float(config.INSUMOS_COEF_ENXOFRE),
            "coef_rocha": float(config.INSUMOS_COEF_ROCHA),
            "ncms_map": list(MAP["ncms"]),
            "corte_amostra_map_t": int(comparacao.CORTE_AMOSTRA_T),
            "custo": [num(v, 6) for v in c["custo_insumo_usd_t"]],
            "cif_map": [num(v, 6) for v in c["cif_map_usd_t"]],
            "razao": [num(v, 6) for v in c["razao_custo_cif_map"]],
            "amostra_pequena": [bool(v) if pd.notna(v) else False for v in c["amostra_pequena"]],
        },
        "notas": notas(),
    }


def _posicoes(ncms: list[str]) -> str:
    """Posições (SH4) ou subposições (SH6) dos NCMs, para a descrição: "2503" ou "2510.10 e 2510.20"."""
    sh4 = sorted({n[:4] for n in ncms})
    sh6 = sorted({n[:6] for n in ncms})
    if len(sh6) <= 1:
        return " e ".join(sh4)
    nomes = [f"{s[:4]}.{s[4:]}" for s in sh6]
    return ", ".join(nomes[:-1]) + " e " + nomes[-1]
