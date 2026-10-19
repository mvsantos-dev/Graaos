"""index.html: a frase de resumo e o aria-label dos gráficos de preços, frete, custo por
nutriente, relação de troca e Brasil x mercado internacional, iguais ao que o script desenha na
visão padrão (todos os grupos, período inteiro, KCl no benchmark, custo em US$).

Cada função espelha uma do script do index.html (nome entre parênteses), com a mesma saída: o
teste de navegador (tests/e2e/test_estatico_resumo_precos.py) compara o HTML do build com o que
o script desenha, e as frases do script com as do Python em todos os grupos e produtos. As contas
seguem a ordem das do script (mesmos floats, mesmo arredondamento na formatação).

Regras do CLAUDE.md em toda frase: a fonte dos números no fim; custo por nutriente e relação de
troca "no porto", nunca o preço ao produtor; o spread sempre com o preço do Brasil da sua base e a
ressalva de que não é ágio; reais só pela PTAX venda média do mês.
"""

from __future__ import annotations

import math

from . import formato as F
from .contexto import Contexto, esc

PLURAL_GRUPO = {"TOTAL": "fertilizantes", "N": "nitrogenados", "P": "fosfatados", "K": "potássicos", "NPK": "compostos (NPK)"}
NAO_E_AGIO = "Não é ágio: o benchmark é de outro lugar e de outro momento de contrato."
PRODUTOS_TROCA = {"K": ["kcl"], "N": ["ureia"], "P": ["map"]}  # (PRODUTOS_TROCA)
TROCA_TODOS = ["kcl", "ureia", "map"]
PRODUTOS_NUTR = {"N": ["ureia", "sulfato_amonio", "nitrato_amonio"], "P": ["map", "dap", "tsp"], "K": ["kcl"]}  # (PRODUTOS_NUTR)
NUTR_TODOS = ["ureia", "map", "kcl"]
MOEDAS_NUTR = {"usd": {"rotulo": "US$", "campo": "custo"}, "brl": {"rotulo": "R$", "campo": "custo_brl"}}  # (MOEDAS_NUTR)
PRODUTOS_BM = {"K": ["kcl"], "N": ["ureia"], "P": ["map", "dap", "tsp"]}  # (PRODUTOS_BM)
ORDEM_BM = ["kcl", "ureia", "map", "dap", "tsp"]
FONTE_COMEX = "Fonte: Comex Stat/MDIC."
FONTE_BM = "Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet)."
FONTE_PTAX = "Fonte: Comex Stat/MDIC; BCB/PTAX."


# --- Auxiliares do script ---------------------------------------------------------------------
def nome_na_frase(nome: str) -> str:
    """(nomeNaFrase) "Ureia" vira "ureia"; siglas como KCl e MAP ficam."""
    return nome[0].lower() + nome[1:] if len(nome) > 1 and nome[0].isupper() and nome[1].islower() else nome


def mes_ano_antes(periodo: str) -> str:
    """(mesAnoAntes) o mesmo mês do ano anterior."""
    return f"{int(periodo[:4]) - 1}-{periodo[5:7]}"


def indice(lista: list, valor) -> int:
    """(indexOf)"""
    return lista.index(valor) if valor in lista else -1


def por_tonelada_mes(dados: dict, g: str, campo: str, i: int):
    """(porToneladaMes) valor por tonelada de um mês da série (a conta de serieMensal)."""
    if i < 0:
        return None
    m = dados["mensal"][g]
    t, v = m["t"][i], m[campo][i]
    return v * 1e6 / t if t is not None and t > 0 and not F.nulo(v) else None


def diferenca_em_texto(v, rotulo: str) -> str:
    """(diferencaEmTexto) "5,3% a mais que em set/2025"; sem base de comparação, ""."""
    if F.nulo(v) or not math.isfinite(v):
        return ""
    sinal = F.sinal_de(v, F.fmt1, "+")
    if not sinal:
        return f"praticamente o mesmo que em {rotulo}"
    return f"{F.fmt1(abs(v))}% a {'menos' if sinal == F.MENOS else 'mais'} que em {rotulo}"


def reais(v) -> str:
    """(reais)"""
    return F.TRACO if F.nulo(v) else f"R$ {F.fmt0(v)}/t"


