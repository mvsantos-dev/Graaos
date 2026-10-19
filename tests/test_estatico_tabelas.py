"""Tabelas de "Ver tabela" escritas no HTML pelo build (src/estatico/tabelas.py). Sem rede.

A igualdade com o que o script desenha é conferida no navegador (tests/e2e/test_estatico_tabelas.py);
aqui ficam o formato, valores conferidos com dados.py e formato.py, os nulos e o escape.
"""

import copy
import json
import re
import shutil
from pathlib import Path

import pytest

from src.estatico import dados as D
from src.estatico import formato as F
from src.estatico import tabelas as T
from src.estatico import tabelas_notas as N
from src.estatico.contexto import Contexto, ErroEstatico, esc

RAIZ = Path(__file__).resolve().parent.parent
DADOS = json.loads((RAIZ / "data" / "processed" / "dashboard.json").read_text(encoding="utf-8"))
CSS = (RAIZ / "dashboard" / "assets" / "radar.css").read_text(encoding="utf-8")
P = DADOS["mensal"]["periodos"]
V = T.Visao.padrao(DADOS)
COR = T.cor_do_tema_claro(CSS, "--g-total")


def _linhas(html: str) -> list[list[str]]:
    """Textos das células de cada linha do corpo (sem as tags)."""
    corpo = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return [[re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr)] for tr in re.findall(r"<tr>(.*?)</tr>", corpo)]


def _cabecalho(html: str) -> list[str]:
    return re.findall(r"<th(?:\s[^>]*)?>(.*?)</th>", html.split("</thead>", 1)[0])


def test_visao_padrao_e_a_da_pagina_sem_hash():
    assert (V.grupo, V.de, V.ate, V.ano_rotas, V.bm) == ("TOTAL", P[0], P[-1], None, None)
    assert V.indices(DADOS) == list(range(len(P)))
    assert V.ano_das_rotas() == int(P[-1][:4])
    assert T.produto_bm(DADOS, V) == "kcl"  # o primeiro de ORDEM_BM com dados


def test_todas_as_tabelas_tem_linhas_e_colunas_coerentes():
    tabelas = T.tabelas(DADOS, V, COR)
    assert set(tabelas) == {"tabela-toneladas", "tabela-origens", "tabela-hhi", "tabela-fluxos", "tabela-portos", "tabela-rotas",
                            "tabela-precos", "tabela-frete", "tabela-nutrientes", "tabela-bm", "tabela-troca"}
    for id_, html in tabelas.items():
        if id_ == "tabela-fluxos":
            continue
        assert html.startswith("<table><thead><tr>") and html.endswith("</tbody></table>"), id_
        n = len(_cabecalho(html))
        assert all(len(linha) == n for linha in _linhas(html)), id_
    for id_ in ("tabela-toneladas", "tabela-precos", "tabela-frete", "tabela-nutrientes", "tabela-bm", "tabela-troca"):
        linhas = _linhas(tabelas[id_])
        assert len(linhas) == len(P), id_
        assert [x[0] for x in linhas] == [F.rotulo_mes(p) for p in P], id_
    assert len(_linhas(tabelas["tabela-hhi"])) == len(DADOS["anual"]["anos"])


def test_toneladas_com_os_quatro_grupos_e_o_total():
    html = T.toneladas(DADOS, V)
    assert _cabecalho(html) == ["Mês", "N (t)", "P (t)", "K (t)", "NPK (t)", "Total (t)"]
    assert '<th class="num">N (t)</th>' in html and "<th>Mês</th>" in html
    ultima = _linhas(html)[-1]
    i = len(P) - 1
    valores = [DADOS["mensal"][g]["t"][i] or 0 for g in F.GRUPOS]
    assert ultima == [F.rotulo_mes(P[i])] + [F.fmt0(v) for v in valores] + [F.fmt0(sum(valores))]
    # o total da tabela soma os grupos, como o script; o TOTAL do JSON (o do card Resumo) é
    # arredondado à parte e pode diferir em 1 t
    assert abs(sum(valores) - D.metricas(DADOS, "TOTAL", [i])["t"]) <= 2
    # um grupo só: sem a coluna do total
    assert _cabecalho(T.toneladas(DADOS, T.Visao("K", P[0], P[-1]))) == ["Mês", "K (t)"]


