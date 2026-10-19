"""src/estatico/insumos.py: a seção "Insumos do fósforo" no HTML do build (frases, aria-labels, notas,
tabelas e o item do Método) e a página estática insumos/.

A igualdade com o que o script desenha é conferida no navegador (tests/e2e/test_estatico_insumos.py);
aqui ficam as contas, os casos sem dado e com amostra pequena e as regras do CLAUDE.md (no porto,
aproximação que não é o custo de nenhuma empresa nem o preço ao produtor, spread com o preço do
Brasil da base e "não é ágio", fontes citadas, nenhum número escrito à mão).
"""

import copy
import json
import re
from pathlib import Path

import pytest

from src.estatico import formato as F
from src.estatico import insumos as I
from src.estatico.contexto import Contexto, ErroEstatico, esc

RAIZ = Path(__file__).resolve().parents[1]
INDEX = RAIZ / "dashboard" / "index.html"
DADOS = json.loads((RAIZ / "data" / "processed" / "dashboard.json").read_text(encoding="utf-8"))
P = DADOS["mensal"]["periodos"]
TODOS = list(range(len(P)))
FONTE_COMEX = "Fonte: Comex Stat/MDIC."
FONTE_PINK = "Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet)."


# --- Dados de mentira: 27 meses (jan/2024 a mar/2026), valores redondos ---------------------------
def _periodos(n=27, inicio=2024):
    return [f"{inicio + i // 12}-{i % 12 + 1:02d}" for i in range(n)]


def _prod(nome, descricao, t, fob, cif, frete, n):
    return {
        "nome": nome, "descricao": descricao, "ncms": ["0"], "corte_amostra_t": 30_000, "t": [t] * n,
        "fob_musd": [t * fob / 1e6] * n, "cif_musd": [t * cif / 1e6] * n, "frete_musd": [t * frete / 1e6] * n,
        "fob": [fob] * n, "cif": [cif] * n, "frete": [frete] * n, "amostra_pequena": [False] * n,
    }


def _falsos(n=27):
    per = _periodos(n)
    enxofre = _prod("Enxofre", "enxofre a granel e outras formas (NCM 2503)", 100_000, 200.0, 220.0, 20.0, n)
    rocha = _prod("Rocha fosfática", "fosfatos de cálcio naturais (NCM 2510.10 e 2510.20)", 150_000, 100.0, 120.0, 20.0, n)
    rocha["benchmark"] = {"serie": "Phosphate rock", "base": "FOB Norte da África", "comparacao": "FOB×FOB", "bm": [125.0] * n,
                          "spread_usd_t": [-25.0] * n, "spread_pct": [-20.0] * n, "pink_atualizado_em": None}
    custo = 0.45 * 220.0 + 1.7 * 120.0
    return {
        "meta": {"periodo": {"inicio": per[0], "fim": per[-1]}},
        "mensal": {"periodos": per},
        "anual": {"anos": [2024, 2025, 2026], "n_meses": [12, 12, n - 24]},
        "insumos": {
            "periodos": per, "fonte": "Comex Stat/MDIC; Banco Mundial (Pink Sheet)", "produtos": {"enxofre": enxofre, "rocha": rocha},
            "origens": {"2026": {"enxofre": [["249", "Estados Unidos", 60_000, 60.0, 10.0], [None, "Outros", 40_000, 40.0, None]], "rocha": []}},
            "custo_map": {"coef_enxofre": 0.45, "coef_rocha": 1.7, "ncms_map": ["31054000"], "corte_amostra_map_t": 10_000,
                          "custo": [custo] * n, "cif_map": [600.0] * n, "razao": [custo / 600.0] * n, "amostra_pequena": [False] * n},
            "notas": ["Nota A com o coeficiente.", "Nota B."],
        },
    }


@pytest.fixture
def falsos():
    return _falsos()


def _todos(d):
    return list(range(len(d["mensal"]["periodos"])))


