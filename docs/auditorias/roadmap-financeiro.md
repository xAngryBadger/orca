# Roadmap Financeiro — Orca para Ganhos Reais Semanais/Mensais + Gráficos

**Data:** 2026-11-06  
**Branch:** rework  
**Objetivo do Dono:** Usar Orca para ganhos reais semanais/mensais + gráficos no painel web

---

## 1. Estado Atual — `modo_somente_hh=True`

**Arquivo:** `src/atm/orca/config.py:36, 39-43`
```python
MODO_SOMENTE_HH = True

def modo_somente_hh(cfg=None):
    if cfg is not None:
        return cfg.get("modo_somente_hh", MODO_SOMENTE_HH)
    return MODO_SOMENTE_HH
```

### Caminho de Código Financeiro Existente

| Componente | Arquivo | Status | Observação |
|------------|---------|--------|------------|
| `preco_ha` / `preco_unit` | `tarifas.py:150-174` | 🟡 **Parcial** | `resolver_preco_ha` retorna 0.0 se `modo_somente_hh=True` |
| `custo_hora` | `tarifas.py:177-201` | 🟡 **Parcial** | `resolver_custo_hora` retorna 0.0 se `modo_somente_hh=True` |
| `preco_final.json` | `tarifas.py:255-394` | ✅ **Vivo** | Cache TTL, merge com CT, score de qualidade |
| Tarifas CT (HH/HM/preco/custo) | `tarifas.py:485-683` | ✅ **Vivo** | `normalizar_ct313` → `STG_TARIFAS.xlsx` |
| Custos globais (direto/indireto) | `tarifas.py:762-851` | ✅ **Vivo** | Importação de planilha bruta |
| `custo_total` no cronograma | `engine.py:322-326` | 🟡 **Parcial** | Calcula se `not modo_somente_hh` |
| `total_custo` no resultado | `scheduler_core.py:596` | 🟡 **Parcial** | Incluído mas = 0.0 em modo HH |

### O Que Está **Vivo** (Funciona Mesmo com `modo_somente_hh=True`)
- Importação e normalização de CT (`normalizar_ct313`)
- `preco_final.json` como fonte suplementar (HH/HM/preco)
- Custos globais brutos (direto/indireto)
- Estrutura de dados: `tarifas[chave] = {rendimento_hh, rendimento_hm, preco_ha, custo_hora, custo_ha, tipo}`

### O Que Está **Morto/Desativado** (Retorna 0.0)
- `resolver_preco_ha()` → linha 153: `if modo_somente_hh(cfg): return 0.0`
- `resolver_custo_hora()` → linha 180: `if modo_somente_hh(cfg): return 0.0`
- `custo_total` no cronograma → `engine.py:322`: `if not config.modo_somente_hh(config.cfg)`
- Exportação Excel: `scheduler_core.py:1028` mostra "N/A" se modo HH

---

## 2. Caminho MÍNIMO Mapa-a-Mapa — Expor Ganho Semanal/Mensal Por Fazenda

### Princípio: **Só Soma o Que o Motor Já Calcula** (cronograma + tarifas), **Sem Inventar Número**

### Dados Já Disponíveis no Motor

| Dado | Onde É Calculado | Como Acessar |
|------|------------------|--------------|
| `cronograma` (lista de linhas com Dia, Talhão, Atividade, Turma, HH, HM, Custo_MO) | `engine.py:_executar_scheduler_loop` → `cronograma` | `resultado_final["cronograma"]` |
| `total_hh`, `total_hm`, `total_custo` | `engine.py:_construir_demandas` + loop | `resultado_final["total_hh"]`, etc. |
| `tarifas[atv] = {preco_ha, custo_hora, custo_ha}` | `tarifas.py:carregar_stg_tarifas` | `cfg["tarifas"]` |
| `dias_simulado`, `meses_simulado` | `comparativo_real.py` / `engine.py:_merge_cronograma_base_e_metricas` | `resultado_final["dias_simulado"]` |
| `uso_capacidade_pct` | `comparativo_real.py:102` | `cenario["uso_capacidade_pct"]` |

### Mapa Mínimo — Arquivos/Chaves a Expor

#### A. No Resultado Final (Já Existe, Só Precisa Ativar Financeiro)
**Arquivo:** `src/atm/orca/scheduler_core.py:589-617` → `_build_resultado_final`
```python
resultado_final = {
    "fazenda": fazenda,
    "dias_simulado": int(dias_simulado),
    "meses_simulado": float(meses_simulado),
    "total_hh": float(total_hh),
    "total_custo": float(total_custo),  # ← JÁ EXISTE, mas = 0.0 se modo HH
    "total_hm": float(total_hm),
    "cronograma": cronograma_base,      # ← LINHAS COM Custo_MO POR DIA/TALHÃO
    ...
}
```

