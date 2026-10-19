"""Seção "Insumos do fósforo" do index.html (frases, aria-labels, notas, tabelas e o item do Método,
iguais ao que o script desenha na visão padrão: período inteiro, sem filtro de grupo) e a página
estática insumos/, com as mesmas frases e tabelas, mais as tabelas por ano e as maiores origens.

Cada função espelha uma do script do index.html (nome entre parênteses), com a mesma saída e as
contas na mesma ordem (somas em laço): o teste de navegador (tests/e2e/test_estatico_insumos.py)
compara o HTML do build com o que o script desenha, e as frases do script com as do Python em
vários períodos. Tudo sai do bloco "insumos" do dashboard.json; os coeficientes do custo de insumo
vêm de lá (config.py, via src/insumos.py), nunca escritos aqui.

Regras do CLAUDE.md em toda frase: a fonte dos números no fim; o custo de insumo é no porto, uma
aproximação técnica, não o custo de nenhuma empresa nem o preço ao produtor; o spread da rocha vai
com o preço do Brasil da base e com a ressalva de que não é ágio.

Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet).
"""

from __future__ import annotations

from . import boletins as B
from . import formato as F
from .contexto import REPOSITORIO, URL_BASE, Contexto, ErroEstatico, Pagina, esc
from .resumo import com_fonte_comex, comparado_a, lista_com_e, rotulo_ano
from .resumo_precos import NAO_E_AGIO, diferenca_em_texto, indice, mes_ano_antes, nome_na_frase
from .tabelas import em, tabela

PASTA = "insumos"
FONTE_PINK = "Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet)."
FONTES_PAGINA = ["Comex Stat/MDIC", "Banco Mundial (Pink Sheet)"]
PINK_SHEET = "https://www.worldbank.org/en/research/commodity-markets"
TITULO = "Enxofre e rocha fosfática: importação e preços | Graaos"
H1 = "Enxofre e rocha fosfática: importação e preços"
DESCRICAO = ("Importação de enxofre e rocha fosfática pelo Brasil, mês a mês: volume, preço CIF, a rocha contra a Pink Sheet"
             " e o custo de insumo do MAP no porto.")
MAX_TITULO, MAX_DESCRICAO = 60, 155
CANVAS = ["grafico-enxofre", "grafico-enxofre-t", "grafico-rocha", "grafico-rocha-t", "grafico-custo-map", "grafico-razao-map"]
FRASES = ["resumo-enxofre", "resumo-enxofre-t", "resumo-rocha", "resumo-rocha-t", "resumo-custo-map", "resumo-razao-map"]
NOTAS = ["nota-enxofre", "nota-rocha", "nota-custo-map", "metodo-insumos"]
TABELAS = ["tabela-enxofre", "tabela-rocha", "tabela-custo-map"]


# --- Auxiliares do script ---------------------------------------------------------------------
def fmt_coef(v) -> str:
    """(fmtCoef) Intl.NumberFormat("pt-BR", {maximumFractionDigits: 3}): 0.45 vira "0,45"."""
    return F.numero(v, 0, 3)


def no_mes(dados: dict, serie: list, periodo: str):
    """(noMesInsumos) valor de uma série do bloco "insumos" no mês; fora do bloco, None."""
    k = indice(dados["insumos"]["periodos"], periodo)
    return None if k < 0 else em(serie, k)


def pequena_insumo(dados: dict, prod: dict, periodo: str) -> bool:
    """(pequenaInsumo)"""
    return no_mes(dados, prod["amostra_pequena"], periodo) is True


def sem_preco_insumo(dados: dict, prod: dict, periodo: str, onde: str, falta: str) -> str:
    """(semPrecoInsumo) por que o mês não tem o preço do insumo."""
    nome, t, mes = nome_na_frase(prod["nome"]), no_mes(dados, prod["t"], periodo), F.rotulo_mes(periodo)
    if F.nulo(t):
        return f"Em {mes}, não há dado de importação de {nome}."
    if t == 0:
        return f"Em {mes}, não houve importação de {nome}."
    if pequena_insumo(dados, prod, periodo):
        return f"Em {mes}, a importação de {nome} foi de {F.toneladas(t)}, menos de {F.fmt0(prod['corte_amostra_t'])} t: amostra pequena, {onde}."
    return f"Em {mes}, não há {falta} para {nome}."


def _ate(dados: dict, indices: list[int]) -> str:
    return dados["mensal"]["periodos"][indices[-1]]