def produtos_bm(dados: dict, g: str) -> list[str]:
    """(produtosBm) os produtos do benchmark do grupo, na ordem dos chips."""
    produtos = (dados.get("benchmark") or {}).get("produtos") or {}
    return [k for k in PRODUTOS_BM.get(g, ORDEM_BM) if produtos.get(k)]


# --- Frases -----------------------------------------------------------------------------------
def frase_precos(dados: dict, g: str, ate: str) -> str:
    """(frasePrecos) FOB e CIF do último mês; o FOB contra o mesmo mês do ano anterior."""
    p = dados["mensal"]["periodos"]
    i, antes = indice(p, ate), mes_ano_antes(ate)
    fob, cif = por_tonelada_mes(dados, g, "fob_musd", i), por_tonelada_mes(dados, g, "cif_musd", i)
    if F.nulo(fob):
        return f"Em {F.rotulo_mes(ate)}, não há preço implícito dos {PLURAL_GRUPO[g]} importados. {FONTE_COMEX}"
    dif = diferenca_em_texto(F.variacao_pct(fob, por_tonelada_mes(dados, g, "fob_musd", indice(p, antes))), F.rotulo_mes(antes))
    com_cif = "" if F.nulo(cif) else f" e {F.por_tonelada(cif)} CIF, com {F.por_tonelada(cif - fob)} de frete e seguro"
    return (f"Em {F.rotulo_mes(ate)}, o preço implícito dos {PLURAL_GRUPO[g]} importados foi {F.por_tonelada(fob)} FOB"
            f"{f' ({dif})' if dif else ''}{com_cif}. {FONTE_COMEX}")


def frase_frete(dados: dict, g: str, ate: str) -> str:
    """(fraseFrete) US$/t e peso no CIF do último mês e do mesmo mês do ano anterior."""
    p = dados["mensal"]["periodos"]
    m = dados["mensal"][g]

    def peso(i):
        c = m["cif_musd"][i] if i >= 0 else None
        if c is None or not c > 0:
            return None
        f = m["frete_musd"][i]
        return 100 * (f if f is not None else 0) / c

    i, j = indice(p, ate), indice(p, mes_ano_antes(ate))
    frete, frete_antes = por_tonelada_mes(dados, g, "frete_musd", i), por_tonelada_mes(dados, g, "frete_musd", j)
    if F.nulo(frete):
        return f"Em {F.rotulo_mes(ate)}, não há frete por tonelada dos {PLURAL_GRUPO[g]} importados. {FONTE_COMEX}"
    antes = "" if F.nulo(frete_antes) else f"; em {F.rotulo_mes(p[j])}, {F.por_tonelada(frete_antes)} e {F.pct(peso(j))}"
    return (f"Em {F.rotulo_mes(ate)}, o frete internacional médio dos {PLURAL_GRUPO[g]} importados foi {F.por_tonelada(frete)}, "
            f"{F.pct(peso(i))} do valor CIF{antes}. {FONTE_COMEX}")


def produtos_nutrientes(dados: dict, g: str) -> list[str]:
    """(desenharNutrientes) os produtos do grupo que o bloco traz."""
    nu = dados["nutrientes"]
    return [k for k in PRODUTOS_NUTR.get(g, NUTR_TODOS) if nu["produtos"].get(k)]


def frase_nutrientes(dados: dict, g: str, ate: str, moeda: str = "usd") -> str:
    """(fraseNutrientes) o último mês de cada produto do gráfico, com o motivo de quem ficou fora."""
    nu = dados["nutrientes"]
    k = indice(nu["periodos"], ate)
    campo, rotulo = MOEDAS_NUTR[moeda]["campo"], MOEDAS_NUTR[moeda]["rotulo"]
    itens = []
    for chave in produtos_nutrientes(dados, g):
        prod = nu["produtos"][chave]
        nome = nome_na_frase(prod["nome"])
        t = None if k < 0 else prod["t"][k]
        v = None if k < 0 or not prod.get(campo) else prod[campo][k]
        if F.nulo(t) or t == 0:
            itens.append(f"{nome} sem importação no mês")
        elif prod["amostra_pequena"][k]:
            itens.append(f"{nome} fora do gráfico (amostra pequena, {F.toneladas(t)})")
        elif F.nulo(v):
            itens.append(f"{nome} sem custo no mês")
        else:
            itens.append(f"{nome} {rotulo} {F.fmt0(v)}/t de {nu['nutrientes'][prod['nutriente']]}")
    em_reais = ", em reais pela PTAX venda média do mês" if moeda == "brl" else ""
    fonte = FONTE_PTAX if moeda == "brl" else FONTE_COMEX
    return f"Custo por tonelada de nutriente no porto em {F.rotulo_mes(ate)}{em_reais}: {'; '.join(itens)}. Não é o preço ao produtor. {fonte}"


