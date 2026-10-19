"""index.html: o card "Resumo" já preenchido, os destaques, a frase de resumo dos gráficos de
volumes, origens, HHI, portos e rotas (com o subtítulo de cada um) e o aria-label deles, iguais ao
que o script desenha na visão padrão (todos os grupos, período inteiro). O script continua
redesenhando por cima.

Cada função espelha uma do script do index.html (nome entre parênteses), com a mesma saída: o
teste de navegador (tests/e2e/test_estatico_resumo.py) compara o HTML do build com o que o
script desenha. Somas de float em laço, na ordem do script (o sum() do Python 3.12+ compensa o
arredondamento e pode dar outro último dígito).
"""

from __future__ import annotations

import math

from . import dados as D
from . import formato as F
from .contexto import Contexto, esc

LIMIAR_HHI = 1800  # (LIMIAR_HHI) diretrizes de fusões dos EUA (2023)
FERTILIZANTES_DE = {
    "TOTAL": "fertilizantes",
    "N": "fertilizantes nitrogenados",
    "P": "fertilizantes fosfatados",
    "K": "fertilizantes potássicos",
    "NPK": "fertilizantes compostos (NPK)",
}
PRODUTOS_TROCA = {"K": ["kcl"], "N": ["ureia"], "P": ["map"]}  # (PRODUTOS_TROCA)
TROCA_TODOS = ["kcl", "ureia", "map"]


# --- Auxiliares do script ---------------------------------------------------------------------
def lista_com_e(itens: list[str]) -> str:
    """(listaComE) "A", "A e B", "A, B e C"."""
    return "".join(itens) if len(itens) < 2 else f"{', '.join(itens[:-1])} e {itens[-1]}"


def n_meses(dados: dict, ano: int) -> int:
    """(nMeses)"""
    anos = dados["anual"]["anos"]
    return dados["anual"]["n_meses"][anos.index(ano)] if ano in anos else 0


def ano_parcial(dados: dict, ano: int) -> bool:
    """(anoParcial)"""
    return 0 < n_meses(dados, ano) < 12


def rotulo_ano(dados: dict, ano: int) -> str:
    """(rotuloAno) "2026 (jan–set)" num ano parcial."""
    return f"{ano} (jan–{F.MESES[n_meses(dados, ano) - 1]})" if ano_parcial(dados, ano) else str(ano)


def comparado_a(v, rotulo: str) -> str | None:
    """(comparadoA) "27,9% a menos que em set/2025"; sem base de comparação, None."""
    if F.nulo(v) or not math.isfinite(v):
        return None
    sinal = F.sinal_de(v, F.fmt1, "+")
    if not sinal:
        return f"praticamente o mesmo que em {rotulo}"
    return f"{F.fmt1(abs(v))}% a {'menos' if sinal == F.MENOS else 'mais'} que em {rotulo}"


def _linhas_ranking(dados: dict, tipo: str, g: str, ano: int) -> list:
    bloco = dados["origens"] if tipo == "origens" else dados["urfs"]
    return (bloco["dados"].get(str(ano)) or {}).get(g) or []


# --- Frases -----------------------------------------------------------------------------------
def texto_destaques(dados: dict, g: str, ate: str) -> str:
    """(textoDestaques) as três maiores origens do ano e a relação de troca do mês (no porto)."""
    ano = int(ate[:4])
    origens = [r for r in _linhas_ranking(dados, "origens", g, ano) if r[1] != "Outros"][:3]
    partes = []
    if origens:
        itens = [f"{r[1]} ({F.pct(r[3])}{' das toneladas' if i == 0 else ''})" for i, r in enumerate(origens)]
        partes.append(f"Principais origens em {rotulo_ano(dados, ano)}: {lista_com_e(itens)}.")
    tr = dados.get("troca")
    j = tr["periodos"].index(ate) if tr and ate in tr["periodos"] else -1
    chaves = [] if g == "NPK" else PRODUTOS_TROCA.get(g, TROCA_TODOS)
    trocas = [] if j < 0 else [x for x in (tr["produtos"].get(k) for k in chaves) if x and not F.nulo(x["razao"][j])]
    if trocas:
        valores = "; ".join(f"{x['nome']} {F.fmt2(x['razao'][j])}" for x in trocas)
        partes.append(f"Relação de troca no porto em {F.rotulo_mes(ate)}, em t de soja por t de fertilizante: {valores}. Não é o preço ao produtor.")
    if partes:
        partes.append("Fonte: Comex Stat/MDIC.")
    return " ".join(partes)


