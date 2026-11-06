# Auditoria — Calendário Semântico do Orca

**Data:** 2026-11-06  
**Branch:** rework  
**Escopo:** `src/atm/orca/config.py`, `src/atm/orca/scheduler.py`, `src/atm/orca/scheduler_core.py`, `src/atm/orca/engine_pkg/engine.py`

---

## 1. `_default_sequencia_dict` — Configuração Base

**Arquivo:** `src/atm/orca/config.py:93-118`

```python
def _default_sequencia_dict():
    return {
        "modo": "implantacao",
        "offset_limpeza_quimica_dias": 30,
        "filtros_plantio": ["plantio"],
        "filtros_irrigacao": ["irrig"],
        "limpeza_quimica_filtros": ["limpeza", "quim"],
        "limpeza_quimica_exclusoes": ["impl", "impl."],
        "implantacao_outras_fase": 5.5,
        "implantacao_fases": [
            {"id": "rocada", "filtros": ["rocada", "rocada"], "exclusoes": []},
            {"id": "formiga", "filtros": ["formiga", "combate a formiga", "combate a formigas"], "exclusoes": []},
            {"id": "coroamento", "filtros": ["coroamento", "coroa"], "exclusoes": []},
            {"id": "coveamento", "filtros": ["coveamento", "coveam"], "exclusoes": []},
            {"id": "adubacao_quimica", "filtros": ["adubacao quim", "adubacao quim", "melhora quim"], "exclusoes": []},
        ],
        "personalizado_ordem": [],
    }
```

### Estrutura
| Chave | Tipo | Função |
|-------|------|--------|
| `modo` | str | `"implantacao"`, `"manutencao_seco"`, `"manutencao_umido"`, `"personalizado"` |
| `offset_limpeza_quimica_dias` | int | Dias após fim do plantio para liberar limpeza química pós-plantio |
| `filtros_plantio` | list[str] | Palavras-chave para detectar atividades de plantio |
| `filtros_irrigacao` | list[str] | Palavras-chave para detectar irrigação |
| `limpeza_quimica_filtros` | list[str] | Detecta "limpeza química pós-plantio" |
| `limpeza_quimica_exclusoes` | list[str] | Exclui "implantação" da limpeza pós-plantio |
| `implantacao_outras_fase` | float | Fase genérica (5.5) para atividades não classificadas |
| `implantacao_fases` | list[dict] | **Cascata fixa**: rocada → formiga → coroamento → coveamento → adubação |
| `personalizado_ordem` | list[dict] | Grupos definidos pelo usuário (paralelos dentro, sequenciais entre grupos) |

### Modos Disponíveis
**Arquivo:** `src/atm/orca/config.py:131-145`

```python
_SEQUENCIAS_DISPONIVEIS = [
    ("implantacao", "Rocada > Formiga > Coroamento > Coveamento > Adubacao > Plantio > Irrigacao (cascata)"),
    ("manutencao_seco", "[EM PROGRESSO] Manutencao periodo seco — regras ainda nao definidas"),
    ("manutencao_umido", "[EM PROGRESSO] Manutencao periodo umido — regras ainda nao definidas"),
    ("personalizado", "Sequencia personalizada (defina grupos sequenciais/paralelos)"),
]
```

---

## 2. Cascata por Talhão — `classificar_fase_cascata_valor` + `_min_fase_cascata_por_talhao`

### 2.1 `classificar_fase_cascata_valor` — Valor Numérico de Fase
**Arquivo:** `src/atm/orca/scheduler.py:70-96`

```python
def classificar_fase_cascata_valor(atv, seq_cfg, modo, atividades_plantio, atividades_irrig):
    if modo in ("manutencao_seco", "manutencao_umido"):
        return 0.0  # Sem cascata
    if eh_limpeza_quimica_pos_plantio(atv, seq_cfg):
        return 8.0  # Última fase
    if atv in atividades_plantio or _match_filtros_fase(atv, filtros_plantio):
        return 6.0  # Plantio
    if atv in atividades_irrig or _match_filtros_fase(atv, filtros_irrigacao):
        return 7.0  # Irrigação (após plantio)
    for i, fase in enumerate(implantacao_fases):
        if _match_filtros_fase(atv, fase.filtros, fase.exclusoes):
            return float(i)  # 0=rocada, 1=formiga, 2=coroamento, 3=coveamento, 4=adubação
    return implantacao_outras_fase  # 5.5 (genérico)
```

### 2.2 `_min_fase_cascata_por_talhao` — Mínimo por Talhão (Não Global!)
**Arquivo:** `src/atm/orca/scheduler.py:123-153`

