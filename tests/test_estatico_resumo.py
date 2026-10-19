"""Card Resumo e frases dos gráficos de volumes, origens, HHI, portos e rotas escritos no build
(src/estatico/resumo.py). Sem rede e sem navegador: a igualdade com o script do dashboard está em
tests/e2e/test_estatico_resumo.py."""

import json
import shutil
from pathlib import Path

import pytest

from src.estatico import dados as D
from src.estatico import formato as F
from src.estatico import resumo as R
from src.estatico.contexto import Contexto, ErroEstatico

RAIZ = Path(__file__).resolve().parent.parent
PAINEL = json.loads((RAIZ / "data" / "processed" / "dashboard.json").read_text(encoding="utf-8"))
GRUPOS = ["TOTAL", "N", "P", "K", "NPK"]


def _painel(t: list[float], inicio_ano: int = 2024) -> dict:
    """dashboard.json mínimo: a mesma série de toneladas em todos os grupos, a partir de janeiro."""
    periodos = [f"{inicio_ano + i // 12}-{i % 12 + 1:02d}" for i in range(len(t))]
    serie = {"t": list(t), "fob_musd": [x / 1e4 for x in t], "cif_musd": [x / 9e3 for x in t], "frete_musd": [x / 9e4 for x in t]}
    anos = sorted({int(p[:4]) for p in periodos})
    n_meses = [sum(1 for p in periodos if int(p[:4]) == a) for a in anos]
    anual = {g: {"hhi": [1000] * len(anos), "n_origens": [10] * len(anos), "lider": ["China"] * len(anos), "lider_share_pct": [30.0] * len(anos)} for g in GRUPOS}
    return {
        "meta": {"periodo": {"inicio": periodos[0], "fim": periodos[-1]}},
        "mensal": {"periodos": periodos, **{g: {k: list(v) for k, v in serie.items()} for g in GRUPOS}},
        "anual": {"anos": anos, "n_meses": n_meses, **anual},
        "origens": {"dados": {}},
        "urfs": {"dados": {}},
    }


# --- Auxiliares -------------------------------------------------------------------------------
def test_lista_com_e():
    assert R.lista_com_e([]) == ""
    assert R.lista_com_e(["A"]) == "A"
    assert R.lista_com_e(["A", "B"]) == "A e B"
    assert R.lista_com_e(["A", "B", "C"]) == "A, B e C"


def test_rotulo_ano_marca_o_ano_parcial():
    painel = _painel([100] * 15)  # 2024 inteiro e jan-mar/2025
    assert R.rotulo_ano(painel, 2024) == "2024"
    assert R.rotulo_ano(painel, 2025) == "2025 (jan–mar)"
    assert R.rotulo_ano(painel, 2030) == "2030"


@pytest.mark.parametrize(
    ("v", "esperado"),
    [
        (-27.94, "27,9% a menos que em set/2025"),
        (5.26, "5,3% a mais que em set/2025"),
        (0.04, "praticamente o mesmo que em set/2025"),
        (-0.04, "praticamente o mesmo que em set/2025"),  # sinal pelo número arredondado: nunca "−0,0"
        (None, None),
        (float("inf"), None),
        (float("nan"), None),
    ],
)
def test_comparado_a(v, esperado):
    assert R.comparado_a(v, "set/2025") == esperado


# --- Volumes ----------------------------------------------------------------------------------
def test_frase_toneladas_mes_e_acumulado():
    painel = _painel([1_000_000] * 12 + [800_000, 900_000, 1_100_000])
    assert R.frase_toneladas(painel, "TOTAL", "2025-03") == (
        "Em mar/2025, o Brasil importou 1,1\u00a0mi t de fertilizantes, 10,0% a mais que em mar/2024. "
        "No acumulado de jan–mar/2025, foram 2,8\u00a0mi t, 6,7% a menos que em jan–mar/2024."
    )
    # janeiro: o acumulado é o próprio mês
    assert R.frase_toneladas(painel, "K", "2025-01") == "Em jan/2025, o Brasil importou 800\u00a0mil t de fertilizantes potássicos, 20,0% a menos que em jan/2024."