def test_precos_e_frete_batem_com_as_metricas_do_resumo():
    i = len(P) - 1
    m = D.metricas(DADOS, "TOTAL", [i])
    assert _linhas(T.precos(DADOS, V))[-1] == [F.rotulo_mes(P[i]), F.fmt0(m["preco_fob"]), F.fmt0(m["preco_cif"])]
    assert _linhas(T.frete(DADOS, V))[-1] == [F.rotulo_mes(P[i]), F.fmt0(m["frete_t"]), F.pct(m["frete_cif"])]


def test_ranking_de_origens_e_portos_do_ano_do_fim_do_periodo():
    ano = int(P[-1][:4])
    meses = DADOS["anual"]["n_meses"][DADOS["anual"]["anos"].index(ano)]
    rotulo = f"jan–{F.MESES[meses - 1]}/{ano - 1}" if meses < 12 else str(ano - 1)
    origens = T.ranking(DADOS, V, "origens")
    assert _cabecalho(origens) == ["#", "País", "Toneladas", "Share", f"Var. t vs {rotulo}", "Var. share", "US$/t FOB"]
    linhas = DADOS["origens"]["dados"][str(ano)]["TOTAL"]
    r = linhas[0]
    assert _linhas(origens)[0] == ["1", r[1], F.fmt0(r[2]), F.pct(r[3]), F.variacao(r[4]), F.variacao(r[5], " p.p."), F.fmt0(r[6])]
    assert _linhas(origens)[-1][:2] == ["", "Outros"]  # "Outros" sem posição
    portos = T.ranking(DADOS, V, "portos")
    assert _cabecalho(portos)[1] == "URF" and len(_cabecalho(portos)) == 6
    assert _linhas(portos)[0][1] == F.nome_urf(DADOS["urfs"]["dados"][str(ano)]["TOTAL"][0][1])


def test_hhi_com_lider_e_ano_parcial():
    html = T.hhi(DADOS, V)
    anos, n = DADOS["anual"]["anos"], DADOS["anual"]["n_meses"]
    linhas = _linhas(html)
    assert [x[0] for x in linhas] == [f"{a} (jan–{F.MESES[m - 1]})" if m < 12 else str(a) for a, m in zip(anos, n)]
    k = DADOS["anual"]["K"]
    assert linhas[0][7:10] == [F.fmt0(k["hhi"][0]), f"{k['lider'][0]} ({F.pct(k['lider_share_pct'][0])})", F.pct(k["cr3_pct"][0])]


def test_rotas_versao_larga_com_barra_na_cor_do_tema_claro():
    assert COR == "#6250d6"  # --g-total do :root do radar.css (o tema escuro vem depois)
    rot = T.rotas(DADOS, V, COR)
    ano = V.ano_das_rotas()
    bloco = DADOS["rotas"]["dados"][str(ano)]["TOTAL"]
    assert rot.titulo == f"Frete por rota · {T.rotulo_ano(DADOS, ano)}"
    assert f"São {bloco['n_relevantes']} de {bloco['n_rotas']} rotas" in rot.nota
    assert f"Mostrando as {len(bloco['rotas'])} maiores" in rot.nota
    assert _cabecalho(rot.html) == ["#", "Origem", "URF", "Toneladas", "Share", "Frete US$/t", "", "Frete no CIF", "Meses"]
    barras = re.findall(r'<span class="barra" style="width: (\d+)px; background: rgba\(98, 80, 214, 0\.5\);"></span>', rot.html)
    assert len(barras) == len(bloco["rotas"])
    maior = max(r[5] or 0 for r in bloco["rotas"])
    assert max(map(int, barras)) == 64 and barras[0] == str(T._js_round(64 * (bloco["rotas"][0][5] or 0) / maior))
    r = bloco["rotas"][0]
    assert _linhas(rot.html)[0][-1] == f"{r[7]}/{T.n_meses(DADOS, ano)}"
    # ano parcial: o corte proporcional na nota
    if T.ano_parcial(DADOS, ano):
        assert f"t × {T.n_meses(DADOS, ano)}/12 meses)" in rot.nota


