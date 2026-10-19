"""Páginas estáticas dos boletins (src/estatico/boletins.py): boletim/AAAA-MM/ e boletim/.

Monta a pasta do site como o build_site.sh antes do src.estatico (dashboard/, dashboard.json e
boletim.json) e roda só a etapa dos boletins. Não fixa valores de nenhum mês: os números das
páginas são conferidos contra o pacote de fatos do boletim e as contas do script (dados.kpis)
calculados na hora, em todos os meses dos dados.
"""

from __future__ import annotations

import ast
import html
import json
import re
import shutil
from pathlib import Path

import pytest

from src import boletim as B
from src import config
from src.estatico import boletins, boletins_frases as T, dados as D, formato as F
from src.estatico.contexto import URL_BASE, Contexto, ErroEstatico

RAIZ = Path(__file__).resolve().parents[1]
ATUALIZADO = "2026-10-15"


def _montar(pasta: Path, boletim_site: dict | None = None, textos: dict[str, dict | str] | None = None) -> Contexto:
    site, raiz = pasta / "site", pasta / "raiz"
    # sem as capturas grandes do README; os ícones (favicon-*.png etc.) ficam, porque as páginas os ligam
    shutil.copytree(RAIZ / "dashboard", site, ignore=shutil.ignore_patterns("*.gif", "print*.png", "preview.png"))
    shutil.copy(config.PROCESSED_DIR / "dashboard.json", site / "dashboard.json")
    (site / "boletim.json").write_text(json.dumps(boletim_site or {}, ensure_ascii=False), encoding="utf-8")
    (raiz / "boletins").mkdir(parents=True)
    for mes, conteudo in (textos or {}).items():
        texto = conteudo if isinstance(conteudo, str) else json.dumps(conteudo, ensure_ascii=False)
        (raiz / "boletins" / f"{mes}.json").write_text(texto, encoding="utf-8")
    return Contexto.carregar(site, ATUALIZADO, raiz=raiz)


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    c = _montar(tmp_path_factory.mktemp("boletins"))
    boletins.gerar(c)
    return c