def test_frase_toneladas_sem_ano_anterior_e_sem_importacao():
    painel = _painel([1_000_000, 0, 500])
    assert R.frase_toneladas(painel, "NPK", "2024-01") == "Em jan/2024, o Brasil importou 1\u00a0mi t de fertilizantes compostos (NPK)."
    assert R.frase_toneladas(painel, "N", "2024-02") == (
        "Em fev/2024, o Brasil não importou fertilizantes nitrogenados. No acumulado de jan–fev/2024, foram 1\u00a0mi t."
    )


# --- Origens e portos -------------------------------------------------------------------------
def test_frase_ranking_das_origens():
    painel = _painel([100] * 12)
    painel["origens"]["dados"]["2024"] = {
        "TOTAL": [["676", "Rússia", 60, 21.852, None, None, None], ["160", "China", 30, 18.221, None, None, None],
                  ["149", "Canadá", 10, 15.015, None, None, None], ["474", "Marrocos", 5, 7.0, None, None, None],
                  [None, "Outros", 5, 37.912, None, None, None]],
        "K": [["149", "Canadá", 10, 60.0, None, None, None], [None, "Outros", 5, 40.0, None, None, None]],
        "N": [["160", "China", 30, 70.0, None, None, None], ["676", "Rússia", 60, 30.0, None, None, None]],
    }
    painel["anual"]["K"]["n_origens"] = [1]
    assert R.frase_ranking(painel, "origens", "TOTAL", 2024) == (
        "Maior origem dos fertilizantes em 2024: Rússia, com 21,9% das toneladas, à frente de China (18,2%) e Canadá (15,0%); "
        "juntas, as três somam 55,1%. Ao todo, as importações vieram de 10 países."
    )
    assert R.frase_ranking(painel, "origens", "N", 2024).startswith("Maior origem dos fertilizantes nitrogenados em 2024: China, com 70,0% das toneladas, à frente de Rússia (30,0%); juntas, as duas somam 100,0%.")
    assert R.frase_ranking(painel, "origens", "K", 2024) == "Maior origem dos fertilizantes potássicos em 2024: Canadá, com 60,0% das toneladas. Ao todo, as importações vieram de 1 país."
    assert R.frase_ranking(painel, "origens", "P", 2024) == "Sem importações de fertilizantes fosfatados em 2024."
    assert R.frase_ranking(painel, "origens", "TOTAL", 2019) == "Sem importações de fertilizantes em 2019."


def test_frase_ranking_dos_portos_usa_o_nome_curto_da_urf():
    painel = _painel([100] * 12)
    painel["urfs"]["dados"]["2024"] = {"TOTAL": [
        ["0917800", "PORTO DE PARANAGUA", 50, 50.0, None, None], ["0317903", "IRF SAO LUIS", 30, 30.0, None, None],
        ["0517800", "ALF - SALVADOR", 15, 15.0, None, None], [None, "Outros", 5, 5.0, None, None],
    ]}
    assert R.frase_ranking(painel, "portos", "TOTAL", 2024) == (
        "Maior porto de entrada (URF) dos fertilizantes em 2024: Paranaguá, com 50,0% das toneladas, "
        "à frente de IRF São Luís (30,0%) e ALF - Salvador (15,0%); juntos, os três somam 95,0%."
    )


def test_soma_dos_shares_na_ordem_do_script():
    # o sum() do Python 3.12+ compensa o arredondamento; o script soma na ordem, como o laço
    painel = _painel([100] * 12)
    painel["origens"]["dados"]["2024"] = {"TOTAL": [["1", "A", 1, 0.1, None, None, None], ["2", "B", 1, 0.2, None, None, None], ["3", "C", 1, 0.3, None, None, None]]}
    soma = 0
    for v in (0.1, 0.2, 0.3):
        soma += v
    assert f"somam {F.pct(soma)}." in R.frase_ranking(painel, "origens", "TOTAL", 2024)