def test_rotas_sem_rota_no_ano_esvaziam_a_caixa():
    d = copy.deepcopy(DADOS)
    d["rotas"]["dados"]["2019"]["TOTAL"]["rotas"] = []
    rot = T.rotas(d, T.Visao("TOTAL", P[0], P[-1], ano_rotas=2019), COR)
    assert rot.html == "" and rot.nota.startswith("Nenhuma rota com pelo menos ")
    d["rotas"] = None
    assert T.rotas(d, V, COR) is None


def test_nutrientes_marcam_amostra_pequena_e_trazem_as_duas_moedas():
    html = T.nutrientes(DADOS, V)
    nu = DADOS["nutrientes"]
    assert _cabecalho(html)[1:5] == ["Ureia t", "Ureia CIF US$/t", "Ureia US$/t de N", "Ureia R$/t de N"]
    pequenos = [(k, p) for k in ("ureia", "map", "kcl") for p, x in zip(nu["periodos"], nu["produtos"][k]["amostra_pequena"]) if x and p in P]
    linhas = {x[0]: x for x in _linhas(html)}
    for k, p in pequenos:
        col = 1 + 4 * ["ureia", "map", "kcl"].index(k)
        assert linhas[F.rotulo_mes(p)][col + 2].endswith("*") and linhas[F.rotulo_mes(p)][col + 3].endswith("*")
    d = copy.deepcopy(DADOS)
    d["nutrientes"]["produtos"]["kcl"]["custo"][-1] = None
    d["nutrientes"]["produtos"]["kcl"]["amostra_pequena"][-1] = True
    assert _linhas(T.nutrientes(d, V))[-1][11] == "–*"


def test_troca_em_toneladas_de_soja_e_sacas():
    html = T.troca(DADOS, V)
    tr = DADOS["troca"]
    assert _cabecalho(html)[:5] == ["Mês", "Soja US$/t FOB", "KCl US$/t CIF", "KCl t soja/t", "KCl sacas/t"]
    j = tr["periodos"].index(P[-1])
    kcl = tr["produtos"]["kcl"]
    assert _linhas(html)[-1][1:5] == [F.fmt0(tr["soja_fob"][j]), F.fmt0(kcl["cif"][j]), F.fmt2(kcl["razao"][j]), F.fmt1(kcl["razao"][j] * 1000 / tr["kg_saca"])]
    d = copy.deepcopy(DADOS)
    d["troca"]["produtos"]["kcl"]["razao"][j] = None
    assert _linhas(T.troca(d, V))[-1][3:5] == ["–", "–"]


def test_benchmark_com_base_vigente_e_sinal_ascii():
    html = T.benchmark(DADOS, V)
    bm = DADOS["benchmark"]
    kcl = bm["produtos"]["kcl"]
    linhas = {x[0]: x for x in _linhas(html)}
    assert linhas["jan/2015"][5] == "FOB Vancouver (FOB×FOB)"
    assert linhas["jan/2020"][5] == "CFR Brasil (granulado) (CIF×CFR)"
    negativos = [(p, v) for p, v in zip(bm["periodos"], kcl["spread_usd_t"]) if v is not None and v <= -0.5 and p in P]
    assert negativos, "os dados têm spread negativo em algum mês"
    p, v = negativos[0]
    assert linhas[F.rotulo_mes(p)][6] == "-" + F.fmt0(abs(v))  # o script troca o "−" por "-" na tabela
    assert F.MENOS not in html
    pequenos = [p for p, x in zip(bm["periodos"], kcl["amostra_pequena"]) if x and p in P]
    assert all(linhas[F.rotulo_mes(p)][-1] == "pequena" for p in pequenos)
    assert sum(1 for x in linhas.values() if x[-1] == "pequena") == len(pequenos)
    # produto escolhido na URL e produto fora do grupo
    assert _cabecalho(T.benchmark(DADOS, T.Visao("TOTAL", P[0], P[-1], bm="tsp"))) == _cabecalho(html)
    assert T.produto_bm(DADOS, T.Visao("P", P[0], P[-1], bm="kcl")) == "map"


