"""Notas dos cartões das tabelas e a fonte do rodapé, como o script as escreve na visão padrão.

Sem JavaScript, a tabela precisa dizer o que mostra: o grupo e o período (nota de cada cartão), o
produto do benchmark, o que é o "*" do custo por nutriente e as fontes dos números (o rodapé cita o
Banco Mundial e a PTAX quando os dados os têm). Cada texto espelha o do script (função entre
parênteses); o teste de navegador compara os dois. Só preenche o que outra etapa ainda não escreveu.
"""

from __future__ import annotations

from . import formato as F
from .tabelas import PRODUTOS_NUTR, PRODUTOS_TROCA, Visao, ano_parcial, em, indice, intl, js, produto_bm, rotulo_ano

MOEDA_PADRAO = "US$"  # estado.nutrMoeda = "usd"
FONTE_RODAPE = "Fonte: Comex Stat/MDIC"  # texto do index.html, que rodape() completa


def _periodo(dados: dict, v: Visao) -> str:
    p = dados["mensal"]["periodos"]
    indices = v.indices(dados)
    return f"{F.rotulo_mes(p[indices[0]])} a {F.rotulo_mes(p[indices[-1]])}"


def _nota_ranking(dados: dict, v: Visao, tipo: str) -> str:
    """(desenharRanking)"""
    bloco = dados["origens"] if tipo == "origens" else dados["urfs"]
    linhas = (bloco["dados"].get(str(v.ano)) or {}).get(v.grupo) or []
    top = len(linhas) - (1 if any(r[1] == "Outros" for r in linhas) else 0)
    return f"{F.NOMES[v.grupo]} · {rotulo_ano(dados, v.ano)} · share das toneladas, top {top} e outros"


def _nota_hhi(dados: dict, v: Visao) -> str:
    """(desenharHhi)"""
    anos = [a for a in dados["anual"]["anos"] if int(v.de[:4]) <= a <= int(v.ate[:4])]
    parcial = next((a for a in anos if ano_parcial(dados, a)), None)
    return f"{F.NOMES[v.grupo]} · por país de origem, em toneladas{f' · {rotulo_ano(dados, parcial)}' if parcial else ''}"


def _nota_rotas(dados: dict, v: Visao) -> str | None:
    """(desenharRotas)"""
    if not dados.get("rotas"):
        return None
    ano = v.ano_das_rotas()
    bloco = (dados["rotas"]["dados"].get(str(ano)) or {}).get(v.grupo)
    n_origens = len([o for o in bloco["origens"] if o[1] != "Outros"]) if bloco else 0
    n_urfs = len([u for u in bloco["urfs"] if u[1] != "Outros"]) if bloco else 0
    return (f"{F.NOMES[v.grupo]} · {rotulo_ano(dados, ano)} · espessura = toneladas · {n_origens} maiores origens e {n_urfs} maiores URFs; "
            "o resto em Outros")


def _notas_nutrientes(dados: dict, v: Visao) -> dict[str, str]:
    """(desenharNutrientes) nota do cartão e dos teores (que explica o "*" da tabela)."""
    nu = dados.get("nutrientes")
    if not nu:
        return {}
    chaves = [k for k in PRODUTOS_NUTR.get(v.grupo, ["ureia", "map", "kcl"]) if nu["produtos"].get(k)]
    produtos = [dict(nu["produtos"][k], chave=k) for k in chaves]

    def teor_texto(prod):
        """(teorTexto)"""
        return " e ".join(f"{js(x)}% de {nu['nutrientes'][n]}" for n, x in prod["teores"].items())

    npk = " · os compostos NPK não entram (o teor varia de carga para carga): mostrando um produto de cada nutriente" if v.grupo == "NPK" else ""
    credito = [x for x in produtos if x.get("credito_n")]
    usados = "; ".join(x["nome"] + " " + teor_texto(x) for x in produtos)
    teores = [
        f"Teores usados: {usados}. O Comex Stat não traz o teor de cada carga.",
        (f"No {' e no '.join(x['nome'] for x in credito)}, o N que vem junto é descontado pelo custo do N da ureia no mesmo mês; "
         "o tooltip traz o custo sem esse desconto.") if credito else "",
        "O enxofre do sulfato de amônio (cerca de 24% de S) não é descontado." if any(x["chave"] == "sulfato_amonio" for x in produtos) else "",
        f"Meses com menos de {intl(F.fmt0, nu['corte_amostra_t'])} t do produto ficam fora do gráfico (na tabela, com *).",
        f"Fonte: {js(nu['fonte'])}.",
    ]
    return {
        "nota-nutrientes": f"{', '.join(x['nome'] for x in produtos)} · {MOEDA_PADRAO} por tonelada de nutriente · {_periodo(dados, v)}{npk}",
        "nota-teores": " ".join(t for t in teores if t),
    }