# --- HHI --------------------------------------------------------------------------------------
def test_frase_hhi_com_todos_os_grupos_por_posicao_no_limiar():
    painel = _painel([100] * 21)  # 2024 inteiro e jan-set/2025
    for g, hhi in {"N": 2499, "P": 1769, "K": 2803, "NPK": 1597}.items():
        painel["anual"][g]["hhi"] = [1000, hhi]
    assert R.frase_hhi(painel, "TOTAL", 2025) == (
        "Em 2025 (jan–set), o HHI de N (2.499) e K (2.803) ficou acima de 1.800, o limiar de mercado altamente concentrado; "
        "o de P (1.769) e NPK (1.597), abaixo."
    )
    assert R.frase_hhi(painel, "TOTAL", 2024) == "Em 2024, o HHI de N (1.000), P (1.000), K (1.000) e NPK (1.000) ficou abaixo de 1.800, o limiar de mercado altamente concentrado."
    painel["anual"]["P"]["hhi"] = [1000, 1800]
    assert "; o de P (1.800), no limiar; o de NPK (1.597), abaixo." in R.frase_hhi(painel, "TOTAL", 2025)


def test_frase_hhi_de_um_grupo_cita_a_maior_origem():
    painel = _painel([100] * 12)
    painel["anual"]["K"].update(hhi=[2803], lider=["Canadá"], lider_share_pct=[38.823])
    assert R.frase_hhi(painel, "K", 2024) == (
        "Em 2024, o HHI dos fertilizantes potássicos ficou em 2.803, acima de 1.800, o limiar de mercado altamente concentrado; "
        "a maior origem, Canadá, teve 38,8% das toneladas."
    )
    painel["anual"]["K"].update(hhi=[None], lider=[None])
    assert R.frase_hhi(painel, "K", 2024) == ""
    assert R.frase_hhi(painel, "K", 2019) == ""


# --- Rotas ------------------------------------------------------------------------------------
def _bloco_rotas(**extra) -> dict:
    bloco = {
        "origens": [["676", "Rússia", 100], [None, "Outros", 20]],
        "urfs": [["0817800", "PORTO DE SANTOS", 90], [None, "Outros", 30]],
        "fluxos": [[0, 0, 80, 44.1], [0, 1, 20, 40.0], [1, 0, 10, 30.0], [1, 1, 10, 30.0]],
        "rotas": [["Rússia", "0817800", "PORTO DE SANTOS", 1718203, 6.04, 44.1, 9.4, 9]],
        "n_rotas": 381, "n_relevantes": 100, "share_relevantes_pct": 93.0, "frete_relevantes": 33.5, "corte_t": 37500,
    }
    bloco.update(extra)
    return bloco


def test_frase_rotas():
    painel = _painel([100] * 21)
    painel["rotas"] = {"corte_t": 50000, "dados": {}}
    assert R.frase_rotas(painel, _bloco_rotas(), "TOTAL", 2025) == (
        "Maior rota dos fertilizantes em 2025 (jan–set): Rússia → Santos, com 1,7\u00a0mi t (6,0% do total) e frete de US$ 44/t. "
        "As 100 rotas com pelo menos 37.500 t somam 93,0% das toneladas, com frete médio de US$ 34/t."
    )
    uma = R.frase_rotas(painel, _bloco_rotas(n_relevantes=1, frete_relevantes=None, rotas=[["Rússia", "1", "SANTAREM", 60000, 50.0, None, None, 9]]), "K", 2024)
    assert uma == "Maior rota dos fertilizantes potássicos em 2024: Rússia → Santarém, com 60\u00a0mil t (50,0% do total). A rota com pelo menos 37.500 t soma 93,0% das toneladas."
    assert R.frase_rotas(painel, _bloco_rotas(rotas=[], corte_t=None), "P", 2024) == "Em 2024, nenhuma rota de fertilizantes fosfatados teve pelo menos 50.000 t."
    assert R.frase_rotas(painel, None, "NPK", 2024) == "Sem importações de fertilizantes compostos (NPK) em 2024."
    assert R.frase_rotas(painel, _bloco_rotas(fluxos=[]), "NPK", 2024) == "Sem importações de fertilizantes compostos (NPK) em 2024."