def test_tabela_do_mapa_no_ultimo_ano_completo():
    mapa = DADOS["mapa"]
    ano = T.ano_padrao_fluxos(mapa)
    assert mapa["n_meses"][mapa["anos"].index(ano)] == 12
    html = T.fluxos(DADOS)
    r = mapa["dados"][str(ano)]["TOTAL"]
    assert html.count("<table>") == 3 and html.count('<h4 class="subtitulo">') == 2
    assert f'<caption class="leitor">Origens em {ano}, todos os grupos</caption>' in html
    assert '<th scope="col">País de origem</th><th class="num" scope="col">Toneladas</th>' in html
    tabelas = html.split("</table>")
    assert len(_linhas(tabelas[0] + "</table>")) == len(r["origens"]) + 1  # + "Outros"
    assert "Outros (menos de 1.000 t ou sem coordenada)" in html and "<td></td><td></td><td></td><td></td></tr>" in html
    assert len(_linhas(tabelas[2] + "</table>")) == len(r["rotas"])
    assert "Rotas com pelo menos 50 mil t no ano" in html
    # ano parcial: o corte proporcional e o período no título
    parcial = mapa["anos"][-1]
    m = mapa["n_meses"][-1]
    if m < 12:
        corte = F.numero(mapa["corte_rota_t"][-1] / 1000, 0, 1)
        assert f"Rotas com pelo menos {corte} mil t em jan–{F.MESES[m - 1]}" in T.fluxos(DADOS, parcial)


def test_variacao_sobre_base_quase_zero_vira_novo_no_mapa():
    d = copy.deepcopy(DADOS)
    ano = T.ano_padrao_fluxos(d["mapa"])
    o = d["mapa"]["dados"][str(ano)]["TOTAL"]["origens"][0]
    o[1], o[3] = 5000, 900.0  # base de 500 t, abaixo do mínimo de 1.000 t
    assert "<td class=\"num\">novo</td>" in T.fluxos(d)


def test_escapa_o_texto_dos_dados():
    d = copy.deepcopy(DADOS)
    ano = str(V.ano)
    d["origens"]["dados"][ano]["TOTAL"][0][1] = '<img src=x onerror="alert(1)"> & Cia'
    html = T.ranking(d, V, "origens")
    assert "<img" not in html and "&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; Cia" in html
    assert T.celula("td", T.Bruto("<b>x</b>")) == "<td><b>x</b></td>"
    assert T.celula("td", "<b>") == "<td>&lt;b&gt;</td>"


@pytest.mark.parametrize("valor,texto", [
    (None, "null"), (9, "9"), (9.0, "9"), (33.5, "33.5"), (-2.25, "-2.25"), (0.0, "0"), (1e21, "1e+21"), (1.5e-7, "1.5e-7"),
    (0.000001, "0.000001"), (123456789012345680000.0, "123456789012345680000"), (0.1 + 0.2, "0.30000000000000004"), (True, "true"),
])
def test_js_escreve_numeros_como_o_javascript(valor, texto):
    assert T.js(valor) == texto


def test_arredondamentos_e_nulos_como_no_navegador():
    assert [T._js_round(x) for x in (2.5, -2.5, 0.49999999999999994, 63.5, 0.0)] == [3, -2, 0, 64, 0]
    assert T.intl(F.fmt0, None) == "0"  # Intl.format(null)
    assert T.com_alfa("#6250d6", 0.5) == "rgba(98, 80, 214, 0.5)"


def test_cor_do_tema_claro_exige_a_variavel():
    with pytest.raises(ErroEstatico):
        T.cor_do_tema_claro(":root { --g-n: #2a78d6; }", "--g-total")
    assert T.cor_do_tema_claro(":root { --g-total: #ABCDEF; }\n:root[data-theme=dark] { --g-total: #000000; }", "--g-total") == "#abcdef"