# --- Frases -----------------------------------------------------------------------------------
def frase_volume_insumo(dados: dict, chave: str, indices: list[int]) -> str:
    """(fraseVolumeInsumo) o último mês contra o mesmo mês do ano anterior e o acumulado do ano (só
    com todos os meses no bloco: None é mês fora do período ingerido, não zero)."""
    prod = dados["insumos"]["produtos"][chave]
    nome = nome_na_frase(prod["nome"])

    def t(periodo):
        return no_mes(dados, prod["t"], periodo)

    ate = _ate(dados, indices)
    ano, mes, antes = int(ate[:4]), int(ate[5:7]), mes_ano_antes(ate)
    if F.nulo(t(ate)):
        return com_fonte_comex(f"Em {F.rotulo_mes(ate)}, não há dado de importação de {nome}.")
    no_mes_ = comparado_a(F.variacao_pct(t(ate), t(antes)), F.rotulo_mes(antes))
    if t(ate) > 0:
        frase = f"Em {F.rotulo_mes(ate)}, o Brasil importou {F.toneladas(t(ate))} de {nome}{f', {no_mes_}' if no_mes_ else ''}."
    else:
        frase = f"Em {F.rotulo_mes(ate)}, o Brasil não importou {nome}."

    def acumulado(a):
        s = 0
        for m in range(1, mes + 1):
            v = t(f"{a}-{m:02d}")
            if F.nulo(v):
                return None
            s += v
        return s

    t_acum = acumulado(ano) if mes > 1 else None
    if not F.nulo(t_acum):
        no_acum = comparado_a(F.variacao_pct(t_acum, acumulado(ano - 1)), f"jan–{F.MESES[mes - 1]}/{ano - 1}")
        frase += f" No acumulado de jan–{F.MESES[mes - 1]}/{ano}, foram {F.toneladas(t_acum)}{f', {no_acum}' if no_acum else ''}."
    return com_fonte_comex(frase)


def frase_preco_enxofre(dados: dict, indices: list[int]) -> str:
    """(frasePrecoEnxofre) CIF, FOB e frete do último mês e o menor e o maior CIF do período."""
    prod = dados["insumos"]["produtos"]["enxofre"]
    nome = nome_na_frase(prod["nome"])
    p = dados["mensal"]["periodos"]

    def v(campo, periodo):
        return no_mes(dados, prod[campo], periodo)

    def com_preco(periodo):
        return not F.nulo(v("cif", periodo)) and not pequena_insumo(dados, prod, periodo)

    ate = _ate(dados, indices)
    antes = mes_ano_antes(ate)
    if com_preco(ate):
        dif = diferenca_em_texto(F.variacao_pct(v("cif", ate), v("cif", antes) if com_preco(antes) else None), F.rotulo_mes(antes))
        frase = (f"Em {F.rotulo_mes(ate)}, o {nome} importado custou {F.por_tonelada(v('cif', ate))} CIF{f' ({dif})' if dif else ''}, "
                 f"com {F.por_tonelada(v('fob', ate))} FOB e {F.por_tonelada(v('frete', ate))} de frete.")
    else:
        frase = sem_preco_insumo(dados, prod, ate, "ponto vazado no gráfico de preço", "preço")
    meses = [p[i] for i in indices if com_preco(p[i])]
    if len(meses) > 1:
        menor = maior = meses[0]
        for x in meses:
            if v("cif", x) < v("cif", menor):
                menor = x
            if v("cif", x) > v("cif", maior):
                maior = x
        frase += (f" No período, o CIF foi de {F.por_tonelada(v('cif', menor))} ({F.rotulo_mes(menor)}, o menor) a "
                  f"{F.por_tonelada(v('cif', maior))} ({F.rotulo_mes(maior)}, o maior).")
    return com_fonte_comex(frase)


