"""Frases-modelo das páginas dos boletins (boletim/AAAA-MM/ e boletim/).

Preenchidas pelo programa com os valores do pacote de fatos do boletim (src.boletim.montar_fatos):
os mesmos números, já formatados em pt-BR, que a IA cita por marcadores no boletim do mês. Texto
neutro e factual, sem juízo nem causa: a direção ("alta", "queda") vem do próprio pacote
(chaves _sentido), e a relação de troca sai sempre "no porto", sem ser o preço ao produtor.
"""

from __future__ import annotations

from ..boletim import Fatos, mes_curto

PRODUTOS_TROCA = {"kcl": "KCl", "ureia": "ureia", "map": "MAP"}
NOMES_GRUPOS = {"n": "nitrogenados", "p": "fosfatados", "k": "potássicos", "npk": "compostos (NPK)"}
MAX_DESCRICAO = 155


def valor(f: Fatos, chave: str) -> str | None:
    return f[chave]["valor"] if chave in f else None


def variacao(f: Fatos, chave: str, base: str | None = None, artigo: bool = True) -> str | None:
    """"uma queda de 27,9% sobre setembro de 2025", "alta de 5,3%" ou "sem variação"."""
    if chave not in f:
        return None
    sentido = valor(f, f"{chave}_sentido")
    texto = "sem variação" if sentido == "estabilidade" else f"{'uma ' if artigo else ''}{sentido} de {valor(f, chave)}"
    return f"{texto} sobre {base}" if base else texto


def _juntar(partes: list[str]) -> str:
    """"A; B; e C" (as partes já levam vírgulas por dentro)."""
    return partes[0] if len(partes) == 1 else "; ".join(partes[:-1]) + "; e " + partes[-1]


def mes_anterior(periodo: str) -> str:
    return f"{int(periodo[:4]) - 1}{periodo[4:]}"


def frase_mes(f: Fatos) -> str:
    mes, t = valor(f, "mes_referencia"), valor(f, "t_total_mes")
    if t is None:
        return f"Em {mes}, o Comex Stat não registra importação de fertilizantes."
    var = variacao(f, "var_t_total_mes", valor(f, "mes_ano_anterior"))
    return f"Em {mes}, o Brasil importou {t} de fertilizantes" + (f", {var}" if var else "") + "."


def frase_acumulado(f: Fatos) -> str | None:
    """Do acumulado do ano; em janeiro, o acumulado é o próprio mês e a frase fica de fora."""
    t = valor(f, "t_total_ytd")
    if f.periodo.endswith("-01") or t is None:
        return None
    var = variacao(f, "var_t_total_ytd", f"o mesmo período de {valor(f, 'ano_anterior')}")
    return f"No acumulado de {valor(f, 'periodo_ytd')}, foram {t}" + (f", {var}" if var else "") + "."


def lead(f: Fatos) -> str:
    return " ".join(x for x in (frase_mes(f), frase_acumulado(f)) if x)


def frase_precos(f: Fatos) -> str | None:
    cif = valor(f, "preco_cif_total_mes")
    if cif is None:
        return None
    var = variacao(f, "var_preco_cif_total_mes", valor(f, "mes_ano_anterior"))
    frase = f"O preço médio CIF do mês foi de {cif}" + (f", {var}" if var else "")
    resto = [x for x in (
        f"o FOB, de {valor(f, 'preco_fob_total_mes')}" if "preco_fob_total_mes" in f else None,
        f"o frete médio, de {valor(f, 'frete_total_mes')}" if "frete_total_mes" in f else None,
    ) if x]
    if resto:
        frase += "; " + ", e ".join(resto)
    return frase + "."


def frase_grupos(f: Fatos, ordem: list[str]) -> str | None:
    """Toneladas de cada grupo no mês (`ordem`: chaves n, p, k, npk, do maior para o menor)."""
    partes, com_variacao = [], False
    for k in ordem:
        t = valor(f, f"t_{k}_mes")
        if t is None:
            continue
        var = variacao(f, f"var_t_{k}_mes", artigo=False)
        com_variacao |= var is not None
        partes.append(f"{NOMES_GRUPOS[k]}, {t}" + (f" ({var})" if var else ""))
    if not partes:
        return None
    frase = f"Por grupo, em {valor(f, 'mes_referencia')}: " + "; ".join(partes) + "."
    return frase + (f" Variações sobre {valor(f, 'mes_ano_anterior')}." if com_variacao else "")


def periodo_anual(f: Fatos) -> str:
    """O período dos blocos anuais quando eles terminam no mês: "em 2025", "de janeiro a setembro de 2026"."""
    m = int(f.periodo[5:7])
    if m == 12:
        return f"em {valor(f, 'ano_referencia')}"
    return f"{'em' if m == 1 else 'de'} {valor(f, 'periodo_ytd')}"


