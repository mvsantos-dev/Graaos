"""index.html: as tabelas de "Ver tabela" (e a de frete por rota) já no HTML, iguais às que o script
monta na visão padrão, a da página sem hash: todos os grupos, o período inteiro, o ano do fim do
período no ranking e nas rotas, o primeiro produto do benchmark e o custo por nutriente em US$; no
mapa de fluxos (assets/fluxos.js), o último ano completo.

Cada função espelha uma do script (nome entre parênteses), com os formatadores de formato.py. O
teste de navegador (tests/e2e/test_estatico_tabelas.py) compara o innerHTML de cada tabela com e
sem JavaScript. A tabela de rotas tem uma versão de celular (sem a posição e sem a barra): o HTML
traz a de tela larga, que o script troca ao carregar. A barra do frete usa a cor de "Todos" do
tema claro, lida do radar.css (no tema escuro, o script a redesenha na cor do tema).

Para a tabela dizer o que mostra sem o script, o build também escreve o título e a nota do frete
por rota, a nota de cada cartão (tabelas_notas.py: grupo, período, produto, o "*" da amostra
pequena) e as fontes do rodapé, e tira o "oculto" das seções que o script mostra com estes dados.
Texto que outra etapa já escreveu fica como está.

Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet); BCB/PTAX.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal

from . import formato as F
from .contexto import Contexto, ErroEstatico, esc

# Tabelas fixas do script (mesmos nomes)
PRODUTOS_TROCA = {"K": ["kcl"], "N": ["ureia"], "P": ["map"]}
PRODUTOS_NUTR = {"N": ["ureia", "sulfato_amonio", "nitrato_amonio"], "P": ["map", "dap", "tsp"], "K": ["kcl"]}
PRODUTOS_BM = {"K": ["kcl"], "N": ["ureia"], "P": ["map", "dap", "tsp"]}
ORDEM_BM = ["kcl", "ureia", "map", "dap", "tsp"]
# assets/fluxos.js
DESCRICAO_GRUPO = {"TOTAL": "todos os grupos", "N": "nitrogenados", "P": "fosfatados", "K": "potássicos", "NPK": "compostos (NPK)"}
OUTROS_FLUXOS = "Outros (menos de 1.000 t ou sem coordenada)"  # texto fixo da tabela do fluxos.js
CORTE_ROTA_PADRAO = 50000  # o "?? 50000" do textoCorte do fluxos.js

TITULO_ROTAS = "Frete por rota"  # texto do index.html, que o script completa com o ano


class Bruto(str):
    """Célula já em HTML (a barra do frete por rota): entra sem escapar."""


# --- Como o JavaScript escreve um valor ------------------------------------------------------
def js(v) -> str:
    """String(v) (e ${v}) do JavaScript: null, inteiros sem ".0", decimais no formato do Number."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        if math.isinf(v):
            return "Infinity" if v > 0 else "-Infinity"
        if v == 0:
            return "0"
        sinal = "-" if v < 0 else ""
        _, digitos, expoente = Decimal(repr(abs(v))).normalize().as_tuple()
        d = "".join(map(str, digitos))
        k, n = len(d), len(d) + expoente  # n: posição da vírgula, como no Number::toString
        if k <= n <= 21:
            texto = d + "0" * (n - k)
        elif 0 < n <= 21:
            texto = f"{d[:n]}.{d[n:]}"
        elif -6 < n <= 0:
            texto = "0." + "0" * -n + d
        else:
            texto = d[0] + (f".{d[1:]}" if k > 1 else "") + f"e{'+' if n - 1 >= 0 else '-'}{abs(n - 1)}"
        return sinal + texto
    return str(v)


def intl(f, v) -> str:
    """f.format(v) do Intl sem o teste de nulo: null vira 0, como no navegador."""
    return f(0 if v is None else v)


def _n(f, v) -> str:
    """(n) nulo vira "–"."""
    return F.TRACO if F.nulo(v) else f(v)