def frase_rocha(dados: dict, indices: list[int]) -> str:
    """(fraseRocha) o último mês comparável do período, com o preço do Brasil da base do benchmark, o
    spread e quantos meses ficaram acima dele (pelo número arredondado)."""
    prod = dados["insumos"]["produtos"]["rocha"]
    ref = prod["benchmark"]
    nome = nome_na_frase(prod["nome"])
    p = dados["mensal"]["periodos"]

    def v(serie, i):
        return no_mes(dados, serie, p[i])

    def comparavel(i):
        return not pequena_insumo(dados, prod, p[i]) and not F.nulo(v(ref["spread_pct"], i))

    ate = indices[-1]

    def fora():
        return sem_preco_insumo(dados, prod, p[ate], "fora da comparação", "benchmark do Banco Mundial")

    meses = [i for i in indices if comparavel(i)]
    if not meses:
        return f"{fora()} Nenhum mês do período tem preço comparável com o benchmark. {FONTE_PINK}"
    i = meses[-1]
    na_origem = ref["comparacao"].startswith("FOB")
    brasil = f"{F.por_tonelada(v(prod['fob'] if na_origem else prod['cif'], i))} {'FOB' if na_origem else 'CIF'}"
    s, usd = v(ref["spread_pct"], i), v(ref["spread_usd_t"], i)
    sinal = F.sinal_de(s, F.fmt1, "+")
    relacao = f"{F.fmt1(abs(s))}% {'abaixo' if sinal == F.MENOS else 'acima'} do benchmark" if sinal else "praticamente igual ao benchmark"
    em_usd = "" if F.nulo(usd) else f" ({F.sinal_de(usd, F.fmt0, '+')}US$ {F.fmt0(abs(usd))}/t)"
    acima = len([x for x in meses if F.sinal_de(v(ref["spread_pct"], x), F.fmt1, "+") == "+"])
    quando = f"Em {F.rotulo_mes(p[i])}" if i == ate else f"{fora()} Em {F.rotulo_mes(p[i])}, o último mês comparável do período"
    return (f"{quando}, o Brasil importou {nome} a {F.por_tonelada(v(prod['fob'], i))} FOB e {F.por_tonelada(v(prod['cif'], i))} CIF; "
            f"o benchmark do Banco Mundial ({ref['serie']}), na base {ref['base']}, foi de {F.por_tonelada(v(ref['bm'], i))}. "
            f"Na base comparável ({ref['comparacao']}), o preço do Brasil, de {brasil}, ficou {relacao}{em_usd}. No período, ficou acima "
            f"do benchmark em {F.fmt0(acima)} de {F.fmt0(len(meses))} {'mês comparável' if len(meses) == 1 else 'meses comparáveis'}. "
            f"{NAO_E_AGIO} {FONTE_PINK}")


def custo_map_no_mes(dados: dict, campo: str, periodo: str):
    """(custoMapNoMes)"""
    return no_mes(dados, dados["insumos"]["custo_map"][campo], periodo)


def custo_usavel(dados: dict, periodo: str) -> bool:
    """(custoUsavel) os três preços no mês, fora da amostra pequena."""
    produtos = dados["insumos"]["produtos"]
    return (all(not F.nulo(custo_map_no_mes(dados, campo, periodo)) for campo in ("custo", "cif_map", "razao"))
            and all(not F.nulo(no_mes(dados, produtos[k]["cif"], periodo)) for k in ("enxofre", "rocha"))
            and custo_map_no_mes(dados, "amostra_pequena", periodo) is not True)


def sem_custo_map(dados: dict, periodo: str) -> str:
    """(semCustoMap)"""
    b = dados["insumos"]
    nomes = [nome_na_frase(b["produtos"][k]["nome"]) for k in ("enxofre", "rocha")]
    if custo_map_no_mes(dados, "amostra_pequena", periodo) is True:
        cortes = [F.fmt0(x) for x in (b["produtos"]["enxofre"]["corte_amostra_t"], b["produtos"]["rocha"]["corte_amostra_t"], b["custo_map"]["corte_amostra_map_t"])]
        return (f"Em {F.rotulo_mes(periodo)}, o custo de insumo fica fora da conta: amostra pequena (menos de {cortes[0]} t de {nomes[0]}, "
                f"{cortes[1]} t de {nomes[1]} ou {cortes[2]} t de MAP no mês; ponto vazado nos gráficos).")
    return f"Em {F.rotulo_mes(periodo)}, não há custo de insumo: falta o preço de {nomes[0]}, de {nomes[1]} ou de MAP no mês."


def quando_custo_map(dados: dict, m: str, ate: str) -> str:
    """(quandoCustoMap)"""
    return f"Em {F.rotulo_mes(m)}" if m == ate else f"{sem_custo_map(dados, ate)} Em {F.rotulo_mes(m)}, o último mês do período nos gráficos"


def _meses_custo(dados: dict, indices: list[int]) -> list[str]:
    p = dados["mensal"]["periodos"]
    return [p[i] for i in indices if custo_usavel(dados, p[i])]


def frase_custo_map(dados: dict, indices: list[int]) -> str:
    """(fraseCustoMap) o custo de insumo do último mês nos gráficos, com a conta, e o CIF do MAP."""
    b = dados["insumos"]
    c = b["custo_map"]
    ate = _ate(dados, indices)
    meses = _meses_custo(dados, indices)
    if not meses:
        return com_fonte_comex(f"{sem_custo_map(dados, ate)} Nenhum mês do período tem custo de insumo.")
    m = meses[-1]

    def parte(chave, coef):
        cif = no_mes(dados, b["produtos"][chave]["cif"], m)
        return f"{fmt_coef(coef)} t de {nome_na_frase(b['produtos'][chave]['nome'])} a {F.por_tonelada(cif)} CIF"

    return com_fonte_comex(
        f"{quando_custo_map(dados, m, ate)}, o custo de insumo por tonelada de MAP, no porto, foi de {F.por_tonelada(custo_map_no_mes(dados, 'custo', m))}: "
        f"{parte('enxofre', c['coef_enxofre'])} e {parte('rocha', c['coef_rocha'])}. O CIF do MAP importado no mesmo mês foi de "
        f"{F.por_tonelada(custo_map_no_mes(dados, 'cif_map', m))}. É uma aproximação técnica, não o custo de nenhuma empresa nem o preço ao produtor."
    )