def frase_troca(dados: dict, g: str, ate: str) -> str:
    """(fraseTroca) t de soja por t de cada produto no último mês, contra a média histórica."""
    tr = dados["troca"]
    j = indice(tr["periodos"], ate)
    itens = []
    primeiro = True
    for chave in PRODUTOS_TROCA.get(g, TROCA_TODOS):
        prod = tr["produtos"][chave]
        nome = nome_na_frase(prod["nome"])
        v = None if j < 0 else prod["razao"][j]
        if F.nulo(v):
            t = None if j < 0 else prod["t"][j]
            itens.append(f"{nome} ficou sem relação de troca no mês ({'sem importação' if F.nulo(t) or t == 0 else 'sem preço da soja'})")
            continue
        media_v = prod["media"]
        desvio = 100 * (v / media_v - 1) if media_v is not None and media_v > 0 else None
        sinal = None if F.nulo(desvio) else F.sinal_de(desvio, F.fmt1, "+")
        media = f"média{' histórica' if primeiro else ''} ({F.fmt2(media_v)} t)" if media_v is not None else ""
        if sinal is None:
            dif = ""
        elif sinal:
            dif = f", {F.fmt1(abs(desvio))}% {'abaixo' if sinal == F.MENOS else 'acima'} da {media}"
        else:
            dif = f", igual à {media}"
        itens.append(f"1 t de {nome} custou {F.fmt2(v)} t de soja{dif}" if primeiro else f"1 t de {nome}, {F.fmt2(v)} t{dif}")
        primeiro = False
    return f"Em {F.rotulo_mes(ate)}, no porto, {'; '.join(itens)}. Não é o preço ao produtor. {FONTE_COMEX}"


