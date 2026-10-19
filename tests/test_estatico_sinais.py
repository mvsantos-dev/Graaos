"""Sinais do mês no site (src/estatico/sinais.py): os cards da home, a minilinha, o feed /sinais.xml,
o bloco das páginas dos boletins e o que o build faz com um data/sinais.json ausente ou velho.

Monta a pasta do site como o build_site.sh antes do src.estatico. Os testes com os dados versionados
não fixam valores: conferem os cards e o feed contra o data/sinais.json e o dashboard.json da hora.
Os de ordem, limite, mês vazio e minilinha usam séries e sinais sintéticos.
"""

from __future__ import annotations

import copy
import html
import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from src import config
from src import sinais as S
from src.estatico import boletins, cabecalho, formato as F, sinais as ES
from src.estatico.contexto import URL_BASE, Contexto, ErroEstatico

RAIZ = Path(__file__).resolve().parents[1]
ATOM = "{http://www.w3.org/2005/Atom}"
INDEX = (RAIZ / "dashboard" / "index.html").read_text(encoding="utf-8")


def _site(pasta: Path, dados: dict | None = None) -> Path:
    site = pasta / "site"
    shutil.copytree(RAIZ / "dashboard", site, ignore=shutil.ignore_patterns("*.gif", "print*.png", "preview.png"))
    if dados is None:
        shutil.copy(config.PROCESSED_DIR / "dashboard.json", site / "dashboard.json")
    else:
        (site / "dashboard.json").write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    (site / "boletim.json").write_text("{}", encoding="utf-8")
    return site


def _ctx(pasta: Path, dados: dict | None = None, raiz: Path = RAIZ, atualizado: str | None = "2026-10-15") -> Contexto:
    return Contexto.carregar(_site(pasta, dados), atualizado, raiz=raiz)


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    c = _ctx(tmp_path_factory.mktemp("sinais"))
    ES.gerar(c)
    return c


@pytest.fixture(scope="module")
def doc():
    return S.ler()


@pytest.fixture(scope="module")
def painel():
    return json.loads((config.PROCESSED_DIR / "dashboard.json").read_text(encoding="utf-8"))


def _secao(pagina: str) -> str:
    m = re.search(r'<section class="bloco sinais" id="sinais"[^>]*>.*?</section>', pagina, re.S)
    assert m
    return m.group(0)


def _cards(pagina: str) -> list[str]:
    return re.findall(r'<li class="cartao sinal".*?</li>', _secao(pagina), re.S)


