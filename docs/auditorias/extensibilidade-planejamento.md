# Auditoria — Extensibilidade do Planejamento

**Data:** 2026-11-06  
**Branch:** rework  
**Escopo:** `src/atm/orca/` — config.py, scheduler.py, scheduler_core.py, turmas.py, comparativo_real.py, engine_pkg/engine.py

---

## 1. Placeholders `manutencao_seco` / `manutencao_umido` — O Que Falta Exatamente

### Status Atual
**Arquivo:** `src/atm/orca/config.py:137-142`
```python
("manutencao_seco", "[EM PROGRESSO] Manutencao periodo seco — regras ainda nao definidas"),
("manutencao_umido", "[EM PROGRESSO] Manutencao periodo umido — regras ainda nao definidas"),
```

**Arquivo:** `src/atm/orca/scheduler.py:77-78`
```python
if modo in ("manutencao_seco", "manutencao_umido"):
    return 0.0  # Sem cascata — todas atividades mesmo nível
```

**Arquivo:** `src/atm/orca/turmas.py` (funções placeholder)
```python
def sequencia_manutencao_seco_placeholder(cfg):
    aviso("Manutencao SECO: regras de sequencia nao definidas ainda.")
def sequencia_manutencao_umido_placeholder(cfg):
    aviso("Manutencao UMIDO: regras de sequencia nao definidas ainda.")
```

### Arquivos/Linhas Que Precisariam Mudar Para Implementar

| Arquivo | Linha | O Que Implementar |
|---------|-------|-------------------|
| `config.py` | 93-118 | Adicionar `manutencao_seco_fases`, `manutencao_umido_fases` no `_default_sequencia_dict` |
| `config.py` | 131-145 | Remover `[EM PROGRESSO]`, adicionar descrições reais em `_SEQUENCIAS_DISPONIVEIS` |
| `scheduler.py` | 70-96 | `classificar_fase_cascata_valor`: tratar `manutencao_seco/umido` com fases próprias (não retornar 0.0) |
| `scheduler.py` | 123-153 | `_min_fase_cascata_por_talhao`: suportar fases de manutenção (hoje pula se modo ∈ manutencao) |
| `scheduler.py` | 156-190 | `pode_agendar_atividade_cascata`: regras de bloqueio/ordem específicas para manutenção |
| `scheduler.py` | 193-239 | `diagnosticar_sequencia_atividades`: validar atividades contra fases de manutenção |
| `turmas.py` | ~114-116 | Substituir placeholders por lógica real de vinculação de atividades |
| `scheduler_core.py` | 1201-1204 | Remover chamadas aos placeholders, adicionar configuração interativa real |

### Mínimo Para Ficar Funcional
1. Definir `manutencao_seco_fases` e `manutencao_umido_fases` no dict de sequência (como `implantacao_fases`)
2. Em `classificar_fase_cascata_valor`: adicionar branch para esses modos usando suas fases
3. Em `_min_fase_cascata_por_talhao`: remover `if modo in ("manutencao_seco", "manutencao_umido"): return {}`
4. Definir `filtros_plantio_manutencao`, `filtros_irrigacao_manutencao` se houver bloqueio
5. Atualizar `_SEQUENCIAS_DISPONIVEIS` com descrições reais

---

## 2. Sequência Personalizada — O Que Dá Pra Fazer HOJE Sem Código Novo

### Configuração Via `config.json` (chave `sequencia.personalizado_ordem`)

**Arquivo:** `src/atm/orca/scheduler.py:690-780` — `_configurar_sequencia_personalizada`

**O que funciona hoje:**
- Usuário define **grupos sequenciais** via CLI interativo
- Atividades no **mesmo grupo** rodam **em paralelo** (sem restrição de cascata entre elas)
- **Grupos** rodam em **sequência**: grupo N+1 só inicia quando grupo N zera **por talhão**
- Seleção de atividades via índices (`1,3,5` ou `1-5`)
- Salva em `config.json` → persiste entre execuções

**Exemplo de `personalizado_ordem` gerado:**
```json
"personalizado_ordem": [
  {"id": "grupo_1", "filtros": ["Rocada Manual", "Rocada Quimica"], "exclusoes": []},
  {"id": "grupo_2", "filtros": ["Plantio"], "exclusoes": []},
  {"id": "grupo_3", "filtros": ["Irrigacao", "Adubacao"], "exclusoes": []}
]
```

**Limitações atuais:**
- Não há interface web para editar (só CLI)
- `exclusoes` não é exposto no builder interativo (sempre `[]`)
- Não há validação de cobertura (atividades não listadas caem em "outras" = fase 5.5)
- Não suporta "OR" entre filtros (cada filtro é testado independentemente via `_match_filtros_fase`)

---

## 3. Novo Tipo de Cascata/Ordem — Config Apenas ou Exige `scheduler_core`?

### Pontos de Extensão Reais (Arquivo:Linha)