# --- Volume ----------------------------------------------------------------------------------------
def test_volume_contra_o_mesmo_mes_e_o_acumulado(falsos):
    falsos["insumos"]["produtos"]["enxofre"]["t"][-1] = 120_000
    frase = I.frase_volume_insumo(falsos, "enxofre", _todos(falsos))
    assert frase == (f"Em mar/2026, o Brasil importou {F.toneladas(120_000)} de enxofre, 20,0% a mais que em mar/2025. "
                     f"No acumulado de jan–mar/2026, foram {F.toneladas(320_000)}, 6,7% a mais que em jan–mar/2025. {FONTE_COMEX}")
    # a rocha fosfática pelo mesmo caminho
    assert I.frase_volume_insumo(falsos, "rocha", _todos(falsos)).startswith(f"Em mar/2026, o Brasil importou {F.toneladas(150_000)} de rocha fosfática, praticamente o mesmo")


def test_volume_sem_importacao_sem_dado_e_acumulado_incompleto(falsos):
    t = falsos["insumos"]["produtos"]["enxofre"]["t"]
    t[-1] = 0
    assert I.frase_volume_insumo(falsos, "enxofre", _todos(falsos)).startswith("Em mar/2026, o Brasil não importou enxofre. No acumulado de jan–mar/2026")
    t[-1] = None  # fora do período ingerido: não é zero
    assert I.frase_volume_insumo(falsos, "enxofre", _todos(falsos)) == f"Em mar/2026, não há dado de importação de enxofre. {FONTE_COMEX}"
    t[-1], t[-2] = 100_000, None  # um mês do ano sem dado: sem o acumulado
    assert "acumulado" not in I.frase_volume_insumo(falsos, "enxofre", _todos(falsos))
    t[-2], t[13] = 100_000, None  # fev/2025 sem dado: acumulado sem comparação
    assert I.frase_volume_insumo(falsos, "enxofre", _todos(falsos)).endswith(f"No acumulado de jan–mar/2026, foram {F.toneladas(300_000)}. {FONTE_COMEX}")


# --- Preço do enxofre --------------------------------------------------------------------------------
def test_preco_do_enxofre_com_ano_anterior_e_extremos(falsos):
    cif = falsos["insumos"]["produtos"]["enxofre"]["cif"]
    cif[-13] = 200.0  # mar/2025
    frase = I.frase_preco_enxofre(falsos, _todos(falsos))
    assert frase == ("Em mar/2026, o enxofre importado custou US$ 220/t CIF (10,0% a mais que em mar/2025), com US$ 200/t FOB e US$ 20/t de frete. "
                     f"No período, o CIF foi de US$ 200/t (mar/2025, o menor) a US$ 220/t (jan/2024, o maior). {FONTE_COMEX}")


def test_preco_do_enxofre_com_amostra_pequena(falsos):
    prod = falsos["insumos"]["produtos"]["enxofre"]
    prod["amostra_pequena"][-1], prod["t"][-1], prod["cif"][-1] = True, 5_000, 999.0
    prod["amostra_pequena"][-13], prod["cif"][-13] = True, 1.0  # o ano anterior fora: nem comparação nem extremo
    frase = I.frase_preco_enxofre(falsos, _todos(falsos))
    assert frase.startswith(f"Em mar/2026, a importação de enxofre foi de {F.toneladas(5_000)}, menos de 30.000 t: amostra pequena, fora do gráfico de preço.")
    assert "US$ 999" not in frase and "US$ 1/t" not in frase
    prod["amostra_pequena"][-2] = False
    prod["cif"][-2] = 230.0
    assert "US$ 220/t (jan/2024, o menor) a US$ 230/t (fev/2026, o maior)" in I.frase_preco_enxofre(falsos, _todos(falsos))
    # um mês só no período: sem extremos
    assert "No período" not in I.frase_preco_enxofre(falsos, [0])