def frase_toneladas(dados: dict, g: str, ate: str) -> str:
    """(fraseToneladas) o mês contra o mesmo mês do ano anterior e o acumulado do ano."""
    p = dados["mensal"]["periodos"]
    ano, mes = int(ate[:4]), int(ate[5:7])
    anterior = f"{ano - 1}-{mes:02d}"
    t = D.metricas(dados, g, [p.index(ate)])["t"]
    t_anterior = D.metricas(dados, g, [p.index(anterior)])["t"] if anterior in p else None
    nome = FERTILIZANTES_DE[g]
    no_mes = comparado_a(F.variacao_pct(t, t_anterior), F.rotulo_mes(anterior))
    if t > 0:
        frase = f"Em {F.rotulo_mes(ate)}, o Brasil importou {F.toneladas(t)} de {nome}{', ' + no_mes if no_mes else ''}."
    else:
        frase = f"Em {F.rotulo_mes(ate)}, o Brasil não importou {nome}."
    if mes > 1:
        idx_ant = D.meses_do_ano(dados, ano - 1, mes)
        t_acum = D.metricas(dados, g, D.meses_do_ano(dados, ano, mes))["t"]
        base = D.metricas(dados, g, idx_ant)["t"] if len(idx_ant) == mes else None
        no_acum = comparado_a(F.variacao_pct(t_acum, base), f"jan–{F.MESES[mes - 1]}/{ano - 1}")
        frase += f" No acumulado de jan–{F.MESES[mes - 1]}/{ano}, foram {F.toneladas(t_acum)}{', ' + no_acum if no_acum else ''}."
    return frase


def frase_ranking(dados: dict, tipo: str, g: str, ano: int) -> str:
    """(fraseRanking) origens ou portos: o maior do ano e os dois seguintes, com o share."""
    linhas = [r for r in _linhas_ranking(dados, tipo, g, ano) if r[1] != "Outros"][:3]
    nome = FERTILIZANTES_DE[g]
    if not linhas:
        return f"Sem importações de {nome} em {rotulo_ano(dados, ano)}."

    def nome_de(r):
        return r[1] if tipo == "origens" else F.nome_curto_urf(r[1])

    maior, demais = linhas[0], linhas[1:]
    titulo = "Maior origem" if tipo == "origens" else "Maior porto de entrada (URF)"
    frase = f"{titulo} dos {nome} em {rotulo_ano(dados, ano)}: {nome_de(maior)}, com {F.pct(maior[3])} das toneladas"
    if demais:
        soma = 0
        for r in linhas:
            soma += r[3]
        if tipo == "origens":
            juntos = "juntas, as duas" if len(demais) == 1 else "juntas, as três"
        else:
            juntos = "juntos, os dois" if len(demais) == 1 else "juntos, os três"
        frase += f", à frente de {lista_com_e([f'{nome_de(r)} ({F.pct(r[3])})' for r in demais])}; {juntos} somam {F.pct(soma)}"
    frase += "."
    anos = dados["anual"]["anos"]
    n_origens = dados["anual"][g]["n_origens"][anos.index(ano)] if ano in anos else None
    if tipo == "origens" and not F.nulo(n_origens):
        frase += f" Ao todo, as importações vieram de {F.fmt0(n_origens)} {'país' if n_origens == 1 else 'países'}."
    return frase


def frase_hhi(dados: dict, g: str, ano: int) -> str:
    """(fraseHhi) o ano contra o limiar de 1.800; com "Todos", cada grupo, como no gráfico."""
    anos = dados["anual"]["anos"]
    if ano not in anos:
        return ""
    i = anos.index(ano)
    limiar = F.fmt0(LIMIAR_HHI)

    def posicao(h):
        return "acima" if h > LIMIAR_HHI else "abaixo" if h < LIMIAR_HHI else "no limiar"

    relacao = {"acima": f"acima de {limiar}", "abaixo": f"abaixo de {limiar}", "no limiar": f"em {limiar}"}
    if g != "TOTAL":
        a = dados["anual"][g]
        h = a["hhi"][i]
        if F.nulo(h):
            return ""
        lider = "" if F.nulo(a["lider"][i]) else f"; a maior origem, {a['lider'][i]}, teve {F.pct(a['lider_share_pct'][i])} das toneladas"
        return f"Em {rotulo_ano(dados, ano)}, o HHI dos {FERTILIZANTES_DE[g]} ficou em {F.fmt0(h)}, {relacao[posicao(h)]}, o limiar de mercado altamente concentrado{lider}."
    valores = [(x, dados["anual"][x]["hhi"][i]) for x in F.GRUPOS if not F.nulo(dados["anual"][x]["hhi"][i])]
    blocos = [(pos, [v for v in valores if posicao(v[1]) == pos]) for pos in ("acima", "no limiar", "abaixo")]
    blocos = [(pos, lista) for pos, lista in blocos if lista]
    if not blocos:
        return ""

    def lista(itens):
        return lista_com_e([f"{x} ({F.fmt0(h)})" for x, h in itens])

    (pos, primeiros), resto = blocos[0], blocos[1:]
    demais = "".join(f"; o de {lista(itens)}, {p}" for p, itens in resto)
    return f"Em {rotulo_ano(dados, ano)}, o HHI de {lista(primeiros)} ficou {relacao[pos]}, o limiar de mercado altamente concentrado{demais}."


