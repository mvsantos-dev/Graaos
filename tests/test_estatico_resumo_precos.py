"""src/estatico/resumo_precos.py: frases de resumo e aria-labels dos gráficos de preços, frete,
custo por nutriente, relação de troca e Brasil x mercado internacional no HTML do build.

A igualdade com o que o script desenha é conferida no navegador (tests/e2e/
test_estatico_resumo_precos.py); aqui ficam as contas, os casos sem dado e as regras do CLAUDE.md
(no porto, não é o preço ao produtor, spread com o preço do Brasil da base e "não é ágio", reais só
pela PTAX, fontes citadas).
"""

import copy
import json
import re
from pathlib import Path

import pytest

from src.estatico import formato as F
from src.estatico import resumo_precos as R
from src.estatico.contexto import Contexto, ErroEstatico

RAIZ = Path(__file__).resolve().parents[1]
INDEX = RAIZ / "dashboard" / "index.html"
DADOS = json.loads((RAIZ / "data" / "processed" / "dashboard.json").read_text(encoding="utf-8"))
P = DADOS["mensal"]["periodos"]
TODOS = list(range(len(P)))
FRASES = ["resumo-precos", "resumo-frete", "resumo-nutrientes", "resumo-troca", "resumo-bm", "resumo-spread", "resumo-brl"]


# --- Dados de mentira: 3 anos, valores redondos ---------------------------------------------------
def _periodos(n=27, inicio=2024):
    return [f"{inicio + i // 12}-{i % 12 + 1:02d}" for i in range(n)]


def _falsos(n=27):
    per = _periodos(n)
    mensal = {"periodos": per}
    for g in ("N", "P", "K", "NPK", "TOTAL"):
        mensal[g] = {"t": [100_000] * n, "fob_musd": [40.0] * n, "cif_musd": [44.0] * n, "frete_musd": [3.0] * n}
    mensal["TOTAL"]["fob_musd"][-13] = 36.0  # um ano antes do último mês: FOB de US$ 360/t

    def prod_nutr(nome, nutriente, teor, custo):
        return {"nome": nome, "nutriente": nutriente, "teores": {nutriente: teor}, "credito_n": False, "t": [50_000] * n,
                "cif": [400.0] * n, "custo": [custo] * n, "custo_brl": [custo * 5] * n, "amostra_pequena": [False] * n}

    nutrientes = {
        "periodos": per, "nutrientes": {"N": "N", "P2O5": "P₂O₅", "K2O": "K₂O"}, "ptax": [5.0] * n, "corte_amostra_t": 10_000,
        "fonte": "Comex Stat/MDIC; BCB/PTAX (SGS 3698, ODbL)", "referencia_credito": "ureia",
        "produtos": {
            "ureia": prod_nutr("Ureia", "N", 46, 1000.0), "sulfato_amonio": prod_nutr("Sulfato de amônio", "N", 21, 1100.0),
            "nitrato_amonio": prod_nutr("Nitrato de amônio", "N", 34, 1200.0), "map": prod_nutr("MAP", "P2O5", 52, 1500.0),
            "dap": prod_nutr("DAP", "P2O5", 46, 1600.0), "tsp": prod_nutr("TSP", "P2O5", 46, 1550.0), "kcl": prod_nutr("KCl", "K2O", 60, 650.0),
        },
    }

    def prod_troca(nome, razao, media):
        return {"nome": nome, "ncm": "0", "descricao": nome, "grupo": "K", "t": [50_000] * n, "cif": [400.0] * n, "razao": [razao] * n,
                "media": media, "media_periodo": [per[0], per[-1]], "n_meses": n}

    troca = {"periodos": per, "soja_fob": [400.0] * n, "soja_t": [1] * n, "kg_saca": 60, "notas": [],
             "produtos": {"kcl": prod_troca("KCl", 1.0, 0.8), "ureia": prod_troca("Ureia", 0.9, 1.0), "map": prod_troca("MAP", 1.5, 1.5)}}

    def prod_bm(nome, serie, bases, fob, cif, ref):
        spread = [(fob - ref) if b == "FOB×FOB" else (cif - ref) for b in [bases[-1]["comparacao"]] * n]
        return {"nome": nome, "descricao": nome, "grupo": "K", "ncms": ["0"], "proxy": nome == "MAP", "serie": serie, "bases": bases,
                "t": [50_000] * n, "fob": [fob] * n, "cif": [cif] * n, "bm": [ref] * n, "spread_usd_t": spread,
                "spread_pct": [100 * s / ref for s in spread], "custo_posto_usd_t": [cif - ref] * n, "cif_brl_t": [cif * 5] * n,
                "amostra_pequena": [False] * n}

    fob_fob = [{"desde": per[0], "base": "FOB Golfo dos EUA", "comparacao": "FOB×FOB"}]
    benchmark = {
        "periodos": per, "ptax": [5.0] * n, "corte_amostra_t": 10_000, "quebras": [], "pink_atualizado_em": "2026-01-05", "fonte": "", "notas": [],
        "produtos": {
            "kcl": prod_bm("KCl", "Potassium chloride", [{"desde": per[0], "base": "FOB Vancouver", "comparacao": "FOB×FOB"},
                                                        {"desde": per[12], "base": "CFR Brasil (granulado)", "comparacao": "CIF×CFR"}], 300.0, 330.0, 300.0),
            "ureia": prod_bm("Ureia", "Urea", [{"desde": per[0], "base": "FOB Oriente Médio", "comparacao": "FOB×FOB"}], 380.0, 420.0, 400.0),
            "map": prod_bm("MAP", "DAP", fob_fob, 800.0, 850.0, 760.0),
            "dap": prod_bm("DAP", "DAP", fob_fob, 760.0, 800.0, 760.0),
            "tsp": prod_bm("TSP", "TSP", [{"desde": per[0], "base": "importação no Golfo dos EUA", "comparacao": "CIF×CFR"}], 650.0, 690.0, 700.0),
        },
    }
    return {"meta": {"periodo": {"inicio": per[0], "fim": per[-1]}}, "mensal": mensal, "nutrientes": nutrientes, "troca": troca, "benchmark": benchmark}


