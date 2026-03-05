"""
Code-Agent — Python Analyzer.
Uses Python's built-in AST module for precise code analysis.
"""

import ast
from pathlib import Path

import structlog

from src.core.analyzers.base import BaseAnalyzer
from src.models.domain import FileAnalysis, LanguageType

logger = structlog.get_logger()

# Infrastructure imports that indicate coupling
INFRA_IMPORTS = {
    # Database
    "psycopg2", "sqlalchemy", "pymongo", "redis", "asyncpg", "databases",
    "peewee", "tortoise", "motor",
    # AWS
    "boto3", "botocore", "dynamodb", "s3", "sqs", "sns", "lambda",
    # HTTP/Framework
    "fastapi", "flask", "django", "starlette", "sanic", "aiohttp",
    # Messaging
    "kafka", "pika", "celery", "kombu",
}

# Patterns in function calls that indicate DB access
DB_CALL_PATTERNS = {
    "execute", "query", "find", "insert", "update", "delete",
    "commit", "rollback", "fetchone", "fetchall", "fetchmany",
    "create", "save", "bulk_create", "get_or_create",
    "filter", "aggregate", "cursor", "session",
}

# Patterns that indicate external service calls
EXTERNAL_CALL_PATTERNS = {
    "requests.get", "requests.post", "requests.put", "requests.delete",
    "httpx.", "aiohttp.", "urllib",
    "boto3.client", "boto3.resource",
    "send_message", "publish", "put_object", "get_object",
    "invoke",
}