def frase_rotas(dados: dict, bloco: dict | None, g: str, ano: int) -> str:
    """(fraseRotas) a maior rota do ano e o frete médio das rotas com volume relevante."""
    nome = FERTILIZANTES_DE[g]
    if not bloco or not bloco["fluxos"]:
        return f"Sem importações de {nome} em {rotulo_ano(dados, ano)}."
    corte = bloco.get("corte_t") if bloco.get("corte_t") is not None else dados["rotas"]["corte_t"]
    if not bloco["rotas"]:
        return f"Em {rotulo_ano(dados, ano)}, nenhuma rota de {nome} teve pelo menos {F.fmt0(corte)} t."
    pais, _, urf, t, share, frete = bloco["rotas"][0][:6]
    origem = pais if pais is not None else F.TRACO
    porto = F.nome_curto_urf(urf) if urf else F.TRACO
    frete_txt = "" if F.nulo(frete) else f" e frete de {F.por_tonelada(frete)}"
    frase = f"Maior rota dos {nome} em {rotulo_ano(dados, ano)}: {origem} → {porto}, com {F.toneladas(t)} ({F.pct(share)} do total){frete_txt}."
    n = bloco["n_relevantes"]
    quem = "A rota" if n == 1 else f"As {F.fmt0(n)} rotas"
    medio = "" if F.nulo(bloco["frete_relevantes"]) else f", com frete médio de {F.por_tonelada(bloco['frete_relevantes'])}"
    frase += f" {quem} com pelo menos {F.fmt0(corte)} t {'soma' if n == 1 else 'somam'} {F.pct(bloco['share_relevantes_pct'])} das toneladas{medio}."
    return frase


# --- Subtítulos e aria-labels dos gráficos (os mesmos textos do script) -----------------------
def nota_toneladas(dados: dict, g: str, de: str, ate: str) -> str:
    """(desenharToneladas, #nota-toneladas)"""
    return f"{F.NOMES[g]} · {F.rotulo_mes(de)} a {F.rotulo_mes(ate)}"


def rotulo_toneladas(dados: dict, g: str, de: str, ate: str) -> str:
    """(desenharToneladas, aria-label do canvas)"""
    return f"Toneladas importadas por mês, {F.NOMES[g]}, de {F.rotulo_mes(de)} a {F.rotulo_mes(ate)}. A tabela abaixo traz os valores. {frase_toneladas(dados, g, ate)}"


def nota_ranking(dados: dict, tipo: str, g: str, ano: int) -> str:
    """(desenharRanking, #nota-origens e #nota-portos)"""
    linhas = _linhas_ranking(dados, tipo, g, ano)
    top = len(linhas) - (1 if any(r[1] == "Outros" for r in linhas) else 0)
    return f"{F.NOMES[g]} · {rotulo_ano(dados, ano)} · share das toneladas, top {top} e outros"


def rotulo_ranking(dados: dict, tipo: str, g: str, ano: int) -> str:
    """(desenharRanking, aria-label do canvas)"""
    titulo = "Share por país de origem" if tipo == "origens" else "Ranking de portos"
    return f"{titulo} em {rotulo_ano(dados, ano)}, {F.NOMES[g]}. A tabela abaixo traz os valores. {frase_ranking(dados, tipo, g, ano)}"


def _anos_hhi(dados: dict, de: str, ate: str) -> list[int]:
    return [a for a in dados["anual"]["anos"] if int(de[:4]) <= a <= int(ate[:4])]


def nota_hhi(dados: dict, g: str, de: str, ate: str) -> str:
    """(desenharHhi, #nota-hhi)"""
    parcial = next((a for a in _anos_hhi(dados, de, ate) if ano_parcial(dados, a)), None)
    return f"{F.NOMES[g]} · por país de origem, em toneladas{f' · {rotulo_ano(dados, parcial)}' if parcial else ''}"


def rotulo_hhi(dados: dict, g: str, de: str, ate: str) -> str:
    """(desenharHhi, aria-label do canvas)"""
    anos = _anos_hhi(dados, de, ate)
    resumo = frase_hhi(dados, g, int(ate[:4]))
    return f"HHI por ano, {F.NOMES[g]}, de {anos[0]} a {anos[-1]}. A tabela abaixo traz os valores.{' ' + resumo if resumo else ''}"


