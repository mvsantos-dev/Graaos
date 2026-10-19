"""Sinais de preço e de volume (src/sinais.py): séries sintéticas por regra e os dados versionados."""

from __future__ import annotations

import copy
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src import config, sinais

RAIZ = Path(__file__).resolve().parent.parent
DASHBOARD = RAIZ / "data" / "processed" / "dashboard.json"
N = 48
NUTRIENTES = ("ureia", "sulfato_amonio", "nitrato_amonio", "map", "dap", "tsp", "kcl")
PINK = ("kcl", "ureia", "map", "dap", "tsp")
TROCA = ("kcl", "ureia", "map")
PRECO = {"media_12m", "variacao_3m", "recorde", "internacional", "troca_p90"}


def per(n: int) -> list[str]:
    return [f"{2015 + i // 12}-{i % 12 + 1:02d}" for i in range(n)]


def lista(valor, mudancas: dict | None = None, n: int = N) -> list:
    saida = [valor] * n
    for i, v in (mudancas or {}).items():
        saida[i] = v
    return saida


def dash(n=N, cif=None, t=None, pink=None, razao=None, soja_t=None, pequena=None, bases=None, insumos=True) -> dict:
    """dashboard.json mínimo, com os blocos que o src/sinais lê: tudo estável (nenhum sinal) por padrão."""
    cif, t, pink, razao, pequena, bases = cif or {}, t or {}, pink or {}, razao or {}, pequena or {}, bases or {}
    p = per(n)

    def serie(d, k, v):
        return list(d.get(k, [v] * n))

    dados = {
        "meta": {"periodo": {"inicio": p[0], "fim": p[-1]}},
        "mensal": {"periodos": p, "NPK": {"t": serie(t, "npk", 100_000), "preco_cif": serie(cif, "npk", 300.0)}},
        "nutrientes": {
            "periodos": p,
            "produtos": {
                k: {"nome": k, "t": serie(t, k, 100_000), "cif": serie(cif, k, 300.0), "amostra_pequena": serie(pequena, k, False)}
                for k in NUTRIENTES
            },
        },
        "benchmark": {
            "periodos": p,
            "produtos": {
                k: {"serie": "DAP" if k in ("map", "dap") else k.upper(), "proxy": k == "map", "bases": bases.get(k, [{"desde": p[0], "base": "FOB"}]), "bm": serie(pink, k, 300.0)}
                for k in PINK
            },
        },
        "troca": {"periodos": p, "soja_t": list(soja_t or [1_000_000] * n), "produtos": {k: {"razao": serie(razao, k, 1.0)} for k in TROCA}},
    }
    if insumos:
        dados["insumos"] = {
            "periodos": p,
            "produtos": {
                "enxofre": {"nome": "Enxofre", "t": serie(t, "enxofre", 150_000), "cif": serie(cif, "enxofre", 150.0), "amostra_pequena": serie(pequena, "enxofre", False)},
                "rocha": {
                    "nome": "Rocha fosfática", "t": serie(t, "rocha", 150_000), "cif": serie(cif, "rocha", 100.0), "amostra_pequena": serie(pequena, "rocha", False),
                    "benchmark": {"serie": "Phosphate rock", "base": "FOB Norte da África", "comparacao": "FOB×FOB", "bm": serie(pink, "rocha", 100.0)},
                },
            },
        }
    return dados


def achar(dados, produto=None, tipo=None, mes=None, limites=None) -> list[dict]:
    return [
        s for s in sinais.calcular(dados, limites)
        if (produto is None or s["produto"] == produto) and (tipo is None or s["tipo"] == tipo) and (mes is None or s["mes"] == mes)
    ]


def um(dados, produto, tipo, mes, limites=None) -> dict:
    achados = achar(dados, produto, tipo, mes, limites)
    assert len(achados) == 1, achados
    return achados[0]


# --- Base ------------------------------------------------------------------------------------


def test_series_estaveis_nao_disparam_nada():
    doc = sinais.gerar(dash())
    assert doc["sinais"] == []
    assert list(doc["produtos"]) == list(sinais.PRODUTOS)
    sinais.validar(doc)