def _js_round(x: float) -> int:
    """Math.round: meio para cima (em direção a +infinito)."""
    piso = math.floor(x)
    return piso + 1 if x - piso >= 0.5 else piso


def indice(lista, valor) -> int:
    """indexOf: -1 quando não acha."""
    try:
        return lista.index(valor)
    except ValueError:
        return -1


def em(lista, k):
    """lista[k] do JavaScript: undefined (None) fora da lista, inclusive k negativo."""
    return lista[k] if lista is not None and 0 <= k < len(lista) else None


def _f(v):
    """Número do JSON como double (as contas do script são em ponto flutuante)."""
    return None if v is None else float(v)


# --- HTML das tabelas ------------------------------------------------------------------------
def celula(tag: str, conteudo, num: bool = False, escopo: bool = False) -> str:
    atributos = (' class="num"' if num else "") + (' scope="col"' if escopo else "")
    corpo = conteudo if isinstance(conteudo, Bruto) else esc(conteudo if isinstance(conteudo, str) else js(conteudo))
    return f"<{tag}{atributos}>{corpo}</{tag}>"


def tabela(colunas: list[tuple[str, bool]], linhas: list[list]) -> str:
    """(tabela) colunas: [(título, numérica)]; linhas: listas de textos (Bruto para HTML pronto)."""
    cabeca = "".join(celula("th", titulo, num) for titulo, num in colunas)
    corpo = "".join("<tr>" + "".join(celula("td", v, colunas[i][1]) for i, v in enumerate(linha)) + "</tr>" for linha in linhas)
    return f"<table><thead><tr>{cabeca}</tr></thead><tbody>{corpo}</tbody></table>"


# --- Visão (o "estado" do script) ------------------------------------------------------------
@dataclass
class Visao:
    """(estado) filtro da página. Sem hash, lerUrl deixa o grupo "TOTAL", o período inteiro, o ano
    das rotas e o produto do benchmark em null (o script os resolve) e o custo por nutriente em US$."""

    grupo: str
    de: str
    ate: str
    ano_rotas: int | None = None
    bm: str | None = None

    @classmethod
    def padrao(cls, dados: dict) -> "Visao":
        p = dados["mensal"]["periodos"]
        return cls(grupo="TOTAL", de=p[0], ate=p[-1])

    def indices(self, dados: dict) -> list[int]:
        """(indicesEntre)"""
        p = dados["mensal"]["periodos"]
        return list(range(p.index(self.de), p.index(self.ate) + 1))

    @property
    def ano(self) -> int:
        return int(self.ate[:4])

    def ano_das_rotas(self) -> int:
        """(anoRotas)"""
        return self.ano_rotas if self.ano_rotas is not None else self.ano


def n_meses(dados: dict, ano: int) -> int:
    """(nMeses)"""
    i = indice(dados["anual"]["anos"], ano)
    return dados["anual"]["n_meses"][i] if i >= 0 else 0


def ano_parcial(dados: dict, ano: int) -> bool:
    return 0 < n_meses(dados, ano) < 12


def rotulo_ano(dados: dict, ano: int) -> str:
    """(rotuloAno) "2026 (jan–set)" num ano parcial."""
    return f"{ano} (jan–{F.MESES[n_meses(dados, ano) - 1]})" if ano_parcial(dados, ano) else str(ano)


# --- Tabelas do script principal -------------------------------------------------------------
def toneladas(dados: dict, v: Visao) -> str:
    """(desenharToneladas)"""
    p = dados["mensal"]["periodos"]
    grupos = F.GRUPOS if v.grupo == "TOTAL" else [v.grupo]
    empilhado = len(grupos) > 1
    colunas = [("Mês", False)] + [(f"{g} (t)", True) for g in grupos] + ([("Total (t)", True)] if empilhado else [])
    linhas = []
    for i in v.indices(dados):
        valores = [_f(dados["mensal"][g]["t"][i]) if dados["mensal"][g]["t"][i] is not None else 0.0 for g in grupos]
        total = 0.0
        for x in valores:
            total += x
        linhas.append([F.rotulo_mes(p[i])] + [F.fmt0(x) for x in valores] + ([F.fmt0(total)] if empilhado else []))
    return tabela(colunas, linhas)


