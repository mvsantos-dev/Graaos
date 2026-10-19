"""Insumos do fósforo (enxofre e rocha fosfática): NCMs num CSV próprio, importações gravadas à
parte e nunca nos totais de fertilizantes. Nenhum teste acessa a rede: a API é simulada."""

import json

import pandas as pd
import pytest

from src import config, ingest, transform
from tests.test_ingest import TABELAS, ApiFalsa, registro

# Granel líquido fica fora do Graaos: ácido sulfúrico, ácido fosfórico e amônia.
GRANEL_LIQUIDO = ("2807", "2809", "2814")


def test_buscar_ncms_insumos_so_enxofre_e_rocha_no_grupo_insumos():
    class ClienteFalso:
        def __init__(self):
            self.buscas = []

        def get(self, caminho, params=None):
            assert caminho == config.ENDPOINT_NCM
            sh4 = params["search"]
            self.buscas.append(sh4)
            itens = [
                {"coNcm": f"{sh4}1010", "noNCM": f"Item {sh4}", "headingCode": sh4, "subHeadingCode": f"{sh4}10"},
                # a busca casa trechos do código: 92503100 contém "2503" mas é de outra posição
                {"coNcm": f"9{sh4}100", "noNCM": "Outro capítulo", "headingCode": "9250", "subHeadingCode": "925031"},
            ]
            return {"list": itens, "count": len(itens)}

    cliente = ClienteFalso()
    df = ingest.buscar_ncms_insumos(cliente)
    assert cliente.buscas == list(config.INSUMOS_POR_SH4)
    assert df["ncm"].tolist() == ["25031010", "25101010"]
    assert set(df["grupo"]) == {config.GRUPO_INSUMOS}


def test_csv_de_ncms_insumos_versionado_e_separado_dos_fertilizantes():
    insumos = ingest.carregar_ncms(config.NCM_INSUMOS_CSV)
    fertilizantes = ingest.carregar_ncms(config.NCM_CSV)
    assert list(insumos.columns) == ingest.COLUNAS_NCM
    assert insumos["ncm"].is_unique
    assert set(insumos["sh4"]) == set(config.INSUMOS_POR_SH4)
    assert (insumos["sh4"] == insumos["ncm"].str[:4]).all() and (insumos["sh6"] == insumos["ncm"].str[:6]).all()
    assert set(insumos["grupo"]) == {config.GRUPO_INSUMOS}
    # 2510.10 (não moída) e 2510.20 (moída) da rocha; enxofre em 2503
    assert {"251010", "251020"} <= set(insumos["sh6"]) and "250300" in set(insumos["sh6"])
    assert not set(insumos["ncm"]) & set(fertilizantes["ncm"])
    assert not set(fertilizantes["grupo"]) & {config.GRUPO_INSUMOS}
    for ncms in (insumos["ncm"], fertilizantes["ncm"]):
        assert not ncms.str[:4].isin(GRANEL_LIQUIDO).any()


def test_insumos_incrementais_em_diretorio_proprio(tmp_path):
    raw = tmp_path / "raw_insumos"
    ncm_csv = tmp_path / "ncm_insumos.csv"
    ingest.salvar_ncms(
        pd.DataFrame({"ncm": ["25030010"], "descricao": ["Enxofre"], "grupo": ["INSUMOS"], "sh4": ["2503"], "sh6": ["250300"]}),
        ncm_csv,
    )
    api = ApiFalsa(ultimo="2025-02")
    assert ingest.ingerir_insumos(api, "2024-12", raw_dir=raw, ncm_csv=ncm_csv) == ("2024-12", "2025-02")
    assert api.consultas == [("2024-12", "2024-12"), ("2025-01", "2025-02")]
    # a mesma consulta das importações de fertilizantes (todos os detalhamentos e métricas)...
    assert all(c["flow"] == "import" and c["details"] == config.DETALHES for c in api.corpos)
    assert all(c["filters"] == [{"filter": "ncm", "values": ["25030010"]}] for c in api.corpos)
    # ...gravada à parte, com as mesmas colunas, e o mesmo cache incremental
    assert (raw / "ano=2025" / config.RAW_ARQUIVO).exists()
    assert list(ingest.ler_insumos(raw).columns) == ["ano", *ingest.COLUNAS_RAW]
    api.consultas.clear()
    ingest.ingerir_insumos(api, "2024-12", raw_dir=raw, ncm_csv=ncm_csv)
    assert api.consultas == []


