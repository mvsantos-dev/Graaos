"""Marcos de mercado (data/eventos.yml): leitura e validação, só com a biblioteca padrão.

O arquivo é uma lista YAML, um mapeamento por evento. O build do site (src/estatico/marcos.py) põe
os eventos no index.html e o script desenha uma linha vertical discreta no mês de cada um, nos
gráficos dos produtos citados, com a dica (título, data e domínio da fonte) e o link da fonte.

Só este subconjunto do YAML é aceito; qualquer coisa fora dele é erro e derruba o build:

    # comentário (linha inteira, ou depois de um espaço no fim da linha)
    - data: 2026-03-15                # AAAA-MM-DD ou AAAA-MM
      titulo: "Título curto do evento"
      fonte_url: https://exemplo.gov.br/noticia
      produtos: [ureia, map]          # chaves de PRODUTOS, entre colchetes

- cada evento começa com "- " na primeira coluna; os outros campos, alinhados com o primeiro;
- valores numa linha só: sem aspas, entre aspas duplas (escapes \\" e \\\\) ou simples ('' é
  uma aspa); valor com ": " ou " #" vai entre aspas;
- exatamente os campos data, titulo, fonte_url e produtos, sem repetir; evento repetido (mesma
  data e mesmo título) também é erro;
- um arquivo só com comentários, ou com [], não tem nenhum evento.

Uso: python -m src.eventos [arquivo]   (confere o arquivo e lista os eventos)
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ARQUIVO = "data/eventos.yml"  # relativo à raiz do repositório
RAIZ = Path(__file__).resolve().parent.parent

# Chaves de produto: as mesmas dos sinais e das âncoras do site.
PRODUTOS = {
    "ureia": "Ureia",
    "sulfato_amonio": "Sulfato de amônio",
    "kcl": "KCl",
    "map": "MAP",
    "dap": "DAP",
    "tsp": "TSP",
    "npk": "NPK",
    "enxofre": "Enxofre",
    "rocha": "Rocha fosfática",
}
CAMPOS = ("data", "titulo", "fonte_url", "produtos")
TITULO_MAX = 160  # caracteres: a dica e a linha "Marcos" são curtas
URL_MAX = 500

# Valores que o YAML leria como nulo ou booleano: só entre aspas.
_RESERVADOS = {"~", "null", "true", "false", "yes", "no", "on", "off", "y", "n"}
# Começo de valor sem aspas que o YAML leria como outra coisa (lista, mapa, âncora, bloco...).
_INDICADORES = set("[]{},&*!|>%@`")
_URL_PROIBIDOS = set('"<>\\^`{|}')


class ErroEventos(ValueError):
    """Arquivo de eventos fora do formato (o build do site para)."""


# --- Leitura do subconjunto do YAML ---------------------------------------------------------
class _Linha:
    def __init__(self, nome: str, numero: int):
        self.nome, self.numero = nome, numero

    def erro(self, mensagem: str) -> ErroEventos:
        return ErroEventos(f"{self.nome}, linha {self.numero}: {mensagem}")


def _fim(resto: str, onde: _Linha, o_que: str) -> None:
    """Depois de um valor, só espaços ou um comentário (# depois de espaço)."""
    if resto.strip() and not (resto[0].isspace() and resto.lstrip().startswith("#")):
        raise onde.erro(f"texto depois de {o_que}: {resto.strip()!r}")


def _entre_aspas(texto: str, onde: _Linha) -> tuple[str, str]:
    """Valor entre aspas no começo de `texto`: (valor, o que sobra depois da aspa final)."""
    aspa, saida, i = texto[0], [], 1
    while i < len(texto):
        c = texto[i]
        if aspa == "'" and c == "'":
            if texto[i + 1:i + 2] == "'":
                saida.append("'")
                i += 2
                continue
            return "".join(saida), texto[i + 1:]
        if aspa == '"' and c == "\\":
            seguinte = texto[i + 1:i + 2]
            if seguinte not in ('"', "\\", "/"):
                raise onde.erro(f"escape \\{seguinte} não aceito entre aspas duplas (só \\\" e \\\\)")
            saida.append(seguinte)
            i += 2
            continue
        if aspa == '"' and c == '"':
            return "".join(saida), texto[i + 1:]
        saida.append(c)
        i += 1
    raise onde.erro("aspas sem fechar (valores em várias linhas não são aceitos)")


def _sem_aspas(texto: str, onde: _Linha, na_lista: bool = False) -> tuple[str, str]:
    """Valor sem aspas: até o comentário (" #"), o fim da linha ou, numa lista, a vírgula ou o "]"."""
    if texto[0] in _INDICADORES or texto[0] in "#'\"" or texto[:2] in ("- ", "? ", ": ") or texto in ("-", "?", ":"):
        raise onde.erro(f"valor {texto.strip()!r} não pode começar com {texto[0]!r} sem aspas")
    fim = len(texto)
    m = re.search(r"\s#", texto)
    if m:
        fim = m.start()
    if na_lista:
        m = re.search(r"[,\[\]{}]", texto[:fim])
        if m:
            fim = m.start()
    valor = texto[:fim].rstrip()
    if ": " in valor or valor.endswith(":"):
        raise onde.erro(f"valor {valor!r} tem ':' seguido de espaço; ponha o valor entre aspas")
    if valor.lower() in _RESERVADOS:
        raise onde.erro(f"o valor {valor!r} tem outro sentido em YAML; ponha entre aspas")
    return valor, texto[fim:]


def _lista(texto: str, onde: _Linha) -> tuple[list[str], str]:
    """Lista entre colchetes numa linha só: [a, b, "c"]."""
    itens: list[str] = []
    resto = texto[1:].lstrip(" ")
    if resto.startswith("]"):
        return itens, resto[1:]
    while True:
        if not resto or resto[0] in ",]":
            raise onde.erro("item vazio na lista entre colchetes")
        if resto[0] == "[":
            raise onde.erro("lista dentro de lista não é aceita")
        if resto[0] in "'\"":
            item, resto = _entre_aspas(resto, onde)
        else:
            item, resto = _sem_aspas(resto, onde, na_lista=True)
        itens.append(item)
        resto = resto.lstrip(" ")
        if resto.startswith(","):
            resto = resto[1:].lstrip(" ")
            continue
        if resto.startswith("]"):
            return itens, resto[1:]
        raise onde.erro("lista sem ']' no fim (listas em várias linhas não são aceitas)")


def _valor(texto: str, onde: _Linha, campo: str) -> str | list[str]:
    if not texto.strip() or texto.lstrip(" ").startswith("#"):
        raise onde.erro(f"o campo {campo!r} está sem valor (valores em várias linhas não são aceitos)")
    texto = texto.lstrip(" ")
    if texto[0] == "[":
        valor, resto = _lista(texto, onde)
        _fim(resto, onde, "a lista")
        return valor
    if texto[0] in "'\"":
        valor, resto = _entre_aspas(texto, onde)
        _fim(resto, onde, "o valor entre aspas")
        return valor
    valor, resto = _sem_aspas(texto, onde)
    _fim(resto, onde, "o valor")
    return valor


def _campo(corpo: str, onde: _Linha, evento: dict) -> None:
    chave, dois_pontos, resto = corpo.partition(":")
    if not dois_pontos:
        raise onde.erro(f"esperava 'campo: valor', achei {corpo!r}")
    if resto and resto[0] != " ":
        raise onde.erro(f"falta um espaço depois de '{chave}:'")
    if chave not in CAMPOS:
        raise onde.erro(f"campo desconhecido {chave!r} (os campos são {', '.join(CAMPOS)})")
    if chave in evento["campos"]:
        raise onde.erro(f"o campo {chave!r} aparece duas vezes no mesmo evento")
    evento["campos"][chave] = _valor(resto, onde, chave)
    evento["linhas"][chave] = onde.numero


def ler_yaml(texto: str, nome: str = ARQUIVO) -> list[dict]:
    """Os eventos do arquivo, como estão escritos, sem validar os valores:
    [{"linha": n, "campos": {campo: valor}, "linhas": {campo: n}}]."""
    eventos: list[dict] = []
    atual: dict | None = None
    coluna: int | None = None  # coluna dos campos do evento atual
    vazio_em: int | None = None  # linha do "[]"
    # quebra de linha só \n, \r\n ou \r, como no YAML (str.splitlines também quebraria no U+2028)
    for numero, linha in enumerate(re.split(r"\r\n|\r|\n", texto), 1):
        onde = _Linha(nome, numero)
        recuo_bruto = linha[: len(linha) - len(linha.lstrip(" \t"))]
        if "\t" in recuo_bruto:
            raise onde.erro("tabulação no começo da linha; use espaços")
        corpo = linha.strip(" ")
        if not corpo or corpo.startswith("#"):
            continue
        if vazio_em is not None:
            raise onde.erro(f"nada pode vir depois da lista vazia da linha {vazio_em}")
        recuo = len(linha) - len(linha.lstrip(" "))
        if recuo == 0 and corpo.startswith("[") and not eventos and atual is None:
            valor, resto = _lista(corpo, onde)
            _fim(resto, onde, "a lista")
            if valor:
                raise onde.erro("o arquivo é uma lista de eventos, um por bloco '- data: ...', não uma lista entre colchetes")
            vazio_em = numero
            continue
        if recuo == 0 and (corpo == "-" or corpo.startswith("- ") or corpo.startswith("-#")):
            if corpo.startswith("-#"):
                raise onde.erro("falta um espaço depois do '-'")
            atual = {"linha": numero, "campos": {}, "linhas": {}}
            eventos.append(atual)
            depois = corpo[1:]
            resto = depois.lstrip(" ")
            if not resto or resto.startswith("#"):
                coluna = None  # "-" sozinho: os campos vêm nas linhas de baixo
                continue
            coluna = 1 + len(depois) - len(resto)
            _campo(resto, onde, atual)
            continue
        if recuo == 0:
            if re.match(r"(---|\.\.\.)(\s|$)", corpo):
                raise onde.erro(f"marcador de documento {corpo[:3]!r} não é aceito: o arquivo é só a lista de eventos")
            if corpo.startswith("-"):
                raise onde.erro("falta um espaço depois do '-'")
            raise onde.erro("cada evento começa com '- ' na primeira coluna (o arquivo é uma lista de eventos)")
        if atual is None:
            raise onde.erro("linha recuada antes do primeiro evento")
        if coluna is None:
            coluna = recuo
        elif recuo != coluna:
            raise onde.erro(f"recuo de {recuo} espaços; os campos do evento da linha {atual['linha']} estão a {coluna}")
        if corpo.startswith("- ") or corpo == "-":
            raise onde.erro("lista dentro do evento não é aceita (produtos vão entre colchetes: [ureia, map])")
        _campo(corpo, onde, atual)
    return eventos


# --- Validação ------------------------------------------------------------------------------
def _invisivel(texto: str) -> bool:
    return any(unicodedata.category(c) in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp") for c in texto)


def _data(valor, onde: _Linha) -> str:
    if not isinstance(valor, str) or not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", valor):
        raise onde.erro(f"data {valor!r} fora do formato AAAA-MM-DD ou AAAA-MM")
    ano, mes, dia = int(valor[:4]), int(valor[5:7]), int(valor[8:10]) if len(valor) == 10 else 1
    try:
        date(ano, mes, dia)
    except ValueError:
        raise onde.erro(f"data {valor!r} não existe") from None
    return valor


def _titulo(valor, onde: _Linha) -> str:
    if not isinstance(valor, str):
        raise onde.erro("o título é um texto, não uma lista")
    titulo = valor.strip()
    if not titulo:
        raise onde.erro("título vazio")
    if _invisivel(titulo):
        raise onde.erro("o título tem caractere de controle ou invisível")
    if len(titulo) > TITULO_MAX:
        raise onde.erro(f"título com {len(titulo)} caracteres; o máximo é {TITULO_MAX}")
    return titulo


def _url(valor, onde: _Linha) -> str:
    if not isinstance(valor, str):
        raise onde.erro("fonte_url é um endereço, não uma lista")
    if not re.fullmatch(r"[\x21-\x7e]+", valor) or set(valor) & _URL_PROIBIDOS:
        raise onde.erro(f"fonte_url {valor!r} tem espaço, acento ou caractere inválido (use o endereço codificado, com %XX)")
    if len(valor) > URL_MAX:
        raise onde.erro(f"fonte_url com mais de {URL_MAX} caracteres")
    try:
        partes = urlsplit(valor)
        partes.port  # porta inválida levanta ValueError
    except ValueError:
        raise onde.erro(f"fonte_url {valor!r} inválida") from None
    # "https://" literal, em minúsculas: o script da página só aceita assim (HTTPS:// sumiria sem erro)
    if partes.scheme != "https" or not valor.startswith("https://"):
        raise onde.erro(f"fonte_url {valor!r} precisa começar com https:// (em minúsculas)")
    if partes.username is not None or partes.password is not None:
        raise onde.erro("fonte_url com usuário ou senha não é aceita")
    host = partes.hostname or ""
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}", host):
        raise onde.erro(f"fonte_url {valor!r} sem um domínio válido")
    return valor


def _produtos(valor, onde: _Linha) -> list[str]:
    if not isinstance(valor, list):
        raise onde.erro(f"produtos vão numa lista entre colchetes, ex.: produtos: [{valor}]")
    if not valor:
        raise onde.erro("lista de produtos vazia")
    for k in valor:
        if k not in PRODUTOS:
            raise onde.erro(f"produto desconhecido {k!r} (as chaves são {', '.join(PRODUTOS)})")
    repetidos = sorted({k for k in valor if valor.count(k) > 1})
    if repetidos:
        raise onde.erro(f"produto repetido: {', '.join(repetidos)}")
    return list(valor)


def validar(brutos: list[dict], nome: str = ARQUIVO) -> list[dict]:
    """Confere cada evento e devolve [{data, titulo, fonte_url, produtos}], na ordem da data (os do
    mesmo dia, na ordem do arquivo)."""
    eventos = []
    vistos: dict[tuple, int] = {}
    for bruto in brutos:
        onde = _Linha(nome, bruto["linha"])
        campos = bruto["campos"]
        faltam = [c for c in CAMPOS if c not in campos]
        if faltam:
            raise onde.erro(f"o evento está sem {', '.join(faltam)}")
        linhas = bruto.get("linhas", {})  # o erro aponta a linha do campo
        em = {c: _Linha(nome, linhas.get(c, bruto["linha"])) for c in CAMPOS}
        evento = {
            "data": _data(campos["data"], em["data"]),
            "titulo": _titulo(campos["titulo"], em["titulo"]),
            "fonte_url": _url(campos["fonte_url"], em["fonte_url"]),
            "produtos": _produtos(campos["produtos"], em["produtos"]),
        }
        chave = (evento["data"], " ".join(evento["titulo"].split()).casefold())
        if chave in vistos:
            raise onde.erro(f"evento repetido: a linha {vistos[chave]} já tem {evento['data']} {evento['titulo']!r}")
        vistos[chave] = bruto["linha"]
        eventos.append(evento)
    return sorted(eventos, key=lambda e: e["data"])


def analisar(texto: str, nome: str = ARQUIVO) -> list[dict]:
    """Eventos válidos de um texto no formato de data/eventos.yml (ErroEventos se não for)."""
    return validar(ler_yaml(texto, nome), nome)


def ler(caminho: Path | str | None = None, nome: str | None = None) -> list[dict]:
    """Eventos válidos do arquivo (padrão: data/eventos.yml do repositório)."""
    caminho = Path(caminho) if caminho is not None else RAIZ / ARQUIVO
    nome = nome or (ARQUIVO if caminho.resolve() == (RAIZ / ARQUIVO).resolve() else str(caminho))
    try:
        texto = caminho.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ErroEventos(f"{nome}: o arquivo não está em UTF-8") from None
    except OSError as e:
        raise ErroEventos(f"{nome}: não consegui ler o arquivo ({e.strerror or e})") from None
    return analisar(texto, nome)


def dominio(url: str) -> str:
    """Domínio da fonte, para a dica: sem o "www."."""
    host = urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Confere data/eventos.yml (marcos de mercado) e lista os eventos.")
    parser.add_argument("arquivo", nargs="?", type=Path, help="padrão: data/eventos.yml")
    args = parser.parse_args(argv)
    try:
        eventos = ler(args.arquivo)
    except ErroEventos as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1
    print(f"{args.arquivo or ARQUIVO}: {len(eventos)} {'evento' if len(eventos) == 1 else 'eventos'}")
    for e in eventos:
        print(f"  {e['data']:<10}  {e['titulo']}  [{', '.join(e['produtos'])}]  {dominio(e['fonte_url'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