class PythonAnalyzer(BaseAnalyzer):
    """Analyzer for Python source files using AST."""

    @property
    def language(self) -> LanguageType:
        return LanguageType.PYTHON

    @property
    def extensions(self) -> list[str]:
        return [".py"]

    def analyze_file(self, file_path: str, project_root: str = "") -> FileAnalysis:
        """Analyze a Python file using AST parsing."""
        source = self._read_file(file_path)
        if not source:
            return self._empty_analysis(file_path, project_root)

        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError as e:
            logger.warning("python_parse_error", file=file_path, error=str(e))
            return self._empty_analysis(file_path, project_root)

        lines = source.splitlines()

        classes = self._extract_classes(tree)
        functions = self._extract_functions(tree)
        imports = self._extract_imports(tree)
        decorators = self._extract_decorators(tree)
        endpoints = self._detect_endpoints(tree, source)
        db_calls = self._detect_db_calls(tree, source)
        external_calls = self._detect_external_calls(source, imports)
        complexity = self._calc_complexity(tree)

        return FileAnalysis(
            file_path=self._relative_path(file_path, project_root),
            file_name=Path(file_path).name,
            language=LanguageType.PYTHON,
            total_lines=len(lines),
            classes=classes,
            functions=functions,
            imports=imports,
            decorators=decorators,
            api_endpoints=endpoints,
            database_calls=db_calls,
            external_calls=external_calls,
            complexity=complexity,
        )

    def _empty_analysis(self, file_path: str, project_root: str) -> FileAnalysis:
        return FileAnalysis(
            file_path=self._relative_path(file_path, project_root),
            file_name=Path(file_path).name,
            language=LanguageType.PYTHON,
        )

    # ── Extraction methods ──────────────────────────────────

    def _extract_classes(self, tree: ast.AST) -> list[str]:
        """Extract class names from the AST."""
        return [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]

    def _extract_functions(self, tree: ast.AST) -> list[str]:
        """Extract function names with class prefix if nested."""
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        functions.append(f"{node.name}.{item.name}")
        # Top-level functions
        if isinstance(tree, ast.Module):
            for item in tree.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append(item.name)
        return functions

    def _extract_imports(self, tree: ast.AST) -> list[str]:
        """Extract import module names."""
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        return imports

    def _extract_decorators(self, tree: ast.AST) -> list[str]:
        """Extract decorator names from classes and functions."""
        decorators = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name):
                        decorators.append(f"@{dec.id}")
                    elif isinstance(dec, ast.Attribute):
                        decorators.append(f"@{ast.dump(dec)}")
                    elif isinstance(dec, ast.Call):
                        if isinstance(dec.func, ast.Attribute):
                            parts = []
                            current = dec.func
                            while isinstance(current, ast.Attribute):
                                parts.append(current.attr)
                                current = current.value
                            if isinstance(current, ast.Name):
                                parts.append(current.id)
                            decorators.append(f"@{'.'.join(reversed(parts))}")
                        elif isinstance(dec.func, ast.Name):
                            decorators.append(f"@{dec.func.id}")
        return decorators

    def _detect_endpoints(self, tree: ast.AST, source: str) -> list[dict]:
        """Detect API endpoint decorators (FastAPI, Flask)."""
        endpoints = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    dec_str = ast.dump(dec).lower()
                    for method in ("get", "post", "put", "delete", "patch"):
                        if f"'{method}'" in dec_str or f'"{method}"' in dec_str or f".{method}" in dec_str:
                            # Try to extract the path from decorator args
                            path = self._extract_route_path(dec)
                            endpoints.append({
                                "method": method.upper(),
                                "path": path or f"/{node.name}",
                                "handler": node.name,
                            })
                            break
        return endpoints

    def _extract_route_path(self, decorator: ast.AST) -> str | None:
        """Try to extract route path from a decorator."""
        if isinstance(decorator, ast.Call) and decorator.args:
            first_arg = decorator.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                return first_arg.value
        return None

    def _detect_db_calls(self, tree: ast.AST, source: str) -> list[dict]:
        """Detect database operations by call patterns."""
        db_calls = []
        source_lower = source.lower()
        for pattern in DB_CALL_PATTERNS:
            if f".{pattern}(" in source_lower or f".{pattern} " in source_lower:
                db_calls.append({"tipo": pattern, "detected_by": "pattern_match"})
        return db_calls

    def _detect_external_calls(self, source: str, imports: list[str]) -> list[dict]:
        """Detect external service calls."""
        calls = []
        for imp in imports:
            imp_lower = imp.lower()
            if any(infra in imp_lower for infra in ("boto3", "botocore")):
                calls.append({"servicio": "AWS", "import": imp})
            elif any(infra in imp_lower for infra in ("requests", "httpx", "aiohttp")):
                calls.append({"servicio": "HTTP", "import": imp})
            elif any(infra in imp_lower for infra in ("kafka", "pika", "celery")):
                calls.append({"servicio": "Messaging", "import": imp})
        return calls

    def _calc_complexity(self, tree: ast.AST) -> int:
        """
        Calculate cyclomatic complexity for the entire file.
        CC = 1 + count of decision points (if, while, for, except, and, or, elif).
        """
        complexity = 1
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                # Each 'and'/'or' adds (n-1) to complexity
                complexity += len(node.values) - 1
            elif isinstance(node, ast.comprehension):
                complexity += 1  # list/dict/set comprehensions with conditions
                complexity += len(node.ifs)
        return complexity

    def get_function_details(self, file_path: str) -> list[dict]:
        """
        Get detailed info per function: name, start/end line, complexity, LOC, docstring.
        Used by logical_unit_extractor for per-function granularity.
        """
        source = self._read_file(file_path)
        if not source:
            return []

        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            return []

        details = []
        source_lines = source.splitlines()

        # Process classes and their methods
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                # Class itself
                class_end = self._get_end_line(node, source_lines)
                class_loc = class_end - node.lineno + 1
                details.append({
                    "name": node.name,
                    "type": "CLASE",
                    "parent": None,
                    "linea_inicio": node.lineno,
                    "linea_fin": class_end,
                    "lineas_codigo": class_loc,
                    "complejidad": self._node_complexity(node),
                    "docstring": ast.get_docstring(node) is not None,
                })
                # Methods inside class
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        func_end = self._get_end_line(item, source_lines)
                        func_loc = func_end - item.lineno + 1
                        details.append({
                            "name": item.name,
                            "type": "FUNCION",
                            "parent": node.name,
                            "linea_inicio": item.lineno,
                            "linea_fin": func_end,
                            "lineas_codigo": func_loc,
                            "complejidad": self._node_complexity(item),
                            "docstring": ast.get_docstring(item) is not None,
                        })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Top-level function
                func_end = self._get_end_line(node, source_lines)
                func_loc = func_end - node.lineno + 1
                details.append({
                    "name": node.name,
                    "type": "FUNCION",
                    "parent": None,
                    "linea_inicio": node.lineno,
                    "linea_fin": func_end,
                    "lineas_codigo": func_loc,
                    "complejidad": self._node_complexity(node),
                    "docstring": ast.get_docstring(node) is not None,
                })

        return details

    def _get_end_line(self, node: ast.AST, source_lines: list[str]) -> int:
        """Get end line of a node. Uses end_lineno (Python 3.8+)."""
        if hasattr(node, "end_lineno") and node.end_lineno:
            return node.end_lineno
        # Fallback: estimate from body
        max_line = node.lineno
        for child in ast.walk(node):
            if hasattr(child, "lineno"):
                max_line = max(max_line, child.lineno)
        return max_line

    def _node_complexity(self, node: ast.AST) -> int:
        """Calculate CC for a single function/class."""
        cc = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                cc += 1
            elif isinstance(child, ast.BoolOp):
                cc += len(child.values) - 1
            elif isinstance(child, ast.comprehension):
                cc += 1 + len(child.ifs)
        return cc
