# Reliability Lab
### Sistema pessoal de análise de confiabilidade informacional
*Execução local · Conteúdos digitais · Análise baseada em evidências · Tags explicáveis · Anti-alucinação*

---

## 1. Visão Geral

O **Reliability Lab** é uma prova de conceito funcional executada 100% no computador do usuário para investigar a eficácia de um pipeline automatizado de análise informacional. O sistema reduz o esforço de checagem ao extrair alegações, buscar evidências externas, isolar trechos literais comprobatórios e aplicar **regras determinísticas de código** (sem permitir que o modelo LLM "invente" ou "opine" sobre o veredito final).

### Principais Características
- **Execução Local & Assíncrona:** Backend orquestrado por um `JobManager` em thread com event loop asyncio dedicado; UI Streamlit responsiva que não congela e oferece botão **"Cancelar Análise"** a qualquer instante.
- **Transparência & Determinismo (RNF-03):** O módulo `src/reliability/verification/` não importa nenhuma biblioteca de LLM. Vereditos por alegação, tags de atenção e o placar geral são gerados estritamente por regras determinísticas em código Python.
- **Saídas Estruturadas & Anti-Alucinação (RF-06, RNF-05):** Integração com `instructor` forçando contratos estritos de schemas Pydantic em modo JSON. Qualquer trecho citado (`source_quote` ou `exact_quote`) é auditado como substring do documento/fonte real; se não existir literalmente, o validador falha e aciona retry corretivo automático (até 3 tentativas).
- **Isolamento de Prompt (RNF-02):** Conteúdos externos são sanitizados (remoção de caracteres invisíveis/bidi) e envelopados na tag `<doc>`. Prompts do sistema instruem explicitamente a ignorar quaisquer ordens imperativas contidas no texto do usuário.
- **Proteção contra SSRF (RNF-04):** Validação estrita de URLs rejeitando loopback (`127.0.0.1`, `localhost`), IPs privados (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), metadados de nuvem (`169.254.169.254`), IPv6 local e redirects maliciosos para destinos internos.
- **Extração Resiliente (RF-04):** Usa `trafilatura` com fallback heurístico para BeautifulSoup. Identifica ativamente barreiras de paywall e banners de consentimento de cookies, truncando e alertando sobre análises parciais.
- **Telemetria Completa & Reprodutibilidade (RF-13, RNF-07):** Registro em SQLite de tokens consumidos (prompt e completion), tempo de processamento em ms, versão do pipeline, versão do prompt e modelo utilizado.
- **Mecanismo de Feedback (RF-14):** Permite avaliar se a análise acertou ou errou, com anotações de correção salvas para auditoria.

---

## 2. Estrutura do Repositório

```text
Root-L-Verifica/
├── app.py                      # Ponto de entrada da interface Streamlit
├── pyproject.toml              # Metadados e dependências (Python >=3.12)
├── .env.example                # Modelo de configuração de ambiente
├── README.md                   # Documentação do sistema
├── datasets/
│   └── sample.jsonl            # Dataset de teste para avaliação em lote
├── src/
│   └── reliability/
│       ├── config.py           # Configurações com pydantic-settings
│       ├── schemas.py          # Schemas Pydantic e validação de trechos exatos
│       ├── errors.py           # Exceções amigáveis ao usuário
│       ├── jobs.py             # Gerenciador de jobs assíncronos (JobManager)
│       ├── bootstrap.py        # Injeção de dependências
│       ├── pipeline.py         # Orquestrador do ciclo de vida da análise
│       ├── demo.py             # Fakes determinísticos para modo demonstração e testes
│       ├── ui_helpers.py       # Estilização CSS e componentes visuais seguros (anti-XSS)
│       ├── ingestion/          # Validação de input, SSRF, sanitização e truncamento
│       ├── extraction/         # Fetcher seguro, Trafilatura, detecção de paywall/cookies
│       ├── claims/             # Integração com instructor + prompts versionados
│       ├── search/             # Provedores de busca (DuckDuckGo sem chave, Tavily)
│       ├── verification/       # MOTOR DETERMINÍSTICO (sem dependência de LLM)
│       ├── persistence/        # Modelos SQLAlchemy 2.0 e repositório SQLite
│       └── evaluation/         # Runner de avaliação de datasets (F1, acurácia, latência)
└── tests/                      # 110 testes automatizados cobrindo todos os módulos
```

---

## 3. Instalação e Configuração

### Pré-requisitos
- Python 3.12+ (ou `uv`)

### Passo a passo
1. **Instalar dependências com uv:**
   ```powershell
   uv venv --python 3.12
   .venv\Scripts\activate
   uv pip install -e ".[dev]"
   ```

2. **Configurar variáveis de ambiente:**
   Copie `.env.example` para `.env`:
   ```powershell
   copy .env.example .env
   ```