# --- Rocha x Pink Sheet ------------------------------------------------------------------------------
def test_rocha_com_o_preco_do_brasil_da_base_e_nao_e_agio(falsos):
    ref = falsos["insumos"]["produtos"]["rocha"]["benchmark"]
    ref["spread_pct"][:3] = [5.0, 0.04, -0.04]  # acima de zero pelo número arredondado: +0,0% não conta
    frase = I.frase_rocha(falsos, _todos(falsos))
    assert frase == ("Em mar/2026, o Brasil importou rocha fosfática a US$ 100/t FOB e US$ 120/t CIF; o benchmark do Banco Mundial "
                     "(Phosphate rock), na base FOB Norte da África, foi de US$ 125/t. Na base comparável (FOB×FOB), o preço do Brasil, de "
                     "US$ 100/t FOB, ficou 20,0% abaixo do benchmark (−US$ 25/t). No período, ficou acima do benchmark em 1 de 27 meses "
                     "comparáveis. Não é ágio: o benchmark é de outro lugar e de outro momento de contrato. " + FONTE_PINK)
    # base no destino (CIF×CFR): o preço do Brasil vira o CIF
    ref["comparacao"] = "CIF×CFR"
    assert "o preço do Brasil, de US$ 120/t CIF, ficou" in I.frase_rocha(falsos, _todos(falsos))


def test_rocha_com_o_ultimo_mes_fora_da_comparacao(falsos):
    prod = falsos["insumos"]["produtos"]["rocha"]
    prod["amostra_pequena"][-1], prod["t"][-1], prod["benchmark"]["spread_pct"][-1] = True, 8_000, None
    frase = I.frase_rocha(falsos, _todos(falsos))
    assert frase.startswith(f"Em mar/2026, a importação de rocha fosfática foi de {F.toneladas(8_000)}, menos de 30.000 t: amostra pequena, fora da comparação. "
                            "Em fev/2026, o último mês comparável do período, o Brasil importou rocha fosfática")
    assert "em 0 de 26 meses comparáveis" in frase
    # sem nenhum mês comparável no período
    assert I.frase_rocha(falsos, [26]).endswith(f"fora da comparação. Nenhum mês do período tem preço comparável com o benchmark. {FONTE_PINK}")
    # sem a Pink Sheet no mês (e sem amostra pequena)
    prod["amostra_pequena"][-1], prod["t"][-1] = False, 150_000
    assert I.frase_rocha(falsos, _todos(falsos)).startswith("Em mar/2026, não há benchmark do Banco Mundial para rocha fosfática. Em fev/2026")
    prod["t"][-1] = 0
    assert I.frase_rocha(falsos, _todos(falsos)).startswith("Em mar/2026, não houve importação de rocha fosfática. Em fev/2026")


# --- Custo de insumo e razão -------------------------------------------------------------------------
def test_custo_de_insumo_com_os_coeficientes_do_dashboard_json(falsos):
    frase = I.frase_custo_map(falsos, _todos(falsos))
    assert frase == ("Em mar/2026, o custo de insumo por tonelada de MAP, no porto, foi de US$ 303/t: 0,45 t de enxofre a US$ 220/t CIF e "
                     "1,7 t de rocha fosfática a US$ 120/t CIF. O CIF do MAP importado no mesmo mês foi de US$ 600/t. É uma aproximação "
                     f"técnica, não o custo de nenhuma empresa nem o preço ao produtor. {FONTE_COMEX}")
    # nenhum coeficiente escrito à mão: os do bloco (config.py) entram na frase e nas notas
    falsos["insumos"]["custo_map"].update(coef_enxofre=0.5, coef_rocha=1.65)
    assert "0,5 t de enxofre" in I.frase_custo_map(falsos, _todos(falsos)) and "1,65 t de rocha fosfática" in I.frase_custo_map(falsos, _todos(falsos))
    assert "CIF do enxofre × 0,5 + CIF da rocha fosfática × 1,65" in I.notas(falsos, _todos(falsos))["nota-custo-map"]


def test_custo_de_insumo_fora_dos_graficos(falsos):
    c = falsos["insumos"]["custo_map"]
    c["amostra_pequena"][-1] = True
    frase = I.frase_custo_map(falsos, _todos(falsos))
    assert frase.startswith("Em mar/2026, o custo de insumo fica fora dos gráficos: amostra pequena (menos de 30.000 t de enxofre, 30.000 t de "
                            "rocha fosfática ou 10.000 t de MAP no mês). Em fev/2026, o último mês do período nos gráficos, o custo de insumo")
    c["amostra_pequena"][-1], c["custo"][-1], c["razao"][-1] = False, None, None
    assert I.frase_custo_map(falsos, _todos(falsos)).startswith(
        "Em mar/2026, não há custo de insumo: falta o preço de enxofre, de rocha fosfática ou de MAP no mês. Em fev/2026")
    assert I.frase_custo_map(falsos, [26]).endswith(f"no mês. Nenhum mês do período tem custo de insumo. {FONTE_COMEX}")
    assert I.frase_razao_map(falsos, [26]).endswith(f"no mês. Nenhum mês do período tem a razão entre o custo de insumo e o CIF do MAP. {FONTE_COMEX}")