@pytest.fixture
def falsos():
    return _falsos()


# --- Auxiliares -------------------------------------------------------------------------------
@pytest.mark.parametrize("nome, esperado", [("Ureia", "ureia"), ("Sulfato de amônio", "sulfato de amônio"), ("KCl", "KCl"), ("MAP", "MAP"), ("TSP", "TSP")])
def test_nome_na_frase_so_tira_a_maiuscula_de_palavra(nome, esperado):
    assert R.nome_na_frase(nome) == esperado


@pytest.mark.parametrize("v, esperado", [
    (5.26, "5,3% a mais que em set/2025"), (-27.94, "27,9% a menos que em set/2025"),
    (0.04, "praticamente o mesmo que em set/2025"), (-0.04, "praticamente o mesmo que em set/2025"), (None, ""), (float("inf"), ""),
])
def test_diferenca_em_texto_pelo_numero_arredondado(v, esperado):
    assert R.diferenca_em_texto(v, "set/2025") == esperado


def test_por_tonelada_mes_fora_da_serie_e_sem_toneladas(falsos):
    assert R.por_tonelada_mes(falsos, "TOTAL", "fob_musd", -1) is None  # nunca o último mês por índice negativo
    falsos["mensal"]["K"]["t"][3] = 0
    assert R.por_tonelada_mes(falsos, "K", "fob_musd", 3) is None
    assert R.por_tonelada_mes(falsos, "K", "fob_musd", 4) == 400.0


# --- Preços e frete ---------------------------------------------------------------------------
def test_frase_precos_com_fob_cif_e_ano_anterior(falsos):
    per = falsos["mensal"]["periodos"]
    assert R.frase_precos(falsos, "TOTAL", per[-1]) == (
        "Em mar/2026, o preço implícito dos fertilizantes importados foi US$ 400/t FOB (11,1% a mais que em mar/2025) e US$ 440/t CIF, "
        "com US$ 40/t de frete e seguro. Fonte: Comex Stat/MDIC.")
    # primeiro ano: sem comparação; grupo no plural da frase
    assert R.frase_precos(falsos, "NPK", per[0]) == (
        "Em jan/2024, o preço implícito dos compostos (NPK) importados foi US$ 400/t FOB e US$ 440/t CIF, com US$ 40/t de frete e seguro. "
        "Fonte: Comex Stat/MDIC.")


def test_frase_precos_sem_importacao(falsos):
    falsos["mensal"]["N"]["t"][-1] = 0
    assert R.frase_precos(falsos, "N", "2026-03") == "Em mar/2026, não há preço implícito dos nitrogenados importados. Fonte: Comex Stat/MDIC."


