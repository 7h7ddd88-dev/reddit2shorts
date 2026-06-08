"""
Orchestrator Registry

Автоматическая регистрация оркестраторов для CLI и конфигурации.
"""

from typing import Dict, Type, Any, Optional
from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class OrchestratorRegistry:
    """
    Реестр оркестраторов для автоматической регистрации.
    
    Usage:
        @OrchestratorRegistry.register("reddit", "reddit")
        class RedditOrchestrator(BaseOrchestrator):
            ...
    """
    
    _orchestrators: Dict[str, Dict[str, Any]] = {}
    _initialized: bool = False
    
    @classmethod
    def register(
        cls,
        flow_name: str,
        config_key: str,
        cli_command: Optional[str] = None,
        description: Optional[str] = None
    ):
        """
        Декоратор для регистрации оркестратора.
        
        Args:
            flow_name: Имя флоу (для логов, YouTube канала)
            config_key: Ключ в config.yaml
            cli_command: Команда CLI (если None, используется flow_name)
            description: Описание для CLI help
        """
        def decorator(orchestrator_class: Type):
            cli_cmd = cli_command or flow_name
            
            cls._orchestrators[flow_name] = {
                "class": orchestrator_class,
                "config_key": config_key,
                "cli_command": cli_cmd,
                "description": description or f"{flow_name} video workflow"
            }
            
            logger.debug(f"Registered orchestrator: {flow_name} -> {orchestrator_class.__name__}")
            
            return orchestrator_class
        
        return decorator
    
    @classmethod
    def _ensure_initialized(cls):
        """Ensure all orchestrators are imported and registered."""
        if cls._initialized:
            return
        
        # Import all orchestrator modules to trigger registration
        try:
            from reddit2shorts.core.reddit_orchestrator import RedditOrchestrator
            from reddit2shorts.core.knights_orchestrator import KnightsOrchestrator
            from reddit2shorts.core.darkmotiv_orchestrator import DarkMotivOrchestrator
            from reddit2shorts.core.longform_orchestrator import LongformOrchestrator
            from reddit2shorts.core.brainrot_orchestrator import BrainrotOrchestrator
            from reddit2shorts.core.roblox_brainrot_orchestrator import RobloxBrainrotOrchestrator
            from reddit2shorts.core.asmr_brainrot_orchestrator import ASMRBrainrotOrchestrator
            
            cls._initialized = True
            logger.debug(f"Initialized registry with {len(cls._orchestrators)} orchestrators")
        except ImportError as e:
            logger.warning(f"Failed to import some orchestrators: {e}")
    
    @classmethod
    def get_orchestrator(cls, flow_name: str) -> Optional[Type]:
        """Получить класс оркестратора по имени флоу."""
        cls._ensure_initialized()
        entry = cls._orchestrators.get(flow_name)
        return entry["class"] if entry else None
    
    @classmethod
    def get_all(cls) -> Dict[str, Dict[str, Any]]:
        """Получить все зарегистрированные оркестраторы."""
        cls._ensure_initialized()
        return cls._orchestrators.copy()
    
    @classmethod
    def get_config_keys(cls) -> Dict[str, str]:
        """Получить маппинг flow_name -> config_key."""
        cls._ensure_initialized()
        return {
            name: info["config_key"]
            for name, info in cls._orchestrators.items()
        }
    
    @classmethod
    def get_cli_commands(cls) -> Dict[str, Dict[str, Any]]:
        """Получить маппинг cli_command -> orchestrator info."""
        cls._ensure_initialized()
        return {
            info["cli_command"]: {
                "flow_name": name,
                "class": info["class"],
                "description": info["description"]
            }
            for name, info in cls._orchestrators.items()
        }
