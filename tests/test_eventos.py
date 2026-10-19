"""Marcos de mercado: o parser de data/eventos.yml (src/eventos.py) e a etapa do build que põe os
eventos no index.html (src/estatico/marcos.py). Sem rede."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src import eventos as E
from src.estatico import marcos as M
from src.estatico.contexto import Contexto, ErroEstatico

RAIZ = Path(__file__).resolve().parent.parent
INDEX = RAIZ / "dashboard" / "index.html"
VALIDO = """\
# comentário no topo

- data: 2026-03-15            # dia
  titulo: "China: suspende a exportação # de ureia"
  fonte_url: https://www.exemplo.gov.br/noticia?id=1#trecho
  produtos: [ureia, "map"]    # duas chaves
-
    data: 2024-06
    titulo: 'Porto d''água fecha'
    fonte_url: https://exemplo.org/b
    produtos: [kcl]
-   data: 2025-01-02
    titulo: Texto sem aspas, com vírgula e (parênteses)
    fonte_url: https://dados.exemplo.br:8443/a/b.pdf
    produtos: [ enxofre , rocha ]
"""


def _evento(**campos) -> str:
    base = {"data": "2026-03", "titulo": "Evento", "fonte_url": "https://exemplo.gov.br/a", "produtos": "[kcl]"}
    base.update(campos)
    linhas = [f"{k}: {v}" for k, v in base.items() if v is not None]
    return "- " + "\n  ".join(linhas) + "\n"


# --- Parser: casos válidos ----------------------------------------------------------------
def test_le_o_subconjunto_do_yaml_em_ordem_de_data():
    eventos = E.analisar(VALIDO)
    assert eventos == [
        {"data": "2024-06", "titulo": "Porto d'água fecha", "fonte_url": "https://exemplo.org/b", "produtos": ["kcl"]},
        {"data": "2025-01-02", "titulo": "Texto sem aspas, com vírgula e (parênteses)", "fonte_url": "https://dados.exemplo.br:8443/a/b.pdf", "produtos": ["enxofre", "rocha"]},
        {"data": "2026-03-15", "titulo": "China: suspende a exportação # de ureia", "fonte_url": "https://www.exemplo.gov.br/noticia?id=1#trecho", "produtos": ["ureia", "map"]},
    ]


@pytest.mark.parametrize("texto", ["", "\n\n", "# só comentários\n  # recuado\n", "[]\n", "# nada\n[]   # lista vazia\n\n# fim\n"])
def test_arquivo_sem_eventos(texto):
    assert E.analisar(texto) == []


def test_escapes_bom_e_fim_de_linha_do_windows(tmp_path):
    texto = '- data: 2026-01\r\n  titulo: "Aspas \\"duplas\\", barra \\\\ e \\/"\r\n  fonte_url: https://a.gov.br\r\n  produtos: [npk]\r\n'
    arquivo = tmp_path / "eventos.yml"
    arquivo.write_bytes(b"\xef\xbb\xbf" + texto.encode("utf-8"))
    assert E.ler(arquivo)[0]["titulo"] == 'Aspas "duplas", barra \\ e /'


def test_mesma_data_fica_na_ordem_do_arquivo():
    texto = _evento(data="2026-03", titulo="B") + _evento(data="2025-12", titulo="Z") + _evento(data="2026-03", titulo="A")
    assert [e["titulo"] for e in E.analisar(texto)] == ["Z", "B", "A"]


def test_arquivo_do_repositorio_e_valido_e_o_exemplo_comentado_tambem():
    texto = (RAIZ / E.ARQUIVO).read_text(encoding="utf-8")
    assert E.ler() == E.ler(RAIZ / E.ARQUIVO)  # vazio hoje; o maintainer preenche
    # o exemplo comentado, sem o "# ", é um evento válido
    exemplo = "\n".join(linha[2:] for linha in texto.splitlines() if re.match(r"# (- |  )\w+:", linha))
    eventos = E.analisar(exemplo)
    assert len(eventos) == 1 and set(eventos[0]) == set(E.CAMPOS)
    # as chaves de produto listadas no cabeçalho são as do parser
    lista = re.search(r"com as chaves: (.*\n(?:# {14}.*\n)*)", texto).group(1)
    assert re.findall(r"[a-z_]+", lista) == list(E.PRODUTOS)


def test_dominio_sem_www():
    assert E.dominio("https://www.gov.br/agricultura/x") == "gov.br"
    assert E.dominio("https://WWW2.Exemplo.org:8443/") == "www2.exemplo.org"


# --- Parser: casos inválidos ----------------------------------------------------------------
INVALIDOS = [
    # estrutura
    ("eventos:\n  - data: 2026-01\n", 1, "cada evento começa com '- '"),
    ("data: 2026-01\n", 1, "cada evento começa com '- '"),
    ("-data: 2026-01\n", 1, "falta um espaço depois do '-'"),
    ("-# comentário\n", 1, "falta um espaço depois do '-'"),
    ("  titulo: x\n", 1, "antes do primeiro evento"),
    ("- data: 2026-01\n\ttitulo: x\n", 2, "tabulação"),
    ("- data: 2026-01\n   titulo: x\n", 2, "recuo de 3 espaços"),
    ("-\n    data: 2026-01\n  titulo: x\n", 3, "recuo de 2 espaços"),
    ("- data: 2026-01\n  titulo: Um título\n    que continua\n", 3, "recuo de 4 espaços"),
    ("- data: 2026-01\n  produtos:\n    - kcl\n", 2, "sem valor"),
    ("- data: 2026-01\n  - kcl\n", 2, "lista dentro do evento"),
    ("[]\n- data: 2026-01\n", 2, "depois da lista vazia"),
    ("[a, b]\n", 1, "não uma lista entre colchetes"),
    # campos
    (_evento(cor="azul"), 5, "campo desconhecido 'cor'"),
    (_evento(**{"título": "x"}), 5, "campo desconhecido 'título'"),
    ("- data: 2026-01\n  data: 2026-02\n", 2, "aparece duas vezes"),
    (_evento(fonte_url=None), 1, "sem fonte_url"),
    ("- data: 2026-01\n", 1, "sem titulo, fonte_url, produtos"),
    ("- data:2026-01\n", 1, "falta um espaço depois de 'data:'"),
    ("- data\n", 1, "esperava 'campo: valor'"),
    (_evento(titulo=""), 2, "sem valor"),
    (_evento(titulo="   # só comentário"), 2, "sem valor"),
    # valores
    (_evento(titulo="|"), 2, "não pode começar com '|'"),
    (_evento(titulo=">-"), 2, "não pode começar com '>'"),
    (_evento(titulo="&ancora x"), 2, "não pode começar com '&'"),
    (_evento(titulo="*ref"), 2, "não pode começar com '*'"),
    (_evento(titulo="- item"), 2, "não pode começar com '-'"),
    (_evento(titulo='"sem fechar'), 2, "aspas sem fechar"),
    (_evento(titulo="'sem fechar"), 2, "aspas sem fechar"),
    (_evento(titulo='"quebra \\n de linha"'), 2, "escape \\n não aceito"),
    (_evento(titulo='"fechado" e mais'), 2, "texto depois de o valor entre aspas"),
    (_evento(titulo='"fechado"# colado'), 2, "texto depois de o valor entre aspas"),
    (_evento(titulo="China: suspende"), 2, "ponha o valor entre aspas"),
    (_evento(titulo="termina com dois pontos:"), 2, "ponha o valor entre aspas"),
    (_evento(titulo="null"), 2, "outro sentido em YAML"),
    (_evento(titulo="~"), 2, "outro sentido em YAML"),
    (_evento(titulo="Yes"), 2, "outro sentido em YAML"),
    (_evento(titulo="[ureia]"), 2, "o título é um texto, não uma lista"),
    (_evento(produtos="[kcl, ]"), 4, "item vazio"),
    (_evento(produtos="[, kcl]"), 4, "item vazio"),
    (_evento(produtos="[kcl, [map]]"), 4, "lista dentro de lista"),
    (_evento(produtos="[kcl, map"), 4, "sem ']' no fim"),
    (_evento(produtos="[kcl] map"), 4, "texto depois de a lista"),
    (_evento(produtos="[kcl: x]"), 4, "ponha o valor entre aspas"),
    # data
    (_evento(data="2026/03/15"), 1, "fora do formato"),
    (_evento(data="2026-3"), 1, "fora do formato"),
    (_evento(data="15-03-2026"), 1, "fora do formato"),
    (_evento(data="2026-03-15T10:00"), 1, "fora do formato"),
    (_evento(data='"2026-03-1"'), 1, "fora do formato"),
    (_evento(data="2026-02-30"), 1, "não existe"),
    (_evento(data="2026-13"), 1, "não existe"),
    (_evento(data="2026-00"), 1, "não existe"),
    (_evento(data="[2026-01]"), 1, "fora do formato"),
    # título
    (_evento(titulo='"   "'), 2, "título vazio"),
    (_evento(titulo='"com\u200binvisível"'), 2, "invisível"),
    (_evento(titulo='"com\x07controle"'), 2, "controle"),
    (_evento(titulo='"separador\u2028de linha"'), 2, "invisível"),
    (_evento(titulo="x" * 161), 2, "o máximo é 160"),
    # fonte
    (_evento(fonte_url="http://exemplo.gov.br/a"), 3, "precisa começar com https://"),
    (_evento(fonte_url="ftp://exemplo.gov.br/a"), 3, "precisa começar com https://"),
    (_evento(fonte_url="exemplo.gov.br/a"), 3, "precisa começar com https://"),
    (_evento(fonte_url="https://"), 3, "sem um domínio válido"),
    (_evento(fonte_url="https://localhost/a"), 3, "sem um domínio válido"),
    (_evento(fonte_url="https://192.168.0.1/a"), 3, "sem um domínio válido"),
    (_evento(fonte_url='"https://exemplo.gov.br/com espaço"'), 3, "caractere inválido"),
    (_evento(fonte_url="https://exemplo.gov.br/notícia"), 3, "caractere inválido"),
    (_evento(fonte_url='https://exemplo.gov.br/"a"'), 3, "caractere inválido"),
    (_evento(fonte_url="https://exemplo.gov.br/<b>"), 3, "caractere inválido"),
    (_evento(fonte_url="https://usuario:senha@exemplo.gov.br/"), 3, "usuário ou senha"),
    (_evento(fonte_url="https://exemplo.gov.br:porta/"), 3, "inválida"),
    (_evento(fonte_url="https://exemplo.gov.br/" + "a" * 500), 3, "mais de 500"),
    (_evento(fonte_url="[https://exemplo.gov.br]"), 3, "não uma lista"),
    # produtos
    (_evento(produtos="kcl"), 4, "lista entre colchetes"),
    (_evento(produtos="[]"), 4, "lista de produtos vazia"),
    (_evento(produtos="[soja]"), 4, "produto desconhecido 'soja'"),
    (_evento(produtos="[KCl]"), 4, "produto desconhecido 'KCl'"),
    (_evento(produtos="[acido_sulfurico]"), 4, "produto desconhecido"),
    (_evento(produtos="[kcl, map, kcl]"), 4, "produto repetido: kcl"),
    # evento repetido (mesma data e mesmo título, sem contar maiúsculas e espaços)
    (_evento() + _evento(titulo='"  EVENTO "'), 5, "evento repetido: a linha 1"),
]


@pytest.mark.parametrize(("texto", "linha", "trecho"), INVALIDOS, ids=[f"{i:02d}" for i in range(len(INVALIDOS))])
def test_formato_invalido_e_erro_com_a_linha(texto, linha, trecho):
    with pytest.raises(E.ErroEventos) as erro:
        E.analisar(texto)
    mensagem = str(erro.value)
    assert mensagem.startswith(f"data/eventos.yml, linha {linha}: "), mensagem
    assert trecho in mensagem, mensagem


def test_a_mesma_data_com_titulos_diferentes_nao_e_repetida():
    assert len(E.analisar(_evento(titulo="A") + _evento(titulo="B"))) == 2
    assert len(E.analisar(_evento(data="2026-03") + _evento(data="2026-03-01"))) == 2


def test_arquivo_fora_do_utf8_ou_que_nao_abre(tmp_path):
    arquivo = tmp_path / "eventos.yml"
    arquivo.write_bytes("- data: 2026-01\n  titulo: ação\n".encode("latin-1"))
    with pytest.raises(E.ErroEventos, match="não está em UTF-8"):
        E.ler(arquivo)
    with pytest.raises(E.ErroEventos, match="não consegui ler"):
        E.ler(tmp_path / "nao-existe.yml")


def test_linha_de_comando(tmp_path, capsys):
    arquivo = tmp_path / "eventos.yml"
    arquivo.write_text(VALIDO, encoding="utf-8")
    assert E.main([str(arquivo)]) == 0
    saida = capsys.readouterr().out
    assert "3 eventos" in saida and "exemplo.gov.br" in saida and "www." not in saida
    arquivo.write_text(_evento(produtos="[soja]"), encoding="utf-8")
    assert E.main([str(arquivo)]) == 1
    assert "produto desconhecido 'soja'" in capsys.readouterr().err
    assert E.main([]) == 0  # o do repositório
    assert capsys.readouterr().out.startswith("data/eventos.yml: ")


# --- Build: os eventos no index.html -------------------------------------------------------
PAGINA = '<html><body><div id="dica"></div>\n<script type="application/json" id="marcos-dados"></script>\n<script>"use strict";</script></body></html>'


def _ctx(tmp_path, texto: str | None) -> Contexto:
    raiz = tmp_path / "repo"
    (raiz / "data").mkdir(parents=True)
    if texto is not None:
        (raiz / E.ARQUIVO).write_text(texto, encoding="utf-8")
    return Contexto(site=tmp_path / "site", dados={}, boletim={}, html=PAGINA, raiz=raiz)


def _inline(html: str) -> str:
    return re.search(r'<script type="application/json" id="marcos-dados">(.*?)</script>', html, re.S).group(1)


def test_build_poe_os_eventos_no_html(tmp_path):
    ctx = _ctx(tmp_path, VALIDO)
    M.gerar(ctx)
    dados = json.loads(_inline(ctx.html))
    assert [e["data"] for e in dados] == ["2024-06", "2025-01-02", "2026-03-15"]
    assert dados[2] == {"data": "2026-03-15", "titulo": "China: suspende a exportação # de ureia", "fonte_url": "https://www.exemplo.gov.br/noticia?id=1#trecho",
                        "produtos": ["ureia", "map"], "dominio": "exemplo.gov.br"}
    assert ctx.html.count('id="marcos-dados"') == 1


def test_build_sem_eventos_poe_lista_vazia(tmp_path, capsys):
    ctx = _ctx(tmp_path, (RAIZ / E.ARQUIVO).read_text(encoding="utf-8"))
    M.gerar(ctx)
    assert _inline(ctx.html) == "[]"
    assert capsys.readouterr().err == ""
    # sem o arquivo, nenhum marco, com um aviso
    ctx = _ctx(tmp_path / "sem", None)
    M.gerar(ctx)
    assert _inline(ctx.html) == "[]"
    assert "sem data/eventos.yml" in capsys.readouterr().err


def test_json_no_html_nao_fecha_o_script(tmp_path):
    titulo = "A </script><script>alert(1)</script> <!-- & assets/x.js"
    texto = f'- data: 2026-01\n  titulo: "{titulo}"\n  fonte_url: https://exemplo.gov.br/assets/a.js?x=1&y=2\n  produtos: [kcl]\n'
    ctx = _ctx(tmp_path, texto)
    M.gerar(ctx)
    bruto = _inline(ctx.html)
    assert not set(bruto) & set("<>&\u2028\u2029")
    assert "/" not in bruto.replace("\\/", "")  # toda barra vai como \/
    assert "assets\\/" in bruto and "assets/" not in bruto
    assert json.loads(bruto)[0]["titulo"] == titulo
    assert json.loads(bruto)[0]["fonte_url"] == "https://exemplo.gov.br/assets/a.js?x=1&y=2"
    assert ctx.html.count("</script>") == PAGINA.count("</script>")
    # os separadores de linha do Unicode também saem escapados (o título nunca os tem: o parser recusa)
    assert M.json_inline(["a\u2028b\u2029c"]) == '["a\\u2028b\\u2029c"]'


def test_build_com_arquivo_invalido_e_erro(tmp_path):
    ctx = _ctx(tmp_path, VALIDO + "    cor: azul\n")
    with pytest.raises(ErroEstatico, match=r"^data/eventos.yml, linha 16: campo desconhecido 'cor'"):
        M.gerar(ctx)


def test_index_html_tem_o_lugar_dos_dados_vazio_e_o_registro_com_chaves_conhecidas():
    html = INDEX.read_text(encoding="utf-8")
    assert html.count('<script type="application/json" id="marcos-dados"></script>') == 1
    registro = re.search(r"const MARCOS_GRAFICOS = \{(.*?)\};", html, re.S).group(1)
    chaves = set(re.findall(r'"([a-z_]+)"(?!\s*:)', registro))
    assert chaves and chaves <= set(E.PRODUTOS)
    # os gráficos de produto passam os produtos que mostram
    for funcao, trecho in (("desenharNutrientes", "marcos: { produtos: produtos.map((x) => x.chave) }"), ("desenharTroca", "marcos: { produtos: chaves }"),
                           ("desenharBenchmark", "marcos: { produtos: [estado.bm] }")):
        corpo = html.split(f"function {funcao}(", 1)[1].split("\nfunction ", 1)[0]
        assert trecho in corpo, funcao
    assert html.split("function desenharBenchmark(", 1)[1].split("\nfunction ", 1)[0].count("marcos: {") == 3


@pytest.mark.skipif(shutil.which("bash") is None, reason="precisa de bash")
def test_build_site_falha_com_eventos_invalidos(tmp_path):
    """O build_site.sh de verdade, numa cópia do repositório (fora do git) com um eventos.yml inválido."""
    raiz = tmp_path / "repo"
    raiz.mkdir()
    shutil.copy(RAIZ / "build_site.sh", raiz / "build_site.sh")
    shutil.copytree(RAIZ / "dashboard", raiz / "dashboard", ignore=shutil.ignore_patterns("print*.png", "preview.png", "*.gif"))
    shutil.copytree(RAIZ / "src", raiz / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (raiz / "data" / "processed").mkdir(parents=True)
    shutil.copy(RAIZ / "data" / "processed" / "dashboard.json", raiz / "data" / "processed" / "dashboard.json")
    (raiz / E.ARQUIVO).write_text(_evento(data="2026-02-30"), encoding="utf-8")
    r = subprocess.run(["bash", str(raiz / "build_site.sh"), str(raiz / "site")], capture_output=True, text=True, timeout=300)
    assert r.returncode == 1
    assert "build_site.sh: ERRO: data/eventos.yml, linha 1: data '2026-02-30' não existe" in r.stderr
    # corrigido, o mesmo build passa e põe o evento na página
    (raiz / E.ARQUIVO).write_text(_evento(data="2026-02-27"), encoding="utf-8")
    r = subprocess.run(["bash", str(raiz / "build_site.sh"), str(raiz / "site")], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    dados = json.loads(_inline((raiz / "site" / "index.html").read_text(encoding="utf-8")))
    assert [(e["data"], e["dominio"]) for e in dados] == [("2026-02-27", "exemplo.gov.br")]