def test_razao_com_media_maior_e_menor(falsos):
    r = falsos["insumos"]["custo_map"]["razao"]
    r[0], r[1] = 0.4, 0.7
    s = 0
    for x in r:
        s += 100 * x
    frase = I.frase_razao_map(falsos, _todos(falsos))
    assert frase == (f"Em mar/2026, o custo de insumo equivaleu a {F.pct(100 * r[-1])} do CIF do MAP, no porto. Na média dos 27 meses do "
                     f"período nos gráficos, {F.pct(s / 27)}; o maior, 70,0%, em fev/2024, e o menor, 40,0%, em jan/2024. É uma aproximação "
                     f"técnica, não o custo de nenhuma empresa. {FONTE_COMEX}")
    # um mês só: sem média
    assert "média" not in I.frase_razao_map(falsos, [26])


# --- Notas, aria-labels e tabelas --------------------------------------------------------------------
def test_notas_e_item_do_metodo_vem_do_bloco(falsos):
    n = I.notas(falsos, _todos(falsos))
    assert n["nota-enxofre"].startswith("Enxofre a granel e outras formas (NCM 2503) · US$ por tonelada e toneladas · jan/2024 a mar/2026 · "
                                        "meses com menos de 30.000 t")
    assert "benchmark: Phosphate rock, FOB Norte da África, Banco Mundial" in n["nota-rocha"]
    assert n["metodo-insumos"] == "Insumos do fósforo (enxofre e rocha fosfática importados): Nota A com o coeficiente. Nota B."
    rotulos = I.rotulos(falsos, _todos(falsos))
    frases = I.frases(falsos, _todos(falsos))
    assert set(rotulos) == set(I.CANVAS) and set(frases) == set(I.FRASES)
    for canvas, frase in zip(I.CANVAS, I.FRASES):
        assert rotulos[canvas].endswith(f"de jan/2024 a mar/2026. A tabela abaixo traz os valores. {frases[frase]}") or \
            f"de jan/2024 a mar/2026, com a média dos meses do período tracejada. A tabela abaixo traz os valores. {frases[frase]}" in rotulos[canvas]


def test_tabelas_marcam_amostra_pequena_e_sinal(falsos):
    falsos["insumos"]["produtos"]["rocha"]["amostra_pequena"][0] = True
    falsos["insumos"]["custo_map"]["amostra_pequena"][0] = True
    rocha = I.tabela_rocha(falsos, [0, 1])
    assert rocha.startswith('<table><thead><tr><th>Mês</th><th class="num">Toneladas</th>')
    assert '<td>jan/2024</td><td class="num">150.000</td><td class="num">100</td><td class="num">120</td><td class="num">125,0</td>' \
           '<td class="num">-25</td><td class="num">-20,0</td><td>pequena</td>' in rocha
    assert "<td>fev/2024</td>" in rocha and rocha.count("pequena") == 1
    custo = I.tabela_custo_map(falsos, [0])
    assert '<td class="num">303</td><td class="num">600</td><td class="num">50,5%</td><td>pequena</td>' in custo
    enxofre = I.tabela_enxofre(falsos, [0])
    assert enxofre == ('<table><thead><tr><th>Mês</th><th class="num">Toneladas</th><th class="num">FOB US$/t</th><th class="num">CIF US$/t</th>'
                       '<th class="num">Frete US$/t</th><th>Amostra</th></tr></thead><tbody><tr><td>jan/2024</td><td class="num">100.000</td>'
                       '<td class="num">200</td><td class="num">220</td><td class="num">20</td><td></td></tr></tbody></table>')