def test_rotulo_do_diagrama_traz_as_maiores_rotas_sem_outros_e_a_frase():
    painel = _painel([100] * 12)
    painel["rotas"] = {"corte_t": 50000, "dados": {}}
    rotulo = R.rotulo_sankey(painel, _bloco_rotas(), "TOTAL", 2024)
    assert rotulo.startswith("Fluxo das importações, Todos os grupos, 2024: das maiores origens para as maiores URFs. Maiores rotas: Rússia para Santos, 80 t. A tabela abaixo traz o frete por rota. Maior rota dos")
    assert R.rotulo_sankey(painel, None, "TOTAL", 2024) == "Sem importações neste ano e grupo."


# --- Destaques do card Resumo -----------------------------------------------------------------
def _painel_troca() -> dict:
    painel = _painel([100] * 12)
    painel["origens"]["dados"]["2024"] = {g: [["676", "Rússia", 60, 60.0, None, None, None], ["160", "China", 40, 40.0, None, None, None]] for g in GRUPOS}
    produto = lambda nome, razao: {"nome": nome, "razao": [None] * 11 + [razao]}  # noqa: E731
    painel["troca"] = {"periodos": painel["mensal"]["periodos"], "produtos": {"kcl": produto("KCl", 0.835864), "ureia": produto("Ureia", 0.949905), "map": produto("MAP", None)}}
    return painel


def test_destaques_com_origens_e_troca_no_porto():
    painel = _painel_troca()
    assert R.texto_destaques(painel, "TOTAL", "2024-12") == (
        "Principais origens em 2024: Rússia (60,0% das toneladas) e China (40,0%). "
        "Relação de troca no porto em dez/2024, em t de soja por t de fertilizante: KCl 0,84; Ureia 0,95. "  # MAP sem valor no mês
        "Não é o preço ao produtor. Fonte: Comex Stat/MDIC."
    )
    k = R.texto_destaques(painel, "K", "2024-12")
    assert "KCl 0,84." in k and "Ureia" not in k
    assert "troca" not in R.texto_destaques(painel, "NPK", "2024-12")  # NPK não entra na relação
    assert "troca" not in R.texto_destaques(painel, "P", "2024-12")  # o MAP não tem valor no mês
    assert "troca" not in R.texto_destaques(painel, "TOTAL", "2024-11")
    del painel["troca"]
    assert R.texto_destaques(painel, "TOTAL", "2024-12") == "Principais origens em 2024: Rússia (60,0% das toneladas) e China (40,0%). Fonte: Comex Stat/MDIC."
    painel["origens"]["dados"] = {}
    assert R.texto_destaques(painel, "TOTAL", "2024-12") == ""


def test_kpis_html_igual_ao_cartao_do_script():
    cartoes = [{"rotulo": "Toneladas", "valor": f"3,1{F.NBSP}mi t", "delta": "▼ −27,9%"}, {"rotulo": "A <b>", "valor": "x & y", "delta": "–"}]
    assert R.kpis_html(cartoes) == (
        '<div class="kpi"><div class="rotulo">Toneladas</div><div class="valor"><span class="numero">3,1 mi t</span></div><div class="delta">▼ −27,9%</div></div>'
        '<div class="kpi"><div class="rotulo">A &lt;b&gt;</div><div class="valor"><span class="numero">x &amp; y</span></div><div class="delta">–</div></div>'
    )