def razoes_map(dados: dict, meses: list[str]) -> dict:
    """(razoesMap) razão em %, a média simples dos meses (na ordem do período) e o maior e o menor."""
    def r(x):
        return 100 * custo_map_no_mes(dados, "razao", x)

    s = 0
    maior = menor = meses[0] if meses else None
    for x in meses:
        s += r(x)
        if r(x) > r(maior):
            maior = x
        if r(x) < r(menor):
            menor = x
    return {"r": r, "media": s / len(meses) if meses else None, "maior": maior, "menor": menor}


def frase_razao_map(dados: dict, indices: list[int]) -> str:
    """(fraseRazaoMap)"""
    ate = _ate(dados, indices)
    meses = _meses_custo(dados, indices)
    if not meses:
        return com_fonte_comex(f"{sem_custo_map(dados, ate)} Nenhum mês do período tem a razão entre o custo de insumo e o CIF do MAP.")
    m = meses[-1]
    z = razoes_map(dados, meses)
    r = z["r"]
    frase = f"{quando_custo_map(dados, m, ate)}, o custo de insumo equivaleu a {F.pct(r(m))} do CIF do MAP, no porto."
    if len(meses) > 1:
        frase += (f" Na média dos {F.fmt0(len(meses))} meses do período nos gráficos, {F.pct(z['media'])}; o maior, {F.pct(r(z['maior']))}, "
                  f"em {F.rotulo_mes(z['maior'])}, e o menor, {F.pct(r(z['menor']))}, em {F.rotulo_mes(z['menor'])}.")
    return com_fonte_comex(f"{frase} É uma aproximação técnica, não o custo de nenhuma empresa nem o preço ao produtor.")


def frases(dados: dict, indices: list[int]) -> dict[str, str]:
    """id do <p class="resumo-grafico"> -> frase."""
    return {
        "resumo-enxofre": frase_preco_enxofre(dados, indices),
        "resumo-enxofre-t": frase_volume_insumo(dados, "enxofre", indices),
        "resumo-rocha": frase_rocha(dados, indices),
        "resumo-rocha-t": frase_volume_insumo(dados, "rocha", indices),
        "resumo-custo-map": frase_custo_map(dados, indices),
        "resumo-razao-map": frase_razao_map(dados, indices),
    }


# --- Notas, aria-labels e tabelas -------------------------------------------------------------
def _intervalo(dados: dict, indices: list[int]) -> tuple[str, str]:
    p = dados["mensal"]["periodos"]
    return F.rotulo_mes(p[indices[0]]), F.rotulo_mes(p[indices[-1]])


def _descricao(prod: dict) -> str:
    d = prod["descricao"]
    return d[:1].upper() + d[1:]


def notas(dados: dict, indices: list[int]) -> dict[str, str]:
    """(notasInsumos) notas dos cartões e o item do Método (as notas do bloco)."""
    b = dados["insumos"]
    c = b["custo_map"]
    de, ate = _intervalo(dados, indices)
    periodo = f"{de} a {ate}"
    enx, rocha = b["produtos"]["enxofre"], b["produtos"]["rocha"]
    ref = rocha["benchmark"]
    return {
        "nota-enxofre": (f"{_descricao(enx)} · US$ por tonelada e toneladas · {periodo} · meses com menos de {F.fmt0(enx['corte_amostra_t'])} t "
                         'aparecem como ponto vazado, fora das frases (na tabela, "pequena")'),
        "nota-rocha": (f"{_descricao(rocha)} · benchmark: {ref['serie']}, {ref['base']}, Banco Mundial · {periodo} · meses com menos de "
                       f'{F.fmt0(rocha["corte_amostra_t"])} t aparecem como ponto vazado, fora das frases e da comparação (na tabela, "pequena")'),
        "nota-custo-map": (f"Custo de insumo = CIF do enxofre × {fmt_coef(c['coef_enxofre'])} + CIF da rocha fosfática × {fmt_coef(c['coef_rocha'])}, "
                           f"em US$ por tonelada de MAP · CIF do MAP: NCM {', '.join(c['ncms_map'])} · {periodo} · o mês com amostra pequena de um dos "
                           "três aparece como ponto vazado, fora das frases e da média"),
        "metodo-insumos": f"Insumos do fósforo (enxofre e rocha fosfática importados): {' '.join(b['notas'])}",
    }


