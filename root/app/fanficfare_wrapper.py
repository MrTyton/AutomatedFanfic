"""
FanFicFare Native Python API Wrapper

This module provides a native Python interface to FanFicFare functionality,
replacing subprocess CLI calls with direct Python API usage for improved
performance and better error handling.

Key Features:
    - Direct Python API calls instead of subprocess command execution
    - Enhanced error reporting with structured exception handling  
    - Better performance by eliminating interpreter startup overhead
    - Improved logging and debugging capabilities
    - Configuration support equivalent to CLI parameters

Architecture:
    Wraps FanFicFare's native Python API to provide the same functionality
    as the CLI commands but with direct Python function calls. Handles
    configuration setup, adapter initialization, and story downloading
    with appropriate error handling and logging.

Functions:
    execute_fanficfare: Main entry point replacing CLI command execution
    create_configuration: Sets up FanFicFare configuration from parameters
    get_download_options: Converts CLI flags to API parameters
    handle_fanficfare_exceptions: Structured exception handling

Dependencies:
    - fanficfare: Core FanFicFare package for story downloading
    - fanficfare.cli: CLI module for configuration and utility functions
    - fanficfare.adapters: Adapter system for site-specific handling
    - fanficfare.writers: Output format writers (EPUB, etc.)

Example:
    ```python
    from fanficfare_wrapper import execute_fanficfare
    
    # Replace CLI subprocess call
    options = {
        'update': True,
        'force': False,
        'update_cover': True,
        'non_interactive': True
    }
    
    result = execute_fanficfare("https://example.com/story/123", 
                               "/tmp/workdir", options)
    if result.success:
        print(f"Downloaded: {result.output_filename}")
    else:
        print(f"Failed: {result.error_message}")
    ```
"""

import os
import sys
import io
import tempfile
from dataclasses import dataclass
from typing import Optional, Dict, Any, Union
from contextlib import redirect_stdout, redirect_stderr

import fanficfare
import fanficfare.cli as cli
import fanficfare.adapters as adapters
import fanficfare.writers as writers
import fanficfare.exceptions as exceptions

import ff_logging
import calibre_info


@dataclass
class FanFicFareResult:
    """
    Result object for FanFicFare operations.
    
    Attributes:
        success: Whether the operation completed successfully
        output_filename: Path to the generated story file (if successful)
        error_message: Error description (if failed)
        output_text: Raw output that would have been printed to stdout
        metadata: Story metadata (if available)
        chapter_count: Number of chapters processed
        exception: Original exception object (if failed)
    """
    success: bool
    output_filename: Optional[str] = None
    error_message: Optional[str] = None
    output_text: str = ""
    metadata: Optional[Dict[str, Any]] = None
    chapter_count: Optional[int] = None
    exception: Optional[Exception] = None


def create_configuration(
    url_or_path: str,
    work_dir: str,
    cdb: calibre_info.CalibreInfo,
    update_mode: str = "update",
    force: bool = False,
    update_always: bool = False,
    update_cover: bool = True,
    chapter_begin: Optional[int] = None,
    chapter_end: Optional[int] = None
) -> Any:
    """
    Create FanFicFare configuration object from parameters.
    
    This function sets up the configuration that FanFicFare needs,
    including personal.ini and defaults.ini files from the Calibre
    configuration directory.
    
    Args:
        url_or_path: Story URL or file path to process
        work_dir: Working directory for temporary files
        cdb: Calibre configuration information
        update_mode: Update method (update, update_always, force, update_no_force)
        force: Whether to force update regardless of chapter count
        update_always: Whether to re-download all chapters
        update_cover: Whether to update cover image
        chapter_begin: Starting chapter number (optional)
        chapter_end: Ending chapter number (optional)
        
    Returns:
        FanFicFare Configuration object
        
    Note:
        This function loads configuration files from the Calibre
        configuration directory to ensure consistent behavior with
        the original CLI implementation.
    """
    # Change to working directory for file operations
    original_cwd = os.getcwd()
    os.chdir(work_dir)
    
    try:
        # Load configuration files (personal.ini, defaults.ini)
        personal_ini_path = os.path.join(work_dir, "personal.ini") 
        defaults_ini_path = os.path.join(work_dir, "defaults.ini")
        
        # Read configuration files if they exist
        passed_personal = None
        passed_defaults = None
        
        try:
            if os.path.exists(personal_ini_path):
                with open(personal_ini_path, 'r') as f:
                    passed_personal = f.read()
        except Exception:
            # If we can't read personal.ini, continue without it
            pass
                
        try:
            if os.path.exists(defaults_ini_path):
                with open(defaults_ini_path, 'r') as f:
                    passed_defaults = f.read()
        except Exception:
            # If we can't read defaults.ini, continue without it
            pass
        
        # Create configuration using FanFicFare's get_configuration
        configuration = cli.get_configuration(
            url_or_path,
            passed_defaults,
            passed_personal,
            None,  # options will be set separately
            None,  # chaptercount
            None   # output_filename
        )
        
        return configuration
        
    finally:
        os.chdir(original_cwd)