# --- Dados reais ------------------------------------------------------------------------------
@pytest.mark.parametrize("g", GRUPOS)
def test_todas_as_frases_saem_para_todos_os_meses_dos_dados(g):
    """Nenhum mês ou grupo da série quebra as frases, e as regras das saídas públicas valem em todos."""
    p = PAINEL["mensal"]["periodos"]
    for ate in p:
        ano = int(ate[:4])
        destaques = R.texto_destaques(PAINEL, g, ate)
        if "troca" in destaques:
            assert "Relação de troca no porto" in destaques and "Não é o preço ao produtor." in destaques
        assert "R$" not in destaques
        assert destaques.endswith("Fonte: Comex Stat/MDIC.")
        bloco = (PAINEL["rotas"]["dados"].get(str(ano)) or {}).get(g)
        frases = [
            R.frase_toneladas(PAINEL, g, ate), R.frase_ranking(PAINEL, "origens", g, ano), R.frase_ranking(PAINEL, "portos", g, ano),
            R.frase_hhi(PAINEL, g, ano), R.frase_rotas(PAINEL, bloco, g, ano), R.rotulo_sankey(PAINEL, bloco, g, ano),
            R.rotulo_toneladas(PAINEL, g, p[0], ate), R.rotulo_hhi(PAINEL, g, p[0], ate),
        ]
        for frase in frases:
            assert frase and frase.endswith(".") and "None" not in frase and "nan" not in frase.lower(), (g, ate, frase)
            assert "ágio" not in frase and "UF do importador" not in frase


def _site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    site.mkdir()
    shutil.copy(RAIZ / "dashboard" / "index.html", site / "index.html")
    shutil.copy(RAIZ / "data" / "processed" / "dashboard.json", site / "dashboard.json")
    (site / "boletim.json").write_text("{}", encoding="utf-8")
    return site


def test_gerar_preenche_o_card_resumo_e_as_frases_da_visao_padrao(tmp_path):
    ctx = Contexto.carregar(_site(tmp_path))
    R.gerar(ctx)
    html = ctx.html
    p = PAINEL["mensal"]["periodos"]
    ate, ano = p[-1], int(p[-1][:4])
    k = D.kpis(PAINEL, "TOTAL", ate)
    assert f'id="titulo-kpis">{k["titulo"]}</h3>' in html
    assert f'id="titulo-mes">{k["titulo_mes"]}</h3>' in html
    assert f'id="kpis-mes">{R.kpis_html(k["mes"])}</div>' in html
    assert f'id="kpis-acumulado">{R.kpis_html(k["acumulado"])}</div>' in html
    # os números vêm do dashboard.json: o último mês e o ano dele
    assert F.toneladas(PAINEL["mensal"]["TOTAL"]["t"][-1]) in R.frase_toneladas(PAINEL, "TOTAL", ate)
    maior = PAINEL["origens"]["dados"][str(ano)]["TOTAL"][0]
    assert f"{maior[1]} ({F.pct(maior[3])} das toneladas)" in R.texto_destaques(PAINEL, "TOTAL", ate)
    for id_ in ("destaques-kpis", "resumo-toneladas", "resumo-origens", "resumo-hhi", "resumo-portos", "resumo-rotas",
                "nota-kpis", "nota-toneladas", "nota-origens", "nota-hhi", "nota-portos", "nota-rotas"):
        assert f'id="{id_}"></' not in html, f"#{id_} ficou vazio"
    for id_, rotulo in (("grafico-toneladas", R.rotulo_toneladas(PAINEL, "TOTAL", p[0], ate)), ("grafico-hhi", R.rotulo_hhi(PAINEL, "TOTAL", p[0], ate))):
        assert f'id="{id_}" role="img" aria-label="{rotulo}"' in html
    assert 'id="sankey" role="img" aria-label="Fluxo das importações, Todos os grupos' in html
    # rodar de novo no mesmo HTML é erro de build (o elemento já não está vazio)
    with pytest.raises(ErroEstatico):
        R.gerar(ctx)


def test_index_html_tem_os_encaixes_vazios():
    """Os pontos de encaixe do build existem uma vez e vazios no index.html do repositório."""
    html = (RAIZ / "dashboard" / "index.html").read_text(encoding="utf-8")
    for id_ in ("titulo-kpis", "nota-kpis", "titulo-mes", "titulo-acumulado", "kpis-mes", "kpis-acumulado", "destaques-kpis",
                "resumo-toneladas", "resumo-origens", "resumo-hhi", "resumo-portos", "resumo-rotas"):
        assert html.count(f'id="{id_}"') == 1, id_
        assert f'id="{id_}"></' in html, f"#{id_} não está vazio no index.html"