def nota_rotas(dados: dict, bloco: dict | None, g: str, ano: int) -> str:
    """(desenharRotas, #nota-rotas)"""
    n_origens = sum(1 for o in bloco["origens"] if o[1] != "Outros") if bloco else 0
    n_urfs = sum(1 for u in bloco["urfs"] if u[1] != "Outros") if bloco else 0
    return f"{F.NOMES[g]} · {rotulo_ano(dados, ano)} · espessura = toneladas · {n_origens} maiores origens e {n_urfs} maiores URFs; o resto em Outros"


def rotulo_sankey(dados: dict, bloco: dict | None, g: str, ano: int) -> str:
    """(desenharSankey, aria-label do diagrama)"""
    if not bloco or not bloco["fluxos"]:
        return "Sem importações neste ano e grupo."

    def nome_o(i):
        return bloco["origens"][i][1]

    def nome_u(i):
        return "Outros" if bloco["urfs"][i][1] == "Outros" else F.nome_curto_urf(bloco["urfs"][i][1])

    fitas = [(o, u, t) for o, u, t, *_ in bloco["fluxos"]]
    sem_outros = [f for f in fitas if nome_o(f[0]) != "Outros" and bloco["urfs"][f[1]][1] != "Outros"]
    maiores = sorted(sem_outros, key=lambda f: -f[2])[:3]  # sort estável, como o do script
    lista = "; ".join(f"{nome_o(o)} para {nome_u(u)}, {F.toneladas(t)}" for o, u, t in maiores)
    return (f"Fluxo das importações, {F.NOMES[g]}, {rotulo_ano(dados, ano)}: das maiores origens para as maiores URFs. "
            f"Maiores rotas: {lista}. A tabela abaixo traz o frete por rota. {frase_rotas(dados, bloco, g, ano)}")


# --- Card Resumo ------------------------------------------------------------------------------
def kpis_html(cartoes: list[dict]) -> str:
    """Os cartões de desenharKpis: <div class="kpi"> com rótulo, valor (span.numero) e variação."""
    return "".join(
        f'<div class="kpi"><div class="rotulo">{esc(c["rotulo"])}</div>'
        f'<div class="valor"><span class="numero">{esc(c["valor"])}</span></div>'
        f'<div class="delta">{esc(c["delta"])}</div></div>'
        for c in cartoes
    )


def gerar(ctx: Contexto) -> None:
    """Visão padrão do script (lerUrl sem hash): todos os grupos, do primeiro ao último mês."""
    dados = ctx.dados
    g = "TOTAL"
    de, ate = ctx.periodos[0], ctx.periodos[-1]
    ano = int(ate[:4])

    k = D.kpis(dados, g, ate)
    ctx.preencher("titulo-kpis", esc(k["titulo"]))
    ctx.preencher("nota-kpis", esc(k["nota"]))
    ctx.preencher("titulo-mes", esc(k["titulo_mes"]))
    ctx.preencher("titulo-acumulado", esc(k["titulo_acumulado"]))
    ctx.preencher("kpis-mes", kpis_html(k["mes"]))
    ctx.preencher("kpis-acumulado", kpis_html(k["acumulado"]))
    ctx.preencher("destaques-kpis", esc(texto_destaques(dados, g, ate)))

    ctx.preencher("nota-toneladas", esc(nota_toneladas(dados, g, de, ate)))
    ctx.preencher("resumo-toneladas", esc(frase_toneladas(dados, g, ate)))
    ctx.definir_atributo("grafico-toneladas", "aria-label", rotulo_toneladas(dados, g, de, ate))

    for tipo in ("origens", "portos"):
        ctx.preencher(f"nota-{tipo}", esc(nota_ranking(dados, tipo, g, ano)))
        ctx.preencher(f"resumo-{tipo}", esc(frase_ranking(dados, tipo, g, ano)))
        ctx.definir_atributo(f"grafico-{tipo}", "aria-label", rotulo_ranking(dados, tipo, g, ano))

    ctx.preencher("nota-hhi", esc(nota_hhi(dados, g, de, ate)))
    ctx.preencher("resumo-hhi", esc(frase_hhi(dados, g, ano)))
    ctx.definir_atributo("grafico-hhi", "aria-label", rotulo_hhi(dados, g, de, ate))

    if dados.get("rotas"):  # sem o bloco, o script esconde a seção
        bloco = (dados["rotas"]["dados"].get(str(ano)) or {}).get(g)
        ctx.preencher("nota-rotas", esc(nota_rotas(dados, bloco, g, ano)))
        ctx.preencher("resumo-rotas", esc(frase_rotas(dados, bloco, g, ano)))
        ctx.definir_atributo("sankey", "aria-label", rotulo_sankey(dados, bloco, g, ano))