3. **Configuração de Modelo e Busca no `.env`:**
   - **OpenAI (Nuvem - Recomendado: gpt-4o-mini):**
     ```ini
     LLM_BASE_URL=https://api.openai.com/v1
     OPENAI_API_KEY=sk-proj-sua-chave-aqui
     LLM_MODEL=gpt-4o-mini
     LLM_CONTEXT_TOKENS=128000
     LLM_TIMEOUT_S=60
     ```
   - **Ollama (Execução Local):**
     ```ini
     LLM_BASE_URL=http://localhost:11434/v1
     LLM_API_KEY=ollama
     LLM_MODEL=qwen2.5:7b-instruct
     LLM_CONTEXT_TOKENS=8192
     LLM_TIMEOUT_S=120
     ```
   - **LM Studio / vLLM / Groq / Outro servidor OpenAI-compatible:**
     Basta apontar `LLM_BASE_URL` para o endereço correspondente e preencher a chave em `OPENAI_API_KEY` ou `LLM_API_KEY`.
   - **Provedor de Busca:**
     - `SEARCH_PROVIDER=auto`: Usa DuckDuckGo por padrão (sem necessidade de chaves). Se `TAVILY_API_KEY` for informada, utiliza automaticamente a API da Tavily.
   - **Modo Demonstração (Sem necessidade de LLM ou internet):**
     ```ini
     RELIABILITY_DEMO=1
     ```

---

## 4. Executando a Aplicação

Inicie o servidor Streamlit:
```powershell
uv run streamlit run app.py
```
Acesse no navegador: `http://localhost:8501`.

### Telas do Sistema:
1. **Nova Análise:** Entrada para colar URLs ou texto longo, seletor de profundidade (*Rápida* com busca de snippets ou *Profunda* com download completo das páginas fontes).
2. **Progresso:** Acompanhamento em tempo real via stepper visual e logs passo a passo das micro-etapas, com botão **"⛔ Cancelar Análise"**.
3. **Relatório:**
   - Placar geral determinístico e chips explicativos de tags de atenção.
   - Resumo factual objetivo do conteúdo.
   - Lista expansível de alegações factuais identificadas, com veredito, regra aplicada, relevância e **citação literal exata** destacada de cada fonte externa.
   - Widget de **Feedback de Precisão** (Acertou/Errou + notas).
   - Metadados de telemetria (tempo total, tokens de prompt/resposta, modelo e versão do pipeline).
4. **Histórico e Métricas:** Tabela com histórico persistido no SQLite, métricas agregadas de acerto e consumo, visualizador detalhado e botão de **Exportar CSV** (com sanitização contra injeção de fórmulas em planilhas).

---

## 5. Regras Determinísticas de Classificação

O motor Python aplica regras sequenciais transparentes:

### Veredito por Alegação (`src/reliability/verification/rules.py`):
| Regra | Condição | Veredito |
|---|---|---|
| **Regra 1** | Tipo de alegação for Opinião, Previsão ou Juízo Subjetivo | `Não Verificável` |
| **Regra 2** | Nenhuma evidência com trecho verificado e relevância $\ge 0.5$ | `Inconclusiva` |
| **Regra 3** | Pelo menos 1 fonte contradiz e nenhuma fonte sustenta | `Contradita` |
| **Regra 4** | Fontes conflitantes (sustentam e contradizem simultaneamente) | `Inconclusiva` (divergência preservada) |
| **Regra 5** | Nenhuma contradição e ao menos 1 fonte sustenta parcialmente | `Parcialmente Corroborada` |
| **Regra 6** | Ao menos 1 fonte independente sustenta sem contradições | `Corroborada` |

### Classificação Geral (`src/reliability/verification/overall.py`):
- Se houver **qualquer alegação contradita**: `Contém alegações contraditas` (regra do pior caso: 5 verdades e 1 mentira grave resultam em alerta de contradição, sem médias ingênuas).
- Se não houver alegações verificáveis ou todas forem inconclusivas: `Evidências insuficientes`.
- Se todas forem corroboradas sem tags de ressalva: `Muito bem corroborado`.
- Se todas forem corroboradas com tags de ressalva (ex: fonte única, desatualizado): `Corroborado com ressalvas`.
- Caso contrário: `Conteúdo misto`.

---

## 6. Runner de Avaliação (Sprint 6)

Para rodar a avaliação em lote sobre datasets formatados em `.jsonl`:
```powershell
uv run python -m reliability.evaluation.runner datasets/sample.jsonl --demo --out resultados.csv
```
O runner calcula métricas de acurácia, F1-macro dos vereditos contra o gabarito, latência média/P95 e consumo de tokens.

---

## 7. Testes Automatizados

O projeto conta com uma suíte de 110 testes automatizados cobrindo todos os requisitos funcionais e não-funcionais:
```powershell
uv run pytest tests -q
uv run ruff check src tests app.py
```