def _nota_troca(dados: dict, v: Visao) -> str | None:
    """(desenharTroca)"""
    tr = dados.get("troca")
    if not tr:
        return None
    nomes = [tr["produtos"][k]["nome"] for k in PRODUTOS_TROCA.get(v.grupo, ["kcl", "ureia", "map"]) if tr["produtos"].get(k)]
    npk = " · NPK não entra na relação: mostrando os três produtos" if v.grupo == "NPK" else ""
    return f"{', '.join(nomes)} · t de soja por t de fertilizante · {_periodo(dados, v)}{npk}"


def _notas_benchmark(dados: dict, v: Visao) -> dict[str, str]:
    """(desenharBenchmark) produto e base da tabela, meses fora dos gráficos e o CIF em reais."""
    chave = produto_bm(dados, v)
    if chave is None:
        return {}
    bm = dados["benchmark"]
    prod = bm["produtos"][chave]
    p = dados["mensal"]["periodos"]

    def pequena(i):
        k = indice(bm["periodos"], p[i])
        return k >= 0 and bool(em(prod["amostra_pequena"], k))

    n_pequena = sum(1 for i in v.indices(dados) if pequena(i))
    proxy = " · o MAP usa o DAP como referência (a Pink Sheet não tem MAP)" if prod.get("proxy") else ""
    fora = (f" {n_pequena} {'mês' if n_pequena == 1 else 'meses'} com menos de {intl(F.fmt0, bm['corte_amostra_t'])} t ficam fora dos gráficos "
            "(estão na tabela).") if n_pequena else ""
    return {
        "nota-bm": f"{prod['nome']} ({prod['descricao']}, NCM {', '.join(prod['ncms'])}) · benchmark: {prod['serie']}, Banco Mundial{proxy} · {_periodo(dados, v)}",
        "nota-spread": ("FOB Brasil − benchmark quando o benchmark é FOB; CIF Brasil − benchmark quando ele já é um preço no destino. "
                        f"Acima de zero, o Brasil pagou mais que a referência.{fora}"),
        "nota-brl": f"{prod['nome']} · CIF Brasil × PTAX venda média do mês (BCB). A relação de troca com a soja é US$/US$ e não muda com o câmbio.",
    }


def notas(dados: dict, v: Visao) -> dict[str, str]:
    """id -> texto da nota de cada cartão com tabela (só as que o script escreve nesta visão)."""
    saida = {
        "nota-toneladas": f"{F.NOMES[v.grupo]} · {_periodo(dados, v)}",
        "nota-origens": _nota_ranking(dados, v, "origens"),
        "nota-hhi": _nota_hhi(dados, v),
        "nota-portos": _nota_ranking(dados, v, "portos"),
        "nota-rotas": _nota_rotas(dados, v),
        "nota-precos": f"{F.NOMES[v.grupo]} · US$ por tonelada · {_periodo(dados, v)}",
        "nota-frete": f"{F.NOMES[v.grupo]} · US$ por tonelada · {_periodo(dados, v)}",
        **_notas_nutrientes(dados, v),
        **_notas_benchmark(dados, v),
        "nota-troca": _nota_troca(dados, v),
    }
    return {k: x for k, x in saida.items() if x}


def fonte_rodape(dados: dict) -> str:
    """(rodape) as fontes dos números da página."""
    ptax = bool(dados.get("benchmark")) or any(not F.nulo(x) for x in ((dados.get("nutrientes") or {}).get("ptax") or []))
    return "; ".join([FONTE_RODAPE] + (["Banco Mundial (Pink Sheet)"] if dados.get("benchmark") else []) + (["BCB/PTAX"] if ptax else []))