def frase_origens(f: Fatos) -> str | None:
    """Maior origem, maior URF e maior rota do acumulado do ano (só quando o ano termina no mês)."""
    lider = valor(f, "lider_total_ano")
    if lider is None:
        return None
    frase = f"{lider} foi a principal origem {periodo_anual(f)}, com {valor(f, 'share_lider_total_ano')} das toneladas"
    if "porto_lider_ano" in f:
        frase += f", e {valor(f, 'porto_lider_ano')} foi a URF (porto) que mais recebeu fertilizantes, com {valor(f, 'share_porto_lider_ano')}"
    frase += "."
    if "rota_1_ano" in f:
        frete = f" e frete médio de {valor(f, 'frete_rota_1_ano')}" if "frete_rota_1_ano" in f else ""
        frase += f" A maior rota foi {valor(f, 'rota_1_ano')}, com {valor(f, 't_rota_1_ano')}{frete}."
    return frase


def frase_troca(f: Fatos) -> str | None:
    itens = [(nome, valor(f, f"troca_{p}_ultimo")) for p, nome in PRODUTOS_TROCA.items() if f"troca_{p}_ultimo" in f]
    if not itens:
        return None
    partes = [f"1 t de {nome} equivalia no porto a {v}" if i == 0 else f"1 t de {nome}, a {v}" for i, (nome, v) in enumerate(itens)]
    return f"Em {valor(f, 'mes_referencia')}, {_juntar(partes)}. É a relação de troca no porto, não o preço ao produtor."


def delta_troca(f: Fatos, prod: str) -> str:
    """Linha de baixo do cartão do produto: distância da média histórica, sacas e CIF."""
    sacas_cif = f"{valor(f, f'sacas_{prod}_ultimo')} · CIF {valor(f, f'cif_{prod}_ultimo')}"
    if _media_de_um_mes(f):
        return sacas_cif
    media, posicao = valor(f, f"troca_{prod}_media"), valor(f, f"desvio_troca_{prod}_posicao")
    distancia = f"{posicao} ({media})" if posicao.startswith("em linha") else f"{valor(f, f'desvio_troca_{prod}')} {posicao} ({media})"
    return f"{distancia} · {sacas_cif}"


def _media_de_um_mes(f: Fatos) -> bool:
    """No primeiro mês da série, a "média histórica" é o próprio mês: fica de fora."""
    inicio, _, fim = (valor(f, "periodo_media_troca") or "").partition(" a ")
    return inicio == fim


def nota_troca(f: Fatos) -> str | None:
    soja = valor(f, "soja_fob_ultimo")
    if soja is None:
        return None
    var = variacao(f, "var_soja_fob_ano", valor(f, "mes_ano_anterior"), artigo=False)
    media = "" if _media_de_um_mes(f) else f" Média histórica: média simples dos meses de {valor(f, 'periodo_media_troca')}."
    return f"Soja em grão exportada (FOB): {soja}" + (f", {var}" if var else "") + "." + media


def resumo_curto(f: Fatos) -> str:
    """Uma linha para o arquivo: "3,11 milhões de t, queda de 27,9% sobre set/2025"."""
    t = valor(f, "t_total_mes")
    if t is None:
        return "sem importação registrada"
    var = variacao(f, "var_t_total_mes", mes_curto(mes_anterior(f.periodo)), artigo=False)
    return t + (f", {var}" if var else "")


def descricao(f: Fatos, tem_origens: bool) -> str:
    """Meta description (até 155 caracteres): a frase do mês e o que mais a página traz."""
    sufixos = ["Preços, origens, portos e relação de troca com a soja." if tem_origens else "Preços, frete e relação de troca com a soja.",
               "Preços e relação de troca com a soja.", "Preços e troca com a soja.", ""]
    for base in (frase_mes(f), _frase_mes_curta(f)):
        for sufixo in sufixos:
            texto = f"{base} {sufixo}".strip()
            if len(texto) <= MAX_DESCRICAO:
                return texto
    return _frase_mes_curta(f)[:MAX_DESCRICAO]


def _frase_mes_curta(f: Fatos) -> str:
    t = valor(f, "t_total_mes")
    if t is None:
        return frase_mes(f)
    var = variacao(f, "var_t_total_mes", mes_curto(mes_anterior(f.periodo)), artigo=False)
    return f"Em {valor(f, 'mes_referencia_curto')}, o Brasil importou {t} de fertilizantes" + (f" ({var})" if var else "") + "."