def test_limites_vem_do_config_e_voltam_no_arquivo():
    lim = sinais.limites_config()
    assert lim["volume_min_t"] == config.SINAIS_VOLUME_MIN_T == 20_000
    assert lim["volume_min_t_produto"] == config.SINAIS_VOLUME_MIN_T_PRODUTO
    assert set(lim["volume_min_t_produto"]) == {"enxofre", "rocha"}
    assert (lim["media_12m"]["limite_pct"], lim["variacao_3m"]["limite_pct"]) == (20.0, 15.0)
    assert (lim["internacional"]["limite_pct"], lim["internacional"]["meses"]) == (10.0, 2)
    assert (lim["troca_p90"]["percentil"], lim["ritmo_importacao"]["limite_pct"]) == (90.0, 25.0)
    for regra in ("media_12m", "variacao_3m", "internacional", "ritmo_importacao"):
        assert lim[regra]["forte_pct"] > lim[regra]["limite_pct"]
    assert sinais.gerar(dash())["limites"] == lim


# --- media_12m e variacao_3m -----------------------------------------------------------------


def test_alta_contra_a_media_de_12_meses_e_em_3_meses():
    d = dash(n=25, cif={"ureia": lista(300.0, {24: 372.0}, 25)})
    s = um(d, "ureia", "media_12m", "2017-01")
    assert (s["direcao"], s["nivel"], s["valor"], s["metrica"], s["unidade"]) == ("alta", "atencao", 372.0, "cif_usd_t", "US$/t")
    assert s["comparacao"] == {"base": "media_12m", "valor": 300.0, "variacao_pct": 24.0, "janela_meses": 12, "meses_validos": 12}
    assert s["frase"] == "Ureia: CIF 24% acima da média de 12 meses"
    assert (s["id"], s["ancora"]) == ("2017-01/ureia/media_12m", "#secao-bm")
    v = um(d, "ureia", "variacao_3m", "2017-01")
    assert v["comparacao"]["mes"] == "2016-10" and v["frase"] == "Ureia: CIF subiu 24% em 3 meses"
    # 24 meses de histórico ainda não bastam para recorde; nada mais dispara
    assert {x["tipo"] for x in achar(d)} == {"media_12m", "variacao_3m"}


def test_queda_forte():
    d = dash(n=25, cif={"sulfato_amonio": lista(300.0, {24: 165.0}, 25)})
    m = um(d, "sulfato_amonio", "media_12m", "2017-01")
    v = um(d, "sulfato_amonio", "variacao_3m", "2017-01")
    assert (m["direcao"], m["nivel"], v["direcao"], v["nivel"]) == ("queda", "forte", "queda", "forte")
    assert m["frase"] == "Sulfato de amônio: CIF 45% abaixo da média de 12 meses"
    assert v["frase"] == "Sulfato de amônio: CIF caiu 45% em 3 meses"
    assert m["ancora"] == "#secao-nutrientes"


@pytest.mark.parametrize(
    ("alta_pct", "nivel"),
    [(19.4, None), (19.6, "atencao"), (25.0, "atencao"), (39.4, "atencao"), (39.6, "forte"), (60.0, "forte")],
)
def test_nivel_da_media_segue_o_numero_da_frase(alta_pct, nivel):
    d = dash(n=25, cif={"kcl": lista(300.0, {24: 300.0 * (1 + alta_pct / 100)}, 25)})
    achados = achar(d, "kcl", "media_12m", "2017-01")
    assert [s["nivel"] for s in achados] == ([nivel] if nivel else [])
    if nivel == "forte" and alta_pct < 40:
        assert achados[0]["frase"] == "KCl: CIF 40% acima da média de 12 meses"  # nunca "40%" como atenção


@pytest.mark.parametrize(("var", "nivel"), [(14.4, None), (15.0, "atencao"), (-29.0, "atencao"), (-30.0, "forte")])
def test_nivel_da_variacao_em_3_meses(var, nivel):
    d = dash(n=16, cif={"tsp": lista(300.0, {15: 300.0 * (1 + var / 100)}, 16)})
    assert [s["nivel"] for s in achar(d, "tsp", "variacao_3m")] == ([nivel] if nivel else [])