def test_cli_inclui_insumos_em_todas_as_series_e_no_ultimo_gravado(tmp_path, monkeypatch, capsys):
    dirs = {"fertilizantes": tmp_path / "raw", "soja": tmp_path / "raw_soja", "insumos": tmp_path / "raw_insumos"}
    monkeypatch.setattr(ingest, "SERIES", {
        "fertilizantes": (dirs["fertilizantes"], config.RAW_ARQUIVO),
        "soja": (dirs["soja"], config.RAW_SOJA_ARQUIVO),
        "insumos": (dirs["insumos"], config.RAW_ARQUIVO),
    })
    ncm_insumos = tmp_path / "ncm_insumos.csv"
    ingest.salvar_ncms(
        pd.DataFrame({"ncm": ["25101010"], "descricao": ["Rocha"], "grupo": ["INSUMOS"], "sh4": ["2510"], "sh6": ["251010"]}),
        ncm_insumos,
    )
    monkeypatch.setattr(config, "NCM_INSUMOS_CSV", ncm_insumos)
    api = ApiFalsa(ultimo="2025-02")
    monkeypatch.setattr(ingest, "ClienteComexStat", lambda **kwargs: api)
    assert ingest.main(["--inicio", "2025-01", "--pausa", "0"]) == 0
    assert [c["flow"] for c in api.corpos] == ["import", "export", "import"]
    assert api.corpos[-1]["filters"] == [{"filter": "ncm", "values": ["25101010"]}]
    assert "Resumo insumos do fósforo" in capsys.readouterr().out
    # o mês completo exige as três séries do Comex Stat
    ingest.gravar_ano(ingest.normalizar([registro(2025, 3)], TABELAS), 2025, dirs["fertilizantes"])
    assert ingest.main(["--ultimo-gravado", "--por-serie"]) == 0
    assert "insumos 2025-02" in capsys.readouterr().out
    assert ingest.main(["--ultimo-gravado", "--serie", "insumos"]) == 0
    assert capsys.readouterr().out.strip() == "2025-02"


# --- Totais de fertilizantes ---------------------------------------------------------------


def test_insumo_nos_dados_de_fertilizantes_derruba_o_transform(tmp_path):
    """Um NCM de enxofre ou rocha em data/raw não entra calado nos totais: o transform recusa."""
    raw = tmp_path / "raw"
    linha = registro(2025, 1)
    ingest.gravar_ano(ingest.normalizar([linha, {**linha, "coNcm": "25030010"}], TABELAS), 2025, raw)
    with pytest.raises(ValueError, match="25030010"):
        transform.carregar_base(raw)


@pytest.mark.skipif(not (config.PROCESSED_DIR / "dashboard.json").exists(), reason="sem dashboard.json")
def test_totais_de_fertilizantes_sao_so_os_ncms_de_fertilizantes():
    """Os totais do dashboard (os 45,5 Mt de 2025, por exemplo) somam só data/raw, com os NCMs de
    data/ncm_fertilizantes.csv; os insumos ficam em data/raw_insumos e não mudam nenhum total."""
    fertilizantes = set(ingest.carregar_ncms(config.NCM_CSV)["ncm"])
    raw = ingest.ler_raw(config.RAW_DIR)
    assert set(raw["co_ncm"]) <= fertilizantes
    assert not raw["co_ncm"].str[:4].isin(list(config.INSUMOS_POR_SH4)).any()
    painel = json.loads((config.PROCESSED_DIR / "dashboard.json").read_text(encoding="utf-8"))
    anual = painel["anual"]
    soma = raw.assign(t=raw["kg_liquido"].astype("float64") / 1000).groupby("ano")["t"].sum()
    for ano, t in zip(anual["anos"], anual["TOTAL"]["t"]):
        assert t == pytest.approx(soma[ano], abs=1), ano
    if config.RAW_INSUMOS_DIR.exists():
        insumos = ingest.ler_insumos()
        assert not set(insumos["co_ncm"]) & fertilizantes
        assert insumos["co_ncm"].str[:4].isin(list(config.INSUMOS_POR_SH4)).all()