def rotulos(dados: dict, indices: list[int], fr: dict[str, str] | None = None) -> dict[str, str]:
    """(desenharEnxofre, desenharRocha e desenharCustoMap) aria-label de cada canvas."""
    fr = fr or frases(dados, indices)
    b = dados["insumos"]["produtos"]
    de, ate = _intervalo(dados, indices)
    intervalo = f"de {de} a {ate}"
    tabela_ = "A tabela abaixo traz os valores."
    return {
        "grafico-enxofre": f"{b['enxofre']['nome']}: preço implícito FOB e CIF em US$ por tonelada, {intervalo}. {tabela_} {fr['resumo-enxofre']}",
        "grafico-enxofre-t": f"{b['enxofre']['nome']}: toneladas importadas por mês, {intervalo}. {tabela_} {fr['resumo-enxofre-t']}",
        "grafico-rocha": (f"{b['rocha']['nome']}: preço FOB e CIF do Brasil e benchmark do Banco Mundial (Pink Sheet), em US$ por tonelada, "
                          f"{intervalo}. {tabela_} {fr['resumo-rocha']}"),
        "grafico-rocha-t": f"{b['rocha']['nome']}: toneladas importadas por mês, {intervalo}. {tabela_} {fr['resumo-rocha-t']}",
        "grafico-custo-map": (f"Custo de insumo por tonelada de MAP (enxofre e rocha fosfática, no porto) e CIF do MAP, em US$ por tonelada, "
                              f"{intervalo}. {tabela_} {fr['resumo-custo-map']}"),
        "grafico-razao-map": (f"Custo de insumo ÷ CIF do MAP, em porcentagem, {intervalo}, com a média dos meses do período tracejada. "
                              f"{tabela_} {fr['resumo-razao-map']}"),
    }


def _n(x, f=F.fmt0) -> str:
    """(n) nulo vira "–"."""
    return F.TRACO if F.nulo(x) else f(x)


def _n_sinal(x, f) -> str:
    """(n da tabela da rocha) com o sinal pelo número arredondado e o "-" do teclado."""
    return F.TRACO if F.nulo(x) else F.com_sinal(x, f).replace(F.MENOS, "-", 1)


def tabela_enxofre(dados: dict, indices: list[int]) -> str:
    """(desenharEnxofre)"""
    prod = dados["insumos"]["produtos"]["enxofre"]
    p = dados["mensal"]["periodos"]

    def v(campo, i):
        return no_mes(dados, prod[campo], p[i])

    colunas = [("Mês", False), ("Toneladas", True), ("FOB US$/t", True), ("CIF US$/t", True), ("Frete US$/t", True), ("Amostra", False)]
    return tabela(colunas, [[F.rotulo_mes(p[i]), _n(v("t", i)), _n(v("fob", i)), _n(v("cif", i)), _n(v("frete", i)),
                             "pequena" if pequena_insumo(dados, prod, p[i]) else ""] for i in indices])


def tabela_rocha(dados: dict, indices: list[int]) -> str:
    """(desenharRocha)"""
    prod = dados["insumos"]["produtos"]["rocha"]
    ref = prod["benchmark"]
    p = dados["mensal"]["periodos"]

    def v(serie, i):
        return no_mes(dados, serie, p[i])

    colunas = [("Mês", False), ("Toneladas", True), ("FOB Brasil US$/t", True), ("CIF Brasil US$/t", True), ("Banco Mundial US$/t", True),
               ("Spread US$/t", True), ("Spread %", True), ("Amostra", False)]
    return tabela(colunas, [[F.rotulo_mes(p[i]), _n_sinal(v(prod["t"], i), F.fmt0), _n_sinal(v(prod["fob"], i), F.fmt0), _n_sinal(v(prod["cif"], i), F.fmt0),
                             _n_sinal(v(ref["bm"], i), F.fmt1), _n_sinal(v(ref["spread_usd_t"], i), F.fmt0), _n_sinal(v(ref["spread_pct"], i), F.fmt1),
                             "pequena" if pequena_insumo(dados, prod, p[i]) else ""] for i in indices])


def tabela_custo_map(dados: dict, indices: list[int]) -> str:
    """(desenharCustoMap)"""
    b = dados["insumos"]
    p = dados["mensal"]["periodos"]
    colunas = [("Mês", False), (f"{b['produtos']['enxofre']['nome']} CIF US$/t", True), (f"{b['produtos']['rocha']['nome']} CIF US$/t", True),
               ("Custo de insumo US$/t de MAP", True), ("CIF do MAP US$/t", True), ("Custo ÷ CIF do MAP", True), ("Amostra", False)]
    linhas = []
    for i in indices:
        r = custo_map_no_mes(dados, "razao", p[i])
        linhas.append([F.rotulo_mes(p[i]), _n(no_mes(dados, b["produtos"]["enxofre"]["cif"], p[i])), _n(no_mes(dados, b["produtos"]["rocha"]["cif"], p[i])),
                       _n(custo_map_no_mes(dados, "custo", p[i])), _n(custo_map_no_mes(dados, "cif_map", p[i])), F.TRACO if F.nulo(r) else F.pct(100 * r),
                       "pequena" if custo_map_no_mes(dados, "amostra_pequena", p[i]) is True else ""])
    return tabela(colunas, linhas)