def execute_fanficfare(
    url_or_path: str,
    work_dir: str,
    cdb: calibre_info.CalibreInfo,
    update_mode: str = "update",
    force: bool = False,
    update_always: bool = False,
    update_cover: bool = True,
    chapter_begin: Optional[int] = None,
    chapter_end: Optional[int] = None
) -> FanFicFareResult:
    """
    Execute FanFicFare download/update using native Python API.
    
    This function replaces the CLI subprocess call with direct Python
    API usage, providing the same functionality with better performance
    and error handling.
    
    Args:
        url_or_path: Story URL or existing file path to update
        work_dir: Working directory for temporary files and output
        cdb: Calibre configuration information
        update_mode: Update method from config (update, update_always, force, update_no_force)
        force: Whether to force update (overrides normal update logic)
        update_always: Whether to re-download all chapters
        update_cover: Whether to update cover image
        chapter_begin: Starting chapter number for range downloads
        chapter_end: Ending chapter number for range downloads
        
    Returns:
        FanFicFareResult object containing success status, output info, and any errors
        
    The function handles all the same logic as the CLI version including:
    - Configuration file loading
    - Update vs new download detection
    - Chapter count comparison
    - Error handling for various failure modes
    - Output file generation
    """
    original_cwd = os.getcwd()
    
    # Capture stdout/stderr for output parsing
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    
    try:
        os.chdir(work_dir)
        
        # Determine if this is an update operation
        is_update = os.path.exists(url_or_path) and url_or_path.endswith('.epub')
        
        # Extract URL and chapter count if updating from file
        url = url_or_path
        existing_chapter_count = None
        output_filename = None
        
        if is_update:
            try:
                url, existing_chapter_count = cli.get_dcsource_chaptercount(url_or_path)
                output_filename = url_or_path
                ff_logging.log_debug(f"Updating {url_or_path}, URL: {url}")
            except Exception as e:
                # If we can't read the file, treat as new download
                ff_logging.log_debug(f"Failed to read epub for update: {e}, treating as new download")
                is_update = False
                url = url_or_path
        
        # Create configuration
        configuration = create_configuration(
            url, work_dir, cdb, update_mode, force, update_always, 
            update_cover, chapter_begin, chapter_end
        )
        
        # Redirect output for capture
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            
            # Get URL and chapter range
            url, ch_begin, ch_end = adapters.get_url_chapter_range(url)
            
            # Get adapter for the story
            adapter = adapters.getAdapter(configuration, url)
            
            # Set chapter range if specified
            if ch_begin or ch_end:
                adapter.setChaptersRange(ch_begin, ch_end)
            elif chapter_begin or chapter_end:
                adapter.setChaptersRange(chapter_begin, chapter_end)
            
            # Handle update logic
            if is_update and not force:
                # Get story metadata to check chapter count
                story_metadata = adapter.getStoryMetadataOnly()
                url_chapter_count = story_metadata.getChapterCount()
                
                if existing_chapter_count == url_chapter_count and not update_always:
                    ff_logging.log_debug(f"Story already contains {existing_chapter_count} chapters")
                    return FanFicFareResult(
                        success=True,
                        output_filename=output_filename,
                        output_text=f"{output_filename} already contains {existing_chapter_count} chapters.",
                        chapter_count=existing_chapter_count
                    )
                elif existing_chapter_count > url_chapter_count and not update_always:
                    error_msg = f"Local file contains {existing_chapter_count} chapters, more than source: {url_chapter_count}"
                    ff_logging.log_debug(error_msg)
                    return FanFicFareResult(
                        success=False,
                        error_message=error_msg,
                        output_text=error_msg
                    )
                elif existing_chapter_count == 0:
                    error_msg = f"{output_filename} doesn't contain any recognizable chapters, probably from a different source. Not updating."
                    ff_logging.log_debug(error_msg)
                    return FanFicFareResult(
                        success=False,
                        error_message=error_msg,
                        output_text=error_msg
                    )
                else:
                    # Perform update - load existing data
                    update_data = cli.get_update_data(output_filename)
                    (url, existing_chapter_count, adapter.oldchapters, 
                     adapter.oldimgs, adapter.oldcover, adapter.calibrebookmark,
                     adapter.logfile, adapter.oldchaptersmap, 
                     adapter.oldchaptersdata) = update_data[0:9]
                    
                    ff_logging.log_debug(f"Do update - epub({existing_chapter_count}) vs url({url_chapter_count})")
            
            # Write the story
            output_filename = cli.write_story(configuration, adapter, 'epub', 
                                            metaonly=False, nooutput=False)
            
            # Get metadata for result
            metadata = adapter.getStoryMetadataOnly().getAllMetadata()
            chapter_count = metadata.get('numChapters', 0)
            
            # Check for chapter download errors
            if hasattr(adapter.story, 'chapter_error_count') and adapter.story.chapter_error_count > 0:
                error_msg = f"{adapter.story.chapter_error_count} chapters errored downloading {url}"
                ff_logging.log_debug(error_msg)
                return FanFicFareResult(
                    success=False,
                    error_message=error_msg,
                    output_text=stdout_capture.getvalue(),
                    output_filename=output_filename,
                    metadata=metadata,
                    chapter_count=chapter_count
                )
            
            return FanFicFareResult(
                success=True,
                output_filename=output_filename,
                output_text=stdout_capture.getvalue(),
                metadata=metadata,
                chapter_count=chapter_count
            )
    
    except exceptions.InvalidStoryURL as e:
        error_msg = f"Invalid story URL: {e}"
        ff_logging.log_debug(error_msg)
        return FanFicFareResult(
            success=False,
            error_message=error_msg,
            output_text=stdout_capture.getvalue(),
            exception=e
        )
    
    except exceptions.StoryDoesNotExist as e:
        error_msg = f"Story does not exist: {e}"
        ff_logging.log_debug(error_msg)
        return FanFicFareResult(
            success=False,
            error_message=error_msg,
            output_text=stdout_capture.getvalue(),
            exception=e
        )
    
    except exceptions.UnknownSite as e:
        error_msg = f"Unknown site: {e}"
        ff_logging.log_debug(error_msg)
        return FanFicFareResult(
            success=False,
            error_message=error_msg,
            output_text=stdout_capture.getvalue(),
            exception=e
        )
    
    except exceptions.AccessDenied as e:
        error_msg = f"Access denied: {e}"
        ff_logging.log_debug(error_msg)
        return FanFicFareResult(
            success=False,
            error_message=error_msg,
            output_text=stdout_capture.getvalue(),
            exception=e
        )
    
    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        ff_logging.log_debug(error_msg)
        return FanFicFareResult(
            success=False,
            error_message=error_msg,
            output_text=stdout_capture.getvalue(),
            exception=e
        )
    
    finally:
        os.chdir(original_cwd)


def get_update_mode_params(update_method: str, force_requested: bool) -> tuple[str, bool, bool]:
    """
    Convert update method configuration to FanFicFare parameters.
    
    Args:
        update_method: Update method from config (update, update_always, force, update_no_force)
        force_requested: Whether force was explicitly requested
        
    Returns:
        Tuple of (update_mode, force, update_always) parameters
    """
    if update_method == "update_no_force":
        # Special case: ignore all force requests
        return ("update", False, False)
    elif force_requested or update_method == "force":
        # Use force when explicitly requested or configured
        return ("force", True, False)
    elif update_method == "update_always":
        # Always perform full refresh
        return ("update", False, True)
    else:  # Default to 'update' behavior
        # Normal update - only download new chapters
        return ("update", False, False)