def _site(tmp_path: Path, dados: dict) -> Path:
    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True)
    shutil.copy(RAIZ / "dashboard" / "index.html", site / "index.html")
    shutil.copy(RAIZ / "dashboard" / "assets" / "radar.css", site / "assets" / "radar.css")
    (site / "dashboard.json").write_text(json.dumps(dados), encoding="utf-8")
    (site / "boletim.json").write_text("{}", encoding="utf-8")
    return site


def _classe(html: str, id_: str) -> str:
    return re.search(r'<[^>]*\sid="' + id_ + r'"[^>]*>', html).group(0).split('class="', 1)[1].split('"', 1)[0]


def test_gerar_preenche_as_caixas_mostra_as_secoes_e_escreve_titulo_e_nota_das_rotas(tmp_path):
    ctx = Contexto.carregar(_site(tmp_path, DADOS))
    original = ctx.html
    assert "oculto" in _classe(original, "secao-nutrientes") and "oculto" in _classe(original, "secao-bm")
    T.gerar(ctx)
    for id_, html in T.tabelas(DADOS, V, COR).items():
        assert f'id="{id_}">{html}</div>' in ctx.html, id_
    assert _classe(ctx.html, "secao-nutrientes") == "cartao grade" and _classe(ctx.html, "secao-bm") == "cartao grade"
    rot = T.rotas(DADOS, V, COR)
    assert f'id="titulo-frete-rotas">{esc(rot.titulo)}</h3>' in ctx.html
    assert f'id="nota-frete-rotas">{esc(rot.nota)}</p>' in ctx.html
    # desfeitas as inserções, o HTML volta a ser o original: nada mais mudou
    volta = ctx.html
    for id_, html in T.tabelas(DADOS, V, COR).items():
        volta = volta.replace(f'id="{id_}">{html}<', f'id="{id_}"><', 1)
    volta = volta.replace(f">{esc(rot.titulo)}</h3>", f">{T.TITULO_ROTAS}</h3>", 1).replace(f">{esc(rot.nota)}</p>", "></p>", 1)
    for id_, texto in N.notas(DADOS, V).items():
        assert f'id="{id_}">{esc(texto)}</p>' in volta, id_
        volta = volta.replace(f'id="{id_}">{esc(texto)}</p>', f'id="{id_}"></p>', 1)
    volta = volta.replace(f'id="fonte-rodape">{esc(N.fonte_rodape(DADOS))}<', f'id="fonte-rodape">{N.FONTE_RODAPE}<', 1)
    ctx_volta = Contexto(site=ctx.site, dados=DADOS, boletim={}, html=volta)
    for id_ in ("secao-nutrientes", "secao-bm", "rodape-bm"):
        ctx_volta.definir_atributo(id_, "class", _classe(original, id_))
    assert ctx_volta.html == original


def test_gerar_respeita_nota_ja_escrita_e_esconde_secoes_sem_dados(tmp_path):
    d = copy.deepcopy(DADOS)
    for chave in ("nutrientes", "benchmark", "troca", "mapa"):
        d[chave] = None
    ctx = Contexto.carregar(_site(tmp_path, d))
    ctx.html = ctx.html.replace('<p class="nota" id="nota-frete-rotas"></p>', '<p class="nota" id="nota-frete-rotas">já escrita</p>')
    T.gerar(ctx)
    assert 'id="nota-frete-rotas">já escrita</p>' in ctx.html
    assert 'id="tabela-nutrientes"></div>' in ctx.html and 'id="tabela-bm"></div>' in ctx.html
    assert 'id="tabela-troca"></div>' in ctx.html and 'id="tabela-fluxos"></div>' in ctx.html
    assert "oculto" in _classe(ctx.html, "secao-troca").split() and "oculto" in _classe(ctx.html, "secao-nutrientes").split()


