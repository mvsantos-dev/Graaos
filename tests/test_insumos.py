"""Insumos do fósforo (src/insumos.py): séries de enxofre e rocha, rocha x Pink Sheet e custo de
insumo por tonelada de MAP. Séries sintéticas para as fórmulas e os dados versionados para o
formato do bloco e para provar que nada mais muda. Sem rede."""

import json
import re

import pandas as pd
import pytest

from src import benchmark, comparacao, config, ingest, insumos, transform
from tests.test_comparacao import importacao

KAZ = ("153", "Cazaquistão")
EUA = ("249", "Estados Unidos")
PERU = ("589", "Peru")
MARROCOS = ("474", "Marrocos")
EGITO = ("240", "Egito")
ENXOFRE, ROCHA = "25030010", "25101010"


def imp(ano, mes, ncm, t, fob, frete, pais=KAZ):
    """Uma linha no formato de ingest.ler_insumos (kg e US$)."""
    return {
        "ano": ano, "mes": mes, "co_ncm": ncm, "co_pais": pais[0], "no_pais": pais[1], "sg_uf": "PR",
        "no_uf": "Paraná", "co_via": "01", "no_via": "MARITIMA", "co_urf": "0917800", "no_urf": "PORTO DE PARANAGUA",
        "vl_fob": fob, "kg_liquido": int(t * 1000), "vl_cif": fob + frete, "vl_frete": frete, "vl_seguro": 0,
    }


def rocha_pink(valores):
    """{mes: valor da rocha} -> DataFrame no formato de benchmark.ler_pink()."""
    meses = sorted(valores)
    return pd.DataFrame({"mes": meses, **{s: [None] * len(meses) for s in ["ureia", "dap", "tsp", "kcl"]}, "rocha_fosfatica": [valores[m] for m in meses]})


def meses(*periodos):
    return pd.DataFrame([{"ano": int(p[:4]), "mes": int(p[5:])} for p in periodos])


@pytest.fixture
def cortes(monkeypatch):
    monkeypatch.setattr(config, "INSUMOS_CORTE_AMOSTRA_T", {"enxofre": 50_000, "rocha": 40_000})


@pytest.fixture
def tres_meses():
    """Insumos ingeridos de 2025-01 a 2025-03 (2025-02 sem enxofre)."""
    return insumos.preparar(
        pd.DataFrame(
            [
                imp(2025, 1, ENXOFRE, 100_000, 15_000_000, 1_000_000),
                imp(2025, 1, "25030090", 20_000, 2_000_000, 400_000, pais=EUA),  # enxofre: 120 mil t
                imp(2025, 1, ROCHA, 60_000, 6_000_000, 1_200_000, pais=PERU),  # FOB 100, CIF 120
                imp(2025, 2, ROCHA, 35_000, 3_500_000, 700_000, pais=PERU),  # amostra pequena
                imp(2025, 3, ENXOFRE, 30_000, 6_000_000, 600_000),  # amostra pequena
                imp(2025, 3, "25102010", 50_000, 4_500_000, 1_000_000, pais=MARROCOS),
            ]
        )
    )


def _linha(df, produto, periodo):
    return df[(df["produto"] == produto) & (df["periodo"] == periodo)].iloc[0]


# --- Séries mensais --------------------------------------------------------------------------


def test_preparar_recusa_ncm_fora_do_enxofre_e_da_rocha():
    with pytest.raises(ValueError, match="31042090"):
        insumos.preparar(pd.DataFrame([imp(2025, 1, ENXOFRE, 1, 1, 0), imp(2025, 1, "31042090", 1, 1, 0)]))
    df = insumos.preparar(pd.DataFrame([imp(2025, 1, ENXOFRE, 2.5, 100, 0), imp(2025, 1, "25102090", 1, 1, 0)]))
    assert df["produto"].tolist() == ["enxofre", "rocha"] and df["toneladas"].iloc[0] == pytest.approx(2.5)


