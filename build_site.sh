#!/usr/bin/env bash
# Monta o site estático do dashboard em site/ (ou no diretório passado como 1º argumento).
#
# Usado pelo deploy na Cloudflare (wrangler.jsonc: "assets.directory": "./site") e pelo
# GitHub Pages (.github/workflows/pages.yml, em _site). O index.html busca tudo por caminho
# relativo à própria página, então os dados ficam na raiz do site:
#   index.html, assets/   <- dashboard/ (assets/mapa-pontos.json é a base do mapa; assets/lista-espera.js, o
#                            formulário da lista de espera, que só fala com a Edge Function do Supabase)
#   dashboard.json        <- data/processed/dashboard.json (todos os gráficos e o mapa de fluxos)
#   boletim.json          <- boletins/latest.json ({} enquanto não houver boletim)
#   favicon-*.png, apple-touch-icon.png, site.webmanifest <- dashboard/ (ícones e manifest)
#   robots.txt, sitemap.xml, 404.html, llms.txt, _headers <- gerados pelo src/estatico (cabecalho.py),
#                            que também põe ?v=<hash> em toda referência a assets/ (cache longo no _headers)
# Sem segredos e sem rede. Termina com erro (exit 1) se faltar o index.html ou algum dado, ou
# se algum JSON for inválido: melhor um deploy que falha do que um site no ar sem dados.
set -euo pipefail

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
saida="${1:-site}"
case "$saida" in /*) ;; *) saida="$raiz/$saida" ;; esac

falhar() {
  echo "build_site.sh: ERRO: $*" >&2
  exit 1
}

[[ -f "$raiz/dashboard/index.html" ]] || falhar "dashboard/index.html não existe"
[[ -f "$raiz/data/processed/dashboard.json" ]] || falhar "data/processed/dashboard.json não existe (gere com python -m src.transform)"
[[ "$saida" != "$raiz" && "$saida" != "/" ]] || falhar "diretório de saída inválido: $saida"

rm -rf "$saida"
mkdir -p "$saida"
cp -R "$raiz/dashboard/." "$saida/"
cp "$raiz/data/processed/dashboard.json" "$saida/dashboard.json"
if [[ -f "$raiz/boletins/latest.json" ]]; then
  cp "$raiz/boletins/latest.json" "$saida/boletim.json"
else
  echo '{}' > "$saida/boletim.json" # sem boletim ainda: o card fica oculto, sem 404
fi

# Data da última atualização dos dados, no rodapé da página. Sem histórico do git, fica em branco.
atualizado="$(git -C "$raiz" log -1 --format=%cs -- data/processed/dashboard.json 2>/dev/null || true)"
if [[ "$atualizado" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  sed -i.bak "s|<meta name=\"atualizado\" content=\"\">|<meta name=\"atualizado\" content=\"${atualizado}\">|" "$saida/index.html"
  rm -f "$saida/index.html.bak"
  grep -q "name=\"atualizado\" content=\"${atualizado}\"" "$saida/index.html" || falhar "não consegui gravar a data de atualização no index.html"
else
  echo "build_site.sh: aviso: sem histórico do git, o rodapé fica sem a data de atualização" >&2
fi

# --- Verificações finais -------------------------------------------------------------------
for arquivo in index.html dashboard.json boletim.json assets/mapa-pontos.json assets/fluxos.js assets/hero.js assets/mapa-hero.js assets/lista-espera.js assets/radar.css; do
  [[ -s "$saida/$arquivo" ]] || falhar "falta $arquivo em $saida"
done
# a página busca "dashboard.json" e "boletim.json" ao lado do index.html
grep -q '"dashboard.json"' "$saida/index.html" || falhar "o index.html não busca dashboard.json na raiz do site; ajuste este script"
grep -q '"boletim.json"' "$saida/index.html" || falhar "o index.html não busca boletim.json na raiz do site; ajuste este script"

# JSON válido e com os blocos que a página lê
validar='
const fs = require("fs");
const [arquivo, ...chaves] = process.argv.slice(1);
let dados;
try { dados = JSON.parse(fs.readFileSync(arquivo, "utf8")); } catch (e) { console.error(e.message); process.exit(1); }
const faltam = chaves.filter((k) => !(k in dados));
if (faltam.length) { console.error(`sem as chaves ${faltam.join(", ")}`); process.exit(1); }
'
validar_py='
import json, sys
arquivo, *chaves = sys.argv[1:]
with open(arquivo, encoding="utf-8") as f:
    dados = json.load(f)
faltam = [k for k in chaves if k not in dados]
if faltam:
    sys.exit("sem as chaves " + ", ".join(faltam))
'
checar_json() { # arquivo [chaves obrigatórias...]
  local saida_erro
  if command -v python3 > /dev/null 2>&1; then
    saida_erro="$(python3 -c "$validar_py" "$@" 2>&1)" || falhar "$(basename "$1") inválido: ${saida_erro##*$'\n'}"
  elif command -v node > /dev/null 2>&1; then
    saida_erro="$(node -e "$validar" "$@" 2>&1)" || falhar "$(basename "$1") inválido: ${saida_erro##*$'\n'}"
  else
    falhar "sem python3 nem node para validar $1"
  fi
}
checar_json "$saida/dashboard.json" meta mensal anual origens urfs rotas mapa
checar_json "$saida/boletim.json"
checar_json "$saida/assets/mapa-pontos.json" grade paises

# --- Conteúdo estático, páginas dos boletins e arquivos de indexação --------------------------
# src/estatico (só biblioteca padrão) escreve no HTML o que dá para ler sem JavaScript, gera as
# páginas boletim/AAAA-MM/ e os arquivos de indexação, sempre a partir do dashboard.json e do
# boletim.json acima: nenhum número escrito à mão.
command -v python3 > /dev/null 2>&1 || falhar "sem python3 para gerar o conteúdo estático (src/estatico)"
opcoes_estatico=()
[[ "$atualizado" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && opcoes_estatico=(--atualizado "$atualizado")
( cd "$raiz" && python3 -m src.estatico "$saida" ${opcoes_estatico[@]+"${opcoes_estatico[@]}"} ) || falhar "src/estatico não gerou o conteúdo estático"

# Arquivos de indexação e ícones (o src/estatico já confere a versão ?v= de cada referência a assets/)
for arquivo in robots.txt sitemap.xml 404.html llms.txt _headers site.webmanifest favicon-32.png favicon-192.png favicon-512.png apple-touch-icon.png; do
  [[ -s "$saida/$arquivo" ]] || falhar "falta $arquivo em $saida"
done
checar_json "$saida/site.webmanifest" name icons start_url
validar_indexacao='
import json, re, sys, xml.etree.ElementTree as ET
site = sys.argv[1]
ET.parse(site + "/sitemap.xml")
html = open(site + "/index.html", encoding="utf-8").read()
blocos = re.findall(r"<script type=\"application/ld\+json\">(.*?)</script>", html, re.S)
if len(blocos) != 1:
    sys.exit(f"esperava um JSON-LD no index.html, achei {len(blocos)}")
tipos = {item.get("@type") for item in json.loads(blocos[0])["@graph"]}
if not {"WebSite", "Organization", "Dataset"} <= tipos:
    sys.exit("JSON-LD sem WebSite, Organization ou Dataset")
if "Sitemap: " not in open(site + "/robots.txt", encoding="utf-8").read():
    sys.exit("robots.txt sem o sitemap")
'
saida_erro="$(python3 -c "$validar_indexacao" "$saida" 2>&1)" || falhar "indexação inválida: ${saida_erro##*$'\n'}"

echo "build_site.sh: site montado em $saida"
for arquivo in index.html dashboard.json boletim.json assets/mapa-pontos.json; do
  printf '  %-24s %s bytes\n' "$arquivo" "$(wc -c < "$saida/$arquivo" | tr -d ' ')"
done