def test_frase_frete_com_peso_no_cif(falsos):
    assert R.frase_frete(falsos, "P", "2026-03") == (
        "Em mar/2026, o frete internacional médio dos fosfatados importados foi US$ 30/t, 6,8% do valor CIF; em mar/2025, US$ 30/t e 6,8%. "
        "Fonte: Comex Stat/MDIC.")
    assert R.frase_frete(falsos, "P", "2024-03").endswith("foi US$ 30/t, 6,8% do valor CIF. Fonte: Comex Stat/MDIC.")
    falsos["mensal"]["P"]["frete_musd"][-1] = None
    assert R.frase_frete(falsos, "P", "2026-03") == "Em mar/2026, não há frete por tonelada dos fosfatados importados. Fonte: Comex Stat/MDIC."


def test_precos_e_frete_conferem_com_o_dashboard_json():
    """O último mês do JSON, com a conta refeita aqui (US$ milhões × 10⁶ ÷ toneladas)."""
    m, ate = DADOS["mensal"]["TOTAL"], P[-1]
    fob, cif, frete = (m[c][-1] * 1e6 / m["t"][-1] for c in ("fob_musd", "cif_musd", "frete_musd"))
    precos = R.frase_precos(DADOS, "TOTAL", ate)
    assert f"{F.por_tonelada(fob)} FOB" in precos and f"{F.por_tonelada(cif)} CIF" in precos and F.rotulo_mes(ate) in precos
    assert f"foi {F.por_tonelada(frete)}, {F.pct(100 * m['frete_musd'][-1] / m['cif_musd'][-1])} do valor CIF" in R.frase_frete(DADOS, "TOTAL", ate)


# --- Custo por nutriente --------------------------------------------------------------------------
def test_frase_nutrientes_em_dolares_e_em_reais(falsos):
    assert R.frase_nutrientes(falsos, "TOTAL", "2026-03") == (
        "Custo por tonelada de nutriente no porto em mar/2026: ureia US$ 1.000/t de N; MAP US$ 1.500/t de P₂O₅; KCl US$ 650/t de K₂O. "
        "Não é o preço ao produtor. Fonte: Comex Stat/MDIC.")
    assert R.frase_nutrientes(falsos, "K", "2026-03", "brl") == (
        "Custo por tonelada de nutriente no porto em mar/2026, em reais pela PTAX venda média do mês: KCl R$ 3.250/t de K₂O. "
        "Não é o preço ao produtor. Fonte: Comex Stat/MDIC; BCB/PTAX.")


def test_frase_nutrientes_diz_quem_ficou_fora(falsos):
    prods = falsos["nutrientes"]["produtos"]
    prods["sulfato_amonio"]["t"][-1] = 0
    prods["nitrato_amonio"]["t"][-1] = 4_200
    prods["nitrato_amonio"]["amostra_pequena"][-1] = True
    prods["ureia"]["custo"][-1] = None
    assert R.frase_nutrientes(falsos, "N", "2026-03") == (
        "Custo por tonelada de nutriente no porto em mar/2026: ureia sem custo no mês; sulfato de amônio sem importação no mês; "
        "nitrato de amônio fora do gráfico (amostra pequena, 4,2\u00a0mil t). Não é o preço ao produtor. Fonte: Comex Stat/MDIC.")
    # produto que o bloco não traz não entra (como no script)
    del prods["dap"]
    assert "DAP" not in R.frase_nutrientes(falsos, "P", "2026-03")


# --- Relação de troca -------------------------------------------------------------------------
def test_frase_troca_contra_a_media_historica(falsos):
    assert R.frase_troca(falsos, "TOTAL", "2026-03") == (
        "Em mar/2026, no porto, 1 t de KCl custou 1,00 t de soja, 25,0% acima da média histórica (0,80 t); "
        "1 t de ureia, 0,90 t, 10,0% abaixo da média (1,00 t); 1 t de MAP, 1,50 t, igual à média (1,50 t). "
        "Não é o preço ao produtor. Fonte: Comex Stat/MDIC.")
    # um produto por grupo; NPK mostra os três
    assert R.frase_troca(falsos, "N", "2026-03").startswith("Em mar/2026, no porto, 1 t de ureia custou 0,90 t de soja, 10,0% abaixo da média histórica")
    assert R.frase_troca(falsos, "NPK", "2026-03") == R.frase_troca(falsos, "TOTAL", "2026-03")