def tabelas(dados: dict, indices: list[int]) -> dict[str, str]:
    """id da caixa -> HTML da tabela."""
    return {"tabela-enxofre": tabela_enxofre(dados, indices), "tabela-rocha": tabela_rocha(dados, indices), "tabela-custo-map": tabela_custo_map(dados, indices)}


# --- Etapa do build ---------------------------------------------------------------------------
def gerar(ctx: Contexto) -> None:
    """Visão padrão do script (lerUrl sem hash): o período inteiro. Sem o bloco "insumos", a seção e o
    item do Método ficam ocultos, como o script os deixa, e não há página insumos/."""
    dados = ctx.dados
    if not dados.get("insumos"):
        ctx.definir_atributo("insumos", "class", "bloco oculto")
        ctx.definir_atributo("metodo-insumos", "class", "oculto")
        return
    indices = list(range(len(ctx.periodos)))
    try:
        fr, nt = frases(dados, indices), notas(dados, indices)
        rot, tab = rotulos(dados, indices, fr), tabelas(dados, indices)
        html_pagina = pagina(ctx, fr, nt, tab)
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise ErroEstatico(f"bloco insumos do dashboard.json incompleto: {e!r}") from e
    for id_, texto in {**fr, **nt}.items():
        ctx.preencher(id_, esc(texto))
    for id_, rotulo in rot.items():
        ctx.definir_atributo(id_, "aria-label", rotulo)
    for id_, html in tab.items():
        ctx.preencher(id_, html)
    ctx.escrever(f"{PASTA}/index.html", html_pagina)
    ctx.paginas.append(Pagina(f"{PASTA}/", ctx.atualizado))
    ctx.preencher("link-insumos-pagina", f' A <a href="{PASTA}/">página dos insumos</a> traz as mesmas tabelas, os totais por ano e as maiores origens.')


# --- Página insumos/ --------------------------------------------------------------------------
def por_ano(dados: dict, chave: str) -> list[dict]:
    """Toneladas, FOB e CIF médios (valor ÷ toneladas) de cada ano, e a variação das toneladas sobre os
    mesmos meses do ano anterior (só com todos esses meses no bloco). Ano com mês sem dado fica de fora."""
    b = dados["insumos"]
    prod = b["produtos"][chave]
    meses_de = {}
    for k, periodo in enumerate(b["periodos"]):
        meses_de.setdefault(int(periodo[:4]), []).append(k)

    def soma(serie, ks):
        s = 0
        for k in ks:
            s += serie[k]
        return s

    saida = []
    for ano in sorted(meses_de):
        ks = meses_de[ano]
        if any(F.nulo(prod["t"][k]) for k in ks):
            continue
        t = soma(prod["t"], ks)
        meses = [b["periodos"][k][5:] for k in ks]
        ant = [indice(b["periodos"], f"{ano - 1}-{m}") for m in meses]
        t_ant = soma(prod["t"], ant) if all(k >= 0 and not F.nulo(prod["t"][k]) for k in ant) else None
        saida.append({
            "ano": ano, "t": t, "var_t": F.variacao_pct(t, t_ant),
            "fob": soma(prod["fob_musd"], ks) * 1e6 / t if t > 0 else None,
            "cif": soma(prod["cif_musd"], ks) * 1e6 / t if t > 0 else None,
        })
    return saida


def tabela_por_ano(dados: dict, chave: str) -> str:
    linhas = [[rotulo_ano(dados, x["ano"]), F.fmt0(x["t"]), F.variacao(x["var_t"]), _n(x["fob"]), _n(x["cif"])]
              for x in reversed(por_ano(dados, chave))]
    return B._tabela([("Ano", False), ("Toneladas", True), ("Var. t (mesmos meses)", True), ("FOB US$/t", True), ("CIF US$/t", True)], linhas)


def _origens(dados: dict, chave: str) -> tuple[str, list]:
    """O ano do último mês dos dados e as maiores origens do insumo nele (bloco insumos.origens)."""
    ano = int(dados["insumos"]["periodos"][-1][:4])
    return rotulo_ano(dados, ano), (((dados["insumos"].get("origens") or {}).get(str(ano)) or {}).get(chave) or [])