def test_por_ano_com_os_mesmos_meses_do_ano_anterior(falsos):
    falsos["insumos"]["produtos"]["enxofre"]["t"][24] = 130_000  # jan/2026
    anos = {x["ano"]: x for x in I.por_ano(falsos, "enxofre")}
    assert anos[2024]["t"] == 1_200_000 and anos[2024]["var_t"] is None
    assert anos[2026]["t"] == 330_000 and anos[2026]["var_t"] == pytest.approx(10.0)  # jan–mar/2026 x jan–mar/2025
    assert anos[2025]["cif"] == pytest.approx(220.0) and anos[2025]["fob"] == pytest.approx(200.0)
    assert "2026 (jan–mar)" in I.tabela_por_ano(falsos, "enxofre")


# --- Regras do CLAUDE.md em todas as frases do JSON versionado ---------------------------------------
def _todas():
    for indices in (TODOS, TODOS[:60], TODOS[-5:], TODOS[:1], TODOS[-13:-12]):
        for id_, frase in I.frases(DADOS, indices).items():
            yield id_, frase


def test_frases_seguem_as_regras_das_saidas_publicas():
    for id_, frase in _todas():
        assert frase.endswith(FONTE_PINK if id_ == "resumo-rocha" else FONTE_COMEX), (id_, frase)
        if id_ in ("resumo-custo-map", "resumo-razao-map"):
            assert "no porto" in frase and "aproximação técnica, não o custo de nenhuma empresa" in frase, frase
        if id_ == "resumo-custo-map" and "Nenhum mês" not in frase:
            assert "nem o preço ao produtor" in frase, frase
        if id_ == "resumo-rocha" and "Nenhum mês" not in frase:
            assert "Não é ágio: o benchmark é de outro lugar e de outro momento de contrato." in frase, frase
            assert re.search(r"o preço do Brasil, de US\$ [\d.]+/t (FOB|CIF), ficou", frase), frase  # spread com o preço da base
        assert "R$" not in frase and "PTAX" not in frase, frase
        assert "ágio" not in frase.replace("Não é ágio", ""), frase
        assert "−0,0" not in frase and "-0" not in frase and "NaN" not in frase and "None" not in frase and "undefined" not in frase, frase


def test_bloco_versionado_com_os_coeficientes_do_config():
    from src import config

    c = DADOS["insumos"]["custo_map"]
    assert (c["coef_enxofre"], c["coef_rocha"]) == (config.INSUMOS_COEF_ENXOFRE, config.INSUMOS_COEF_ROCHA)
    nota = I.notas(DADOS, TODOS)["nota-custo-map"]
    assert f"× {I.fmt_coef(config.INSUMOS_COEF_ENXOFRE)} +" in nota and f"× {I.fmt_coef(config.INSUMOS_COEF_ROCHA)}," in nota


# --- gerar(): o index.html do build e a página insumos/ ----------------------------------------------
def _ctx(dados, tmp_path):
    return Contexto(site=tmp_path, dados=dados, boletim={}, html=INDEX.read_text(encoding="utf-8"), atualizado="2026-10-01")


def _conteudo(html, id_):
    return re.search(r'id="' + re.escape(id_) + r'">(.*?)</(p|li|div)>', html, re.S).group(1)


def _rotulo(html, id_):
    tag = re.search(r'<canvas id="' + id_ + r'"[^>]*>', html).group(0)
    m = re.search(r'aria-label="([^"]*)"', tag)
    return m and m.group(1)


def test_gerar_preenche_a_visao_padrao(tmp_path):
    ctx = _ctx(DADOS, tmp_path)
    I.gerar(ctx)
    frases = I.frases(DADOS, TODOS)
    for id_, texto in {**frases, **I.notas(DADOS, TODOS)}.items():
        assert texto and _conteudo(ctx.html, id_) == esc(texto), id_
    for id_, rotulo in I.rotulos(DADOS, TODOS).items():
        assert _rotulo(ctx.html, id_) == esc(rotulo), id_
    for id_, html in I.tabelas(DADOS, TODOS).items():
        assert f'id="{id_}">{html}</div>' in ctx.html, id_
    # a frase do primeiro gráfico de cada cartão logo depois da nota; a do segundo, depois do subtítulo
    for nota, frase in (("nota-enxofre", "resumo-enxofre"), ("nota-rocha", "resumo-rocha"), ("nota-custo-map", "resumo-custo-map")):
        assert re.search(r'id="' + nota + r'">[^<]*</p>\s*<p class="resumo-grafico" id="' + frase + '">', ctx.html), frase
    for frase in ("resumo-enxofre-t", "resumo-rocha-t", "resumo-razao-map"):
        assert re.search(r'</h3>\s*<p class="resumo-grafico" id="' + frase + '">', ctx.html), frase
    # a página insumos/ entra no sitemap e a seção liga para ela
    assert [p.caminho for p in ctx.paginas] == ["insumos/"] and (tmp_path / "insumos" / "index.html").is_file()
    assert '<span id="link-insumos-pagina"> A <a href="insumos/">página dos insumos</a>' in ctx.html