def test_npk_vem_do_bloco_mensal():
    d = dash(n=25, cif={"npk": lista(300.0, {24: 400.0}, 25)})
    s = um(d, "npk", "media_12m", "2017-01")
    assert s["frase"] == "NPK: CIF 33% acima da média de 12 meses" and s["ancora"] == "#precos"


# --- Proteção contra ruído ---------------------------------------------------------------------


def test_volume_baixo_no_mes_nao_calcula_preco():
    d = dash(n=25, cif={"ureia": lista(300.0, {24: 600.0}, 25)}, t={"ureia": lista(100_000, {24: 15_000}, 25)})
    tipos = {s["tipo"] for s in achar(d, "ureia", mes="2017-01")}
    assert not tipos & PRECO
    assert tipos == {"ritmo_importacao"}  # o volume em si é um sinal
    # no limite exato, o mês vale
    d = dash(n=25, cif={"ureia": lista(300.0, {24: 600.0}, 25)}, t={"ureia": lista(100_000, {24: 20_000}, 25)})
    assert {"media_12m", "variacao_3m"} <= {s["tipo"] for s in achar(d, "ureia", mes="2017-01")}


def test_amostra_pequena_e_preco_ausente_ficam_fora():
    d = dash(n=25, cif={"map": lista(300.0, {24: 600.0}, 25)}, pequena={"map": lista(False, {24: True}, 25)})
    assert not {s["tipo"] for s in achar(d, "map", mes="2017-01")} & PRECO
    d = dash(n=25, cif={"map": lista(300.0, {24: None}, 25)})
    assert achar(d, "map") == []


def test_volume_baixo_na_janela_sai_da_media():
    # 3 meses da janela com pouca carga e preço fora da curva: ficam fora, a média é a dos outros 9
    cif = lista(300.0, {12: 1000.0, 13: 1000.0, 14: 1000.0, 24: 372.0}, 25)
    t = lista(100_000, {12: 10_000, 13: 10_000, 14: 10_000}, 25)
    s = um(dash(n=25, cif={"ureia": cif}, t={"ureia": t}), "ureia", "media_12m", "2017-01")
    assert s["direcao"] == "alta" and s["comparacao"]["valor"] == 300.0 and s["comparacao"]["meses_validos"] == 9
    # com 4 meses fora, sobram 8 (< SINAIS_MEDIA_MIN_VALIDOS): sem sinal
    cif[15], t[15] = 1000.0, 10_000
    assert achar(dash(n=25, cif={"ureia": cif}, t={"ureia": t}), "ureia", "media_12m", "2017-01") == []


def test_variacao_em_3_meses_exige_o_mes_de_referencia_valido():
    d = dash(n=25, cif={"ureia": lista(300.0, {24: 372.0}, 25)}, t={"ureia": lista(100_000, {21: 5_000}, 25)})
    assert achar(d, "ureia", "variacao_3m", "2017-01") == []
    assert len(achar(d, "ureia", "media_12m", "2017-01")) == 1


def test_enxofre_e_rocha_tem_volume_minimo_proprio():
    cif = lista(150.0, {24: 300.0}, 25)
    d = dash(n=25, cif={"enxofre": cif}, t={"enxofre": lista(150_000, {24: 30_000}, 25)})
    assert config.SINAIS_VOLUME_MIN_T < 30_000 < config.SINAIS_VOLUME_MIN_T_PRODUTO["enxofre"]
    assert not {s["tipo"] for s in achar(d, "enxofre")} & PRECO
    lim = copy.deepcopy(sinais.limites_config())
    lim["volume_min_t_produto"]["enxofre"] = 20_000
    assert um(d, "enxofre", "media_12m", "2017-01", lim)["nivel"] == "forte"
    d = dash(n=25, cif={"enxofre": cif}, t={"enxofre": lista(150_000, {24: 45_000}, 25)})
    s = um(d, "enxofre", "media_12m", "2017-01")
    assert s["frase"] == "Enxofre: CIF 100% acima da média de 12 meses" and s["ancora"] == "#grafico-enxofre"
    assert sinais.gerar(d)["produtos"]["enxofre"]["volume_min_t"] == config.SINAIS_VOLUME_MIN_T_PRODUTO["enxofre"]