def ranking(dados: dict, v: Visao, tipo: str) -> str:
    """(desenharRanking) tipo "origens" ou "portos"."""
    ano = v.ano
    bloco = dados["origens"] if tipo == "origens" else dados["urfs"]
    linhas = (bloco["dados"].get(str(ano)) or {}).get(v.grupo) or []
    ano_anterior = f"jan–{F.MESES[n_meses(dados, ano) - 1]}/{ano - 1}" if ano_parcial(dados, ano) else str(ano - 1)
    colunas = [("#", False), ("País" if tipo == "origens" else "URF", False), ("Toneladas", True), ("Share", True),
               (f"Var. t vs {ano_anterior}", True), ("Var. share", True)]
    if tipo == "origens":
        colunas.append(("US$/t FOB", True))
    saida = []
    for i, r in enumerate(linhas):
        nome = r[1] if tipo == "origens" else F.nome_urf(r[1])
        base = ["" if r[1] == "Outros" else str(i + 1), nome, intl(F.fmt0, r[2]), F.pct(r[3]), F.variacao(r[4]), F.variacao(r[5], " p.p.")]
        saida.append(base + [_n(F.fmt0, r[6])] if tipo == "origens" else base)
    return tabela(colunas, saida)


def hhi(dados: dict, v: Visao) -> str:
    """(desenharHhi)"""
    ano_de, ano_ate = int(v.de[:4]), int(v.ate[:4])
    anual = dados["anual"]
    anos = [a for a in anual["anos"] if ano_de <= a <= ano_ate]
    grupos = F.GRUPOS if v.grupo == "TOTAL" else [v.grupo]
    colunas = [("Ano", False)]
    for g in grupos:
        colunas += [(f"{g} HHI", True), (f"{g} líder", False), (f"{g} CR3", True)]
    linhas = []
    for a in anos:
        i = anual["anos"].index(a)
        linha = [rotulo_ano(dados, a)]
        for g in grupos:
            x = anual[g]
            linha += [intl(F.fmt0, x["hhi"][i]), f"{js(x['lider'][i])} ({F.pct(x['lider_share_pct'][i])})", F.pct(x["cr3_pct"][i])]
        linhas.append(linha)
    return tabela(colunas, linhas)


def com_alfa(hexa: str, alfa: float) -> str:
    """(comAlfa)"""
    n = int(hexa.replace("#", ""), 16)
    return f"rgba({(n >> 16) & 255}, {(n >> 8) & 255}, {n & 255}, {js(alfa)})"


@dataclass
class Rotas:
    titulo: str
    nota: str
    html: str  # vazio: o script esvazia a caixa (nenhuma rota no ano e grupo)


