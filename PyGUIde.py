import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog
import subprocess
import sys
import os
import ast
import threading
import queue
import re
from pathlib import Path
import json
from datetime import datetime
import importlib.util
import pkg_resources
import venv

# Set the appearance mode and color theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class CodeAnalyzer:
    """Analyzes Python code to provide insights and suggestions"""
    
    @staticmethod
    def analyze_code(code):
        """Analyze code and return insights"""
        insights = {
            'functions': [],
            'classes': [],
            'imports': [],
            'variables': [],
            'complexity_score': 0,
            'suggestions': []
        }
        
        try:
            tree = ast.parse(code)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    insights['functions'].append({
                        'name': node.name,
                        'line': node.lineno,
                        'args': len(node.args.args)
                    })
                elif isinstance(node, ast.ClassDef):
                    insights['classes'].append({
                        'name': node.name,
                        'line': node.lineno
                    })
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        insights['imports'].append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for alias in node.names:
                            insights['imports'].append(f"{node.module}.{alias.name}")
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            insights['variables'].append(target.id)
            
            # Calculate complexity score (simplified)
            insights['complexity_score'] = len(insights['functions']) * 2 + len(insights['classes']) * 3
            
            # Generate suggestions
            if not insights['functions'] and not insights['classes'] and len(code.strip()) > 50:
                insights['suggestions'].append("Consider organizing your code into functions")
            
            if len(insights['imports']) > 5:
                insights['suggestions'].append("Consider organizing imports at the top")
                
        except SyntaxError as e:
            insights['syntax_error'] = str(e)
            
        return insights