def test_sem_bloco_insumos_enxofre_e_rocha_ficam_de_fora():
    d = dash(n=25, cif={"ureia": lista(300.0, {24: 372.0}, 25)}, insumos=False)
    doc = sinais.gerar(d)
    assert "enxofre" not in doc["produtos"] and "rocha" not in doc["produtos"]
    assert {s["produto"] for s in doc["sinais"]} == {"ureia"}
    sinais.validar(doc)


# --- Recorde ---------------------------------------------------------------------------------


def _ciclo(n: int) -> list[float]:
    return [300.0 + i % 5 for i in range(n)]  # entre 300 e 304


def test_recorde_maximo_e_minimo():
    cif = _ciclo(40) + [320.0, 305.0, 299.0, 299.0]
    d = dash(n=44, cif={"kcl": cif})
    rec = achar(d, "kcl", "recorde")
    assert [(s["mes"], s["direcao"], s["nivel"]) for s in rec] == [("2018-05", "alta", "forte"), ("2018-07", "queda", "atencao")]
    alta, queda = rec
    assert alta["comparacao"]["mes"] == "2015-05" and alta["comparacao"]["valor"] == 304.0  # o primeiro mês que chegou a 304
    assert alta["comparacao"]["desde"] == "2015-01" and alta["comparacao"]["meses_validos"] == 40
    assert alta["frase"] == "KCl: CIF de US$ 320/t, o maior da série desde jan/2015"
    assert queda["frase"] == "KCl: CIF de US$ 299/t, o menor da série desde jan/2015"
    # empate com o recorde (2018-08 = 299) não é recorde novo
    assert "2018-08" not in [s["mes"] for s in rec]


def test_recorde_por_pouco_e_atencao():
    d = dash(n=41, cif={"kcl": _ciclo(40) + [310.0]})
    s = um(d, "kcl", "recorde", "2018-05")
    assert s["nivel"] == "atencao" and 0 < s["comparacao"]["variacao_pct"] < config.SINAIS_RECORDE_FORTE_PCT


def test_recorde_exige_historico_minimo():
    d = dash(n=31, cif={"kcl": _ciclo(30) + [400.0]})
    assert achar(d, "kcl", "recorde") == []
    assert len(achar(d, "kcl", "media_12m")) == 1


def test_recorde_ignora_meses_com_pouco_volume():
    cif = _ciclo(40) + [320.0, 2000.0]
    cif[10] = 1000.0
    t = lista(100_000, {10: 5_000, 41: 5_000}, 42)
    rec = achar(dash(n=42, cif={"kcl": cif}, t={"kcl": t}), "kcl", "recorde")
    assert [(s["mes"], s["comparacao"]["valor"], s["comparacao"]["meses_validos"]) for s in rec] == [("2018-05", 304.0, 39)]


# --- Internacional na frente -----------------------------------------------------------------


def _pink_sobe(fim: float, n: int = 30) -> list[float]:
    return lista(300.0, {n - 2: 320.0, n - 1: fim}, n)


@pytest.mark.parametrize(
    ("cif_fim", "frase_brasil"),
    [(309.0, "subiu 3%"), (321.0, "subiu 7%"), (300.0, "ficou estável"), (285.0, "caiu 5%")],
)
def test_internacional_brasil_nao_acompanhou(cif_fim, frase_brasil):
    d = dash(n=30, pink={"ureia": _pink_sobe(345.0)}, cif={"ureia": lista(300.0, {29: cif_fim}, 30)})
    s = um(d, "ureia", "internacional", "2017-06")
    assert (s["direcao"], s["nivel"], s["valor"], s["metrica"]) == ("alta", "atencao", 345.0, "pink_usd_t")
    c = s["comparacao"]
    assert (c["base"], c["mes"], c["valor"], c["variacao_pct"], c["janela_meses"]) == ("pink_2_meses_antes", "2017-04", 300.0, 15.0, 2)
    assert (c["brasil_anterior"], c["brasil_valor"], c["proxy"]) == (300.0, cif_fim, False)
    assert s["frase"] == f"Ureia: Pink Sheet subiu 15% em 2 meses; CIF do Brasil {frase_brasil}"