def frases_benchmark(dados: dict, chave: str, indices: list[int]) -> dict[str, str]:
    """(frasesBenchmark) as frases dos três gráficos do produto, pelo último mês do período que o
    gráfico mostra (sem amostra pequena); se o último mês ficou fora, a frase diz por quê."""
    bm = dados["benchmark"]
    prod = bm["produtos"][chave]
    p = dados["mensal"]["periodos"]

    def k(i):
        return indice(bm["periodos"], p[i])

    def valor(campo, i):
        return None if k(i) < 0 else prod[campo][k(i)]

    def pequena(i):
        return k(i) >= 0 and bool(prod["amostra_pequena"][k(i)])

    def base_de(i):
        return next((b for b in reversed(prod["bases"]) if b["desde"] <= p[i]), prod["bases"][0])

    nome = nome_na_frase(prod["nome"])
    ate = indices[-1]

    def ultimo(ok):
        return next((i for i in reversed(indices) if ok(i)), -1)

    def fora(i, onde, falta):
        t = valor("t", i)
        if F.nulo(t) or t == 0:
            return f"Em {F.rotulo_mes(p[i])}, não houve importação de {nome}."
        if pequena(i):
            return (f"Em {F.rotulo_mes(p[i])}, a importação de {nome} foi de {F.toneladas(t)}, menos de {F.fmt0(bm['corte_amostra_t'])} t: "
                    f"amostra pequena, fora {onde}.")
        return f"Em {F.rotulo_mes(p[i])}, não há {falta} para {nome}."

    def quando(i, onde, falta):
        if i == ate:
            return f"Em {F.rotulo_mes(p[i])}"
        ultimo_mes = "comparável do período" if onde == "da comparação" else "do período no gráfico"
        return f"{fora(ate, onde, falta)} Em {F.rotulo_mes(p[i])}, o último mês {ultimo_mes}"

    frases = {"bm": "", "spread": "", "brl": ""}

    def comparavel(i):
        return not pequena(i) and not F.nulo(valor("spread_pct", i))

    i = ultimo(comparavel)
    if i >= 0:
        base = base_de(i)
        na_origem = base["comparacao"].startswith("FOB")
        brasil = f"{F.por_tonelada(valor('fob' if na_origem else 'cif', i))} {'FOB' if na_origem else 'CIF'}"
        s, usd = valor("spread_pct", i), valor("spread_usd_t", i)
        sinal = F.sinal_de(s, F.fmt1, "+")
        relacao = f"{F.fmt1(abs(s))}% {'abaixo' if sinal == F.MENOS else 'acima'} do benchmark" if sinal else "praticamente igual ao benchmark"
        referencia = prod["serie"] + (f", a referência do {prod['nome']}" if prod.get("proxy") else "")
        frases["bm"] = (
            f"{quando(i, 'da comparação', 'benchmark do Banco Mundial')}, o Brasil importou {nome} a {F.por_tonelada(valor('fob', i))} FOB e "
            f"{F.por_tonelada(valor('cif', i))} CIF; o benchmark do Banco Mundial ({referencia}), na base {base['base']}, foi de "
            f"{F.por_tonelada(valor('bm', i))}. Na base comparável ({base['comparacao']}), o preço do Brasil, de {brasil}, ficou {relacao}. "
            f"{NAO_E_AGIO} {FONTE_BM}"
        )
        meses = [x for x in indices if comparavel(x)]
        acima = sum(1 for x in meses if valor("spread_pct", x) > 0)
        em_usd = "" if F.nulo(usd) else f" ({F.sinal_de(usd, F.fmt0, '+')}US$ {F.fmt0(abs(usd))}/t)"
        quando_spread = f"em {F.rotulo_mes(p[i])}" if i == ate else f"em {F.rotulo_mes(p[i])}, o último mês comparável do período"
        antes = "" if i == ate else f"{fora(ate, 'da comparação', 'benchmark do Banco Mundial')} "
        frases["spread"] = (
            f"{antes}Spread de {nome} na base comparável ({base['comparacao']}) {quando_spread}: {F.com_sinal(s, F.fmt1, '+')}%{em_usd}, "
            f"com o preço do Brasil a {brasil} e o benchmark a {F.por_tonelada(valor('bm', i))}. No período, o spread ficou acima de zero em "
            f"{F.fmt0(acima)} de {F.fmt0(len(meses))} {'mês comparável' if len(meses) == 1 else 'meses comparáveis'}. {NAO_E_AGIO} {FONTE_BM}"
        )

    b = ultimo(lambda x: not pequena(x) and not F.nulo(valor("cif_brl_t", x)))
    if b >= 0:
        k_antes = indice(bm["periodos"], mes_ano_antes(p[b]))
        antes = prod["cif_brl_t"][k_antes] if k_antes >= 0 and not prod["amostra_pequena"][k_antes] else None
        dif = diferenca_em_texto(F.variacao_pct(valor("cif_brl_t", b), antes), F.rotulo_mes(mes_ano_antes(p[b])))
        ptax = bm["ptax"][k(b)]
        frases["brl"] = (
            f"{quando(b, 'do gráfico', 'PTAX do mês')}, o CIF de {nome} em reais, pela PTAX venda média do mês"
            f"{'' if F.nulo(ptax) else f' (R$ {F.fmt4(ptax)})'}, foi {reais(valor('cif_brl_t', b))}{f', {dif}' if dif else ''}. {FONTE_PTAX}"
        )
    return frases


# --- aria-labels dos gráficos (o texto do script mais a frase) --------------------------------
def _intervalo(dados: dict, indices: list[int]) -> tuple[str, str]:
    p = dados["mensal"]["periodos"]
    return F.rotulo_mes(p[indices[0]]), F.rotulo_mes(p[indices[-1]])


def _com_frase(rotulo: str, frase: str) -> str:
    return f"{rotulo} {frase}" if frase else rotulo


def rotulo_precos(dados: dict, g: str, indices: list[int]) -> str:
    """(desenharPrecos, aria-label do canvas)"""
    ate = dados["mensal"]["periodos"][indices[-1]]
    return f"Preço implícito FOB e CIF em US$ por tonelada, {F.NOMES[g]}. A tabela abaixo traz os valores. {frase_precos(dados, g, ate)}"


def rotulo_frete(dados: dict, g: str, indices: list[int]) -> str:
    """(desenharFrete, aria-label do canvas)"""
    ate = dados["mensal"]["periodos"][indices[-1]]
    return f"Frete em US$ por tonelada, {F.NOMES[g]}. A tabela abaixo traz os valores. {frase_frete(dados, g, ate)}"