def frase_origens(dados: dict, chave: str) -> str:
    rotulo, linhas = _origens(dados, chave)
    linhas = [r for r in linhas if r[1] != "Outros" and r[2]][:3]
    if not linhas:
        return ""
    nome = nome_na_frase(dados["insumos"]["produtos"][chave]["nome"])
    itens = [f"{r[1]} ({F.pct(r[3])}{' das toneladas' if k == 0 else ''})" for k, r in enumerate(linhas)]
    return com_fonte_comex(f"Maiores origens de {nome} em {rotulo}: {lista_com_e(itens)}.")


def tabela_origens(dados: dict, chave: str) -> str:
    _, linhas = _origens(dados, chave)
    linhas = [r for r in linhas if r[2]]
    if not linhas:
        return ""
    return B._tabela([("País", False), ("Toneladas", True), ("Share", True), ("Var. t (mesmos meses)", True)],
                     [[r[1], F.fmt0(r[2]), F.pct(r[3]), F.variacao(r[4])] for r in linhas])


def _barra() -> str:
    return (
        '<a class="pular" href="#conteudo">Pular para o conteúdo</a>\n'
        '<div class="fundo-pontos" aria-hidden="true"></div>\n'
        '<header class="barra-topo">\n'
        '  <a class="marca" href="../"><strong>Graaos</strong><span>Fertilizantes</span></a>\n'
        '  <nav class="nav-pilula" aria-label="Navegação do site">\n'
        '    <a href="../">Painel</a>\n'
        f'    <a href="../{PASTA}/" aria-current="page">Insumos</a>\n'
        f'    <a href="../{B.PASTA}/">Boletins</a>\n'
        '    <a class="nav-alertas" href="../#lista-espera">Receber alertas</a>\n'
        "  </nav>\n"
        "</header>"
    )


def _p(classe: str, texto: str) -> str:
    return f'<p class="{classe}">{B._frase(texto)}</p>\n' if texto else ""


def _detalhes(resumo: str, html: str) -> str:
    return f'<details class="tabela"><summary>{esc(resumo)}</summary><div class="rolagem">{html}</div></details>\n'