#### B. No Painel Web `/resultado` — Adicionar Agregação Semanal/Mensal
**Arquivo:** `src/atm/web/app.py:192-206` → `get_resultado`
**Arquivo:** `src/atm/web/bridge.py` → nova função `agregar_financeiro_por_periodo`

**Dados necessários por fazenda:**
```python
# Para cada fazenda no cronograma:
receita_semanal = sum(linha["Custo_MO"] * -1 for linha in cronograma if linha["Semana"] == s)  # se preco_ha > custo_ha
# OU mais simples: ganho = receita - custo
# receita = sum(area * preco_ha)  — vem das demandas originais
# custo = sum(HH * custo_hora)    — já no cronograma como Custo_MO
```

#### C. Chaves Mínimas a Ativar/Expor

| Ação | Arquivo:Linha | Mudança |
|------|---------------|---------|
| 1. Permitir `modo_somente_hh=False` via config | `config.py:304-305` | Já existe: `cfg["modo_somente_hh"] = False` |
| 2. `resolver_preco_ha` / `resolver_custo_hora` não zerarem | `tarifas.py:153, 180` | Remover `if modo_somente_hh: return 0.0` |
| 3. `engine.py:322` calcular `Custo_MO` sem guarda | `engine.py:322` | Remover `if not config.modo_somente_hh` |
| 4. Bridge: agregar `ganho_semanal/mensal` por fazenda | `bridge.py` (novo) | Função pura sobre `cronograma` + `tarifas` |
| 5. Web: expor `/financeiro/<fazenda>` ou estender `/resultado` | `app.py:192` | Novo endpoint ou campos no JSON |

---

## 3. Gráficos — Com Dados Que `/resultado` Já Tem

### Dados Disponíveis no `state.cenarios` (bridge.py → app.py → resultado.html)

| Campo | Fonte | Gráfico Possível |
|-------|-------|------------------|
| `dias_simulados` | `comparativo_real.py:107` | Barras: Dias por cenário (jornada × equipe) |
| `meses_simulados` | `comparativo_real.py:108` | Linha: Meses vs equipe |
| `uso_capacidade_pct` | `comparativo_real.py:113` | Heatmap: Uso% (eixo X=jornada, Y=equipe) |
| `hh_total` | `comparativo_real.py:109` | Barras empilhadas: HH vs HM |
| `hh_pendente` | `comparativo_real.py:110` | Alerta: INCOMPLETO (vermelho) |
| `aprovacao` | `comparativo_real.py:114` | Badge: COMPLETO/INCOMPLETO |
| `capacidade_dia_hh` | `comparativo_real.py:112` | Referência: capacidade teórica |

### Gráficos **Sem Cálculo Novo** (Só Frontend)

1. **Grade de Cenários — Heatmap de Uso%**
   - Eixo X: Jornadas (4.6, 6.0, 8.0)
   - Eixo Y: Equipes (4, 6, 9, 12)
   - Cor: `uso_capacidade_pct` (verde=alto, vermelho=baixo)

2. **Dias Simulados — Barras Agrupadas**
   - X: Equipe
   - Séries: Jornada (barras lado a lado)
   - Valor: `dias_simulados`

3. **Composição HH/HM — Barras Empilhadas**
   - X: Cenário (jornada×equipe)
   - Base: `hh_total`
   - Topo: `hm_total`

4. **Aprovação — Matriz de Status**
   - Grid jornada×equipe
   - Verde: COMPLETO, Vermelho: INCOMPLETO

5. **Linha do Tempo (se cronograma disponível)**
   - X: Dia/Semana
   - Y: HH consumidas por dia (soma de `cronograma` por Dia)
   - Série extra: HM por dia

### Gráficos Que **Precisam Financeiro Ativo**
- Ganho semanal/mensal por fazenda (linha ou barras)
- Receita vs Custo vs Lucro (waterfall)
- Payback / ROI por cenário

---

## 4. Fases Recomendadas — Mínimo → Desejável