def rotas(dados: dict, v: Visao, cor_grupo: str) -> Rotas | None:
    """(tabelaRotas) versão de tela larga; cor_grupo é a cor (#rrggbb) do grupo no tema."""
    bloco_rotas = dados.get("rotas")
    if not bloco_rotas:
        return None
    ano = v.ano_das_rotas()
    bloco = (bloco_rotas["dados"].get(str(ano)) or {}).get(v.grupo)
    corte = bloco.get("corte_t") if bloco and bloco.get("corte_t") is not None else bloco_rotas["corte_t"]
    titulo = f"{TITULO_ROTAS} · {rotulo_ano(dados, ano)}"
    if not bloco or not bloco["rotas"]:
        return Rotas(titulo, f"Nenhuma rota com pelo menos {intl(F.fmt0, corte)} t neste ano e grupo.", "")
    proporcional = f" ({intl(F.fmt0, bloco_rotas['corte_t'])} t × {n_meses(dados, ano)}/12 meses)" if ano_parcial(dados, ano) else ""
    nota = (f"Só rotas com volume relevante: pelo menos {intl(F.fmt0, corte)} t no ano{proporcional}, cerca de um navio Supramax. "
            f"São {js(bloco['n_relevantes'])} de {js(bloco['n_rotas'])} rotas e {F.pct(bloco['share_relevantes_pct'])} das toneladas; "
            f"frete médio delas: {F.por_tonelada(bloco['frete_relevantes'])}. Mostrando as {len(bloco['rotas'])} maiores; "
            "todas estão em data/processed/rotas_ano.csv.")
    max_frete = max([_f(r[5]) if r[5] is not None else 0.0 for r in bloco["rotas"]] + [1.0])
    cor_barra = com_alfa(cor_grupo, 0.5)
    colunas = [("#", False), ("Origem", False), ("URF", False), ("Toneladas", True), ("Share", True), ("Frete US$/t", True), ("", False),
               ("Frete no CIF", True), ("Meses", True)]
    linhas = []
    for i, r in enumerate(bloco["rotas"]):
        largura = _js_round((64 * (_f(r[5]) if r[5] is not None else 0.0)) / max_frete)
        barra = Bruto(f'<span class="barra" style="width: {largura}px; background: {cor_barra};"></span>')
        linhas.append([str(i + 1), F.TRACO if r[0] is None else r[0], F.nome_urf(r[2]) if r[2] else F.TRACO, intl(F.fmt0, r[3]), F.pct(r[4]),
                       _n(F.fmt0, r[5]), barra, F.pct(r[6]), f"{js(r[7])}/{n_meses(dados, ano)}"])
    return Rotas(titulo, nota, tabela(colunas, linhas))


def serie_mensal(dados: dict, v: Visao, campo: str) -> list:
    """(serieMensal) valor em US$ por tonelada, mês a mês."""
    m = dados["mensal"][v.grupo]
    saida = []
    for i in v.indices(dados):
        t, x = m["t"][i], m[campo][i]
        saida.append((_f(x) * 1e6) / _f(t) if t is not None and t > 0 and not F.nulo(x) else None)
    return saida


def precos(dados: dict, v: Visao) -> str:
    """(desenharPrecos)"""
    p = dados["mensal"]["periodos"]
    fob, cif = serie_mensal(dados, v, "fob_musd"), serie_mensal(dados, v, "cif_musd")
    return tabela([("Mês", False), ("US$/t FOB", True), ("US$/t CIF", True)],
                  [[F.rotulo_mes(p[i]), _n(F.fmt0, fob[k]), _n(F.fmt0, cif[k])] for k, i in enumerate(v.indices(dados))])


def frete(dados: dict, v: Visao) -> str:
    """(desenharFrete)"""
    p = dados["mensal"]["periodos"]
    m = dados["mensal"][v.grupo]
    serie = serie_mensal(dados, v, "frete_musd")
    linhas = []
    for k, i in enumerate(v.indices(dados)):
        cif = m["cif_musd"][i]
        peso = (100 * (_f(m["frete_musd"][i]) if m["frete_musd"][i] is not None else 0.0)) / _f(cif) if cif is not None and cif > 0 else None
        linhas.append([F.rotulo_mes(p[i]), _n(F.fmt0, serie[k]), F.pct(peso)])
    return tabela([("Mês", False), ("Frete US$/t", True), ("Frete no CIF", True)], linhas)


