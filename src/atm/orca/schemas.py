"""Contratos de dados do Orca — modelos Pydantic v2.

Espelham as estruturas que o motor REAL produz/consome:

- ``MicroRow``    → linha do DataFrame de ``io.carregar_planilha_microplanejamento``
                    (io.py:325 ``["fazenda","chave","area_ha","atividade"]`` + opcionais)
- ``TarifaCT``    → valor de ``tarifas.carregar_stg_tarifas`` (tarifas.py:695-705)
- ``DeParaMap``   → ``cfg["de_para"]`` (config.json)
- ``PrecoFinal``  → linha de ``preco_final.json`` (tarifas.py:_carregar_mapa_preco_final_json)
- ``PipelineConfig`` → contrato cruzado micro → de_para → tarifas

Regra de negócio codificada (não inventada): quando ``rendimento_hh > 0``
o HM é zerado — é o que ``normalizar_ct313``/``_aplicar_mapa_preco_final`` fazem.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TipoTarifa = Literal["Manual", "Mecanizada", "SemiMecanizada"]


class MicroRow(BaseModel):
    """Linha do microplanejamento. Espelha io.py:324-339."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    fazenda: str = Field(min_length=1, max_length=100)
    chave: str = Field(min_length=1, max_length=50)
    area_ha: float = Field(ge=0, le=10000)
    atividade: str = Field(min_length=1, max_length=200)
    penalidade: float = Field(default=1.0, ge=0.1, le=5.0)
    equipe: Optional[str] = Field(default=None, max_length=100)
    municipio: Optional[str] = Field(default=None, max_length=100)
    estado: Optional[str] = Field(default=None, max_length=2)
    metodologia: Optional[str] = Field(default=None, max_length=100)

    @field_validator("chave")
    @classmethod
    def _chave_maiuscula(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("fazenda", "atividade")
    @classmethod
    def _sem_vazio(cls, v: str) -> str:
        v = " ".join(str(v).split())
        if not v:
            raise ValueError("valor vazio")
        return v


class TarifaCT(BaseModel):
    """Tarifa CT313/CT317. Espelha o valor de carregar_stg_tarifas."""

    model_config = ConfigDict(extra="ignore")

    atividade: str = Field(default="", min_length=0)
    rendimento_hh: float = Field(default=0.0, ge=0)
    rendimento_hm: float = Field(default=0.0, ge=0)
    preco_ha: float = Field(default=0.0, ge=0)
    preco_unit: float = Field(default=0.0, ge=0)
    custo_hora: float = Field(default=0.0, ge=0)
    custo_ha: float = Field(default=0.0, ge=0)
    tipo: str = Field(default="")
    recurso: Literal["homem", "maquina"] = "homem"
    eficiencia: float = Field(default=1.0, ge=0.1, le=2.0)

    @model_validator(mode="after")
    def _hh_zerado_quando_hh_positivo(self) -> "TarifaCT":
        """Regra real do normalizador: HH>0 implica HM=0."""
        if self.rendimento_hh > 0 and self.rendimento_hm > 0:
            self.rendimento_hm = 0.0
        return self

    @model_validator(mode="after")
    def _recurso_coerente(self) -> "TarifaCT":
        if self.rendimento_hh > 0 and self.recurso != "homem":
            self.recurso = "homem"
        elif self.rendimento_hh <= 0 and self.rendimento_hm > 0:
            self.recurso = "maquina"
        return self


class TarifasDict(BaseModel):
    """Dicionário de tarifas, como cfg["tarifas"]."""

    model_config = ConfigDict(extra="forbid")

    root: Dict[str, TarifaCT] = Field(default_factory=dict)

    @field_validator("root")
    @classmethod
    def _chaves_nao_vazias(cls, v: Dict[str, TarifaCT]) -> Dict[str, TarifaCT]:
        for k in v:
            if not str(k).strip():
                raise ValueError("chave de tarifa vazia")
        return v


class DeParaMap(BaseModel):
    """Mapeamento nome-no-micro → nome-na-tarifa (cfg["de_para"])."""

    model_config = ConfigDict(extra="forbid")

    root: Dict[str, str] = Field(default_factory=dict)

    @field_validator("root")
    @classmethod
    def _sem_ciclo_direto(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Auto-mapeamento X→X é legitimo no projeto (grava nome=taro).
        Ciclo de VERDADE é A→B e B→A com A != B."""
        for origem, destino in v.items():
            if origem == destino:
                continue
            if v.get(destino) == origem:
                raise ValueError(f"de_para cíclico: {origem} ↔ {destino}")
        return v


class PrecoFinal(BaseModel):
    """Linha de preco_final.json (tarifas.py:_carregar_mapa_preco_final_json)."""

    model_config = ConfigDict(extra="ignore")

    operacao: str = Field(min_length=1)
    rendimento_hh_ha: float = Field(default=0.0, ge=0)
    rendimento_maquina_ha: float = Field(default=0.0, ge=0)
    preco_rs: float = Field(default=0.0, ge=0)
    tipo: str = Field(default="")


class PipelineConfig(BaseModel):
    """Contrato cruzado: micro + de_para + tarifas."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    micro: List[MicroRow] = Field(default_factory=list)
    tarifas: TarifasDict = Field(default_factory=TarifasDict)
    de_para: DeParaMap = Field(default_factory=DeParaMap)
    preco_final: List[PrecoFinal] = Field(default_factory=list)

    def tarifas_resolvidas(self) -> Dict[str, TarifaCT]:
        return dict(self.tarifas.root)

    def chave_tarifa(self, atividade_micro: str) -> str:
        """Espelha tarifas.resolver_chave_tarifa: de_para → nome próprio."""
        return self.de_para.root.get(atividade_micro, atividade_micro)

    def actividades_sem_tarifa(self) -> List[str]:
        chaves = set(self.tarifas.root.keys())
        faltando = []
        for row in self.micro:
            chave = self.chave_tarifa(row.atividade)
            if chave not in chaves:
                faltando.append(f"{row.atividade} → {chave}")
        return sorted(set(faltando))

    def cobertura(self) -> Dict[str, Any]:
        total = len(self.micro)
        sem = len(self.actividades_sem_tarifa())
        return {
            "linhas_micro": total,
            "atividades_sem_tarifa": sem,
            "cobertura_pct": round(100.0 * (total - sem) / total, 2) if total else 100.0,
        }


def micro_de_dataframe(df: Any) -> List[MicroRow]:
    """Converte o DataFrame do loader em MicroRow validados."""
    linhas: List[MicroRow] = []
    for _, r in df.iterrows():
        dados = {k: r[k] for k in df.columns}
        linhas.append(MicroRow(**dados))
    return linhas


def tarifas_de_dict(d: Dict[str, Any]) -> TarifasDict:
    """No cfg["tarifas"] a CHAVE é a atividade; o valor não repete o nome."""
    root: Dict[str, TarifaCT] = {}
    for chave, valor in (d or {}).items():
        dados = dict(valor or {})
        dados.setdefault("atividade", chave)
        root[chave] = TarifaCT(**dados)
    return TarifasDict(root=root)


def depara_de_dict(d: Dict[str, str]) -> DeParaMap:
    return DeParaMap(root={str(k): str(v) for k, v in (d or {}).items()})