def test_frase_troca_sem_relacao_no_mes(falsos):
    tr = falsos["troca"]["produtos"]
    tr["kcl"]["razao"][-1] = None
    tr["kcl"]["t"][-1] = 0
    tr["ureia"]["razao"][-1] = None
    assert R.frase_troca(falsos, "TOTAL", "2026-03") == (
        "Em mar/2026, no porto, KCl ficou sem relação de troca no mês (sem importação); ureia ficou sem relação de troca no mês "
        "(sem preço da soja); 1 t de MAP custou 1,50 t de soja, igual à média histórica (1,50 t). Não é o preço ao produtor. Fonte: Comex Stat/MDIC.")


# --- Brasil x mercado internacional ---------------------------------------------------------------
def test_benchmark_usa_o_preco_do_brasil_da_base(falsos):
    todos = list(range(27))
    kcl = R.frases_benchmark(falsos, "kcl", todos)
    assert kcl["bm"] == (
        "Em mar/2026, o Brasil importou KCl a US$ 300/t FOB e US$ 330/t CIF; o benchmark do Banco Mundial (Potassium chloride), na base "
        "CFR Brasil (granulado), foi de US$ 300/t. Na base comparável (CIF×CFR), o preço do Brasil, de US$ 330/t CIF, ficou 10,0% acima do "
        "benchmark. Não é ágio: o benchmark é de outro lugar e de outro momento de contrato. Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet).")
    assert kcl["spread"] == (
        "Spread de KCl na base comparável (CIF×CFR) em mar/2026: +10,0% (+US$ 30/t), com o preço do Brasil a US$ 330/t CIF e o benchmark a "
        "US$ 300/t. No período, o spread ficou acima de zero em 27 de 27 meses comparáveis. Não é ágio: o benchmark é de outro lugar e de "
        "outro momento de contrato. Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet).")
    assert kcl["brl"] == ("Em mar/2026, o CIF de KCl em reais, pela PTAX venda média do mês (R$ 5,0000), foi R$ 1.650/t, praticamente o mesmo "
                          "que em mar/2025. Fonte: Comex Stat/MDIC; BCB/PTAX.")
    # base FOB: o preço do Brasil é o FOB; base antiga do KCl (até o 12º mês) também
    ureia = R.frases_benchmark(falsos, "ureia", todos)
    assert "o preço do Brasil, de US$ 380/t FOB, ficou 5,0% abaixo do benchmark" in ureia["bm"]
    assert "Spread de ureia na base comparável (FOB×FOB) em mar/2026: −5,0% (−US$ 20/t), com o preço do Brasil a US$ 380/t FOB" in ureia["spread"]
    assert "acima de zero em 0 de 27 meses comparáveis" in ureia["spread"]
    assert "na base FOB Vancouver" in R.frases_benchmark(falsos, "kcl", list(range(12)))["bm"]
    # MAP: o DAP como referência
    assert "o benchmark do Banco Mundial (DAP, a referência do MAP), na base FOB Golfo dos EUA" in R.frases_benchmark(falsos, "map", todos)["bm"]
    # spread que arredonda a zero
    dap = R.frases_benchmark(falsos, "dap", todos)
    assert "ficou praticamente igual ao benchmark" in dap["bm"] and ": 0,0% (US$ 0/t)" in dap["spread"]


def test_spread_acima_de_zero_pelo_numero_arredondado(falsos):
    """Mês que aparece como 0,0% não conta como acima de zero (o sinal sai do número arredondado)."""
    prod = falsos["benchmark"]["produtos"]["dap"]
    prod["spread_pct"][0], prod["spread_pct"][1], prod["spread_pct"][2] = 0.04, 0.05, -0.04
    assert "acima de zero em 1 de 27 meses comparáveis" in R.frases_benchmark(falsos, "dap", list(range(27)))["spread"]