@pytest.fixture(scope="module")
def painel():
    return json.loads((config.PROCESSED_DIR / "dashboard.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fatos(painel):
    troca = B.troca_do_painel(painel)
    return {p: B.montar_fatos(painel, troca, p) for p in painel["mensal"]["periodos"]}


def _pagina(ctx: Contexto, caminho: str) -> str:
    return (ctx.site / caminho / "index.html").read_text(encoding="utf-8")


def _meta(pagina: str, atributo: str, nome: str) -> str:
    achados = re.findall(rf'<meta {atributo}="{re.escape(nome)}" content="([^"]*)">', pagina)
    assert len(achados) == 1, (nome, achados)
    return html.unescape(achados[0])


def _texto(trecho: str) -> str:
    """Texto visível de um trecho de HTML (tags fora, entidades e espaço inseparável normalizados)."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", trecho)).replace(" ", " ")).strip()


def _secao(pagina: str, id_titulo: str) -> str:
    m = re.search(rf'<section [^>]*aria-labelledby="{id_titulo}">.*?</section>', pagina, re.S)
    assert m, id_titulo
    return m.group(0)


def _mascarar(frase: str, f: B.Fatos) -> str:
    """Troca os valores do pacote de fatos por um marcador: o que sobra é o texto do modelo."""
    for v in sorted(set(f.valores().values()), key=len, reverse=True):
        frase = frase.replace(v, "{}")
    return frase


# --- Páginas, títulos e endereços --------------------------------------------------------------


def test_uma_pagina_por_mes_e_o_arquivo_no_sitemap(ctx):
    periodos = ctx.periodos
    assert len(periodos) >= 12
    for p in periodos:
        assert (ctx.site / "boletim" / p / "index.html").is_file(), p
    assert (ctx.site / "boletim" / "index.html").is_file()
    caminhos = [x.caminho for x in ctx.paginas]
    assert caminhos == [f"boletim/{p}/" for p in periodos] + ["boletim/"]
    assert {x.lastmod for x in ctx.paginas} == {ATUALIZADO}
    assert all(x.url.startswith(URL_BASE + "boletim/") for x in ctx.paginas)


def test_titulo_descricao_canonical_e_previa_de_cada_mes(ctx):
    descricoes = set()
    for p in ctx.periodos:
        pagina = _pagina(ctx, f"boletim/{p}")
        titulo = html.unescape(re.search(r"<title>([^<]*)</title>", pagina).group(1))
        assert titulo == f"Importação de fertilizantes em {F.rotulo_mes_longo(p)} | Graaos"
        assert len(titulo) <= 60, titulo
        descricao = _meta(pagina, "name", "description")
        assert 70 <= len(descricao) <= 155, (p, len(descricao), descricao)
        assert F.rotulo_mes_longo(p) in descricao or F.rotulo_mes(p) in descricao
        descricoes.add(descricao)
        url = f"{URL_BASE}boletim/{p}/"
        assert re.findall(r'<link rel="canonical" href="([^"]*)">', pagina) == [url]
        assert _meta(pagina, "property", "og:url") == url
        assert _meta(pagina, "property", "og:title") == titulo == _meta(pagina, "name", "twitter:title")
        assert _meta(pagina, "property", "og:description") == descricao == _meta(pagina, "name", "twitter:description")
        assert _meta(pagina, "property", "og:image") == URL_BASE + "preview.png"
        assert _meta(pagina, "name", "theme-color") == "#2B36D9"
        assert pagina.startswith('<!doctype html>\n<html lang="pt-BR">')
        assert pagina.count("<h1") == 1
    assert len(descricoes) == len(ctx.periodos)  # uma descrição diferente por página


def test_arquivo_com_todos_os_meses_por_ano(ctx):
    pagina = _pagina(ctx, "boletim")
    titulo = html.unescape(re.search(r"<title>([^<]*)</title>", pagina).group(1))
    assert len(titulo) <= 60 and titulo.endswith("| Graaos")
    assert len(_meta(pagina, "name", "description")) <= 155
    assert re.findall(r'<link rel="canonical" href="([^"]*)">', pagina) == [URL_BASE + "boletim/"]
    links = re.findall(r'<li><a href="(\d{4}-\d{2})/">', pagina)
    assert links == sorted(ctx.periodos, reverse=True)  # todos, do mais novo ao mais antigo
    anos = re.findall(r'id="t-ano-(\d{4})"', pagina)
    assert anos == sorted({p[:4] for p in ctx.periodos}, reverse=True)
    assert pagina.count("<details open>") == 2  # os dois anos mais recentes abertos
    assert f'href="{ctx.periodos[-1]}/"' in _secao(pagina, "t-ultimo")


def test_anterior_e_proximo_encadeiam_todos_os_meses(ctx):
    periodos = ctx.periodos
    for i, p in enumerate(periodos):
        pagina = _pagina(ctx, f"boletim/{p}")
        anterior = re.findall(r'<a class="anterior" rel="prev" href="\.\./(\d{4}-\d{2})/">', pagina)
        proximo = re.findall(r'<a class="proximo" rel="next" href="\.\./(\d{4}-\d{2})/">', pagina)
        assert anterior == ([periodos[i - 1]] if i > 0 else [])
        assert proximo == ([periodos[i + 1]] if i + 1 < len(periodos) else [])
        assert re.findall(r'<link rel="prev" href="\.\./(\d{4}-\d{2})/">', pagina) == anterior
        assert re.findall(r'<link rel="next" href="\.\./(\d{4}-\d{2})/">', pagina) == proximo
        assert '<a class="arquivo" href="../">' in pagina and '<a href="../../">Painel</a>' in pagina


def test_links_relativos_apontam_para_arquivos_do_site(ctx):
    for caminho in [f"boletim/{p}" for p in ctx.periodos] + ["boletim"]:
        pagina = _pagina(ctx, caminho)
        base = ctx.site / caminho
        for href in re.findall(r'(?:href|src)="([^"]+)"', pagina):
            if re.match(r"(?:[a-z]+:|#|//)", href):
                continue
            alvo = (base / href.split("#")[0].split("?")[0]).resolve()
            alvo = alvo / "index.html" if alvo.is_dir() else alvo
            assert alvo.is_file() and ctx.site.resolve() in alvo.parents, (caminho, href)
        assert '<link rel="stylesheet" href="' + ("../" * caminho.count("/") + "../") + 'assets/boletim.css">' in pagina


def test_home_liga_o_ultimo_mes_e_o_arquivo(ctx):
    ultimo = ctx.periodos[-1]
    esperado = (f'<span id="link-boletim-pagina"> Leia o <a href="boletim/{ultimo}/">boletim de {F.rotulo_mes_longo(ultimo)}</a>'
                ' ou o <a href="boletim/">arquivo de todos os meses</a>.</span>')
    assert esperado in ctx.html


def test_json_ld_de_cada_pagina(ctx):
    for caminho in [f"boletim/{p}/" for p in ctx.periodos] + ["boletim/"]:
        pagina = _pagina(ctx, caminho)
        blocos = re.findall(r'<script type="application/ld\+json">\n(.*?)\n</script>', pagina, re.S)
        assert len(blocos) == 1
        dados = json.loads(blocos[0])
        assert dados["@context"] == "https://schema.org"
        tipos = {n["@type"]: n for n in dados["@graph"]}
        url = URL_BASE + caminho
        pagina_ld = tipos["CollectionPage" if caminho == "boletim/" else "WebPage"]
        assert pagina_ld["url"] == url and pagina_ld["@id"] == url + "#pagina"
        assert pagina_ld["isPartOf"] == {"@id": URL_BASE + "#website"} and pagina_ld["publisher"] == {"@id": URL_BASE + "#organization"}
        assert pagina_ld["inLanguage"] == "pt-BR" and pagina_ld["dateModified"] == ATUALIZADO
        assert pagina_ld["license"] == "https://creativecommons.org/licenses/by/4.0/"
        trilha = tipos["BreadcrumbList"]
        assert pagina_ld["breadcrumb"] == {"@id": trilha["@id"]}
        itens = trilha["itemListElement"]
        assert [i["position"] for i in itens] == list(range(1, len(itens) + 1))
        assert itens[0]["item"] == URL_BASE and itens[-1]["item"] == url
        if caminho != "boletim/":
            assert pagina_ld["temporalCoverage"] == caminho[8:15]
            assert pagina_ld["name"] == html.unescape(re.search(r"<title>([^<]*)</title>", pagina).group(1))


# --- Números: os do pacote de fatos e os do script ----------------------------------------------


def test_cartoes_do_resumo_iguais_aos_do_script(ctx, painel):
    for p in ctx.periodos:
        secao = _secao(_pagina(ctx, f"boletim/{p}"), "t-kpis")
        k = D.kpis(painel, "TOTAL", p)
        cartoes = re.findall(r'<div class="kpi"><div class="rotulo">([^<]*)</div><div class="valor"><span class="numero">([^<]*)</span></div><div class="delta">([^<]*)</div></div>', secao)
        assert [tuple(html.unescape(x) for x in c) for c in cartoes] == [(c["rotulo"], c["valor"], c["delta"]) for c in k["mes"] + k["acumulado"]], p
        assert f">{html.escape(k['titulo'])}</h2>" in secao
        assert f"<h3>{html.escape(k['titulo_mes'])}</h3>" in secao and f"<h3>{html.escape(k['titulo_acumulado'])}</h3>" in secao


def test_frases_com_os_valores_do_pacote_de_fatos(ctx, fatos):
    for p in ctx.periodos:
        f = fatos[p]
        pagina = _pagina(ctx, f"boletim/{p}")
        lead = _texto(re.search(r'<p class="bloco-lead">(.*?)</p>', pagina).group(1))
        assert lead == T.lead(f)
        assert T.valor(f, "t_total_mes") in lead and T.valor(f, "mes_referencia") in lead
        if "var_t_total_mes" in f:
            assert f"{T.valor(f, 'var_t_total_mes_sentido')} de {T.valor(f, 'var_t_total_mes')}" in lead or "sem variação" in lead
        troca = _texto(_secao(pagina, "t-troca"))
        for prod in T.PRODUTOS_TROCA:
            if f"troca_{prod}_ultimo" in f:
                assert T.valor(f, f"troca_{prod}_ultimo") in troca and T.valor(f, f"sacas_{prod}_ultimo") in troca
        descricao = _meta(pagina, "name", "description")
        assert T.valor(f, "t_total_mes") in descricao


def test_tabela_por_grupo_igual_as_metricas_do_script(ctx, painel):
    for p in ctx.periodos:
        secao = _secao(_pagina(ctx, f"boletim/{p}"), "t-grupos")
        linhas = re.findall(r"<tr(?: class=\"total\")?><td>([^<]*)</td><td class=\"num\">([^<]*)</td>", secao)
        i = painel["mensal"]["periodos"].index(p)
        esperado = [(F.NOMES[g] if g == "TOTAL" else f"{g} · {F.NOMES[g]}", F.fmt0(D.metricas(painel, g, [i])["t"])) for g in [*F.GRUPOS, "TOTAL"]]
        assert [(html.unescape(a), b) for a, b in linhas] == esperado, p
        tem_ant = f"{int(p[:4]) - 1}{p[4:]}" in painel["mensal"]["periodos"]
        assert ("Var. t vs" in secao) == tem_ant


def test_origens_portos_e_rotas_so_quando_o_ano_termina_no_mes(ctx, painel, fatos):
    anual = painel["anual"]
    for p in ctx.periodos:
        pagina = _pagina(ctx, f"boletim/{p}")
        ano, m = int(p[:4]), int(p[5:7])
        termina = anual["n_meses"][anual["anos"].index(ano)] == m
        assert ('aria-labelledby="t-origens"' in pagina) == termina, p
        assert ("lider_total_ano" in fatos[p]) == termina  # a mesma regra do pacote de fatos
        if termina:
            secao = _texto(_secao(pagina, "t-origens"))
            assert T.valor(fatos[p], "lider_total_ano") in secao and T.valor(fatos[p], "share_lider_total_ano") in secao
            primeira = [r for r in painel["origens"]["dados"][str(ano)]["TOTAL"] if r[1] != "Outros"][0]
            assert f"{primeira[1]} {F.fmt0(primeira[2])} {F.pct(primeira[3])}" in secao
        else:
            alvo = re.search(r'<p class="nota-boletim">.*?<a href="\.\./(\d{4}-\d{2})/">', pagina).group(1)
            assert alvo[:4] == p[:4] and alvo in ctx.periodos and alvo > p


# --- Regras das saídas públicas -----------------------------------------------------------------


def test_troca_no_porto_sem_reais_e_nao_e_preco_ao_produtor(ctx):
    for p in ctx.periodos:
        pagina = _pagina(ctx, f"boletim/{p}")
        troca = _texto(_secao(pagina, "t-troca"))
        assert "No porto, não na fazenda." in troca and "Não é o preço ao produtor" in troca
        assert "no porto, não o preço ao produtor" in troca
        assert "R$" not in pagina and "reais" not in pagina.lower()  # nenhum valor em reais, e troca nunca em R$
        assert "ágio" not in pagina.lower() and "UF do importador" not in pagina
        rodape = re.search(r'<footer class="rodape">(.*?)</footer>', pagina, re.S).group(1)
        assert "Fonte: Comex Stat/MDIC</span>" in rodape and "Código aberto (MIT) · dados CC BY 4.0" in rodape


def test_frases_modelo_neutras_e_sem_numero_fora_do_pacote(painel, fatos):
    """As frases do programa seguem o tom do boletim: sem juízo, causa, recomendação, recorde nem
    "ágio", direção só pelos valores do pacote; e nenhum número escrito fora dele (só o "1 t")."""
    for p, f in fatos.items():
        i = painel["mensal"]["periodos"].index(p)
        ordem = sorted((g.lower() for g in F.GRUPOS), key=lambda k: -(painel["mensal"][k.upper()]["t"][i] or 0))
        frases = [T.lead(f), T.frase_precos(f), T.frase_grupos(f, ordem), T.frase_origens(f), T.frase_troca(f), T.nota_troca(f),
                  T.resumo_curto(f), T.descricao(f, True), T.descricao(f, False),
                  *(T.delta_troca(f, prod) for prod in T.PRODUTOS_TROCA if f"troca_{prod}_ultimo" in f)]
        for frase in filter(None, frases):
            resto = _mascarar(frase, f)
            for regra in (B.PROIBIDOS, B.JUIZO, B.CAUSA, B.RECORDE, B.AGIO):
                assert not regra.search(resto), (p, regra.search(resto).group(0), frase)
            assert not B.PRODUTOR.search(resto.replace("não o preço ao produtor", "")), (p, frase)
            # números: só os do pacote, mais o "1 t" fixo da relação de troca e os meses curtos do resumo
            sobra = re.sub(r"\b1 t de\b", "", resto)
            sobra = re.sub(r"\b(?:jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)/\d{4}\b", "", sobra)
            assert not re.search(r"\d", sobra), (p, frase)


def test_texto_de_ia_escapado_com_rodape_e_fontes(tmp_path, painel):
    periodos = painel["mensal"]["periodos"]
    ultimo, penultimo = periodos[-1], periodos[-2]
    troca = B.troca_do_painel(painel)
    textos = {}
    for mes in (ultimo, penultimo):
        f = B.montar_fatos(painel, troca, mes)
        conteudo = B.gerar(f, B.ProvedorMock())
        B.escrever(conteudo, f, tmp_path / "gerado", "teste", mock=False)
        textos[mes] = json.loads((tmp_path / "gerado" / f"{mes}.json").read_text(encoding="utf-8"))
    textos[penultimo]["titulo"] += ' <script>alert("x")</script> & <b>'
    c = _montar(tmp_path / "a", textos=textos)
    boletins.gerar(c)
    pagina = _pagina(c, f"boletim/{penultimo}")
    secao = _secao(pagina, "t-texto")
    assert "<script>alert" not in pagina and "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; &lt;b&gt;" in secao
    assert all(html.escape(x) in secao for x in textos[penultimo]["paragrafos"])
    assert "números inseridos e verificados automaticamente." in secao and f"Fonte: {textos[penultimo]['fonte']}." in _texto(secao)
    fontes = [x for x in textos[penultimo]["fonte"].split("; ")]
    assert f'<span class="fonte">Fonte: {html.escape("; ".join(fontes))}</span>' in pagina
    assert f"{B.REPOSITORIO}/blob/main/boletins/{penultimo}.md" in secao
    arquivo = _pagina(c, "boletim")
    assert re.search(rf'<a href="{penultimo}/">[^<]*</a><span class="selo">com texto</span>', arquivo)
    assert arquivo.count('<span class="selo">com texto</span>') == 2
    sem_texto = _pagina(c, f"boletim/{periodos[0]}")
    assert 'aria-labelledby="t-texto"' not in sem_texto


def test_boletim_do_site_vale_para_o_proprio_mes_e_mock_fica_de_fora(tmp_path, painel, capsys):
    periodos = painel["mensal"]["periodos"]
    ultimo = periodos[-1]
    f = B.montar_fatos(painel, B.troca_do_painel(painel), ultimo)
    B.escrever(B.gerar(f, B.ProvedorMock()), f, tmp_path / "g", "mock", mock=True)
    mock = json.loads((tmp_path / "g" / "latest.json").read_text(encoding="utf-8"))
    # o boletim.json do site (o latest.json do repositório) entra na página do mês dele
    real = {**mock, "mock": False}
    c = _montar(tmp_path / "a", boletim_site=real)
    boletins.gerar(c)
    assert 'aria-labelledby="t-texto"' in _pagina(c, f"boletim/{ultimo}")
    assert 'aria-labelledby="t-texto"' not in _pagina(c, f"boletim/{periodos[-2]}")
    # texto do modo --mock nunca vira página
    c = _montar(tmp_path / "b", boletim_site=mock, textos={ultimo: mock})
    boletins.gerar(c)
    assert 'aria-labelledby="t-texto"' not in _pagina(c, f"boletim/{ultimo}")
    assert "modo --mock" in capsys.readouterr().err


@pytest.mark.parametrize("conteudo, trecho", [
    ("{", "inválido"),
    (json.dumps({"mes": "1999-01", "titulo": "x", "lead": "y", "paragrafos": ["z"]}), "sem mes"),
    (json.dumps({"titulo": "x", "lead": "y", "paragrafos": []}), "sem mes"),
], ids=["json-quebrado", "outro-mes", "sem-paragrafos"])
def test_texto_do_mes_invalido_falha_o_build(tmp_path, painel, conteudo, trecho):
    ultimo = painel["mensal"]["periodos"][-1]
    c = _montar(tmp_path, textos={ultimo: conteudo})
    with pytest.raises(ErroEstatico, match=trecho):
        boletins.gerar(c)


def test_icones_da_home_com_caminho_relativo_corrigido():
    home = ('<head><link rel="icon" href="data:image/svg+xml,x"><link rel="icon" type="image/png" sizes="32x32" href="favicon-32.png">'
            '<link rel="apple-touch-icon" href="apple-touch-icon.png"><link rel="manifest" href="/site.webmanifest">'
            '<link rel="stylesheet" href="assets/radar.css"></head><body><link rel="icon" href="fora.png"></body>')
    links = boletins._links_da_home(home)
    assert len(links) == 4
    assert [boletins._relativo(x, "../../") for x in links] == [
        '<link rel="icon" href="data:image/svg+xml,x">',
        '<link rel="icon" type="image/png" sizes="32x32" href="../../favicon-32.png">',
        '<link rel="apple-touch-icon" href="../../apple-touch-icon.png">',
        '<link rel="manifest" href="/site.webmanifest">',
    ]


def test_modulos_dos_boletins_usam_so_a_biblioteca_padrao():
    """Rodam no build da Cloudflare e do GitHub Pages, sem instalar pacotes."""
    import sys

    for modulo in ("boletins", "boletins_frases"):
        arvore = ast.parse((RAIZ / "src" / "estatico" / f"{modulo}.py").read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                nomes = [a.name.split(".")[0] for a in no.names]
            elif isinstance(no, ast.ImportFrom) and no.level == 0:
                nomes = [no.module.split(".")[0]]
            else:
                continue
            assert all(n in sys.stdlib_module_names or n == "__future__" for n in nomes), (modulo, nomes)