def nutrientes(dados: dict, v: Visao) -> str | None:
    """(desenharNutrientes) a tabela não muda com a moeda escolhida (traz US$ e R$)."""
    nu = dados.get("nutrientes")
    if not nu:
        return None
    p = dados["mensal"]["periodos"]
    chaves = [k for k in PRODUTOS_NUTR.get(v.grupo, ["ureia", "map", "kcl"]) if nu["produtos"].get(k)]
    produtos = [dict(nu["produtos"][k], chave=k, simbolo=nu["nutrientes"][nu["produtos"][k]["nutriente"]]) for k in chaves]

    def j(i):
        return indice(nu["periodos"], p[i])

    def valor(prod, campo, i):
        k = j(i)
        return None if k < 0 or prod.get(campo) is None else em(prod[campo], k)

    def pequena(prod, i):
        k = j(i)
        return k >= 0 and bool(em(prod["amostra_pequena"], k))

    colunas = [("Mês", False)]
    for x in produtos:
        colunas += [(f"{x['nome']} t", True), (f"{x['nome']} CIF US$/t", True),
                    (f"{x['nome']} US$/t de {x['simbolo']}", True), (f"{x['nome']} R$/t de {x['simbolo']}", True)]
    linhas = []
    for i in v.indices(dados):
        linha = [F.rotulo_mes(p[i])]
        for x in produtos:
            marca = "*" if pequena(x, i) else ""
            linha += [_n(F.fmt0, valor(x, "t", i)), _n(F.fmt0, valor(x, "cif", i)),
                      f"{_n(F.fmt0, valor(x, 'custo', i))}{marca}", f"{_n(F.fmt0, valor(x, 'custo_brl', i))}{marca}"]
        linhas.append(linha)
    return tabela(colunas, linhas)


def troca(dados: dict, v: Visao) -> str | None:
    """(desenharTroca)"""
    tr = dados.get("troca")
    if not tr:
        return None
    p = dados["mensal"]["periodos"]
    produtos = [tr["produtos"][k] for k in PRODUTOS_TROCA.get(v.grupo, ["kcl", "ureia", "map"]) if tr["produtos"].get(k)]

    def valor(prod, campo, i):
        j = indice(tr["periodos"], p[i])
        return None if j < 0 else em(prod[campo], j)

    def sacas(x):
        return None if F.nulo(x) else (_f(x) * 1000) / _f(tr["kg_saca"])

    colunas = [("Mês", False), ("Soja US$/t FOB", True)]
    for x in produtos:
        colunas += [(f"{x['nome']} US$/t CIF", True), (f"{x['nome']} t soja/t", True), (f"{x['nome']} sacas/t", True)]
    linhas = []
    for i in v.indices(dados):
        j = indice(tr["periodos"], p[i])
        linha = [F.rotulo_mes(p[i]), _n(F.fmt0, None if j < 0 else em(tr["soja_fob"], j))]
        for x in produtos:
            r = valor(x, "razao", i)
            linha += [_n(F.fmt0, valor(x, "cif", i)), _n(F.fmt2, r), _n(F.fmt1, sacas(r))]
        linhas.append(linha)
    return tabela(colunas, linhas)


def produto_bm(dados: dict, v: Visao) -> str | None:
    """(produtosBm e o início de desenharBenchmark) o produto mostrado: o da visão ou o primeiro."""
    bm = dados.get("benchmark")
    if not bm:
        return None
    chaves = [k for k in PRODUTOS_BM.get(v.grupo, ORDEM_BM) if (bm.get("produtos") or {}).get(k)]
    if not chaves:
        return None
    return v.bm if v.bm in chaves else chaves[0]