def test_benchmark_com_ultimo_mes_fora_da_comparacao(falsos):
    prod = falsos["benchmark"]["produtos"]["dap"]
    prod["t"][-1], prod["amostra_pequena"][-1] = 57, True
    frases = R.frases_benchmark(falsos, "dap", list(range(27)))
    aviso = "Em mar/2026, a importação de DAP foi de 57 t, menos de 10.000 t: amostra pequena, fora da comparação."
    assert frases["bm"].startswith(f"{aviso} Em fev/2026, o último mês comparável do período, o Brasil importou DAP a US$ 760/t FOB")
    assert frases["spread"].startswith(f"{aviso} Spread de DAP na base comparável (FOB×FOB) em fev/2026, o último mês comparável do período: ")
    assert "em 0 de 26 meses comparáveis" in frases["spread"]
    assert frases["brl"].startswith("Em mar/2026, a importação de DAP foi de 57 t, menos de 10.000 t: amostra pequena, fora do gráfico. "
                                    "Em fev/2026, o último mês do período no gráfico, o CIF de DAP em reais")
    # sem importação no último mês e sem benchmark
    prod["t"][-1], prod["amostra_pequena"][-1] = 0, False
    prod["spread_pct"][-1] = None
    assert R.frases_benchmark(falsos, "dap", list(range(27)))["bm"].startswith("Em mar/2026, não houve importação de DAP. Em fev/2026")
    prod["t"][-1] = 30_000
    assert R.frases_benchmark(falsos, "dap", list(range(27)))["bm"].startswith(
        "Em mar/2026, não há benchmark do Banco Mundial para DAP. Em fev/2026, o último mês comparável do período")


def test_benchmark_sem_mes_comparavel_fica_sem_frase(falsos):
    """Como o script, que troca os três gráficos por um aviso: nenhuma frase."""
    prod = falsos["benchmark"]["produtos"]["dap"]
    prod["amostra_pequena"] = [True] * 27
    assert R.frases_benchmark(falsos, "dap", list(range(20, 27))) == {"bm": "", "spread": "", "brl": ""}
    rotulos = R.rotulos_benchmark(falsos, "dap", list(range(20, 27)))
    assert rotulos["bm"].endswith("A tabela abaixo traz os valores.")


def test_produto_padrao_do_benchmark_segue_os_chips(falsos):
    assert R.produtos_bm(falsos, "TOTAL") == ["kcl", "ureia", "map", "dap", "tsp"]
    assert R.produtos_bm(falsos, "P") == ["map", "dap", "tsp"]
    assert R.produtos_bm(falsos, "NPK") == R.ORDEM_BM
    del falsos["benchmark"]["produtos"]["kcl"]
    assert R.produtos_bm(falsos, "K") == []
    assert R.produtos_bm({}, "TOTAL") == []


# --- Regras do CLAUDE.md em todas as frases do JSON versionado ------------------------------------
def _todas():
    for g in ("TOTAL", "N", "P", "K", "NPK"):
        for ate in (P[-1], P[0], "2024-04", "2026-05"):
            yield "precos", R.frase_precos(DADOS, g, ate)
            yield "frete", R.frase_frete(DADOS, g, ate)
            yield "nutrientes", R.frase_nutrientes(DADOS, g, ate)
            yield "nutrientes_brl", R.frase_nutrientes(DADOS, g, ate, "brl")
            yield "troca", R.frase_troca(DADOS, g, ate)
    for chave in R.ORDEM_BM:
        for indices in (TODOS, TODOS[:60], TODOS[-5:]):
            for parte, frase in R.frases_benchmark(DADOS, chave, indices).items():
                yield parte, frase


def test_frases_seguem_as_regras_das_saidas_publicas():
    for tipo, frase in _todas():
        if not frase:
            continue
        assert re.search(r"Fonte: Comex Stat/MDIC(; Banco Mundial \(Pink Sheet\))?(; BCB/PTAX)?\.$", frase), (tipo, frase)
        if tipo in ("nutrientes", "nutrientes_brl", "troca"):
            assert "no porto" in frase and "Não é o preço ao produtor." in frase, frase
        if tipo in ("bm", "spread"):
            assert "Não é ágio: o benchmark é de outro lugar e de outro momento de contrato." in frase, frase
            assert "Banco Mundial (Pink Sheet)" in frase and "PTAX" not in frase, frase
            assert re.search(r"preço do Brasil(, de| a) US\$ [\d.]+/t (FOB|CIF)", frase), frase  # spread com o preço da base
        if "R$" in frase:
            assert "PTAX venda média do mês" in frase and frase.endswith("BCB/PTAX."), frase
        if tipo == "troca":
            assert "R$" not in frase and "PTAX" not in frase  # nunca troca em R$
        assert "ágio" not in frase.replace("Não é ágio", ""), frase
        assert "−0,0" not in frase and "-0" not in frase and "NaN" not in frase and "None" not in frase and "undefined" not in frase, frase