def test_gerar_falha_se_a_caixa_ja_tem_conteudo(tmp_path):
    ctx = Contexto.carregar(_site(tmp_path, DADOS))
    ctx.html = ctx.html.replace('id="tabela-hhi"></div>', 'id="tabela-hhi">x</div>')
    with pytest.raises(ErroEstatico, match="tabela-hhi"):
        T.gerar(ctx)


def test_notas_dizem_o_que_cada_tabela_mostra():
    notas = N.notas(DADOS, V)
    periodo = f"{F.rotulo_mes(P[0])} a {F.rotulo_mes(P[-1])}"
    assert notas["nota-toneladas"] == f"Todos os grupos · {periodo}"
    assert notas["nota-precos"] == notas["nota-frete"] == f"Todos os grupos · US$ por tonelada · {periodo}"
    kcl = DADOS["benchmark"]["produtos"]["kcl"]
    assert notas["nota-bm"].startswith(f"{kcl['nome']} ({kcl['descricao']}, NCM {', '.join(kcl['ncms'])}) · benchmark: {kcl['serie']}, Banco Mundial")
    assert notas["nota-bm"].endswith(periodo)
    pequenos = sum(1 for p, x in zip(DADOS["benchmark"]["periodos"], kcl["amostra_pequena"]) if x and p in P)
    assert (f" {pequenos} {'mês' if pequenos == 1 else 'meses'} com menos de 10.000 t" in notas["nota-spread"]) == (pequenos > 0)
    assert "(na tabela, com *)" in notas["nota-teores"] and notas["nota-teores"].endswith(f"Fonte: {DADOS['nutrientes']['fonte']}.")
    assert "Ureia 46% de N" in notas["nota-teores"] and "No MAP, o N que vem junto" in notas["nota-teores"]
    assert notas["nota-nutrientes"].startswith("Ureia, MAP, KCl · US$ por tonelada de nutriente")
    assert notas["nota-troca"] == f"KCl, Ureia, MAP · t de soja por t de fertilizante · {periodo}"
    assert notas["nota-origens"].endswith(f"top {len(DADOS['origens']['dados'][str(V.ano)]['TOTAL']) - 1} e outros")
    # NPK: a troca e os nutrientes avisam que mostram os produtos dos três nutrientes
    npk = N.notas(DADOS, T.Visao("NPK", P[0], P[-1]))
    assert npk["nota-troca"].endswith("NPK não entra na relação: mostrando os três produtos")
    assert "os compostos NPK não entram" in npk["nota-nutrientes"]
    # N: os três nitrogenados e o enxofre do sulfato
    assert "O enxofre do sulfato de amônio" in N.notas(DADOS, T.Visao("N", P[0], P[-1]))["nota-teores"]


def test_fonte_do_rodape_cita_o_que_os_dados_usam():
    assert N.fonte_rodape(DADOS) == "Fonte: Comex Stat/MDIC; Banco Mundial (Pink Sheet); BCB/PTAX"
    d = copy.deepcopy(DADOS)
    d["benchmark"] = None
    assert N.fonte_rodape(d) == "Fonte: Comex Stat/MDIC; BCB/PTAX"  # PTAX dos nutrientes
    d["nutrientes"]["ptax"] = [None] * len(d["nutrientes"]["ptax"])
    assert N.fonte_rodape(d) == "Fonte: Comex Stat/MDIC"


def test_texto_ja_escrito_por_outra_etapa_fica_e_id_sumido_falha(tmp_path):
    ctx = Contexto.carregar(_site(tmp_path, DADOS))
    ctx.html = ctx.html.replace('<p class="nota" id="nota-bm"></p>', '<p class="nota" id="nota-bm"><strong>KCl</strong> já escrito</p>')
    T.gerar(ctx)
    assert '<p class="nota" id="nota-bm"><strong>KCl</strong> já escrito</p>' in ctx.html
    ctx = Contexto.carregar(_site(tmp_path / "b", DADOS))
    ctx.html = ctx.html.replace(' id="nota-troca"', "")
    with pytest.raises(ErroEstatico, match="nota-troca"):
        T.gerar(ctx)
