"""Contas do script do dashboard sobre o dashboard.json, em Python e com o mesmo resultado
(nome da função do script entre parênteses). Usadas no card Resumo da home e nas páginas dos
boletins."""

from __future__ import annotations

from . import formato as F


def indices_entre(dados: dict, de: str, ate: str) -> list[int]:
    """(indicesEntre)"""
    p = dados["mensal"]["periodos"]
    return list(range(p.index(de), p.index(ate) + 1))


def soma(serie: list, indices: list[int]) -> float:
    """(soma) nulos contam como zero."""
    s = 0
    for i in indices:
        s += serie[i] if serie[i] is not None else 0
    return s


def metricas(dados: dict, grupo: str, indices: list[int]) -> dict:
    """(metricas) toneladas, valores em US$ e preços do grupo nos meses dados."""
    m = dados["mensal"][grupo]
    t = soma(m["t"], indices)
    fob = soma(m["fob_musd"], indices) * 1e6
    cif = soma(m["cif_musd"], indices) * 1e6
    frete = soma(m["frete_musd"], indices) * 1e6
    return {
        "t": t, "fob": fob, "cif": cif, "frete": frete,
        "preco_fob": fob / t if t > 0 else None,
        "preco_cif": cif / t if t > 0 else None,
        "frete_t": frete / t if t > 0 else None,
        "frete_cif": 100 * frete / cif if cif > 0 else None,
    }


def meses_do_ano(dados: dict, ano: int, ate_mes: int) -> list[int]:
    """(mesesDoAno) índices dos meses de `ano` até `ate_mes`."""
    return [i for i, p in enumerate(dados["mensal"]["periodos"]) if int(p[:4]) == ano and int(p[5:7]) <= ate_mes]


def kpis(dados: dict, grupo: str, ate: str) -> dict:
    """(desenharKpis) títulos e cartões do card Resumo, já formatados como o script os mostra.

    Devolve {"titulo", "nota", "titulo_mes", "titulo_acumulado", "mes": [...], "acumulado": [...]},
    com cada cartão como {"rotulo", "valor", "delta"} (textos prontos, sem HTML).
    """
    ano, mes = int(ate[:4]), int(ate[5:7])
    anterior = f"{ano - 1}-{mes:02d}"
    p = dados["mensal"]["periodos"]
    m_atual = metricas(dados, grupo, [p.index(ate)])
    m_anterior = metricas(dados, grupo, [p.index(anterior)]) if anterior in p else None
    a_atual = metricas(dados, grupo, meses_do_ano(dados, ano, mes))
    idx_ant = meses_do_ano(dados, ano - 1, mes)
    a_anterior = metricas(dados, grupo, idx_ant) if len(idx_ant) == mes else None
    acum = f"jan/{ano}" if mes == 1 else f"jan–{F.MESES[mes - 1]}/{ano}"
    acum_ant = f"jan/{ano - 1}" if mes == 1 else f"jan–{F.MESES[mes - 1]}/{ano - 1}"

    def linha(m: dict, ant: dict | None) -> list[dict]:
        frete_delta = m["frete_cif"] - ant["frete_cif"] if ant and not F.nulo(m["frete_cif"]) and not F.nulo(ant["frete_cif"]) else None
        return [
            {"rotulo": "Toneladas", "valor": F.toneladas(m["t"]), "delta": F.variacao(F.variacao_pct(m["t"], ant and ant["t"]))},
            {"rotulo": "Valor FOB", "valor": F.dolares(m["fob"]), "delta": F.variacao(F.variacao_pct(m["fob"], ant and ant["fob"]))},
            {"rotulo": "Preço FOB", "valor": F.por_tonelada(m["preco_fob"]), "delta": F.variacao(F.variacao_pct(m["preco_fob"], ant and ant["preco_fob"]))},
            {"rotulo": "Frete no CIF", "valor": F.pct(m["frete_cif"]), "delta": F.variacao(frete_delta, " p.p.")},
        ]

    return {
        "titulo": f"{F.NOMES[grupo]} · {F.rotulo_mes_longo(ate)}",
        "nota": "Variações sobre o mesmo período do ano anterior",
        "titulo_mes": f"Mês: {F.rotulo_mes(ate)} x {F.rotulo_mes(anterior)}",
        "titulo_acumulado": f"Acumulado: {acum} x {acum_ant}",
        "mes": linha(m_atual, m_anterior),
        "acumulado": linha(a_atual, a_anterior),
    }