| Fase | Descrição | Esforço | Entregável |
|------|-----------|---------|------------|
| **0. Preparação** | Garantir CT processada (`STG_TARIFAS.xlsx`) + `preco_final.json` opcional | — | Dados de tarifa com `preco_ha` e `custo_hora` válidos |
| **1. MÍNIMO — Ativar Financeiro no Motor** | `cfg["modo_somente_hh"] = False`; remover guards em `tarifas.py` e `engine.py` | **Baixo** (3-4 linhas) | `total_custo` > 0, `Custo_MO` no cronograma |
| **2. MÍNIMO — Agregar Ganho no Bridge** | Nova função `calcular_ganho_fazenda(cronograma, tarifas, demandas)` → `ganho_semanal`, `ganho_mensal` | **Baixo** (função pura, ~50 linhas) | JSON com `ganho_por_semana`, `ganho_por_mes` por fazenda |
| **3. MÍNIMO — Expor no `/resultado`** | Estender `get_resultado` ou criar `/financeiro/<fazenda>` | **Baixo** | Tabela/JSON com ganhos no painel |
| **4. DESEJÁVEL — Gráficos Financeiros no Painel** | Chart.js / ApexCharts no `resultado.html`: ganho semanal, receita×custo, ROI | **Médio** (frontend) | Dashboard visual |
| **5. DESEJÁVEL — Comparativo Financeiro Multi-Cenário** | Grade jornada×equipe com `ganho_mensal`, `ROI`, `payback` | **Médio** (backend + frontend) | Tabela/heatmap de lucro |
| **6. AVANÇADO — Cenários de Preço (Sensibilidade)** | Variação de `preco_ha` (±10%, ±20%) + Monte Carlo leve | **Alto** | Análise de risco |
| **7. AVANÇADO — Cash Flow Projetado** | Curva S de desembolso (custo) vs entrada (receita) por mês | **Alto** | Gráfico de fluxo de caixa |

### Detalhamento das Fases 1-3 (O "Mínimo Viável")

#### Fase 1 — Ativar Financeiro (Backend Only)
```diff
# tarifas.py:153
- if modo_somente_hh(cfg): return 0.0
+ # modo_somente_hh só afeta UI, não cálculo de preço

# tarifas.py:180
- if modo_somente_hh(cfg): return 0.0

# engine.py:322
- custo = consumo * resolver_custo_hora(...) if not config.modo_somente_hh(config.cfg) else 0.0
+ custo = consumo * resolver_custo_hora(config.cfg, config.tarifas, ...)
```

#### Fase 2 — Agregar Ganho (Bridge)
```python
# bridge.py — nova função
def calcular_ganho_fazenda(cronograma, tarifas, demandas_originais):
    """
    Ganho = Receita - Custo
    Receita = sum(area * preco_ha) por atividade (vem de demandas_originais)
    Custo = sum(HH * custo_hora) = sum(Custo_MO do cronograma)
    Agrupa por semana (Dia // 5 + 1) e mês (Dia / 22)
    """
    ganho_semanal = defaultdict(float)
    ganho_mensal = defaultdict(float)
    receita_total = 0.0
    custo_total = 0.0
    
    for linha in cronograma:
        semana = (linha["Dia"] - 1) // 5 + 1
        mes = math.ceil(linha["Dia"] / 22.0)
        custo = linha.get("Custo_MO", 0.0)
        # Receita: precisa cruzar com demanda original (area * preco_ha)
        # Simplificação: ratear receita proporcionalmente ao HH do dia
        ganho_semanal[semana] -= custo  # negativo = custo
        ganho_mensal[mes] -= custo
        custo_total += custo
    
    # Adicionar receita total (uma vez) distribuída ou no final
    for talhao, tarefas in demandas_originais.items():
        for t in tarefas:
            atv = t["atividade"]
            area = t["area"]
            preco = tarifas.get(atv, {}).get("preco_ha", 0.0)
            receita_total += area * preco
    
    # Distribuir receita linearmente nos dias ou alocar no fim
    # Para MVP: mostrar receita_total, custo_total, ganho_total
    return {
        "receita_total": receita_total,
        "custo_total": custo_total,
        "ganho_total": receita_total - custo_total,
        "ganho_por_semana": dict(ganho_semanal),
        "ganho_por_mes": dict(ganho_mensal),
    }
```

#### Fase 3 — Expor no Painel
```python
# app.py:192 — estender get_resultado
@ app.get("/resultado", response_class=HTMLResponse)
def get_resultado(...):
    # ... existente ...
    # Adicionar no contexto:
    "financeiro": state.financeiro  # calculado no bridge após simular
```

---

## Achados Mais Importantes

1. **`config.py:36, 39-43` + `tarifas.py:153, 180` + `engine.py:322`** — `modo_somente_hh=True` **zera todo caminho financeiro** (preco_ha, custo_hora, Custo_MO). Basta flipar config + remover 3 guards para ativar.

2. **`bridge.py` + `app.py:192`** — Painel web **já tem grade de cenários** (dias, meses, uso%, HH, HM, aprovação). Gráficos de heatmap/barras **são só frontend** (Chart.js) sobre `state.cenarios`.

3. **`engine.py:322-326` + `scheduler_core.py:589-617`** — Cronograma **já carrega `Custo_MO` por linha** (dia/talhão/turma). Agregar por semana/mês é **função pura** sobre dados existentes — não precisa rodar scheduler novamente.