@pytest.mark.parametrize("cif_fim", [324.0, 345.0, 360.0])
def test_internacional_brasil_acompanhou(cif_fim):
    # o Brasil andou no mesmo sentido pelo menos a metade (8% ≥ 15% × 0,5)
    d = dash(n=30, pink={"ureia": _pink_sobe(345.0)}, cif={"ureia": lista(300.0, {29: cif_fim}, 30)})
    assert achar(d, "ureia", "internacional") == []


def test_internacional_queda_forte_proxy_e_movimento_pequeno():
    d = dash(n=30, pink={"map": lista(300.0, {28: 280.0, 29: 225.0}, 30), "kcl": lista(300.0, {29: 327.0}, 30)})
    s = um(d, "map", "internacional", "2017-06")
    assert (s["direcao"], s["nivel"]) == ("queda", "forte")
    assert s["comparacao"]["pink_serie"] == "DAP" and s["comparacao"]["proxy"] is True
    assert s["frase"] == "MAP: DAP na Pink Sheet caiu 25% em 2 meses; CIF do Brasil ficou estável"
    assert achar(d, "kcl", "internacional") == []  # 9% em 2 meses: abaixo do limite


def test_internacional_ignora_troca_de_base_e_brasil_sem_volume():
    p = per(30)
    for desde in (p[28], p[29]):
        bases = {"kcl": [{"desde": p[0], "base": "FOB Vancouver"}, {"desde": desde, "base": "CFR Brasil"}]}
        assert achar(dash(n=30, pink={"kcl": _pink_sobe(345.0)}, bases=bases), "kcl", "internacional") == []
    bases = {"kcl": [{"desde": p[0], "base": "FOB Vancouver"}, {"desde": p[27], "base": "CFR Brasil"}]}
    assert len(achar(dash(n=30, pink={"kcl": _pink_sobe(345.0)}, bases=bases), "kcl", "internacional")) == 1
    t = {"kcl": lista(100_000, {27: 5_000}, 30)}
    assert achar(dash(n=30, pink={"kcl": _pink_sobe(345.0)}, t=t), "kcl", "internacional") == []


def test_internacional_da_rocha_vem_do_bloco_insumos():
    d = dash(n=30, pink={"rocha": lista(100.0, {29: 120.0}, 30)})
    s = um(d, "rocha", "internacional", "2017-06")
    assert (s["nivel"], s["ancora"], s["comparacao"]["pink_serie"]) == ("forte", "#grafico-rocha", "Phosphate rock")
    assert s["frase"] == "Rocha fosfática: Pink Sheet subiu 20% em 2 meses; CIF do Brasil ficou estável"
    # sem série na Pink Sheet: sulfato de amônio, NPK e enxofre nunca têm esse sinal
    assert {x["produto"] for x in achar(d, tipo="internacional")} == {"rocha"}


# --- Troca no porto ----------------------------------------------------------------------------


def _troca(fim: float, n: int = 41) -> list[float]:
    return [1.19 - 0.01 * k for k in range(n - 1)] + [fim]  # histórico em queda: nenhum mês anterior dispara


@pytest.mark.parametrize(("fim", "nivel"), [(1.10, None), (1.152, None), (1.16, "atencao"), (1.18, "atencao"), (1.20, "forte")])
def test_troca_acima_do_percentil_90(fim, nivel):
    d = dash(n=41, razao={"kcl": _troca(fim)})
    achados = achar(d, "kcl", "troca_p90")
    assert [(s["mes"], s["nivel"]) for s in achados] == ([("2018-05", nivel)] if nivel else [])
    if nivel:
        s = achados[0]
        assert s["comparacao"]["percentil"] == 90.0 and s["comparacao"]["meses_validos"] == 40
        assert s["comparacao"]["valor"] == pytest.approx(1.151)
        assert (s["ancora"], s["unidade"], s["direcao"]) == ("#troca", "t de soja por t", "alta")
        assert re.fullmatch(r"KCl: troca no porto de 1,\d\d t de soja por t, acima do percentil 90 da série \(1,15 t\)", s["frase"])
        assert "R$" not in s["frase"]