def test_ncms_monitorados_por_insumo():
    ncms = insumos.ncms_por_produto()
    assert ncms["enxofre"] == ["25030010", "25030090"]
    assert {n[:6] for n in ncms["rocha"]} == {"251010", "251020"}
    assert sorted(ncms["enxofre"] + ncms["rocha"]) == sorted(ingest.carregar_ncms(config.NCM_INSUMOS_CSV)["ncm"])


def test_mensal_preco_ponderado_amostra_pequena_e_meses_sem_dados(cortes, tres_meses):
    pink = rocha_pink({"2025-01": 125.0, "2025-02": 110.0, "2025-03": None, "2025-04": 130.0})
    df = insumos.mensal(tres_meses, meses("2025-01", "2025-02", "2025-03", "2025-04"), pink)
    assert list(df.columns) == insumos.COLUNAS and len(df) == 8
    assert df["produto"].tolist()[:2] == ["enxofre", "rocha"]

    e = _linha(df, "enxofre", "2025-01")  # média ponderada pelo peso das duas cargas
    assert e["toneladas"] == pytest.approx(120_000) and e["ncms"] == "25030010|25030090"
    assert e["preco_fob_usd_t"] == pytest.approx(17_000_000 / 120_000)
    assert e["preco_cif_usd_t"] == pytest.approx(18_400_000 / 120_000)
    assert e["frete_usd_t"] == pytest.approx(1_400_000 / 120_000)
    assert not e["amostra_pequena"] and pd.isna(e["benchmark_usd_t"]) and pd.isna(e["spread_usd_t"]) and pd.isna(e["serie_bm"])

    sem = _linha(df, "enxofre", "2025-02")  # dentro do período ingerido, sem importação: zero
    assert sem["toneladas"] == 0 and sem["vl_cif"] == 0 and pd.isna(sem["preco_cif_usd_t"]) and not sem["amostra_pequena"]
    assert _linha(df, "enxofre", "2025-03")["amostra_pequena"]  # 30 mil t < 50 mil t

    r = _linha(df, "rocha", "2025-01")  # FOB×FOB contra a Pink Sheet
    assert (r["serie_bm"], r["base_bm"], r["comparacao"]) == ("Phosphate rock", "FOB Norte da África", "FOB×FOB")
    assert r["preco_fob_usd_t"] == pytest.approx(100) and r["benchmark_usd_t"] == 125
    assert r["spread_usd_t"] == pytest.approx(-25) and r["spread_pct"] == pytest.approx(-20)
    pequena = _linha(df, "rocha", "2025-02")  # 35 mil t < 40 mil t: sem spread, mesmo com benchmark
    assert pequena["amostra_pequena"] and pequena["benchmark_usd_t"] == 110 and pd.isna(pequena["spread_usd_t"])
    assert pd.isna(pequena["spread_pct"])
    sem_bm = _linha(df, "rocha", "2025-03")
    assert not sem_bm["amostra_pequena"] and pd.isna(sem_bm["benchmark_usd_t"]) and pd.isna(sem_bm["spread_usd_t"])

    fora = df[df["periodo"] == "2025-04"]  # depois do último mês ingerido: vazio, não zero
    assert fora["toneladas"].isna().all() and fora["preco_cif_usd_t"].isna().all() and not fora["amostra_pequena"].any()
    assert pd.isna(_linha(df, "rocha", "2025-04")["spread_usd_t"])


def test_mensal_sem_pink_sheet_deixa_o_benchmark_vazio(tres_meses):
    df = insumos.mensal(tres_meses, meses("2025-01"), None)
    assert df["benchmark_usd_t"].isna().all() and df["spread_usd_t"].isna().all()
    assert _linha(df, "rocha", "2025-01")["preco_fob_usd_t"] == pytest.approx(100)


def _base_map():
    """MAP importado: 2025-01 com 100 mil t (CIF 500), 2025-02 sem, 2025-03 com 5 mil t (amostra pequena)."""
    return pd.DataFrame(
        [
            importacao(2025, 1, "31054000", 100_000, 45_000_000, 50_000_000, grupo="P"),
            importacao(2025, 1, "31042090", 200_000, 60_000_000, 70_000_000),
            importacao(2025, 2, "31042090", 200_000, 60_000_000, 70_000_000),
            importacao(2025, 3, "31054000", 5_000, 2_800_000, 3_000_000, grupo="P"),
        ]
    )