def rotulo_nutrientes(dados: dict, g: str, indices: list[int], moeda: str = "usd") -> str:
    """(desenharNutrientes, aria-label do canvas)"""
    nu = dados["nutrientes"]
    nomes = ", ".join(nu["produtos"][x]["nome"] for x in produtos_nutrientes(dados, g))
    de, ate = _intervalo(dados, indices)
    frase = frase_nutrientes(dados, g, dados["mensal"]["periodos"][indices[-1]], moeda)
    return (f"Custo por tonelada de nutriente no porto, em {MOEDAS_NUTR[moeda]['rotulo']}, de {nomes}, de {de} a {ate}. "
            f"A tabela abaixo traz os valores. {frase}")


def rotulo_troca(dados: dict, g: str, indices: list[int]) -> str:
    """(desenharTroca, aria-label do canvas)"""
    tr = dados["troca"]
    nomes = ", ".join(tr["produtos"][x]["nome"] for x in PRODUTOS_TROCA.get(g, TROCA_TODOS))
    de, ate = _intervalo(dados, indices)
    frase = frase_troca(dados, g, dados["mensal"]["periodos"][indices[-1]])
    return (f"Relação de troca no porto, toneladas de soja por tonelada de {nomes}, de {de} a {ate}, com a média histórica tracejada. "
            f"A tabela abaixo traz os valores. {frase}")


def rotulos_benchmark(dados: dict, chave: str, indices: list[int]) -> dict[str, str]:
    """(desenharBenchmark, aria-labels dos três canvas)"""
    nome = dados["benchmark"]["produtos"][chave]["nome"]
    de, ate = _intervalo(dados, indices)
    frases = frases_benchmark(dados, chave, indices)
    return {
        "bm": _com_frase(f"{nome}: preço FOB e CIF do Brasil e benchmark do Banco Mundial, em US$ por tonelada, de {de} a {ate}. "
                         "A tabela abaixo traz os valores.", frases["bm"]),
        "spread": _com_frase(f"{nome}: spread em relação ao benchmark do Banco Mundial, em porcentagem, de {de} a {ate}. "
                             "A tabela abaixo traz os valores.", frases["spread"]),
        "brl": _com_frase(f"{nome}: preço CIF do Brasil em reais por tonelada, de {de} a {ate}. A tabela abaixo traz os valores.", frases["brl"]),
    }


def gerar(ctx: Contexto) -> None:
    """Visão padrão do script (lerUrl sem hash): todos os grupos, do primeiro ao último mês, o
    primeiro produto do benchmark (KCl) e o custo por nutriente em US$."""
    dados = ctx.dados
    g = "TOTAL"
    indices = list(range(len(ctx.periodos)))
    ate = ctx.periodos[indices[-1]]

    ctx.preencher("resumo-precos", esc(frase_precos(dados, g, ate)))
    ctx.definir_atributo("grafico-precos", "aria-label", rotulo_precos(dados, g, indices))
    ctx.preencher("resumo-frete", esc(frase_frete(dados, g, ate)))
    ctx.definir_atributo("grafico-frete", "aria-label", rotulo_frete(dados, g, indices))

    # Sem o bloco, o script esconde a seção e não escreve nada nela.
    if dados.get("nutrientes"):
        ctx.preencher("resumo-nutrientes", esc(frase_nutrientes(dados, g, ate)))
        ctx.definir_atributo("grafico-nutrientes", "aria-label", rotulo_nutrientes(dados, g, indices))
    if dados.get("troca"):
        ctx.preencher("resumo-troca", esc(frase_troca(dados, g, ate)))
        ctx.definir_atributo("grafico-troca", "aria-label", rotulo_troca(dados, g, indices))
    chaves = produtos_bm(dados, g)
    if dados.get("benchmark") and chaves:
        frases = frases_benchmark(dados, chaves[0], indices)
        rotulos = rotulos_benchmark(dados, chaves[0], indices)
        for parte in ("bm", "spread", "brl"):
            if frases[parte]:
                ctx.preencher(f"resumo-{parte}", esc(frases[parte]))
            ctx.definir_atributo(f"grafico-{parte}", "aria-label", rotulos[parte])