def test_troca_exige_historico_volume_e_soja():
    assert achar(dash(n=30, razao={"kcl": _troca(1.5, 30)}), "kcl", "troca_p90") == []
    assert achar(dash(n=41, razao={"kcl": _troca(1.5)}, t={"kcl": lista(100_000, {40: 9_000}, 41)}), "kcl", "troca_p90") == []
    assert achar(dash(n=41, razao={"kcl": _troca(1.5)}, soja_t=lista(1_000_000, {40: 1_000}, 41)), "kcl", "troca_p90") == []
    assert {s["produto"] for s in achar(dash(n=41, razao={k: _troca(1.5) for k in TROCA}), tipo="troca_p90")} == set(TROCA)


# --- Ritmo de importação -----------------------------------------------------------------------


def test_ritmo_de_importacao():
    t = lista(100_000, {12: 130_000, 13: 40_000, 14: 0, 15: None, 16: 30}, 26)
    d = dash(n=26, t={"ureia": t, "kcl": lista(100_000, {0: 10_000}, 26)})
    r = {s["mes"]: s for s in achar(d, "ureia", "ritmo_importacao")}
    # 2016-04 (null: mês sem dado) não é "sem importação", nem como mês atual nem como base (2017-04)
    assert [(m, s["direcao"], s["nivel"]) for m, s in r.items()] == [
        ("2016-01", "alta", "atencao"), ("2016-02", "queda", "forte"), ("2016-03", "queda", "forte"),
        ("2016-05", "queda", "forte"), ("2017-02", "alta", "forte"),
    ]
    assert r["2016-01"]["comparacao"] == {"base": "mesmo_mes_ano_anterior", "mes": "2015-01", "valor": 100_000, "variacao_pct": 30.0}
    assert (r["2016-01"]["metrica"], r["2016-01"]["unidade"], r["2016-01"]["valor"]) == ("t", "t", 130_000)
    assert r["2016-01"]["frase"] == "Ureia: 130 mil t importadas, 30% acima de jan/2015"
    assert r["2016-02"]["frase"] == "Ureia: 40 mil t importadas, 60% abaixo de fev/2015"
    assert r["2016-03"]["frase"] == "Ureia: sem importação no mês, contra 100 mil t em mar/2015"
    assert r["2016-05"]["frase"] == "Ureia: só 30 t importadas, contra 100 mil t em mai/2015"
    assert "2017-01" not in r  # 100 mil contra 130 mil: −23%
    # base sem o volume mínimo: sem comparação
    assert achar(d, "kcl", "ritmo_importacao") == []


def test_insumos_sem_o_ultimo_mes_ingerido_nao_disparam():
    # data/raw_insumos atrasado: o bloco "insumos" deixa o mês vazio (null), não zero
    vazio = {"enxofre": lista(150_000, {25: None}, 26), "rocha": lista(150_000, {25: None}, 26)}
    d = dash(n=26, t=vazio, cif={"enxofre": lista(150.0, {25: None}, 26), "rocha": lista(100.0, {25: None}, 26)})
    assert achar(d, mes="2017-02") == []
    # zero de verdade (mês ingerido sem importação) continua sendo sinal
    d = dash(n=26, t={"enxofre": lista(150_000, {25: 0}, 26)}, cif={"enxofre": lista(150.0, {25: None}, 26)})
    assert [s["frase"] for s in achar(d, mes="2017-02")] == ["Enxofre: sem importação no mês, contra 150 mil t em fev/2016"]


# --- Sem olhar o futuro, ordem, formato e determinismo -------------------------------------------


def _aleatorio(n: int = 84, semente: int = 7) -> dict:
    rng = random.Random(semente)

    def passeio(inicio, sigma, saltos=0.05):
        v, saida = inicio, []
        for _ in range(n):
            v *= 1 + rng.gauss(0, sigma) + (rng.choice((-0.3, 0.3)) if rng.random() < saltos else 0)
            v = max(v, inicio * 0.2)
            saida.append(round(v, 6))
        return saida

    def volumes(media):
        return [0 if rng.random() < 0.03 else int(media * rng.lognormvariate(0, 0.45)) for _ in range(n)]

    produtos = [*NUTRIENTES, "npk", "enxofre", "rocha"]
    return dash(
        n=n,
        cif={k: passeio(300.0, 0.06) for k in produtos},
        t={k: volumes(90_000) for k in produtos},
        pink={k: passeio(300.0, 0.08) for k in [*PINK, "rocha"]},
        razao={k: passeio(1.0, 0.07) for k in TROCA},
        soja_t=volumes(3_000_000),
    )