def test_custo_de_insumo_por_tonelada_de_map_e_razao(cortes, tres_meses, monkeypatch):
    base = _base_map()
    tabela = insumos.mensal(tres_meses, base, rocha_pink({"2025-01": 125.0}))
    df = insumos.custo_map(tabela, base).set_index("periodo")
    assert list(df.reset_index().columns) == insumos.COLUNAS_CUSTO and list(df.index) == ["2025-01", "2025-02", "2025-03"]
    jan = df.loc["2025-01"]
    custo = 18_400_000 / 120_000 * config.INSUMOS_COEF_ENXOFRE + 120 * config.INSUMOS_COEF_ROCHA
    assert (jan["coef_enxofre"], jan["coef_rocha"]) == (config.INSUMOS_COEF_ENXOFRE, config.INSUMOS_COEF_ROCHA)
    assert jan["custo_enxofre_usd_t"] == pytest.approx(18_400_000 / 120_000 * config.INSUMOS_COEF_ENXOFRE)
    assert jan["custo_insumo_usd_t"] == pytest.approx(custo)
    assert jan["cif_map_usd_t"] == pytest.approx(500) and jan["razao_custo_cif_map"] == pytest.approx(custo / 500)
    assert not jan["amostra_pequena"]
    fev = df.loc["2025-02"]  # sem enxofre e sem MAP no mês: custo e razão vazios
    assert pd.isna(fev["custo_insumo_usd_t"]) and pd.isna(fev["cif_map_usd_t"]) and pd.isna(fev["razao_custo_cif_map"])
    assert fev["amostra_pequena_rocha"] and fev["amostra_pequena"] and fev["toneladas_map"] == 0
    mar = df.loc["2025-03"]  # enxofre e MAP com amostra pequena: o custo existe, mas fica marcado
    assert mar["amostra_pequena_enxofre"] and mar["amostra_pequena_map"] and not mar["amostra_pequena_rocha"]
    assert mar["amostra_pequena"] and mar["cif_map_usd_t"] == pytest.approx(600) and pd.notna(mar["razao_custo_cif_map"])

    # os coeficientes vêm do config.py
    monkeypatch.setattr(config, "INSUMOS_COEF_ENXOFRE", 0.5)
    monkeypatch.setattr(config, "INSUMOS_COEF_ROCHA", 2.0)
    outro = insumos.custo_map(tabela, base).set_index("periodo").loc["2025-01"]
    assert outro["custo_insumo_usd_t"] == pytest.approx(18_400_000 / 120_000 * 0.5 + 120 * 2.0)


def test_origens_com_share_variacao_nos_mesmos_meses_e_outros(monkeypatch):
    monkeypatch.setattr(insumos, "TOP_ORIGENS", 2)
    dados = insumos.preparar(
        pd.DataFrame(
            [
                imp(2024, 1, ENXOFRE, 100, 1, 0, pais=KAZ),
                imp(2024, 2, ENXOFRE, 100, 1, 0, pais=KAZ),
                imp(2024, 3, ENXOFRE, 1_000, 1, 0, pais=KAZ),  # fora da base de 2025 (só jan-fev)
                imp(2024, 1, ENXOFRE, 50, 1, 0, pais=EUA),
                imp(2024, 1, ENXOFRE, 40, 1, 0, pais=("198", "Coveite (Kuweit)")),  # deixa de importar
                imp(2025, 1, ENXOFRE, 300, 1, 0, pais=KAZ),
                imp(2025, 2, ENXOFRE, 100, 1, 0, pais=EUA),
                imp(2025, 2, ENXOFRE, 100, 1, 0, pais=("361", "Índia")),
                imp(2025, 1, ROCHA, 500, 1, 0, pais=PERU),
            ]
        )
    )
    saida = insumos.origens(dados, transform._num)
    assert set(saida) == {"2024", "2025"}
    assert all(linha[4] is None for linha in saida["2024"]["enxofre"])  # sem 2023: sem variação
    assert saida["2024"]["rocha"] == []
    e25 = saida["2025"]["enxofre"]
    assert e25[0] == ["153", "Cazaquistão", 300, 60.0, 50.0]  # 300 t contra 200 t em jan-fev/2024
    # empate em toneladas: pelo código do país
    assert e25[1] == ["249", "Estados Unidos", 100, 20.0, 100.0]
    # "Outros": a Índia (nova) e o Coveite (deixou de importar, entra com zero)
    assert e25[2] == [None, "Outros", 100, 20.0, 150.0]
    assert sum(linha[3] for linha in e25) == pytest.approx(100)
    assert saida["2025"]["rocha"] == [["589", "Peru", 500, 100.0, None]]  # sem rocha em jan-fev/2024


