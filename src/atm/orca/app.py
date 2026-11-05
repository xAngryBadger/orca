"""Application layer — menu flows, farm selection, interactive modules.

Os corpos dos comandos foram movidos para commands.py (registry COMANDOS).
Este arquivo mantém re-exports para compatibilidade com entry.py.
"""

# Re-exports de commands.py — registry central de despacho
from .commands import (
    COMANDOS,
    modulo_normalizar_ct,
    modulo_importar_tarifas,
    _aplicar_filtro_regiao,
    _aplicar_filtro_empresa_e_escopo,
    _selecionar_talhoes_fazenda,
    _executar_scheduler_fazenda_interativo,
    _metodologias_presentes,
    _prompt_proximas_metodologias,
)

# Re-exports de compatibilidade: estas funcoes moravam em app.py e foram
# movidas para domain/ (quebra do ciclo scheduler_core <-> app). Quem ainda
# importar daqui continua funcionando.
from .domain.scope import (  # noqa: E401
    _menu_ajustar_escopo_atividades,
    _proximo_caminho_livre,
)
from .domain.terrain import avaliar_terreno  # noqa: E401