def _texto(trecho: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", trecho)).replace("\u00a0", " ")).strip()


def _frase_do_card(card: str) -> str:
    return html.unescape(re.search(r'<p class="sinal-frase"[^>]*>(.*?)</p>', card).group(1)).replace("US$\u00a0", "US$ ")


# --- Séries e sinais sintéticos ------------------------------------------------------------------


def _per(n: int) -> list[str]:
    return [f"{2015 + i // 12}-{i % 12 + 1:02d}" for i in range(n)]


def _painel(cif: list, t: list | None = None) -> dict:
    """dashboard.json mínimo: só o NPK do bloco "mensal" (o src.sinais pula os blocos que faltam)."""
    p = _per(len(cif))
    return {"meta": {"periodo": {"inicio": p[0], "fim": p[-1]}}, "mensal": {"periodos": p, "NPK": {"t": t or [100_000] * len(cif), "preco_cif": cif}}}


def _sinal(produto: str, tipo: str, nivel: str, var: float, mes: str = "2026-09") -> dict:
    c = {"base": S.BASES[tipo], "valor": 100.0, "variacao_pct": var}
    c.update({
        "media_12m": {"janela_meses": 12, "meses_validos": 12},
        "variacao_3m": {"mes": "2026-06", "janela_meses": 3},
        "recorde": {"mes": "2026-08", "desde": "2015-01", "meses_validos": 100},
        "internacional": {"mes": "2026-07", "janela_meses": 2, "pink_serie": "DAP", "proxy": produto == "map",
                          "brasil_valor": 100.0, "brasil_anterior": 100.0, "brasil_variacao_pct": 0.0},
        "troca_p90": {"percentil": 90.0, "meses_validos": 100},
        "ritmo_importacao": {"mes": "2025-09"},
    }[tipo])
    metrica, unidade = S.METRICAS[tipo]
    s = {"id": f"{mes}/{produto}/{tipo}", "mes": mes, "produto": produto, "tipo": tipo, "direcao": "alta" if var > 0 else "queda",
         "metrica": metrica, "valor": 130.0 if tipo != "ritmo_importacao" else 130_000, "unidade": unidade, "comparacao": c,
         "nivel": nivel, "ancora": S.ANCORA_TROCA if tipo == "troca_p90" else S.PRODUTOS[produto][1]}
    s["frase"] = S.frase(s)
    return s


# --- Ordem, limite e mês vazio ------------------------------------------------------------------


def test_fortes_primeiro_e_depois_o_maior_desvio():
    lista = [
        _sinal("ureia", "media_12m", "atencao", 35.0),
        _sinal("kcl", "variacao_3m", "forte", -31.0),
        _sinal("map", "media_12m", "forte", 80.0),
        _sinal("dap", "ritmo_importacao", "atencao", -49.0),
        _sinal("tsp", "recorde", "forte", 6.0),
        _sinal("npk", "ritmo_importacao", "forte", -31.0),  # empate com o KCl: fica a ordem de entrada
    ]
    ordem = [s["id"] for s in ES.ordenar(lista)]
    assert ordem == ["2026-09/map/media_12m", "2026-09/kcl/variacao_3m", "2026-09/npk/ritmo_importacao", "2026-09/tsp/recorde",
                     "2026-09/dap/ritmo_importacao", "2026-09/ureia/media_12m"]


def _doc_sintetico(sinais: list[dict], fim: str = "2026-09") -> dict:
    produtos = {k: {"nome": S.PRODUTOS[k][0], "ancora": S.PRODUTOS[k][1]} for k in S.PRODUTOS}
    return {"versao": 1, "periodo": {"inicio": "2015-01", "fim": fim}, "fonte": S.FONTE, "limites": S.limites_config(),
            "produtos": produtos, "notas": [], "sinais": sinais}


def test_no_maximo_seis_cards_e_o_resto_na_pagina_do_boletim(tmp_path):
    c = _ctx(tmp_path)
    mes = c.periodos[-1]
    tipos = ["media_12m", "variacao_3m", "ritmo_importacao", "recorde"]
    produtos = ["ureia", "kcl", "map", "dap", "tsp", "npk", "sulfato_amonio"]
    lista = [_sinal(p, tipos[k % 4], "forte" if k % 3 == 0 else "atencao", 20.0 + k, mes) for k, p in enumerate(produtos)]
    lista.append(_sinal("ureia", "internacional", "atencao", 12.0, mes))
    doc = _doc_sintetico(lista, mes)
    lead, corpo = ES.secao(c, doc)
    cards = re.findall(r'<li class="cartao sinal".*?</li>', corpo, re.S)
    assert len(cards) == ES.MAX_CARTOES < len(lista)
    esperados = ES.ordenar(doc["sinais"])[: ES.MAX_CARTOES]
    assert [_frase_do_card(k) for k in cards] == [s["frase"] for s in esperados]
    niveis = [re.search(r'data-nivel="(\w+)"', k).group(1) for k in cards]
    assert niveis == sorted(niveis, key=S.NIVEIS.index)  # fortes primeiro
    texto = _texto(corpo)
    n_fortes = sum(s["nivel"] == "forte" for s in lista)
    assert f"Os {ES.MAX_CARTOES} principais dos {len(lista)} sinais de {F.rotulo_mes_longo(c.periodos[-1])} ({n_fortes} fortes)." in texto
    assert f'href="boletim/{c.periodos[-1]}/#sinais"' in corpo and "Ver todos na página do boletim" in texto
    assert F.rotulo_mes_longo(c.periodos[-1]) in lead and f"{len(doc['produtos'])} produtos" in lead
    assert lead.endswith("Os fortes vêm primeiro.")  # fortes e de atenção entre os cards


def test_mes_sem_sinais_mostra_uma_linha(tmp_path):
    dados = _painel([300.0] * 48)  # série estável: nenhuma regra dispara
    c = _ctx(tmp_path, dados, raiz=tmp_path)  # sem data/sinais.json: sai do dashboard.json
    ES.gerar(c)
    secao = _secao(c.html)
    assert "<li" not in secao.split('id="sinais-corpo"', 1)[1].split("sinais-rodape", 1)[0]
    mes = F.rotulo_mes_longo(dados["mensal"]["periodos"][-1])
    assert f'<p class="sinais-vazio">Nenhum sinal de preço ou de volume em {mes}: nenhum produto passou dos limites das regras.</p>' in secao
    assert "Os fortes vêm primeiro" not in secao  # sem card, sem ordem para explicar
    assert ' hidden' not in re.search(r'<section class="bloco sinais"[^>]*>', secao).group(0)
    feed = ET.fromstring((c.site / ES.FEED).read_text(encoding="utf-8"))
    assert feed.findall(f"{ATOM}entry") == []  # sem mês com sinal, sem entrada (o feed continua válido)
    assert feed.find(f"{ATOM}updated").text == "2026-10-15T00:00:00Z"


# --- Home com os dados versionados -----------------------------------------------------------------


def test_cards_do_ultimo_mes_iguais_ao_sinais_json(ctx, doc):
    mes = doc["periodo"]["fim"]
    assert mes == ctx.ultimo_mes
    esperados = ES.ordenar(S.sinais_do_mes(doc, mes))
    cards = _cards(ctx.html)
    assert len(cards) == min(len(esperados), ES.MAX_CARTOES)
    assert [_frase_do_card(k) for k in cards] == [s["frase"] for s in esperados[: len(cards)]]
    for card, s in zip(cards, esperados):
        assert f'data-nivel="{s["nivel"]}"' in card
        assert f'<span class="sinal-nivel">{ES.NIVEL[s["nivel"]]}</span>' in card  # o nível em texto, não só na cor
        assert f'<span class="sinal-tipo">{html.escape(ES.rotulo_tipo(s))}</span>' in card
    secao = _secao(ctx.html)
    assert f'id="sinais-lead">{html.escape(F.rotulo_mes_longo(mes))}' not in secao  # o lead é uma frase, não só o mês
    assert F.rotulo_mes_longo(mes) in _texto(re.search(r'id="sinais-lead">(.*?)</p>', secao).group(1))
    assert f"Fonte: {doc['fonte']}." in _texto(secao)
    assert "sem IA" in _texto(secao)


def test_secao_escondida_sem_o_build_e_visivel_depois(ctx):
    original = re.search(r'<section class="bloco sinais" id="sinais"[^>]*>', INDEX).group(0)
    assert " hidden" in original
    assert '<p class="bloco-lead" id="sinais-lead"></p>' in INDEX and '<div class="sinais-corpo" id="sinais-corpo"></div>' in INDEX
    assert " hidden" not in re.search(r'<section class="bloco sinais" id="sinais"[^>]*>', ctx.html).group(0)
    # sem número no kicker (não é um bloco numerado), logo depois do hero e antes dos filtros
    assert re.search(r'id="sinais"[^>]*>\s*<header class="bloco-cabecalho">\s*<p class="kicker">Sinais</p>', INDEX)
    assert INDEX.index('id="inicio"') < INDEX.index('id="sinais"') < INDEX.index('class="filtros"') < INDEX.index('<main id="conteudo">')
    menu = re.search(r'<nav class="nav-pilula" id="nav-secoes".*?</nav>', INDEX, re.S).group(0)
    assert re.findall(r'data-secao="([\w-]+)"', menu)[:2] == ["sinais", "boletim"]
    cabeca = INDEX.split("</head>", 1)[0]
    assert '<link rel="alternate" type="application/atom+xml" title="Graaos · Fertilizantes: sinais do mês" href="sinais.xml">' in cabeca


def test_links_dos_cards_so_para_ancoras_que_existem(ctx):
    ids = ES.ids_da_pagina(ctx.html)
    secao = _secao(ctx.html)
    internos = re.findall(r'href="#([^"]+)"', secao)
    assert internos, "nenhum card com link"
    for alvo in internos:
        assert alvo in ids, alvo
    for card in _cards(ctx.html):
        link = re.search(r'<a class="sinal-link" href="#([^"]+)" data-secao="([^"]+)" aria-describedby="(sinal-frase-\d+)">([^<]+)</a>', card)
        if link:
            assert link.group(1) == link.group(2)  # data-secao: o hero.js rola sem trocar o hash (que é dos filtros)
            assert f'id="{link.group(3)}"' in card and link.group(4).startswith("Ver ")


def test_card_sem_a_ancora_na_pagina_fica_sem_link(tmp_path, capsys):
    c = _ctx(tmp_path)
    c.html = c.html.replace('id="secao-bm"', 'id="secao-bm-outra"')
    ES.gerar(c)
    assert 'href="#secao-bm"' not in _secao(c.html)
    if any(s["ancora"] == "#secao-bm" for s in ES.do_mes(ES.documento(c), c.ultimo_mes)[: ES.MAX_CARTOES]):
        assert "a âncora #secao-bm não existe no index.html" in capsys.readouterr().err


def test_regras_e_ressalvas_com_os_limites_do_config(doc):
    texto = " ".join(ES.regras(doc))
    for v in (config.SINAIS_MEDIA_PCT, config.SINAIS_VARIACAO_PCT, config.SINAIS_INTERNACIONAL_PCT, config.SINAIS_RITMO_PCT):
        assert f"{F.numero(v, 0, 1)}%" in texto
    assert f"{config.SINAIS_MEDIA_MESES} meses anteriores" in texto and f"percentil {F.numero(config.SINAIS_TROCA_PERCENTIL, 0, 1)}" in texto
    # as condições que completam cada regra: meses válidos mínimos e o quanto o Brasil precisa andar para "acompanhar"
    assert f"pelo menos {config.SINAIS_MEDIA_MIN_VALIDOS} deles válidos" in texto
    assert f"pelo menos {config.SINAIS_RECORDE_MIN_MESES} deles" in texto and f"pelo menos {config.SINAIS_TROCA_MIN_MESES} deles" in texto
    assert f"menos de {F.numero(100 * config.SINAIS_INTERNACIONAL_FRACAO, 0, 1)}% disso" in texto
    assert F.toneladas(config.SINAIS_VOLUME_MIN_T) in texto
    for vol in config.SINAIS_VOLUME_MIN_T_PRODUTO.values():
        assert F.toneladas(vol) in texto
    assert "no porto" in texto and "Não é o preço ao produtor." in texto and "outro momento de contrato" in texto
    assert "R$" not in texto and "ágio" not in texto.lower()
    troca, pink = _sinal("map", "troca_p90", "forte", 20.0), _sinal("ureia", "internacional", "atencao", 15.0)
    assert ES.ressalvas([troca]) == [ES.RESSALVA_TROCA] and "Não é o preço ao produtor." in ES.RESSALVA_TROCA
    assert ES.ressalvas([pink]) == [ES.RESSALVA_PINK] and ES.fontes([pink]) == ["Comex Stat/MDIC", "Banco Mundial (Pink Sheet)"]
    assert ES.fontes([troca]) == ["Comex Stat/MDIC"] and ES.ressalvas([_sinal("kcl", "media_12m", "forte", 50.0)]) == []


# --- Minilinha ----------------------------------------------------------------------------------


def _pontos(d: str) -> list[list[tuple[float, float]]]:
    """Os trechos de um path "M x y L x y ... M ..." (o "h0" de um ponto isolado vira um ponto só)."""
    trechos = []
    for parte in re.findall(r"M[^M]+", d):
        nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", parte.replace("h0", ""))]
        trechos.append(list(zip(nums[0::2], nums[1::2])))
    return trechos


def test_minilinha_proporcional_aos_valores_e_com_vazios(tmp_path):
    n = 48
    cif = [300.0 + (k % 5) * 10 for k in range(n)]
    cif[-1] = 520.0  # alta forte no último mês
    t = [100_000] * n
    t[-5] = 5_000  # mês sem o volume mínimo: fica sem ponto
    dados = _painel(cif, t)
    lista = [s for s in S.calcular(dados) if s["mes"] == dados["mensal"]["periodos"][-1] and s["tipo"] == "media_12m"]
    assert len(lista) == 1
    serie = S.series(dados, S.limites_config())["npk"]
    lin = ES.linha(serie, dados["mensal"]["periodos"], lista[0])
    janela = list(range(n - ES.MESES_LINHA, n))
    assert lin.meses == dados["mensal"]["periodos"][-ES.MESES_LINHA:]
    assert lin.valores == [cif[j] if t[j] >= config.SINAIS_VOLUME_MIN_T else None for j in janela]
    assert lin.referencia == lista[0]["comparacao"]["valor"] and "média dos 12 meses anteriores" in lin.legenda
    assert "vazios: meses sem o volume mínimo" in lin.legenda
    desenho = ES.svg(lin)
    assert 'aria-hidden="true"' in desenho and 'focusable="false"' in desenho
    trechos = _pontos(re.search(r'<path class="serie" d="([^"]+)"', desenho).group(1))
    assert len(trechos) == 2  # o mês sem volume corta a linha
    pontos = [p for tr in trechos for p in tr]
    validos = [v for v in lin.valores if v is not None]
    assert len(pontos) == len(validos)
    # y linear no valor: o maior em cima (margem), o menor embaixo
    lo, hi = min(validos + [lin.referencia]), max(validos + [lin.referencia])
    for (x, y), v in zip(pontos, validos):
        esperado = ES.MARGEM + (ES.ALTURA - 2 * ES.MARGEM) * (hi - v) / (hi - lo)
        assert abs(y - esperado) <= 0.051
    assert pontos[-1] == (ES.LARGURA - ES.MARGEM, ES.MARGEM)  # o último mês (a alta) no canto de cima, à direita
    ref = re.search(r'<path class="referencia" d="M([\d.]+) ([\d.]+)H([\d.]+)"', desenho)
    x0 = ES.MARGEM + (ES.LARGURA - 2 * ES.MARGEM) * (ES.MESES_LINHA - 1 - 12) / (ES.MESES_LINHA - 1)
    assert abs(float(ref.group(1)) - x0) <= 0.051  # a média cobre só os 12 meses anteriores
    assert '<circle class="fim"' in desenho


def test_minilinha_do_ritmo_e_da_troca_usam_toneladas_e_razao(painel, doc):
    series = S.series(painel, doc["limites"])
    periodos = painel["mensal"]["periodos"]
    vistos = set()
    for s in doc["sinais"]:
        if s["tipo"] in vistos or s["mes"] < periodos[ES.MESES_LINHA]:
            continue
        vistos.add(s["tipo"])
        lin = ES.linha(series[s["produto"]], periodos, s)
        i = periodos.index(s["mes"])
        assert len(lin.valores) == ES.MESES_LINHA and lin.meses[-1] == s["mes"]
        if s["tipo"] == "ritmo_importacao":
            assert lin.valores[-1] == pytest.approx(s["valor"], abs=0.5) and lin.marca == ES.MESES_LINHA - 1 - 12
        elif s["tipo"] == "troca_p90":
            assert lin.valores[-1] == pytest.approx(s["valor"], abs=1e-6) and lin.referencia == s["comparacao"]["valor"]
        elif s["tipo"] == "internacional":
            assert lin.extra[-1] == pytest.approx(s["valor"], abs=1e-6) and lin.valores[-1] == pytest.approx(s["comparacao"]["brasil_valor"], abs=1e-6)
        else:
            assert lin.valores[-1] == pytest.approx(s["valor"], abs=1e-6)
        assert lin.valores[-1] is not None and periodos[i - ES.MESES_LINHA + 1] == lin.meses[0]
    assert vistos == set(S.TIPOS)


def test_minilinha_tirada_do_dashboard_json(ctx, painel, doc):
    """Os valores da minilinha de cada card são os do dashboard.json, lidos aqui sem passar pelo src.sinais."""
    periodos = painel["mensal"]["periodos"]
    lim = doc["limites"]
    for s in ES.do_mes(doc, doc["periodo"]["fim"])[: ES.MAX_CARTOES]:
        lin = ES.linha(S.series(painel, lim)[s["produto"]], periodos, s)
        k = s["produto"]
        if k in ("enxofre", "rocha"):
            bloco, t, cif, peq = painel["insumos"], painel["insumos"]["produtos"][k]["t"], painel["insumos"]["produtos"][k]["cif"], painel["insumos"]["produtos"][k]["amostra_pequena"]
        elif k == "npk":
            bloco, t, cif, peq = painel["mensal"], painel["mensal"]["NPK"]["t"], painel["mensal"]["NPK"]["preco_cif"], None
        else:
            p = painel["nutrientes"]["produtos"][k]
            bloco, t, cif, peq = painel["nutrientes"], p["t"], p["cif"], p["amostra_pequena"]
        assert bloco["periodos"] == periodos
        vol = lim["volume_min_t_produto"].get(k, lim["volume_min_t"])
        janela = range(len(periodos) - ES.MESES_LINHA, len(periodos))
        if s["tipo"] == "ritmo_importacao":
            assert lin.valores == [t[j] for j in janela]
        elif s["tipo"] in ("media_12m", "variacao_3m", "recorde", "internacional"):
            assert lin.valores == [cif[j] if t[j] is not None and t[j] >= vol and cif[j] and not (peq and peq[j]) else None for j in janela]


# --- Feed Atom ----------------------------------------------------------------------------------


def test_feed_atom_valido_com_um_mes_por_entrada(ctx, doc):
    texto = (ctx.site / ES.FEED).read_text(encoding="utf-8")
    assert texto.startswith('<?xml version="1.0" encoding="utf-8"?>\n')
    feed = ET.fromstring(texto)
    assert feed.tag == f"{ATOM}feed" and feed.get("{http://www.w3.org/XML/1998/namespace}lang") == "pt-BR"
    assert feed.find(f"{ATOM}id").text == ES.TAG and feed.find(f"{ATOM}title").text
    assert feed.find(f"{ATOM}author/{ATOM}name").text == "Graaos"
    links = {ln.get("rel"): ln.get("href") for ln in feed.findall(f"{ATOM}link")}
    assert links == {"self": URL_BASE + "sinais.xml", "alternate": URL_BASE + "#sinais"}
    rfc3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
    assert rfc3339.fullmatch(feed.find(f"{ATOM}updated").text)
    entradas = feed.findall(f"{ATOM}entry")
    meses = [m for m in reversed(ctx.periodos[-ES.MESES_FEED:]) if S.sinais_do_mes(doc, m)]
    assert 0 < len(entradas) == len(meses) <= ES.MESES_FEED
    for e, mes in zip(entradas, meses):  # do mais novo para o mais antigo
        assert e.find(f"{ATOM}id").text == f"tag:radar.graaos.cloud,2026:sinais/{mes}"
        link = e.find(f"{ATOM}link")
        assert link.get("rel") == "alternate" and link.get("href") == f"{URL_BASE}boletim/{mes}/#sinais"
        assert rfc3339.fullmatch(e.find(f"{ATOM}updated").text) and e.find(f"{ATOM}updated").text > f"{mes}-28"
        assert e.find(f"{ATOM}updated").text <= feed.find(f"{ATOM}updated").text
        lista = ES.do_mes(doc, mes)
        assert e.find(f"{ATOM}title").text == f"Sinais de {F.rotulo_mes_longo(mes)}: {ES.contagem(lista)}"
        conteudo = e.find(f"{ATOM}content")
        assert conteudo.get("type") == "html"
        corpo = conteudo.text  # HTML escapado no XML: o parser devolve o HTML
        itens = re.findall(r"<li><strong>(Forte|Atenção)</strong> · (.*?)</li>", corpo)
        assert [html.unescape(f) for _, f in itens] == [s["frase"] for s in lista]
        assert [n for n, _ in itens] == [ES.NIVEL[s["nivel"]] for s in lista]
        assert "Fonte: Comex Stat/MDIC" in corpo
        if any(s["tipo"] == "troca_p90" for s in lista):
            assert "Não é o preço ao produtor." in corpo
    assert len({e.find(f"{ATOM}id").text for e in entradas}) == len(entradas)


def test_feed_deterministico_e_estavel_entre_builds(tmp_path, doc):
    a, b = _ctx(tmp_path / "a"), _ctx(tmp_path / "b")
    assert ES.feed(a, doc) == ES.feed(b, doc)
    sem_data = _ctx(tmp_path / "c", atualizado=None)
    feed = ET.fromstring(ES.feed(sem_data, doc))
    primeira = feed.find(f"{ATOM}entry/{ATOM}updated").text
    assert feed.find(f"{ATOM}updated").text == primeira  # sem a data do git: a da entrada mais nova


def test_headers_e_llms_com_o_feed(ctx):
    regras = cabecalho.headers(ctx)
    assert f"/sinais.xml\n  Cache-Control: {cabecalho.CACHE_CURTO}\n" in regras
    texto = cabecalho.llms(ctx)
    assert f"({URL_BASE}sinais.xml)" in texto and "/blob/main/data/sinais.json)" in texto


# --- Páginas dos boletins -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def com_boletins(tmp_path_factory):
    c = _ctx(tmp_path_factory.mktemp("sinais-boletins"))
    ES.gerar(c)
    boletins.gerar(c)
    return c


def test_paginas_dos_boletins_tem_o_bloco_de_sinais(com_boletins, doc):
    c = com_boletins
    ids = ES.ids_da_pagina(c.html)
    vazios = [m for m in c.periodos if not S.sinais_do_mes(doc, m)]
    for mes in [c.periodos[-1], c.periodos[-2], *vazios[:2], c.periodos[len(c.periodos) // 2]]:
        pagina = (c.site / "boletim" / mes / "index.html").read_text(encoding="utf-8")
        bloco = re.search(r'<section class="cartao grade sinais-boletim" id="sinais" aria-labelledby="t-sinais">.*?</section>', pagina, re.S)
        assert bloco, mes
        bloco = bloco.group(0)
        assert f'<h2 class="titulo-cartao" id="t-sinais">Sinais do mês · {F.rotulo_mes(mes)}</h2>' in bloco
        lista = ES.do_mes(doc, mes)
        if not lista:
            assert f"Nenhum sinal de preço ou de volume em {F.rotulo_mes_longo(mes)}." in _texto(bloco)
            continue
        itens = re.findall(r'<li data-nivel="(\w+)"><span class="sinal-nivel">([^<]+)</span><span class="sinal-frase">(.*?)</span>(.*?)</li>', bloco)
        assert [(n, html.unescape(f).replace("US$\u00a0", "US$ ")) for n, _, f, _ in itens] == [(s["nivel"], s["frase"]) for s in lista]
        for (_, rotulo, _, link), s in zip(itens, lista):
            assert rotulo == ES.NIVEL[s["nivel"]]
            if s["ancora"][1:] in ids:
                assert link == f'<a href="../../{s["ancora"]}">no painel</a>'
            else:
                assert link == ""
        texto = _texto(bloco)
        assert f"Fonte: {'; '.join(ES.fontes(lista))}." in texto and "sem IA" in texto and "dados até o mês" in texto
        if any(s["tipo"] == "troca_p90" for s in lista):
            assert "no porto" in texto and "Não é o preço ao produtor." in texto
        if any(s["tipo"] == "internacional" for s in lista):
            assert ES.RESSALVA_PINK in texto
            assert "Banco Mundial (Pink Sheet)" in re.search(r'<footer class="rodape">(.*?)</footer>', pagina, re.S).group(1)
        assert "R$" not in bloco and "ágio" not in bloco.lower()


# --- data/sinais.json no build ----------------------------------------------------------------------


def test_sem_sinais_json_os_sinais_saem_do_dashboard(tmp_path, capsys, doc):
    c = _ctx(tmp_path, raiz=tmp_path)
    assert ES.documento(c)["sinais"] == doc["sinais"]
    assert "sem data/sinais.json" in capsys.readouterr().err


@pytest.mark.parametrize("estragar, mensagem", [
    (lambda d: d["sinais"].pop(), "não é o que sai do dashboard.json"),
    (lambda d: d.update(versao=2), "inválido"),
    (lambda d: d["sinais"][0].update(frase="outra"), "inválido"),
])
def test_sinais_json_velho_ou_fora_do_formato_derruba_o_build(tmp_path, doc, estragar, mensagem):
    raiz = tmp_path / "raiz"
    (raiz / "data").mkdir(parents=True)
    ruim = copy.deepcopy(doc)
    estragar(ruim)
    (raiz / "data" / "sinais.json").write_text(json.dumps(ruim, ensure_ascii=False), encoding="utf-8")
    c = _ctx(tmp_path, raiz=raiz)
    with pytest.raises(ErroEstatico, match=mensagem):
        ES.gerar(c)


def test_so_biblioteca_padrao():
    import subprocess
    import sys

    codigo = "import sys, src.estatico.sinais; print(sorted(m for m in ('pandas', 'numpy', 'requests', 'pyarrow') if m in sys.modules))"
    r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, check=True)
    assert r.stdout.strip() == "[]"