def test_notas_tiram_numeros_do_config(monkeypatch):
    notas = " ".join(insumos.notas())
    for termo in ("no porto", "não o custo de nenhuma empresa", "aproximação técnica", "Não é ágio",
                  "outro lugar e de outro momento de contrato", "não são o preço ao produtor", "Pink Sheet", "FOB×FOB"):
        assert termo in notas, termo
    assert "0,45" in notas and "1,7" in notas and "30 mil t" in notas and "10 mil t de MAP" in notas
    # nenhum número escrito à mão: tirando os do config e o NCM do MAP, não sobra dígito
    resto = notas
    numeros = [insumos._decimal(config.INSUMOS_COEF_ENXOFRE), insumos._decimal(config.INSUMOS_COEF_ROCHA), *insumos.MAP["ncms"]]
    numeros += [insumos._toneladas(t) for t in [*config.INSUMOS_CORTE_AMOSTRA_T.values(), comparacao.CORTE_AMOSTRA_T]]
    for numero in sorted(set(numeros), key=len, reverse=True):
        resto = resto.replace(numero, "")
    assert not re.search(r"\d", resto), resto
    # e os números mudam com o config
    monkeypatch.setattr(config, "INSUMOS_COEF_ENXOFRE", 0.37)
    monkeypatch.setattr(config, "INSUMOS_COEF_ROCHA", 1.9)
    monkeypatch.setattr(config, "INSUMOS_CORTE_AMOSTRA_T", {"enxofre": 25_000, "rocha": 42_500})
    notas = " ".join(insumos.notas())
    assert "× 0,37" in notas and "× 1,9" in notas and "25 mil t de enxofre" in notas and "42.500 t de rocha" in notas


# --- transform: CSVs e bloco do dashboard.json -------------------------------------------------

CHAVES_PRODUTO = {"nome", "descricao", "ncms", "corte_amostra_t", "t", "fob_musd", "cif_musd", "frete_musd", "fob", "cif", "frete", "amostra_pequena"}
SERIES_PRODUTO = CHAVES_PRODUTO - {"nome", "descricao", "ncms", "corte_amostra_t"}


def _gerar(destino, base, base_insumos=None, pink=None):
    return transform.gerar(base, destino, None, pink, None, {"atualizado_em": "2026-10-02"}, base_insumos)


def _arquivos(pasta):
    return {p.name: p.read_bytes() for p in sorted(pasta.iterdir())}