def pagina(ctx: Contexto, fr: dict[str, str], nt: dict[str, str], tab: dict[str, str]) -> str:
    """insumos/index.html: as frases e tabelas da seção (visão padrão), as tabelas por ano, as maiores
    origens e o método, sem JavaScript. Links relativos (../) para a home e o arquivo dos boletins."""
    dados = ctx.dados
    url = URL_BASE + f"{PASTA}/"
    if len(TITULO) > MAX_TITULO or len(DESCRICAO) > MAX_DESCRICAO:
        raise ErroEstatico("insumos/: title ou description longos demais")
    p = dados["insumos"]["periodos"]
    inicio, fim = F.rotulo_mes(p[0]), F.rotulo_mes(p[-1])
    trilha = [("Graaos · Fertilizantes", URL_BASE), ("Insumos do fósforo", url)]
    pagina_ld = {
        "@type": "WebPage", "@id": url + "#pagina", "url": url, "name": TITULO, "description": DESCRICAO, "inLanguage": "pt-BR",
        "isPartOf": {"@id": URL_BASE + "#website"}, "publisher": {"@id": URL_BASE + "#organization"}, "breadcrumb": {"@id": url + "#trilha"},
        "about": [{"@type": "Thing", "name": dados["insumos"]["produtos"][k]["nome"]} for k in ("enxofre", "rocha")],
        "temporalCoverage": f"{p[0]}/{p[-1]}", "license": B.LICENCA_DADOS, "isBasedOn": [B.COMEX_STAT, PINK_SHEET],
        "primaryImageOfPage": {"@type": "ImageObject", "url": URL_BASE + "preview.png"},
    }
    if ctx.atualizado:
        pagina_ld["dateModified"] = ctx.atualizado
    cabeca = B._cabeca(ctx, titulo=TITULO, descricao=DESCRICAO, url=url, prefixo="../", og_tipo="website",
                       jsonld=B._jsonld([pagina_ld, B._trilha_jsonld(url, trilha)]), icones=B._links_da_home(ctx.html))
    produtos = dados["insumos"]["produtos"]
    nomes = {k: produtos[k]["nome"] for k in ("enxofre", "rocha")}

    def cartao(id_, titulo, corpo):
        return f'<section class="cartao grade" aria-labelledby="{id_}">\n<div>\n<h2 class="titulo-cartao" id="{id_}">{esc(titulo)}</h2>\n{corpo}</div>\n</section>'

    ressalva_rocha = ('<p class="ressalva"><strong>Referência de outro lugar, não ágio.</strong> A Pink Sheet do Banco Mundial cota a rocha'
                      " fosfática no porto de embarque do Norte da África. A diferença para o preço do Brasil mistura origem, teor de fósforo"
                      " da rocha, prazo de contrato e defasagem entre o negócio e o desembarque.</p>\n")
    ressalva_custo = ('<p class="ressalva"><strong>Aproximação técnica, no porto.</strong> Quanto custariam, ao preço CIF de importação, o'
                      " enxofre e a rocha fosfática de uma tonelada de MAP, pelos coeficientes de consumo do método. Não é o custo de"
                      " nenhuma empresa nem o preço ao produtor: ficam de fora o nitrogênio do MAP, a energia, a conversão, os impostos, o"
                      " frete interno e o insumo de origem nacional.</p>\n")
    origens = []
    for k in ("enxofre", "rocha"):
        t = tabela_origens(dados, k)
        if t:
            origens.append(f'<div><h3 class="subtitulo">{esc(nomes[k])}</h3>{t}</div>')
    rotulo_origens = _origens(dados, "enxofre")[0]
    metodo = "".join(f"<li>{esc(x)}</li>" for x in dados["insumos"]["notas"])
    blocos = [
        cartao("t-enxofre", f"{nomes['enxofre']}: preço e volume importados",
               _p("nota", nt["nota-enxofre"]) + _p("resumo-grafico", fr["resumo-enxofre"]) + _p("resumo-grafico", fr["resumo-enxofre-t"])
               + '<h3 class="subtitulo">Por ano</h3>\n' + tabela_por_ano(dados, "enxofre") + "\n"
               + _detalhes("Ver tabela mês a mês", tab["tabela-enxofre"])),
        cartao("t-rocha", f"{nomes['rocha']}: Brasil x mercado internacional",
               _p("nota", nt["nota-rocha"]) + _p("resumo-grafico", fr["resumo-rocha"]) + ressalva_rocha + _p("resumo-grafico", fr["resumo-rocha-t"])
               + '<h3 class="subtitulo">Por ano</h3>\n' + tabela_por_ano(dados, "rocha") + "\n"
               + _detalhes("Ver tabela mês a mês", tab["tabela-rocha"])),
        cartao("t-origens", f"Maiores origens · {rotulo_origens}",
               '<p class="nota">Share nas toneladas do ano e variação sobre os mesmos meses do ano anterior</p>\n'
               + "".join(_p("resumo-grafico", frase_origens(dados, k)) for k in ("enxofre", "rocha"))
               + f'<div class="tabelas-boletim">{"".join(origens)}</div>\n') if origens else "",
        cartao("t-custo-map", "Custo de insumo do MAP: enxofre e rocha x CIF do MAP",
               _p("nota", nt["nota-custo-map"]) + _p("resumo-grafico", fr["resumo-custo-map"]) + ressalva_custo
               + _p("resumo-grafico", fr["resumo-razao-map"]) + _detalhes("Ver tabela mês a mês", tab["tabela-custo-map"])),
        cartao("t-metodo", "Método", f'<ul class="lista-metodo">{metodo}</ul>\n'
               f'<p class="nota">Dados abertos: <a href="{REPOSITORIO}/blob/main/data/processed/insumos_mensal.csv">insumos_mensal.csv</a> e '
               f'<a href="{REPOSITORIO}/blob/main/data/processed/custo_insumo_map_mensal.csv">custo_insumo_map_mensal.csv</a> (CC BY 4.0).</p>\n'),
    ]
    corpo = "\n".join(x for x in (
        _barra(),
        '<div class="pagina">\n<main id="conteudo">',
        B._trilha([("Graaos · Fertilizantes", "../"), ("Insumos do fósforo", None)]),
        '<section class="bloco" aria-labelledby="titulo-pagina">',
        '<header class="bloco-cabecalho">'
        f'<p class="kicker">Insumos do fósforo · {esc(inicio)} a {esc(fim)}</p>'
        f'<h1 class="titulo-bloco" id="titulo-pagina">{esc(H1)}</h1>'
        '<p class="bloco-lead">Enxofre e rocha fosfática importados pelo Brasil, as matérias-primas do ácido fosfórico do MAP e do DAP:'
        " preço e volume de cada um, a rocha contra a Pink Sheet do Banco Mundial e uma aproximação do custo de insumo por tonelada de"
        ' MAP, no porto. Os gráficos estão no <a href="../#insumos">painel</a>; o mês a mês das importações de fertilizantes, nos'
        f' <a href="../{B.PASTA}/">boletins</a>.</p>'
        "</header>",
        *blocos,
        "</section>",
        "</main>",
        B._rodape(ctx, FONTES_PAGINA),
        "</div>",
    ) if x)
    return B._documento(cabeca, corpo)
