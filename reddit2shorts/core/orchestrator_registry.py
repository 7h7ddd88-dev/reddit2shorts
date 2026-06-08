"""
Orchestrator Registry for automatic flow registration.

Provides:
- Automatic orchestrator discovery
- Flow registration
- CLI command generation
"""

from typing import Dict, Type, Any, Optional
from reddit2shorts.core.base_orchestrator import BaseOrchestrator


class OrchestratorRegistry:
    """
    Registry for automatic orchestrator discovery and registration.
    
    Usage:
        @OrchestratorRegistry.register("brainrot")
        class BrainrotOrchestrator(BaseOrchestrator, VideoGenerationMixin):
            ...
    """
    
    _registry: Dict[str, Type[BaseOrchestrator]] = {}
    
    @classmethod
    def register(cls, flow_name: str):
        """
        Decorator to register an orchestrator.
        
        Args:
            flow_name: Name of the flow (e.g., "brainrot", "knights")
            
        Returns:
            Decorator function
        """
        def decorator(orchestrator_class: Type[BaseOrchestrator]):
            cls._registry[flow_name] = orchestrator_class
            return orchestrator_class
        
        return decorator
    
    @classmethod
    def get_orchestrator(cls, flow_name: str) -> Optional[Type[BaseOrchestrator]]:
        """
        Get orchestrator class by flow name.
        
        Args:
            flow_name: Name of the flow
            
        Returns:
            Orchestrator class or None
        """
        return cls._registry.get(flow_name)
    
    @classmethod
    def create_orchestrator(
        cls,
        flow_name: str,
        config: Dict[str, Any],
        dry_run: bool = False
    ) -> Optional[BaseOrchestrator]:
        """
        Create orchestrator instance.
        
        Args:
            flow_name: Name of the flow
            config: Configuration dict
            dry_run: Dry-run mode
            
        Returns:
            Orchestrator instance or None
        """
        orchestrator_class = cls.get_orchestrator(flow_name)
        
        if orchestrator_class is None:
            return None
        
        return orchestrator_class(config=config, flow_name=flow_name, dry_run=dry_run)
    
    @classmethod
    def get_all_flows(cls) -> list[str]:
        """
        Get list of all registered flows.
        
        Returns:
            List of flow names
        """
        return list(cls._registry.keys())
    
    @classmethod
    def is_registered(cls, flow_name: str) -> bool:
        """
        Check if flow is registered.
        
        Args:
            flow_name: Name of the flow
            
        Returns:
            True if registered
        """
        return flow_name in cls._registry
