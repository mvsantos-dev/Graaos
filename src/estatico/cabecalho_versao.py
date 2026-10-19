"""Versão (?v=) dos arquivos de assets/ em todas as referências do site.

O _headers põe cache de um ano (immutable) em /assets/*. Isso só é seguro se toda referência mudar
quando o arquivo muda: cada uma ganha ?v=<10 primeiros hex do sha256 do arquivo>, nas páginas
(index.html em edição e os .html já gravados) e dentro dos próprios assets (url() do CSS, como as
fontes, e as strings "assets/…" do JavaScript, como o fetch do mapa-pontos.json). Um CSS ou JS é
versionado depois das referências dele, então o hash cobre a versão final.

Onde se procura:
- HTML: fora de comentários, qualquer caminho assets/x, ../assets/x ou /assets/x (atributos,
  srcset, etc.); dentro de <script>, só strings; dentro de <style>, url().
- JavaScript (assets/*.js): strings "assets/x", resolvidas a partir da raiz do site, porque o fetch
  é relativo à página (o index.html, na raiz).
- CSS (assets/*.css): url(), resolvida a partir da pasta do CSS (fontes/x vira assets/fontes/x).

Referência a arquivo que não existe, ou que fica sem a versão certa, é erro de build.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from .contexto import Contexto, ErroEstatico

_PREFIXO = r"(?:/|\./|(?:\.\./)+)?"
_CAMINHO = r"assets/[\w.%/-]*[\w%-]"
_QUERY_FORA = r"(\?[^\s\"'<>`#)]*)?"
# no HTML (fora de script/style): o caminho em qualquer lugar, desde que não seja pedaço de outro
_REF_HTML = re.compile(r"(?<![\w/.%-])(" + _PREFIXO + _CAMINHO + r")" + _QUERY_FORA)
# no JavaScript: só dentro de string
_REF_JS = re.compile(r"(?<=[\"'`])(" + _PREFIXO + _CAMINHO + r")(\?[^\"'`\s#]*)?(?=[#\"'`])")
_URL_CSS = re.compile(r"url\(\s*([\"']?)([^\"')\s]+)\1\s*\)")
_BLOCOS_HTML = re.compile(r"(<!--.*?-->)|(<script\b[^>]*>)(.*?)(</script\s*>)|(<style\b[^>]*>)(.*?)(</style\s*>)", re.S | re.I)
_JSON_LD = re.compile(r"type=[\"']?application/ld\+json", re.I)


def hash_curto(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()[:10]


def _partes_url_css(valor: str) -> tuple[str, str | None, str] | None:
    """(caminho, ?query ou None, #fragmento ou "") de um url() do CSS; None se não for arquivo do site
    (data:, http:, //host, #id de filtro SVG)."""
    if re.match(r"(?i)(?:[a-z][\w+.-]*:|//|#|%23)", valor):
        return None
    antes, cerquilha, fragmento = valor.partition("#")
    caminho, interrogacao, query = antes.partition("?")
    return caminho, (interrogacao + query) or None, cerquilha + fragmento


class Versionador:
    """Resolve e versiona as referências (a verificação final é o Conferente, abaixo)."""

    def __init__(self, site: Path):
        self.site = Path(site).resolve()
        self.assets = self.site / "assets"
        self.hashes: dict[Path, str] = {}
        self._em_andamento: set[Path] = set()
        self.referencias = 0

    # --- Resolução ----------------------------------------------------------------------
    def _alvo(self, ref: str, base: Path, onde: str) -> Path:
        caminho = ref.split("#", 1)[0]
        alvo = self.site / caminho.lstrip("/") if caminho.startswith("/") else base / caminho
        alvo = Path(os.path.normpath(alvo))
        if self.site not in alvo.parents:
            raise ErroEstatico(f"{onde}: {ref!r} aponta para fora do site")
        if not alvo.is_file():
            raise ErroEstatico(f"{onde}: {ref!r} aponta para {alvo.relative_to(self.site)}, que não existe")
        return alvo

    def versao(self, alvo: Path) -> str:
        """Hash do arquivo final (CSS e JS de assets/ são versionados por dentro antes)."""
        if alvo in self.hashes:
            return self.hashes[alvo]
        if alvo in self._em_andamento:
            raise ErroEstatico(f"referência circular em {alvo.relative_to(self.site)}")
        self._em_andamento.add(alvo)
        if alvo.suffix in (".css", ".js") and self.assets in alvo.parents:
            texto = alvo.read_text(encoding="utf-8")
            onde = str(alvo.relative_to(self.site))
            novo = self.css(texto, alvo.parent, onde) if alvo.suffix == ".css" else self.js(texto, self.site, onde)
            if novo != texto:
                alvo.write_text(novo, encoding="utf-8")
        self._em_andamento.discard(alvo)
        self.hashes[alvo] = hash_curto(alvo.read_bytes())
        return self.hashes[alvo]

    def _trocar(self, ref: str, query: str | None, base: Path, onde: str, so_assets: bool = False) -> str | None:
        """Nova referência (com ?v=) ou None se não for de assets/."""
        alvo = self._alvo(ref, base, onde)
        if so_assets and self.assets not in alvo.parents:
            return None
        if self.assets not in alvo.parents:
            raise ErroEstatico(f"{onde}: {ref!r} não fica em assets/")
        self.referencias += 1
        return f"{ref}?v={self.versao(alvo)}"

    # --- Por tipo de texto --------------------------------------------------------------
    def css(self, texto: str, base: Path, onde: str) -> str:
        def troca(m: re.Match) -> str:
            partes = _partes_url_css(m.group(2))
            if partes is None:
                return m.group(0)
            caminho, query, fragmento = partes
            novo = self._trocar(caminho, query, base, onde, so_assets=True)
            return m.group(0) if novo is None else f"url({m.group(1)}{novo}{fragmento}{m.group(1)})"

        return _URL_CSS.sub(troca, texto)

    def js(self, texto: str, base: Path, onde: str) -> str:
        return _REF_JS.sub(lambda m: self._trocar(m.group(1), m.group(2), base, onde), texto)

    def marcacao(self, texto: str, base: Path, onde: str) -> str:
        return _REF_HTML.sub(lambda m: self._trocar(m.group(1), m.group(2), base, onde), texto)

    def html(self, texto: str, base: Path, onde: str) -> str:
        partes, fim = [], 0
        for m in _BLOCOS_HTML.finditer(texto):
            partes.append(self.marcacao(texto[fim : m.start()], base, onde))
            if m.group(1):  # comentário: fica como está
                partes.append(m.group(1))
            elif m.group(2):
                abre = self.marcacao(m.group(2), base, onde)
                corpo = m.group(3) if _JSON_LD.search(m.group(2)) else self.js(m.group(3), base, onde)
                partes.append(abre + corpo + m.group(4))
            else:
                partes.append(self.marcacao(m.group(5), base, onde) + self.css(m.group(6), base, onde) + m.group(7))
            fim = m.end()
        partes.append(self.marcacao(texto[fim:], base, onde))
        return "".join(partes)


_V = re.compile(r"\?v=([0-9a-f]{10})$")


class Conferente(Versionador):
    """Mesma busca, mas só confere: toda referência já tem ?v= com o hash do arquivo."""

    def _trocar(self, ref, query, base, onde, so_assets=False):
        alvo = self._alvo(ref, base, onde)
        if so_assets and self.assets not in alvo.parents:
            return None
        if self.assets not in alvo.parents:
            raise ErroEstatico(f"{onde}: {ref!r} não fica em assets/")
        esperado = hash_curto(alvo.read_bytes())
        m = _V.search(query or "")
        if not m:
            raise ErroEstatico(f"{onde}: {ref!r} ficou sem versão (?v=)")
        if m.group(1) != esperado:
            raise ErroEstatico(f"{onde}: {ref!r} com ?v={m.group(1)}, mas o arquivo tem {esperado}")
        self.referencias += 1
        return ref + query

    def css(self, texto, base, onde):
        for m in _URL_CSS.finditer(texto):
            partes = _partes_url_css(m.group(2))
            if partes is not None:
                self._trocar(partes[0], partes[1], base, onde, so_assets=True)
        return texto

    def versao(self, alvo):
        return hash_curto(alvo.read_bytes())


def _paginas_em_disco(site: Path) -> list[Path]:
    """Os .html do site, menos o index.html da raiz (que está em ctx.html) e os de assets/."""
    return sorted(p for p in site.rglob("*.html") if p != site / "index.html" and site / "assets" not in p.parents)


def versionar(ctx: Contexto) -> int:
    """Versiona tudo e confere. Devolve quantas referências foram versionadas."""
    v = Versionador(ctx.site)
    site = v.site
    for arquivo in sorted(site.joinpath("assets").rglob("*")):
        if arquivo.suffix in (".css", ".js"):
            v.versao(arquivo)
    ctx.html = v.html(ctx.html, site, "index.html")
    for pagina in _paginas_em_disco(site):
        texto = pagina.read_text(encoding="utf-8")
        novo = v.html(texto, pagina.parent, str(pagina.relative_to(site)))
        if novo != texto:
            pagina.write_text(novo, encoding="utf-8")
    conferir(ctx)
    return v.referencias


def conferir(ctx: Contexto) -> int:
    """Erro de build se alguma referência a assets/ ficou sem ?v= ou com o hash errado."""
    c = Conferente(ctx.site)
    site = c.site
    for arquivo in sorted(site.joinpath("assets").rglob("*")):
        onde = str(arquivo.relative_to(site))
        if arquivo.suffix == ".css":
            c.css(arquivo.read_text(encoding="utf-8"), arquivo.parent, onde)
        elif arquivo.suffix == ".js":
            c.js(arquivo.read_text(encoding="utf-8"), site, onde)
    c.html(ctx.html, site, "index.html")
    for pagina in _paginas_em_disco(site):
        c.html(pagina.read_text(encoding="utf-8"), pagina.parent, str(pagina.relative_to(site)))
    return c.referencias