| Ponto | Arquivo:Linha | Tipo | O Que Permite |
|-------|---------------|------|---------------|
| **Fases fixas** | `config.py:102-116` | Config | Adicionar/remover/reordenar fases em `implantacao_fases` |
| **Filtros por fase** | `config.py:102-116` | Config | Mudar palavras-chave que detectam cada fase |
| **Exclusões por fase** | `config.py:102-116` | Config | Excluir atividades de uma fase (ex: "impl" da limpeza) |
| **Modo personalizado** | `config.py:117` + `scheduler.py:690-780` | Config + CLI | Grupos user-defined paralelos/sequenciais |
| **Offset limpeza** | `config.py:96` | Config | Dias de espera pós-plantio |
| **Filtros plantio/irrig** | `config.py:97-98` | Config | Palavras-chave para detectar plantio/irrigacao |
| **Fase "outras"** | `config.py:101` | Config | Valor numérico para atividades não classificadas (default 5.5) |
| **Classificação de fase** | `scheduler.py:70-96` | **Código** | Lógica de como mapear atividade → valor de fase |
| **Mínimo por talhão** | `scheduler.py:123-153` | **Código** | Algoritmo de calcular fase mínima por talhão |
| **Gate de agendamento** | `scheduler.py:156-190` | **Código** | Regras combinadas (cascata + bloqueio + offset + irrig) |
| **Modos manutencao** | `scheduler.py:77-78` | **Código** | Hardcoded `return 0.0` — **exige mudança no código** |

### Gargalos (Exigem Mudança no `scheduler_core` / `scheduler.py`)

1. **`manutencao_seco/umido` hardcoded** — `scheduler.py:77-78`
   ```python
   if modo in ("manutencao_seco", "manutencao_umido"):
       return 0.0  # Não lê config!
   ```
   → Para ter cascata na manutenção, **precisa mexer no código**

2. **`_min_fase_cascata_por_talhao` pula manutenção** — `scheduler.py:133-134`
   ```python
   if not usar_cascata or modo in ("manutencao_seco", "manutencao_umido"):
       return {}
   ```
   → Mesmo se configurar fases no JSON, o código ignora

3. **Detecção de plantio/irrigação hardcoded nos filtros** — `scheduler.py:81-88`
   ```python
   if atv in atividades_plantio or _match_filtros_fase(atv, seq_cfg.get("filtros_plantio")...):
   ```
   → Funciona via config, mas a **lógica de bloqueio** (plantio antes de irrig) é fixa no código

4. **Limpeza química pós-plantio** — `scheduler.py:48-61` + `scheduler.py:172-177`
   ```python
   def eh_limpeza_quimica_pos_plantio(atv, seq_cfg):  # usa filtros/exclusoes do config
   ```
   → **Este funciona via config** (filtros/exclusoes em `limpeza_quimica_*`)

5. **Cascata personalizada** — **Funciona via config** (`personalizado_ordem`), mas:
   - Builder só no CLI (`scheduler.py:690-780`)
   - `exclusoes` não editável no builder
   - Não valida cobertura total

---

## 4. Veredito: O Planejamento É Configurável ou Dependente de Código?

### Resposta: **HÍBRIDO — Configurável para implantação, dependente de código para manutenção e regras estruturais**

| Aspecto | Configurável (JSON/CLI) | Exige Código |
|---------|-------------------------|--------------|
| Ordem das fases (implantação) | ✅ `implantacao_fases` | — |
| Filtros/exclusões por fase | ✅ no JSON | — |
| Offset limpeza química | ✅ `offset_limpeza_quimica_dias` | — |
| Filtros plantio/irrigacao | ✅ `filtros_plantio`, `filtros_irrigacao` | — |
| Sequência personalizada | ✅ `personalizado_ordem` (via CLI) | — |
| **Cascata manutenção seco/úmido** | ❌ **Ignorada pelo código** | ✅ `scheduler.py:77-78, 133-134` |
| **Lógica "plantio antes de irrig"** | ⚠️ Filtros configuráveis, mas regra fixa | ✅ `scheduler.py:178-182` |
| **Algoritmo de fase mínima/talhão** | ❌ | ✅ `scheduler.py:123-153` |
| **Gate combinado de agendamento** | ❌ | ✅ `scheduler.py:156-190` |
| **Novos tipos de bloqueio** | ❌ | ✅ Precisa estender `pode_agendar` |

### Conclusão Prática
- **Para implantacao + personalizado:** 100% configurável (JSON + CLI builder)
- **Para manutencao_seco/umido:** **Inutilizáveis hoje** — placeholders sem lógica; exigem código
- **Para nova regra transversal** (ex: "colheita antes de preparo", "novo tipo de bloqueio"): **exige mudança em `scheduler.py`**
- **Arquitetura:** `scheduler.py` contém a **engine de cascata** (regras duras); `config.py` fornece **parâmetros** (fases, filtros, offsets)

---

## Achados Mais Importantes

1. **`scheduler.py:77-78, 133-134`** — `manutencao_seco/umido` são **hardcoded para retornar 0.0 e pular cascata**; configurar fases no JSON **não adianta** — o código ignora explicitamente.

2. **`scheduler.py:690-780`** — Sequência personalizada **funciona hoje** via CLI interativo (grupos paralelos/sequenciais), mas **não tem interface web** e `exclusoes` não é editável no builder.

3. **`scheduler.py:156-190`** — Gate `pode_agendar_atividade_cascata` concentra **todas as regras duras** (cascata + bloqueio global + offset limpeza + plantio>irrig); qualquer nova regra transversal exige mexer aqui.