def benchmark(dados: dict, v: Visao) -> str | None:
    """(desenharBenchmark) a tabela do produto mostrado."""
    chave = produto_bm(dados, v)
    if chave is None:
        return None
    bm = dados["benchmark"]
    prod = bm["produtos"][chave]
    p = dados["mensal"]["periodos"]

    def j(i):
        return indice(bm["periodos"], p[i])

    def valor(campo, i):
        k = j(i)
        return None if k < 0 else em(prod[campo], k)

    def pequena(i):
        k = j(i)
        return k >= 0 and bool(em(prod["amostra_pequena"], k))

    def base_de(i):
        vigentes = [b for b in prod["bases"] if b["desde"] <= p[i]]
        return vigentes[-1] if vigentes else prod["bases"][0]

    def n(x, f):
        return F.TRACO if F.nulo(x) else F.com_sinal(x, f).replace(F.MENOS, "-", 1)

    colunas = [("Mês", False), ("Toneladas", True), ("FOB Brasil US$/t", True), ("CIF Brasil US$/t", True), ("Banco Mundial US$/t", True),
               ("Base", False), ("Spread US$/t", True), ("Spread %", True), ("Custo posto US$/t", True), ("PTAX R$/US$", True),
               ("CIF R$/t", True), ("Amostra", False)]
    linhas = []
    for i in v.indices(dados):
        k = j(i)
        base = base_de(i)
        linhas.append([F.rotulo_mes(p[i]), n(valor("t", i), F.fmt0), n(valor("fob", i), F.fmt0), n(valor("cif", i), F.fmt0), n(valor("bm", i), F.fmt1),
                       f"{js(base['base'])} ({js(base['comparacao'])})", n(valor("spread_usd_t", i), F.fmt0), n(valor("spread_pct", i), F.fmt1),
                       n(valor("custo_posto_usd_t", i), F.fmt0), n(None if k < 0 else em(bm["ptax"], k), F.fmt4), n(valor("cif_brl_t", i), F.fmt0),
                       "pequena" if pequena(i) else ""])
    return tabela(colunas, linhas)


# --- Tabela alternativa do mapa de fluxos (assets/fluxos.js) ----------------------------------
def fmt_int(v) -> str:
    """new Intl.NumberFormat("pt-BR"): até 3 casas."""
    return F.numero(v, 0, 3)


def fmt_ate1(v) -> str:
    """{maximumFractionDigits: 1}"""
    return F.numero(v, 0, 1)


def ano_padrao_fluxos(mapa: dict) -> int:
    """(receberDados) o último ano completo; sem nenhum, o último."""
    for ano, meses in zip(reversed(mapa["anos"]), reversed(mapa["n_meses"])):
        if meses == 12:
            return ano
    return mapa["anos"][-1]


