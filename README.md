# Targeted Image Collector

**Pipeline configuravel de coleta automatizada de imagens usando webscraping, busca no Google Images e validacao com IA.**

Configurable automated image collection pipeline combining web scraping, Google Images search, and AI-powered validation.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![OpenAI](https://img.shields.io/badge/OpenAI-Vision_API-412991)
![SerpAPI](https://img.shields.io/badge/SerpAPI-Google_Images-orange)
![Pydantic](https://img.shields.io/badge/Pydantic-v2-e92063)

---

## O Desafio / The Challenge

Este projeto resolve um problema fundamentalmente diferente do webscraping tradicional: em vez de extrair dados de **um unico site**, o pipeline precisa coletar imagens de **centenas de sites diferentes** — cada item da lista tem seu proprio website, com estrutura HTML, layout e padroes completamente distintos.

This project solves a fundamentally different problem from traditional web scraping: instead of extracting data from **a single site**, the pipeline needs to collect images from **hundreds of different sites** — each item in the list has its own website, with completely different HTML structures, layouts, and patterns.

Isso significa que nao e possivel criar seletores CSS especificos ou regras fixas para um dominio. O sistema precisa ser **robusto o suficiente para lidar com qualquer site**, usando multiplos metodos de extracao, heuristicas adaptaveis e validacao por IA para garantir qualidade independente da fonte.

This means it's impossible to create specific CSS selectors or fixed rules for a single domain. The system needs to be **robust enough to handle any site**, using multiple extraction methods, adaptive heuristics, and AI validation to ensure quality regardless of the source.

### Webscraping Tradicional vs Multi-site

| Aspecto | Tradicional (site unico) | Este projeto (multi-site) |
|---------|--------------------------|---------------------------|
| Estrutura HTML | Conhecida, seletores fixos | Desconhecida, varia por item |
| Extracao | CSS selectors / XPath | Multi-metodo (img, picture, srcset, CSS bg, gallery links) |
| Validacao | Posicao na pagina | IA (heuristica + Vision API) |
| Identidade | Dados estruturados | Deteccao de homonimos por texto e URL |
| Escala | N paginas de 1 site | 1-3 paginas de N sites |

Alem disso, o pipeline e **configuravel por tipo de imagem**: basta criar um arquivo YAML definindo o que coletar (fachadas de edificios, fotos de produtos, veiculos, etc.) e o sistema adapta automaticamente seus prompts, heuristicas e queries de busca.

Additionally, the pipeline is **configurable by image type**: just create a YAML file defining what to collect (building facades, product photos, vehicles, etc.) and the system automatically adapts its prompts, heuristics, and search queries.

## Arquitetura / Architecture

```
                        ┌──────────────────────┐
                        │   Input: Items        │
                        │  (id, name, city...)  │
                        └──────────┬───────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              │                                         │
              │      ┌─────────────────────┐            │
              │      │  Target Config      │            │
              │      │  (YAML)             │            │
              │      │  - keywords         │            │
              │      │  - prompts          │            │
              │      │  - search terms     │            │
              │      └──────────┬──────────┘            │
              │                 │                        │
              ▼                 ▼                        ▼
    ┌─────────────────┐     adapts      ┌──────────────────┐
    │  Phase 1: Site  │◄────────────────│ Phase 2: SerpAPI │
    │    Scraping     │                 │  Google Images   │
    │                 │                 │                  │
    │ - Multi-method  │                 │ - Prioritized    │
    │   extraction    │                 │   query builder  │
    │ - Gallery       │                 │ - Empty query    │
    │   discovery     │                 │   cache          │
    │ - URL source    │                 │ - Pre-filters    │
    │   classifier    │                 │   (dims, type)   │
    └────────┬────────┘                 └────────┬─────────┘
             │                                    │
             └──────────────┬─────────────────────┘
                            ▼
             ┌──────────────────────────────┐
             │   7-Filter Validation Pipeline│
             │                              │
             │  0.   URL validation          │
             │  0.5  Blocked domains         │
             │  1.   AI Classification       │
             │       (heuristic → Vision API)│
             │  2.   Correct item check      │
             │  2.5  Confidence threshold    │
             │  3.   Category filter         │
             │  4.   Per-item limit          │
             │  5.   Image download          │
             │  6.   Dimension check         │
             │  7.   pHash deduplication     │
             └──────────────┬───────────────┘
                            ▼
                  ┌─────────────────┐
                  │  Saved Images   │
                  │  (validated +   │
                  │   deduplicated) │
                  └─────────────────┘
```

## Funcionalidades Principais / Key Features

### Sistema de Alvos Configuraveis / Configurable Target System
- **YAML-based**: Defina o tipo de imagem (fachadas, produtos, veiculos...) em um arquivo YAML
- **Prompts dinamicos**: O prompt da Vision API e montado automaticamente a partir da config
- **Heuristicas adaptaveis**: Keywords positivas/negativas carregadas da config do alvo
- **Queries inteligentes**: Termos de busca ajustados ao tipo de alvo
- **Inclui exemplos**: `targets/facades.yaml` e `targets/products.yaml`

### Coleta Multi-site Robusta / Robust Multi-site Collection
- **Extracao multi-metodo**: `<img>`, `<picture>`, `<source>`, backgrounds CSS, srcset, data attributes, links de galerias
- **Busca Google Images**: Queries priorizadas em 5 tiers (ampla → especifica) via SerpAPI
- **Classificacao de fonte**: Comportamento diferenciado para sites oficiais vs noticias vs redes sociais
- **Deteccao de galerias**: Navega automaticamente para paginas de galeria do site

### Validacao com IA / AI Validation
- **Pipeline heuristica-primeiro**: Classificacao textual gratuita antes da API paga (economia ~40%)
- **OpenAI Vision diferenciado**: Prompts especificos por tipo de fonte (oficial, noticia, busca)
- **Cache de classificacoes**: 30 dias de TTL, evita reclassificar mesma imagem
- **Deteccao de homonimos**: Impede confusao entre itens com nomes similares na URL

### Otimizacao de Custo / Cost Optimization
- **Cache de queries vazias**: Nao repete buscas que ja retornaram sem resultados (7 dias)
- **Pre-filtros SerpAPI**: Rejeita imagens pequenas e de produto antes do download
- **Deduplicacao por pHash**: SQLite persistente com distancia Hamming configuravel
- **Checkpoint/resume**: Retoma processamento de onde parou em caso de interrupcao
- **Processamento paralelo**: ThreadPoolExecutor para download e classificacao

### Monitoramento / Monitoring
- **Metricas detalhadas**: Cache hit rate, custo estimado, rejeicoes por motivo, tempo por fase
- **Score de eficiencia**: Metrica composta de performance do pipeline
- **Validacao Pydantic**: Schemas tipados para dados de entrada e resultados de classificacao

## Estrutura / Structure

```
├── config.py                 # Centralized configuration (env vars + constants)
├── main.py                   # Pipeline orchestrator (2-phase + 7-filter)
├── schemas.py                # Pydantic v2 validation schemas
├── target_config.py          # YAML-based target definition loader
│
├── targets/                  # Target configuration examples
│   ├── facades.yaml          # Building facades (real estate)
│   └── products.yaml         # Product photos (e-commerce)
│
├── scraper/
│   ├── site_scraper.py       # HTML image extraction (multi-method)
│   ├── serpapi_client.py     # Google Images API wrapper + caching
│   └── query_builder.py     # Prioritized query construction (5 tiers)
│
├── classifier/
│   ├── url_classifier.py     # URL validation + source classification
│   ├── vision_validator.py   # OpenAI Vision + heuristic pipeline
│   └── heuristics.py         # Text-based fast classification
│
├── core/
│   ├── cache.py              # Classification cache (30-day TTL)
│   ├── checkpoint.py         # Resumable progress tracking (hash-based)
│   ├── dedup.py              # Perceptual hash deduplication (SQLite)
│   ├── downloader.py         # Image download + resize + retry
│   └── metrics.py            # Performance & cost monitoring
│
└── docs/
    └── architecture.md       # Detailed architecture documentation
```

## Exemplo de Target Config / Target Config Example

```yaml
# targets/facades.yaml
name: "Building Facades"
category: "facade"
description: "exterior photographs of buildings"

positive_keywords:
  - "facade"
  - "fachada"
  - "exterior"
  - "render"

negative_keywords:
  - "logo"
  - "floor plan"
  - "planta"
  - "map"

search_keywords:
  - "facade"
  - "exterior"
  - "render"

vision:
  system_message: "You are an expert in visual classification of real estate."
  target_description: "External view of the building (facade, perspective, render)"
  exclusion_description: "Other images (floor plans, interiors, logos, maps)"
  extra_rules:
    - "Floor plans and blueprints must be classified as non-target"
```

Para criar um novo alvo, basta copiar um YAML existente e ajustar os campos. O pipeline adapta automaticamente heuristicas, prompts e queries.

To create a new target, just copy an existing YAML and adjust the fields. The pipeline automatically adapts heuristics, prompts, and queries.

## Setup

```bash
# Clone
git clone https://github.com/mauricio-opus10/targeted-image-collector.git
cd targeted-image-collector

# Environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# Configuration
cp .env.example .env
# Edit .env with your API keys
```

### Requisitos / Requirements
- Python 3.12+
- OpenAI API key (for Vision classification)
- SerpAPI key (for Google Images search)

## Como Funciona / How It Works

1. **Input**: Lista de itens com metadados (nome, cidade, site oficial)
2. **Target config**: Carrega definicao YAML do que coletar
3. **Fase 1**: Raspa os sites de cada item buscando imagens (multi-metodo)
4. **Fase 2**: Complementa com Google Images via SerpAPI (queries priorizadas)
5. **Validacao**: Cada imagem candidata passa pelo pipeline de 7 filtros
6. **Output**: Imagens validadas, classificadas e deduplicadas

O sistema e projetado para ser **plugavel** — implemente sua propria funcao `load_items()` no `main.py` para conectar sua fonte de dados (banco de dados, API, CSV, etc).

The system is designed to be **pluggable** — implement your own `load_items()` in `main.py` to connect your data source (database, API, CSV, etc).

## Resultados Tipicos / Typical Results

- Acuracia de validacao: ~80% (fonte oficial: ~80%, SerpAPI: ~70%)
- Reducao de custo: ~40% via heuristicas e cache
- Cobertura: ate 3 imagens por item

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| Vision AI | OpenAI GPT-4o-mini |
| Image Search | SerpAPI (Google Images) |
| Web Scraping | BeautifulSoup4, Requests |
| Validation | Pydantic v2 |
| Image Processing | Pillow, imagehash |
| Deduplication | SQLite + Perceptual Hashing |
| Config | YAML (PyYAML) |
| Logging | Loguru |
| Parallelism | concurrent.futures |

---

## English Summary

This project automates targeted image collection from the web. It was built to solve a specific challenge: **collecting images from hundreds of different websites**, where each item has its own site with unique HTML structures — fundamentally different from traditional single-site scraping.

Instead of CSS selectors tailored to one domain, the pipeline uses multiple extraction methods (img tags, picture elements, srcset, CSS backgrounds, gallery links) combined with AI validation (OpenAI Vision) to work reliably across any website.

The system is **configurable via YAML target definitions**: swap a config file to collect building facades, product photos, vehicle images, or any other visual category — without changing a single line of code.

Key technical highlights:
- **Multi-site robustness**: Works across any website structure without site-specific rules
- **Configurable targets**: YAML-based definition of what to collect (keywords, prompts, search terms)
- **Cost optimization**: Heuristic-first classification saves ~40% on API costs
- **Smart URL analysis**: Source classification + homonym detection
- **Resilient pipeline**: Checkpoint/resume, cache, retry with backoff
- **Quality control**: 7-filter validation pipeline with perceptual hash deduplication

Implement your own `load_items()` to connect your data source.

## License

MIT License - see [LICENSE](LICENSE) for details.