def _cortar(dados, n: int, k: int):
    """O mesmo dashboard só até o mês k (toda lista do tamanho da série vira os k+1 primeiros)."""
    if isinstance(dados, dict):
        return {c: _cortar(v, n, k) for c, v in dados.items()}
    if isinstance(dados, list):
        return [_cortar(v, n, k) for v in (dados[: k + 1] if len(dados) == n else dados)]
    return dados


def test_dados_aleatorios_cobrem_todas_as_regras_e_niveis():
    doc = sinais.gerar(_aleatorio())
    assert {(s["tipo"], s["nivel"]) for s in doc["sinais"]} == {(t, n) for t in sinais.TIPOS for n in sinais.NIVEIS}
    sinais.validar(doc)


@pytest.mark.parametrize("k", [40, 55, 70, 83])
def test_nenhum_sinal_olha_o_futuro(k):
    dados = _aleatorio()
    completo = sinais.calcular(dados)
    ate = per(84)[k]
    assert sinais.calcular(_cortar(dados, 84, k)) == [s for s in completo if s["mes"] <= ate]


def test_nenhum_sinal_olha_o_futuro_nos_dados_versionados():
    dados = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    periodos = dados["mensal"]["periodos"]
    k = periodos.index("2023-06")
    completo = sinais.calcular(dados)
    assert sinais.calcular(_cortar(dados, len(periodos), k)) == [s for s in completo if s["mes"] <= "2023-06"]


def test_ordem_mes_nivel_produto_tipo():
    lista_ = sinais.calcular(_aleatorio())
    chaves = [(s["mes"], sinais.NIVEIS.index(s["nivel"]), list(sinais.PRODUTOS).index(s["produto"]), sinais.TIPOS.index(s["tipo"])) for s in lista_]
    assert chaves == sorted(chaves) and len({s["id"] for s in lista_}) == len(lista_)


def test_formato_de_cada_sinal():
    doc = sinais.gerar(_aleatorio())
    assert list(doc) == ["versao", "periodo", "fonte", "limites", "produtos", "notas", "sinais"]
    assert doc["versao"] == 1 and doc["fonte"] == "Comex Stat/MDIC; Banco Mundial (Pink Sheet)"
    for s in doc["sinais"]:
        assert tuple(s) == sinais.CAMPOS
        assert re.fullmatch(r"\d{4}-\d{2}", s["mes"]) and s["id"] == f"{s['mes']}/{s['produto']}/{s['tipo']}"
        assert s["direcao"] in ("alta", "queda") and s["nivel"] in ("atencao", "forte")
        assert (s["metrica"], s["unidade"]) == sinais.METRICAS[s["tipo"]]
        assert isinstance(s["valor"], (int, float)) and not isinstance(s["valor"], bool)
        c = s["comparacao"]
        assert c["base"] == sinais.BASES[s["tipo"]] and isinstance(c["valor"], (int, float)) and isinstance(c["variacao_pct"], float)
        assert s["ancora"] in ({a for _, a in sinais.PRODUTOS.values()} | {sinais.ANCORA_TROCA})
        assert s["frase"] == sinais.frase(s) and s["frase"].startswith(sinais.PRODUTOS[s["produto"]][0] + ": ")
        assert "R$" not in s["frase"] and "−0" not in s["frase"] and "-0" not in s["frase"]
        if s["tipo"] == "troca_p90":
            assert "no porto" in s["frase"]
        if s["tipo"] == "ritmo_importacao":
            assert isinstance(s["valor"], int) and isinstance(c["valor"], int)


def test_deterministico_e_ida_e_volta():
    a = sinais.serializar(sinais.gerar(_aleatorio()))
    b = sinais.serializar(sinais.gerar(_aleatorio()))
    assert a == b
    doc = json.loads(a)
    assert sinais.serializar(doc) == a
    sinais.validar(doc)
    assert a.endswith("}\n") and "NaN" not in a


