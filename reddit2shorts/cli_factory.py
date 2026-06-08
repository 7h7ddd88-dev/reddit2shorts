"""
CLI Command Factory

Автоматическая генерация CLI команд из OrchestratorRegistry.
Устраняет дублирование кода - каждая команда генерируется автоматически.
"""

from typing import Dict, Any, Optional, Callable
import click
import asyncio
import sys

from reddit2shorts.core.registry import OrchestratorRegistry
from reddit2shorts.config.settings import Settings, load_settings
from reddit2shorts.utils.logger import setup_logging, get_logger
from reddit2shorts.core.exceptions import ConfigurationError


class CLICommandFactory:
    """
    Фабрика для автоматической генерации CLI команд из Registry.
    
    Каждый зарегистрированный orchestrator автоматически получает CLI команду
    с стандартным набором опций и логикой выполнения.
    """
    
    @staticmethod
    def _load_config(config_path: Optional[str]) -> Settings:
        """Загрузка конфигурации"""
        if config_path:
            click.echo(f"Loading config from: {config_path}")
        
        try:
            settings = load_settings()
            return settings
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration: {e}")
    
    @staticmethod
    def _settings_to_dict(settings: Settings) -> dict:
        """
        Convert Settings object to dictionary for orchestrator.
        
        Automatically loads ALL flow configs from YAML based on OrchestratorRegistry.
        """
        import yaml
        from pathlib import Path
        
        # Load full YAML config
        config_path = Path("config.yaml")
        yaml_config = {}
        if config_path.exists():
            with open(config_path, encoding='utf-8') as f:
                yaml_config = yaml.safe_load(f) or {}
        
        # Build base config
        config_dict = {
            "default_proxy": yaml_config.get("default_proxy"),  # CRITICAL: Global proxy for Gemini/Pollinations
            "reddit": yaml_config.get("reddit", {
                "use_public_api": settings.reddit.use_public_api,
                "client_id": settings.reddit.client_id,
                "client_secret": settings.reddit.client_secret,
                "user_agent": settings.reddit.user_agent,
                "subreddit": settings.reddit.subreddit,
                "sort": settings.reddit.sort,
                "time_filter": settings.reddit.time_filter,
            }),
            "google_sheets": {
                "credentials_file": settings.google_sheets.credentials_file,
                "spreadsheet_id": settings.google_sheets.spreadsheet_id,
                "worksheet_name": settings.google_sheets.worksheet_name,
            },
            "llm": {
                "providers": [
                    {
                        "name": p.name,
                        "api_keys": p.api_keys,
                        "base_url": p.base_url,
                        "model": p.model,
                        "max_tokens": p.max_tokens,
                        "temperature": p.temperature,
                    }
                    for p in settings.llm.providers
                ],
                "max_retries": settings.llm.max_retries,
                "retry_delay": settings.llm.retry_delay,
            },
            "image": {
                "provider": settings.image.provider,
                "pollinations_api_key": settings.image.pollinations_api_key,
                "pollinations_url": settings.image.pollinations_url,
                "gemini_api_keys": settings.image.gemini_api_keys,
                "gemini_model": settings.image.gemini_model,
                "model": settings.image.model,
                "size": settings.image.size,
                "quality": settings.image.quality,
                "max_retries": settings.image.max_retries,
                "placeholder_image_path": settings.image.placeholder_image_path,
            },
            "tts": yaml_config.get("tts", {
                "provider": settings.tts.provider,
                "local_url": settings.tts.local_url,
                "tts_engine": settings.tts.tts_engine,
                "kokoro_api_key": settings.tts.kokoro_api_key,
                "kokoro_api_url": settings.tts.kokoro_api_url,
                "kokoro_voice": settings.tts.kokoro_voice,
                "kokoro_speed": settings.tts.kokoro_speed,
                "chatterbox_api_key": settings.tts.chatterbox_api_key,
                "chatterbox_api_url": settings.tts.chatterbox_api_url,
                "chatterbox_clone_voice_id": settings.tts.chatterbox_clone_voice_id,
                "chatterbox_exaggeration": settings.tts.chatterbox_exaggeration,
                "chatterbox_cfg_weight": settings.tts.chatterbox_cfg_weight,
                "chatterbox_temperature": settings.tts.chatterbox_temperature,
                "pollinations_api_keys": settings.tts.pollinations_api_keys,
                "pollinations_voice": settings.tts.pollinations_voice,
                "pollinations_speed": settings.tts.pollinations_speed,
                "pollinations_model": settings.tts.pollinations_model,
                "pollinations_response_format": settings.tts.pollinations_response_format,
                "voice": settings.tts.voice,
                "speed": settings.tts.speed,
            }),
            "video": {
                "provider": settings.video.provider,
                "local_url": settings.video.local_url,
                "api_url": settings.video.api_url,
                "api_key": settings.video.api_key,
                "subtitle_font": settings.video.subtitle_font,
                "subtitle_size": settings.video.subtitle_size,
                "subtitle_color": settings.video.subtitle_color,
                "background_music_volume": settings.video.background_music_volume,
                "polling_interval": settings.video.polling_interval,
                "timeout": settings.video.timeout,
            },
            "gemini": yaml_config.get("gemini", {}),
            "pollinations": yaml_config.get("pollinations", {}),
            "scheduled_publishing": yaml_config.get("scheduled_publishing", {}),
            "output_dir": settings.output_dir,
            "temp_dir": settings.temp_dir,
            "log_level": settings.log_level,
            "log_file": settings.log_file,
            "background_music_path": yaml_config.get("background_music_path", "music/reddit.mp3"),
            "cleanup_temp_files": yaml_config.get("cleanup_temp_files", True),
            "processed_stories_file": yaml_config.get("processed_stories_file", "processed_stories.json"),
        }
        
        # AUTOMATICALLY load ALL flow configs from registry
        config_keys = OrchestratorRegistry.get_config_keys()
        for flow_name, config_key in config_keys.items():
            if config_key in yaml_config:
                config_dict[config_key] = yaml_config[config_key]
        
        return config_dict
    
    @staticmethod
    def _print_results(results: list, flow_name: str):
        """Вывод результатов workflow"""
        click.echo("\nResults:")
        click.echo("-" * 50)
        
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        
        for i, result in enumerate(results, 1):
            status = "[OK]" if result.success else "[FAIL]"
            
            # Определяем ID (может быть story_id или video_id)
            result_id = getattr(result, 'story_id', None) or getattr(result, 'video_id', 'unknown')
            
            click.echo(f"{i}. {status} {flow_name.title()}: {result_id}")
            
            if result.success:
                if result.video_url:
                    click.echo(f"   URL: {result.video_url}")
                click.echo(f"   Duration: {result.duration:.2f}s")
                
                # Flow-specific данные
                if hasattr(result, 'segments_count'):
                    click.echo(f"   Segments: {result.segments_count}")
                if hasattr(result, 'prompt'):
                    click.echo(f"   Prompt: {result.prompt[:60]}...")
            else:
                click.echo(f"   Error: {result.error}")
        
        click.echo("-" * 50)
        click.echo(f"Success: {successful}/{len(results)}")
        if failed > 0:
            click.echo(f"Failed: {failed}/{len(results)}")
    
    @classmethod
    def create_command(cls, flow_name: str, orchestrator_info: Dict[str, Any]) -> Callable:
        """
        Создает CLI команду для конкретного flow.
        
        Args:
            flow_name: Имя flow (knights, darkmotiv, etc.)
            orchestrator_info: Информация из Registry
            
        Returns:
            Click command function
        """
        orchestrator_class = orchestrator_info['class']
        description = orchestrator_info['description']
        
        # Special handling for darkmotiv (supports both shorts and longform)
        if flow_name == 'darkmotiv':
            return cls._create_darkmotiv_command(orchestrator_class, orchestrator_info)
        
        @click.command(name=orchestrator_info['cli_command'])
        @click.option('--num-videos', default=1, type=int, 
                     help='Number of videos to create')
        @click.option('--dry-run', is_flag=True, 
                     help='Run without YouTube upload')
        @click.option('--daily-batch', is_flag=True, 
                     help='Run daily batch with scheduled publishing')
        @click.option('--config', default=None, type=click.Path(exists=False),
                     help='Configuration file path')
        @click.option('--verbose', is_flag=True, 
                     help='Enable verbose logging')
        @click.option('--log-level', default=None,
                     help='Log level (DEBUG|INFO|WARNING|ERROR)')
        def command(num_videos: int, dry_run: bool, daily_batch: bool,
                   config: Optional[str], verbose: bool, log_level: Optional[str]):
            f"""{description}"""
            
            click.echo(f"Reddit2Shorts - {flow_name.title()} Mode")
            click.echo("=" * 50)
            
            try:
                # Load configuration
                settings = cls._load_config(config)
                
                # Override settings from CLI arguments
                if log_level:
                    settings.log_level = log_level
                elif verbose:
                    settings.log_level = "DEBUG"
                
                # Setup logging
                setup_logging(
                    log_level=settings.log_level,
                    log_file=settings.log_file
                )
                
                logger = get_logger(__name__)
                
                # Convert settings to dict
                config_dict = cls._settings_to_dict(settings)
                
                # Create orchestrator - check if it accepts dry_run parameter
                import inspect
                sig = inspect.signature(orchestrator_class.__init__)
                if 'dry_run' in sig.parameters:
                    orchestrator = orchestrator_class(config_dict, dry_run=dry_run)
                else:
                    orchestrator = orchestrator_class(config_dict)
                
                # Run workflow
                if daily_batch:
                    click.echo(f"\nStarting daily batch workflow")
                    click.echo(f"  Mode: {flow_name.title()}")
                    click.echo(f"  Scheduled Publishing: Enabled")
                    click.echo()
                    
                    logger.info(f"Calling run_daily_batch()")
                    results = asyncio.run(orchestrator.run_daily_batch())
                else:
                    click.echo(f"\nStarting {flow_name} workflow:")
                    click.echo(f"  Videos: {num_videos}")
                    click.echo(f"  Dry Run: {dry_run}")
                    click.echo()
                    
                    logger.info(f"Calling run_workflow(num_videos={num_videos}, dry_run={dry_run})")
                    results = asyncio.run(orchestrator.run_workflow(
                        num_videos=num_videos,
                        dry_run=dry_run
                    ))
                
                cls._print_results(results, flow_name)
                
                click.echo("\n" + "=" * 50)
                click.echo(f"✓ {flow_name.title()} workflow complete!")
                
            except KeyboardInterrupt:
                click.echo("\n\n✗ Interrupted by user")
                sys.exit(130)
            except Exception as e:
                click.echo(f"\n✗ Error: {e}", err=True)
                if verbose:
                    import traceback
                    traceback.print_exc()
                sys.exit(1)
        
        return command
    
    @classmethod
    def _create_darkmotiv_command(cls, orchestrator_class, orchestrator_info: Dict[str, Any]) -> Callable:
        """
        Создает специальную CLI команду для DarkMotiv с поддержкой longform.
        
        Args:
            orchestrator_class: Класс DarkMotivOrchestrator
            orchestrator_info: Информация из Registry
            
        Returns:
            Click command function
        """
        @click.command(name=orchestrator_info['cli_command'])
        @click.option('--num-videos', default=1, type=int, 
                     help='Number of videos to create')
        @click.option('--dry-run', is_flag=True, 
                     help='Run without YouTube upload')
        @click.option('--daily-batch', is_flag=True, 
                     help='Run daily batch with scheduled publishing (1 long + 5 shorts)')
        @click.option('--longform', is_flag=True, 
                     help='Create a single longform video (5-7 minutes)')
        @click.option('--topic', default=None, 
                     help='Topic for longform video (optional)')
        @click.option('--config', default=None, type=click.Path(exists=False),
                     help='Configuration file path')
        @click.option('--verbose', is_flag=True, 
                     help='Enable verbose logging')
        @click.option('--log-level', default=None,
                     help='Log level (DEBUG|INFO|WARNING|ERROR)')
        def darkmotiv_command(num_videos: int, dry_run: bool, daily_batch: bool,
                             longform: bool, topic: Optional[str],
                             config: Optional[str], verbose: bool, log_level: Optional[str]):
            """Create dark motivational videos from dark aesthetic images.
            
            Supports both short videos (10-15 seconds) and longform videos (5-7 minutes).
            
            Examples:
            
                # Create 3 short videos
                reddit2shorts darkmotiv --num-videos 3
                
                # Create a single longform video (5-7 minutes)
                reddit2shorts darkmotiv --longform
                
                # Create longform with custom topic
                reddit2shorts darkmotiv --longform --topic "Stoic wisdom for modern life"
                
                # Daily batch (1 longform + 5 shorts with scheduled publishing)
                reddit2shorts darkmotiv --daily-batch
            """
            click.echo("Reddit2Shorts - DarkMotiv Mode")
            click.echo("=" * 50)
            
            try:
                # Load configuration
                settings = cls._load_config(config)
                
                # Override settings from CLI arguments
                if log_level:
                    settings.log_level = log_level
                elif verbose:
                    settings.log_level = "DEBUG"
                
                # Setup logging
                setup_logging(
                    log_level=settings.log_level,
                    log_file=settings.log_file
                )
                
                logger = get_logger(__name__)
                
                # Convert settings to dict
                config_dict = cls._settings_to_dict(settings)
                
                # Create orchestrator
                orchestrator = orchestrator_class(config_dict)
                
                # Run workflow based on mode
                if daily_batch:
                    click.echo(f"\nStarting daily batch workflow")
                    click.echo(f"  Mode: DarkMotiv")
                    click.echo(f"  Videos: 1 longform + 5 shorts = 6 total")
                    click.echo(f"  Order: Longform first, then shorts")
                    click.echo(f"  Scheduled Publishing: Enabled")
                    click.echo()
                    
                    results = asyncio.run(orchestrator.run_daily_batch())
                    
                elif longform:
                    click.echo(f"\nStarting longform video creation:")
                    click.echo(f"  Mode: DarkMotiv Longform")
                    click.echo(f"  Duration: 5-7 minutes")
                    click.echo(f"  Topic: {topic or 'Random'}")
                    click.echo(f"  Dry Run: {dry_run}")
                    click.echo()
                    
                    result = asyncio.run(orchestrator.create_longform_video(
                        topic=topic,
                        dry_run=dry_run
                    ))
                    results = [result]
                    
                else:
                    click.echo(f"\nStarting dark motiv workflow:")
                    click.echo(f"  Mode: Short videos (10-15 seconds)")
                    click.echo(f"  Videos: {num_videos}")
                    click.echo(f"  Dry Run: {dry_run}")
                    click.echo()
                    
                    results = asyncio.run(orchestrator.run_workflow(
                        num_videos=num_videos,
                        dry_run=dry_run
                    ))
                
                cls._print_results(results, 'darkmotiv')
                
                click.echo("\n" + "=" * 50)
                click.echo("✓ DarkMotiv workflow complete!")
                
            except KeyboardInterrupt:
                click.echo("\n\n✗ Interrupted by user")
                sys.exit(130)
            except Exception as e:
                click.echo(f"\n✗ Error: {e}", err=True)
                if verbose:
                    import traceback
                    traceback.print_exc()
                sys.exit(1)
        
        return darkmotiv_command
    
    @classmethod
    def register_all_commands(cls, cli_group: click.Group):
        """
        Регистрирует все команды из Registry в CLI group.
        
        Args:
            cli_group: Click group для регистрации команд
        """
        all_orchestrators = OrchestratorRegistry.get_all()
        
        for flow_name, info in all_orchestrators.items():
            command = cls.create_command(flow_name, info)
            cli_group.add_command(command)
            
            logger = get_logger(__name__)
            logger.debug(f"Registered CLI command: {info['cli_command']} -> {flow_name}")