def fluxos(dados: dict, ano: int | None = None, grupo: str = "TOTAL") -> str | None:
    """(tabela do fluxos.js) origens, portos de chegada e rotas acima do corte do ano e grupo."""
    bloco = dados.get("mapa")
    if not bloco:
        return None
    ano = ano_padrao_fluxos(bloco) if ano is None else ano
    r = (bloco["dados"].get(str(ano)) or {}).get(grupo) or {"t": 0, "origens": [], "outros_t": 0, "rotas": [], "portos": []}
    i_ano = indice(bloco["anos"], ano)
    meses = em(bloco["n_meses"], i_ano)
    parcial = bool(meses) and meses < 12
    rotulo = f"{ano} (jan–{F.MESES[meses - 1]})" if parcial else str(ano)
    corte = em(bloco.get("corte_rota_t"), i_ano)
    corte = CORTE_ROTA_PADRAO if corte is None else corte
    texto_corte = f"pelo menos {fmt_ate1(_f(corte) / 1000)} mil t {f'em jan–{F.MESES[meses - 1]}' if parcial else 'no ano'}"
    minimo = bloco.get("minimo_origem_t")
    minimo = 1000 if minimo is None else minimo

    def nome_pais(co):
        nome = em(bloco["paises"].get(co), 0)
        return co if nome is None else nome

    def porto(i):
        return bloco["portos"][i]

    def novo(v, t) -> bool:
        """(variacao(...).texto === "novo") sobre base quase zero."""
        if v is None or not math.isfinite(v):
            return False
        base = _f(t) / (1 + _f(v) / 100) if t is not None and v > -100 else None
        return base is not None and base < minimo

    def fmt_n(v, f):
        return F.TRACO if v is None else f(v)

    def cabeca(titulos, numerica):
        return "<thead><tr>" + "".join(celula("th", t, numerica(i), escopo=True) for i, t in enumerate(titulos)) + "</tr></thead>"

    def caption(texto):
        return f'<caption class="leitor">{esc(texto)}</caption>'

    td = celula
    corpo = "".join(
        "<tr>" + td("td", nome_pais(o[0])) + td("td", fmt_n(o[1], fmt_int), True) + td("td", fmt_n(o[2], F.fmt1), True)
        + td("td", "novo" if novo(o[3], o[1]) else fmt_n(o[3], F.fmt1), True) + td("td", fmt_n(o[4], F.fmt0), True)
        + td("td", fmt_n(o[5], F.fmt0), True) + "</tr>"
        for o in r["origens"])
    corpo += "<tr>" + td("td", OUTROS_FLUXOS) + td("td", fmt_n(r["outros_t"], fmt_int), True) + "<td></td>" * 4 + "</tr>"
    origens = (f"<table>{caption(f'Origens em {rotulo}, {DESCRICAO_GRUPO[grupo]}')}"
               + cabeca(["País de origem", "Toneladas", "Share %", "Var. % a/a", "Frete US$/t", "CIF US$/t"], lambda i: i > 0)
               + f"<tbody>{corpo}</tbody></table>")

    def var_porto(x):
        return F.TRACO if x[2] is None else "novo" if novo(x[2], x[1]) else fmt_n(x[2], F.fmt1)

    corpo = "".join(
        "<tr>" + td("td", porto(x[0])[0]) + td("td", porto(x[0])[1]) + td("td", fmt_n(x[1], fmt_int), True)
        + td("td", fmt_n((100 * (_f(x[1]) or 0.0)) / _f(r["t"]) if r["t"] else None, F.fmt1), True) + td("td", var_porto(x), True)
        + td("td", fmt_n(x[3], F.fmt0), True) + td("td", fmt_n(x[4], F.fmt0), True) + "</tr>"
        for x in r["portos"])
    portos = (f"<table>{caption(f'Portos em {rotulo}, {DESCRICAO_GRUPO[grupo]}')}"
              + cabeca(["Porto", "UF", "Toneladas", "Share %", "Var. % a/a", "Frete US$/t", "CIF US$/t"], lambda i: i > 1)
              + f"<tbody>{corpo}</tbody></table>")

    corpo = "".join(
        "<tr>" + td("td", nome_pais(x[0])) + td("td", porto(x[1])[0]) + td("td", fmt_n(x[2], fmt_int), True) + td("td", fmt_n(x[3], F.fmt0), True) + "</tr>"
        for x in r["rotas"])
    rotas_ = (f"<table>{caption(f'Rotas com {texto_corte}')}"
              + cabeca(["Origem", "Porto", "Toneladas", "Frete US$/t"], lambda i: i > 1)
              + f"<tbody>{corpo}</tbody></table>")
    return (origens + '<h4 class="subtitulo">Portos de chegada</h4>' + portos
            + f'<h4 class="subtitulo">{esc(f"Rotas com {texto_corte}")}</h4>' + rotas_)


# --- Etapa do build --------------------------------------------------------------------------
def cor_do_tema_claro(css: str, variavel: str) -> str:
    """Valor (#rrggbb) de uma variável no primeiro bloco :root do radar.css (o tema claro)."""
    raiz = re.search(r":root\s*\{([^}]*)\}", css)
    achado = raiz and re.search(re.escape(variavel) + r"\s*:\s*(#[0-9a-fA-F]{6})\s*;", raiz.group(1))
    if not achado:
        raise ErroEstatico(f"radar.css: não achei {variavel} (#rrggbb) no bloco :root")
    return achado.group(1).lower()


def tabelas(dados: dict, v: Visao, cor_grupo: str) -> dict[str, str]:
    """id da caixa -> HTML da tabela, só das que o script desenha nesta visão (e com linhas)."""
    rot = rotas(dados, v, cor_grupo)
    saida = {
        "tabela-toneladas": toneladas(dados, v),
        "tabela-origens": ranking(dados, v, "origens"),
        "tabela-hhi": hhi(dados, v),
        "tabela-fluxos": fluxos(dados),
        "tabela-portos": ranking(dados, v, "portos"),
        "tabela-rotas": rot.html if rot else None,
        "tabela-precos": precos(dados, v),
        "tabela-frete": frete(dados, v),
        "tabela-nutrientes": nutrientes(dados, v),
        "tabela-bm": benchmark(dados, v),
        "tabela-troca": troca(dados, v),
    }
    return {k: x for k, x in saida.items() if x}