def test_transform_grava_csvs_e_bloco_deterministicos_sem_mudar_o_resto(tmp_path):
    base = _base_map()
    bruto = pd.DataFrame([imp(2025, 1, ENXOFRE, 100_000, 15_000_000, 1_000_000), imp(2025, 2, ROCHA, 60_000, 6_000_000, 1_200_000, pais=PERU)])
    pink = rocha_pink({"2025-01": 125.0, "2025-02": 110.0, "2025-03": 120.0})
    pink["kcl"] = 300.0
    _gerar(tmp_path / "a", base, bruto, pink)
    _gerar(tmp_path / "b", base, bruto, pink)
    _gerar(tmp_path / "sem", base, None, pink)
    a, b, sem = _arquivos(tmp_path / "a"), _arquivos(tmp_path / "b"), _arquivos(tmp_path / "sem")
    assert a == b  # determinístico
    novos = {"insumos_mensal.csv", "custo_insumo_map_mensal.csv"}
    assert set(a) - set(sem) == novos
    for nome in sem:  # nada do que já existia muda com os insumos
        if nome != "dashboard.json":
            assert a[nome] == sem[nome], nome
    painel, painel_sem = json.loads(a["dashboard.json"]), json.loads(sem["dashboard.json"])
    assert "insumos" not in painel_sem and {k: v for k, v in painel.items() if k != "insumos"} == painel_sem
    assert list(painel)[-1] == "insumos"  # no fim: o texto dos blocos antigos fica igual
    assert a["dashboard.json"].startswith(sem["dashboard.json"].rstrip(b"\n")[:-1])

    csv = pd.read_csv(tmp_path / "a" / "insumos_mensal.csv", dtype={"ncms": str})
    assert list(csv.columns) == insumos.COLUNAS and len(csv) == 3 * len(insumos.PRODUTOS)
    custo = pd.read_csv(tmp_path / "a" / "custo_insumo_map_mensal.csv")
    assert list(custo.columns) == insumos.COLUNAS_CUSTO and custo["periodo"].tolist() == ["2025-01", "2025-02", "2025-03"]
    assert custo["razao_custo_cif_map"].isna().all()  # nenhum mês com enxofre, rocha e MAP juntos

    bloco = painel["insumos"]
    assert set(bloco) == {"periodos", "fonte", "produtos", "origens", "custo_map", "notas"}
    assert bloco["periodos"] == painel["mensal"]["periodos"] == ["2025-01", "2025-02", "2025-03"]
    assert bloco["fonte"] == "Comex Stat/MDIC; Banco Mundial (Pink Sheet)"
    assert set(bloco["produtos"]) == {"enxofre", "rocha"}
    for chave, p in bloco["produtos"].items():
        assert CHAVES_PRODUTO <= set(p) and all(len(p[s]) == 3 for s in SERIES_PRODUTO), chave
    e, r = bloco["produtos"]["enxofre"], bloco["produtos"]["rocha"]
    assert e["t"] == [100_000, 0, None] and e["cif"] == [160.0, None, None] and e["cif_musd"] == [16.0, 0.0, None]
    assert r["fob"] == [None, 100.0, None] and r["frete"] == [None, 20.0, None]
    bm = r["benchmark"]
    assert (bm["serie"], bm["base"], bm["comparacao"]) == ("Phosphate rock", "FOB Norte da África", "FOB×FOB")
    assert bm["bm"] == [125.0, 110.0, 120.0] and bm["spread_usd_t"] == [None, -10.0, None]
    assert bm["spread_pct"][1] == pytest.approx(-100 / 11, abs=1e-6) and bm["pink_atualizado_em"] == "2026-10-02"
    assert bloco["custo_map"]["coef_enxofre"] == config.INSUMOS_COEF_ENXOFRE and bloco["custo_map"]["coef_rocha"] == config.INSUMOS_COEF_ROCHA
    assert all(len(bloco["custo_map"][s]) == 3 for s in ("custo", "cif_map", "razao", "amostra_pequena"))
    assert bloco["custo_map"]["cif_map"] == [500.0, None, 600.0] and bloco["custo_map"]["amostra_pequena"] == [False, False, True]
    assert bloco["origens"]["2025"]["enxofre"] == [["153", "Cazaquistão", 100_000, 100.0, None]]
    assert bloco["notas"] == insumos.notas()