def test_gerar_sem_o_bloco_esconde_a_secao_como_o_script(tmp_path):
    dados = copy.deepcopy(DADOS)
    del dados["insumos"]
    ctx = _ctx(dados, tmp_path)
    I.gerar(ctx)
    assert '<section class="bloco oculto" id="insumos"' in ctx.html and '<li id="metodo-insumos" class="oculto"></li>' in ctx.html
    assert _conteudo(ctx.html, "resumo-enxofre") == "" and _rotulo(ctx.html, "grafico-enxofre") is None
    assert ctx.paginas == [] and not (tmp_path / "insumos").exists()


def test_gerar_falha_se_o_index_perdeu_um_ponto_de_encaixe(tmp_path):
    ctx = _ctx(DADOS, tmp_path)
    ctx.html = ctx.html.replace('<p class="resumo-grafico" id="resumo-rocha"></p>', "")
    with pytest.raises(ErroEstatico, match="resumo-rocha"):
        I.gerar(ctx)
    ctx = _ctx(copy.deepcopy(DADOS), tmp_path)
    del ctx.dados["insumos"]["custo_map"]
    with pytest.raises(ErroEstatico, match="insumos"):
        I.gerar(ctx)


def test_index_tem_um_ponto_de_encaixe_por_id_e_o_script_escreve_neles():
    html = INDEX.read_text(encoding="utf-8")
    for id_ in [*I.FRASES, *I.NOTAS, *I.TABELAS, *I.CANVAS, "insumos", "link-insumos-pagina"]:
        assert html.count(f'id="{id_}"') == 1, id_
    for id_ in I.FRASES:
        assert f'texto("{id_}", ' in html, id_
    for id_ in I.NOTAS:
        assert f'"{id_}": `' in html, id_  # notasInsumos(), escrita por desenharInsumos
    for id_ in I.TABELAS:
        assert f'tabela("{id_}",' in html, id_
    for funcao in ("fraseVolumeInsumo", "frasePrecoEnxofre", "fraseRocha", "fraseCustoMap", "fraseRazaoMap", "notasInsumos", "semPrecoInsumo",
                   "semCustoMap", "razoesMap", "desenharInsumos", "fmtCoef", "noMesInsumos"):
        assert f"function {funcao}(" in html or f"const {funcao} = " in html, funcao
    assert "  desenharInsumos(indices);\n" in html.split("function atualizar() {", 1)[1].split("\n}", 1)[0]
    # menu: "Insumos" logo depois de "Preços"; a seção logo depois de #precos, antes de #troca, com a numeração seguinte
    menu = re.search(r'<nav class="nav-pilula" id="nav-secoes".*?</nav>', html, re.S).group(0)
    assert '<a href="#precos" data-secao="precos">Preços</a>\n      <a href="#insumos" data-secao="insumos">Insumos</a>' in menu
    assert html.index('id="precos"') < html.index('id="insumos"') < html.index('id="troca"')
    kickers = re.findall(r'<p class="kicker">(\d\d) · ([^<]+)</p>', html)
    assert [n for n, _ in kickers] == [f"{k:02d}" for k in range(1, len(kickers) + 1)]
    assert ("07", "Insumos") in kickers
    assert '<h2 class="titulo-bloco" id="t-insumos" tabindex="-1">Insumos do fósforo</h2>' in html