# --- gerar(): o index.html do build ---------------------------------------------------------------
def _ctx(dados, tmp_path):
    return Contexto(site=tmp_path, dados=dados, boletim={}, html=INDEX.read_text(encoding="utf-8"))


def _conteudo(html, id_):
    return re.search(r'id="' + id_ + r'">([^<]*)</p>', html).group(1)


def _rotulo(html, id_):
    tag = re.search(r'<canvas id="' + id_ + r'"[^>]*>', html).group(0)
    m = re.search(r'aria-label="([^"]*)"', tag)
    return m and m.group(1)


def test_gerar_preenche_a_visao_padrao(tmp_path):
    ctx = _ctx(DADOS, tmp_path)
    R.gerar(ctx)
    ate = P[-1]
    esperado = {
        "resumo-precos": R.frase_precos(DADOS, "TOTAL", ate), "resumo-frete": R.frase_frete(DADOS, "TOTAL", ate),
        "resumo-nutrientes": R.frase_nutrientes(DADOS, "TOTAL", ate), "resumo-troca": R.frase_troca(DADOS, "TOTAL", ate),
        **{f"resumo-{k}": v for k, v in R.frases_benchmark(DADOS, "kcl", TODOS).items()},
    }
    for id_, frase in esperado.items():
        assert frase and _conteudo(ctx.html, id_) == R.esc(frase), id_
    assert _rotulo(ctx.html, "grafico-precos") == R.esc(R.rotulo_precos(DADOS, "TOTAL", TODOS))
    assert _rotulo(ctx.html, "grafico-nutrientes") == R.esc(R.rotulo_nutrientes(DADOS, "TOTAL", TODOS))
    assert _rotulo(ctx.html, "grafico-troca") == R.esc(R.rotulo_troca(DADOS, "TOTAL", TODOS))
    for parte, rotulo in R.rotulos_benchmark(DADOS, "kcl", TODOS).items():
        assert _rotulo(ctx.html, f"grafico-{parte}") == R.esc(rotulo)
    # a frase de cada gráfico logo depois da nota do cartão (ou do subtítulo, no primeiro do benchmark)
    for nota, frase in (("nota-precos", "resumo-precos"), ("nota-frete", "resumo-frete"), ("nota-nutrientes", "resumo-nutrientes"),
                        ("nota-spread", "resumo-spread"), ("nota-brl", "resumo-brl"), ("nota-troca", "resumo-troca")):
        assert re.search(r'id="' + nota + r'"></p>\s*<p class="resumo-grafico" id="' + frase + '">', ctx.html), frase
    assert re.search(r'Preço do Brasil x benchmark \(US\$/t\)</h3>\s*<p class="resumo-grafico" id="resumo-bm">', ctx.html)


def test_gerar_sem_os_blocos_deixa_as_secoes_como_o_script(tmp_path):
    dados = copy.deepcopy(DADOS)
    for bloco in ("nutrientes", "troca", "benchmark"):
        del dados[bloco]
    ctx = _ctx(dados, tmp_path)
    R.gerar(ctx)
    assert _conteudo(ctx.html, "resumo-precos") and _conteudo(ctx.html, "resumo-frete")
    for parte in ("nutrientes", "troca", "bm", "spread", "brl"):
        assert _conteudo(ctx.html, f"resumo-{parte}") == ""
        assert _rotulo(ctx.html, f"grafico-{parte}") is None


def test_gerar_falha_se_o_index_perdeu_um_ponto_de_encaixe(tmp_path):
    ctx = _ctx(DADOS, tmp_path)
    ctx.html = ctx.html.replace('<p class="resumo-grafico" id="resumo-frete"></p>', "")
    with pytest.raises(ErroEstatico, match="resumo-frete"):
        R.gerar(ctx)


def test_index_tem_um_ponto_de_encaixe_por_grafico_e_o_script_escreve_neles():
    html = INDEX.read_text(encoding="utf-8")
    for id_ in FRASES:
        assert html.count(f'id="{id_}"') == 1, id_
        assert f'texto("{id_}", ' in html, id_  # o script reescreve a frase para o filtro escolhido
    for funcao in ("frasePrecos", "fraseFrete", "fraseNutrientes", "fraseTroca", "frasesBenchmark", "nomeNaFrase", "diferencaEmTexto"):
        assert f"function {funcao}(" in html or f"const {funcao} = " in html, funcao