class DependencyManager:
    """Manages project dependencies and virtual environments"""
    
    def __init__(self, project_path=None):
        self.project_path = project_path
        self.venv_path = None
        self.python_executable = sys.executable
        
        if project_path:
            self.detect_venv()
    
    def detect_venv(self):
        """Detect virtual environment in project"""
        if not self.project_path:
            return False
            
        venv_candidates = ['venv', 'env', '.venv', '.env']
        for candidate in venv_candidates:
            potential_venv = os.path.join(self.project_path, candidate)
            if os.path.isdir(potential_venv):
                # Check if it's a valid venv
                if os.name == 'nt':  # Windows
                    python_exe = os.path.join(potential_venv, 'Scripts', 'python.exe')
                else:  # Unix/Linux/macOS
                    python_exe = os.path.join(potential_venv, 'bin', 'python')
                
                if os.path.exists(python_exe):
                    self.venv_path = potential_venv
                    self.python_executable = python_exe
                    return True
        self.venv_path = None
        self.python_executable = sys.executable
        return False
    
    def create_venv(self, venv_name='venv'):
        """Create a new virtual environment"""
        if not self.project_path:
            raise Exception("No project path set")
        
        venv_path = os.path.join(self.project_path, venv_name)
        if os.path.exists(venv_path):
            raise Exception(f"Virtual environment '{venv_name}' already exists")
        
        # Create virtual environment
        venv.create(venv_path, with_pip=True)
        
        self.venv_path = venv_path
        if os.name == 'nt':  # Windows
            self.python_executable = os.path.join(venv_path, 'Scripts', 'python.exe')
        else:  # Unix/Linux/macOS
            self.python_executable = os.path.join(venv_path, 'bin', 'python')
        
        return True
    
    def get_installed_packages(self):
        """Get list of installed packages in current environment"""
        try:
            result = subprocess.run(
                [self.python_executable, '-m', 'pip', 'list', '--format=json'],
                capture_output=True,
                text=True,
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            packages = json.loads(result.stdout)
            return {pkg['name'].lower(): pkg['version'] for pkg in packages}
        except Exception:
            return {}
    
    def analyze_imports(self, code_files):
        """Analyze import statements in code files"""
        imports = set()
        
        for file_path in code_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.add(alias.name.split('.')[0])
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imports.add(node.module.split('.')[0])
            except Exception:
                continue
        
        return imports
    
    @staticmethod
    def is_standard_library(module_name):
        """
        Check if a module is part of the Python standard library.
        A module is considered standard library if it's a built-in,
        or if its source file is not in a 'site-packages' or 'dist-packages' directory.
        """
        # A quick check for common invalid module names from AST parsing
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', module_name):
            return True  # Not a valid package name, treat as "not installable"

        if module_name in sys.builtin_module_names:
            return True

        try:
            spec = importlib.util.find_spec(module_name)
        except (ValueError, ModuleNotFoundError, ImportError):
            # If find_spec fails, it's likely not a stdlib module we can import,
            # so it's probably a missing package.
            return False

        if spec is None:
            # Module not found, so it must be a missing package.
            return False

        origin = spec.origin
        if origin is None or origin == 'built-in':
            # `origin` is None for namespace packages.
            # `origin` is 'built-in' for C modules.
            return True

        # The most reliable check: third-party packages are in `site-packages`
        # or `dist-packages`. Stdlib modules are not.
        return 'site-packages' not in origin and 'dist-packages' not in origin

    def get_missing_packages(self, imports):
        """Get packages that are imported but not installed."""
        installed = self.get_installed_packages()
        
        # Special cases where import name differs from package name
        import_to_package_map = {
            'pil': 'pillow',
            'yaml': 'pyyaml',
            'cv2': 'opencv-python',
            'skimage': 'scikit-image',
            'sklearn': 'scikit-learn',
            'bs4': 'beautifulsoup4',
        }

        missing = set()
        for imp in imports:
            if self.is_standard_library(imp):
                continue
            
            imp_lower = imp.lower()
            package_name = import_to_package_map.get(imp_lower, imp_lower)
            
            if package_name not in installed:
                # Use the mapped package name for installation
                install_name = import_to_package_map.get(imp_lower, imp)
                missing.add(install_name)
        
        return sorted(list(missing))

    def install_packages(self, packages, output_callback=None):
        """Install packages using pip"""
        if not packages:
            return True
        
        try:
            cmd = [self.python_executable, '-m', 'pip', 'install'] + packages
            
            if output_callback:
                # Run with live output
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    universal_newlines=True,
                    bufsize=1,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                
                for line in iter(process.stdout.readline, ''):
                    output_callback(line)
                
                process.wait()
                return process.returncode == 0
            else:
                result = subprocess.run(
                    cmd, check=True, capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                return True
                
        except subprocess.CalledProcessError as e:
            if output_callback:
                output_callback(f"Error: {e}\n{e.stderr or e.stdout}\n")
            return False

class SnippetManager:
    """Manages code snippets for quick insertion"""
    
    def __init__(self):
        self.snippets = {
            'Basic Function': 'def function_name():\n    """Function description"""\n    pass\n',
            'Class Template': 'class ClassName:\n    """Class description"""\n    \n    def __init__(self):\n        pass\n',
            'For Loop': 'for item in items:\n    print(item)\n',
            'While Loop': 'while condition:\n    # Do something\n    pass\n',
            'Try-Except': 'try:\n    # Code that might fail\n    pass\nexcept Exception as e:\n    print(f"Error: {e}")\n',
            'File Reading': 'with open("filename.txt", "r") as file:\n    content = file.read()\n    print(content)\n',
            'List Comprehension': 'result = [item for item in items if condition]\n',
            'Dictionary Comprehension': 'result = {key: value for key, value in items.items()}\n'
        }

class OutputRedirector:
    """Redirects stdout to the output widget"""
    
    def __init__(self, text_widget, queue_obj):
        self.text_widget = text_widget
        self.queue = queue_obj
    
    def write(self, string):
        self.queue.put(('stdout', string))
    
    def flush(self):
        pass

class PyGUIde:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("PyGUIde - Interactive Python IDE")
        self.root.geometry("1400x900")
        self.root.iconname("PyGUIde")
        
        # Initialize components
        self.current_file = None
        self.project_path = None
        self.code_analyzer = CodeAnalyzer()
        self.snippet_manager = SnippetManager()
        self.dependency_manager = DependencyManager()
        self.output_queue = queue.Queue()
        
        # Create the UI
        self.create_menu()
        self.create_main_layout()
        self.create_status_bar()
        
        # Start monitoring output queue
        self.monitor_output_queue()
        
        # Bind events
        self.bind_events()
        
        # Load settings
        self.load_settings()
        
    def create_menu(self):
        """Create the main menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New", command=self.new_file, accelerator="Ctrl+N")
        file_menu.add_command(label="Open File", command=self.open_file, accelerator="Ctrl+O")
        file_menu.add_command(label="Open Folder", command=self.open_folder, accelerator="Ctrl+Shift+O")
        file_menu.add_separator()
        file_menu.add_command(label="Save", command=self.save_file, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As", command=self.save_as_file, accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_closing)
        menubar.add_cascade(label="File", menu=file_menu)
        
        # Edit menu
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Undo", command=self.undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Redo", command=self.redo, accelerator="Ctrl+Y")
        edit_menu.add_separator()
        edit_menu.add_command(label="Find", command=self.find_text, accelerator="Ctrl+F")
        edit_menu.add_command(label="Replace", command=self.replace_text, accelerator="Ctrl+H")
        menubar.add_cascade(label="Edit", menu=edit_menu)
        
        # Project menu
        project_menu = tk.Menu(menubar, tearoff=0)
        project_menu.add_command(label="Create Virtual Environment", command=self.create_venv)
        project_menu.add_command(label="Refresh Dependencies", command=self.refresh_dependencies)
        project_menu.add_command(label="Install All Missing Packages", command=self.install_missing_packages)
        menubar.add_cascade(label="Project", menu=project_menu)
        
        # Run menu
        run_menu = tk.Menu(menubar, tearoff=0)
        run_menu.add_command(label="Run Code", command=self.run_code, accelerator="F5")
        run_menu.add_command(label="Stop Execution", command=self.stop_execution)
        run_menu.add_separator()
        run_menu.add_command(label="Check Syntax", command=self.check_syntax)
        menubar.add_cascade(label="Run", menu=run_menu)
        
        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Toggle Dark Mode", command=self.toggle_theme)
        view_menu.add_command(label="Show/Hide Sidebar", command=self.toggle_sidebar)
        menubar.add_cascade(label="View", menu=view_menu)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        help_menu.add_command(label="Python Documentation", command=self.open_python_docs)
        menubar.add_cascade(label="Help", menu=help_menu)
    
    def create_main_layout(self):
        """Create the main layout with paned windows"""
        # Main container
        self.main_container = ctk.CTkFrame(self.root)
        self.main_container.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Horizontal paned window
        self.h_paned = ctk.CTkFrame(self.main_container)
        self.h_paned.pack(fill="both", expand=True)
        
        # Configure grid
        self.h_paned.grid_columnconfigure(1, weight=1)
        self.h_paned.grid_rowconfigure(0, weight=1)
        
        # Left sidebar
        self.create_sidebar()
        
        # Main editing area
        self.create_main_area()
    
    def create_sidebar(self):
        """Create the left sidebar with tools and insights"""
        self.sidebar = ctk.CTkFrame(self.h_paned, width=300)
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.sidebar.grid_propagate(False)
        
        # Sidebar notebook for tabs
        self.sidebar_notebook = ctk.CTkTabview(self.sidebar)
        self.sidebar_notebook.pack(fill="both", expand=True, padx=5, pady=5)
        
        # File Explorer Tab
        self.explorer_tab = self.sidebar_notebook.add("Explorer")
        self.create_file_explorer()
        
        # Dependencies Tab
        self.dependencies_tab = self.sidebar_notebook.add("Dependencies")
        self.create_dependencies_panel()
        
        # Code Insights Tab
        self.insights_tab = self.sidebar_notebook.add("Insights")
        self.create_insights_panel()
        
        # Snippets Tab
        self.snippets_tab = self.sidebar_notebook.add("Snippets")
        self.create_snippets_panel()
        
    def create_dependencies_panel(self):
        """Create the dependencies management panel"""
        # Title
        deps_title = ctk.CTkLabel(self.dependencies_tab, text="Dependencies", 
                                font=ctk.CTkFont(size=16, weight="bold"))
        deps_title.pack(pady=(5, 10))
        
        # Environment info
        self.env_frame = ctk.CTkFrame(self.dependencies_tab)
        self.env_frame.pack(fill="x", padx=5, pady=5)
        
        self.env_label = ctk.CTkLabel(self.env_frame, text="Environment: Global", 
                                    font=ctk.CTkFont(size=12))
        self.env_label.pack(pady=5)
        
        # Create venv button
        self.create_venv_btn = ctk.CTkButton(self.env_frame, text="Create Virtual Env", 
                                           command=self.create_venv)
        self.create_venv_btn.pack(pady=2)
        
        # Dependencies list
        self.deps_frame = ctk.CTkFrame(self.dependencies_tab)
        self.deps_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Headers
        headers_frame = ctk.CTkFrame(self.deps_frame)
        headers_frame.pack(fill="x", padx=5, pady=(5, 0))
        
        ctk.CTkLabel(headers_frame, text="Package", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10)
        ctk.CTkLabel(headers_frame, text="Status", font=ctk.CTkFont(weight="bold")).pack(side="right", padx=10)
        
        # Scrollable dependencies list
        self.deps_list = ctk.CTkScrollableFrame(self.deps_frame)
        self.deps_list.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Control buttons
        buttons_frame = ctk.CTkFrame(self.dependencies_tab)
        buttons_frame.pack(fill="x", padx=5, pady=5)
        
        self.refresh_deps_btn = ctk.CTkButton(buttons_frame, text="Refresh", 
                                            command=self.refresh_dependencies)
        self.refresh_deps_btn.pack(side="left", padx=2)
        
        self.install_all_btn = ctk.CTkButton(buttons_frame, text="Install All Missing", 
                                           command=self.install_missing_packages,
                                           fg_color="green")
        self.install_all_btn.pack(side="right", padx=2)
    
    def create_insights_panel(self):
        """Create the code insights panel"""
        # Title
        insights_title = ctk.CTkLabel(self.insights_tab, text="Code Analysis", 
                                    font=ctk.CTkFont(size=16, weight="bold"))
        insights_title.pack(pady=(5, 10))
        
        # Insights text area
        self.insights_text = ctk.CTkTextbox(self.insights_tab, height=200)
        self.insights_text.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Analyze button
        self.analyze_btn = ctk.CTkButton(self.insights_tab, text="Analyze Code", 
                                       command=self.analyze_current_code)
        self.analyze_btn.pack(pady=5)
        
        # Complexity meter
        self.complexity_frame = ctk.CTkFrame(self.insights_tab)
        self.complexity_frame.pack(fill="x", padx=5, pady=5)
        
        ctk.CTkLabel(self.complexity_frame, text="Complexity:").pack(pady=2)
        self.complexity_progress = ctk.CTkProgressBar(self.complexity_frame)
        self.complexity_progress.pack(fill="x", padx=10, pady=2)
        self.complexity_progress.set(0)
    
    def create_snippets_panel(self):
        """Create the code snippets panel"""
        snippets_title = ctk.CTkLabel(self.snippets_tab, text="Code Snippets", 
                                    font=ctk.CTkFont(size=16, weight="bold"))
        snippets_title.pack(pady=(5, 10))
        
        # Snippets listbox
        self.snippets_frame = ctk.CTkScrollableFrame(self.snippets_tab)
        self.snippets_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        for snippet_name in self.snippet_manager.snippets.keys():
            btn = ctk.CTkButton(self.snippets_frame, text=snippet_name, 
                              command=lambda name=snippet_name: self.insert_snippet(name),
                              height=30)
            btn.pack(fill="x", pady=2)
    
    def create_file_explorer(self):
        """Create a simple file explorer"""
        explorer_title = ctk.CTkLabel(self.explorer_tab, text="File Explorer", 
                                    font=ctk.CTkFont(size=16, weight="bold"))
        explorer_title.pack(pady=(5, 10))
        
        # Project path display
        self.project_path_label = ctk.CTkLabel(self.explorer_tab, text="No project opened")
        self.project_path_label.pack(pady=5)
        
        # Current directory label
        self.current_dir_label = ctk.CTkLabel(self.explorer_tab, text="Current: " + os.getcwd())
        self.current_dir_label.pack(pady=5)
        
        # File list
        self.file_list = ctk.CTkScrollableFrame(self.explorer_tab)
        self.file_list.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.refresh_file_list()
        
        # Control buttons
        buttons_frame = ctk.CTkFrame(self.explorer_tab)
        buttons_frame.pack(fill="x", padx=5, pady=5)
        
        refresh_btn = ctk.CTkButton(buttons_frame, text="Refresh", 
                                  command=self.refresh_file_list)
        refresh_btn.pack(side="left", padx=2)
        
        open_folder_btn = ctk.CTkButton(buttons_frame, text="Open Folder", 
                                      command=self.open_folder)
        open_folder_btn.pack(side="right", padx=2)
    
    def create_main_area(self):
        """Create the main editing area"""
        self.main_area = ctk.CTkFrame(self.h_paned)
        self.main_area.grid(row=0, column=1, sticky="nsew")
        self.main_area.grid_rowconfigure(0, weight=1)
        self.main_area.grid_columnconfigure(0, weight=1)
        
        # Vertical paned window for editor and output
        self.v_paned = ctk.CTkFrame(self.main_area)
        self.v_paned.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.v_paned.grid_rowconfigure(0, weight=2)
        self.v_paned.grid_rowconfigure(1, weight=1)
        self.v_paned.grid_columnconfigure(0, weight=1)
        
        # Editor area
        self.create_editor()
        
        # Output area
        self.create_output_area()
    
    def create_editor(self):
        """Create the code editor"""
        self.editor_frame = ctk.CTkFrame(self.v_paned)
        self.editor_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
        self.editor_frame.grid_rowconfigure(1, weight=1)
        self.editor_frame.grid_columnconfigure(0, weight=1)
        
        # Toolbar
        self.toolbar = ctk.CTkFrame(self.editor_frame, height=40)
        self.toolbar.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        self.toolbar.grid_columnconfigure(6, weight=1)
        
        # Toolbar buttons
        self.new_btn = ctk.CTkButton(self.toolbar, text="New", command=self.new_file, width=60)
        self.new_btn.grid(row=0, column=0, padx=2)
        
        self.open_btn = ctk.CTkButton(self.toolbar, text="Open", command=self.open_file, width=60)
        self.open_btn.grid(row=0, column=1, padx=2)
        
        self.save_btn = ctk.CTkButton(self.toolbar, text="Save", command=self.save_file, width=60)
        self.save_btn.grid(row=0, column=2, padx=2)
        
        self.run_btn = ctk.CTkButton(self.toolbar, text="► Run", command=self.run_code, 
                                   fg_color="green", width=80)
        self.run_btn.grid(row=0, column=3, padx=5)
        
        self.stop_btn = ctk.CTkButton(self.toolbar, text="■ Stop", command=self.stop_execution, 
                                    fg_color="red", width=80)
        self.stop_btn.grid(row=0, column=4, padx=2)
        
        self.syntax_btn = ctk.CTkButton(self.toolbar, text="Check", command=self.check_syntax, width=60)
        self.syntax_btn.grid(row=0, column=5, padx=2)
        
        # Current file label
        self.file_label = ctk.CTkLabel(self.toolbar, text="Untitled.py")
        self.file_label.grid(row=0, column=6, sticky="e", padx=10)
        
        # Text editor with line numbers
        self.editor_container = ctk.CTkFrame(self.editor_frame)
        self.editor_container.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.editor_container.grid_rowconfigure(0, weight=1)
        self.editor_container.grid_columnconfigure(1, weight=1)
        
        # Line numbers
        self.line_numbers = tk.Text(self.editor_container, width=4, padx=3, takefocus=0,
                                  border=0, state='disabled', wrap='none', background='#2b2b2b',
                                  foreground='#666666', font=('Consolas', 11))
        self.line_numbers.grid(row=0, column=0, sticky="nsew")
        
        # Code editor
        self.code_editor = tk.Text(self.editor_container, wrap="none", undo=True,
                                 font=('Consolas', 11), background='#1e1e1e', 
                                 foreground='#ffffff', insertbackground='white',
                                 selectbackground='#404040')
        self.code_editor.grid(row=0, column=1, sticky="nsew")
        
        # Scrollbars
        v_scrollbar = tk.Scrollbar(self.editor_container, orient="vertical")
        v_scrollbar.grid(row=0, column=2, sticky="ns")
        v_scrollbar.config(command=self.on_scrollbar)
        
        h_scrollbar = tk.Scrollbar(self.editor_container, orient="horizontal")
        h_scrollbar.grid(row=1, column=1, sticky="ew")
        h_scrollbar.config(command=self.code_editor.xview)
        
        self.code_editor.config(yscrollcommand=self.on_textscroll, xscrollcommand=h_scrollbar.set)
        
        # Syntax highlighting setup
        self.setup_syntax_highlighting()
        
        # Bind editor events
        self.code_editor.bind('<KeyRelease>', self.on_key_release)
        self.code_editor.bind('<Button-1>', self.on_click)
        self.code_editor.bind('<MouseWheel>', self.on_mousewheel)
    
    def create_output_area(self):
        """Create the output area with tabs"""
        self.output_frame = ctk.CTkFrame(self.v_paned)
        self.output_frame.grid(row=1, column=0, sticky="nsew")
        
        # Output notebook
        self.output_notebook = ctk.CTkTabview(self.output_frame)
        self.output_notebook.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Output tab
        self.output_tab = self.output_notebook.add("Output")
        self.output_text = ctk.CTkTextbox(self.output_tab, font=('Consolas', 10))
        self.output_text.pack(fill="both", expand=True)
        
        # Console tab (interactive Python shell)
        self.console_tab = self.output_notebook.add("Console")
        self.create_console()
        
        # Problems tab
        self.problems_tab = self.output_notebook.add("Problems")
        self.problems_text = ctk.CTkTextbox(self.problems_tab, font=('Consolas', 10))
        self.problems_text.pack(fill="both", expand=True)
    
    def create_console(self):
        """Create an interactive Python console"""
        console_frame = ctk.CTkFrame(self.console_tab)
        console_frame.pack(fill="both", expand=True)
        console_frame.grid_rowconfigure(0, weight=1)
        console_frame.grid_columnconfigure(0, weight=1)
        
        # Console output
        self.console_output = ctk.CTkTextbox(console_frame)
        self.console_output.grid(row=0, column=0, sticky="nsew", padx=5, pady=(5, 0))
        
        # Console input
        self.console_input = ctk.CTkEntry(console_frame, placeholder_text=">>> Enter Python code here")
        self.console_input.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        self.console_input.bind('<Return>', self.execute_console_command)
        
        # Welcome message
        self.console_output.insert("1.0", "PyGUIde Interactive Console\n")
        self.console_output.insert("end", "Python " + sys.version + "\n")
        self.console_output.insert("end", ">>> ")
    
    def create_status_bar(self):
        """Create the status bar"""
        self.status_bar = ctk.CTkFrame(self.root, height=25)
        self.status_bar.pack(side="bottom", fill="x", padx=5, pady=(0, 5))
        
        self.status_label = ctk.CTkLabel(self.status_bar, text="Ready")
        self.status_label.pack(side="left", padx=10)
        
        # Environment indicator
        self.env_indicator = ctk.CTkLabel(self.status_bar, text="Global Python")
        self.env_indicator.pack(side="left", padx=20)
        
        # Cursor position
        self.cursor_label = ctk.CTkLabel(self.status_bar, text="Line: 1, Col: 1")
        self.cursor_label.pack(side="right", padx=10)
    
    def setup_syntax_highlighting(self):
        """Setup basic syntax highlighting"""
        # Define color schemes
        self.code_editor.tag_configure("keyword", foreground="#569cd6")
        self.code_editor.tag_configure("string", foreground="#ce9178")
        self.code_editor.tag_configure("comment", foreground="#6a9955")
        self.code_editor.tag_configure("number", foreground="#b5cea8")
        self.code_editor.tag_configure("function", foreground="#dcdcaa")
        
        # Python keywords
        self.keywords = ["def", "class", "if", "elif", "else", "while", "for", "try", 
                        "except", "finally", "with", "as", "import", "from", "return", 
                        "yield", "lambda", "and", "or", "not", "in", "is", "True", 
                        "False", "None", "pass", "break", "continue", "global", "nonlocal"]
    
    def highlight_syntax(self):
        """Apply syntax highlighting to the current text"""
        content = self.code_editor.get("1.0", "end-1c")
        
        # Clear existing tags
        for tag in ["keyword", "string", "comment", "number", "function"]:
            self.code_editor.tag_remove(tag, "1.0", "end")
        
        # Highlight keywords
        for keyword in self.keywords:
            start = "1.0"
            while True:
                pos = self.code_editor.search(r'\b' + keyword + r'\b', start, "end", regexp=True)
                if not pos:
                    break
                end = f"{pos}+{len(keyword)}c"
                self.code_editor.tag_add("keyword", pos, end)
                start = end
        
        # Highlight strings
        for quote in ['"', "'"]:
            start = "1.0"
            while True:
                start_pos = self.code_editor.search(quote, start, "end")
                if not start_pos:
                    break
                end_pos = self.code_editor.search(quote, f"{start_pos}+1c", "end")
                if not end_pos:
                    break
                self.code_editor.tag_add("string", start_pos, f"{end_pos}+1c")
                start = f"{end_pos}+1c"
        
        # Highlight comments
        start = "1.0"
        while True:
            pos = self.code_editor.search("#", start, "end")
            if not pos:
                break
            line_end = self.code_editor.search("\n", pos, "end")
            if not line_end:
                line_end = "end"
            self.code_editor.tag_add("comment", pos, line_end)
            start = line_end
        
        # Highlight numbers
        start = "1.0"
        while True:
            pos = self.code_editor.search(r'\b\d+\.?\d*\b', start, "end", regexp=True)
            if not pos:
                break
            # Find the end of the number
            end = pos
            while True:
                char = self.code_editor.get(end)
                if char.isdigit() or char == '.':
                    end = f"{end}+1c"
                else:
                    break
            self.code_editor.tag_add("number", pos, end)
            start = end
    
    def update_line_numbers(self):
        """Update line numbers"""
        content = self.code_editor.get("1.0", "end-1c")
        line_count = content.count('\n') + 1
        
        line_numbers_string = "\n".join(str(i) for i in range(1, line_count + 1))
        
        self.line_numbers.config(state='normal')
        self.line_numbers.delete("1.0", "end")
        self.line_numbers.insert("1.0", line_numbers_string)
        self.line_numbers.config(state='disabled')
    
    def on_scrollbar(self, *args):
        """Handle scrollbar events"""
        self.code_editor.yview(*args)
        self.line_numbers.yview(*args)
    
    def on_textscroll(self, *args):
        """Handle text scroll events"""
        self.line_numbers.yview_moveto(args[0])
        self.code_editor.yview_moveto(args[0])
        return "break"
    
    def on_mousewheel(self, event):
        """Handle mouse wheel events"""
        self.on_scrollbar('scroll', int(-1 * (event.delta / 120)), "units")
        return "break"
    
    def on_key_release(self, event):
        """Handle key release events"""
        self.highlight_syntax()
        self.update_line_numbers()
        self.update_cursor_position()
        
        # Auto-analyze code on changes
        if len(self.code_editor.get("1.0", "end-1c")) > 10:
            self.root.after(2000, self.analyze_current_code)  # Delay analysis
            self.root.after(3000, self.refresh_dependencies)  # Delay dependency refresh
    
    def on_click(self, event):
        """Handle click events"""
        self.update_cursor_position()
    
    def update_cursor_position(self):
        """Update cursor position in status bar"""
        cursor_pos = self.code_editor.index(tk.INSERT)
        line, col = cursor_pos.split('.')
        self.cursor_label.configure(text=f"Line: {line}, Col: {int(col)+1}")
    
    def bind_events(self):
        """Bind keyboard shortcuts"""
        self.root.bind('<Control-n>', lambda e: self.new_file())
        self.root.bind('<Control-o>', lambda e: self.open_file())
        self.root.bind('<Control-Shift-O>', lambda e: self.open_folder())
        self.root.bind('<Control-s>', lambda e: self.save_file())
        self.root.bind('<Control-Shift-S>', lambda e: self.save_as_file())
        self.root.bind('<F5>', lambda e: self.run_code())
        self.root.bind('<Control-f>', lambda e: self.find_text())
        self.root.bind('<Control-h>', lambda e: self.replace_text())
        self.root.bind('<Control-z>', lambda e: self.undo())
        self.root.bind('<Control-y>', lambda e: self.redo())
    
    def open_folder(self):
        """Open a folder as a project"""
        folder_path = filedialog.askdirectory(title="Select Project Folder")
        if folder_path:
            self.project_path = folder_path
            self.dependency_manager = DependencyManager(folder_path)
            
            # Update UI
            self.project_path_label.configure(text=f"Project: {os.path.basename(folder_path)}")
            self.update_environment_indicator()
            
            # Change to project directory
            os.chdir(folder_path)
            self.refresh_file_list()
            self.refresh_dependencies()
            
            self.set_status(f"Opened project: {folder_path}")
    
    def update_environment_indicator(self):
        """Update the environment indicator in status bar and dependencies panel"""
        if self.dependency_manager.venv_path:
            venv_name = os.path.basename(self.dependency_manager.venv_path)
            env_text = f"Venv: {venv_name}"
            self.env_indicator.configure(text=env_text)
            self.env_label.configure(text=f"Environment: {venv_name} (Venv)")
        else:
            env_text = "Global Python"
            self.env_indicator.configure(text=env_text)
            self.env_label.configure(text=f"Environment: Global")
    
    def create_venv(self):
        """Create a virtual environment for the project"""
        if not self.project_path:
            messagebox.showerror("Error", "Please open a project folder first")
            return
        
        if self.dependency_manager.venv_path:
            messagebox.showinfo("Info", "Virtual environment already exists")
            return
        
        # Ask for venv name
        dialog = ctk.CTkInputDialog(text="Enter virtual environment name: (e.g. venv)", title="Create Virtual Environment:")
        venv_name = dialog.get_input()

        if not venv_name:
            return
        
        try:
            self.set_status("Creating virtual environment...")
            self.output_text.delete("1.0", "end")
            self.output_text.insert("1.0", f"Creating virtual environment '{venv_name}'...\n")
            
            # Create venv in separate thread
            def create_venv_thread():
                try:
                    self.dependency_manager.create_venv(venv_name)
                    self.root.after(0, lambda: self.on_venv_created(venv_name))
                except Exception as e:
                    self.root.after(0, lambda: self.on_venv_error(str(e)))
            
            threading.Thread(target=create_venv_thread, daemon=True).start()
            
        except Exception as e:
            messagebox.showerror("Error", f"Could not create virtual environment: {str(e)}")
    
    def on_venv_created(self, venv_name):
        """Called when venv is successfully created"""
        self.output_text.insert("end", f"Virtual environment '{venv_name}' created successfully!\n")
        self.output_text.insert("end", f"Python executable: {self.dependency_manager.python_executable}\n")
        
        self.update_environment_indicator()
        self.refresh_dependencies()
        self.set_status("Virtual environment created successfully")
        
        messagebox.showinfo("Success", f"Virtual environment '{venv_name}' created successfully!")
    
    def on_venv_error(self, error_msg):
        """Called when venv creation fails"""
        self.output_text.insert("end", f"Error creating virtual environment: {error_msg}\n")
        self.set_status("Failed to create virtual environment")
        messagebox.showerror("Error", f"Could not create virtual environment: {error_msg}")
    
    def get_project_python_files(self):
        """Get a list of all python files in the project, excluding virtual environments."""
        python_files = []
        if self.project_path:
            # Define directories to exclude from the scan
            exclude_dirs = {'.git', '__pycache__', 'build', 'dist', '.vscode', 'venv', 'env', '.venv', '.env'}
            if self.dependency_manager and self.dependency_manager.venv_path:
                exclude_dirs.add(os.path.basename(self.dependency_manager.venv_path))

            for root, dirs, files in os.walk(self.project_path, topdown=True):
                # This modifies the list in-place, preventing os.walk from entering excluded folders
                dirs[:] = [d for d in dirs if d not in exclude_dirs]
                
                for file in files:
                    if file.endswith('.py'):
                        python_files.append(os.path.join(root, file))
        elif self.current_file and self.current_file.endswith('.py'):
            python_files.append(self.current_file)
        
        return python_files

    def refresh_dependencies(self):
        """Refresh the dependencies list by analyzing only project source files."""
        if not hasattr(self, 'deps_list'):
            return
            
        # Clear existing dependency widgets
        for widget in self.deps_list.winfo_children():
            widget.destroy()
        
        python_files = self.get_project_python_files()
        
        if not python_files:
            no_files_label = ctk.CTkLabel(self.deps_list, text="No Python files to analyze.")
            no_files_label.pack(pady=10)
            return
        
        # Analyze imports from project files
        imports = self.dependency_manager.analyze_imports(python_files)
        missing_packages = self.dependency_manager.get_missing_packages(imports)
        installed_packages = self.dependency_manager.get_installed_packages()
        
        # Combine all relevant packages for display
        all_deps = sorted(imports.union(set(installed_packages.keys())))

        # Display dependencies
        for dep in all_deps:
            if self.dependency_manager.is_standard_library(dep):
                continue

            dep_frame = ctk.CTkFrame(self.deps_list)
            dep_frame.pack(fill="x", padx=5, pady=2)
            
            # Package name
            name_label = ctk.CTkLabel(dep_frame, text=dep, anchor="w")
            name_label.pack(side="left", padx=10, pady=5)
            
            # Status
            if dep in missing_packages:
                status_label = ctk.CTkLabel(dep_frame, text="Missing", 
                                          text_color="#F96666", font=ctk.CTkFont(weight="bold"))
                # Install button
                install_btn = ctk.CTkButton(dep_frame, text="Install", width=60,
                                          command=lambda pkg=dep: self.install_package(pkg))
                install_btn.pack(side="right", padx=5, pady=2)
            else:
                version = installed_packages.get(dep.lower(), "Installed")
                status_label = ctk.CTkLabel(dep_frame, text=f"v{version}", 
                                          text_color="#50C878")
            
            status_label.pack(side="right", padx=10, pady=5)
        
        # Update install all button state
        if missing_packages:
            self.install_all_btn.configure(state="normal", text=f"Install {len(missing_packages)} Missing")
        else:
            self.install_all_btn.configure(state="disabled", text="All Dependencies Met")
    
    def install_package(self, package):
        """Install a single package"""
        def install_thread():
            def output_callback(line):
                self.root.after(0, lambda: self.output_text.insert("end", line))
            
            self.root.after(0, lambda: self.output_text.delete("1.0", "end"))
            self.root.after(0, lambda: self.output_text.insert("1.0", f"Installing {package}...\n"))
            self.root.after(0, lambda: self.set_status(f"Installing {package}..."))
            
            success = self.dependency_manager.install_packages([package], output_callback)
            
            if success:
                self.root.after(0, lambda: self.output_text.insert("end", f"\n{package} installed successfully!\n"))
                self.root.after(0, lambda: self.set_status(f"{package} installed successfully"))
                self.root.after(0, self.refresh_dependencies)
            else:
                self.root.after(0, lambda: self.output_text.insert("end", f"\nFailed to install {package}!\n"))
                self.root.after(0, lambda: self.set_status(f"Failed to install {package}"))
        
        threading.Thread(target=install_thread, daemon=True).start()
    
    def install_missing_packages(self):
        """Install all missing packages"""
        python_files = self.get_project_python_files()
        
        if not python_files:
            messagebox.showwarning("Warning", "No Python files found to analyze.")
            return
        
        imports = self.dependency_manager.analyze_imports(python_files)
        missing_packages = self.dependency_manager.get_missing_packages(imports)
        
        if not missing_packages:
            messagebox.showinfo("Info", "All required dependencies are already installed.")
            return
        
        # Confirm installation
        result = messagebox.askyesno("Install Packages", 
                                   f"Install {len(missing_packages)} missing packages?\n\n" +
                                   ", ".join(missing_packages))
        if not result:
            return
        
        def install_thread():
            def output_callback(line):
                self.root.after(0, lambda: self.output_text.insert("end", line))
                self.root.after(0, lambda: self.output_text.see("end"))
            
            self.root.after(0, lambda: self.output_text.delete("1.0", "end"))
            self.root.after(0, lambda: self.output_text.insert("1.0", f"Installing {len(missing_packages)} packages...\n"))
            self.root.after(0, lambda: self.set_status("Installing packages..."))
            
            success = self.dependency_manager.install_packages(missing_packages, output_callback)
            
            if success:
                self.root.after(0, lambda: self.output_text.insert("end", f"\nAll packages installed successfully!\n"))
                self.root.after(0, lambda: self.set_status("All packages installed successfully"))
                self.root.after(0, self.refresh_dependencies)
            else:
                self.root.after(0, lambda: self.output_text.insert("end", f"\nSome packages failed to install! Check the output for details.\n"))
                self.root.after(0, lambda: self.set_status("Some packages failed to install"))
        
        threading.Thread(target=install_thread, daemon=True).start()
    
    def new_file(self):
        """Create a new file"""
        if self.check_unsaved_changes():
            self.code_editor.delete("1.0", "end")
            self.current_file = None
            self.file_label.configure(text="Untitled.py")
            self.update_line_numbers()
            self.set_status("New file created")
    
    def open_file(self):
        """Open a file"""
        if self.check_unsaved_changes():
            initial_dir = self.project_path if self.project_path else os.getcwd()
            file_path = filedialog.askopenfilename(
                title="Open Python File",
                initialdir=initial_dir,
                filetypes=[("Python files", "*.py"), ("All files", "*.*")]
            )
            if file_path:
                try:
                    with open(file_path, 'r', encoding='utf-8') as file:
                        content = file.read()
                    
                    self.code_editor.delete("1.0", "end")
                    self.code_editor.insert("1.0", content)
                    self.current_file = file_path
                    self.file_label.configure(text=os.path.basename(file_path))
                    self.highlight_syntax()
                    self.update_line_numbers()
                    self.set_status(f"Opened: {file_path}")
                    
                    # Analyze dependencies if part of project
                    self.root.after(1000, self.refresh_dependencies)
                    
                except Exception as e:
                    messagebox.showerror("Error", f"Could not open file: {str(e)}")
    
    def save_file(self):
        """Save the current file"""
        if self.current_file:
            try:
                content = self.code_editor.get("1.0", "end-1c")
                with open(self.current_file, 'w', encoding='utf-8') as file:
                    file.write(content)
                self.set_status(f"Saved: {self.current_file}")
                # Refresh dependencies after saving
                self.root.after(500, self.refresh_dependencies)
            except Exception as e:
                messagebox.showerror("Error", f"Could not save file: {str(e)}")
        else:
            self.save_as_file()
    
    def save_as_file(self):
        """Save file with a new name"""
        initial_dir = self.project_path if self.project_path else os.getcwd()
        file_path = filedialog.asksaveasfilename(
            title="Save Python File",
            initialdir=initial_dir,
            defaultextension=".py",
            filetypes=[("Python files", "*.py"), ("All files", "*.*")]
        )
        if file_path:
            try:
                content = self.code_editor.get("1.0", "end-1c")
                with open(file_path, 'w', encoding='utf-8') as file:
                    file.write(content)
                self.current_file = file_path
                self.file_label.configure(text=os.path.basename(file_path))
                self.set_status(f"Saved as: {file_path}")
                # Refresh dependencies after saving
                self.root.after(500, self.refresh_dependencies)
            except Exception as e:
                messagebox.showerror("Error", f"Could not save file: {str(e)}")
    
    def check_unsaved_changes(self):
        """Check if there are unsaved changes"""
        # Simplified - in a real implementation, you'd track modifications
        return True
    
    def run_code(self):
        """Run the current Python code"""
        code = self.code_editor.get("1.0", "end-1c")
        if not code.strip():
            self.set_status("No code to run")
            return
        
        # Clear output
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", f"Running code... ({datetime.now().strftime('%H:%M:%S')})\n")
        self.output_text.insert("end", "=" * 50 + "\n")
        
        # Save code to temporary file if needed
        temp_file = None
        if self.current_file:
            self.save_file() # Auto-save before running
            file_to_run = self.current_file
        else:
            import tempfile
            temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8')
            temp_file.write(code)
            temp_file.close()
            file_to_run = temp_file.name
        
        try:
            # Run code in separate thread
            def run_in_thread():
                try:
                    # Use the correct Python executable (venv or global)
                    python_exe = self.dependency_manager.python_executable
                    
                    # Create a subprocess to run the Python code
                    process = subprocess.Popen(
                        [python_exe, file_to_run],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        cwd=self.project_path if self.project_path else os.path.dirname(file_to_run),
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )
                    
                    stdout, stderr = process.communicate(timeout=30)  # 30 second timeout
                    
                    # Update output in main thread
                    self.root.after(0, lambda: self.update_output(stdout, stderr, process.returncode))
                    
                except subprocess.TimeoutExpired:
                    process.kill()
                    self.root.after(0, lambda: self.update_output("", "Error: Code execution timed out (30 seconds)", -1))
                except Exception as e:
                    self.root.after(0, lambda: self.update_output("", f"Error: {str(e)}", -1))
                finally:
                    if temp_file:
                        try:
                            os.unlink(temp_file.name)
                        except:
                            pass
            
            # Start execution thread
            self.execution_thread = threading.Thread(target=run_in_thread)
            self.execution_thread.daemon = True
            self.execution_thread.start()
            
            self.set_status("Code running...")
            
        except Exception as e:
            self.output_text.insert("end", f"Error starting execution: {str(e)}\n")
            if temp_file:
                try:
                    os.unlink(temp_file.name)
                except:
                    pass
    
    def update_output(self, stdout, stderr, return_code):
        """Update the output area with execution results"""
        self.output_text.insert("end", "\nOutput:\n")
        if stdout:
            self.output_text.insert("end", stdout)
        
        if stderr:
            self.output_text.insert("end", f"\nErrors:\n{stderr}")
        
        if return_code == 0:
            self.output_text.insert("end", f"\n\nExecution completed successfully.")
            self.set_status("Code executed successfully")
        else:
            self.output_text.insert("end", f"\n\nExecution failed with return code: {return_code}")
            self.set_status("Code execution failed")
        
        # Scroll to bottom
        self.output_text.see("end")
    
    def stop_execution(self):
        """Stop code execution"""
        # This is a simplified implementation
        self.set_status("Execution stopped")
        self.output_text.insert("end", "\n\n[Execution stopped by user]")
    
    def check_syntax(self):
        """Check Python syntax"""
        code = self.code_editor.get("1.0", "end-1c")
        self.problems_text.delete("1.0", "end")
        
        try:
            ast.parse(code)
            self.problems_text.insert("1.0", "✓ No syntax errors found!")
            self.set_status("Syntax check passed")
        except SyntaxError as e:
            error_msg = f"Syntax Error on line {e.lineno}:\n{e.msg}\n\n"
            if e.text:
                error_msg += f"Code: {e.text.strip()}\n"
                error_msg += " " * (e.offset - 1) + "^\n"
            self.problems_text.insert("1.0", error_msg)
            self.set_status("Syntax errors found")
            
            # Switch to problems tab
            self.output_notebook.set("Problems")
    
    def analyze_current_code(self):
        """Analyze the current code and update insights"""
        code = self.code_editor.get("1.0", "end-1c")
        if not code.strip():
            return
        
        insights = self.code_analyzer.analyze_code(code)
        
        # Clear and update insights
        self.insights_text.delete("1.0", "end")
        
        if 'syntax_error' in insights:
            self.insights_text.insert("1.0", f"Syntax Error: {insights['syntax_error']}\n\n")
        else:
            # Display analysis results
            analysis_text = f"Code Analysis Results:\n\n"
            analysis_text += f"Functions: {len(insights['functions'])}\n"
            analysis_text += f"Classes: {len(insights['classes'])}\n"
            analysis_text += f"Imports: {len(insights['imports'])}\n"
            analysis_text += f"Variables: {len(insights['variables'])}\n\n"
            
            if insights['functions']:
                analysis_text += "Functions found:\n"
                for func in insights['functions']:
                    analysis_text += f"  • {func['name']}() - line {func['line']} ({func['args']} args)\n"
                analysis_text += "\n"
            
            if insights['classes']:
                analysis_text += "Classes found:\n"
                for cls in insights['classes']:
                    analysis_text += f"  • {cls['name']} - line {cls['line']}\n"
                analysis_text += "\n"
            
            if insights['suggestions']:
                analysis_text += "Suggestions:\n"
                for suggestion in insights['suggestions']:
                    analysis_text += f"  • {suggestion}\n"
            
            self.insights_text.insert("1.0", analysis_text)
        
        # Update complexity meter
        complexity = min(insights['complexity_score'] / 20.0, 1.0)  # Normalize to 0-1
        self.complexity_progress.set(complexity)
    
    def insert_snippet(self, snippet_name):
        """Insert a code snippet at cursor position"""
        snippet_code = self.snippet_manager.snippets.get(snippet_name, "")
        if snippet_code:
            cursor_pos = self.code_editor.index(tk.INSERT)
            self.code_editor.insert(cursor_pos, snippet_code)
            self.highlight_syntax()
            self.update_line_numbers()
            self.set_status(f"Inserted snippet: {snippet_name}")
    
    def refresh_file_list(self):
        """Refresh the file explorer"""
        # Clear existing items
        for widget in self.file_list.winfo_children():
            widget.destroy()
        
        try:
            current_dir = self.project_path if self.project_path else os.getcwd()
            self.current_dir_label.configure(text=f"Current: {os.path.basename(current_dir)}")
            
            # Add parent directory option (only if not at project root)
            if self.project_path and current_dir != self.project_path:
                parent_btn = ctk.CTkButton(self.file_list, text=".. (Up)", 
                                         command=lambda: self.change_directory(".."),
                                         height=25, anchor="w")
                parent_btn.pack(fill="x", pady=1)
            
            # List directories and Python files
            items = []
            try:
                for item in os.listdir(current_dir):
                    if item.startswith('.'):  # Skip hidden files
                        continue
                        
                    item_path = os.path.join(current_dir, item)
                    if os.path.isdir(item_path):
                        # Highlight venv directory
                        if item in ['venv', 'env', '.venv', '.env']:
                            items.append(("[VENV] " + item, item_path, "venv"))
                        else:
                            items.append(("[DIR] " + item, item_path, "dir"))
                    elif item.endswith('.py'):
                        items.append(("[PY] " + item, item_path, "file"))
                    elif item.endswith(('.txt', '.md', '.json', '.xml', '.yml', '.yaml', '.cfg', '.ini')):
                        items.append(("[FILE] " + item, item_path, "file"))
                
                # Sort items (directories first, then files)
                items.sort(key=lambda x: (x[2] not in ["dir", "venv"], x[0].lower()))
                
                for display_name, full_path, item_type in items:
                    if item_type in ["dir", "venv"]:
                        btn = ctk.CTkButton(self.file_list, text=display_name,
                                          command=lambda p=full_path: self.change_directory(p),
                                          height=25, anchor="w")
                        if item_type == "venv":
                            btn.configure(fg_color="orange")
                    else:
                        btn = ctk.CTkButton(self.file_list, text=display_name,
                                          command=lambda p=full_path: self.open_file_from_explorer(p),
                                          height=25, anchor="w")
                    btn.pack(fill="x", pady=1)
                    
            except PermissionError:
                error_label = ctk.CTkLabel(self.file_list, text="Permission denied")
                error_label.pack(pady=10)
                
        except Exception as e:
            error_label = ctk.CTkLabel(self.file_list, text=f"Error: {str(e)}")
            error_label.pack(pady=10)
    
    def change_directory(self, path):
        """Change current directory"""
        try:
            if path == "..":
                new_dir = os.path.dirname(os.getcwd())
                # Don't go above project root if we have one
                if self.project_path and not new_dir.startswith(self.project_path):
                    return
                os.chdir(new_dir)
            else:
                os.chdir(path)
            self.refresh_file_list()
        except Exception as e:
            messagebox.showerror("Error", f"Could not change directory: {str(e)}")
    
    def open_file_from_explorer(self, file_path):
        """Open a file from the file explorer"""
        if self.check_unsaved_changes():
            try:
                with open(file_path, 'r', encoding='utf-8') as file:
                    content = file.read()
                
                self.code_editor.delete("1.0", "end")
                self.code_editor.insert("1.0", content)
                self.current_file = file_path
                self.file_label.configure(text=os.path.basename(file_path))
                self.highlight_syntax()
                self.update_line_numbers()
                self.set_status(f"Opened: {file_path}")
                
                # Analyze dependencies
                self.root.after(1000, self.refresh_dependencies)
                
            except Exception as e:
                messagebox.showerror("Error", f"Could not open file: {str(e)}")
    
    def execute_console_command(self, event):
        """Execute command in interactive console"""
        command = self.console_input.get().strip()
        if not command:
            return
        
        # Add command to console output
        self.console_output.insert("end", command + "\n")
        
        try:
            # Simple evaluation - in a real implementation, you'd want a proper Python REPL
            if command.startswith("print(") or "=" in command or command in ["help()", "exit()", "quit()"]:
                # Handle special cases
                if command in ["exit()", "quit()"]:
                    self.console_output.insert("end", "Use Ctrl+C to exit console\n")
                elif command == "help()":
                    self.console_output.insert("end", "PyGUIde Interactive Console Help\n")
                    self.console_output.insert("end", "Type Python expressions to evaluate them\n")
                else:
                    # Execute the command
                    try:
                        # Create a simple execution environment
                        exec_globals = {"__name__": "__main__"}
                        result = eval(command, exec_globals)
                        if result is not None:
                            self.console_output.insert("end", f"{result}\n")
                    except:
                        # Try exec for statements
                        exec(command, exec_globals)
            else:
                # Try to evaluate as expression
                result = eval(command)
                if result is not None:
                    self.console_output.insert("end", f"{result}\n")
                    
        except Exception as e:
            self.console_output.insert("end", f"Error: {str(e)}\n")
        
        self.console_output.insert("end", ">>> ")
        self.console_output.see("end")
        self.console_input.delete(0, "end")
    
    def find_text(self):
        """Open find dialog"""
        find_dialog = FindDialog(self.root, self.code_editor)
    
    def replace_text(self):
        """Open replace dialog"""
        replace_dialog = ReplaceDialog(self.root, self.code_editor)
    
    def undo(self):
        """Undo last action"""
        try:
            self.code_editor.edit_undo()
            self.highlight_syntax()
            self.update_line_numbers()
        except tk.TclError:
            pass
    
    def redo(self):
        """Redo last undone action"""
        try:
            self.code_editor.edit_redo()
            self.highlight_syntax()
            self.update_line_numbers()
        except tk.TclError:
            pass
    
    def toggle_theme(self):
        """Toggle between light and dark themes"""
        current_mode = ctk.get_appearance_mode()
        new_mode = "light" if current_mode == "dark" else "dark"
        ctk.set_appearance_mode(new_mode)
        
        # Update code editor colors
        if new_mode == "dark":
            self.code_editor.configure(background='#1e1e1e', foreground='#ffffff')
            self.line_numbers.configure(background='#2b2b2b', foreground='#666666')
        else:
            self.code_editor.configure(background='#ffffff', foreground='#000000')
            self.line_numbers.configure(background='#f0f0f0', foreground='#666666')
        
        self.highlight_syntax()
        self.set_status(f"Switched to {new_mode} mode")
    
    def toggle_sidebar(self):
        """Toggle sidebar visibility"""
        if self.sidebar.winfo_viewable():
            self.sidebar.grid_remove()
            self.set_status("Sidebar hidden")
        else:
            self.sidebar.grid()
            self.set_status("Sidebar shown")
    
    def show_about(self):
        """Show about dialog"""
        about_text = """PyGUIde - Interactive Python IDE

Version: 2.1.0
Created with CustomTkinter
Autor: LMLK-seal
Email: Yaniv.schwartz1@gmail.com

An educational Python development environment
designed to make coding more visual and interactive.

Features:
• Project-based workflow
• Virtual environment management
• Dependency analysis and installation
• Syntax highlighting
• Code analysis and insights
• Interactive console
• Code snippets
• File explorer
• Modern dark/light themes

Perfect for learning Python and rapid prototyping!"""
        
        messagebox.showinfo("About PyGUIde", about_text)
    
    def open_python_docs(self):
        """Open Python documentation"""
        import webbrowser
        webbrowser.open("https://docs.python.org/3/")
    
    def monitor_output_queue(self):
        """Monitor the output queue for updates"""
        try:
            while True:
                msg_type, content = self.output_queue.get_nowait()
                if msg_type == 'stdout':
                    self.output_text.insert("end", content)
                    self.output_text.see("end")
        except queue.Empty:
            pass
        
        # Schedule next check
        self.root.after(100, self.monitor_output_queue)
    
    def set_status(self, message):
        """Set status bar message"""
        self.status_label.configure(text=message)
        # Clear status after 5 seconds
        self.root.after(5000, lambda: self.status_label.configure(text="Ready"))
    
    def load_settings(self):
        """Load user settings"""
        # Simplified settings loading
        try:
            settings_file = Path.home() / ".pyguide_settings.json"
            if settings_file.exists():
                with open(settings_file, 'r') as f:
                    settings = json.load(f)
                    # Apply settings (theme, window size, etc.)
                    if 'last_project' in settings and os.path.exists(settings['last_project']):
                        # Optionally auto-open last project
                        pass
        except Exception:
            pass  # Use defaults if settings can't be loaded
    
    def save_settings(self):
        """Save user settings"""
        try:
            settings = {
                'theme': ctk.get_appearance_mode(),
                'window_geometry': self.root.geometry(),
                'last_directory': os.getcwd(),
                'last_project': self.project_path
            }
            settings_file = Path.home() / ".pyguide_settings.json"
            with open(settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception:
            pass  # Silently fail if settings can't be saved
    
    def on_closing(self):
        """Handle application closing"""
        if self.check_unsaved_changes():
            self.save_settings()
            self.root.destroy()
    
    def run(self):
        """Start the application"""
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()


class FindDialog:
    """Find text dialog"""
    
    def __init__(self, parent, text_widget):
        self.text_widget = text_widget
        self.dialog = ctk.CTkToplevel(parent)
        self.dialog.title("Find")
        self.dialog.geometry("300x100")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Find entry
        ctk.CTkLabel(self.dialog, text="Find:").pack(pady=5)
        self.find_entry = ctk.CTkEntry(self.dialog, width=250)
        self.find_entry.pack(pady=5)
        self.find_entry.focus()
        
        # Buttons
        button_frame = ctk.CTkFrame(self.dialog)
        button_frame.pack(pady=10)
        
        ctk.CTkButton(button_frame, text="Find Next", command=self.find_next).pack(side="left", padx=5)
        ctk.CTkButton(button_frame, text="Cancel", command=self.dialog.destroy).pack(side="left", padx=5)
        
        self.find_entry.bind('<Return>', lambda e: self.find_next())
        self.dialog.bind('<Escape>', lambda e: self.dialog.destroy())
    
    def find_next(self):
        """Find next occurrence"""
        search_text = self.find_entry.get()
        if search_text:
            start_pos = self.text_widget.search(search_text, tk.INSERT, "end")
            if start_pos:
                end_pos = f"{start_pos}+{len(search_text)}c"
                self.text_widget.tag_remove("sel", "1.0", "end")
                self.text_widget.tag_add("sel", start_pos, end_pos)
                self.text_widget.mark_set(tk.INSERT, end_pos)
                self.text_widget.see(start_pos)
            else:
                messagebox.showinfo("Find", "Text not found")


class ReplaceDialog:
    """Replace text dialog"""
    
    def __init__(self, parent, text_widget):
        self.text_widget = text_widget
        self.dialog = ctk.CTkToplevel(parent)
        self.dialog.title("Replace")
        self.dialog.geometry("300x150")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Find entry
        ctk.CTkLabel(self.dialog, text="Find:").pack(pady=2)
        self.find_entry = ctk.CTkEntry(self.dialog, width=250)
        self.find_entry.pack(pady=2)
        
        # Replace entry
        ctk.CTkLabel(self.dialog, text="Replace with:").pack(pady=2)
        self.replace_entry = ctk.CTkEntry(self.dialog, width=250)
        self.replace_entry.pack(pady=2)
        
        self.find_entry.focus()
        
        # Buttons
        button_frame = ctk.CTkFrame(self.dialog)
        button_frame.pack(pady=10)
        
        ctk.CTkButton(button_frame, text="Replace", command=self.replace_current).pack(side="left", padx=2)
        ctk.CTkButton(button_frame, text="Replace All", command=self.replace_all).pack(side="left", padx=2)
        ctk.CTkButton(button_frame, text="Cancel", command=self.dialog.destroy).pack(side="left", padx=2)
        
        self.dialog.bind('<Escape>', lambda e: self.dialog.destroy())
    
    def replace_current(self):
        """Replace current selection"""
        find_text = self.find_entry.get()
        replace_text = self.replace_entry.get()
        
        if find_text and self.text_widget.tag_ranges("sel"):
            self.text_widget.delete("sel.first", "sel.last")
            self.text_widget.insert(tk.INSERT, replace_text)
    
    def replace_all(self):
        """Replace all occurrences"""
        find_text = self.find_entry.get()
        replace_text = self.replace_entry.get()
        
        if find_text:
            content = self.text_widget.get("1.0", "end-1c")
            new_content = content.replace(find_text, replace_text)
            
            self.text_widget.delete("1.0", "end")
            self.text_widget.insert("1.0", new_content)
            
            count = content.count(find_text)
            messagebox.showinfo("Replace All", f"Replaced {count} occurrences")


if __name__ == "__main__":
    # Check if CustomTkinter is installed
    try:
        import customtkinter as ctk
    except ImportError:
        print("CustomTkinter is required to run PyGUIde.")
        print("Install it with: pip install customtkinter")
        sys.exit(1)
    
    # Create and run the application
    app = PyGUIde()
    app.run()