```python
def _min_fase_cascata_por_talhao(demanda_global, seq_cfg, modo, usar_cascata, ...):
    if not usar_cascata or modo in ("manutencao_seco", "manutencao_umido"):
        return {}
    por_talhao = defaultdict(list)
    for (talhao, atv), hh in sorted(demanda_global.items()):
        if hh <= 0.01: continue
        if usar_bloqueio_global and atv in bloqueadas:  # plantio/irrig bloqueadas
            if _ha_trabalho_nao_bloqueado(...): continue
        if eh_limpeza_quimica_pos_plantio(atv, seq_cfg):
            if not limpeza_permitida_por_talhao(...): continue
        fv = classificar_fase_cascata_valor(...)
        por_talhao[talhao].append(fv)
    return {t: min(vs) for t, vs in por_talhao.items() if vs}
```

**Ponto chave:** Retorna **dict `{talhao: min_fase}`** — cada talhão avança independentemente.  
Fase N+1 só começa no talhão X quando fase N **naquele talhão** zera.

### 2.3 `pode_agendar_atividade_cascata` — Gate de Agendamento
**Arquivo:** `src/atm/orca/scheduler.py:156-190`

Regras combinadas (ordem de avaliação):
1. **Demanda > 0.01** — senão `False`
2. **Bloqueio global** — se `atividades_bloqueadas` (plantio/irrig) e há trabalho não-bloqueado → `False`
3. **Limpeza química pós-plantio** — exige `dia >= dia_fim_plantio_talhao + offset(30)`
4. **Irrigação após plantio** — se há plantio pendente no talhão → `False`
5. **Cascata por talhão** — `fv > min_fase_talhao + epsilon` → `False`

---

## 3. `dias_uteis_no_periodo` + `DIAS_UTEIS_POR_MES = 22`

### 3.1 `dias_uteis_no_periodo` — Cálculo Real de Dias Úteis
**Arquivo:** `src/atm/orca/scheduler.py:675-687`

```python
def dias_uteis_no_periodo(mes_ini, ano_ini, meses):
    dias = 0
    m, a = mes_ini, ano_ini
    for _ in range(int(math.ceil(meses))):
        for sem in calendar.monthcalendar(a, m):
            for i, d in enumerate(sem):
                if d != 0 and i < 5:  # Seg-Sex
                    dias += 1
        m += 1
        if m > 12:
            m = 1
            a += 1
    return dias
```
- Usa `calendar.monthcalendar` — **dias úteis reais** por mês
- Considera feriados? **Não** — apenas seg-sex

### 3.2 `DIAS_UTEIS_POR_MES = 22.0` — Constante de Conversão
**Arquivo:** `src/atm/orca/scheduler_core.py:18` / `engine_pkg/engine.py:156`

```python
DIAS_UTEIS_POR_MES = 22.0
meses_simulado = dias_simulado / DIAS_UTEIS_POR_MES
```

- **Aproximação fixa** (22 dias/mês) para exibição de meses
- **Não usado no agendamento** — só em relatórios/métricas
- Divergência: `dias_uteis_no_periodo(1, 2026, 6)` ≈ 130 dias vs `6*22=132`

### 3.3 Como Viram Datas/Dias
| Origem | Uso |
|--------|-----|
| `dia_ref, mes_ref, ano_ref` (input usuário) | Data início simulada |
| `_calcular_data_fim_por_meses` (datas.py) | Data fim = início + meses úteis reais |
| `dia` (inteiro 1, 2, 3...) | Dia útil simulado (não data calendário) |
| `_formatar_data_dia(dia, mes, ano)` | Converte dia útil N → data real para Excel |

---

## 4. `offset_limpeza_quimica_dias = 30`

**Definição:** `config.py:96` → `"offset_limpeza_quimica_dias": 30`

**Onde atua:** `scheduler.py:106-120` → `limpeza_permitida_por_talhao`

```python
def limpeza_permitida_por_talhao(talhao, dia, seq_cfg, dia_termino_plantio, tem_plantio_previsto):
    if not tem_plantio_previsto_no_talhao:
        return True  # Sem plantio = limpeza livre
    d = dia_termino_plantio.get(talhao)
    if d is None:
        return False  # Plantio não acabou
    off = int(seq_cfg.get("offset_limpeza_quimica_dias", 30) or 30)
    return dia >= d + off  # Libera 30 dias após fim do plantio
```