def _trocar_texto(ctx: Contexto, id_: str, de: tuple[str, ...], para: str) -> None:
    """Troca o conteúdo do elemento quando ele ainda é um de `de` (o texto do index.html). Se outra
    etapa já o escreveu, fica como está; se o id sumiu do index.html, o build falha."""
    abertura = list(re.finditer(r"<([a-zA-Z][\w-]*)\b[^>]*?\sid=\"" + re.escape(id_) + r"\"[^>]*>", ctx.html))
    if len(abertura) != 1:
        raise ErroEstatico(f'index.html: esperava um elemento com id="{id_}", achei {len(abertura)}')
    m = re.compile(r"([^<]*)</" + re.escape(abertura[0].group(1)) + ">").match(ctx.html, abertura[0].end())
    if m and m.group(1) in de:
        ctx.html = ctx.html[: m.start(1)] + esc(para) + ctx.html[m.end(1):]


def _mostrar(ctx: Contexto, id_: str, visivel: bool) -> None:
    """(classList.toggle("oculto", !visivel)) na seção de tabela que o script mostra ou esconde."""
    tag = re.search(r"<[a-zA-Z][\w-]*\b[^>]*?\sid=\"" + re.escape(id_) + r"\"[^>]*>", ctx.html)
    classe = re.search(r'\sclass="([^"]*)"', tag.group(0)) if tag else None
    if not classe:
        raise ErroEstatico(f'index.html: esperava o id="{id_}" com atributo class')
    tokens = [c for c in classe.group(1).split() if c != "oculto"] + ([] if visivel else ["oculto"])
    if tokens != classe.group(1).split():
        ctx.definir_atributo(id_, "class", " ".join(tokens))


def gerar(ctx: Contexto) -> None:
    dados = ctx.dados
    v = Visao.padrao(dados)
    try:
        css = (ctx.site / "assets" / "radar.css").read_text(encoding="utf-8")
    except OSError as e:
        raise ErroEstatico(f"não consegui ler o assets/radar.css do site: {e}") from e
    cor = cor_do_tema_claro(css, "--g-total" if v.grupo == "TOTAL" else f"--g-{v.grupo.lower()}")
    for id_, html in tabelas(dados, v, cor).items():
        ctx.preencher(id_, html)
    # Seções que o script esconde sem os dados: sem JavaScript, o mesmo (as tabelas ficam à vista).
    _mostrar(ctx, "secao-nutrientes", bool(dados.get("nutrientes")))
    _mostrar(ctx, "secao-bm", produto_bm(dados, v) is not None)
    _mostrar(ctx, "secao-troca", bool(dados.get("troca")))
    _mostrar(ctx, "secao-rotas", bool(dados.get("rotas")))
    # Título e nota do frete por rota, notas dos cartões e fontes do rodapé, como o script os
    # escreve (se outra etapa não os escreveu): sem JavaScript, cada tabela diz o que mostra.
    from .tabelas_notas import FONTE_RODAPE, fonte_rodape, notas  # tabelas_notas importa este módulo

    rot = rotas(dados, v, cor)
    if rot:
        _trocar_texto(ctx, "titulo-frete-rotas", (TITULO_ROTAS,), rot.titulo)
        _trocar_texto(ctx, "nota-frete-rotas", ("",), rot.nota)
    for id_, texto in notas(dados, v).items():
        _trocar_texto(ctx, id_, ("",), texto)
    _trocar_texto(ctx, "fonte-rodape", (FONTE_RODAPE,), fonte_rodape(dados))
    _mostrar(ctx, "rodape-bm", bool(dados.get("benchmark")))