def test_transform_sem_pink_sheet_tira_o_banco_mundial_da_fonte(tmp_path):
    bruto = pd.DataFrame([imp(2025, 1, ROCHA, 60_000, 6_000_000, 1_200_000)])
    _gerar(tmp_path, _base_map(), bruto, None)
    bloco = json.loads((tmp_path / "dashboard.json").read_text(encoding="utf-8"))["insumos"]
    assert bloco["fonte"] == "Comex Stat/MDIC" and set(bloco["produtos"]["rocha"]["benchmark"]["bm"]) == {None}


def test_transform_sem_insumos_nao_cria_o_bloco(tmp_path):
    _gerar(tmp_path, _base_map(), pd.DataFrame(columns=["ano", *ingest.COLUNAS_RAW]))
    assert not (tmp_path / "insumos_mensal.csv").exists() and not (tmp_path / "custo_insumo_map_mensal.csv").exists()
    assert "insumos" not in json.loads((tmp_path / "dashboard.json").read_text(encoding="utf-8"))


def test_arredonda_a_razao_no_csv_sem_menos_zero():
    df = transform._arredondar(pd.DataFrame({"razao_custo_cif_map": [0.123456789, -0.00001]}))
    assert df.to_csv(index=False).splitlines()[1:] == ["0.1235", "0.0"]


# --- Dados versionados ---------------------------------------------------------------------------

_SEM_DADOS = not (config.PROCESSED_DIR / "dashboard.json").exists() or not any(config.RAW_INSUMOS_DIR.glob(f"ano=*/{config.RAW_ARQUIVO}"))
dados_versionados = pytest.mark.skipif(_SEM_DADOS, reason="sem dashboard.json ou sem data/raw_insumos")


def _painel():
    return json.loads((config.PROCESSED_DIR / "dashboard.json").read_text(encoding="utf-8"))


@dados_versionados
def test_bloco_versionado_no_formato_combinado():
    painel = _painel()
    bloco = painel["insumos"]
    n = len(painel["mensal"]["periodos"])
    assert bloco["periodos"] == painel["mensal"]["periodos"]
    assert bloco["fonte"] == "Comex Stat/MDIC; Banco Mundial (Pink Sheet)"
    ncms = insumos.ncms_por_produto()
    for chave, p in bloco["produtos"].items():
        assert CHAVES_PRODUTO <= set(p) and all(len(p[s]) == n for s in SERIES_PRODUTO), chave
        assert p["ncms"] == ncms[chave] and p["corte_amostra_t"] == config.INSUMOS_CORTE_AMOSTRA_T[chave]
        assert all(isinstance(v, int) for v in p["t"] if v is not None)
        for t, cif, cif_musd, pequena in zip(p["t"], p["cif"], p["cif_musd"], p["amostra_pequena"]):
            # t e cif_musd vêm arredondados (t inteiro, US$ mi com 3 casas): na fronteira do corte e
            # em mês de pouco volume, a conta com eles só vale dentro desse arredondamento
            if t is None:
                assert not pequena
            elif t not in (0, p["corte_amostra_t"]):
                assert pequena == (t < p["corte_amostra_t"])
            if t:
                assert cif == pytest.approx(cif_musd * 1e6 / t, abs=(500 + cif) / t)
    assert bloco["produtos"]["enxofre"]["descricao"].endswith("(NCM 2503)")
    assert bloco["produtos"]["rocha"]["descricao"].endswith("(NCM 2510.10 e 2510.20)")
    rocha = bloco["produtos"]["rocha"]
    bm = rocha["benchmark"]
    assert all(len(bm[s]) == n for s in ("bm", "spread_usd_t", "spread_pct"))
    for fob, ref, spread, pct, pequena in zip(rocha["fob"], bm["bm"], bm["spread_usd_t"], bm["spread_pct"], rocha["amostra_pequena"]):
        if pequena or fob is None or not ref:
            assert spread is None and pct is None
        else:
            assert spread == pytest.approx(fob - ref, abs=1e-5) and pct == pytest.approx(100 * spread / ref, abs=1e-5)
    # o CIF do MAP é o mesmo dos blocos "nutrientes" e "benchmark"
    c = bloco["custo_map"]
    assert (c["coef_enxofre"], c["coef_rocha"]) == (config.INSUMOS_COEF_ENXOFRE, config.INSUMOS_COEF_ROCHA)
    for outro in (painel["nutrientes"]["produtos"]["map"]["cif"], painel["benchmark"]["produtos"]["map"]["cif"]):
        assert [v is None for v in c["cif_map"]] == [v is None for v in outro]
        assert all(abs(a - b) < 1e-6 for a, b in zip(c["cif_map"], outro) if a is not None)
    pequenas = zip(bloco["produtos"]["enxofre"]["amostra_pequena"], rocha["amostra_pequena"], painel["nutrientes"]["produtos"]["map"]["amostra_pequena"])
    assert c["amostra_pequena"] == [any(m) for m in pequenas]
    for e, r, custo, cif_map, razao in zip(bloco["produtos"]["enxofre"]["cif"], rocha["cif"], c["custo"], c["cif_map"], c["razao"]):
        if e is None or r is None:
            assert custo is None and razao is None
        else:
            assert custo == pytest.approx(e * c["coef_enxofre"] + r * c["coef_rocha"], abs=1e-5)
            assert razao == pytest.approx(custo / cif_map, abs=1e-6)
    for ano, por_produto in bloco["origens"].items():
        for chave, linhas in por_produto.items():
            assert sum(linha[3] for linha in linhas) == pytest.approx(100, abs=0.01), (ano, chave)
            assert len([linha for linha in linhas if linha[1] != "Outros"]) <= insumos.TOP_ORIGENS
    assert len(bloco["notas"]) >= 5 and bloco["notas"] == insumos.notas()