**Fluxo:**
1. Scheduler detecta fim do plantio no talhão → `dia_termino_plantio[talhao] = dia_atual`
2. Limpeza química (filtros "limpeza"+ "quim", exceto "impl") fica bloqueada
3. Após `offset` dias (default 30), `pode_agendar` retorna `True`

---

## 5. `_SEQUENCIAS_DISPONIVEIS` — Modos de Sequência

| Modo | Status | Cascata | Plantio/Irrig | Uso |
|------|--------|---------|---------------|-----|
| `implantacao` | ✅ **Vivo** | Sim (5 fases fixas) | Bloqueio global opcional | Padrão |
| `manutencao_seco` | ⚠️ **[EM PROGRESSO]** | Não (retorna 0.0) | Não definido | Placeholder |
| `manutencao_umido` | ⚠️ **[EM PROGRESSO]** | Não (retorna 0.0) | Não definido | Placeholder |
| `personalizado` | ✅ **Vivo** | Sim (grupos user-defined) | Conforme filtros | Avançado |

### `manutencao_seco/umido` — O que Falta
- `classificar_fase_cascata_valor` retorna `0.0` (linha 77-78) → **sem cascata**
- `_SEQUENCIAS_DISPONIVEIS` marca "[EM PROGRESSO]"
- `sequencia_manutencao_seco_placeholder` / `sequencia_manutencao_umido_placeholder` em `turmas.py` só mostram aviso
- **Não há fases definidas**, **não há filtros**, **não há regras de bloqueio**

---

## Diagrama Textual — Fluxo do Calendário Semântico

```
┌─────────────────────────────────────────────────────────────────┐
│                    CONFIGURAÇÃO (config.py)                     │
│  _default_sequencia_dict()                                      │
│  ├── modo: "implantacao"                                        │
│  ├── implantacao_fases: [rocada, formiga, coroamento,           │
│  │     coveamento, adubacao_quimica]  ← ORDEM FIXA (0-4)       │
│  ├── offset_limpeza_quimica_dias: 30                            │
│  ├── filtros_plantio: ["plantio"]                               │
│  ├── filtros_irrigacao: ["irrig"]                               │
│  └── personalizado_ordem: []  ← USER-DEFINED                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│           CLASSIFICAÇÃO DE FASE (scheduler.py)                  │
│  classificar_fase_cascata_valor(atividade) → float             │
│  ├── 0.0  = rocada                                              │
│  ├── 1.0  = formiga                                             │
│  ├── 2.0  = coroamento                                          │
│  ├── 3.0  = coveamento                                          │
│  ├── 4.0  = adubação química                                    │
│  ├── 5.5  = "demais" (implantacao_outras_fase)                 │
│  ├── 6.0  = plantio (filtros_plantio)                          │
│  ├── 7.0  = irrigação (filtros_irrigacao)                      │
│  └── 8.0  = limpeza química pós-plantio                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│         MÍNIMO POR TALHÃO (scheduler.py)                        │
│  _min_fase_cascata_por_talhao() → {talhao: min_fase}           │
│  • Cada talhão tem sua fase mínima independentemente           │
│  • Filtra: bloqueadas, limpeza não liberada, HH≤0.01           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│            GATE DE AGENDAMENTO (scheduler.py)                   │
│  pode_agendar_atividade_cascata(talhao, atv, dia, ...)         │
│  1. demanda > 0.01?                  → Não = False             │
│  2. bloqueio_global + trabalho livre? → Sim = False             │
│  3. limpeza_quimica + offset?        → Não = False              │
│  4. irrigacao + plantio_pendente?    → Sim = False              │
│  5. cascata: fase_atv > min_fase_talh? → Sim = False            │
│  Senão → True (pode agendar)                                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              LOOP DO SCHEDULER (engine.py)                      │
│  while dia < MAX_DIAS:                                          │
│    para cada turma:                                             │
│      consome capacidade_dia (ops * jornada)                    │
│      agenda atividades onde pode_agendar == True               │
│    _min_fase_cascata_por_talhao recalculado a cada dia        │
│    para quando TODAS demandas ≤ 0.01                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Achados Mais Importantes

1. **`config.py:137-142`** — `manutencao_seco/umido` são **placeholders**: `classificar_fase_cascata_valor` retorna `0.0` (sem cascata), não há fases/filtros/bloqueios definidos.

2. **`scheduler.py:123-153`** — Cascata é **por talhão** (`{talhao: min_fase}`), não global. Fase N+1 inicia no talhão X quando fase N zera **naquele talhão**.

3. **`scheduler.py:106-120`** — `offset_limpeza_quimica_dias=30` só atua se **houver plantio no talhão**; sem plantio, limpeza química roda livre.