FORA_DO_FORMATO = {
    "versao": lambda d: d.update(versao=2),
    "sem limites": lambda d: d.pop("limites"),
    "id repetido": lambda d: d["sinais"].append(copy.deepcopy(d["sinais"][-1])),
    "fora de ordem": lambda d: d["sinais"].reverse(),
    "frase editada": lambda d: d["sinais"][0].update(frase=d["sinais"][0]["frase"] + "!"),
    "nível": lambda d: d["sinais"][0].update(nivel="alto"),
    "base": lambda d: d["sinais"][0]["comparacao"].update(base="outra"),
    "campos em outra ordem": lambda d: d["sinais"].__setitem__(0, dict(reversed(list(d["sinais"][0].items())))),
    "mês fora do período": lambda d: d["periodo"].update(fim="2015-06"),
}


@pytest.mark.parametrize("caso", FORA_DO_FORMATO)
def test_validar_recusa_arquivo_fora_do_formato(caso):
    doc = sinais.gerar(_aleatorio())
    sinais.validar(doc)
    FORA_DO_FORMATO[caso](doc)
    with pytest.raises(sinais.ErroSinais):
        sinais.validar(doc)


def test_sinais_do_mes_aceita_o_sinais_json_e_o_dashboard():
    dados = _aleatorio()
    doc = sinais.gerar(dados)
    mes = doc["sinais"][-1]["mes"]
    do_mes = sinais.sinais_do_mes(doc, mes)
    assert do_mes and all(s["mes"] == mes for s in do_mes)
    assert sinais.sinais_do_mes(dados, mes) == do_mes
    assert [s["nivel"] for s in do_mes] == sorted((s["nivel"] for s in do_mes), key=sinais.NIVEIS.index)
    assert sinais.sinais_do_mes(doc, "1999-01") == []


def test_cli_grava_e_mostra_um_mes(tmp_path, capsys):
    entrada, saida = tmp_path / "dashboard.json", tmp_path / "sinais.json"
    entrada.write_text(json.dumps(_aleatorio()), encoding="utf-8")
    assert sinais.main(["--dashboard", str(entrada), "--saida", str(saida)]) == 0
    doc = sinais.ler(saida)
    assert saida.read_text(encoding="utf-8") == sinais.serializar(doc)
    mes = doc["sinais"][-1]["mes"]
    capsys.readouterr()
    assert sinais.main(["--dashboard", str(entrada), "--mes", mes]) == 0
    saida_txt = capsys.readouterr().out
    for s in sinais.sinais_do_mes(doc, mes):
        assert s["frase"] in saida_txt
    assert sinais.main(["--dashboard", str(entrada), "--mes", "1999-01"]) == 1


def test_so_usa_a_biblioteca_padrao():
    codigo = "import sys, src.sinais; print(sorted(m for m in ('pandas', 'numpy', 'requests', 'pyarrow') if m in sys.modules))"
    r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, check=True)
    assert r.stdout.strip() == "[]"


# --- Dados versionados -----------------------------------------------------------------------


def test_sinais_json_versionado_esta_em_dia_com_o_dashboard():
    """data/sinais.json é exatamente o que python -m src.sinais gera do dashboard.json versionado."""
    dados = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    texto = config.SINAIS_JSON.read_text(encoding="utf-8")
    assert texto == sinais.serializar(sinais.gerar(dados)), "rode python -m src.sinais"
    doc = sinais.ler()
    assert doc["periodo"] == dados["meta"]["periodo"]
    ids = [s["id"] for s in doc["sinais"]]
    assert len(ids) == len(set(ids)) and doc["sinais"] == sorted(doc["sinais"], key=sinais._ordem)
    for s in doc["sinais"]:
        assert "R$" not in s["frase"]
        if s["tipo"] == "troca_p90":
            assert "no porto" in s["frase"] and s["produto"] in TROCA


def test_ancoras_existem_no_index_html():
    pagina = (RAIZ / "dashboard" / "index.html").read_text(encoding="utf-8")
    secao_insumos = 'id="insumos"' in pagina  # a seção Insumos do fósforo chega com a frente do site
    for chave, (_, ancora) in [*sinais.PRODUTOS.items(), ("troca", (None, sinais.ANCORA_TROCA))]:
        if chave in sinais.INSUMOS and not secao_insumos:
            continue
        assert f'id="{ancora[1:]}"' in pagina, ancora