@dados_versionados
def test_bloco_versionado_e_o_que_o_transform_gera():
    """O bloco gravado é o que o código gera com os dados brutos (determinístico e atualizado)."""
    base = transform.carregar_base()
    pink = benchmark.ler_pink()
    fonte = json.loads((config.RAW_BENCHMARK_DIR / config.PINK_FONTE).read_text(encoding="utf-8"))
    dados = insumos.nos_meses(ingest.ler_insumos(), base)
    periodos = _painel()["mensal"]["periodos"]
    blocos = []
    for _ in range(2):
        tabela = insumos.mensal(dados, base, pink)
        bloco = insumos.bloco_dashboard(
            tabela, insumos.custo_map(tabela, base), periodos, transform._num, insumos.origens(dados, transform._num), fonte
        )
        blocos.append(json.dumps(bloco, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    assert blocos[0] == blocos[1]
    assert json.loads(blocos[0]) == _painel()["insumos"]


@dados_versionados
def test_insumos_nao_mudam_nenhuma_saida_de_fertilizantes(tmp_path):
    """Sem os insumos, o transform grava exatamente os outros CSVs e o resto do dashboard.json:
    os totais de fertilizantes (os 45,5 Mt de 2025, por exemplo) não mudam."""
    assert transform.main(["--saida", str(tmp_path), "--raw-insumos", str(tmp_path / "vazio")]) == 0
    novos = {"insumos_mensal.csv", "custo_insumo_map_mensal.csv"}
    gerados = {p.name for p in tmp_path.iterdir() if p.is_file()}
    versionados = {p.name for p in config.PROCESSED_DIR.iterdir() if p.suffix in (".csv", ".json")}
    assert gerados == versionados - novos
    for nome in sorted(gerados - {"dashboard.json"}):
        assert (tmp_path / nome).read_bytes() == (config.PROCESSED_DIR / nome).read_bytes(), nome
    painel = _painel()
    sem = json.loads((tmp_path / "dashboard.json").read_text(encoding="utf-8"))
    assert {k: v for k, v in painel.items() if k != "insumos"} == sem
    assert sem["anual"]["TOTAL"] == painel["anual"]["TOTAL"] and sem["mensal"]["TOTAL"] == painel["mensal"]["TOTAL"]
    texto = (config.PROCESSED_DIR / "dashboard.json").read_bytes()
    assert texto.startswith((tmp_path / "dashboard.json").read_bytes().rstrip(b"\n")[:-1])