def test_glossario_e_metodo_dos_insumos_sem_numeros_escritos_a_mao():
    html = INDEX.read_text(encoding="utf-8")
    glossario = re.search(r'<dl class="glossario">(.*?)</dl>', html, re.S).group(1)
    for termo in ("Enxofre", "Rocha fosfática", "Custo de insumo do MAP"):
        dd = re.search(r"<dt>" + termo + r"</dt><dd>([^<]*)</dd>", glossario).group(1)
        assert not re.search(r"\d", dd), termo
    assert "Não é o custo de nenhuma empresa nem o preço ao produtor" in glossario
    assert '<li id="metodo-insumos"></li>' in html  # o build e o script escrevem as notas do bloco
    secao = html.split('<section class="bloco" id="insumos"', 1)[1].split('<section class="bloco" id="troca"', 1)[0]
    texto = re.sub(r"<[^>]+>", " ", re.sub(r'<p class="kicker">\d\d · ', "", secao))  # a numeração do kicker não é dado
    assert not re.search(r"\d", texto.replace("NCM", "")), "a seção não traz número escrito à mão"


def _pagina(tmp_path):
    ctx = _ctx(DADOS, tmp_path)
    I.gerar(ctx)
    return ctx, (tmp_path / "insumos" / "index.html").read_text(encoding="utf-8")


def test_pagina_insumos_com_cabecalho_de_busca(tmp_path):
    _, pagina = _pagina(tmp_path)
    titulo = re.search(r"<title>([^<]+)</title>", pagina).group(1)
    descricao = re.search(r'<meta name="description" content="([^"]+)">', pagina).group(1)
    assert titulo == I.TITULO and len(titulo) <= 60 and not re.search(r"\d", titulo)
    assert len(descricao) <= 155 and not re.search(r"\d", descricao)
    assert '<link rel="canonical" href="https://radar.graaos.cloud/insumos/">' in pagina
    assert '<meta property="og:url" content="https://radar.graaos.cloud/insumos/">' in pagina and '<meta property="og:title"' in pagina
    ld = json.loads(re.search(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', pagina, re.S).group(1))
    tipos = {x["@type"]: x for x in ld["@graph"]}
    assert tipos["WebPage"]["isPartOf"] == {"@id": "https://radar.graaos.cloud/#website"}
    assert tipos["WebPage"]["url"] == "https://radar.graaos.cloud/insumos/" and tipos["WebPage"]["dateModified"] == "2026-10-01"
    assert [i["item"] for i in tipos["BreadcrumbList"]["itemListElement"]] == ["https://radar.graaos.cloud/", "https://radar.graaos.cloud/insumos/"]
    # assets pelo caminho relativo (o versionador põe o ?v=), links para a seção da home e para os boletins
    assert '<link rel="stylesheet" href="../assets/radar.css">' in pagina and '<link rel="stylesheet" href="../assets/boletim.css">' in pagina
    assert 'href="../#insumos"' in pagina and 'href="../boletim/"' in pagina
    assert "<h1 " in pagina and pagina.count("<h1") == 1
    # sem JavaScript além do tema e do JSON-LD
    scripts = re.findall(r"<script\b[^>]*>", pagina)
    assert scripts == ["<script>", '<script type="application/ld+json">']


def test_pagina_insumos_traz_as_frases_e_tabelas_da_secao(tmp_path):
    _, pagina = _pagina(tmp_path)
    plano = pagina.replace("\xa0", " ")
    for frase in I.frases(DADOS, TODOS).values():
        assert esc(frase).replace("\xa0", " ") in plano, frase
    for html in I.tabelas(DADOS, TODOS).values():
        assert html in pagina
    for nota in DADOS["insumos"]["notas"]:
        assert f"<li>{esc(nota)}</li>" in pagina
    assert "Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet)</span>" in pagina  # rodapé com as duas fontes
    for chave in ("enxofre", "rocha"):
        frase = I.frase_origens(DADOS, chave)
        assert frase and esc(frase) in pagina and frase.endswith(FONTE_COMEX)
    # tabela por ano: o ano parcial com o rótulo dos meses
    ano = int(P[-1][:4])
    assert f"<td>{I.rotulo_ano(DADOS, ano)}</td>" in pagina
